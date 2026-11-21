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


if __name__ == "__main__":
    import tempfile
    checks = [test_actual_service_constructs_without_connecting_or_disclosing_password,
              test_actual_http_save_connect_disconnect_and_keychain_removal,
              test_simulator_accounts_cannot_start_even_when_a_native_bridge_exists,
              test_corrupt_accounts_are_preserved_without_disabling_other_services,
              test_native_route_change_retires_old_engine_and_obeys_allowed_networks,
              test_actual_private_server_protects_sip_routes]
    for check in checks:
        with tempfile.TemporaryDirectory(prefix="next-private-sip-runtime-") as folder:
            check(Path(folder))
    print(f"All {len(checks)} staged SIP account, HTTP, route and isolation checks passed; no real registrations.")
