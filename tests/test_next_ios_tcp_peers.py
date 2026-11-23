import importlib.util
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("next_tcp_peers", ROOT / "ios/NextRuntimeProbe/tcp_peers.py")
peers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(peers)


def row(identifier="one", host="127.0.0.1", port=45001, enabled=True):
    return dict(id=identifier, host=host, port=port, enabled=enabled)


def wait_for(condition):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    assert condition()


def test_rmap_legacy_migrates_to_all_four_distinct_peers():
    for port in (4242, 4343):
        result = peers.normalize_peers(dict(host="RMAP.world.", port=port), device=True)
        assert [(p["host"], p["port"]) for p in result] == list(peers.DEFAULT_ENDPOINTS)
        assert all(p["enabled"] for p in result)


def test_private_legacy_and_simulator_never_gain_public_peers():
    for device in (False, True):
        result = peers.normalize_peers(dict(host="127.0.0.1", port=45001), device=device)
        assert [(p["host"], p["port"]) for p in result if p["enabled"]] == [("127.0.0.1", 45001)]
        assert len(result) == (5 if device else 1)
        if device:
            assert [(p["host"], p["port"]) for p in result[1:]] == list(peers.DEFAULT_ENDPOINTS)
    with pytest.raises(ValueError, match="loopback"):
        peers.normalize_peers(dict(host="rmap.world", port=4343), device=False)


def test_explicit_peer_list_preserves_individual_disabled_states_and_deletions():
    source = [row(enabled=False), row("two", port=45002)]
    assert peers.normalize_peers(dict(peers=source), device=False) == source
    assert peers.normalize_peers(dict(peers=[]), device=True) == []


@pytest.mark.parametrize("change", [dict(host="https://example.org"), dict(host="bad\nname"),
    dict(port=True), dict(port=0), dict(port=65536), dict(enabled="yes"), dict(id="bad/id")])
def test_invalid_peer_settings_are_rejected(change):
    with pytest.raises(ValueError):
        peers.normalize_peers(dict(peers=[dict(row(), **change)]), device=True)


def test_normalized_duplicate_endpoint_and_repeated_id_are_rejected():
    with pytest.raises(ValueError, match="already listed"):
        peers.normalize_peers(dict(peers=[row(host="Example.org"), row("two", host="example.org.")]), device=True)
    with pytest.raises(ValueError, match="unique"):
        peers.normalize_peers(dict(peers=[row(), row(port=45002)]), device=True)


def test_ipv6_peer_is_valid_for_device_but_not_private_simulator():
    result = peers.normalize_peers(dict(peers=[row(host="2001:db8::1")]), device=True)
    assert result[0]["host"] == "2001:db8::1"
    with pytest.raises(ValueError, match="loopback"):
        peers.normalize_peers(dict(peers=result), device=False)


@pytest.fixture
def controller(monkeypatch):
    import sys
    import RNS
    monkeypatch.syspath_prepend(str(ROOT / "app/src/main/python"))
    monkeypatch.setattr(RNS.Transport, "interfaces", [])
    monkeypatch.setattr(RNS.Transport, "path_table", {})
    calls = []
    now = [100.0]

    class Interface:
        def __init__(self, owner, config):
            self.target_ip, self.target_port = config["target_host"], config["target_port"]
            self.online, self.detached, self.family_connection_epoch = True, False, 1
        def detach(self):
            self.detached, self.online = True, False

    manager = peers.TCPPeers(SimpleNamespace(_add_interface=RNS.Transport.interfaces.append),
        SimpleNamespace(direct_links={}, backchannel_links={}),
        SimpleNamespace(announce=lambda **kwargs: calls.append(kwargs["attached_interface"])),
        device=False, factory=Interface, clock=lambda: now[0])
    yield manager, calls, now
    manager.close()


def test_edit_disable_and_remove_leave_other_peer_connected(controller):
    manager, _, _ = controller
    manager.apply(dict(peers=[row(), row("two", port=45002)]))
    wait_for(lambda: len(manager.interfaces) == 2)
    first, second = manager.interfaces["one"], manager.interfaces["two"]
    manager.apply(dict(peers=[row(port=45003), row("two", port=45002)]))
    wait_for(lambda: manager.interfaces.get("one") is not None)
    assert first.detached and manager.interfaces["two"] is second
    assert manager.interfaces["one"].target_port == 45003
    manager.apply(dict(peers=[row(enabled=False, port=45003), row("two", port=45002)]))
    assert manager.snapshot()[0]["status"] == "Disabled"
    assert manager.interfaces["two"] is second and second.online
    manager.apply(dict(peers=[]))
    assert not manager.online and second.detached


def test_startup_hourly_and_each_reconnected_route_announce_independently(controller):
    manager, calls, now = controller
    manager.apply(dict(peers=[row(), row("two", port=45002)]))
    wait_for(lambda: len(manager.interfaces) == 2)
    one, two = manager.interfaces["one"], manager.interfaces["two"]
    manager.announce_due()
    assert len(calls) == 2 and one in calls and two in calls
    now[0] += 3599
    manager.announce_due()
    assert len(calls) == 2
    one.family_connection_epoch += 1
    manager.announce_due()
    assert calls[-1] is one and len(calls) == 3
    now[0] += 1
    manager.announce_due()
    assert calls[-1] is two and len(calls) == 4
    one.online = False
    now[0] += 3600
    manager.announce_due()
    assert calls[-1] is two and len(calls) == 5


def test_disabling_a_peer_during_connect_cannot_add_it_later(controller):
    manager, _, _ = controller
    release, started = threading.Event(), threading.Event()
    created = []
    factory = manager.factory
    def delayed(owner, config):
        interface = factory(owner, config)
        created.append(interface)
        started.set()
        assert release.wait(3)
        return interface
    manager.factory = delayed
    manager.apply(dict(peers=[row()]))
    assert started.wait(3)
    manager.apply(dict(peers=[row(enabled=False)]))
    release.set()
    wait_for(lambda: created[0].detached)
    assert not manager.interfaces and not manager.transport.interfaces


def test_retired_closed_lxmf_links_are_removed_without_dropping_other_routes(controller):
    manager, _, _ = controller
    manager.apply(dict(peers=[row(), row("two", port=45002)]))
    wait_for(lambda: len(manager.interfaces) == 2)
    one, two = manager.interfaces["one"], manager.interfaces["two"]
    closed = []
    bad = SimpleNamespace(attached_interface=one, status=manager.link_type.ACTIVE, teardown=lambda: closed.append("one"))
    good = SimpleNamespace(attached_interface=two, status=manager.link_type.ACTIVE, teardown=lambda: closed.append("two"))
    manager.router.direct_links.update({b"old": bad, b"other": good})
    manager.apply(dict(peers=[row(enabled=False), row("two", port=45002)]))
    assert manager.router.direct_links == {b"other": good} and closed == ["one"]


def test_partial_add_failure_releases_interface_and_pending_job(controller):
    manager, _, _ = controller
    def fail_after_add(interface):
        manager.transport.interfaces.append(interface)
        raise RuntimeError("simulated registration failure")
    manager.reticulum._add_interface = fail_after_add
    manager.apply(dict(peers=[row()]))
    wait_for(lambda: not manager.pending)
    assert not manager.interfaces and not manager.transport.interfaces
    assert manager.snapshot()[0]["status"] == "Could not configure this TCP peer"


def test_failed_announce_stays_due_until_success(controller):
    manager, calls, _ = controller
    manager.apply(dict(peers=[row()]))
    wait_for(lambda: len(manager.interfaces) == 1)
    original = manager.source.announce
    manager.source.announce = lambda **kwargs: (_ for _ in ()).throw(OSError("offline"))
    manager.announce_due()
    assert not manager.announced
    manager.source.announce = original
    manager.announce_due()
    assert len(calls) == 1 and len(manager.announced) == 1


def test_announce_display_time_records_only_success_and_survives_disconnect(controller):
    manager, calls, now = controller
    wall = [1_800_000_000]
    manager.wall_clock = lambda: wall[0]
    manager.apply(dict(peers=[row()]))
    wait_for(lambda: len(manager.interfaces) == 1)
    assert manager.last_announced_at is None
    original = manager.source.announce
    manager.source.announce = lambda **kw: (_ for _ in ()).throw(OSError("offline"))
    manager.announce_due()
    assert manager.last_announced_at is None
    manager.source.announce = original
    manager.announce_due()
    assert manager.last_announced_at == wall[0]
    wall[0] += 30
    manager.announce_due()
    assert manager.last_announced_at == 1_800_000_000  # Not a poll timestamp.
    manager.request_announce()
    assert manager.last_announced_at == 1_800_000_000  # Queuing is not transmission.
    manager.announce_due()
    assert manager.last_announced_at == wall[0]
    manager.apply(dict(peers=[row(enabled=False)]))
    assert manager.last_announced_at == wall[0]


def test_custom_announce_interval_and_disabled_timer_keep_reconnect_and_manual(controller):
    manager, calls, now = controller
    manager.apply(dict(peers=[row()]))
    wait_for(lambda: len(manager.interfaces) == 1)
    assert manager.announce_due(900) == 1
    now[0] += 899
    assert manager.announce_due(900) == 0
    now[0] += 1
    assert manager.announce_due(900) == 1
    now[0] += 100_000
    assert manager.announce_due(0) == 0
    manager.interfaces["one"].family_connection_epoch += 1
    assert manager.announce_due(0) == 1
    manager.request_announce()
    assert manager.announce_due(0) == 1


def test_retiring_a_peer_closes_other_reticulum_service_links_on_only_that_interface(controller, monkeypatch):
    manager, _, _ = controller
    manager.apply(dict(peers=[row(), row('two', port=45002)]))
    wait_for(lambda: len(manager.interfaces) == 2)
    one, two = manager.interfaces['one'], manager.interfaces['two']
    closed = []
    def link(name, interface, status, address=b'node'):
        return SimpleNamespace(attached_interface=interface, status=status,
            destination=SimpleNamespace(hash=address), teardown=lambda: closed.append(name))
    cached = link('cached and registered once', one, manager.link_type.ACTIVE)
    browser = link('browser', one, manager.link_type.ACTIVE)
    unrelated = link('unrelated', two, manager.link_type.ACTIVE)
    pending = link('pending browser', None, manager.link_type.PENDING, b'pending')
    other_pending = link('other pending', None, manager.link_type.PENDING, b'other')
    manager.router.direct_links[b'cached'] = cached
    monkeypatch.setattr(manager.transport, 'active_links', [cached, browser, unrelated])
    monkeypatch.setattr(manager.transport, 'pending_links', [pending, other_pending])
    monkeypatch.setattr(manager.transport, 'next_hop_interface', lambda address: one if address == b'pending' else two)
    manager.apply(dict(peers=[row(enabled=False), row('two', port=45002)]))
    assert sorted(closed) == sorted(['cached and registered once', 'browser', 'pending browser'])
    assert manager.interfaces['two'] is two and two.online
    assert manager.router.direct_links == {}


def test_retiring_a_peer_removes_only_routes_received_on_that_interface(controller):
    from RNS.Transport import IDX_PT_RVCD_IF
    manager, _, _ = controller
    manager.apply(dict(peers=[row(), row('two', port=45002)]))
    wait_for(lambda: len(manager.interfaces) == 2)
    one, two = manager.interfaces['one'], manager.interfaces['two']
    def route(interface):
        value = [None] * (IDX_PT_RVCD_IF + 1)
        value[IDX_PT_RVCD_IF] = interface
        return value
    keep = route(two)
    manager.transport.path_table.update({b'retired-browser': route(one), b'other-peer': keep})
    manager.apply(dict(peers=[row(enabled=False), row('two', port=45002)]))
    assert manager.transport.path_table == {b'other-peer': keep}
