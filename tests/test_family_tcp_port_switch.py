import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/src/main/python"))
import family_backend as family


def test_rmap_port_switch_shows_each_configured_endpoint(monkeypatch):
    peer = {
        "host": "RMAP.world",
        "port": 4343,
        "enabled": True,
        "backupHost": "rmap.world",
        "backupPort": 4242,
    }
    monkeypatch.setattr(family, "_peer", None)
    monkeypatch.setattr(family, "_backup_peers", ())
    assert family._tcp_connection_status(peer) == [
        {"host": "RMAP.world", "port": 4343, "online": False},
        {"host": "reticulum.washmesh.net", "port": 7242, "online": False},
        {"host": "rns.chimesh.org", "port": 4242, "online": False},
    ]
    peer.update(backupHost="private.example", backupPort=9000)
    assert family._tcp_endpoints(peer) == [("RMAP.world", 4343), ("private.example", 9000)]


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
    monkeypatch.setattr(family, "_state", {"peer": {
        "host": "rmap.world", "port": 4343, "enabled": True,
    }})
    monkeypatch.setattr(family, "_announce_available_routes", lambda: None)

    def connect(owner, config):
        assert (config["target_host"], config["target_port"]) == ("rmap.world", 4343)
        raise ConnectionError("Primary offline")

    monkeypatch.setattr(family_tcp, "FamilyTCPInterface", connect)
    family._connect()
    assert primary.detached
    assert family._tcp_interfaces() == (wash, chicago)
    assert family._online_tcp() is wash
    assert [row["online"] for row in family._tcp_connection_status(family._state["peer"])] == [
        False, True, True,
    ]
