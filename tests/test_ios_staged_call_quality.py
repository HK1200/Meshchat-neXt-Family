import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_runtime_can_rank_an_approved_method_without_source_checkout(tmp_path):
    wheel = ROOT / 'ios/RuntimeBuild/public/rns-1.5.7-py3-none-any.whl'
    if not wheel.exists():
        pytest.skip('Pinned iOS Reticulum wheel is not cached')
    spec = importlib.util.spec_from_file_location('private_runtime_stager', ROOT / 'ios/stage-runtime.py')
    staging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(staging)
    target = tmp_path / 'staged'
    staging.stage(wheel, target)
    code = r'''
import json, pathlib, socket, sys
sys.path.insert(0, sys.argv[1])
import family_backend as backend
import family_call_quality as quality
import family_call_alerts, family_call_hints
for module in (family_call_alerts, family_call_hints):
    assert pathlib.Path(module.__file__).resolve().parent == pathlib.Path(sys.argv[1]).resolve()
assert family_call_alerts.FamilyCallHints(None, {}, __import__('threading').RLock()).start(1, 'ab'*16, 'cd'*16) is None
assert pathlib.Path(quality.__file__).resolve().parent == pathlib.Path(sys.argv[1]).resolve()
def forbidden(*args, **kwargs):
    raise AssertionError('Ranking must not create a network socket')
socket.socket = forbidden
backend._tcp_only = True
backend._state = {'contacts': [{'id': 1, 'addresses': {'sip': 'sip:test@example.invalid'}}],
                  'voiceEnabled': False, 'callQuality': []}
reply = json.loads(backend.request(json.dumps({'action': 'call_routes', 'payload': {
    'sip': {'enabled': True, 'registered': True}}})))
assert reply['ok'], reply
route, = reply['callRoutes']['1']
assert route['service'] == 'sip' and route['automatic'] and not route['measured']
print('Packaged runtime call-quality request passed without source checkout or networking')
'''
    result = subprocess.run([sys.executable, '-I', '-c', code, str(target)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
