"""Radio editor lifecycle tests without Bluetooth, sockets, or RF transmissions."""

import stat
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROBE = Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"
sys.path.insert(0, str(PROBE))
RNodeSettings = importlib.import_module("rnode_settings").RNodeSettings


@pytest.fixture(autouse=True)
def shared_radio_module(monkeypatch):
    monkeypatch.syspath_prepend(str(PROBE.parents[1] / "app/src/main/python"))


@pytest.fixture
def profile():
    return dict(
        enabled=True,
        transport="tcp",
        endpoint="127.0.0.1",
        frequency="914.875",
        bandwidth="125",
        sf=8,
        cr=7,
        power=17,
    )


class FakeRadio:
    instances = []

    def __init__(self, owner, **options):
        self.owner = owner
        self.options = options
        self.applied = []
        self.interface = SimpleNamespace(online=True, detached=False)
        self.instances.append(self)

    def configure(self, config):
        self.applied.append(config)

    def snapshot(self):
        return dict(
            online=bool(self.applied[-1] and self.applied[-1]["enabled"]),
            connecting=False,
            error="",
            battery=None,
        )


def make(tmp_path, *, device=True, clock=lambda: 0, source=None):
    if source is None:
        source = SimpleNamespace(announce=lambda **kwargs: None)
    return RNodeSettings(
        tmp_path,
        object(),
        source,
        lambda interface: None,
        device=device,
        factory=FakeRadio,
        clock=clock,
    )


def test_unconfigured_app_does_not_open_radio_or_touch_settings(tmp_path):
    manager = make(tmp_path)
    assert manager.radio is None
    assert manager.snapshot()["settings"] is None
    assert manager.snapshot()["runtime"]["online"] is False
    assert not manager.path.exists()
    manager.close()


def test_saved_profile_uses_private_permissions_editor_units_and_reopens(
    tmp_path, profile
):
    manager = make(tmp_path)
    state = manager.apply(profile)
    assert state["settings"]["frequency"] == 914.875
    assert state["settings"]["bandwidth"] == 125
    assert stat.S_IMODE(manager.path.stat().st_mode) == 0o600
    assert manager.radio.applied[-1]["frequency"] == 914875000
    reopened = make(tmp_path)
    assert reopened.radio.applied[-1] == manager.radio.applied[-1]
    assert reopened.snapshot()["runtime"]["online"] is True


def test_invalid_update_preserves_saved_profile_and_radio(tmp_path, profile):
    manager = make(tmp_path)
    manager.apply(profile)
    before = manager.path.read_bytes()
    with pytest.raises(ValueError):
        manager.apply(dict(profile, frequency="not a frequency"))
    assert manager.path.read_bytes() == before
    assert len(manager.radio.applied) == 1


def test_simulator_never_opens_an_enabled_radio(tmp_path, profile):
    manager = make(tmp_path, device=False)
    with pytest.raises(ValueError, match="simulator"):
        manager.apply(profile)
    assert manager.radio is None
    manager.apply(dict(profile, enabled=False))
    assert manager.radio is None
    assert make(tmp_path, device=False).radio is None


def test_disable_and_close_release_only_selected_radio(tmp_path, profile):
    manager = make(tmp_path)
    manager.apply(profile)
    radio = manager.radio
    manager.apply(dict(profile, enabled=False))
    assert manager.radio is radio
    assert radio.applied[-1]["enabled"] is False
    assert manager.snapshot()["runtime"]["online"] is False
    manager.close()
    assert radio.applied[-1] is None


def test_startup_hourly_and_reconnect_announces_are_scoped_to_radio(tmp_path, profile):
    now = [100.0]
    sent = []
    manager = make(
        tmp_path,
        clock=lambda: now[0],
        source=SimpleNamespace(announce=lambda **kw: sent.append(kw)),
    )
    manager.apply(profile)
    manager.announce_due()
    manager.announce_due()
    assert sent == [dict(attached_interface=manager.radio.interface)]
    now[0] += 3600
    manager.announce_due()
    assert len(sent) == 2
    manager.radio.interface.online = False
    manager.announce_due()
    manager.radio.interface.online = True
    manager.radio.options["on_ready"]()
    manager.announce_due()
    assert len(sent) == 3
    manager.apply(dict(profile, enabled=False))
    manager.announce_due()
    assert len(sent) == 3


def test_failed_announce_remains_due(tmp_path, profile):
    calls = []

    def announce(**kw):
        calls.append(kw)
        if len(calls) == 1:
            raise ConnectionError("synthetic")

    manager = make(tmp_path, source=SimpleNamespace(announce=announce))
    manager.apply(profile)
    manager.announce_due()
    manager.announce_due()
    assert len(calls) == 2
    assert manager.last_announce == 0


def test_ble_uses_ios_uuid_validation_and_never_another_radio(
    tmp_path, profile, monkeypatch
):
    with monkeypatch.context() as ios:
        ios.setattr(sys, "platform", "ios")
        manager = make(tmp_path)
        selected = "2fbd5d29-9c96-4ffd-a3e7-cff736fa5062"
        manager.apply(dict(profile, transport="ble", endpoint=selected))
        assert manager.radio.applied[-1]["endpoint"] == selected.upper()
        with pytest.raises(ValueError):
            manager.apply(dict(profile, transport="ble", endpoint="00:11:22:33:44:55"))


def test_corrupt_saved_profile_leaves_tcp_available_without_overwriting(tmp_path):
    path = tmp_path / "rnode.json"
    path.write_text("broken JSON")
    manager = make(tmp_path)
    assert manager.radio is None
    assert "could not be read" in manager.snapshot()["runtime"]["error"]
    assert path.read_text() == "broken JSON"


def test_old_interface_is_not_announced_while_replacement_is_pending(tmp_path, profile):
    sent = []
    manager = make(
        tmp_path, source=SimpleNamespace(announce=lambda **kw: sent.append(kw))
    )
    manager.apply(profile)
    manager.radio.snapshot = lambda: {"online": False}
    manager.announce_due()
    assert not sent


@pytest.mark.parametrize("disabled_during_open", [True, False])
def test_radio_finishing_open_only_registers_current_profile(
    profile, monkeypatch, disabled_during_open
):
    import threading
    from family_radios import Radio, validate

    config = validate(profile)
    radio = Radio.__new__(Radio)
    radio._lock = threading.RLock()
    radio.config = config.copy()
    radio.interface = None
    radio.applied = None
    registered, detached = [], []
    radio.reticulum = SimpleNamespace(_add_interface=registered.append)
    interface = SimpleNamespace(detach=lambda: detached.append(True))

    def construct(owner, settings):
        assert settings["port"] == "tcp://127.0.0.1"
        assert settings["frequency"] == 914875000
        if disabled_during_open:
            radio.config = dict(config, enabled=False)
        return interface

    monkeypatch.setitem(
        sys.modules,
        "RNS.Interfaces.RNodeInterface",
        SimpleNamespace(RNodeInterface=construct),
    )
    radio._open_network_radio(SimpleNamespace(Transport=object()), config)
    if disabled_during_open:
        assert registered == []
        assert detached == [True]
        assert radio.interface is None
    else:
        assert registered == [interface]
        assert detached == []
        assert radio.interface is interface
        assert radio.applied == config


def test_saving_unchanged_connected_or_pairing_profile_does_not_restart(
    tmp_path, profile
):
    manager = make(tmp_path)
    manager.apply(profile)
    manager.apply(profile)
    assert len(manager.radio.applied) == 1
    manager.radio.snapshot = lambda: {
        "online": False,
        "connecting": True,
        "error": "",
        "battery": None,
    }
    manager.apply(profile)
    assert len(manager.radio.applied) == 1
