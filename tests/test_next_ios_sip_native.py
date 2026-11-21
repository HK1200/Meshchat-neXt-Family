"""SIP adapter lifecycle and call-identity tests; no actual registrations."""
import asyncio
from pathlib import Path
import sys
import uuid

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe'))
from sip_native import IOSPasswords, IOSSIPEngine, networks


class Native:
    def __init__(self):self.calls=[];self.passwords={};self.events=[]
    def __call__(self,row):
        self.calls.append(row.copy());op=row['op']
        if op=='password-save':self.passwords[row['account']]=row['password']
        if op=='password-load':return {'ok':True,'value':self.passwords[row['account']]}
        if op=='password-remove':self.passwords.pop(row['account'],None)
        if op=='poll':
            events,self.events=self.events,[]
            return {'ok':True,'events':events}
        if op=='close':return {'ok':True,'closed':True}
        return {'ok':True}


def test_constructing_engine_or_vault_does_not_connect():
    native=Native();IOSSIPEngine(request=native);IOSPasswords(request=native)
    assert native.calls==[]


def test_password_adapter_uses_native_slots_and_validates_inputs():
    native=Native();vault=IOSPasswords(native);account=str(uuid.uuid4())
    vault.save(account,'private SIP test')
    assert vault.load(account,interactive=False)=='private SIP test'
    vault.remove(account)
    assert not native.passwords
    for value in ['not-a-uuid','../other']:
        with pytest.raises(ValueError):vault.save(value,'private dummy')
    for password in [None,'','bad\0password','é'*129]:
        with pytest.raises(ValueError):vault.save(account,password)


def test_networks_report_only_the_actual_default_route():
    route={'kind':'wifi','interface':'ios-default-1','address':'default'}
    assert networks(lambda _: {'networks':[route]})==[route]
    assert networks(lambda _: {'networks':[]})==[]
    with pytest.raises(ValueError):networks(lambda _: {'networks':[route,dict(route,kind='mobile')]})
    with pytest.raises(ValueError):networks(lambda _: {'networks':[dict(route,kind='unknown')]})


def test_stale_call_events_cannot_end_or_replace_the_current_call():
    engine=IOSSIPEngine(request=Native());seen=[];engine.on_event=seen.append
    engine.deliver({'state':'incoming','peer':'sip:test@127.0.0.1','native_id':'first'})
    engine.deliver({'state':'ended','peer':'','native_id':'other'})
    engine.deliver({'state':'connected','peer':'','native_id':'other'})
    assert len(seen)==1 and engine._call_id=='first'
    engine.deliver({'state':'connected','peer':'','native_id':'first'})
    engine.deliver({'state':'ended','peer':'','native_id':'first'})
    assert [row['state'] for row in seen]==['incoming','connected','ended']
    assert not engine._call_id


def test_start_is_explicit_and_call_controls_use_exact_native_call_id():
    async def exercise():
        native=Native();engine=IOSSIPEngine(request=native,poll_interval=10)
        await engine.launch()
        try:
            assert [row['op'] for row in native.calls]==['open']
            await engine.command('start',user='9001',host='127.0.0.1',port=55162,password='private dummy')
            assert any(row['op']=='start' for row in native.calls)
            engine.deliver({'state':'incoming','peer':'sip:test@127.0.0.1','native_id':'current-call'})
            await engine.command('answer');await engine.command('mute',value=True)
            controls=[row for row in native.calls if row['op'] in ('answer','mute')]
            assert all(row['call_id']=='current-call' for row in controls)
            engine.deliver({'state':'ended','peer':'','native_id':'current-call'})
            before=len(native.calls)
            with pytest.raises(ValueError):await engine.command('hangup')
            assert len(native.calls)==before
        finally:await engine.close()
        assert not engine.running and native.calls[-1]['op']=='close'
    asyncio.run(exercise())


def test_rejected_dial_does_not_leave_a_phantom_call():
    async def exercise():
        native=Native()
        def request(row):
            if row['op']=='dial':raise ConnectionError('private test rejection')
            return native(row)
        engine=IOSSIPEngine(request=request,poll_interval=10);await engine.launch()
        try:
            with pytest.raises(ConnectionError):await engine.command('dial',peer='sip:test@127.0.0.1')
            assert engine._call_id==''
        finally:await engine.close()
    asyncio.run(exercise())


def test_malformed_events_do_not_mutate_call_identity():
    engine=IOSSIPEngine(request=Native());seen=[];engine.on_event=seen.append
    engine.deliver({'state':[]})
    engine.deliver({'state':'incoming','native_id':'first','peer':'x'*513})
    assert engine._call_id=='' and not seen
    engine.deliver({'state':'incoming','native_id':'first','peer':'sip:test@localhost'})
    engine.deliver({'state':'ended','native_id':'first','peer':None})
    assert engine._call_id=='first' and len(seen)==1


def test_password_bridge_uses_only_the_sip_domain(monkeypatch):
    import json
    from types import SimpleNamespace
    from sip_native import password_request
    calls = []
    def request(raw):
        calls.append(json.loads(raw))
        return json.dumps({'ok': True, 'value': 'private synthetic'})
    monkeypatch.setitem(sys.modules, '_next_credentials', SimpleNamespace(request=request))
    account = str(uuid.uuid4())
    assert password_request({'op': 'password-load', 'account': account})['value'] == 'private synthetic'
    assert calls == [{'op': 'password-load', 'account': account, 'domain': 'sip'}]
    monkeypatch.setitem(sys.modules, '_next_credentials', SimpleNamespace(request=lambda _: '{"ok":false}'))
    with pytest.raises(ConnectionError): password_request({'op': 'password-load', 'account': account})



def test_unlinked_transport_fails_without_starting_or_leaving_a_session(monkeypatch):
    from sip_native import native_request
    monkeypatch.setitem(sys.modules, '_next_sip', None)
    async def exercise():
        engine = IOSSIPEngine()
        with pytest.raises(RuntimeError, match='not enabled'): await engine.launch()
        assert not engine.running and engine._task is None
        await engine.close()
    asyncio.run(exercise())
    with pytest.raises(ValueError, match='limit'): native_request({'op': 'x', 'padding': 'x'*20000})


def test_close_waits_for_native_exit_and_is_idempotent():
    async def exercise():
        calls=[];closing=False
        def request(row):
            nonlocal closing
            calls.append(row['op'])
            if row['op']=='close': closing=True;return {'ok':True,'closed':False}
            return {'ok':True,'closed':closing,'events':[]}
        engine=IOSSIPEngine(request=request,poll_interval=10)
        await engine.launch();await engine.close()
        assert calls[-2:]==['close','poll'] and not engine.running
        before=calls.copy();await engine.close();assert calls==before
    asyncio.run(exercise())


def test_delayed_events_cannot_resurrect_a_finished_call_or_closed_engine():
    engine = IOSSIPEngine(request=Native())
    seen = []
    engine.on_event = seen.append
    event = lambda state, identifier: dict(state=state, native_id=identifier, peer='sip:test@127.0.0.1')
    engine.deliver(event('incoming', 'first'))
    engine.deliver(event('ended', 'first'))
    before = len(seen)
    for state in ['incoming', 'calling', 'connected', 'ended']:
        engine.deliver(event(state, 'first'))
    assert len(seen) == before and not engine._call_id
    engine.deliver(event('incoming', 'second'))
    assert engine._call_id == 'second'
    engine.deliver({'state': 'stopped'})
    before = len(seen)
    engine.deliver(event('incoming', 'third'))
    engine.deliver({'state': 'registered'})
    assert len(seen) == before and not engine._call_id


def test_retired_call_memory_is_bounded_and_failed_dial_ids_are_retired():
    async def exercise():
        identifiers = []
        def request(row):
            if row['op'] == 'dial':
                identifiers.append(row['call_id'])
                raise ConnectionError('private rejection')
            return Native()(row)
        engine = IOSSIPEngine(request=request, poll_interval=10)
        await engine.launch()
        try:
            with pytest.raises(ConnectionError):
                await engine.command('dial', peer='sip:test@127.0.0.1')
            assert identifiers[0] in engine._retired
            engine.deliver(dict(state='calling', native_id=identifiers[0]))
            assert not engine._call_id
            for number in range(300):
                identifier = 'private-' + str(number)
                engine.deliver(dict(state='incoming', native_id=identifier))
                engine.deliver(dict(state='ended', native_id=identifier))
            assert len(engine._retired) == 256
        finally:
            await engine.close()
    asyncio.run(exercise())
