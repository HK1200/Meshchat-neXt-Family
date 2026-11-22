"""Native adapter contracts; no Bluetooth access or RF transmissions."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

PROBE = Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"
sys.path.insert(0, str(PROBE))
import meshcore_runtime as runtime

UUID = "c890bd27-5ed4-4a28-aed6-e64892abb835"


@pytest.fixture(autouse=True)
def family_path(monkeypatch):
    monkeypatch.syspath_prepend(str(PROBE.parents[1] / "app/src/main/python"))


def test_only_explicit_ios_bluetooth_uuid_is_allowed():
    assert runtime.ble_target("ble", UUID, device=True) == UUID.upper()
    for kind, target in [("usb", UUID), ("ble", "AA:BB:CC:DD:EE:FF"), ("ble", ""), ("ble", None)]:
        with pytest.raises(ValueError):
            runtime.ble_target(kind, target, device=True)
    with pytest.raises(ValueError, match="simulator"):
        runtime.ble_target("ble", UUID, device=False)


def test_session_constructs_native_adapter_without_opening_radio(monkeypatch):
    calls = []
    class Session:
        def __init__(self, *, connection_factory):
            self.factory = connection_factory
    def connection(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(send=lambda data:None)
    monkeypatch.setitem(sys.modules, "meshchatnext.src.backend.meshcore_session", SimpleNamespace(MeshCoreSession=Session))
    monkeypatch.setitem(sys.modules, "meshchatnext.src.backend.meshcore_transport", SimpleNamespace(AndroidConnection=connection))
    session = runtime.session_factory(device=True)
    assert not calls
    session.factory("ble", UUID, timeout=3)
    from family_ios_bluetooth import NativeSession
    assert calls[0][0] == ("ble", UUID.upper())
    assert calls[0][1] == {"native_factory": NativeSession, "timeout": 3}
    with pytest.raises(ValueError):
        session.factory("usb", "/dev/usb")
    assert len(calls) == 1


def test_discovery_does_not_connect_and_is_disabled_on_simulator(monkeypatch):
    import family_ios_bluetooth
    calls = []
    def request(operation):
        calls.append(operation)
        return {"devices": [{"id": UUID, "name": "Fairside J"}]} if operation == "devices" else {}
    async def immediate(_seconds): pass
    monkeypatch.setattr(family_ios_bluetooth, "request", request)
    monkeypatch.setattr(runtime.asyncio, "sleep", immediate)
    assert asyncio.run(runtime.bluetooth_devices(device=False)) == []
    assert not calls
    assert asyncio.run(runtime.bluetooth_devices(device=True)) == [{"address": UUID, "name": "Fairside J"}]
    assert calls == ["scan", "devices"]


def test_radio_http_selection_and_simulator_isolation(monkeypatch):
    delegated = []
    def register(routes, owner):
        async def original(request):
            delegated.append((request.method, request.match_info['action']))
            return web.json_response({"result": "delegated"})
        routes.get('/api/v1/meshcore/{action}')(original)
        routes.post('/api/v1/meshcore/{action}')(original)
    monkeypatch.setitem(sys.modules, 'meshchatnext.src.backend.meshcore_http', SimpleNamespace(register_meshcore_routes=register))

    async def exercise(device):
        adapter = runtime.NextMeshCore.__new__(runtime.NextMeshCore)
        adapter.device = device
        adapter.owner = object()
        app = web.Application()
        adapter.register(app.router)
        async with TestClient(TestServer(app)) as client:
            assert (await client.get('/api/v1/meshcore/usb-devices')).status == 200
            assert not delegated
            response = await client.post('/api/v1/meshcore/radio-add', json={"kind":"usb", "target":"/dev/usb"})
            assert response.status == (400 if device else 403)
            assert not delegated
            response = await client.post('/api/v1/meshcore/radio-add', json={"kind":"ble", "target":UUID})
            assert response.status == (200 if device else 403)
            assert len(delegated) == int(device)
    asyncio.run(exercise(False))
    asyncio.run(exercise(True))


def test_backend_hash_rejected_before_mutating_destination(tmp_path):
    spec = importlib.util.spec_from_file_location('next_backend_stager', PROBE / 'stage-backend.py')
    stager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stager)
    wheel = tmp_path / 'wrong.whl'
    wheel.write_bytes(b'not the release wheel')
    destination = tmp_path / 'staged'
    with pytest.raises(ValueError, match='checksum'):
        stager.stage(wheel, destination, tmp_path)
    assert not destination.exists()
