"""Connection failures must remain visible while radio setup/reconnect is pending."""
import importlib.util
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / 'app/src/main/python/family_radios.py'
spec = importlib.util.spec_from_file_location('family_radio_status', SOURCE)
radios = importlib.util.module_from_spec(spec)
spec.loader.exec_module(radios)


def radio(*, error='', enabled=True, interface=None):
    value = radios.Radio.__new__(radios.Radio)
    value._lock = threading.RLock()
    value.interface = interface
    value.config = {'enabled': enabled, 'transport': 'ble', 'endpoint': 'test-radio'}
    value.applied = value.config
    value.error = error
    value.network_only = True
    return value


def test_setup_failure_visible_before_interface_exists(monkeypatch):
    monkeypatch.setitem(sys.modules, 'family_ios_bluetooth', SimpleNamespace(last_error=lambda _: ''))
    result = radio(error='Bluetooth connection timed out').snapshot()
    assert result['error'] == 'Bluetooth connection timed out'
    assert not result['connecting']


def test_native_failure_visible_before_interface_exists(monkeypatch):
    monkeypatch.setitem(sys.modules, 'family_ios_bluetooth', SimpleNamespace(last_error=lambda _: 'Pairing was refused'))
    result = radio().snapshot()
    assert result['error'] == 'Pairing was refused'
    assert not result['connecting']


def test_disabled_radio_hides_old_failure():
    result = radio(error='Old error', enabled=False).snapshot()
    assert result['error'] == ''
    assert not result['connecting']


def test_hardware_failure_is_visible(monkeypatch):
    monkeypatch.setitem(sys.modules, 'family_ios_bluetooth', SimpleNamespace(last_error=lambda _: ''))
    interface = SimpleNamespace(online=False, hw_errors=[{'description': 'Radio hardware failure'}])
    result = radio(interface=interface).snapshot()
    assert result['error'] == 'Radio hardware failure'
    assert not result['connecting']
