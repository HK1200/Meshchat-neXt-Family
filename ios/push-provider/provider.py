"""Send generic APNs alerts for guardian-authorized LXMF mailbox hints."""

import argparse
import base64
import errno
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import stat
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


ALERT = {"aps": {"alert": {"title": "New Family message", "body": "Open neXt Family to read it."},
                 "sound": "default"}}
HINT_FIELDS = {"recipient", "message", "sender", "issued", "signature"}
HINT_LIFETIME = 300
# Longer than every valid hint/retry window, without an indefinite delivery log.
ALERT_RECORD_RETENTION = 3600
NEXT_ALERT = {"aps": {"alert": {"title": "New neXt message", "body": "Open Meshchat neXt to read it."},
                       "sound": "default"}}
ALERTS_PER_MINUTE = 6


def hex_field(value, size):
    return type(value) is str and re.fullmatch(rf"[a-f0-9]{{{size * 2}}}", value) is not None


def signed_bytes(hint, audience):
    """Bytes signed by the approved sender's existing Reticulum identity."""
    fields = {key: hint[key] for key in ("recipient", "message", "sender", "issued")}
    return b"neXt Family push v1\x00" + json.dumps(
        {"audience": audience, **fields}, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


class Unavailable(Exception):
    pass


class Provider:
    def __init__(self, audience, spool, subscriptions, database, send):
        self.audience = audience
        self.spool = spool
        self.subscriptions = subscriptions
        self.send = send
        self.database = sqlite3.connect(database)
        self.database.execute("PRAGMA secure_delete = ON")
        self.database.executescript("""
            CREATE TABLE IF NOT EXISTS alerts (
                recipient TEXT NOT NULL,
                message TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                PRIMARY KEY (recipient, message)
            );
            CREATE INDEX IF NOT EXISTS recipient_time ON alerts (recipient, accepted);
            CREATE INDEX IF NOT EXISTS alert_expiry ON alerts (accepted);
            CREATE TABLE IF NOT EXISTS registrations (
                recipient TEXT PRIMARY KEY,
                token TEXT,
                senders TEXT NOT NULL
            );
        """)

    def prune(self, now=None):
        now = int(time.time()) if now is None else now
        with self.database:
            expired = self.database.execute("DELETE FROM alerts WHERE accepted < ?",
                                            (now - ALERT_RECORD_RETENTION,)).rowcount
            disabled = self.database.execute("DELETE FROM registrations WHERE token IS NULL").rowcount
        return expired + disabled

    def stored(self, recipient, message):
        """The relay writes destination || ciphertext || 32-byte propagation stamp."""
        for path in self.spool.glob(f"{message}_*"):
            try:
                if path.is_symlink():
                    continue
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                with os.fdopen(os.open(path, flags), "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size <= 48:
                        continue
                    recipient_bytes = stream.read(16)
                    if recipient_bytes.hex() != recipient:
                        continue
                    digest = hashlib.sha256(recipient_bytes)
                    remaining = info.st_size - 48
                    while remaining:
                        chunk = stream.read(min(128 * 1024, remaining))
                        if not chunk:
                            break  # Concurrent truncation is not a stored packet.
                        digest.update(chunk)
                        remaining -= len(chunk)
                    # The final 32 bytes are the propagation stamp, not part of
                    # the packet hash. Reject a changed length while reading.
                    if (remaining == 0 and len(stream.read(33)) == 32
                            and digest.hexdigest() == message):
                        return True
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.ELOOP, errno.ENOTDIR):
                    raise
                continue  # Removed or replaced by a concurrent mailbox fetch.
        return False

    def register(self, request, authorization):
        if (type(request) is not dict or request.keys() != {"recipient", "token", "senders"}
                or not hex_field(request["recipient"], 16) or type(request["senders"]) is not list
                or len(request["senders"]) > 256
                or any(not hex_field(sender, 64) for sender in request["senders"])):
            return 400
        token = request["token"]
        if token is not None and (not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32,512}", token)):
            return 400
        recipient = request["recipient"]
        subscription = self.subscriptions.get(recipient, {})
        secret_hash = subscription.get("enrollment_hash")
        prefix = "Bearer "
        secret = authorization[len(prefix):] if authorization.startswith(prefix) else ""
        if (not secret_hash or not hex_field(secret, 32)
                or not hmac.compare_digest(secret_hash, hashlib.sha256(bytes.fromhex(secret)).hexdigest())):
            return 403
        with self.database:
            if token is None:
                self.database.execute("DELETE FROM registrations WHERE recipient = ?", (recipient,))
            else:
                self.database.execute("""
                    INSERT INTO registrations VALUES (?, ?, ?)
                    ON CONFLICT(recipient) DO UPDATE SET token=excluded.token, senders=excluded.senders
                """, (recipient, token, json.dumps(request["senders"])))
        return 204

    def subscription(self, recipient):
        subscription = self.subscriptions.get(recipient)
        if not subscription:
            return None
        if "enrollment_hash" not in subscription:
            return subscription
        row = self.database.execute(
            "SELECT token, senders FROM registrations WHERE recipient = ?", (recipient,)
        ).fetchone()
        if not row or row[0] is None:
            return None
        return {"token": row[0], "senders": json.loads(row[1])}

    def notify(self, hint, now=None):
        now = int(time.time()) if now is None else now
        if (type(hint) is not dict or hint.keys() != HINT_FIELDS
                or not hex_field(hint["recipient"], 16) or not hex_field(hint["message"], 32)
                or not hex_field(hint["sender"], 64) or not hex_field(hint["signature"], 64)
                or type(hint["issued"]) is not int):
            return 400
        if not now - HINT_LIFETIME <= hint["issued"] <= now + 30:
            return 403
        recipient, message, sender = hint["recipient"], hint["message"], hint["sender"]
        try:
            key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(sender)[32:])
            key.verify(bytes.fromhex(hint["signature"]), signed_bytes(hint, self.audience))
        except InvalidSignature:
            return 403

        with self.database:
            # Serialize a decision even if multiple provider processes share this state.
            self.database.execute("BEGIN IMMEDIATE")
            subscription = self.subscription(recipient)
            if not subscription or sender not in subscription["senders"]:
                return 403
            if self.database.execute(
                "SELECT 1 FROM alerts WHERE recipient = ? AND message = ?", (recipient, message)
            ).fetchone():
                return 204
            if not self.stored(recipient, message):
                return 404
            sent, = self.database.execute(
                "SELECT count(*) FROM alerts WHERE recipient = ? AND accepted >= ?",
                (recipient, now - 60),
            ).fetchone()
            if sent >= ALERTS_PER_MINUTE:
                return 429
            try:
                self.send(subscription["token"], message)
            except Unavailable:
                return 503
            self.database.execute("INSERT INTO alerts VALUES (?, ?, ?)", (recipient, message, now))
        return 204


def b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class APNs:
    def __init__(self, settings):
        app = settings.get("app", "family")
        if app not in ("family", "next"):
            raise ValueError("APNs app must be family or next")
        self.alert = ALERT if app == "family" else NEXT_ALERT
        self.topic = settings["topic"]
        self.team = settings["team"]
        self.key_id = settings["key_id"]
        if not hex_field(settings["id_key"], 32):
            raise ValueError("Expected a private 32-byte alert identifier key")
        self.id_key = bytes.fromhex(settings["id_key"])
        self.key = serialization.load_pem_private_key(Path(settings["key_file"]).read_bytes(), None)
        if not isinstance(self.key, ec.EllipticCurvePrivateKey) or self.key.curve.name != "secp256r1":
            raise ValueError("Expected an Apple P-256 APNs private key")
        if settings["environment"] not in ("development", "production"):
            raise ValueError("Invalid APNs environment")
        self.host = ("api.sandbox.push.apple.com" if settings["environment"] == "development"
                     else "api.push.apple.com")
        self.jwt = ""
        self.jwt_time = 0

    def authorization(self, now):
        if not self.jwt or not 0 <= now - self.jwt_time < 45 * 60:
            header = b64url(json.dumps({"alg": "ES256", "kid": self.key_id}).encode())
            claims = b64url(json.dumps({"iss": self.team, "iat": now}).encode())
            text = f"{header}.{claims}"
            signature = self.key.sign(text.encode(), ec.ECDSA(hashes.SHA256()))
            r, s = decode_dss_signature(signature)
            self.jwt = f"{text}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
            self.jwt_time = now
        return self.jwt

    def __call__(self, token, message):
        # Curl reads credentials via stdin so the token and JWT stay out of argv.
        now = int(time.time())
        content = json.dumps(self.alert, separators=(",", ":"))
        alert_id = hmac.digest(self.id_key, bytes.fromhex(message), "sha256").hex()
        headers = [
            f"authorization: bearer {self.authorization(now)}",
            f"apns-topic: {self.topic}",
            "apns-push-type: alert",
            "apns-priority: 10",
            f"apns-expiration: {now + 300}",
            f"apns-collapse-id: {alert_id}",
            f"apns-id: {uuid.UUID(hex=alert_id[:32])}",
            "content-type: application/json",
        ]
        config = "\n".join([
            f"url = {json.dumps(f'https://{self.host}/3/device/{token}')}",
            *(f"header = {json.dumps(header)}" for header in headers),
            f"data = {json.dumps(content)}",
        ])
        try:
            result = subprocess.run(
                ["curl", "-q", "--http2", "--noproxy", "*", "--silent", "--max-time", "8",
                 "--output", "/dev/null", "--write-out", "%{http_code}", "--config", "-"],
                input=config, capture_output=True, timeout=10, text=True, check=True
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise Unavailable("APNs transport failed") from error
        if result.stdout != "200":
            raise Unavailable("APNs rejected the alert")


class Handler(BaseHTTPRequestHandler):
    timeout = 5

    def log_message(self, *_):
        pass  # Do not log caller IPs, routing identifiers, or hints.

    def do_POST(self):
        status = 404
        if self.path in ("/v1/mailbox-alert", "/v1/subscription"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 36_000 if self.path == "/v1/subscription" else 2048
                if not 0 < length <= limit:
                    raise ValueError("Invalid request length")
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("Incomplete request")
                hint = json.loads(body)
            except (OSError, ValueError, RecursionError):
                status = 400
            else:
                try:
                    if self.path == "/v1/subscription":
                        status = self.server.provider.register(hint, self.headers.get("Authorization", ""))
                    else:
                        status = self.server.provider.notify(hint)
                except (OSError, sqlite3.Error):
                    status = 503
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


class ProviderHTTPServer(HTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_cleanup = 0

    def service_actions(self):
        now = time.monotonic()
        if now >= self._next_cleanup:
            try:
                self.provider.prune()
            except sqlite3.Error:
                logging.getLogger(__name__).warning("Mailbox alert metadata cleanup will retry")
            self._next_cleanup = now + 60


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    if args.config.stat().st_mode & 0o077:
        raise ValueError("The config file must only be readable by its owner")
    config = json.loads(args.config.read_text())
    if Path(config["apns"]["key_file"]).stat().st_mode & 0o077:
        raise ValueError("The APNs key file must only be readable by its owner")
    for recipient, subscription in config["subscriptions"].items():
        valid = (hex_field(subscription.get("enrollment_hash"), 32) if "enrollment_hash" in subscription else
                 isinstance(subscription.get("token"), str)
                 and re.fullmatch(r"[a-f0-9]{32,512}", subscription["token"])
                 and all(hex_field(key, 64) for key in subscription["senders"]))
        if not hex_field(recipient, 16) or not valid:
            raise ValueError("Invalid subscription")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", config["apns"]["topic"]):
        raise ValueError("Invalid APNs topic")
    database = Path(config["database"])
    if not database.parent.is_dir() or database.parent.stat().st_mode & 0o077:
        raise ValueError("The database parent must be a private directory")
    os.umask(0o077)
    spool = Path(config["spool"])
    if not spool.is_dir():
        raise ValueError("The private LXMF spool must be an existing directory")
    provider = Provider(config["audience"], spool, config["subscriptions"], database, APNs(config["apns"]))
    try:
        with ProviderHTTPServer(("127.0.0.1", config.get("port", 8087)), Handler) as server:
            server.provider = provider
            server.serve_forever()
    finally:
        provider.database.close()


if __name__ == "__main__":
    main()
