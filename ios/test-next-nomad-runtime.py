# SPDX-License-Identifier: 0BSD
"""The real released Nomad handlers against the iOS adapter, without radio traffic."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent / 'NextRuntimeProbe'))
from nomad_runtime import NomadRuntime

ADDRESS = 'a1' * 16


class Client:
    def __init__(self): self.rows = []
    async def send_str(self, value): self.rows.append(json.loads(value))
    async def send_json(self, value): self.rows.append(value)


def fixture(folder, blocked=lambda _: False):
    return NomadRuntime(folder, SimpleNamespace(source=SimpleNamespace(identity=None), reticulum=None), blocked, lambda _: None, {})


async def result(client):
    async with asyncio.timeout(3):
        while not client.rows: await asyncio.sleep(.01)
    return client.rows.pop(0)


def test_released_archive_handlers_save_list_load_and_flush(tmp_path):
    async def check():
        runtime, client = fixture(tmp_path), Client()
        try:
            assert await runtime.handle(client, {'type': 'nomadnet.page.archive.add', 'destination_hash': ADDRESS,
                'page_path': '/page/index.mu', 'content': 'Signed transport page'})
            assert (await result(client))['type'] == 'nomadnet.page.archive.added'
            assert await runtime.handle(client, {'type': 'nomadnet.page.archives.get', 'destination_hash': ADDRESS,
                'page_path': '/page/index.mu'})
            rows = (await result(client))['archives']
            assert len(rows) == 1
            await runtime.handle(client, {'type': 'nomadnet.page.archive.load', 'archive_id': rows[0]['id']})
            page = (await result(client))['nomadnet_page_download']
            assert page['status'] == 'success' and page['page_content'] == 'Signed transport page'
            await runtime.handle(client, {'type': 'nomadnet.page.archive.flush'})
            assert runtime.store.archives() == []
        finally: await runtime.close()
    asyncio.run(check())


def test_visiting_does_not_automatically_archive_without_explicit_setting(tmp_path):
    async def check():
        runtime = fixture(tmp_path)
        try:
            runtime.archive_page(ADDRESS, '/page/index.mu', 'Not saved')
            assert runtime.store.archives() == []
            runtime.config['page_archiver_enabled'] = True
            runtime.archive_page(ADDRESS, '/page/index.mu', 'Saved by choice')
            assert len(runtime.store.archives()) == 1
        finally: await runtime.close()
    asyncio.run(check())


def test_malformed_blocked_and_over_budget_requests_never_start_a_downloader(tmp_path):
    async def check():
        runtime, client = fixture(tmp_path, lambda address: address == ADDRESS), Client()
        calls = []
        async def forbidden(*_): calls.append('unexpected request')
        runtime.handlers = dict(runtime.handlers)
        runtime.handlers['nomadnet.page.download'] = forbidden
        try:
            for body in (None, {}, {'destination_hash': ADDRESS, 'page_path': '/page/index.mu'},
                    {'destination_hash': 'b2' * 16, 'page_path': 'file:///private/identity'},
                    {'destination_hash': True, 'page_path': '/page/index.mu'},
                    {'destination_hash': 'b2' * 16, 'page_path': '/page/index.mu', 'field_data': 'x' * 20_000}):
                await runtime.handle(client, {'type': 'nomadnet.page.download', 'nomadnet_page_download': body, 'request_id': 'private'})
                row = await result(client)
                assert row['nomadnet_page_download']['status'] == 'failure' and row['request_id'] == 'private'
            assert calls == [] and runtime.active_downloads == {}
        finally: await runtime.close()
    asyncio.run(check())


def test_only_the_owning_websocket_can_cancel_a_download(tmp_path):
    async def check():
        runtime, owner, stranger = fixture(tmp_path), Client(), Client()
        cancelled = []
        download = SimpleNamespace(_meshchatnext_client=owner, cancel=lambda: cancelled.append(True))
        runtime.active_downloads[1] = download
        try:
            await runtime.handle(stranger, {'type': 'nomadnet.download.cancel', 'download_id': 1})
            assert runtime.active_downloads[1] is download and cancelled == []
            await runtime.handle(owner, {'type': 'nomadnet.download.cancel', 'download_id': 1})
            assert (await result(owner))['type'] == 'nomadnet.download.cancelled'
            assert cancelled == [True] and runtime.active_downloads == {}
        finally: await runtime.close()
    asyncio.run(check())


def test_unknown_events_are_not_consumed_and_disconnect_cancels_only_own_downloads(tmp_path):
    async def check():
        runtime, owner, other = fixture(tmp_path), Client(), Client()
        cancelled = []
        runtime.active_downloads.update({1: SimpleNamespace(_meshchatnext_client=owner, cancel=lambda: cancelled.append(1)),
            2: SimpleNamespace(_meshchatnext_client=other, cancel=lambda: cancelled.append(2))})
        try:
            assert not await runtime.handle(owner, {'type': 'ping'})
            assert not await runtime.handle(owner, [])
            runtime.disconnect(owner)
            assert cancelled == [1] and list(runtime.active_downloads) == [2]
        finally: await runtime.close()
        assert cancelled == [1, 2]
    asyncio.run(check())


def test_discovery_accepts_only_the_identity_bound_nomad_destination(tmp_path, monkeypatch):
    import RNS
    def forbidden(*_args, **_kwargs): raise AssertionError('Passive discovery must not transmit')
    monkeypatch.setattr(RNS.Transport, 'request_path', forbidden)
    async def check():
        runtime = fixture(tmp_path)
        try:
            identity = RNS.Identity()
            address = RNS.Destination.hash_from_name_and_identity('nomadnetwork.node', identity)
            lxmf = RNS.Destination.hash_from_name_and_identity('lxmf.delivery', identity)
            runtime.discovery.received_announce(lxmf, identity, b'Not a Nomad announce')
            assert runtime.discovered({'aspect': 'nomadnetwork.node'}) == []
            runtime.discovery.received_announce(address, identity, b'Local node')
            rows = runtime.discovered({'aspect': 'nomadnetwork.node', 'search': 'local'})
            assert len(rows) == 1 and rows[0]['destination_hash'] == address.hex()
            assert rows[0]['display_name'] == 'Local node'
            assert runtime.discovered({'aspect': 'lxmf.delivery'}) == []
            runtime.discovery.received_announce(address, identity, b'x' * 513)
            assert runtime.discovered({'aspect': 'nomadnetwork.node'})[0]['display_name'] == 'Local node'
            runtime.denied = lambda value: value == address.hex()
            assert runtime.discovered({'aspect': 'nomadnetwork.node'}) == []
        finally: await runtime.close()
    asyncio.run(check())


def test_download_slots_remain_reserved_until_output_is_delivered(tmp_path):
    async def check():
        runtime, client = fixture(tmp_path), Client()
        senders = []
        async def accepted(_runtime, proxy, _envelope): senders.append(proxy)
        runtime.handlers = dict(runtime.handlers)
        runtime.handlers['nomadnet.page.download'] = accepted
        def request(number): return {'type': 'nomadnet.page.download', 'request_id': str(number),
            'nomadnet_page_download': {'destination_hash': ADDRESS, 'page_path': '/page/index.mu'}}
        try:
            for number in range(4): await runtime.handle(client, request(number))
            # The upstream completion pops active_downloads before its async
            # WebSocket sender runs. That must not admit another full resource.
            assert runtime.active_downloads == {} and len(runtime.download_slots) == 4
            await runtime.handle(client, request(5))
            assert len(senders) == 4 and len(runtime.download_slots) == 4
            assert (await result(client))['nomadnet_page_download']['status'] == 'failure'
            await senders[0].send_json({'type': 'nomadnet.page.download', 'nomadnet_page_download': {
                'status': 'success', 'destination_hash': ADDRESS, 'page_content': 'drained'}})
            assert len(runtime.download_slots) == 3
            await runtime.handle(client, request(6))
            assert len(senders) == 5 and len(runtime.download_slots) == 4
        finally: await runtime.close()
        assert not runtime.download_slots
    asyncio.run(check())


def test_block_or_close_prevents_a_late_page_from_reaching_the_webview(tmp_path):
    async def check():
        runtime, client = fixture(tmp_path), Client()
        senders = []
        async def accepted(_runtime, proxy, _envelope): senders.append(proxy)
        runtime.handlers = dict(runtime.handlers)
        runtime.handlers['nomadnet.page.download'] = accepted
        request = {'type': 'nomadnet.page.download', 'request_id': 'pending',
            'nomadnet_page_download': {'destination_hash': ADDRESS, 'page_path': '/page/index.mu'}}
        await runtime.handle(client, request)
        runtime.denied = lambda _: True
        late = {'type': 'nomadnet.page.download', 'nomadnet_page_download': {
            'status': 'success', 'destination_hash': ADDRESS, 'page_content': 'MUST NOT REACH WEBVIEW'}}
        await senders[0].send_json(late)
        assert 'MUST NOT REACH WEBVIEW' not in json.dumps(client.rows)
        assert client.rows[-1]['nomadnet_page_download']['code'] == 'destination_blocked'
        assert not runtime.download_slots
        runtime.denied = lambda _: False
        await runtime.handle(client, request)
        await runtime.close()
        before = list(client.rows)
        await senders[1].send_json(late)
        assert client.rows == before
    asyncio.run(check())


def test_expired_output_releases_its_slot_and_closes_only_its_websocket(tmp_path):
    class Closable(Client):
        closed = False
        async def close(self): self.closed = True
    async def check():
        runtime, owner, other = fixture(tmp_path), Closable(), Closable()
        senders = []
        async def accepted(_runtime, proxy, _envelope): senders.append(proxy)
        runtime.handlers = dict(runtime.handlers)
        runtime.handlers['nomadnet.page.download'] = accepted
        envelope = {'type': 'nomadnet.page.download', 'request_id': 'pending',
            'nomadnet_page_download': {'destination_hash': ADDRESS, 'page_path': '/page/index.mu'}}
        try:
            await runtime.handle(owner, envelope)
            await runtime.handle(other, envelope)
            await senders[0].expire()
            assert owner.closed and not other.closed
            assert owner.rows[-1]['nomadnet_page_download']['code'] == 'download_timed_out'
            assert len(runtime.download_slots) == 1 and senders[1].active
        finally: await runtime.close()
    asyncio.run(check())


class Link:
    def __init__(self):
        import RNS
        self.status = RNS.Link.ACTIVE
        self.txbytes = self.rxbytes = 0
        self.identities, self.requests = [], []
        self.closed = False
    def identify(self, identity): self.identities.append(identity)
    def request(self, path, **_kwargs): self.requests.append(path); return None
    def teardown(self): self.closed = True


def pending_page(runtime):
    cls = runtime.handlers['nomadnet.page.download'].__globals__['NomadnetPageDownloader']
    return cls(bytes.fromhex(ADDRESS), '/page/index.mu', None, lambda _: None, lambda _: None,
        lambda _: None, local_identity=object(), identify_on_connect=True)


def test_pending_identification_is_rechecked_and_other_runtimes_are_not_changed(tmp_path):
    async def check():
        from meshchatnext.src.backend.http.ws import handlers_nomad
        original = handlers_nomad.NomadnetPageDownloader
        first = fixture(tmp_path)
        other = tmp_path / 'other'; other.mkdir()
        second = fixture(other)
        try:
            first.store.save_favourite(ADDRESS, 'First', identify=True)
            second.store.save_favourite(ADDRESS, 'Second', identify=True)
            pending_first, pending_second = pending_page(first), pending_page(second)
            # Both requests captured opt-in when created. Revoke only the first
            # before its delayed link callback reaches identification.
            with first.policy_lock:
                first.store.save_favourite(ADDRESS, 'First', identify=False)
            first_link, second_link = Link(), Link()
            pending_first.link_established(first_link)
            pending_second.link_established(second_link)
            assert first_link.identities == [] and len(first_link.requests) == 1
            assert len(second_link.identities) == len(second_link.requests) == 1
            assert handlers_nomad.NomadnetPageDownloader is original
            assert first.handlers['nomadnet.page.download'].__code__ is handlers_nomad.HANDLERS['nomadnet.page.download'].__code__
        finally:
            await first.close(); await second.close()
    asyncio.run(check())


def test_a_block_committed_while_the_path_is_pending_prevents_identification_and_request(tmp_path):
    async def check():
        runtime = fixture(tmp_path)
        try:
            runtime.store.save_favourite(ADDRESS, 'Saved', identify=True)
            pending = pending_page(runtime)
            runtime.begin_block({ADDRESS})
            link = Link()
            pending.link_established(link)
            assert link.identities == link.requests == []
            assert link.closed and pending.is_cancelled
        finally: await runtime.close()
    asyncio.run(check())


def test_browser_http_layout_import_and_selected_archive_removal_preserve_other_data(tmp_path):
    async def check():
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        runtime = fixture(tmp_path)
        app = web.Application(); runtime.register(app.router)
        try:
            async with TestClient(TestServer(app, host='127.0.0.1')) as client:
                assert (await client.post('/api/v1/favourites/add', json={'destination_hash': ADDRESS, 'display_name': 'Saved'})).status == 200
                assert (await client.post('/api/v1/favourites/'+ADDRESS+'/identify-on-connect', json={'enabled': True})).status == 200
                imported = await client.post('/api/v1/favourites/import', json={'favourites': [
                    {'destination_hash': 'b2' * 16, 'display_name': 'Imported', 'identify_on_connect': True}]})
                assert imported.status == 200 and (await imported.json())['imported'] == 1
                assert not runtime.store.should_identify_on_connect('b2' * 16)
                layout = {'sections': [{'id': 'root', 'name': 'Routes'}, {'id': '__proto__', 'name': 'Invalid'}],
                    'sectionOrder': ['root'], 'favouritesBySection': {'root': [ADDRESS.upper(), ADDRESS, '__proto__']}}
                saved = await client.put('/api/v1/favourites/layout', json={'layout': layout})
                assert saved.status == 200
                value = (await saved.json())['layout']
                assert value['sections'] == [{'id': 'root', 'name': 'Routes', 'collapsed': False}]
                assert value['favouritesBySection']['root'] == [ADDRESS]
                assert (await (await client.get('/api/v1/favourites/layout')).json())['layout'] == value
                first = runtime.store.archive_page(ADDRESS, '/page/index.mu', '<script>not executable</script>')
                second = runtime.store.archive_page(ADDRESS, '/page/index.mu', 'Latest page')
                listing = await (await client.get('/api/v1/nomadnet/archives?limit=1')).json()
                assert listing['pagination']['total_count'] == 2 and len(listing['archives']) == 1
                details = await (await client.get('/api/v1/nomadnet/archives/'+str(first['id']))).json()
                assert '&lt;script&gt;' in details['archive']['snippet'] and '<script>' not in details['archive']['snippet']
                assert (await client.delete('/api/v1/nomadnet/archives', json={'ids': []})).status == 400
                assert len(runtime.store.archives()) == 2
                assert (await client.delete('/api/v1/nomadnet/archives', json={'ids': [second['id']]})).status == 200
                assert [row['id'] for row in runtime.store.archives()] == [first['id']]
                assert runtime.store.should_identify_on_connect(ADDRESS)
                assert (await client.post('/api/v1/favourites/add', json={'destination_hash': ADDRESS, 'display_name': 'x', 'unused': 'x' * 4096})).status == 413
        finally: await runtime.close()
    asyncio.run(check())


def test_archive_zip_contains_only_selected_saved_pages_and_leaves_no_temporary_file(tmp_path):
    async def check():
        import io, zipfile
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        runtime = fixture(tmp_path)
        runtime.store.archive_page(ADDRESS, '/page/../../private.mu', 'Chosen content')
        runtime.store.archive_page('b2' * 16, '/page/elsewhere.mu', 'Must not be exported')
        app = web.Application(); runtime.register(app.router)
        before = {path.name for path in tmp_path.iterdir()}
        try:
            async with TestClient(TestServer(app, host='127.0.0.1')) as client:
                response = await client.get('/api/v1/nomadnet/archives/export?destination_hash='+ADDRESS)
                assert response.status == 200 and response.headers['Content-Type'] == 'application/zip'
                data = await response.read()
                assert len(data) == int(response.headers['Content-Length'])
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    assert archive.testzip() is None
                    assert all(not name.startswith('/') and '..' not in name.split('/') for name in archive.namelist())
                    manifest = json.loads(archive.read('manifest.json'))
                    assert len(manifest) == 1 and manifest[0]['destination_hash'] == ADDRESS
                    assert archive.read(manifest[0]['file']) == b'Chosen content'
                    assert b'Must not be exported' not in b''.join(archive.read(name) for name in archive.namelist())
                async with asyncio.timeout(3):
                    while runtime.exporting: await asyncio.sleep(.01)
                assert not runtime.exporting
                assert {path.name for path in tmp_path.iterdir()} == before
        finally: await runtime.close()
    asyncio.run(check())


def test_live_discovery_broadcasts_only_committed_unblocked_nomad_announces(tmp_path):
    import RNS
    async def check():
        runtime = fixture(tmp_path)
        events = []
        runtime.broadcast = events.append
        identity = RNS.Identity()
        address = RNS.Destination.hash_from_name_and_identity('nomadnetwork.node', identity)
        wrong = RNS.Destination.hash_from_name_and_identity('lxmf.delivery', identity)
        try:
            runtime.discovery.received_announce(wrong, identity, b'Wrong aspect')
            await asyncio.sleep(0)
            assert events == []
            runtime.discovery.received_announce(address, identity, b'Live Nomad node')
            await asyncio.sleep(0)
            assert len(events) == 1
            assert events[0]['type'] == 'announce'
            assert events[0]['announce']['display_name'] == 'Live Nomad node'
            assert runtime.discovery.page({'aspect': 'nomadnetwork.node'})[0] == events[0]['announce']
            runtime.begin_block([address.hex()])
            runtime.discovery.received_announce(address, identity, b'Blocked update')
            await asyncio.sleep(0)
            assert len(events) == 1
            runtime.discovery.received_announce(address, identity, b'x' * 513)
            await asyncio.sleep(0)
            assert len(events) == 1
        finally: await runtime.close()
        runtime.announce_changed(address.hex())
        assert len(events) == 1
    asyncio.run(check())


def test_cancelled_export_closes_the_workers_file_and_holds_its_reservation(tmp_path, monkeypatch):
    import threading
    import tempfile
    import nomad_runtime
    from aiohttp import web
    async def check():
        runtime = fixture(tmp_path)
        runtime.store.archive_page(ADDRESS, '/page/index.mu', 'Private saved page')
        entered, release = threading.Event(), threading.Event()
        files = []
        original = tempfile.TemporaryFile
        def paused_file(*args, **kwargs):
            result = original(*args, **kwargs)
            files.append(result)
            entered.set()
            if not release.wait(3):
                result.close()
                raise AssertionError('The cancellation test failed to release its worker')
            return result
        monkeypatch.setattr(nomad_runtime.tempfile, 'TemporaryFile', paused_file)
        app = web.Application(); runtime.register(app.router)
        handler = next(route.handler for route in app.router.routes()
            if route.method == 'GET' and route.resource.canonical == '/api/v1/nomadnet/archives/export')
        task = asyncio.create_task(handler(SimpleNamespace(query={})))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
            else: raise AssertionError('Cancelled export returned successfully')
            assert runtime.exporting and not files[0].closed
            try: await handler(SimpleNamespace(query={}))
            except web.HTTPConflict: pass
            else: raise AssertionError('A second export bypassed the active worker')
            release.set()
            async with asyncio.timeout(3):
                while runtime.exporting: await asyncio.sleep(.01)
            assert files[0].closed
        finally:
            release.set()
            await runtime.close()
    asyncio.run(check())


def test_repeated_archive_exports_do_not_accumulate_file_descriptors(tmp_path):
    import os
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    async def check():
        runtime = fixture(tmp_path)
        runtime.store.archive_page(ADDRESS, '/page/index.mu', 'Repeated private export')
        app = web.Application(); runtime.register(app.router)
        try:
            async with TestClient(TestServer(app, host='127.0.0.1')) as client:
                baseline = None
                for index in range(12):
                    async with client.get('/api/v1/nomadnet/archives/export') as response:
                        assert response.status == 200
                        await response.read()
                    async with asyncio.timeout(3):
                        while runtime.exporting: await asyncio.sleep(.01)
                    if os.path.isdir('/proc/self/fd'):
                        count = len(os.listdir('/proc/self/fd'))
                        if index == 0: baseline = count
                        else: assert count <= baseline, (baseline, count)
        finally: await runtime.close()
    asyncio.run(check())


def test_archive_storage_failure_reports_an_error_without_false_saved_confirmation(tmp_path, monkeypatch):
    async def check():
        runtime, client = fixture(tmp_path), Client()
        original = runtime.store.archive_page
        def unavailable(*args, **kwargs): raise OSError('private filesystem detail')
        monkeypatch.setattr(runtime.store, 'archive_page', unavailable)
        envelope = {'type': 'nomadnet.page.archive.add', 'destination_hash': ADDRESS,
            'page_path': '/page/index.mu', 'content': 'Keep this page'}
        try:
            await runtime.handle(client, envelope)
            error = await result(client)
            assert error['type'] == 'error' and error['code'] == 'local_storage_unavailable'
            assert 'private filesystem detail' not in json.dumps(error)
            assert runtime.store.archives() == []
            monkeypatch.setattr(runtime.store, 'archive_page', original)
            await runtime.handle(client, envelope)
            assert (await result(client))['type'] == 'nomadnet.page.archive.added'
            assert len(runtime.store.archives()) == 1
        finally: await runtime.close()
    asyncio.run(check())


def test_mobile_sandbox_csp_matches_the_checksum_pinned_upstream_policy():
    import ast
    import inspect
    import os
    from nomad_frame import build_nomad_crash_tab_csp
    source = Path(os.environ['NEXT_TEST_BACKEND_SOURCE']) / 'meshchatnext/src/backend/http/middleware.py'
    original = next(node for node in ast.parse(source.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == 'build_nomad_crash_tab_csp')
    mobile = ast.parse(inspect.getsource(build_nomad_crash_tab_csp)).body[0]
    assert ast.dump(original, include_attributes=False) == ast.dump(mobile, include_attributes=False)
