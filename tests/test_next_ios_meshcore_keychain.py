"""Credential bridge contracts with no filesystem or real passwords."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe'))
from meshcore_keychain import IOSNodePasswords

OWNER='a'*64
PEER='b'*64


@pytest.fixture
def bridge(monkeypatch):
    values={}
    calls=[]
    def request(raw):
        row=json.loads(raw);calls.append(row)
        slot=(row['owner'],row['peer'],row['role'])
        if row['operation']=='save':values[slot]=row['password'];value=True
        elif row['operation']=='has':value=slot in values
        elif row['operation']=='forget':values.pop(slot,None);value=True
        elif row['operation']=='load':
            if slot not in values:return json.dumps({'error':'not found'})
            value=values[slot]
        return json.dumps({'value':value})
    monkeypatch.setitem(sys.modules,'_next_credentials',SimpleNamespace(request=request))
    return values,calls


def test_saved_credentials_round_trip_and_are_isolated_by_radio_and_role(bridge):
    store=IOSNodePasswords()
    assert not store.has(OWNER,PEER,'member')
    store.save(OWNER,PEER,'member','private test password')
    assert store.load(OWNER,PEER,'member')=='private test password'
    assert not store.has(OWNER,PEER,'admin')
    assert not store.has('c'*64,PEER,'member')
    store.forget(OWNER,PEER,'member')
    assert not store.has(OWNER,PEER,'member')
    with pytest.raises(ValueError,match='unavailable'):store.load(OWNER,PEER,'member')


@pytest.mark.parametrize('owner,peer,role',[(OWNER+'\n',PEER,'member'),(OWNER,PEER+'\n','admin'),('https://example.invalid',PEER,'member'),(OWNER,PEER,'other')])
def test_invalid_slots_never_reach_native_storage(bridge,owner,peer,role):
    with pytest.raises(ValueError):IOSNodePasswords().has(owner,peer,role)
    assert not bridge[1]


@pytest.mark.parametrize('password',['bad\0password','é'*33,None])
def test_invalid_passwords_never_reach_native_storage(bridge,password):
    with pytest.raises(ValueError):IOSNodePasswords().save(OWNER,PEER,'member',password)
    assert not bridge[1]


def test_native_failure_has_no_plaintext_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules,'_next_credentials',SimpleNamespace(request=lambda raw:json.dumps({'error':'locked'})))
    with pytest.raises(ValueError,match='unavailable'):IOSNodePasswords().save(OWNER,PEER,'member','private dummy')
