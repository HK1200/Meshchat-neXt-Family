"""Remote names discover clients without approving or remapping contacts."""
from pathlib import Path
import sys
import time
import pytest
import RNS
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"))
from discovery import ClientDiscovery


def announce(store, name=b"Private Test"):
    identity = RNS.Identity()
    address = RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity)
    store.received_announce(address, identity, name)
    return address.hex(), identity


def test_verified_client_names_are_searchable_and_survive_reopening(tmp_path):
    path = tmp_path / "clients.sqlite3"
    store = ClientDiscovery(path, "ab" * 16)
    address, identity = announce(store, "Private 雪".encode())
    assert store.page({"search": "PRIVATE 雪"})[0]["destination_hash"] == address
    assert store.page({"search": address})[0]["identity_hash"] == identity.hash.hex()
    assert store.page({})[0]["public_key"] == identity.get_public_key().hex()
    assert store.page({"search": "missing"}) == []
    assert store.page({"aspect": "rrc.hub"}) == []
    assert store.page({"aspect": "lxmf.propagation"}) == []
    store.close()
    store = ClientDiscovery(path, "ab" * 16)
    assert store.page({})[0]["display_name"] == "Private 雪"
    store.close()
    assert path.stat().st_mode & 0o777 == 0o600


def test_other_identity_cannot_overwrite_an_address_and_own_client_is_hidden(tmp_path):
    store = ClientDiscovery(tmp_path / "clients", "ab" * 16)
    address, identity = announce(store)
    store.received_announce(bytes.fromhex(address), RNS.Identity(), b"Impostor")
    store.received_announce(bytes.fromhex("ab" * 16), identity, b"Own")
    assert [r["display_name"] for r in store.page({})] == ["Private Test"]
    # Seeing an announce never creates a saved contact or changes its nickname.
    assert store.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("clients",)]
    store.close()
    store.received_announce(bytes.fromhex(address), identity, b"Late callback")
    assert store.page({}) == []
    store.close()


def test_remote_names_and_storage_are_bounded_and_expire(tmp_path):
    store = ClientDiscovery(tmp_path / "clients", "ab" * 16)
    store.capacity = 3
    address, identity = announce(store, "\nName\u202E雪".encode())
    assert store.page({})[0]["display_name"] == "Name雪"
    store.received_announce(bytes.fromhex(address), identity, b"\x91")
    assert store.page({})[0]["display_name"] == "Anonymous Peer"
    store.received_announce(bytes.fromhex(address), identity, b"x" * 513)
    assert store.page({})[0]["display_name"] == "Anonymous Peer"
    for _ in range(4): announce(store)
    assert len(store.page({})) == 3
    with store.db: store.db.execute("UPDATE clients SET last_seen=?", (time.time() - store.retention_seconds - 1,))
    assert store.page({}) == []
    announce(store)
    assert store.db.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 1
    store.close()


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": "oops"}, {"limit": 101}, {"offset": -1}, {"offset": 1001}, {"search": "x" * 257}])
def test_invalid_pagination_is_rejected_without_reading_unbounded_rows(tmp_path, query):
    store = ClientDiscovery(tmp_path / "clients", "ab" * 16)
    with pytest.raises(ValueError): store.page(query)
    store.close()
