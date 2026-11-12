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
