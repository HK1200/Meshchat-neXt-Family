import copy
import importlib.util
import json
from pathlib import Path
import signal
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'app/src/main/python/family_backend.py'
WIFI = 'ios:wifi:112233445566'
CELL = 'ios:cellular:aabbccddeeff'


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.syspath_prepend(str(SOURCE.parent))
    spec = importlib.util.spec_from_file_location('ios_quality_context_fixture', SOURCE)
    module = importlib.util.module_from_spec(spec)
    original = signal.signal
    try:
        spec.loader.exec_module(module)
    finally:
        signal.signal = original
    module._tcp_only = True
    module._state = {'peer': {'enabled': True, 'host': 'private', 'port': 4343}}
    module._rns = object()
    module._connect = Mock()
    return module


def update(module, context, generation):
    result = json.loads(module.request(json.dumps({'action': 'ios_network_context',
        'payload': {'context': context, 'generation': generation}})))
    module._connect.assert_not_called()
    return result


def test_stale_or_duplicate_path_updates_cannot_restore_previous_quality_context(backend):
    original = copy.deepcopy(backend._state)
    assert update(backend, WIFI, 1)['ok']
    assert update(backend, CELL, 2)['ok']
    assert update(backend, WIFI, 1)['ok']
    assert update(backend, WIFI, 2)['ok']
    assert backend._network_context == CELL
    assert backend._state == original


@pytest.mark.parametrize('context,generation', [('192.168.0.1', 1), ('ios:wifi:my-home-network', 1),
    ('ios:wifi\n', 1), (WIFI, True), (WIFI, -1), (WIFI, '2')])
def test_raw_network_details_and_invalid_epochs_are_rejected(backend, context, generation):
    assert not update(backend, context, generation)['ok']
    assert backend._network_context == 'unknown'


def test_wifi_measurements_do_not_become_cellular_measurements(backend, monkeypatch):
    peer = SimpleNamespace(target_ip='private', target_port=4343)
    monkeypatch.setitem(sys.modules, 'RNS', SimpleNamespace(Transport=SimpleNamespace(next_hop_interface=lambda _: None)))
    backend._radio = None
    backend._tcp_interfaces = lambda: [peer]
    backend._online_tcp = lambda: peer
    backend._online = lambda: True
    backend._voice = SimpleNamespace(snapshot=lambda: {'ready': True})
    backend._state.update(contacts=[{'id': 1, 'addresses': {'lxst': 'ab'*16, 'sip': 'sip:test@example.invalid'}}],
        voiceEnabled=True, callQuality=[{'service': 'reticulum', 'target': 'ab'*16,
        'context': 'tcp:private:4343:' + WIFI, 'timestamp': time.time(), 'failed': False,
        'metrics': {'rtt_ms': 20, 'jitter_ms': 0, 'loss_pct': 0}}])
    sip = json.dumps({'enabled': True, 'registered': True})
    assert update(backend, WIFI, 1)['ok']
    wifi = json.loads(backend.call_routes(sip))['1']
    assert wifi[0]['service'] == 'reticulum' and wifi[0]['measured']
    assert update(backend, CELL, 2)['ok']
    cell = json.loads(backend.call_routes(sip))['1']
    assert not next(row for row in cell if row['service'] == 'reticulum')['measured']
