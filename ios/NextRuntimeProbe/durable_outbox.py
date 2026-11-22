# SPDX-License-Identifier: 0BSD
"""Private restart journal for signed, explicitly submitted neXt messages.

All SQLite calls belong to the app loop. Journal writes join the history
transaction; this module never commits another component's transaction.
"""
from dataclasses import asdict, is_dataclass
import hashlib
import json
import re

import LXMF

MAX_PACKET = 11_000_000
MAX_TOTAL = 50_000_000
MAX_PENDING = 100


def schema(database):
    database.execute("""CREATE TABLE IF NOT EXISTS next_pending_messages (
        hash TEXT PRIMARY KEY, peer TEXT NOT NULL, packet BLOB NOT NULL,
        policy TEXT NOT NULL)""")


def policy(method, automatic, relay, route, *, recipient=None):
    if type(method) is not int or method not in (LXMF.LXMessage.DIRECT, LXMF.LXMessage.OPPORTUNISTIC, LXMF.LXMessage.PROPAGATED):
        raise ValueError('Unsupported pending delivery method')
    if type(automatic) is not bool:
        raise ValueError('Invalid automatic delivery choice')
    if relay is not None and (not isinstance(relay, bytes) or len(relay) != 16):
        raise ValueError('Invalid pending mailbox')
    if method == LXMF.LXMessage.PROPAGATED and relay is None:
        raise ValueError('A propagated message requires its selected mailbox')
    if recipient is not None and (not isinstance(recipient, bytes) or len(recipient) != 64):
        raise ValueError('Invalid pending recipient public key')
    # Only a fingerprint is needed to prevent a changed route receiving a hint.
    fingerprint = route_fingerprint(route)
    return dict(method=method, automatic=automatic, relay=relay.hex() if relay else None, route=fingerprint, recipient=recipient.hex() if recipient is not None else None)


def route_fingerprint(route):
    if route is None: return None
    value = asdict(route) if is_dataclass(route) else route
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def enqueue(database, row, packet, delivery):
    """Call inside the same transaction that saves the visible Sending row."""
    if (row.get('state') != 'sending' or not row.get('is_outbound')
            or row.get('is_private_telemetry') or str(row.get('content', '')).startswith('!NFLOC1:')):
        raise ValueError('Only ordinary pending messages can enter the restart journal')
    key, peer = row.get('hash'), row.get('destination_hash')
    if (not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key)
            or not isinstance(peer, str) or not re.fullmatch('[a-f0-9]{32}', peer)
            or not isinstance(packet, bytes) or not 96 < len(packet) <= MAX_PACKET):
        raise ValueError('Invalid pending signed message')
    recipient_identity(delivery, peer)
    current = database.execute('SELECT COUNT(*), COALESCE(SUM(length(packet)), 0) FROM next_pending_messages WHERE hash != ?', (key,)).fetchone()
    if current[0] >= MAX_PENDING or current[1] + len(packet) > MAX_TOTAL:
        raise ValueError('Pending messages have filled the local queue. Wait for delivery or remove an unsent conversation.')
    database.execute('INSERT INTO next_pending_messages VALUES (?, ?, ?, ?) ON CONFLICT(hash) DO UPDATE SET packet=excluded.packet, policy=excluded.policy',
                     (key, peer, packet, json.dumps(delivery, sort_keys=True)))


def remove(database, key):
    database.execute('DELETE FROM next_pending_messages WHERE hash = ?', (key,))


def selected_policy(raw):
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) not in ({'method', 'automatic', 'relay', 'route'}, {'method', 'automatic', 'relay', 'route', 'recipient'}):
        raise ValueError('Invalid saved delivery choices')
    relay = bytes.fromhex(value['relay']) if isinstance(value['relay'], str) else value['relay']
    recipient = value.get('recipient')
    if recipient is not None and (not isinstance(recipient, str) or not re.fullmatch('[a-f0-9]{128}', recipient)):
        raise ValueError('Invalid saved recipient public key')
    result = policy(value['method'], value['automatic'], relay, None, recipient=bytes.fromhex(recipient) if recipient else None)
    if value['route'] is not None and (not isinstance(value['route'], str) or not re.fullmatch('[a-f0-9]{64}', value['route'])):
        raise ValueError('Invalid saved alert route')
    result['route'] = value['route']
    return result


def recipient_identity(delivery, peer):
    """Recover only a public key bound to this exact LXMF destination."""
    import RNS
    saved = delivery.get('recipient')
    if saved is None:
        # Older journals remain readable. Never invent a missing public key.
        return RNS.Identity.recall(bytes.fromhex(peer), _no_use=True)
    if not isinstance(saved, str) or not re.fullmatch('[a-f0-9]{128}', saved):
        raise ValueError('Invalid saved recipient public key')
    identity = RNS.Identity(create_keys=False)
    identity.load_public_key(bytes.fromhex(saved))
    if RNS.Destination.hash_from_name_and_identity('lxmf.delivery', identity).hex() != peer:
        raise ValueError('The pending recipient public key does not match its address')
    return identity


def recreate(packet, expected_hash, peer, probe, delivery):
    """Validate the original signature and reconstruct through standard LXMF.

    Repacking uses the app's same private identity and original timestamp.
    It must preserve the signed message hash, including every attachment byte.
    """
    if not isinstance(packet, bytes) or not 96 < len(packet) <= MAX_PACKET:
        raise ValueError('Invalid pending packet length')
    original = LXMF.LXMessage.unpack_from_bytes(packet)
    if (original.hash.hex() != expected_hash or original.destination_hash.hex() != peer
            or original.source_hash != probe.source.hash):
        raise ValueError('Pending message identity does not match this conversation')
    import RNS
    from RNS.vendor import umsgpack
    payload = umsgpack.unpackb(packet[96:])
    if not isinstance(payload, list) or len(payload) not in (4, 5):
        raise ValueError('Invalid signed pending payload')
    signed = packet[:32] + umsgpack.packb(payload[:4])
    if not probe.source.identity.validate(packet[32:96], signed + RNS.Identity.full_hash(signed)):
        raise ValueError('The pending message signature is invalid')
    fields = original.fields if isinstance(original.fields, dict) else {}
    if (original.content_as_string().startswith('!NFLOC1:') or any(key in fields for key in
            (LXMF.FIELD_TELEMETRY, LXMF.FIELD_TELEMETRY_STREAM))):
        raise ValueError('Location updates must never be replayed after a restart')
    identity = recipient_identity(delivery, peer)
    if identity is None or RNS.Destination.hash_from_name_and_identity('lxmf.delivery', identity).hex() != peer:
        raise LookupError('The recipient identity is not currently known')
    message = probe._message(identity, original.content_as_string(), fields, delivery['method'])
    message.set_title_from_bytes(original.title)
    message.timestamp = original.timestamp
    message.pack()
    if message.hash != original.hash:
        raise ValueError('Reconstructed pending content does not match its signed identifier')
    return message
