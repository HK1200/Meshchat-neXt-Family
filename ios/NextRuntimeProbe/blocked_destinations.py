"""Durable identity-bound bans shared by messaging, calls and location.

Database work stays on the app loop. Network callbacks read an immutable snapshot;
no names or unverified remote metadata are used to decide who is blocked.
"""
from datetime import datetime, timezone
import re

import RNS


def address(value):
    if not isinstance(value, str) or not re.fullmatch('[a-fA-F0-9]{32}', value):
        raise ValueError('Use a 32-character Reticulum address')
    return value.lower()


def aliases(value):
    value = address(value)
    raw = bytes.fromhex(value)
    identity = RNS.Identity.recall(raw) or RNS.Identity.recall(raw, from_identity_hash=True)
    result = {value}
    if identity is not None:
        result.update((identity.hash.hex(),
                       RNS.Destination.hash_from_name_and_identity('lxmf.delivery', identity).hex(),
                       RNS.Destination.hash_from_name_and_identity('lxst.telephony', identity).hex()))
    return frozenset(result)


class PeerBlocks:
    def __init__(self, database, own_identity):
        self.db = database
        self.own = frozenset((own_identity.hash.hex(),
            RNS.Destination.hash_from_name_and_identity('lxmf.delivery', own_identity).hex(),
            RNS.Destination.hash_from_name_and_identity('lxst.telephony', own_identity).hex()))
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS next_blocked_destinations (destination_hash TEXT PRIMARY KEY, created_at TEXT NOT NULL)')
        self.blocked = frozenset(address(row[0]) for row in self.db.execute('SELECT destination_hash FROM next_blocked_destinations'))

    def denies(self, value):
        try:
            value = address(value)
            return bool(self.blocked and self.blocked.intersection(aliases(value)))
        except (ValueError, TypeError):
            return True

    def checked_aliases(self, value):
        keys = aliases(value)
        if keys.intersection(self.own):
            raise ValueError('Your own Reticulum identity cannot be blocked')
        return keys

    def add(self, value):
        keys = self.checked_aliases(value)
        if len(self.blocked | keys) > 10000:
            raise ValueError('At most 10,000 Reticulum addresses may be blocked')
        stamp = datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.executemany('INSERT OR IGNORE INTO next_blocked_destinations VALUES (?,?)',
                                [(key, stamp) for key in sorted(keys)])
        self.blocked = self.blocked | keys
        return keys

    def remove(self, value):
        keys = aliases(value)
        with self.db:
            self.db.executemany('DELETE FROM next_blocked_destinations WHERE destination_hash = ?',
                                [(key,) for key in keys])
        self.blocked = self.blocked - keys
        return keys

    def snapshot(self):
        return [{'destination_hash':peer, 'created_at':stamp} for peer, stamp in self.db.execute(
            'SELECT destination_hash,created_at FROM next_blocked_destinations ORDER BY created_at,destination_hash')]
