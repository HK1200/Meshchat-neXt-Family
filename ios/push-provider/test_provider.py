import json
import subprocess
from hashlib import sha256

import RNS
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from provider import ALERT, APNs, Provider, Unavailable, signed_bytes


def mailbox_item(spool, recipient, content):
    packet = bytes.fromhex(recipient) + content
    message = sha256(packet).hexdigest()
    (spool / (message + "_123_14")).write_bytes(packet + bytes(32))
    return message


def hint_for(identity, recipient, message, issued=1000, audience="test-mailbox"):
    hint = {"recipient": recipient, "message": message, "issued": issued,
            "sender": identity.get_public_key().hex()}
    hint["signature"] = identity.sign(signed_bytes(hint, audience)).hex()
    return hint


def test_approval_spool_and_replay(tmp_path):
    approved, outsider = RNS.Identity(), RNS.Identity()
    recipient = "ab" * 16
    spool = tmp_path / "spool"
    spool.mkdir()
    message = mailbox_item(spool, recipient, b"example encrypted mailbox item")
    database = tmp_path / "provider.db"
    subscriptions = {recipient: {"senders": [approved.get_public_key().hex()], "token": "test-device"}}
    alerts = []
    broker = Provider("test-mailbox", spool, subscriptions, database, lambda *item: alerts.append(item))
    assert broker.notify(hint_for(outsider, recipient, message), now=1000) == 403
    assert broker.notify(hint_for(approved, recipient, message, issued=699), now=1000) == 403
    assert broker.notify(hint_for(approved, recipient, message, audience="other"), now=1000) == 403
    assert broker.notify(hint_for(approved, recipient, "ff" * 32), now=1000) == 404
    bad_id = "00" * 32
    (spool / (bad_id + "_123_14")).write_bytes((spool / (message + "_123_14")).read_bytes())
    assert broker.notify(hint_for(approved, recipient, bad_id), now=1000) == 404

    hint = hint_for(approved, recipient, message)
    assert broker.notify(hint, now=1000) == 204
    broker.database.close()
    broker = Provider("test-mailbox", spool, subscriptions, database, lambda *item: alerts.append(item))
    assert broker.notify(hint, now=1001) == 204
    assert alerts == [("test-device", message)]
    subscriptions.clear()
    assert broker.notify(hint, now=1002) == 403
    broker.database.close()


def test_transient_failure_and_rate_limit(tmp_path):
    approved = RNS.Identity()
    recipient = "ab" * 16
    subscription = {"senders": [approved.get_public_key().hex()], "token": "test-device"}
    outcomes = iter([Unavailable(), None])

    def send(*_):
        result = next(outcomes, None)
        if result is not None:
            raise result

    broker = Provider("test-mailbox", tmp_path, {recipient: subscription}, tmp_path / "state.db", send)
    for index in range(6):
        hint = hint_for(approved, recipient, mailbox_item(tmp_path, recipient, bytes(32) + bytes([index])))
        if index == 0:
            assert broker.notify(hint, now=1000) == 503
        assert broker.notify(hint, now=1000) == 204
    hint = hint_for(approved, recipient, mailbox_item(tmp_path, recipient, b"limit" * 8))
    assert broker.notify(hint, now=1001) == 429
    assert broker.notify(hint, now=1061) == 204
    broker.database.close()


def test_apns_uses_generic_payload_and_hides_credentials(tmp_path, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    keyfile = tmp_path / "key.pem"
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    calls = []

    def run(args, **options):
        calls.append((args, options))
        return subprocess.CompletedProcess(args, 0, stdout="200")

    monkeypatch.setattr(subprocess, "run", run)
    send = APNs({"topic": "org.example.mailbox", "team": "TEST", "key_id": "KEY",
                 "key_file": keyfile, "environment": "development", "id_key": "ef" * 32})
    token, message = "ab" * 32, "cd" * 32
    send(token, message)
    args, options = calls[0]
    assert "--http2" in args and token not in " ".join(args)
    config = options["input"]
    assert f"api.sandbox.push.apple.com/3/device/{token}" in config
    assert "apns-push-type: alert" in config and "apns-priority: 10" in config
    assert message not in config
    assert json.loads(json.loads(config.split("data = ")[1])) == ALERT
