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
            row=(await response.json())['interface_stats']['interfaces'][0]
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


def test_radio_stats_do_not_invent_a_battery_reading(monkeypatch):
    radio=type('IOSRNodeInterface', (), {'name':'neXt TCP saved', 'ble':SimpleNamespace(connected=True), 'r_battery_state':0})()
    monkeypatch.setattr(RNS.Transport, 'interfaces', [radio])
    async def run():
        runtime=fixture(); raw=runtime.probe.reticulum.get_interface_stats()
        raw['interfaces'][0]['battery_percent']=0
        runtime.probe.reticulum.get_interface_stats=lambda:raw
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.get('/api/v1/interface-stats')
            result=await response.json(); assert set(result)=={'interface_stats'}
            row=result['interface_stats']['interfaces'][0]
            assert row['bluetooth_connected'] is True and 'battery_percent' not in row
            assert raw['interfaces'][0]['battery_percent']==0
    asyncio.run(run())


def test_chat_header_path_actions_use_released_routes_and_block_guard(monkeypatch):
    sent=[]
    monkeypatch.setattr(RNS.Transport, 'request_path', lambda address:sent.append(address))
    async def run():
        runtime=fixture();app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/destination/'+'cd'*16+'/request-path',json={})
            assert response.status==200 and sent==[bytes.fromhex('cd'*16)]
            response=await client.post('/api/v1/destination/'+'ab'*16+'/request-path',json={})
            assert response.status==400 and len(sent)==1
            for body in ({'timeout':0},{'timeout':601},{'destination_hash':'ef'*16}):
                response=await client.post('/api/v1/destination/'+'cd'*16+'/path',json=body)
                assert response.status==400 and len(sent)==1
    asyncio.run(run())


def test_path_wait_stops_after_a_destination_is_blocked(monkeypatch):
    monkeypatch.setattr(RNS.Transport, 'has_path', lambda address:False)
    async def run():
        runtime=fixture();started=asyncio.Event();sent=[]
        runtime.path=lambda address:{'path':None,'path_stale':True,'path_unresponsive':False}
        def prepare(address):sent.append(address);started.set()
        runtime.prepare_request=prepare
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            task=asyncio.create_task(client.post('/api/v1/destination/'+'cd'*16+'/path',json={'timeout':5}))
            await asyncio.wait_for(started.wait(),1)
            runtime.blocked=lambda address:True
            response=await asyncio.wait_for(task,1)
            assert response.status==400 and sent==[bytes.fromhex('cd'*16)]
            assert runtime.waits._value==2
    asyncio.run(run())


def test_path_wait_returns_new_route_without_duplicate_requests(monkeypatch):
    known=False
    monkeypatch.setattr(RNS.Transport, 'has_path', lambda address:known)
    async def run():
        runtime=fixture();sent=[]
        def snapshot(address):return {'path':{'hops':2,'next_hop':'ef'*16,'next_hop_interface':'Fixture'} if known else None,'path_stale':not known,'path_unresponsive':False}
        runtime.path=snapshot
        def prepare(address):
            nonlocal known
            known=True;sent.append(address)
        runtime.prepare_request=prepare
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/destination/'+'cd'*16+'/path?timeout=2',json={})
            assert response.status==200 and (await response.json())['path']['hops']==2
            response=await client.post('/api/v1/destination/'+'cd'*16+'/path',json={})
            assert response.status==200 and len(sent)==1
            assert runtime.waits._value==2
    asyncio.run(run())


@pytest.mark.parametrize('timeout',[True,1.5,float('inf'),float('nan')])
def test_malformed_body_timeout_cannot_transmit(timeout,monkeypatch):
    monkeypatch.setattr(RNS.Transport,'request_path',lambda *args:pytest.fail('Invalid timeout transmitted'))
    async def run():
        runtime=fixture();app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/destination/'+'cd'*16+'/path',json={'timeout':timeout})
            assert response.status==400
    asyncio.run(run())


@pytest.mark.parametrize('hops', [0, 1, 2, 4])
def test_trace_reports_only_known_hops_without_transmitting(monkeypatch, hops):
    def forbidden(*args, **kwargs): raise AssertionError('A read-only trace transmitted')
    monkeypatch.setattr(RNS.Transport, 'request_path', forbidden)
    async def run():
        runtime=fixture(); runtime.probe.identity=SimpleNamespace(hash=b'd'*16)
        runtime.path=lambda address: {'path': {'hops': hops, 'next_hop': 'cd'*16,
                                             'next_hop_interface': 'Private test'},
                                      'path_stale': True, 'path_unresponsive': False}
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.get('/api/v1/rnpath/trace/'+'ef'*16)
            assert response.status==200 and response.headers['Cache-Control']=='no-store'
            value=await response.json()
            assert value['hops']==hops and value['path_stale'] is True
            assert value['path'][0]['hash']==(b'd'*16).hex()
            assert value['path'][-1]['hash']=='ef'*16 and value['path'][-1]['type']=='destination'
            assert len([row for row in value['path'] if row['type']=='hop'])==int(hops>1)
            unknown=[row for row in value['path'] if row['type']=='unknown']
            assert unknown==([{'type':'unknown','count':hops-2}] if hops>2 else [])
    asyncio.run(run())


def test_trace_missing_and_invalid_paths_do_not_request_or_change_settings(monkeypatch):
    calls=[];monkeypatch.setattr(RNS.Transport, 'request_path', lambda *a, **k:calls.append(a))
    async def run():
        runtime=fixture();runtime.path=lambda address:{'path':None}
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            missing=await client.get('/api/v1/rnpath/trace/'+'ef'*16)
            assert missing.status==200 and 'Request a path first' in (await missing.json())['error']
            invalid=await client.get('/api/v1/rnpath/trace/not-an-address')
            assert invalid.status==400
            assert not calls and len(runtime.probe.connections.snapshot())==1
    asyncio.run(run())


def probe_fixture(monkeypatch, status=None):
    runtime=fixture();identity=RNS.Identity()
    address=RNS.Destination.hash_from_name_and_identity('test.echo.request',identity).hex()
    monkeypatch.setattr(RNS.Identity,'recall',lambda destination:identity)
    monkeypatch.setattr(RNS.Transport,'has_path',lambda destination:True)
    monkeypatch.setattr(RNS.Transport,'hops_to',lambda destination:1)
    runtime.probe.reticulum.get_next_hop=lambda destination:bytes.fromhex('cd'*16)
    runtime.probe.reticulum.get_next_hop_if_name=lambda destination:'Private test'
    sent=[]
    class Packet:
        def __init__(self,target,data):
            assert target.hash.hex()==address
            self.data=data
        def pack(self): pass
        def send(self):
            sent.append(self.data)
            return SimpleNamespace(status=RNS.PacketReceipt.DELIVERED if status is None else status,
                                   proof_packet=SimpleNamespace(rssi=-70,snr=7),get_rtt=lambda:.125)
    monkeypatch.setattr(RNS,'Packet',Packet)
    return runtime,dict(destination_hash=address,full_name='test.echo.request',timeout=1),sent


def test_probe_uses_standard_receipt_result_contract_and_random_bounded_payloads(monkeypatch):
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch)
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',json={**body,'probes':2,'size':24,'wait':0})
            assert response.status==200 and response.headers['Cache-Control']=='no-store'
            value=await response.json()
            assert (value['sent'],value['delivered'],value['timeouts'],value['failed'])==(2,2,0,0)
            assert [row['probe_number'] for row in value['results']]==[1,2]
            assert all(row['rtt']==.125 and row['hops']==1 and row['reception_stats']=={'rssi':-70,'snr':7} for row in value['results'])
            assert len(sent)==2 and all(len(data)==24 for data in sent) and sent[0]!=sent[1]
            assert runtime.probe_slots._value==1
    asyncio.run(run())


@pytest.mark.parametrize('bad', [{'size':0},{'size':99999},{'size':True},{'probes':0},{'probes':51},
                                {'probes':1.5},{'wait':-1},{'wait':float('nan')},{'wait':float('inf')},
                                {'timeout':False},{'timeout':601},{'full_name':'wrong name'},
                                {'full_name':'test'},{'full_name':''},{'destination_hash':'invalid'},
                                {'unknown':True}])
def test_probe_rejects_invalid_input_before_any_packet(monkeypatch,bad):
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch)
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',json={**body,**bad})
            assert response.status==400 and not sent
            assert runtime.probe_slots._value==1
    asyncio.run(run())


def test_probe_rechecks_block_after_path_request_without_sending_probe(monkeypatch):
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch);blocked=[]
        runtime.blocked=lambda address:bool(blocked)
        monkeypatch.setattr(RNS.Transport,'has_path',lambda destination:False)
        runtime.prepare_request=lambda destination:blocked.append(destination)
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',json=body)
            assert response.status==400 and not sent and len(blocked)==1
            assert runtime.probe_slots._value==1
    asyncio.run(run())


@pytest.mark.parametrize('status,field',[(RNS.PacketReceipt.SENT,'timeouts'),(RNS.PacketReceipt.FAILED,'failed')])
def test_probe_reports_timeout_and_failure_without_claiming_delivery(monkeypatch,status,field):
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch,status)
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',json={**body,'timeout':.001})
            value=await response.json()
            assert response.status==200 and value['delivered']==0 and value[field]==1 and len(sent)==1
    asyncio.run(run())


def test_probe_cancelled_client_releases_slot_and_stops_next_packet(monkeypatch):
    import contextlib
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch,RNS.PacketReceipt.SENT)
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            task=asyncio.create_task(client.post('/api/v1/rnprobe',json={**body,'probes':3}))
            while not sent: await asyncio.sleep(.01)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await task
            for _ in range(30):
                if runtime.probe_slots._value==1:break
                await asyncio.sleep(.02)
            assert runtime.probe_slots._value==1 and len(sent)==1
    asyncio.run(run())


@pytest.mark.parametrize('payload', [b'{', b'x'*4097])
def test_probe_rejects_malformed_and_oversized_bodies(monkeypatch,payload):
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch)
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',data=payload)
            assert response.status==400 and not sent and runtime.probe_slots._value==1
    asyncio.run(run())


def test_probe_name_must_bind_to_the_recalled_identity(monkeypatch):
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch)
        wrong=RNS.Identity();monkeypatch.setattr(RNS.Identity,'recall',lambda destination:wrong)
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',json=body)
            assert response.status==400 and not sent and runtime.probe_slots._value==1
    asyncio.run(run())


def test_probe_blocked_contact_never_starts(monkeypatch):
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch);runtime.blocked=lambda address:True
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',json=body)
            assert response.status==400 and not sent and runtime.probe_slots._value==1
    asyncio.run(run())


def test_probe_stops_next_packet_when_blocked_during_result_lookup(monkeypatch):
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch);blocked=[]
        runtime.blocked=lambda address:bool(blocked)
        def next_hop(destination):blocked.append(True);return bytes.fromhex('cd'*16)
        runtime.probe.reticulum.get_next_hop=next_hop
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',json={**body,'probes':3})
            assert response.status==400 and len(sent)==1 and runtime.probe_slots._value==1
    asyncio.run(run())


def test_probe_batch_deadline_releases_slot_and_stops_next_packet(monkeypatch):
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch,RNS.PacketReceipt.SENT);runtime.PROBE_BUDGET=.05
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',json={**body,'probes':3})
            assert response.status==503 and len(sent)==1 and runtime.probe_slots._value==1
    asyncio.run(run())


def test_probe_rejects_nonfinite_adaptive_timeout(monkeypatch):
    import network_runtime
    monkeypatch.setattr(network_runtime,'path_response_window',lambda *args:float('nan'))
    async def run():
        runtime,body,sent=probe_fixture(monkeypatch);body.pop('timeout')
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/v1/rnprobe',json=body)
            assert response.status==400 and not sent and runtime.probe_slots._value==1
    asyncio.run(run())


def test_transport_blackhole_snapshot_matches_desktop_without_fetching_or_mutation(monkeypatch):
    entries={bytes.fromhex('ab'*16): {'source':bytes.fromhex('cd'*16),'until':1234567890,'reason':'Private fixture'},
             bytes.fromhex('ef'*16): {'source':None,'until':None,'reason':None}}
    monkeypatch.setattr(RNS.Transport, 'blackholed_identities', entries)
    monkeypatch.setattr(RNS.Transport, 'request_path', lambda *args,**kwargs:pytest.fail('Snapshot transmitted'))
    async def run():
        runtime=fixture()
        # Exercise the actual standard local-instance getter, not a fabricated
        # empty list. This does not start or mutate any real Reticulum instance.
        local=SimpleNamespace(is_connected_to_shared_instance=False)
        runtime.probe.reticulum.get_blackholed_identities=lambda:RNS.Reticulum.get_blackholed_identities(local)
        app=web.Application();runtime.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response=await client.get('/api/v1/reticulum/blackhole')
            assert response.status==200
            assert response.headers['Cache-Control']=='no-store'
            assert await response.json()=={'blackholed_identities':{
                'ab'*16:{'source':'cd'*16,'until':1234567890,'reason':'Private fixture'},
                'ef'*16:{'source':None,'until':None,'reason':None}}}
            assert RNS.Transport.blackholed_identities is entries
            del runtime.probe.reticulum.get_blackholed_identities
            response=await client.get('/api/v1/reticulum/blackhole')
            assert response.status==501 and 'unavailable' in (await response.json())['message']
    asyncio.run(run())
