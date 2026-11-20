import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/src/main/python"))
import family_backend as family


def test_legacy_rmap_upgrade_shows_both_ports_and_preserves_custom_backup():
    peers = family._legacy_tcp_peers({
        "host": "RMAP.world",
        "port": 4242,
        "enabled": True,
        "backupHost": "private.example",
        "backupPort": 9000,
    })
    assert [(row["host"], row["port"]) for row in peers] == [
        *family.DEFAULT_TCP_PEERS, ("private.example", 9000),
    ]
    assert all(row["enabled"] for row in peers)
    assert len({row["id"] for row in peers}) == 5


def test_custom_only_upgrade_keeps_other_peers_disabled():
    peers = family._legacy_tcp_peers({"host": "private.example", "port": 9000, "enabled": True})
    assert [row["enabled"] for row in peers] == [True, False, False, False, False]


def test_guardian_can_edit_disable_and_add_one_peer_without_changing_others(monkeypatch):
    peers = family._legacy_tcp_peers({"host": "rmap.world", "port": 4242, "enabled": True})
    monkeypatch.setattr(family, "_state", {"tcpPeers": peers})
    monkeypatch.setattr(family, "_rns", None)
    monkeypatch.setattr(family, "_save", lambda: None)
    monkeypatch.setattr(family, "_authorized", lambda payload: None)
    monkeypatch.setattr(family, "_snapshot", lambda: {"tcpConnections": family._configured_tcp_peers()})

    def save(**payload):
        return json.loads(family.request(json.dumps({"action": "peer", "payload": payload})))

    result = save(id=peers[0]["id"], host="other.example", port=4343, enabled=False)
    assert result["ok"]
    assert result["tcpConnections"][0] == dict(peers[0], host="other.example", enabled=False)
    assert result["tcpConnections"][1:] == peers[1:]
    assert not save(host="RMAP.WORLD.", port=4242, enabled=True)["ok"]
    result = save(host="private.example", port=9000, enabled=True)
    assert result["ok"] and len(result["tcpConnections"]) == 5
    assert family._state["peer"]["enabled"]


def test_changing_primary_reuses_backup_interfaces(monkeypatch):
    import RNS
    import family_tcp

    class Interface:
        def __init__(self, host, port):
            self.target_ip = host
            self.target_port = port
            self.online = True
            self.detached = False

        def detach(self):
            self.detached = True
            self.online = False

    primary = Interface("rmap.world", 4242)
    wash = Interface("reticulum.washmesh.net", 7242)
    chicago = Interface("rns.chimesh.org", 4242)
    interfaces = [primary, wash, chicago]
    monkeypatch.setattr(RNS.Transport, "interfaces", interfaces)
    monkeypatch.setattr(family, "_rns", SimpleNamespace(_add_interface=interfaces.append))
    monkeypatch.setattr(family, "_peer", primary)
    monkeypatch.setattr(family, "_backup_peers", (wash, chicago))
    peers = family._legacy_tcp_peers({"host": "rmap.world", "port": 4343, "enabled": True})
    peers[1]["enabled"] = False
    monkeypatch.setattr(family, "_state", {"tcpPeers": peers})
    monkeypatch.setattr(family, "_announce_available_routes", lambda: None)

    def connect(owner, config):
        assert (config["target_host"], config["target_port"]) == ("rmap.world", 4343)
        raise ConnectionError("Primary offline")

    monkeypatch.setattr(family_tcp, "FamilyTCPInterface", connect)
    family._connect()
    assert primary.detached
    assert family._tcp_interfaces() == (wash, chicago)
    assert family._online_tcp() is wash
    assert [row["online"] for row in family._tcp_connection_status(peers)] == [
        False, False, True, True,
    ]


def test_reconnect_drops_retired_lxmf_links_without_touching_other_routes(monkeypatch):
    import RNS

    old = SimpleNamespace(target_ip="127.0.0.1", target_port=4343, online=True, detached=False)
    radio = object()
    events = []
    old.detach = lambda: events.append("interface detached")

    def link(interface, status=RNS.Link.ACTIVE, closed=None):
        result = SimpleNamespace(attached_interface=interface, status=status)
        def teardown():
            assert "interface detached" not in events
            events.append(result)
            result.status = RNS.Link.CLOSED
            if closed:
                closed()
        result.teardown = teardown
        return result

    direct = link(old)
    backchannel = link(old)
    pending = link(None, RNS.Link.PENDING)
    unaffected = link(radio)
    replacement = link(radio)
    direct_cache = {b"direct": direct, b"pending": pending, b"radio": unaffected}
    # A close callback may replace a cache entry with a new usable link.
    swapped = link(old, closed=lambda: direct_cache.update({b"swapped": replacement}))
    direct_cache[b"swapped"] = swapped
    router = SimpleNamespace(direct_links=direct_cache, backchannel_links={b"back": backchannel, b"radio": unaffected})
    interfaces = [old]
    monkeypatch.setattr(RNS.Transport, "interfaces", interfaces)
    monkeypatch.setattr(RNS.Transport, "next_hop_interface", lambda address: old if address == b"pending" else radio)
    monkeypatch.setattr(family, "_rns", object())
    monkeypatch.setattr(family, "_router", router)
    monkeypatch.setattr(family, "_rooms", None)
    monkeypatch.setattr(family, "_peer", old)
    monkeypatch.setattr(family, "_backup_peers", ())
    monkeypatch.setattr(family, "_configured_tcp_peers", lambda: [])
    monkeypatch.setattr(family, "_announce_available_routes", lambda: None)
    monkeypatch.setattr(family, "_connecting", False)
    monkeypatch.setattr(family, "_connect_pending", None)

    family._connect(reconnect=True)

    assert router.direct_links == {b"radio": unaffected, b"swapped": replacement}
    assert router.backchannel_links == {b"radio": unaffected}
    assert len(events) == 5 and events[-1] == "interface detached"
    assert unaffected.status == RNS.Link.ACTIVE and replacement.status == RNS.Link.ACTIVE



def test_healthy_backup_is_available_while_primary_connection_is_blocked(monkeypatch):
    import threading
    import RNS
    import family_tcp

    primary_started = threading.Event()
    release_primary = threading.Event()
    backup_announced = threading.Event()
    interfaces = []
    monkeypatch.setattr(RNS.Transport, "interfaces", interfaces)
    monkeypatch.setattr(family, "_rns", SimpleNamespace(_add_interface=interfaces.append))
    monkeypatch.setattr(family, "_peer", None)
    monkeypatch.setattr(family, "_backup_peers", ())
    monkeypatch.setattr(family, "_router", None)
    monkeypatch.setattr(family, "_rooms", None)
    monkeypatch.setattr(family, "_connecting", False)
    monkeypatch.setattr(family, "_connect_pending", None)
    monkeypatch.setattr(family, "_error", "")
    peers = [dict(id=str(index), host="127.0.0.1", port=port, enabled=True)
             for index, port in enumerate((45101, 45102))]
    monkeypatch.setattr(family, "_state", {"tcpPeers": peers})

    def connect(owner, config):
        if config["target_port"] == 45101:
            primary_started.set()
            assert release_primary.wait(5)
            raise ConnectionError("Primary unavailable")
        return SimpleNamespace(target_ip=config["target_host"], target_port=config["target_port"],
                               online=True, detached=False)

    def announce():
        if family._online_tcp() is not None:
            backup_announced.set()

    monkeypatch.setattr(family_tcp, "FamilyTCPInterface", connect)
    monkeypatch.setattr(family, "_announce_available_routes", announce)
    runner = threading.Thread(target=family._connect)
    runner.start()
    try:
        assert primary_started.wait(2)
        assert backup_announced.wait(2), "A blocked primary must not hold up the healthy backup"
        assert family._online_tcp().target_port == 45102
        assert family._connecting  # The primary attempt has not finished yet.
        assert [row["online"] for row in family._tcp_connection_status(peers)] == [False, True]
    finally:
        release_primary.set()
        runner.join(5)
    assert not runner.is_alive()
    assert not family._connecting and family._error == ""


def test_disabling_peer_during_connection_does_not_register_stale_interface(monkeypatch):
    import threading
    import RNS
    import family_tcp

    started, release = threading.Event(), threading.Event()
    interfaces, detached = [], []
    monkeypatch.setattr(RNS.Transport, "interfaces", interfaces)
    monkeypatch.setattr(family, "_rns", SimpleNamespace(_add_interface=interfaces.append))
    monkeypatch.setattr(family, "_peer", None)
    monkeypatch.setattr(family, "_backup_peers", ())
    monkeypatch.setattr(family, "_router", None)
    monkeypatch.setattr(family, "_rooms", None)
    monkeypatch.setattr(family, "_connecting", False)
    monkeypatch.setattr(family, "_connect_pending", None)
    monkeypatch.setattr(family, "_error", "")
    peer = dict(id="test", host="127.0.0.1", port=45103, enabled=True)
    monkeypatch.setattr(family, "_state", {"tcpPeers": [peer]})
    monkeypatch.setattr(family, "_announce_available_routes", lambda: None)

    def connect(owner, config):
        started.set()
        assert release.wait(5)
        return SimpleNamespace(target_ip=config["target_host"], target_port=config["target_port"],
                               online=True, detached=False, detach=lambda: detached.append(True))

    monkeypatch.setattr(family_tcp, "FamilyTCPInterface", connect)
    runner = threading.Thread(target=family._connect)
    runner.start()
    try:
        assert started.wait(2)
        with family._lock:
            family._state["tcpPeers"] = [dict(peer, enabled=False)]
    finally:
        release.set()
        runner.join(5)
    assert not runner.is_alive()
    assert not interfaces and not family._tcp_interfaces()
    assert detached == [True]
