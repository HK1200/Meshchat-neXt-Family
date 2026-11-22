import json
import subprocess
from hashlib import sha256

import RNS
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from provider import ALERT, NEXT_ALERT, APNs, Provider, Unavailable, signed_bytes


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


@pytest.mark.parametrize("app,expected", [("family", ALERT), ("next", NEXT_ALERT)])
def test_apns_uses_generic_payload_and_hides_credentials(tmp_path, monkeypatch, app, expected):
    key = ec.generate_private_key(ec.SECP256R1())
    keyfile = tmp_path / "key.pem"
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    calls = []

    def run(args, **options):
        calls.append((args, options))
        return subprocess.CompletedProcess(args, 0, stdout="200")

    monkeypatch.setattr(subprocess, "run", run)
    send = APNs({"app": app, "topic": "org.example.mailbox", "team": "TEST", "key_id": "KEY",
                 "key_file": keyfile, "environment": "development", "id_key": "ef" * 32})
    token, message = "ab" * 32, "cd" * 32
    send(token, message)
    args, options = calls[0]
    assert "--http2" in args and token not in " ".join(args)
    config = options["input"]
    assert f"api.sandbox.push.apple.com/3/device/{token}" in config
    assert "apns-push-type: alert" in config and "apns-priority: 10" in config
    assert message not in config
    assert json.loads(json.loads(config.split("data = ")[1])) == expected


def test_guardian_enrollment_token_rotation_and_disable(tmp_path):
    approved, removed = RNS.Identity(), RNS.Identity()
    recipient = "ab" * 16
    secret = "31" * 32
    subscriptions = {recipient: {"enrollment_hash": sha256(bytes.fromhex(secret)).hexdigest()}}
    alerts = []
    database = tmp_path / "provider.db"
    broker = Provider("test-mailbox", tmp_path, subscriptions, database, lambda *item: alerts.append(item))
    token = "e1" * 32
    registration = {"recipient": recipient, "token": token,
                    "senders": [approved.get_public_key().hex(), removed.get_public_key().hex()]}
    msg = mailbox_item(tmp_path, recipient, b"mail waiting before its guardian enables push")
    assert broker.notify(hint_for(approved, recipient, msg), now=1000) == 403
    assert broker.register(registration, "Bearer " + "32" * 32) == 403
    assert broker.register(registration, "Bearer " + secret) == 204
    assert broker.notify(hint_for(approved, recipient, msg), now=1000) == 204

    new_token = "e2" * 32
    registration["token"] = new_token
    registration["senders"].pop()
    assert broker.register(registration, "Bearer " + secret) == 204
    pending = mailbox_item(tmp_path, recipient, b"mail waiting after updating sender list")
    assert broker.notify(hint_for(removed, recipient, pending), now=1000) == 403
    assert broker.notify(hint_for(approved, recipient, pending), now=1000) == 204
    assert alerts == [(token, msg), (new_token, pending)]

    assert broker.register(dict(registration, token=None, senders=[]), "Bearer " + secret) == 204
    broker.database.close()
    broker = Provider("test-mailbox", tmp_path, subscriptions, database, lambda *item: alerts.append(item))
    assert broker.notify(hint_for(approved, recipient, pending), now=1001) == 403
    broker.database.close()
