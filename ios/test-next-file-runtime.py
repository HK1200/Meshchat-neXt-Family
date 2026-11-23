"""RNCP uses its own storage, explicit identities and actual cancellation."""
import asyncio
import importlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ['NEXT_TEST_BACKEND_SOURCE']).resolve()
sys.path[:0] = [str(ROOT / 'ios/NextRuntimeProbe'), str(BACKEND)]
import file_runtime as module

ADDRESS = 'ab' * 16
IDENTITY = bytes.fromhex('cd' * 16)


def runtime(tmp_path, monkeypatch=None):
    return module.FileRuntime(SimpleNamespace(reticulum=object(), source=SimpleNamespace(identity=object())),
                              tmp_path / 'rncp', lambda address: address == 'ff' * 16, AsyncMock())


async def with_client(value, operation):
    app = web.Application()
    value.register(app.router)
    async with TestClient(TestServer(app)) as client:
        try: return await operation(client)
        finally: await value.close()


@pytest.mark.parametrize('bad', [None, '', '../private', 'g' * 32, 'aa' * 15, True])
def test_invalid_destination_never_starts_a_transfer(tmp_path, bad):
    async def run():
        value = runtime(tmp_path)
        value.handler.send_file = AsyncMock()
        file = value.shared / 'chosen.txt'; file.write_bytes(b'chosen')
        async def check(client):
            response = await client.post('/api/v1/rncp/send', json={'destination_hash': bad, 'file_path': str(file)})
            assert response.status == 400
            value.handler.send_file.assert_not_awaited()
        await with_client(value, check)
    asyncio.run(run())


@pytest.mark.parametrize('bad', [True, False, 0, -1, 601, 'nan', 'inf', [], {}])
def test_invalid_timeout_never_starts_a_transfer(tmp_path, bad):
    async def run():
        value = runtime(tmp_path); value.handler.send_file = AsyncMock()
        file = value.shared / 'chosen.txt'; file.write_bytes(b'chosen')
        async def check(client):
            response = await client.post('/api/v1/rncp/send', json={'destination_hash': ADDRESS, 'file_path': str(file), 'timeout': bad})
            assert response.status == 400
            value.handler.send_file.assert_not_awaited()
        await with_client(value, check)
    asyncio.run(run())


def test_local_paths_reject_private_data_and_escaping_symlinks(tmp_path):
    async def run():
        value = runtime(tmp_path)
        private = tmp_path / 'identity'; private.write_bytes(b'private')
        (value.shared / 'escape').symlink_to(private)
        value.handler.send_file = AsyncMock()
        value.handler.fetch_file = AsyncMock()
        async def check(client):
            for path in (str(private), str(value.shared / 'escape'), '../identity', str(tmp_path)):
                response = await client.post('/api/v1/rncp/send', json={'destination_hash': ADDRESS, 'file_path': path})
                assert response.status == 400
            response = await client.post('/api/v1/rncp/fetch', json={'destination_hash': ADDRESS, 'file_path': 'remote.txt', 'save_path': str(tmp_path)})
            assert response.status == 400
            value.handler.send_file.assert_not_awaited(); value.handler.fetch_file.assert_not_awaited()
            assert private.read_bytes() == b'private'
        await with_client(value, check)
    asyncio.run(run())


def test_selected_upload_keeps_name_bytes_and_does_not_overwrite(tmp_path):
    async def run():
        value = runtime(tmp_path)
        async def check(client):
            paths = []
            for payload in (b'first', b'second'):
                form = FormData(); form.add_field('file', payload, filename='photo.png', content_type='application/octet-stream')
                response = await client.post('/api/v1/preview/rncp/upload', data=form)
                assert response.status == 200
                result = await response.json(); path = Path(result['file_path'])
                assert path.name == 'photo.png' and path.read_bytes() == payload
                assert path.stat().st_mode & 0o777 == 0o600
                assert path.is_relative_to(value.shared); paths.append(path)
            assert paths[0] != paths[1] and paths[0].read_bytes() == b'first'
            value.handler.send_file = AsyncMock(return_value={'status': 'completed', 'transfer_id': 'aa' * 32})
            response = await client.post('/api/v1/rncp/send', json={'destination_hash': ADDRESS, 'file_path': str(paths[0]), 'timeout': 30})
            assert response.status == 200
            assert value.handler.send_file.await_args.kwargs['file_path'] == str(paths[0])
        await with_client(value, check)
    asyncio.run(run())


def test_failed_or_multi_file_upload_does_not_leave_partial_data(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'MAX_FILE', 4)
    async def run():
        value = runtime(tmp_path)
        async def check(client):
            form = FormData(); form.add_field('file', b'12345', filename='large.txt')
            assert (await client.post('/api/v1/preview/rncp/upload', data=form)).status == 400
            form = FormData(); form.add_field('file', b'123', filename='one.txt'); form.add_field('file', b'456', filename='two.txt')
            assert (await client.post('/api/v1/preview/rncp/upload', data=form)).status == 400
            assert list(value.shared.iterdir()) == []
        await with_client(value, check)
    asyncio.run(run())


def test_listener_rejects_unapproved_identity_shapes_and_bad_paths(tmp_path):
    async def run():
        value = runtime(tmp_path); value.handler.setup_receive_destination = lambda **kwargs: pytest.fail('Listener must not start')
        async def check(client):
            for data in ({'allowed_hashes': ['invalid']}, {'allowed_hashes': ['ff' * 16]}, {'allowed_hashes': [ADDRESS] * 101},
                         {'fetch_allowed': 'true'}, {'fetch_jail': str(tmp_path)}):
                assert (await client.post('/api/v1/rncp/listen', json=data)).status == 400
            assert (await client.get('/api/v1/rncp/status')).status == 200
            assert (await client.get('/api/v1/rncp/listen')).status == 405
        await with_client(value, check)
    asyncio.run(run())


def test_cancel_stops_the_resource_before_its_reference_is_dropped(tmp_path):
    async def run():
        value = runtime(tmp_path); calls = []
        resource = SimpleNamespace(cancel=lambda: calls.append('cancelled'))
        value.handler.active_transfers['aa' * 32] = {'status': 'sending', 'resource': resource}
        assert value.cancel('aa' * 32) == {'cancelled': ['aa' * 32]}
        assert calls == ['cancelled'] and value.handler.active_transfers['aa' * 32]['status'] == 'cancelled'
        await value.close()
    asyncio.run(run())


def test_reception_checks_current_approval_capacity_and_cancel_before_saving(tmp_path, monkeypatch):
    finished = []
    monkeypatch.setattr(module.RNCPHandler, '_receive_resource_concluded', lambda self, resource: finished.append(resource.hash))
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=module.RESERVE + 100))
    async def run():
        value = runtime(tmp_path); value.handler.allowed_identity_hashes = [IDENTITY]
        link = SimpleNamespace(get_remote_identity=lambda: SimpleNamespace(hash=IDENTITY))
        def advert(key, size=20): return SimpleNamespace(link=link, get_data_size=lambda: size, get_hash=lambda: key)
        assert value.handler._receive_resource_callback(advert(b'a' * 32))
        assert value.handler._receive_resource_callback(advert(b'b' * 32))
        assert not value.handler._receive_resource_callback(advert(b'c' * 32))
        assert not value.handler._receive_resource_callback(advert(b'a' * 32))
        value.handler.cancel_transfer((b'a' * 32).hex())
        value.handler._receive_resource_concluded(SimpleNamespace(link=link, hash=b'a' * 32))
        assert finished == []
        value.handler._receive_resource_concluded(SimpleNamespace(link=link, hash=b'b' * 32))
        assert finished == [b'b' * 32]
        assert value.reservations == {}
        await value.close()
        assert not value.handler._receive_resource_callback(advert(b'c' * 32))
    asyncio.run(run())


def test_export_serves_only_received_files_and_no_external_symlinks(tmp_path):
    async def run():
        value = runtime(tmp_path)
        private = tmp_path / 'private'; private.write_bytes(b'not shared')
        (value.received / 'escaped').symlink_to(private)
        (value.received / 'reply.txt').write_bytes(b'actual received bytes')
        async def check(client):
            listing = await (await client.get('/api/v1/preview/rncp/files')).json()
            assert [row['name'] for row in listing['files']] == ['reply.txt']
            response = await client.get('/api/v1/preview/rncp/files/' + listing['files'][0]['id'] + '/download')
            assert response.status == 200 and await response.read() == b'actual received bytes'
            assert 'attachment' in response.headers['Content-Disposition']
            assert (await client.get('/api/v1/preview/rncp/files/' + '0' * 32 + '/download')).status == 404
        await with_client(value, check)
    asyncio.run(run())


def test_cancel_all_stops_path_waits_and_preserves_completed_records(tmp_path):
    async def run():
        value = runtime(tmp_path); entered = asyncio.Event(); stopped = asyncio.Event()
        file = value.shared / 'chosen'; file.write_bytes(b'data')
        async def waiting(**kwargs):
            entered.set()
            try: await asyncio.Future()
            finally: stopped.set()
        value.handler.send_file = waiting
        value.handler.active_transfers['bb' * 32] = {'status': 'completed'}
        async def check(client):
            operation = asyncio.create_task(client.post('/api/v1/rncp/send', json={'destination_hash': ADDRESS, 'file_path': str(file)}))
            await asyncio.wait_for(entered.wait(), 2)
            response = await client.post('/api/v1/rncp/cancel', json={})
            result = await response.json()
            assert response.status == 200 and result['pending_cancelled'] == 1
            response = await asyncio.wait_for(operation, 2)
            assert response.status == 409
            assert stopped.is_set() and value.slots._value == 2 and not value.transfers
            assert value.handler.active_transfers['bb' * 32]['status'] == 'completed'
        await with_client(value, check)
    asyncio.run(run())


def test_shutdown_cancels_and_releases_in_flight_requests(tmp_path):
    async def run():
        from aiohttp import ClientConnectionError
        value = runtime(tmp_path); entered = asyncio.Event(); stopped = asyncio.Event()
        file = value.shared / 'chosen'; file.write_bytes(b'data')
        async def waiting(**kwargs):
            entered.set()
            try: await asyncio.Future()
            finally: stopped.set()
        value.handler.send_file = waiting
        app = web.Application(); value.register(app.router)
        async with TestClient(TestServer(app)) as client:
            operation = asyncio.create_task(client.post('/api/v1/rncp/send', json={'destination_hash': ADDRESS, 'file_path': str(file)}))
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.wait_for(value.close(), 2)
            with pytest.raises(ClientConnectionError): await asyncio.wait_for(operation, 2)
            assert stopped.is_set() and value.slots._value == 2 and not value.pending and not value.transfers
            assert (await client.post('/api/v1/rncp/listen', json={})).status == 503
    asyncio.run(run())


def test_fetch_guard_rejects_changed_engine_and_keeps_private_namespaces(tmp_path):
    import inspect
    import mobile_rncp_guard
    async def run():
        first = runtime(tmp_path / 'one'); second = runtime(tmp_path / 'two')
        assert first.handler.fetch_file.__func__.__globals__ is not second.handler.fetch_file.__func__.__globals__
        source = inspect.getsource(module.RNCPHandler.fetch_file)
        for changed in (source + '\n', source.replace('ACCEPT_ALL', 'ACCEPT_APP')):
            with pytest.raises(ValueError): mobile_rncp_guard.guarded_source(changed)
        with pytest.raises(ValueError): mobile_rncp_guard.guarded_send_source(inspect.getsource(module.RNCPHandler.send_file) + '\n')
        assert not first.handler._mobile_fetch_accept(SimpleNamespace(get_data_size=lambda: module.MAX_FILE + 1, get_hash=lambda: b'a' * 32), bytes.fromhex(ADDRESS))
        assert not first.handler._mobile_fetch_accept(SimpleNamespace(get_data_size=lambda: 1, get_hash=lambda: b'a' * 32), bytes.fromhex('ff' * 16))
        await first.close(); await second.close()
    asyncio.run(run())


@pytest.mark.parametrize('cancelled', [False, True])
def test_guarded_fetch_never_saves_a_cancelled_complete_resource(tmp_path, cancelled):
    async def run():
        value = runtime(tmp_path)
        value.handler._path_wait_seconds = lambda *args: 2
        namespace = value.handler.fetch_file.__func__.__globals__
        source = tmp_path / 'rns-temp'; source.write_bytes(b'exact received bytes')
        key = b'a' * 32
        resource = SimpleNamespace(hash=key, status=9, metadata={'name': b'chosen.bin'}, data=SimpleNamespace(name=str(source)), progress_callback=lambda callback: None, get_progress=lambda: 1.0, cancel=lambda: None)
        links = []
        class Link:
            ACTIVE = 1
            ACCEPT_APP = 2
            def __init__(self, destination): self.status = 1; self.callbacks = {}; self.ended = False; links.append(self)
            def identify(self, identity): pass
            def set_resource_strategy(self, strategy): assert strategy == self.ACCEPT_APP
            def set_resource_callback(self, callback): self.callbacks['accept'] = callback
            def set_resource_started_callback(self, callback): self.callbacks['start'] = callback
            def set_resource_concluded_callback(self, callback): self.callbacks['finish'] = callback
            def teardown(self): self.ended = True
            def request(self, *args, **kwargs):
                kwargs['response_callback'](SimpleNamespace(response=True))
                resource.link = self
                assert self.callbacks['accept'](SimpleNamespace(link=self, get_data_size=lambda: 20, get_hash=lambda: key))
                self.callbacks['start'](resource)
                if cancelled: value.cancel(key.hex())
                self.callbacks['finish'](resource)
        namespace['link_establishment_window'] = lambda *args: 2
        namespace['RNS'] = SimpleNamespace(Transport=SimpleNamespace(has_path=lambda destination: True), Identity=SimpleNamespace(recall=lambda destination: object()),
            Destination=lambda *args: object(), Link=Link, Resource=SimpleNamespace(COMPLETE=9))
        namespace['RNS'].Destination = type('Destination', (), {'OUT': 1, 'SINGLE': 1, '__init__': lambda self, *args: None})
        if cancelled:
            with pytest.raises(InterruptedError): await value.handler.fetch_file(bytes.fromhex(ADDRESS), 'chosen.bin', timeout=2)
            assert source.read_bytes() == b'exact received bytes' and not list(value.received.iterdir())
        else:
            result = await value.handler.fetch_file(bytes.fromhex(ADDRESS), 'chosen.bin', timeout=2)
            assert Path(result['file_path']).read_bytes() == b'exact received bytes'
        assert links[0].ended and not value.reservations
        await value.close()
    asyncio.run(run())


def test_cancel_during_link_setup_tears_down_only_its_own_link(tmp_path):
    async def run():
        value = runtime(tmp_path); entered = asyncio.Event(); links = []
        value.handler._path_wait_seconds = lambda *args: 2
        namespace = value.handler.fetch_file.__func__.__globals__
        class Link:
            ACTIVE = 1
            def __init__(self, destination): self.status = 0; self.ended = False; links.append(self); entered.set()
            def teardown(self): self.ended = True
        namespace['link_establishment_window'] = lambda *args: 60
        namespace['RNS'] = SimpleNamespace(Transport=SimpleNamespace(has_path=lambda destination: True), Identity=SimpleNamespace(recall=lambda destination: object()),
            Destination=type('Destination', (), {'OUT': 1, 'SINGLE': 1, '__init__': lambda self, *args: None}), Link=Link)
        async def check(client):
            operation = asyncio.create_task(client.post('/api/v1/rncp/fetch', json={'destination_hash': ADDRESS, 'file_path': 'remote.bin'}))
            await asyncio.wait_for(entered.wait(), 2)
            assert (await client.post('/api/v1/rncp/cancel', json={})).status == 200
            assert (await asyncio.wait_for(operation, 2)).status == 409
            assert links[0].ended and not value.links and not value.transfers and value.slots._value == 2
        await with_client(value, check)
    asyncio.run(run())


def test_resource_constructor_failure_closes_the_selected_file_and_link(tmp_path):
    async def run():
        value = runtime(tmp_path); handles = []; links = []
        chosen = value.shared / 'chosen.bin'; chosen.write_bytes(b'not leaked')
        value.handler._path_wait_seconds = lambda *args: 2
        namespace = value.handler.send_file.__func__.__globals__
        class Link:
            ACTIVE = 1
            def __init__(self, destination): self.status = 1; self.ended = False; links.append(self)
            def identify(self, identity): pass
            def teardown(self): self.ended = True
        class Resource:
            def __init__(self, handle, *args, **kwargs): handles.append(handle); raise RuntimeError('Synthetic constructor failure')
        namespace['link_establishment_window'] = lambda *args: 2
        namespace['RNS'] = SimpleNamespace(Transport=SimpleNamespace(has_path=lambda destination: True), Identity=SimpleNamespace(recall=lambda destination: object()),
            Destination=type('Destination', (), {'OUT': 1, 'SINGLE': 1, '__init__': lambda self, *args: None}), Link=Link, Resource=Resource)
        async def check(client):
            response = await client.post('/api/v1/rncp/send', json={'destination_hash': ADDRESS, 'file_path': str(chosen)})
            assert response.status == 502
            assert handles[0].closed and links[0].ended and not value.links
            assert chosen.read_bytes() == b'not leaked'
        await with_client(value, check)
    asyncio.run(run())


def test_block_while_finding_a_path_prevents_opening_the_file_link(tmp_path):
    async def run():
        flags = {'blocked': False, 'path': False}; requested = asyncio.Event()
        value = module.FileRuntime(SimpleNamespace(reticulum=object(), source=SimpleNamespace(identity=object())),
            tmp_path / 'rncp', lambda address: flags['blocked'], AsyncMock())
        chosen = value.shared / 'chosen.bin'; chosen.write_bytes(b'not transmitted')
        value.handler._path_wait_seconds = lambda *args: 3
        namespace = value.handler.send_file.__func__.__globals__
        namespace['RNS'] = SimpleNamespace(Transport=SimpleNamespace(has_path=lambda destination: flags['path'], request_path=lambda destination: requested.set()),
            Identity=SimpleNamespace(recall=lambda destination: pytest.fail('Must reject before recalling or opening a destination')))
        async def check(client):
            operation = asyncio.create_task(client.post('/api/v1/rncp/send', json={'destination_hash': ADDRESS, 'file_path': str(chosen)}))
            await asyncio.wait_for(requested.wait(), 2)
            flags.update(blocked=True, path=True)
            assert (await asyncio.wait_for(operation, 2)).status == 400
            assert not value.links and chosen.read_bytes() == b'not transmitted'
        await with_client(value, check)
    asyncio.run(run())


@pytest.mark.parametrize('started', [False, True])
def test_real_mobile_fetch_deadline_only_limits_waiting_for_resource_start(tmp_path, monkeypatch, started):
    from rncp_lifetime_fixture import exercise
    async def run():
        value = runtime(tmp_path)
        try:
            if started:
                await exercise(value.handler, monkeypatch, tmp_path, started=True)
            else:
                with pytest.raises(TimeoutError, match='waiting for remote resource'):
                    await exercise(value.handler, monkeypatch, tmp_path, started=False)
        finally: await value.close()
    asyncio.run(run())


async def _exercise_mobile_segment_completion(
    tmp_path, monkeypatch, terminal
):
    from contextlib import suppress
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from meshchatnext.src.backend import rncp_handler as engine

    complete, failed = engine.RNS.Resource.COMPLETE, engine.RNS.Resource.FAILED
    active = engine.RNS.Link.ACTIVE
    outgoing, single = engine.RNS.Destination.OUT, engine.RNS.Destination.SINGLE
    calls = []
    link = SimpleNamespace(status=active, identify=MagicMock(), teardown=MagicMock())

    class Link:
        ACTIVE = active

        def __new__(cls, *_):
            return link

    class Resource:
        COMPLETE, FAILED = complete, failed

        def __init__(self, handle, _link, **options):
            self.hash = bytes.fromhex("12" * 32)
            self.status = complete  # Only the first segment has its proof.
            self.total_size = 123
            self.get_progress = lambda: 1.0 if terminal == "immediate" else 1 / 3
            calls.append((self, handle, options))
            if terminal == "immediate":
                options["callback"](self)

    monkeypatch.setattr(engine.RNS, "Link", Link)
    monkeypatch.setattr(engine.RNS, "Resource", Resource)
    monkeypatch.setattr(engine.RNS.Transport, "has_path", lambda *_: True)
    monkeypatch.setattr(engine.RNS.Identity, "recall", lambda *_: object())

    class Destination:
        OUT, SINGLE = outgoing, single

        def __new__(cls, *_):
            return object()

    monkeypatch.setattr(engine.RNS, "Destination", Destination)
    monkeypatch.setattr(engine, "link_establishment_window", lambda *_: 1)
    monkeypatch.setattr(engine.traffic_stats, "get_meter", lambda: MagicMock())
    value = runtime(tmp_path)
    handler = value.handler
    monkeypatch.setattr(handler, "_path_wait_seconds", lambda *_: 1)
    source = value.shared / "selected.bin"
    source.write_bytes(b"Private segmented-transfer fixture")
    started = asyncio.Event()
    task = asyncio.create_task(
        handler.send_file(
            bytes.fromhex("34" * 16),
            str(source),
            on_transfer_started=lambda _: started.set(),
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        if terminal == "immediate":
            result = await asyncio.wait_for(task, 2)
            assert result["status"] == "completed"
            link.teardown.assert_called_once()
            assert handler.active_transfers["12" * 32]["status"] == "completed"
            return
        await asyncio.sleep(0.01)
        assert not task.done(), "First segment proof closed the complete file transfer"
        link.teardown.assert_not_called()
        assert handler.active_transfers["12" * 32]["status"] == "sending"
        if terminal == "cancel":
            handler.cancel_transfer("12" * 32)
            with pytest.raises(InterruptedError, match="cancelled"):
                await asyncio.wait_for(task, 2)
        else:
            final = SimpleNamespace(
                status=complete if terminal == "complete" else failed,
                total_size=123,
                get_progress=lambda: 1.0,
            )
            calls[0][2]["callback"](final)
            if terminal == "complete":
                result = await asyncio.wait_for(task, 2)
                assert result["status"] == "completed"
            else:
                with pytest.raises(Exception, match="Transfer failed"):
                    await asyncio.wait_for(task, 2)
        link.teardown.assert_called_once()
        assert (
            handler.active_transfers["12" * 32]["status"]
            == {"complete": "completed", "failed": "failed", "cancel": "cancelled"}[
                terminal
            ]
        )
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
        for _, handle, _ in calls:
            handle.close()
        await value.close()


@pytest.mark.parametrize("terminal", ["complete", "failed", "cancel", "immediate"])
def test_mobile_waits_for_full_transfer_conclusion(tmp_path, monkeypatch, terminal):
    asyncio.run(_exercise_mobile_segment_completion(tmp_path, monkeypatch, terminal))


def test_split_receive_counts_a_file_once_and_releases_its_reservation(tmp_path):
    async def run():
        value = runtime(tmp_path)
        value.handler.allowed_identity_hashes = [IDENTITY]
        link = SimpleNamespace(get_remote_identity=lambda: SimpleNamespace(hash=IDENTITY))
        first = b'a' * 32
        def advert(index, key, size=200):
            return SimpleNamespace(link=link, o=first, i=index, l=3,
                get_data_size=lambda: size, get_hash=lambda: key)
        assert value.handler._receive_resource_callback(advert(1, first))
        assert value.handler._receive_resource_callback(advert(2, b'b' * 32))
        assert value.handler._receive_resource_callback(advert(3, b'c' * 32))
        assert len(value.reservations) == 1
        assert sum(value.reservations.values()) == 200
        value.handler._mobile_fetch_release(SimpleNamespace(link=link, hash=b'c' * 32, original_hash=first))
        assert not value.reservations
        await value.close()
    asyncio.run(run())


@pytest.mark.parametrize('change', ['duplicate', 'skip', 'size', 'count', 'other-link', 'reused-hash'])
def test_split_receive_rejects_inconsistent_continuations(tmp_path, change):
    async def run():
        value = runtime(tmp_path)
        value.handler.allowed_identity_hashes = [IDENTITY]
        def link(): return SimpleNamespace(get_remote_identity=lambda: SimpleNamespace(hash=IDENTITY))
        original = link()
        first = b'a' * 32
        def advert(index, key, size=200, count=3, connection=original):
            return SimpleNamespace(link=connection, o=first, i=index, l=count,
                get_data_size=lambda: size, get_hash=lambda: key)
        assert value.handler._receive_resource_callback(advert(1, first))
        changes = {
            'duplicate': advert(1, first), 'skip': advert(3, b'c' * 32),
            'size': advert(2, b'b' * 32, size=201),
            'count': advert(2, b'b' * 32, count=4),
            'other-link': advert(2, b'b' * 32, connection=link()),
            'reused-hash': advert(2, first),
        }
        assert not value.handler._receive_resource_callback(changes[change])
        assert len(value.reservations) == 1 and sum(value.reservations.values()) == 200
        # Rejection must not advance or corrupt the original transfer.
        assert value.handler._receive_resource_callback(advert(2, b'b' * 32))
        await value.close()
        assert not value.reservations and not value.receive_segments and not value.receive_links
    asyncio.run(run())


def test_closed_receive_link_releases_capacity_and_preserves_existing_callback(tmp_path):
    async def run():
        value = runtime(tmp_path)
        value.handler.allowed_identity_hashes = [IDENTITY]
        closed = []
        class Link:
            def __init__(self): self.callbacks = SimpleNamespace(link_closed=lambda ended: closed.append(ended))
            def set_link_closed_callback(self, callback): self.callbacks.link_closed = callback
            def get_remote_identity(self): return SimpleNamespace(hash=IDENTITY)
        link = Link()
        def advert(key): return SimpleNamespace(link=link, get_data_size=lambda: 20, get_hash=lambda: key)
        assert value.handler._receive_resource_callback(advert(b'a' * 32))
        assert value.handler._receive_resource_callback(advert(b'b' * 32))
        assert not value.handler._receive_resource_callback(advert(b'c' * 32))
        link.callbacks.link_closed(link)
        assert closed == [link]
        assert not value.reservations and not value.receive_segments and not value.receive_links
        assert value.handler._receive_resource_callback(advert(b'c' * 32))
        await value.close()
    asyncio.run(run())


def test_cancel_one_receive_does_not_release_another_files_reservation(tmp_path):
    async def run():
        value = runtime(tmp_path)
        value.handler.allowed_identity_hashes = [IDENTITY]
        link = SimpleNamespace(get_remote_identity=lambda: SimpleNamespace(hash=IDENTITY))
        def advert(key): return SimpleNamespace(link=link, get_data_size=lambda: 20, get_hash=lambda: key)
        first, second = b'a' * 32, b'b' * 32
        assert value.handler._receive_resource_callback(advert(first))
        assert value.handler._receive_resource_callback(advert(second))
        resource = SimpleNamespace(hash=first, original_hash=first, link=link, cancel=lambda: None)
        value.handler.active_transfers[first.hex()] = {'status': 'receiving', 'resource': resource}
        value.cancel(first.hex())
        assert len(value.reservations) == 1 and (id(link), second) in value.reservations
        await value.close()
    asyncio.run(run())


def test_remove_received_file_preserves_other_files_and_rejects_symlinks(tmp_path):
    async def run():
        value = runtime(tmp_path)
        chosen=value.received/'chosen.bin'; chosen.write_bytes(b'chosen bytes')
        other=value.received/'other.bin'; other.write_bytes(b'keep this')
        private=tmp_path/'identity'; private.write_bytes(b'private identity')
        (value.received/'escape').symlink_to(private)
        (value.received/'internal-link').symlink_to(other)
        async def check(client):
            listing=(await (await client.get('/api/v1/preview/rncp/files')).json())['files']
            ids={r['name']:r['id'] for r in listing}
            assert 'escape' not in ids
            assert (await client.delete('/api/v1/preview/rncp/files/'+ids['internal-link'])).status==404
            assert (await client.delete('/api/v1/preview/rncp/files/not-a-file-id')).status==404
            assert (await client.delete('/api/v1/preview/rncp/files/'+ids['chosen.bin'])).status==204
            assert not chosen.exists() and other.read_bytes()==b'keep this'
            assert private.read_bytes()==b'private identity'
            assert (await client.delete('/api/v1/preview/rncp/files/'+ids['chosen.bin'])).status==404
        await with_client(value,check)
    asyncio.run(run())


@pytest.mark.parametrize('fail', [False,True])
def test_file_removal_waits_for_send_to_finish_or_fail(tmp_path,fail):
    async def run():
        value=runtime(tmp_path); source=value.received/'reply.bin';source.write_bytes(b'outgoing bytes')
        entered=asyncio.Event();done=asyncio.Event()
        async def send(**kwargs):
            entered.set();await done.wait()
            if fail:raise RuntimeError('Private fixture failure')
            return {'status':'completed','transfer_id':'ab'*32}
        value.handler.send_file=send
        async def check(client):
            key=value.inventory()[0]['id']
            sending=asyncio.create_task(client.post('/api/v1/rncp/send',json={'destination_hash':ADDRESS,'file_path':str(source)}))
            await entered.wait()
            assert value.inventory()[0]['in_use']
            response=await client.delete('/api/v1/preview/rncp/files/'+key)
            assert response.status==409 and source.read_bytes()==b'outgoing bytes'
            done.set();response=await sending;assert response.status==(502 if fail else 200)
            assert not value.source_files
            assert (await client.delete('/api/v1/preview/rncp/files/'+key)).status==204
        await with_client(value,check)
    asyncio.run(run())


def test_pending_send_already_protects_its_selected_file(tmp_path):
    async def run():
        value=runtime(tmp_path); source=value.received/'waiting.bin';source.write_bytes(b'waiting bytes')
        value.handler.send_file=AsyncMock(return_value={'status':'completed'})
        await value.slots.acquire();await value.slots.acquire()
        async def check(client):
            key=value.inventory()[0]['id']
            sending=asyncio.create_task(client.post('/api/v1/rncp/send',json={'destination_hash':ADDRESS,'file_path':str(source)}))
            end=asyncio.get_running_loop().time()+.5
            while not value.source_files:
                assert asyncio.get_running_loop().time()<end
                await asyncio.sleep(.001)
            value.handler.send_file.assert_not_awaited()
            assert (await client.delete('/api/v1/preview/rncp/files/'+key)).status==409
            value.slots.release();value.slots.release()
            assert (await sending).status==200
            assert not value.source_files
        await with_client(value,check)
    asyncio.run(run())


def test_streaming_download_holds_a_read_lease_for_the_whole_request(tmp_path):
    async def run():
        value=runtime(tmp_path);source=value.received/'export.bin';source.write_bytes(b'export bytes')
        key=value.inventory()[0]['id'];entered=asyncio.Event();done=asyncio.Event()
        async def request():
            response=await value.download(SimpleNamespace(match_info={'file_id':key}))
            assert isinstance(response,web.FileResponse)
            entered.set();await done.wait()
        exporting=asyncio.create_task(request());await entered.wait()
        assert value.inventory()[0]['in_use']
        blocked=await value.remove_file(SimpleNamespace(match_info={'file_id':key}))
        assert blocked.status==409 and source.read_bytes()==b'export bytes'
        done.set();await exporting;await asyncio.sleep(0)
        assert not value.source_files
        assert (await value.remove_file(SimpleNamespace(match_info={'file_id':key}))).status==204
        await value.close()
    asyncio.run(run())



def test_real_http_stream_keeps_its_read_lease_until_disconnect(tmp_path):
    async def run():
        value=runtime(tmp_path);source=value.received/'stream.bin'
        with source.open('wb') as stream:stream.truncate(32*1024*1024)
        key=value.inventory()[0]['id']
        app=web.Application();value.register(app.router)
        async with TestClient(TestServer(app),read_bufsize=1024) as client:
            try:
                response=await client.get('/api/v1/preview/rncp/files/'+key+'/download')
                assert response.status==200
                assert value.inventory()[0]['in_use']
                assert (await client.delete('/api/v1/preview/rncp/files/'+key)).status==409
                response.close()
                end=asyncio.get_running_loop().time()+5
                while value.source_files:
                    assert asyncio.get_running_loop().time()<end,'Closed download retained its read lease'
                    await asyncio.sleep(.01)
                assert (await client.delete('/api/v1/preview/rncp/files/'+key)).status==204
            finally:await value.close()
    asyncio.run(run())
