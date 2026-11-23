import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT
PYTHON = ROOT / 'app/src/main/python'


@pytest.fixture
def backend(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(PYTHON))
    spec = importlib.util.spec_from_file_location('native_inbox_prototype', HERE / 'app/src/main/python/family_backend.py')
    module = importlib.util.module_from_spec(spec)
    previous = signal.signal
    try:
        spec.loader.exec_module(module)
    finally:
        signal.signal = previous
    module._tcp_only = True
    module._root = tmp_path
    module._state = {'contacts': [{'id': 1, 'addresses': {'lxmf': 'ab' * 16}, 'identityPublicKey': 'approved'}], 'messages': []}
    monkeypatch.setitem(sys.modules, 'LXMF', SimpleNamespace(FIELD_TELEMETRY=1, FIELD_FILE_ATTACHMENTS=2, FIELD_IMAGE=3,
        LXMessage=SimpleNamespace(SOURCE_UNKNOWN=1)))
    return module


def message(text='Private test', fields=None):
    return SimpleNamespace(source_hash=bytes.fromhex('ab' * 16), signature_validated=True,
        hash=bytes.fromhex('cd' * 32), fields=fields or {}, content_as_string=lambda: text)


def test_signal_is_payload_free_and_happens_after_successful_persistence(backend, monkeypatch):
    events = []
    def changed(*args):
        assert not args
        events.append(json.loads((backend._root / 'state.json').read_text())['messages'][0]['text'])
    monkeypatch.setitem(sys.modules, '_family_native_events', SimpleNamespace(inbox_changed=changed))
    backend._receive(message())
    assert events == ['Private test']
    backend._receive(message())
    assert events == ['Private test']  # duplicate deliveries do not alert again


def test_telemetry_and_unapproved_senders_do_not_signal_chat_messages(backend, monkeypatch):
    changed = Mock()
    monkeypatch.setitem(sys.modules, '_family_native_events', SimpleNamespace(inbox_changed=changed))
    backend._locations = SimpleNamespace(receive=Mock())
    backend._receive(message('', {1: b'test telemetry'}))
    backend._locations.receive.assert_called_once()
    backend._state['contacts'] = []
    backend._receive(message())
    changed.assert_not_called()
    assert not backend._state['messages']


def test_storage_failure_never_signals_or_leaves_an_inbox_row(backend, monkeypatch):
    changed = Mock()
    monkeypatch.setitem(sys.modules, '_family_native_events', SimpleNamespace(inbox_changed=changed))
    backend._save = Mock(side_effect=OSError('Private disk failure fixture'))
    with pytest.raises(OSError):
        backend._receive(message())
    changed.assert_not_called()
    assert not backend._state['messages']


@pytest.mark.parametrize('missing', [False, True])
def test_callback_failure_cannot_drop_a_verified_message(backend, monkeypatch, missing):
    monkeypatch.setitem(sys.modules, '_family_native_events', None if missing else SimpleNamespace(inbox_changed=Mock(side_effect=RuntimeError('UI unavailable'))))
    backend._receive(message())
    assert len(json.loads((backend._root / 'state.json').read_text())['messages']) == 1


def test_unverified_message_does_not_signal(backend, monkeypatch):
    changed = Mock()
    monkeypatch.setitem(sys.modules, '_family_native_events', SimpleNamespace(inbox_changed=changed))
    backend._state['contacts'][0].pop('identityPublicKey')
    incoming = message()
    incoming.signature_validated = False
    incoming.unverified_reason = 99
    backend._receive(incoming)
    changed.assert_not_called()
    assert not backend._state['messages']


def test_android_does_not_use_native_ios_events(backend, monkeypatch):
    changed = Mock()
    monkeypatch.setitem(sys.modules, '_family_native_events', SimpleNamespace(inbox_changed=changed))
    backend._tcp_only = False
    backend._receive(message())
    changed.assert_not_called()
    assert len(backend._state['messages']) == 1


def test_actual_c_bridge_supports_worker_thread_and_reentrant_callbacks_without_payload(tmp_path):
    if sys.platform == 'win32' or not shutil.which('cc') or not shutil.which('python3-config'):
        pytest.skip('The embedded bridge host check requires a Unix C compiler and Python development SDK')
    modules = tmp_path / 'modules'
    modules.mkdir()
    (modules / 'family_backend.py').write_text('''
import json, socket, threading
import _family_native_events
socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Networking disabled"))
def initialize(*a, **k): pass
def voice_push(*a): pass
def voice_pull(*a): return b""
def request(raw):
    action = json.loads(raw)["action"]
    if action == "wake":
        import _family_native_calls
        assert not hasattr(_family_native_calls, "arm")
        assert not hasattr(_family_native_calls, "reset")
        assert _family_native_calls.consume("b"*32) is False
        assert _family_native_calls.consume("a"*32) is True
        assert _family_native_calls.consume("a"*32) is False
    elif action == "emit": _family_native_events.inbox_changed()
    elif action == "worker":
        t = threading.Thread(target=_family_native_events.inbox_changed)
        t.start(); t.join(timeout=3)
        assert not t.is_alive()
    elif action == "payload":
        try: _family_native_events.inbox_changed("must not pass private data")
        except TypeError: return json.dumps({"rejected": True})
        raise AssertionError("Payload was accepted")
    return json.dumps({"ok": True})
''')
    harness = tmp_path / 'harness.c'
    harness.write_text(r'''
#include <Python.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include "FamilyRuntime.h"
static atomic_int count, replaced, failures;
static void changed(void) {
    atomic_fetch_add(&count, 1);
    if (PyGILState_Check()) atomic_fetch_add(&failures, 1);
    char *reply = family_runtime_request("{\"action\":\"status\"}");
    if (!reply || !strstr(reply,"true")) atomic_fetch_add(&failures,1);
    free(reply);
}
static void replacement(void) { atomic_fetch_add(&replaced,1); }
int main(int argc, char **argv) {
    family_runtime_set_inbox_changed(changed);
    if (!family_call_wake_arm("0123456789abcdef0123456789abcdef", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 30)) return 4;
    if (!family_runtime_start(NULL, argv[1], argv[2])) return 1;
    family_runtime_set_inbox_changed(replacement);
    const char *requests[] = {"{\"action\":\"emit\"}","{\"action\":\"worker\"}","{\"action\":\"payload\"}"};
    char *wake=family_runtime_request("{\"action\":\"wake\"}");
    if (!wake || !strstr(wake,"true")) return 5;
    free(wake);
    for (int i=0;i<3;i++) {
        char *reply=family_runtime_request(requests[i]);
        if (!reply || !strstr(reply,"true")) return 2;
        free(reply);
    }
    return atomic_load(&count)==2 && !atomic_load(&replaced) && !atomic_load(&failures) ? 0 : 3;
}
''')
    flags = shlex.split(subprocess.check_output(['python3-config', '--cflags'], text=True))
    libs = shlex.split(subprocess.check_output(['python3-config', '--embed', '--ldflags'], text=True))
    binary = tmp_path / 'bridge-proof'
    compile_result = subprocess.run(['cc', '-std=c11', *flags,
        '-I'+str(HERE / 'ios/LiveRuntime'), '-I'+str(ROOT / 'ios/LiveRuntime'),
        str(HERE / 'ios/LiveRuntime/FamilyRuntime.c'), str(HERE / 'ios/LiveRuntime/FamilyCallWakeGate.c'), str(harness), '-o', str(binary), *libs, '-lpthread'],
        capture_output=True, text=True, timeout=30)
    assert compile_result.returncode == 0, compile_result.stderr
    proof = subprocess.run([str(binary), str(modules), str(tmp_path / 'state')], capture_output=True, text=True, timeout=10)
    assert proof.returncode == 0, proof.stdout + proof.stderr
