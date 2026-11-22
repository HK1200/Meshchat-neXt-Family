"""Private timed location and final Bluetooth handoff; no GPS, radio or internet."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import os
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ['NEXT_TEST_BACKEND_SOURCE']).resolve()
assert (BACKEND/'meshchatnext/src/backend/meshcore_private_location.py').is_file()
sys.path[:0] = [str(ROOT/'ios/NextRuntimeProbe'), str(BACKEND), str(ROOT/'app/src/main/python')]
from meshcore_runtime import NextMeshCore, NATIVE_LOCATION_GUARD, protect_native_location_writes
from location_runtime import LocationRuntime
from location_sessions import Session
from meshchatnext.src.backend.meshcore_private_location import WRITE_GUARD, LocationPermissionChanged
from meshchatnext.src.backend.meshcore_store import MeshCoreStore

OWNER, PEER = 'ab'*32, 'cd'*32


def adapter(tmp_path):
    store = MeshCoreStore(tmp_path/'mesh.sqlite3')
    store.bind(OWNER, 'Own companion')
    store.replace_contacts(OWNER, {'user':{'public_key':PEER,'adv_name':'Private user','type':1},
                                 'room':{'public_key':'ef'*32,'adv_name':'Room','type':3}})
    service = SimpleNamespace(_store=store)
    rows = [dict(id='saved-radio',owner=OWNER,connected=True)]
    def resolve(radio, owner):
        if radio != 'saved-radio' or owner != OWNER: raise ValueError('Identity changed')
        return service
    mesh = NextMeshCore.__new__(NextMeshCore)
    mesh.fleet = SimpleNamespace(radio_rows=lambda:rows,resolve=resolve)
    return mesh, store, service, rows


def test_only_saved_unambiguous_users_with_existing_share_consent_are_offered(tmp_path):
    async def run():
        mesh, store, _, rows = adapter(tmp_path)
        assert await mesh.location_recipients() == {}
        policy = store.configure_private_location(OWNER,PEER,False,True)
        peers = await mesh.location_recipients()
        key = 'meshcore:'+OWNER+':'+PEER+':'+policy['generation']
        assert set(peers)=={key} and peers[key]['generation']==policy['generation']
        assert peers[key]['online'] and peers[key]['service']=='meshcore'
        rows[0]['connected']=False
        assert not (await mesh.location_recipients())[key]['online']
        store.configure_private_location(OWNER,PEER,False,False,generation=policy['generation'])
        assert await mesh.location_recipients()=={}
        store.configure_private_location(OWNER,PEER,False,True)
        store.replace_contacts(OWNER,{'collision':{'public_key':PEER[:12]+'00'*26,'type':1},
                                    'user':{'public_key':PEER,'type':1}})
        assert await mesh.location_recipients()=={}
    asyncio.run(run())


def test_transport_rechecks_native_consent_after_waiting_for_write_lock():
    async def run():
        entered=asyncio.Event();release=asyncio.Event();sent=[];allowed=True
        async def original(data):
            entered.set();await release.wait()
            # Same final-to-thread guard used by the pinned AndroidConnection.
            await asyncio.to_thread(lambda:WRITE_GUARD.get()())
            sent.append(data)
        transport=protect_native_location_writes(SimpleNamespace(send=original))
        async def asynchronous():return True
        token=NATIVE_LOCATION_GUARD.set((asynchronous,lambda:allowed))
        try:task=asyncio.create_task(transport.send(b'private encrypted frame'))
        finally:NATIVE_LOCATION_GUARD.reset(token)
        await entered.wait();allowed=False;release.set()
        with pytest.raises(LocationPermissionChanged):await task
        assert sent==[] and WRITE_GUARD.get() is None and NATIVE_LOCATION_GUARD.get() is None
    asyncio.run(run())


def test_ordinary_commands_and_backend_policy_guards_are_preserved():
    async def run():
        sent=[];checks=[]
        async def original(data):
            gate=WRITE_GUARD.get()
            if gate:gate()
            sent.append(data)
            return len(data)
        transport=protect_native_location_writes(SimpleNamespace(send=original))
        assert await transport.send(b'normal chat')==11
        async def yes():return True
        token=NATIVE_LOCATION_GUARD.set((yes,lambda:True))
        inner=WRITE_GUARD.set(lambda:checks.append('original permission'))
        try:assert await transport.send(b'private fix')==11
        finally:WRITE_GUARD.reset(inner);NATIVE_LOCATION_GUARD.reset(token)
        assert checks==['original permission'] and sent==[b'normal chat',b'private fix']
    asyncio.run(run())


def test_native_location_routes_only_to_selected_full_identity_and_restores_context(tmp_path):
    async def run():
        mesh, store, service, _ = adapter(tmp_path)
        store.configure_private_location(OWNER,PEER,False,True)
        target=next(iter((await mesh.location_recipients()).values()));calls=[]
        async def call(*args,**kwargs):
            assert NATIVE_LOCATION_GUARD.get() is not None
            calls.append((args,kwargs));return {'state':'accepted'}
        service.call=call
        async def yes():return True
        assert await mesh.send_native_location(target,{'synthetic':True},yes,lambda:True)
        args,body=calls[0]
        assert args==('messages','send_private_location')
        assert body['expected_owner']==OWNER and body['peer']==PEER and body['generation']==target['generation']
        assert NATIVE_LOCATION_GUARD.get() is None
        async def no():return False
        assert not await mesh.send_native_location(target,{},no,lambda:True) and len(calls)==1
    asyncio.run(run())


@pytest.mark.parametrize('change',['stop','expiry','replacement','generation','foreground'])
def test_location_runtime_final_native_gate_rejects_revocation(tmp_path,change):
    async def run():
        history=SimpleNamespace(conversation_entries=lambda:{})
        telemetry=SimpleNamespace(settings=lambda:{'location_source':'browser'})
        probe=SimpleNamespace(source=SimpleNamespace(identity=SimpleNamespace(hash=b'i'*16)))
        async def native(_):return {'ok':True}
        runtime=LocationRuntime(tmp_path,probe,history,telemetry,native=native)
        target=dict(owner=OWNER,address=PEER,service='meshcore',generation='c'*32);key='meshcore:'+OWNER+':'+PEER+':'+target['generation']
        session=Session(time.time()+900,'15','a'*32,False)
        runtime.manager.sessions[key]=session;runtime.manager.armed=True;runtime.manager.native_generation=5
        state=dict(ok=True,can_submit=True,generation=5,foreground=True)
        runtime.native_write_status=lambda:state
        fix=dict(latitude=48.,longitude=-122.,last_update=time.time())
        async def yes():return True
        async def send(_target,_fix,asynchronous,synchronous):
            assert await asynchronous() and synchronous()
            if change=='stop':runtime.manager.armed=False
            elif change=='expiry':runtime.manager.clock=lambda:session.until+1
            elif change=='replacement':runtime.manager.sessions[key]=Session(session.until,'15','b'*32,False)
            elif change=='generation':state['generation']=6
            elif change=='foreground':state['foreground']=False
            assert not synchronous();return False
        runtime.meshcore=SimpleNamespace(send_native_location=send)
        try:assert not await runtime.transmit(target,fix,yes)
        finally:await runtime.close()
    asyncio.run(run())


def test_regranting_private_permission_never_reuses_the_old_native_target(tmp_path):
    async def run():
        mesh, store, _, _ = adapter(tmp_path)
        first=store.configure_private_location(OWNER,PEER,False,True)
        old=set(await mesh.location_recipients())
        second=store.configure_private_location(OWNER,PEER,False,False,generation=first['generation'])
        store.configure_private_location(OWNER,PEER,False,True,generation=second['generation'])
        fresh=set(await mesh.location_recipients())
        assert len(old)==len(fresh)==1 and not old.intersection(fresh)
    asyncio.run(run())


def test_actual_pinned_transport_denies_revoked_native_permission_without_disconnecting():
    async def run():
        from meshchatnext.src.backend.meshcore_transport import AndroidConnection
        written=[];ready=asyncio.Event();allowed=True
        connection=AndroidConnection('ble','fixture',native_factory=lambda *_:None)
        connection._connected=True
        connection._native=SimpleNamespace(send=lambda packet:written.append(packet))
        protect_native_location_writes(connection)
        await connection._write.acquire()
        async def check():ready.set();return True
        token=NATIVE_LOCATION_GUARD.set((check,lambda:allowed))
        try:task=asyncio.create_task(connection.send(b'private encrypted location'))
        finally:NATIVE_LOCATION_GUARD.reset(token)
        await ready.wait();allowed=False;connection._write.release()
        with pytest.raises(LocationPermissionChanged):await task
        assert written==[] and connection.is_connected and connection.failure_reason is None
    asyncio.run(run())


def test_native_status_read_failure_is_a_permission_denial_not_radio_disconnect():
    async def run():
        async def original(_):WRITE_GUARD.get()()
        connection=protect_native_location_writes(SimpleNamespace(send=original))
        async def yes():return True
        def unavailable():raise RuntimeError('Native permission unavailable')
        token=NATIVE_LOCATION_GUARD.set((yes,unavailable))
        try:
            with pytest.raises(LocationPermissionChanged):await connection.send(b'fix')
        finally:NATIVE_LOCATION_GUARD.reset(token)
    asyncio.run(run())


def test_actual_transport_rechecks_again_inside_native_send_thread():
    async def run():
        from meshchatnext.src.backend.meshcore_transport import AndroidConnection
        written=[];checks=[]
        connection=AndroidConnection('ble','fixture',native_factory=lambda *_:None)
        connection._connected=True;connection._native=SimpleNamespace(send=lambda packet:written.append(packet))
        protect_native_location_writes(connection)
        async def yes():return True
        def changed_between_handoffs():
            checks.append(True)
            return len(checks)==1
        token=NATIVE_LOCATION_GUARD.set((yes,changed_between_handoffs))
        try:
            with pytest.raises(LocationPermissionChanged):await connection.send(b'private fix')
        finally:NATIVE_LOCATION_GUARD.reset(token)
        assert len(checks)==2 and written==[] and connection.is_connected and connection.failure_reason is None
    asyncio.run(run())


def test_actual_transport_permits_one_consented_private_frame_and_restores_scope():
    async def run():
        from meshchatnext.src.backend.meshcore_transport import AndroidConnection
        written=[];checks=[];loop=asyncio.get_running_loop()
        connection=AndroidConnection('ble','fixture',native_factory=lambda *_:None)
        connection._connected=True
        def send(packet):
            written.append(packet)
            loop.call_soon_threadsafe(connection._written.set_result,True)
        connection._native=SimpleNamespace(send=send)
        protect_native_location_writes(connection)
        async def yes():return True
        def consent():checks.append(True);return True
        token=NATIVE_LOCATION_GUARD.set((yes,consent))
        try:await connection.send(b'private fix')
        finally:NATIVE_LOCATION_GUARD.reset(token)
        assert written==[b'private fix'] and len(checks)==2
        assert WRITE_GUARD.get() is None and NATIVE_LOCATION_GUARD.get() is None
    asyncio.run(run())


def test_background_permission_retains_native_gate_but_allows_a_locked_private_send(tmp_path):
    async def run():
        probe=SimpleNamespace(source=SimpleNamespace(identity=SimpleNamespace(hash=b'i'*16)))
        history=SimpleNamespace(conversation_entries=lambda:{})
        telemetry=SimpleNamespace(settings=lambda:{'location_source':'browser'})
        async def native(_):return {'ok':True}
        runtime=LocationRuntime(tmp_path,probe,history,telemetry,native=native)
        target=dict(owner=OWNER,address=PEER,service='meshcore',generation='c'*32)
        key='meshcore:'+OWNER+':'+PEER+':'+target['generation']
        runtime.manager.sessions[key]=Session(time.time()+900,'15','a'*32,True)
        runtime.manager.armed=True;runtime.manager.native_generation=5
        runtime.native_write_status=lambda:dict(ok=True,can_submit=True,generation=5,foreground=False)
        async def yes():return True
        async def send(_target,fix,asynchronous,synchronous):
            assert await asynchronous() and synchronous()
            assert fix['latitude']==48. and fix['speed']==2
            return True
        runtime.meshcore=SimpleNamespace(send_native_location=send)
        try:assert await runtime.transmit(target,dict(latitude=48.,longitude=-122.,last_update=time.time(),speed=2),yes)
        finally:await runtime.close()
    asyncio.run(run())


def test_catalog_combines_services_without_enabling_meshcore_permission_or_gps(tmp_path):
    async def run():
        mesh,store,_,_=adapter(tmp_path)
        policy=store.configure_private_location(OWNER,PEER,False,True)
        probe=SimpleNamespace(source=SimpleNamespace(identity=SimpleNamespace(hash=b'i'*16)),online=True)
        history=SimpleNamespace(conversation_entries=lambda:{'12'*16:{'name':'Reticulum user'}})
        source='browser';requests=[]
        telemetry=SimpleNamespace(settings=lambda:{'location_source':source})
        async def native(request):requests.append(request);return {'ok':True}
        runtime=LocationRuntime(tmp_path,probe,history,telemetry,native=native);runtime.meshcore=mesh
        try:
            rows=await runtime.catalog()
            assert {row['service'] for row in rows.values()}=={'reticulum','meshcore'}
            assert store.private_location_policy(OWNER,PEER)==policy and requests==[]
            source='disabled'
            assert await runtime.catalog()=={} and requests==[]
            source='manual'
            assert await runtime.catalog()=={} and requests==[]
        finally:await runtime.close()
    asyncio.run(run())
