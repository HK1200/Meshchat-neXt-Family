import importlib.util
import json
from pathlib import Path
import signal
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

PYTHON = Path(__file__).resolve().parents[1] / 'app/src/main/python'


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.syspath_prepend(str(PYTHON))
    spec = importlib.util.spec_from_file_location('ios_call_rank_fixture', PYTHON / 'family_backend.py')
    module = importlib.util.module_from_spec(spec)
    original = signal.signal
    try:
        spec.loader.exec_module(module)
    finally:
        signal.signal = original
    module._tcp_only = True
    module._state = {'contacts': [{'id': 1, 'addresses': {'sip': 'sip:test@example.invalid', 'lxst': 'ab'*16}}],
                     'voiceEnabled': True, 'callQuality': []}
    module._voice = SimpleNamespace(snapshot=lambda: {'ready': True}, call=Mock())
    module._voice_route_context = lambda _: 'tcp:test'
    module._online = lambda: True
    return module


def routes(backend, registered=True):
    result = json.loads(backend.request(json.dumps({'action': 'call_routes', 'payload': {
        'sip': {'enabled': True, 'registered': registered, 'quality_context': 'ios:wifi'}}})))
    assert result['ok'], result
    backend._voice.call.assert_not_called()
    assert list(result['callRoutes']) == ['1']
    return result['callRoutes']['1']


def test_unknown_quality_is_not_reported_as_measured_and_registration_is_required(backend):
    result = routes(backend)
    assert result[0]['service'] == 'sip'
    assert all(not row['measured'] for row in result)
    assert [row['service'] for row in routes(backend, registered=False)] == ['reticulum']


def test_recent_reticulum_measurements_and_failure_change_recommendation(backend):
    backend._state['callQuality'] = [{'service': 'reticulum', 'target': 'ab'*16, 'context': 'tcp:test',
        'timestamp': time.time(), 'failed': False, 'metrics': {'rtt_ms': 20, 'jitter_ms': 1, 'loss_pct': 0}}]
    assert routes(backend)[0]['service'] == 'reticulum'
    assert routes(backend)[0]['measured']
    backend._state['callQuality'][0]['failed'] = True
    assert routes(backend)[0]['service'] == 'sip'


def test_slow_radio_route_remains_manual_only(backend):
    backend._voice_route_context = lambda _: 'radio:test'
    result = routes(backend, registered=False)
    assert len(result) == 1 and result[0]['service'] == 'reticulum'
    assert result[0]['automatic'] is False
    assert not any(row['automatic'] for row in result)


def test_only_current_approved_methods_are_returned(backend):
    backend._state['contacts'][0]['addresses'] = {}
    assert routes(backend) == []
