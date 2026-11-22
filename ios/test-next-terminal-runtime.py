"""Remote-terminal boundaries, restart preservation and standard message flow."""
import asyncio
from pathlib import Path
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ['NEXT_TEST_BACKEND_SOURCE']).resolve()
sys.path[:0] = [str(ROOT / 'ios/NextRuntimeProbe'), str(BACKEND)]
import terminal_runtime as module

ADDRESS = 'ab' * 16


def runtime(folder, blocked=lambda address: False):
    return module.TerminalRuntime(SimpleNamespace(reticulum=object(), source=SimpleNamespace(identity=object())), folder, blocked, AsyncMock())


async def request(value, operation):
    app = web.Application(); value.register(app.router)
    async with TestClient(TestServer(app)) as client:
        try: return await operation(client)
        finally: await value.close()


@pytest.mark.parametrize('data', [None, [], {'destination': 'invalid'}, {'destination': ADDRESS, 'mode': 'listen'},
    {'destination': ADDRESS, 'remote_command': 'x' * 4097}, {'destination': ADDRESS, 'remote_command': '"unclosed'},
    {'destination': ADDRESS, 'config_path': '/private'}, {'destination': ADDRESS, 'identity_path': '/private'},
    {'destination': ADDRESS, 'no_id': 'true'}, {'destination': ADDRESS, 'mirror': 1}, {'destination': ADDRESS, 'autostart': 'true'},
    {'destination': ADDRESS, 'rows': True}, {'destination': ADDRESS, 'cols': 0}, {'destination': ADDRESS, 'timeout': 'nan'},
    {'destination': ADDRESS, 'timeout': True}, {'destination': ADDRESS, 'timeout': -1}])
def test_invalid_or_local_execution_settings_are_rejected(data):
    with pytest.raises(ValueError): module.configuration(data)


def test_saved_history_and_settings_survive_restart_without_running_commands(tmp_path):
    async def run():
        value = runtime(tmp_path)
        async def check(client):
            response = await client.post('/api/v1/rnsh/sessions', json={'destination': ADDRESS, 'name': 'Private shell', 'remote_command': 'echo "quoted value"', 'autostart': False})
            assert response.status == 200
            identifier = (await response.json())['session']['id']
            session = value.sessions[identifier]; session.append('Unicode ☃ retained\r\n'); await value.tick()
            assert value.state.stat().st_mode & 0o777 == 0o600
            return identifier
        identifier = await request(value, check)
        reopened = runtime(tmp_path)
        assert not reopened.error
        session = reopened.sessions[identifier]
        assert session.status == 'stopped' and session.worker is None and session.link is None
        assert session.record()['output_text'] == 'Unicode ☃ retained\r\n'
        assert session.config['remote_command'] == 'echo "quoted value"'
        await reopened.close()
    asyncio.run(run())


def test_stopping_before_the_first_run_discards_unsent_input(tmp_path, monkeypatch):
    async def run():
        value = runtime(tmp_path)
        session = module.Session(value, 'aa' * 16, module.configuration({'destination': ADDRESS, 'autostart': False}))
        called = []
        async def never_run(self): called.append('ran'); await asyncio.Future()
        monkeypatch.setattr(module.Session, 'run', never_run)
        session.start(); session.input.extend(b'do not replay'); await session.stop()
        assert not session.input and called == [] and session.status == 'stopped'
        session.start(); assert not session.input; await session.stop()
        await value.close()
    asyncio.run(run())


def test_gets_and_invalid_input_do_not_connect_or_change_saved_state(tmp_path):
    async def run():
        value = runtime(tmp_path)
        async def check(client):
            assert (await client.get('/api/v1/rnsh/sessions')).status == 200
            assert not value.state.exists() and not value.sessions
            response = await client.post('/api/v1/rnsh/sessions', json={'destination': ADDRESS, 'autostart': False})
            identifier = (await response.json())['session']['id']
            before = value.state.read_bytes()
            for cursor in ('-1', 'nan', '0' * 21):
                assert (await client.get('/api/v1/rnsh/sessions/'+identifier+'/output?cursor='+cursor)).status == 400
            assert (await client.post('/api/v1/rnsh/sessions/'+identifier+'/input', json={'text': 'not started'})).status == 400
            assert value.state.read_bytes() == before and value.sessions[identifier].worker is None
        await request(value, check)
    asyncio.run(run())


def test_blocked_contact_never_creates_a_session_or_path_request(tmp_path, monkeypatch):
    monkeypatch.setattr(module.RNS.Transport, 'request_path', lambda *args: pytest.fail('No path request allowed'))
    async def run():
        value = runtime(tmp_path, blocked=lambda address: True)
        async def check(client):
            assert (await client.post('/api/v1/rnsh/sessions', json={'destination': ADDRESS})).status == 400
            assert not value.sessions and not value.state.exists()
        await request(value, check)
    asyncio.run(run())


def test_corrupt_session_file_is_preserved_and_only_disables_the_terminal(tmp_path):
    tmp_path.mkdir(exist_ok=True); state = tmp_path / 'sessions.json'; state.write_bytes(b'not json')
    async def run():
        value = runtime(tmp_path)
        async def check(client):
            assert (await client.get('/api/v1/rnsh/sessions')).status == 503
            assert (await client.post('/api/v1/rnsh/sessions', json={'destination': ADDRESS})).status == 503
            assert state.read_bytes() == b'not json'
        await request(value, check)
        assert state.read_bytes() == b'not json'
    asyncio.run(run())


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('code', [-9, 0, 7, 123456789])
def test_actual_exit_message_preserves_reported_code_and_mirror_policy(tmp_path, mirror, code):
    async def run():
        value = runtime(tmp_path)
        session = module.Session(value, 'aa' * 16, module.configuration({'destination': ADDRESS, 'autostart': False, 'mirror': mirror}))
        message = module.protocol.CommandExitedMessage(code)
        decoded = module.protocol.CommandExitedMessage(); decoded.unpack(message.pack())
        session.command_exited(decoded.return_code)
        assert session.remote_exit_code == code
        assert session.last_exit_code == (code if mirror else 0)
        assert session.status == ('failed' if mirror and code else 'stopped')
        await value.close()
    asyncio.run(run())


@pytest.mark.parametrize('code', [None, True, '7', 1.5, 2**40])
def test_invalid_remote_exit_messages_are_rejected(tmp_path, code):
    async def run():
        value = runtime(tmp_path)
        session = module.Session(value, 'aa' * 16, module.configuration({'destination': ADDRESS, 'autostart': False}))
        with pytest.raises(ValueError): session.command_exited(code)
        assert session.remote_exit_code is None
        await value.close()
    asyncio.run(run())


def test_nonfatal_remote_diagnostics_do_not_end_a_healthy_connection(tmp_path):
    async def run():
        value = runtime(tmp_path)
        session = module.Session(value, 'aa' * 16, module.configuration({'destination': ADDRESS, 'autostart': False}))
        session.inbox.put_nowait(module.protocol.ErrorMessage('Nonfatal peer notice', fatal=False))
        session.inbox.put_nowait(module.protocol.VersionInfoMessage())
        assert isinstance(await session.receive(1), module.protocol.VersionInfoMessage)
        assert 'Nonfatal peer notice' in session.record()['output_text']
        session.inbox.put_nowait(module.protocol.ErrorMessage('Access denied', fatal=True))
        with pytest.raises(ConnectionError): await session.receive(1)
        await value.close()
    asyncio.run(run())


def test_verified_final_output_is_drained_after_the_remote_link_closes(tmp_path):
    async def run():
        value = runtime(tmp_path)
        session = module.Session(value, 'aa' * 16, module.configuration({'destination': ADDRESS, 'autostart': False}))
        session.link = SimpleNamespace(status=module.RNS.Link.CLOSED)
        session.inbox.put_nowait(module.protocol.CommandExitedMessage(7))
        message = await session.receive(.1)
        session.command_exited(message.return_code)
        assert session.remote_exit_code == 7
        with pytest.raises(ConnectionError): await session.receive(.1)
        session.inbox.put_nowait(module.protocol.CommandExitedMessage(0))
        value.blocked = lambda destination: True
        with pytest.raises(PermissionError): await session.receive(.1)
        await value.close()
    asyncio.run(run())


def test_storage_failure_during_close_does_not_block_other_services_cleanup(tmp_path, monkeypatch):
    async def run():
        value = runtime(tmp_path)
        def no_space(): raise OSError('No space left')
        monkeypatch.setattr(value, 'save', no_space)
        await value.close()
        assert value.closed and 'could not be saved' in value.error
        assert not value.events
    asyncio.run(run())


def test_failed_initial_save_never_starts_a_remote_command(tmp_path, monkeypatch):
    async def run():
        value = runtime(tmp_path)
        called = []
        monkeypatch.setattr(module.Session, 'start', lambda self: called.append(self.id))
        def no_space(): raise OSError('No space left')
        monkeypatch.setattr(value, 'save', no_space)
        async def check(client):
            response = await client.post('/api/v1/rnsh/sessions', json={'destination': ADDRESS, 'autostart': True})
            assert response.status == 507
            await asyncio.sleep(0)
            assert called == [] and not value.sessions
        await request(value, check)
    asyncio.run(run())


def test_slow_web_view_bounds_event_tasks_and_resyncs_saved_output(tmp_path):
    async def run():
        value = runtime(tmp_path)
        release = asyncio.Event(); observed = []
        async def publish(event):
            await release.wait()
            observed.append(event)
        value.publish = publish
        session = module.Session(value, 'aa' * 16, module.configuration({'destination': ADDRESS, 'autostart': False}))
        value.sessions[session.id] = session
        for index in range(1000): session.append('remote output ' + str(index) + '\r\n')
        assert len(value.events) == 64 and value.deferred == {session.id}
        assert session.record()['output_text'].endswith('remote output 999\r\n')
        release.set()
        async with asyncio.timeout(3):
            while value.events or value.deferred: await asyncio.sleep(.01)
        assert len(observed) == 65
        assert observed[-1] == {'type': 'rnsh.session.change', 'session_id': session.id}
        await value.close()
        assert not value.events and not value.deferred
    asyncio.run(run())


@pytest.mark.parametrize('command', [False, [], {}])
def test_invalid_empty_command_types_do_not_open_a_remote_shell(command):
    with pytest.raises(ValueError): module.configuration({'destination': ADDRESS, 'remote_command': command})


def test_unicode_history_reopens_with_ascii_default_locale(tmp_path):
    import json
    import subprocess
    row = dict(id='aa' * 16, config=dict(destination=ADDRESS, autostart=False),
               created_at=1, updated_at=2, output_text='Unicode \u2603 retained\r\n')
    (tmp_path / 'sessions.json').write_bytes(json.dumps([row], ensure_ascii=False).encode('utf-8'))
    code = r"""
import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from terminal_runtime import TerminalRuntime
async def run():
    value = TerminalRuntime(SimpleNamespace(), Path(sys.argv[1]), lambda address: False, AsyncMock())
    assert not value.error, value.error
    session = value.sessions['aa' * 16]
    assert session.status == 'stopped' and session.worker is None
    assert session.record()['output_text'] == 'Unicode \u2603 retained\r\n'
    await value.close()
asyncio.run(run())
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
        env={**os.environ, 'LC_ALL': 'C', 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0',
             'PYTHONPATH': os.pathsep.join([str(ROOT / 'ios/NextRuntimeProbe'), str(BACKEND)])},
        capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
