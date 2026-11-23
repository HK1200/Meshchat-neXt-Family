"""Real signed provider hints from Family; no radios, Apple or public network."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import sys
import threading
import time
from types import SimpleNamespace
import uuid

import pytest
import RNS

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app/src/main/python'),str(ROOT/'ios/push-provider')]
from family_call_alerts import FamilyCallHints, bound_contact, route_for, set_route, reconcile_routes
from family_call_wake import destination_hash,voice_hash
from call_provider import CallProvider

@pytest.fixture
def fixture(tmp_path):
    own,peer=RNS.Identity(),RNS.Identity()
    address=destination_hash('lxmf.delivery',peer.get_public_key())
    voice=voice_hash(peer.get_public_key())
    state={'setup_complete':True,'voiceEnabled':True,'contacts':[{'id':7,'name':'Private approved name',
        'identityPublicKey':peer.get_public_key().hex(),'addresses':{'lxmf':address,'lxst':voice}}]}
    return SimpleNamespace(own=own,peer=peer,address=address,voice=voice,state=state,lock=threading.RLock(),folder=tmp_path,
        entry={'provider':'https://example.invalid','audience':'private-calls'})


def test_route_is_bound_to_one_current_approved_contact_without_an_entered_key(fixture):
    f=fixture; route=set_route(f.state,7,f.entry)
    assert route.public_key==f.peer.get_public_key().hex() and route.voice==f.voice
    original=copy.deepcopy(f.state)
    assert set(f.state['callAlertRoutes'])=={'7'}
    for entry in [{**f.entry,'provider':'http://example.invalid'},{**f.entry,'public_key':f.peer.get_public_key().hex()},
                  {**f.entry,'audience':'invalid/path'}]:
        with pytest.raises(ValueError):set_route(f.state,7,entry)
        assert f.state==original
    f.state['contacts'][0]['name']='A guardian rename'
    assert route_for(f.state,7)==route
    f.state['contacts'][0]['id']=8
    assert route_for(f.state,7) is None and route_for(f.state,8) is None
    reconcile_routes(f.state);assert f.state['callAlertRoutes']=={}


@pytest.mark.parametrize('change',['remove','voice','messaging','key','disabled'])
def test_no_hint_for_removed_unbound_or_disabled_contact(fixture,change):
    f=fixture;set_route(f.state,7,f.entry);sent=[]
    if change=='remove':f.state['contacts']=[]
    elif change=='voice':f.state['contacts'][0]['addresses']['lxst']='ab'*16
    elif change=='messaging':f.state['contacts'][0]['addresses']['lxmf']='ab'*16
    elif change=='key':f.state['contacts'][0]['identityPublicKey']='ab'*64
    else:f.state['voiceEnabled']=False
    sender=FamilyCallHints(f.own,f.state,f.lock,sender=lambda *args:sent.append(args))
    assert sender.start(7,uuid.uuid4().hex,f.voice) is None and sent==[]


@pytest.mark.parametrize('lost_ack',[False,True])
def test_family_signed_intent_reaches_actual_provider_and_cancel_is_ordered(fixture,lost_ack):
    f=fixture;set_route(f.state,7,f.entry);code=b'1'*32
    operations=[];alerts=[];received=threading.Event();state={}
    def post(route,operation,raw):
        if 'provider' not in state:
            provider=CallProvider('private-calls',{f.address:{'enrollment_hash':hashlib.sha256(code).hexdigest(),'allow_calls':True}},
                f.folder/'provider.sqlite3',lambda token,payload:alerts.append(payload))
            assert provider.register({'recipient_key':f.peer.get_public_key().hex(),'token':'ab'*32,
                'callers':[voice_hash(f.own.get_public_key())]},'Bearer '+code.hex())==204
            state['provider']=provider
        provider=state['provider'];packet=json.loads(raw);operations.append((operation,packet))
        assert set(packet)=={'recipient','call','sender','issued','signature'}
        if operation=='call-alert':
            result=provider.notify(packet,now=1000);received.set()
            return 503 if lost_ack else result
        result=provider.cancel(packet,now=1000)
        state['lookup']=provider.lookup(f.address,packet['call'],'Bearer '+code.hex(),now=1000)
        provider.database.close();return result
    sender=FamilyCallHints(f.own,f.state,f.lock,sender=post,wall_clock=lambda:1000)
    handle=sender.start(7,uuid.uuid4().hex,f.voice)
    assert handle is not None
    try:assert received.wait(5)
    finally:handle.cancel();handle.thread.join(timeout=6)
    assert not handle.thread.is_alive()
    assert [op for op,_ in operations]==['call-alert','call-cancel']
    assert len(alerts)==1 and state['lookup'][0]==200 and state['lookup'][1]['state']=='cancelled'
    from test_family_call_wake import unseal
    assert unseal({"recipient":f.peer},alerts[0])==operations[0][1]
    assert f.own.get_private_key().hex() not in json.dumps(operations)
    assert 'Private approved name' not in json.dumps(operations)


def test_revocation_during_inflight_post_cancels_the_original_attempt(fixture):
    f=fixture;set_route(f.state,7,f.entry);entered=threading.Event();release=threading.Event();ops=[]
    def post(route,operation,raw):
        ops.append(operation)
        if operation=='call-alert':entered.set();assert release.wait(5)
        return 204
    handle=FamilyCallHints(f.own,f.state,f.lock,sender=post).start(7,uuid.uuid4().hex,f.voice)
    try:
        assert entered.wait(5)
        with f.lock:f.state['contacts']=[]
    finally:release.set();handle.thread.join(timeout=6)
    assert not handle.thread.is_alive() and ops==['call-alert','call-cancel']


def test_ordinary_unconfigured_voice_does_not_contact_a_provider(fixture):
    f=fixture;sent=[]
    assert FamilyCallHints(f.own,f.state,f.lock,sender=lambda *args:sent.append(args)).start(7,uuid.uuid4().hex,f.voice) is None
    assert sent==[]


@pytest.fixture
def backend(fixture,monkeypatch):
    f=fixture;spec=importlib.util.spec_from_file_location('family_hint_backend_fixture',ROOT/'app/src/main/python/family_backend.py')
    module=importlib.util.module_from_spec(spec);previous=signal.signal
    try:spec.loader.exec_module(module)
    finally:signal.signal=previous
    module._root=f.folder;module._state=f.state;module._tcp_only=True;module._sessions={'private-session':time.time()+60}
    return module


def request(backend,action,**data):
    return json.loads(backend.request(json.dumps({'action':action,'payload':data})))


def test_actual_backend_route_api_needs_guardian_and_rolls_back_failed_save(backend,fixture,monkeypatch):
    f=fixture
    for action in ['call_alert_route_get','call_alert_route_set']:
        assert not request(backend,action,contactId=7,route=f.entry)['ok']
    assert 'callAlertRoutes' not in f.state
    assert request(backend,'call_alert_route_set',token='private-session',contactId=7,route=f.entry)['ok']
    original=copy.deepcopy(f.state)
    assert request(backend,'call_alert_route_get',token='private-session',contactId=7)['callAlertRoute']==f.entry
    def fail():raise OSError('simulated write failure')
    monkeypatch.setattr(backend,'_save',fail)
    assert not request(backend,'call_alert_route_set',token='private-session',contactId=7,route=None)['ok']
    assert f.state==original
    assert json.loads((f.folder/'state.json').read_text())==original


def test_voice_queues_hint_before_path_lookup_and_cancels_on_hangup(fixture,monkeypatch):
    from family_voice import FamilyVoice
    f=fixture;started=[];cancelled=[];looked=threading.Event()
    class Hints:
        def start(self,contact_id,call_id,address):
            started.append((contact_id,call_id,address))
            return SimpleNamespace(cancel=lambda:cancelled.append(call_id))
    def path(_):
        assert started,'Hint must be queued before starting path discovery'
        looked.set();return False
    monkeypatch.setattr(RNS.Transport,'has_path',path)
    monkeypatch.setattr(RNS.Transport,'request_path',lambda *_:None)
    voice=FamilyVoice(f.own,f.state,f.lock,lambda:None,gate=lambda _:True,autostart=False,hints=Hints())
    voice.phone=SimpleNamespace(active_call=None)
    voice.call(7);call_id=voice.call_id
    try:assert looked.wait(3)
    finally:
        voice.hangup(call_id)
        deadline=time.monotonic()+3
        while voice._dialling and time.monotonic()<deadline:time.sleep(.01)
    assert not voice._dialling and cancelled==[call_id]
    assert started==[(7,call_id,f.voice)]


def test_actual_contact_removal_clears_only_its_explicit_route(backend,fixture):
    f=fixture;set_route(f.state,7,f.entry)
    other=RNS.Identity();key=other.get_public_key()
    f.state['contacts'].append({'id':8,'name':'Another approved contact','identityPublicKey':key.hex(),
        'addresses':{'lxmf':destination_hash('lxmf.delivery',key),'lxst':voice_hash(key)}})
    set_route(f.state,8,f.entry)
    backend._snapshot=lambda:{'ok':True}
    contacts=copy.deepcopy(f.state['contacts'][1:])
    assert request(backend,'contacts',token='private-session',contacts=contacts)['ok']
    assert set(f.state['callAlertRoutes'])=={'8'}
    assert route_for(f.state,8) is not None
    assert request(backend,'contacts',token='private-session',contacts=[fixture.state['contacts'][0],
        {'id':7,'name':'Added again','identityPublicKey':f.peer.get_public_key().hex(),
         'addresses':{'lxmf':f.address,'lxst':f.voice}}])['ok']
    assert route_for(f.state,7) is None
