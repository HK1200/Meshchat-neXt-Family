"""Exercise real desktop handlers through the embedded iOS HTTP routes."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import os
import threading

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ['NEXT_TEST_BACKEND_SOURCE']).resolve()
assert (BACKEND/'meshchatnext/src/backend/rnpath_handler.py').is_file()
sys.path[:0] = [str(ROOT/'ios/NextRuntimeProbe'), str(BACKEND)]
from network_runtime import NetworkRuntime
import RNS


class Reticulum:
    def get_path_table(self, max_hops=None):
        return [{'hash': bytes.fromhex('ab'*16), 'hops': 2, 'via': bytes.fromhex('cd'*16),
                 'interface': 'neXt TCP saved', 'expires': 100, 'timestamp': 90}]
    def get_rate_table(self): return []
    def get_interface_stats(self):
        return {'interfaces': [{'name': 'TCPClientInterface[neXt TCP saved]', 'short_name': 'neXt TCP saved', 'hash': b'a'*16}]}


def fixture():
    peers = SimpleNamespace(snapshot=lambda: [dict(id='saved', host='127.0.0.1', port=4242, enabled=True, online=False)])
    return NetworkRuntime(SimpleNamespace(reticulum=Reticulum(), connections=peers), lambda address: address == 'ab'*16)


def test_reads_use_real_handlers_without_transmissions_or_setting_changes(monkeypatch):
    calls=[]
    monkeypatch.setattr(RNS.Transport, 'request_path', lambda *args, **kwargs: calls.append(args))
    async def run():
        runtime=fixture(); app=web.Application(); runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.get('/api/v1/rnpath/table?limit=50')
            assert response.status==200
            result=await response.json()
            assert result['total']==1 and result['table'][0]['hash']=='ab'*16
            response=await client.get('/api/v1/rnpath/table?search=not-present')
            assert (await response.json())['total']==0
            response=await client.get('/api/v1/rnstatus?show_all=true')
            assert response.status==200 and 'interfaces' in await response.json()
            response=await client.get('/api/v1/rnpath/rates')
            assert await response.json()=={'rates': []}
            response=await client.get('/api/v1/reticulum/interfaces')
            assert (await response.json())['interfaces']['neXt TCP saved']['interface_enabled'] is True
            response=await client.get('/api/v1/interface-stats')
            row=(await response.json())['interfaces'][0]
            assert row['hash']==(b'a'*16).hex() and row['interface_name']=='neXt TCP saved'
            assert not calls and runtime.probe.connections.snapshot()[0]['port']==4242
    asyncio.run(run())


@pytest.mark.parametrize('query', ['limit=-1', 'limit=1001', 'page=0', 'hops=NaN', 'max_hops=999',
                                   'remote=ab', 'identity_path=/private/key'])
def test_invalid_query_never_runs_sdk(query):
    async def run():
        runtime=fixture()
        runtime.paths.get_path_table=lambda **kwargs: pytest.fail('Invalid request reached SDK')
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.get('/api/v1/rnpath/table?'+query)
            assert response.status==400
    asyncio.run(run())


def test_path_request_requires_valid_unblocked_address(monkeypatch):
    sent=[]
    monkeypatch.setattr(RNS.Transport, 'request_path', lambda address: sent.append(address))
    async def run():
        runtime=fixture();app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            for body in ({'destination_hash':'ab'*16}, {'destination_hash':'x'},
                         {'destination_hash':'cd'*16, 'remote':True}, []):
                response=await client.post('/api/v1/rnpath/request',json=body)
                assert response.status==400 and sent==[]
            response=await client.post('/api/v1/rnpath/request',data=b'x'*4097)
            assert response.status==400 and sent==[]
            response=await client.post('/api/v1/rnpath/request',json={'destination_hash':'CD'*16})
            assert response.status==200 and await response.json()=={'success':True}
            assert sent==[bytes.fromhex('cd'*16)]
            runtime.blocked=lambda address: True
            response=await client.post('/api/v1/rnpath/request',json={'destination_hash':'cd'*16})
            assert response.status==400 and len(sent)==1
    asyncio.run(run())


def test_no_path_snapshot_is_read_only(monkeypatch):
    monkeypatch.setattr(RNS.Transport, 'has_path', lambda address:False)
    monkeypatch.setattr(RNS.Transport, 'request_path', lambda address:pytest.fail('GET transmitted'))
    async def run():
        runtime=fixture();app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.get('/api/v1/destination/'+'ab'*16+'/path')
            assert response.status==200 and (await response.json())['path'] is None
            response=await client.get('/api/v1/destination/'+'ab'*16+'/path?request=true')
            assert response.status==400
            response=await client.get('/api/v1/destination/invalid/path')
            assert response.status==400
    asyncio.run(run())


def test_cancelled_reader_holds_slot_until_worker_stops():
    async def run():
        runtime=fixture();release=threading.Event();started=threading.Event()
        def slow():started.set();release.wait(5)
        task=asyncio.create_task(runtime.read(slow))
        while not started.is_set():await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert runtime.reads._value==1
        release.set()
        for _ in range(100):
            if runtime.reads._value==2:break
            await asyncio.sleep(0.01)
        assert runtime.reads._value==2
    asyncio.run(run())


def test_known_and_own_paths_match_the_conversation_header_contract(monkeypatch):
    import network_runtime
    monkeypatch.setattr(RNS.Transport, 'has_path', lambda address:True)
    monkeypatch.setattr(RNS.Transport, 'hops_to', lambda address:2)
    monkeypatch.setattr(network_runtime, 'path_metadata_for_api', lambda address:{'path_stale':False,'path_unresponsive':False})
    async def run():
        runtime=fixture()
        runtime.probe.source=SimpleNamespace(hash=b'i'*16,identity=SimpleNamespace(hash=b'j'*16))
        runtime.probe.reticulum.get_next_hop=lambda address: b'v'*16
        runtime.probe.reticulum.get_next_hop_if_name=lambda address:'neXt TCP saved'
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.get('/api/v1/destination/'+'cd'*16+'/path')
            assert await response.json()=={'path':{'hops':2,'next_hop':(b'v'*16).hex(),'next_hop_interface':'neXt TCP saved'},'path_stale':False,'path_unresponsive':False}
            response=await client.get('/api/v1/destination/'+(b'i'*16).hex()+'/path')
            assert (await response.json())['path']=={'hops':0,'next_hop':(b'i'*16).hex(),'next_hop_interface':'Local'}
    asyncio.run(run())
