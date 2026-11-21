"""Released SIP account/HTTP service with the iOS adapters; no real registrars."""
import asyncio
import json
from pathlib import Path
import sys

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

PROBE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE))
from sip_runtime import NextSIPRuntime


class Vault:
    def __init__(self): self.values = {}
    def save(self, key, value): self.values[key] = value
    def load(self, key, *, interactive=True): return self.values[key]
    def remove(self, key): self.values.pop(key, None)


class Engine:
    instances = []
    def __init__(self, *args, **kwargs):
        self.running = False; self.on_event = None; self.options = kwargs
        self.commands = []; self.closed = False; self.instances.append(self)
    async def launch(self): self.running = True
    async def command(self, op, **values):
        self.commands.append((op, values))
        if op == 'start': self.on_event({'state': 'registered'})
    async def close(self): self.running = False; self.closed = True


def adapter(folder, route=None):
    return NextSIPRuntime(folder, device=True, vault=Vault(), engine_factory=Engine,
                          network_provider=lambda: route or [dict(interface='ios-default-private', address='default', kind='wifi')])


def test_actual_service_constructs_without_connecting_or_disclosing_password(tmp_path):
    async def run():
        Engine.instances.clear()
        runtime = adapter(tmp_path)
        assert not Engine.instances and not runtime.service.store.accounts
        await runtime.start()
        await asyncio.sleep(0)
        assert not Engine.instances
        await runtime.close()
        assert not Engine.instances
    asyncio.run(run())


def test_actual_http_save_connect_disconnect_and_keychain_removal(tmp_path):
    async def run():
        Engine.instances.clear(); runtime = adapter(tmp_path)
        app = web.Application(); runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            status = await (await client.get('/api/v1/sip/status')).json()
            assert status['platform'] == 'ios' and not status['calling_available']
            assert status['account_management_available'] and not status['available'] and not status['registered']
            secret = 'synthetic private account test'
            payload = dict(op='save', account=dict(extension='9001', host='127.0.0.1', port=55162,
                                                   allowed_networks=['wifi'], save_password=True), password=secret)
            response = await client.post('/api/v1/sip/command', json=payload)
            assert response.status == 200
            saved = await response.json(); key = saved['accounts'][0]['id']
            assert secret not in json.dumps(saved) and not Engine.instances
            metadata = tmp_path / 'sip/accounts.json'
            assert secret not in metadata.read_text()
            response = await client.post('/api/v1/sip/command', json=dict(op='connect', id=key))
            assert response.status == 200
            connected = await response.json()
            assert connected['registered'] and connected['network'] == 'wifi'
            assert len(Engine.instances) == 1
            assert Engine.instances[0].options['interface'] == 'ios-default-private'
            assert Engine.instances[0].commands == [('start', dict(user='9001', host='127.0.0.1', port=55162, password=secret))]
            for op in ['call','answer','hangup','mute','hold','dtmf','speaker']:
                response = await client.post('/api/v1/sip/command', json=dict(op=op, target='9002'))
                assert response.status == 400
            assert len(Engine.instances[0].commands) == 1
            response = await client.post('/api/v1/sip/command', json=dict(op='disconnect'))
            assert response.status == 200 and Engine.instances[0].closed
            assert not (await response.json())['registered']
            assert (await client.post('/api/v1/sip/command', json=dict(op='remove', id=key))).status == 200
            assert not runtime.service.store.vault.values
            assert not json.loads(metadata.read_text())['accounts']
        await runtime.close()
    asyncio.run(run())


def test_simulator_accounts_cannot_start_even_when_a_native_bridge_exists(tmp_path):
    async def run():
        def forbidden(*args, **kwargs): raise AssertionError('Simulator opened a SIP account')
        runtime = NextSIPRuntime(tmp_path, device=False, service_factory=forbidden)
        await runtime.start()
        assert not tmp_path.joinpath('sip').exists()
        app = web.Application(); runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            status = await (await client.get('/api/v1/sip/status')).json()
            assert status['platform'] == 'ios' and not status['available']
            assert (await client.post('/api/v1/sip/command', json=dict(op='connect'))).status == 503
        await runtime.close()
    asyncio.run(run())


def test_corrupt_accounts_are_preserved_without_disabling_other_services(tmp_path):
    path = tmp_path / 'sip/accounts.json'; path.parent.mkdir(); path.write_text('{not json')
    runtime = adapter(tmp_path)
    assert not runtime.status()['available'] and runtime.error
    assert path.read_text() == '{not json'


def test_native_route_change_retires_old_engine_and_obeys_allowed_networks(tmp_path):
    async def run():
        Engine.instances.clear()
        routes = [dict(interface='ios-default-1', address='default', kind='wifi')]
        runtime = adapter(tmp_path, routes)
        await runtime.service.command('save', account=dict(extension='9001',host='127.0.0.1',port=55162,allowed_networks=['wifi']),password='synthetic')
        await runtime.service.command('connect')
        first = Engine.instances[0]
        routes[:] = [dict(interface='ios-default-2',address='default',kind='mobile')]
        await runtime.service.reconcile()
        assert first.closed and runtime.status()['state'] == 'waiting_network'
        assert len(Engine.instances) == 1
        routes[:] = [dict(interface='ios-default-3',address='default',kind='wifi')]
        await runtime.service.reconcile()
        assert len(Engine.instances) == 2 and runtime.status()['registered']
        await runtime.close()
    asyncio.run(run())


def test_actual_private_server_protects_sip_routes(tmp_path):
    async def run():
        from loopback_probe import serve
        import aiohttp
        frontend = tmp_path / "frontend"; frontend.mkdir()
        (frontend / "index.html").write_text("<html>Private SIP check</html>")
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"peers": [dict(id="off",host="127.0.0.1",port=45454,enabled=False)]}))
        ready = tmp_path / "ready.url"
        task = asyncio.create_task(serve(ready, frontend, settings, device=True, sip_factory=NextSIPRuntime))
        try:
            for _ in range(100):
                if ready.exists(): break
                if task.done(): await task
                await asyncio.sleep(.1)
            assert ready.exists(), "Private iOS server did not start"
            info = json.loads((tmp_path / "next-runtime-info.json").read_text())
            base = info["origin"]
            async with aiohttp.ClientSession() as client:
                assert (await client.get(base + "/api/v1/sip/status")).status == 403
                headers = {"X-neXt-Session": info["capability"]}
                response = await client.get(base + "/api/v1/sip/status", headers=headers)
                assert response.status == 200
                value = await response.json()
                assert value["platform"] == "ios" and value["account_management_available"]
                assert not value["available"] and not value["calling_available"]
                assert (await client.post(base + "/api/v1/sip/command", headers=headers, json={"op":"connect"})).status == 403
                token = await (await client.get(base + "/api/v1/auth/csrf", headers=headers)).json()
                headers["X-CSRF-Token"] = token["csrf_token"]
                headers["Origin"] = "https://example.invalid"
                assert (await client.post(base + "/api/v1/sip/command", headers=headers, json={"op":"connect"})).status == 403
                headers["Origin"] = base
                assert (await client.post(base + "/api/v1/sip/command", headers=headers, json={"op":"call", "target":"9002"})).status == 400
                assert not (tmp_path / "sip/accounts.json").exists()
        finally:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
    asyncio.run(run())


def test_linked_call_routes_require_the_displayed_call_identity(tmp_path):
    async def run():
        Engine.instances.clear()
        runtime = NextSIPRuntime(tmp_path, device=True, vault=Vault(), engine_factory=Engine,
            network_provider=lambda: [dict(interface='ios-private',address='default',kind='wifi')],
            capability_provider=lambda: dict(calling_available=True, default_speaker=True))
        app = web.Application(); runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            async def command(op, **fields):
                response = await client.post('/api/v1/sip/command',json=dict(op=op,**fields))
                return response.status, await response.json()
            status, saved = await command('save', account=dict(extension='9001',host='127.0.0.1',port=55162),password='synthetic')
            assert status == 200 and saved['available'] and saved['calling_available'] and saved['speaker']
            assert (await command('connect'))[0] == 200
            engine = runtime.service.engine
            runtime.service._event(engine,dict(state='incoming',peer='sip:9002@127.0.0.1:55162'))
            first = runtime.status()['call_id']; assert first
            count = len(engine.commands)
            for identifier in ['', 'old-call', None]:
                assert (await command('answer',call_id=identifier))[0] == 400
            assert len(engine.commands) == count
            assert (await command('answer',call_id=first))[0] == 200
            runtime.service._event(engine,dict(state='connected',peer='sip:9002@127.0.0.1:55162'))
            assert (await command('mute',call_id=first,value=1))[0] == 400
            assert (await command('mute',call_id=first,value=True))[0] == 200
            runtime.service._event(engine,dict(state='muted',code=0))
            assert not runtime.status()['muted']
            assert (await command('dtmf',call_id=first,digit='12'))[0] == 400
            assert (await command('dtmf',call_id=first,digit='5'))[0] == 200
            assert engine.commands[-1] == ('digit',{'digit':'5'})
            runtime.service._event(engine,dict(state='ended'))
            runtime.service._event(engine,dict(state='incoming',peer='sip:9003@127.0.0.1:55162'))
            second = runtime.status()['call_id']; assert second and second != first
            count = len(engine.commands)
            assert (await command('hangup',call_id=first))[0] == 400
            assert len(engine.commands) == count
            assert (await command('hangup',call_id=second))[0] == 200
        await runtime.close()
    asyncio.run(run())


def test_reading_microphone_status_never_connects_or_requests_access(tmp_path):
    Engine.instances.clear()
    capability = dict(calling_available=True, microphone_permission='not_determined')
    runtime = NextSIPRuntime(tmp_path, device=True, vault=Vault(),engine_factory=Engine,
                            capability_provider=lambda: capability)
    assert runtime.status()['microphone_permission'] == 'not_determined'
    capability['microphone_permission'] = 'granted'
    assert runtime.status()['microphone_permission'] == 'granted'
    capability['microphone_permission'] = 'invalid private data'
    assert runtime.status()['microphone_permission'] == 'unknown'
    assert not Engine.instances and not (tmp_path/'sip/accounts.json').exists()


def test_foreground_refresh_preserves_active_calls_and_disabled_accounts(tmp_path):
    async def run():
        class Service:
            def __init__(self, status): self.current=status; self.commands=[]
            def status(self): return dict(self.current)
            async def resume_foreground(self): self.commands.append("resume"); return True
        runtime=NextSIPRuntime.__new__(NextSIPRuntime)
        runtime.service=None
        assert not await runtime.foreground()
        for state in ['incoming','calling','ringing','progress','connected','ending']:
            runtime.service=Service(dict(enabled=True,call_state=state,call_id='exact-live-call'))
            assert not await runtime.foreground()
            assert runtime.service.commands==[]
            assert runtime.service.current['call_id']=='exact-live-call'
        for status in [dict(enabled=False,call_state='idle',call_id=''),
                       dict(enabled=True,call_state='idle',call_id='retiring-call')]:
            runtime.service=Service(status)
            assert not await runtime.foreground() and runtime.service.commands==[]
        runtime.service=Service(dict(enabled=True,call_state='idle',call_id=''))
        assert await runtime.foreground()
        assert runtime.service.commands==['resume']
    asyncio.run(run())


def test_foreground_refresh_rechecks_calls_after_waiting_for_the_service_lock(tmp_path):
    async def run():
        runtime=adapter(tmp_path)
        await runtime.service.command('save',account=dict(extension='9001',host='127.0.0.1',port=55162),password='synthetic')
        await runtime.service.command('connect')
        engine=runtime.service.engine
        assert runtime.service.status()['registered']
        await runtime.service._lock.acquire()
        pending=asyncio.create_task(runtime.foreground())
        await asyncio.sleep(0)
        runtime.service._event(engine,dict(state='incoming',peer='sip:9002@127.0.0.1:55162'))
        call_id=runtime.service.call_id
        runtime.service._lock.release()
        assert not await pending
        assert runtime.service.engine is engine and not engine.closed
        assert runtime.service.call_id==call_id and runtime.service.call_state=='incoming'
        runtime.service._event(engine,dict(state='ended'))
        assert await runtime.foreground()
        assert engine.closed and runtime.service.engine is not engine
        assert runtime.service.status()['registered']
        replacement=runtime.service.engine
        assert not await runtime.foreground()  # existing five-second restart bound
        assert runtime.service.engine is replacement
        await runtime.close()
    asyncio.run(run())


def test_system_call_failures_are_visible_and_clear_without_connecting(tmp_path):
    Engine.instances.clear()
    capability = {'calling_available': True, 'microphone_permission': 'granted',
                  'system_call_error': 'iOS could not show this call. Please try again.'}
    runtime = NextSIPRuntime(tmp_path, device=True, vault=Vault(), engine_factory=Engine,
                            capability_provider=lambda: capability)
    assert runtime.status()['error'] == capability['system_call_error']
    capability['system_call_error'] = ''
    assert not runtime.status().get('error')
    for invalid in ('private\ninternal', 'x' * 241, {'unsafe': True}):
        capability['system_call_error'] = invalid
        assert runtime.status()['system_call_error'] == ''
    assert not Engine.instances and not (tmp_path/'sip/accounts.json').exists()


if __name__ == "__main__":
    import tempfile
    checks = [test_actual_service_constructs_without_connecting_or_disclosing_password,
              test_actual_http_save_connect_disconnect_and_keychain_removal,
              test_simulator_accounts_cannot_start_even_when_a_native_bridge_exists,
              test_corrupt_accounts_are_preserved_without_disabling_other_services,
              test_native_route_change_retires_old_engine_and_obeys_allowed_networks,
              test_actual_private_server_protects_sip_routes,
              test_linked_call_routes_require_the_displayed_call_identity,
              test_reading_microphone_status_never_connects_or_requests_access,
              test_system_call_failures_are_visible_and_clear_without_connecting,
              test_foreground_refresh_preserves_active_calls_and_disabled_accounts,
              test_foreground_refresh_rechecks_calls_after_waiting_for_the_service_lock]
    for check in checks:
        with tempfile.TemporaryDirectory(prefix="next-private-sip-runtime-") as folder:
            check(Path(folder))
    print(f"All {len(checks)} staged SIP account, HTTP, route and isolation checks passed; no real registrations.")
