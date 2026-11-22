# SPDX-License-Identifier: 0BSD
"""Opt-in Reticulum call-wake admission; this module never carries call audio.

Kept separate from mailbox acceptance: only genuine call setup may use a VoIP
push. No APNs transport is enabled by importing or constructing this provider.
"""

import base64
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import sys
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app/src/main/python"))
from family_call_wake import (
    destination_hash,
    voice_hash,
    signed_bytes,
    valid_shape,
    fresh,
    hex_value,
)
from provider import Unavailable

RETENTION = 120
CALLS_PER_MINUTE = 4
SEAL_INFO = b"neXt Reticulum call payload v1\0"


def seal(hint, recipient_public, *, ephemeral=None, nonce=None):
    """APNs sees only a sealed payload, not caller names or mesh addresses."""
    import os

    public = bytes.fromhex(recipient_public)
    if len(public) != 64 or voice_hash(public) != hint["recipient"]:
        raise ValueError("Call payload recipient does not match its key")
    secret = ephemeral or x25519.X25519PrivateKey.generate()
    nonce = os.urandom(12) if nonce is None else nonce
    if not isinstance(nonce, bytes) or len(nonce) != 12:
        raise ValueError("Invalid call payload nonce")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=SEAL_INFO).derive(
        secret.exchange(x25519.X25519PublicKey.from_public_bytes(public[:32]))
    )
    plain = json.dumps(hint, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(plain) > 2048:
        raise ValueError("Call payload is too large")
    aad = SEAL_INFO + bytes.fromhex(hint["recipient"])
    cipher = AESGCM(key).encrypt(nonce, plain, aad)
    encode = lambda value: base64.b64encode(value).decode("ascii")
    return {
        "aps": {},
        "next_call": dict(
            v=1,
            key=encode(
                secret.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                )
            ),
            nonce=encode(nonce),
            cipher=encode(cipher),
        ),
    }


class CallProvider:
    def __init__(self, audience, subscriptions, database, send):
        signed_bytes(
            dict(recipient="00" * 16, call="00" * 16, sender="00" * 64, issued=0),
            audience,
        )
        self.audience, self.subscriptions, self.send = audience, subscriptions, send
        self.database = sqlite3.connect(database)
        self.database.execute("PRAGMA secure_delete=ON")
        self.database.executescript("""
            CREATE TABLE IF NOT EXISTS call_registrations (
                owner TEXT PRIMARY KEY, voice TEXT UNIQUE NOT NULL, public_key TEXT NOT NULL,
                token TEXT NOT NULL, callers TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS call_wakes (
                recipient TEXT NOT NULL, call TEXT NOT NULL, sender TEXT NOT NULL,
                accepted INTEGER NOT NULL, state TEXT NOT NULL, hint TEXT NOT NULL,
                PRIMARY KEY(recipient,call));
            CREATE INDEX IF NOT EXISTS call_wake_expiry ON call_wakes(accepted);
        """)

    def authorized(self, owner, authorization):
        configured = self.subscriptions.get(owner, {})
        secret = (
            authorization[7:]
            if isinstance(authorization, str) and authorization.startswith("Bearer ")
            else ""
        )
        expected = configured.get("enrollment_hash")
        return (
            hex_value(secret, 32)
            and hex_value(expected, 32)
            and hmac.compare_digest(
                expected, hashlib.sha256(bytes.fromhex(secret)).hexdigest()
            )
        )

    def register(self, request, authorization):
        if (
            type(request) is not dict
            or request.keys() != {"recipient_key", "token", "callers"}
            or not hex_value(request["recipient_key"], 64)
            or type(request["callers"]) is not list
            or len(request["callers"]) > 256
            or any(not hex_value(value, 16) for value in request["callers"])
        ):
            return 400
        public = bytes.fromhex(request["recipient_key"])
        owner = destination_hash("lxmf.delivery", public)
        if not self.authorized(owner, authorization):
            return 403
        token = request["token"]
        if token is not None and (
            not isinstance(token, str)
            or not 32 <= len(token) <= 512
            or not hex_value(token, len(token) // 2)
        ):
            return 400
        if (
            token is not None
            and self.subscriptions.get(owner, {}).get("allow_calls") is not True
        ):
            return 403
        with self.database:
            if token is None:
                self.database.execute(
                    "DELETE FROM call_registrations WHERE owner=?", (owner,)
                )
            else:
                self.database.execute(
                    """INSERT INTO call_registrations VALUES (?,?,?,?,?)
                    ON CONFLICT(owner) DO UPDATE SET voice=excluded.voice,public_key=excluded.public_key,
                    token=excluded.token,callers=excluded.callers""",
                    (
                        owner,
                        voice_hash(public),
                        request["recipient_key"],
                        token,
                        json.dumps(sorted(set(request["callers"]))),
                    ),
                )
        return 204

    def subscription(self, recipient):
        row = self.database.execute(
            "SELECT owner,public_key,token,callers FROM call_registrations WHERE voice=?",
            (recipient,),
        ).fetchone()
        if not row or self.subscriptions.get(row[0], {}).get("allow_calls") is not True:
            return None
        return dict(
            owner=row[0], public_key=row[1], token=row[2], callers=json.loads(row[3])
        )

    def valid(self, hint, now, cancel):
        if not valid_shape(hint):
            return 400
        if not fresh(hint, now):
            return 403
        try:
            key = ed25519.Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(hint["sender"])[32:]
            )
            key.verify(
                bytes.fromhex(hint["signature"]),
                signed_bytes(hint, self.audience, cancel=cancel),
            )
        except (InvalidSignature, ValueError):
            return 403
        return 204

    def notify(self, hint, now=None):
        now = int(time.time()) if now is None else now
        status = self.valid(hint, now, False)
        if status != 204:
            return status
        with self.database:
            self.database.execute("BEGIN IMMEDIATE")
            subscription = self.subscription(hint["recipient"])
            caller = voice_hash(bytes.fromhex(hint["sender"]))
            if not subscription or caller not in subscription["callers"]:
                return 403
            existing = self.database.execute(
                "SELECT sender,state,hint FROM call_wakes WHERE recipient=? AND call=?",
                (hint["recipient"], hint["call"]),
            ).fetchone()
            if existing:
                if existing[0] != hint["sender"]:
                    return 403
                if existing[1] == "cancelled":
                    return 204
                return 204 if json.loads(existing[2]) == hint else 409
            count = self.database.execute(
                "SELECT COUNT(*) FROM call_wakes WHERE recipient=? AND accepted>=?",
                (hint["recipient"], now - 60),
            ).fetchone()[0]
            if count >= CALLS_PER_MINUTE:
                return 429
            try:
                self.send(subscription["token"], seal(hint, subscription["public_key"]))
            except (Unavailable, ValueError):
                return 503
            self.database.execute(
                "INSERT INTO call_wakes VALUES (?,?,?,?,?,?)",
                (
                    hint["recipient"],
                    hint["call"],
                    hint["sender"],
                    now,
                    "ringing",
                    json.dumps(hint),
                ),
            )
        return 204

    def cancel(self, hint, now=None):
        now = int(time.time()) if now is None else now
        status = self.valid(hint, now, True)
        if status != 204:
            return status
        with self.database:
            self.database.execute("BEGIN IMMEDIATE")
            existing = self.database.execute(
                "SELECT sender FROM call_wakes WHERE recipient=? AND call=?",
                (hint["recipient"], hint["call"]),
            ).fetchone()
            if existing:
                if existing[0] != hint["sender"]:
                    return 403
                self.database.execute(
                    "UPDATE call_wakes SET state='cancelled',hint=? WHERE recipient=? AND call=?",
                    (json.dumps(hint), hint["recipient"], hint["call"]),
                )
            else:
                subscription = self.subscription(hint["recipient"])
                caller = voice_hash(bytes.fromhex(hint["sender"]))
                if not subscription or caller not in subscription["callers"]:
                    return 403
                count = self.database.execute(
                    "SELECT COUNT(*) FROM call_wakes WHERE recipient=? AND accepted>=?",
                    (hint["recipient"], now - 60),
                ).fetchone()[0]
                if count >= CALLS_PER_MINUTE:
                    return 429
                self.database.execute(
                    "INSERT INTO call_wakes VALUES (?,?,?,?,?,?)",
                    (
                        hint["recipient"],
                        hint["call"],
                        hint["sender"],
                        now,
                        "cancelled",
                        json.dumps(hint),
                    ),
                )
        return 204

    def lookup(self, owner, call_id, authorization, now=None):
        if not hex_value(owner, 16) or not hex_value(call_id, 16):
            return 400, None
        if (
            not self.authorized(owner, authorization)
            or self.subscriptions.get(owner, {}).get("allow_calls") is not True
        ):
            return 403, None
        row = self.database.execute(
            """SELECT w.state,w.hint,w.accepted FROM call_wakes w
            JOIN call_registrations r ON r.voice=w.recipient WHERE r.owner=? AND w.call=?""",
            (owner, call_id),
        ).fetchone()
        now = int(time.time()) if now is None else now
        if not row:
            return 404, None
        hint = json.loads(row[1])
        state = row[0]
        if state == "ringing" and not fresh(hint, now):
            state = "expired"
        return 200, dict(state=state, hint=hint)

    def prune(self, now=None):
        now = int(time.time()) if now is None else now
        with self.database:
            deleted = self.database.execute(
                "DELETE FROM call_wakes WHERE accepted<?", (now - RETENTION,)
            ).rowcount
            for (owner,) in self.database.execute(
                "SELECT owner FROM call_registrations"
            ).fetchall():
                if self.subscriptions.get(owner, {}).get("allow_calls") is not True:
                    self.database.execute(
                        "DELETE FROM call_registrations WHERE owner=?", (owner,)
                    )
                    deleted += 1
        return deleted
