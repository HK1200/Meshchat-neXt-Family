"""Preserve only the current explicitly identified iOS call across scene changes."""
import importlib.util
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'app/src/main/python/family_backend.py'
CALL = 'a' * 32


@pytest.fixture
def backend():
    original = signal.signal
    spec = importlib.util.spec_from_file_location('family_call_presence_fixture', SOURCE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        signal.signal = original
    ended = []
    muted = []
    module._ios_voice = True
    module._tcp_only = True
    module._voice = SimpleNamespace(phase='connected', call_id=CALL, phone=None,
                                   hangup=lambda call_id: ended.append(call_id), set_muted=muted.append)
    module._snapshot = lambda: {}
    return module, ended, muted


def request(module, action='voice_presence', **payload):
    return json.loads(module.request(json.dumps({'action': action, 'payload': payload})))


@pytest.mark.parametrize('phase', ['finding', 'calling', 'incoming', 'connected'])
def test_only_exact_preserved_call_survives_background(backend, phase):
    module, ended, _ = backend
    module._voice.phase = phase
    assert request(module, foreground=False, preserveCallId=CALL)['ok']
    assert not module._ios_voice_foreground and ended == []


@pytest.mark.parametrize('preserve', [None, 'b' * 32])
def test_missing_or_stale_preservation_does_not_keep_a_different_call(backend, preserve):
    module, ended, _ = backend
    assert request(module, foreground=False, preserveCallId=preserve)['ok']
    assert ended == [CALL]


@pytest.mark.parametrize('preserve', [True, '', 12, 'not-a-call'])
def test_invalid_preservation_cannot_change_presence(backend, preserve):
    module, ended, _ = backend
    module._ios_voice_foreground = True
    assert not request(module, foreground=False, preserveCallId=preserve)['ok']
    assert module._ios_voice_foreground and not ended


def test_older_scene_task_cannot_reopen_foreground_call_admission(backend):
    module, ended, _ = backend
    assert request(module, foreground=False, preserveCallId=CALL, generation=2)['ok']
    assert request(module, foreground=True, generation=1)['ok']
    assert not module._ios_voice_foreground and not ended
    assert request(module, foreground=True, generation=3)['ok']
    assert module._ios_voice_foreground


def test_stale_system_mute_cannot_mute_a_replacement_call(backend):
    module, _, muted = backend
    assert not request(module, action='voice_mute', callId='b' * 32, muted=True)['ok']
    assert muted == []
    assert request(module, action='voice_mute', callId=CALL, muted=True)['ok']
    assert muted == [True]
