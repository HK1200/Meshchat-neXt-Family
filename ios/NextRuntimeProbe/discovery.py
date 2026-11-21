"""Bounded, passive LXMF discovery for the iOS client; never adds contacts."""
from datetime import datetime, timezone
import sqlite3
import threading
import time
import unicodedata

import LXMF
import RNS


class ClientDiscovery:
    aspect_filter = "lxmf.delivery"
    receive_path_responses = True
    capacity = 1000
    retention_seconds = 30 * 24 * 60 * 60

    def __init__(self, path, own_address):
        self.own_address = own_address
        self.lock = threading.RLock()
        self.closed = False
        self.db = sqlite3.connect(path, check_same_thread=False)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS clients (
                address TEXT PRIMARY KEY, identity_hash TEXT NOT NULL,
                public_key TEXT NOT NULL, name TEXT NOT NULL, last_seen REAL NOT NULL
            )""")
        path.chmod(0o600)

    def received_announce(self, destination_hash, announced_identity, app_data, announce_packet_hash=None):
        # Reticulum invokes this handler after validating the announce signature.
        # Check the identity's exact LXMF destination as well; a name never acts
        # as an identity or an approval and cannot redirect an existing contact.
        if (not isinstance(destination_hash, bytes) or len(destination_hash) != 16
                or destination_hash.hex() == self.own_address or announced_identity is None):
            return
        expected = RNS.Destination.hash_from_name_and_identity("lxmf.delivery", announced_identity)
        if destination_hash != expected:
            return
        public_key = announced_identity.get_public_key()
        if not isinstance(public_key, bytes) or len(public_key) != 64:
            return
        if app_data is not None and (not isinstance(app_data, bytes) or len(app_data) > 512):
            return
        try:
            name = LXMF.display_name_from_app_data(app_data) or "Anonymous Peer"
        except Exception:  # Malformed remote MessagePack must not stop announce processing.
            name = "Anonymous Peer"
        if not isinstance(name, str):
            name = "Anonymous Peer"
        name = "".join(c for c in name if not unicodedata.category(c).startswith("C"))
        name = name.encode("utf-8")[:128].decode("utf-8", errors="ignore").strip() or "Anonymous Peer"
        now = time.time()
        with self.lock:
            if self.closed:
                return
            with self.db:
                self._remember(destination_hash, announced_identity, public_key, name, now)

    def _remember(self, destination_hash, announced_identity, public_key, name, now):
        self.db.execute("""INSERT INTO clients VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET name=excluded.name,
                public_key=excluded.public_key, identity_hash=excluded.identity_hash,
                last_seen=excluded.last_seen""",
            (destination_hash.hex(), announced_identity.hash.hex(), public_key.hex(), name, now))
        self.db.execute("DELETE FROM clients WHERE last_seen < ?", (now - self.retention_seconds,))
        self.db.execute("""DELETE FROM clients WHERE address NOT IN
            (SELECT address FROM clients ORDER BY last_seen DESC, address LIMIT ?)""", (self.capacity,))

    def page(self, query):
        aspect = query.get("aspect", "lxmf.delivery")
        search = query.get("search", "")
        if not isinstance(search, str) or len(search) > 256:
            raise ValueError("Search must be at most 256 characters")
        try:
            limit, offset = int(query.get("limit", 25)), int(query.get("offset", 0))
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Invalid discovery pagination") from error
        if not 1 <= limit <= 100 or not 0 <= offset <= self.capacity:
            raise ValueError("Invalid discovery pagination")
        if aspect != self.aspect_filter:
            return []
        with self.lock:
            if self.closed:
                return []
            rows = self.db.execute("""SELECT address, identity_hash, public_key, name, last_seen
                FROM clients WHERE last_seen >= ? ORDER BY last_seen DESC, address""",
                (time.time() - self.retention_seconds,)).fetchall()
        needle = search.strip().casefold()
        rows = [row for row in rows if needle in (row[3] + " " + row[0]).casefold()]
        return [{"destination_hash": address, "identity_hash": identity_hash,
                 "public_key": public_key, "display_name": name, "aspect": self.aspect_filter,
                 "created_at": datetime.fromtimestamp(seen, timezone.utc).isoformat()}
                for address, identity_hash, public_key, name, seen in rows[offset:offset + limit]]

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.db.close()
