"""Real telemetry format and transport boundary without GPS or radio traffic."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import time
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'ios/NextRuntimeProbe'), str(ROOT/'app/src/main/python')]
from location_runtime import LocationRuntime


class Probe:
    source = SimpleNamespace(identity=SimpleNamespace(hash=b'i'*16))
    online = True
    def __init__(self): self.composed=[];self.sent=[]
    def compose(self, *args, **kwargs):
        self.composed.append((args, kwargs))
        return SimpleNamespace(pack=lambda:None)
    def send(self, message): self.sent.append(message)


def fixture(tmp_path, source='browser'):
    probe=Probe()
    history=SimpleNamespace(conversation_entries=lambda:{'ab'*16:{'name':'Private fixture'}})
    telemetry=SimpleNamespace(settings=lambda:{'location_source':source})
    async def native(request):return {'ok':True}
    return LocationRuntime(tmp_path, probe, history, telemetry, native=native)


def test_catalog_uses_own_identity_and_existing_contacts_only(tmp_path):
    async def run():
        runtime=fixture(tmp_path)
        try:
            rows=await runtime.catalog()
            assert rows=={f"reticulum:{(b'i'*16).hex()}:{'ab'*16}":{
                'name':'Private fixture','service':'reticulum','online':True,'address':'ab'*16}}
            runtime.telemetry.settings=lambda:{'location_source':'manual'}
            assert await runtime.catalog()=={}
            runtime.telemetry.settings=lambda:{'location_source':'disabled'}
            assert await runtime.catalog()=={}
        finally:await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize('permitted',[True,False])
def test_direct_telemetry_rechecks_consent_after_pathfinding_and_never_uses_mailbox(tmp_path,permitted):
    async def run():
        import LXMF
        runtime=fixture(tmp_path)
        async def guard():return permitted
        fix={'latitude':48.75,'longitude':-122.48,'accuracy':10,'speed':2,'last_update':time.time()}
        try:
            accepted=await runtime.transmit({'address':'ab'*16},fix,guard)
            assert accepted is permitted and len(runtime.probe.sent)==int(permitted)
            args,kwargs=runtime.probe.composed[0]
            assert args[0]=='' and set(args[2])=={LXMF.FIELD_TELEMETRY}
            from meshchatnext.src.backend.telemetry_utils import Telemeter
            assert Telemeter.from_packed(args[2][LXMF.FIELD_TELEMETRY])['location']['speed']==7.2
            assert kwargs=={'delivery_method':'direct','propagation_node':None}
        finally:await runtime.close()
    asyncio.run(run())


def test_http_controls_are_bounded_and_get_never_starts_location(tmp_path):
    async def run():
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        runtime=fixture(tmp_path);commands=[]
        async def native(request):commands.append(request);return {'ok':True}
        runtime.manager.native=native
        app=web.Application();runtime.register(app.router)
        try:
            async with TestClient(TestServer(app)) as client:
                response=await client.get('/api/v1/preview/location-sessions')
                assert response.status==200 and not (await response.json())['active'] and commands==[]
                for body in ({'action':'broadcast'}, {'action':'start','targets':[],'duration':'15'},
                             {'action':'stop','extra':'no'}, {'action':'start','targets':['x'*5000],'duration':'15'}):
                    response=await client.post('/api/v1/preview/location-sessions',json=body)
                    assert response.status==400 and commands==[]
                target=next(iter(await runtime.catalog()))
                response=await client.post('/api/v1/preview/location-sessions',json={
                    'action':'start','targets':[target],'duration':'15','request_id':'a'*32,'consent_epoch':0})
                assert response.status==200 and (await response.json())['active']
                assert commands[-1]['op']=='start' and commands[-1]['background'] is False
                response=await client.post('/api/v1/preview/location-sessions',json={'action':'stop'})
                assert response.status==200 and not (await response.json())['active']
                assert commands[-1]['op']=='stop' and commands[-1]['revisions']==[]
        finally:await runtime.close()
    asyncio.run(run())
