"""Exercise the iOS runtime boundary for the local companion battery query."""
import importlib.util
import json
from pathlib import Path
import signal
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "app/src/main/python/family_backend.py"

@pytest.fixture
def backend(monkeypatch):
    monkeypatch.syspath_prepend(str(SOURCE.parent))
    spec = importlib.util.spec_from_file_location("ios_battery_request_fixture", SOURCE)
    module = importlib.util.module_from_spec(spec)
    original = signal.signal
    try:
        spec.loader.exec_module(module)
    finally:
        signal.signal = original
    module._tcp_only = True
    module._state = {"setup_complete": True}
    module._meshcore = Mock()
    return module


def test_ios_runtime_accepts_the_local_battery_query_without_guardian_unlock(backend):
    reply = json.loads(backend.request(json.dumps({"action": "radio_batteries"})))
    assert reply == {"ok": True}
    backend._meshcore.request_battery.assert_called_once_with()


def test_battery_query_does_not_contact_a_radio_before_setup(backend):
    backend._state["setup_complete"] = False
    assert json.loads(backend.request('{"action":"radio_batteries"}')) == {"ok": True}
    backend._meshcore.request_battery.assert_not_called()


def test_battery_query_is_safe_without_a_meshcore_companion(backend):
    backend._meshcore = None
    assert json.loads(backend.request('{"action":"radio_batteries"}')) == {"ok": True}
