import importlib.util
import json
from pathlib import Path
import signal
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'app/src/main/python/family_backend.py'


@pytest.fixture
def backend(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SOURCE.parent))
    spec = importlib.util.spec_from_file_location('ios_background_location_fixture', SOURCE)
    module = importlib.util.module_from_spec(spec)
    previous = signal.signal
    try:
        spec.loader.exec_module(module)
    finally:
        signal.signal = previous
    module._tcp_only = True
    module._root = tmp_path
    module._state = {'setup_complete': True, 'contacts': [], 'location_policy': {'until': 0}}
    module._sessions = {'guardian': time.time() + 60}
    module._locations = SimpleNamespace(suspend_samples=Mock())
    module._snapshot = lambda: {}
    return module


def configure(backend, enabled, token='guardian'):
    return json.loads(backend.request(json.dumps({'action': 'ios_location_background',
        'payload': {'token': token, 'enabled': enabled}})))


def test_only_guardian_can_enable_or_disable_persisted_background_preference(backend):
    assert not configure(backend, True, token='')['ok']
    assert 'ios_location_background' not in backend._state
    assert configure(backend, True)['ok']
    assert json.loads((backend._root / 'state.json').read_text())['ios_location_background'] is True
    assert not configure(backend, False, token='')['ok']
    assert backend._state['ios_location_background'] is True
    assert configure(backend, False)['ok']
    assert json.loads((backend._root / 'state.json').read_text())['ios_location_background'] is False
    backend._locations.suspend_samples.assert_called_once()
    assert backend._state['location_policy']['until'] == 0  # saving opt-in never starts sharing


@pytest.mark.parametrize('value', [None, 'true', 'false', 1, 0, [], {}])
def test_background_preference_requires_a_real_boolean(backend, value):
    assert not configure(backend, value)['ok']
    assert 'ios_location_background' not in backend._state
    assert not (backend._root / 'state.json').exists()
    backend._locations.suspend_samples.assert_not_called()


def test_ios_preference_does_not_change_android_behavior(backend):
    backend._tcp_only = False
    assert not configure(backend, True)['ok']
    assert 'ios_location_background' not in backend._state


def test_expired_guardian_access_cannot_enable_background_sharing(backend):
    backend._sessions['guardian'] = time.time() - 1
    assert not configure(backend, True)['ok']
    assert 'ios_location_background' not in backend._state


@pytest.mark.parametrize('previous', [None, False, True])
def test_failed_save_restores_previous_preference_and_does_not_suspend(backend, previous):
    if previous is not None:
        backend._state['ios_location_background'] = previous
    backend._save = Mock(side_effect=OSError('Private storage failure fixture'))
    assert not configure(backend, previous is not True)['ok']
    if previous is None:
        assert 'ios_location_background' not in backend._state
    else:
        assert backend._state['ios_location_background'] is previous
    backend._locations.suspend_samples.assert_not_called()
