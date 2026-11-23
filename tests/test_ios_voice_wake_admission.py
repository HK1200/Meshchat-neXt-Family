"""A native call wake permits one approved incoming peer, never background dialing."""
import ctypes
import importlib.util
from pathlib import Path
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
import RNS

ROOT=Path(__file__).resolve().parents[1]
CALL=b"0123456789abcdef0123456789abcdef"


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    library=tmp_path/'window.so'
    subprocess.run(['cc','-std=c11','-fPIC','-shared',str(ROOT/'ios/LiveRuntime/FamilyCallWakeGate.c'),'-pthread','-o',str(library)],check=True,capture_output=True,timeout=20)
    native=ctypes.CDLL(str(library))
    native.family_call_wake_arm.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint32];native.family_call_wake_arm.restype=ctypes.c_bool
    native.family_call_wake_consume.argtypes=[ctypes.c_char_p];native.family_call_wake_consume.restype=ctypes.c_bool
    monkeypatch.syspath_prepend(str(ROOT/'app/src/main/python'))
    spec=importlib.util.spec_from_file_location('ios_wake_admission_fixture',ROOT/'app/src/main/python/family_backend.py')
    backend=importlib.util.module_from_spec(spec);previous=signal.signal
    try:spec.loader.exec_module(backend)
    finally:signal.signal=previous
    monkeypatch.setitem(sys.modules,'_family_native_calls',SimpleNamespace(consume=lambda voice:native.family_call_wake_consume(voice.encode())))
    from family_voice import FamilyVoice
    peer=RNS.Identity.from_bytes(bytes(range(64,128)))
    address=RNS.Destination.hash_from_name_and_identity('lxst.telephony',peer.hash).hex()
    state={'setup_complete':True,'voiceEnabled':True,'contacts':[{'id':7,'name':'Approved private test','addresses':{'lxst':address}}]}
    voice=FamilyVoice(None,state,threading.RLock(),lambda:None,gate=lambda acquire:not acquire or backend._ios_voice_foreground,incoming_gate=backend._ios_voice_incoming,autostart=False)
    ended=threading.Event();voice.hangup=lambda *args:ended.set()
    backend._tcp_only=True;backend._ios_voice=True;backend._root=tmp_path;backend._state=state
    return SimpleNamespace(native=native,backend=backend,voice=voice,peer=peer,address=address,ended=ended)


def test_approved_caller_consumes_native_wake_once_without_claiming_foreground(fixture):
    f=fixture
    assert f.native.family_call_wake_arm(CALL,f.address.encode(),30)
    f.voice._ring(f.peer)
    assert f.voice.phase=='incoming' and f.voice.target==f.address
    assert f.backend._ios_voice_foreground is False
    assert not f.native.family_call_wake_consume(f.address.encode())


def test_background_call_without_native_wake_is_rejected(fixture):
    f=fixture;f.voice._ring(f.peer)
    assert f.ended.wait(1) and f.voice.phase=='idle'


def test_unapproved_caller_cannot_consume_even_a_native_window(fixture):
    f=fixture;f.voice.state['contacts']=[]
    assert f.native.family_call_wake_arm(CALL,f.address.encode(),30)
    f.voice._ring(f.peer)
    assert f.ended.wait(1) and f.voice.phase=='idle'
    assert f.native.family_call_wake_consume(f.address.encode())


def test_other_approved_caller_cannot_consume_selected_callers_window(fixture):
    f=fixture;other=RNS.Destination.hash_from_name_and_identity('lxst.telephony',RNS.Identity().hash).hex()
    assert f.native.family_call_wake_arm(CALL,other.encode(),30)
    f.voice._ring(f.peer)
    assert f.ended.wait(1) and f.voice.phase=='idle'
    assert f.native.family_call_wake_consume(other.encode())


def test_native_incoming_window_does_not_enable_background_outgoing_calls(fixture):
    f=fixture;f.voice.phone=SimpleNamespace(active_call=None)
    assert f.native.family_call_wake_arm(CALL,f.address.encode(),30)
    with pytest.raises(ValueError,match='background'):f.voice.call(7)
    assert f.native.family_call_wake_consume(f.address.encode())


def test_existing_foreground_approval_works_without_push(fixture):
    f=fixture;f.backend._ios_voice_foreground=True
    f.voice._ring(f.peer)
    assert f.voice.phase=='incoming' and not f.ended.is_set()


def test_json_actions_cannot_arm_the_native_window(fixture):
    import json
    f=fixture
    for action in ['voice_wake','call_wake_arm','native_call_wake']:
        reply=json.loads(f.backend.request(json.dumps({'action':action,'payload':{'caller':f.address}})))
        assert reply['ok'] is False
        assert not f.native.family_call_wake_consume(f.address.encode())


def test_android_default_gate_is_still_used_for_incoming_calls(fixture):
    from family_voice import FamilyVoice
    f=fixture;calls=[]
    voice=FamilyVoice(None,f.voice.state,threading.RLock(),lambda:None,gate=lambda acquire:calls.append(acquire) or True,autostart=False)
    voice._ring(f.peer)
    assert voice.phase=='incoming' and calls==[True]
