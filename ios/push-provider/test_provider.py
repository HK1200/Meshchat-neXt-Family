import json
import os
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


def test_spool_verification_streams_large_encrypted_messages_without_loading_them(tmp_path):
    import tracemalloc

    recipient = "ab" * 16
    spool = tmp_path / "spool"
    spool.mkdir()
    temporary = spool / "pending"
    digest = sha256(bytes.fromhex(recipient))
    block = b"encrypted synthetic attachment" * 4096
    with temporary.open("wb") as stream:
        stream.write(bytes.fromhex(recipient))
        for _ in range(160):
            stream.write(block)
            digest.update(block)
        stream.write(bytes(32))
    message = digest.hexdigest()
    packet = spool / (message + "_123_14")
    temporary.rename(packet)
    broker = Provider("test-mailbox", spool, {}, tmp_path / "state.db", lambda *_: None)
    tracemalloc.start()
    try:
        assert broker.stored(recipient, message)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        broker.database.close()
    assert peak < 2 * 1024 * 1024, f"Spool verification allocated {peak} bytes for one file"


def test_streaming_spool_rejects_corruption_wrong_recipient_truncation_and_links(tmp_path):
    recipient = "ab" * 16
    message = mailbox_item(tmp_path, recipient, b"private synthetic ciphertext")
    packet = tmp_path / (message + "_123_14")
    original = packet.read_bytes()
    broker = Provider("test-mailbox", tmp_path, {}, tmp_path / "state.db", lambda *_: None)
    try:
        assert broker.stored(recipient, message)
        assert not broker.stored("cd" * 16, message)
        packet.write_bytes(original[:16] + b"changed" + original[23:])
        assert not broker.stored(recipient, message)
        packet.write_bytes(original[:40])
        assert not broker.stored(recipient, message)
        packet.unlink()
        target = tmp_path / "private-file"
        target.write_bytes(original)
        packet.symlink_to(target)
        assert not broker.stored(recipient, message)
        packet.unlink()
        os.mkfifo(packet)
        assert not broker.stored(recipient, message)
    finally:
        broker.database.close()


def test_old_delivery_metadata_expires_without_reopening_valid_hint_replays(tmp_path):
    from provider import ALERT_RECORD_RETENTION, HINT_LIFETIME
    assert ALERT_RECORD_RETENTION > HINT_LIFETIME + 30
    identity=RNS.Identity();recipient='ab'*16;alerts=[]
    broker=Provider('test-mailbox',tmp_path,{recipient:{'senders':[identity.get_public_key().hex()],'token':'test-device'}},tmp_path/'state.db',lambda *value:alerts.append(value))
    try:
        message=mailbox_item(tmp_path,recipient,b'private ciphertext')
        hint=hint_for(identity,recipient,message)
        assert broker.notify(hint,now=1000)==204
        broker.prune(now=1000+HINT_LIFETIME)
        assert broker.notify(hint,now=1000+HINT_LIFETIME)==204
        assert len(alerts)==1
        broker.prune(now=1001+ALERT_RECORD_RETENTION)
        assert broker.database.execute('select count(*) from alerts').fetchone()[0]==0
        assert broker.notify(hint,now=1001+ALERT_RECORD_RETENTION)==403
        assert len(alerts)==1
    finally:broker.database.close()


def test_disabling_deletes_the_active_registration_instead_of_retaining_empty_row(tmp_path):
    recipient='ab'*16;secret='31'*32
    broker=Provider('test-mailbox',tmp_path,{recipient:{'enrollment_hash':sha256(bytes.fromhex(secret)).hexdigest()}},tmp_path/'state.db',lambda *_:None)
    try:
        row={'recipient':recipient,'token':'e1'*32,'senders':[RNS.Identity().get_public_key().hex()]}
        assert broker.register(row,'Bearer '+secret)==204
        assert broker.register(dict(row,token=None,senders=[]),'Bearer '+secret)==204
        assert broker.database.execute('select count(*) from registrations').fetchone()[0]==0
        assert broker.subscription(recipient) is None
        assert row['token'].encode() not in (tmp_path/'state.db').read_bytes()
        assert row['senders'][0].encode() not in (tmp_path/'state.db').read_bytes()
    finally:broker.database.close()


def test_idle_http_server_prunes_without_any_incoming_request(tmp_path):
    import threading,time
    from provider import ProviderHTTPServer,Handler
    broker=Provider('test-mailbox',tmp_path,{},tmp_path/'state.db',lambda *_:None)
    try:
        with broker.database:
            broker.database.executemany('insert into alerts values(?,?,?)', [('old','old',0),('current','current',int(time.time()))])
            broker.database.execute('insert into registrations values(?,NULL,?)',('disabled','[]'))
        with ProviderHTTPServer(('127.0.0.1',0),Handler) as server:
            server.provider=broker
            stop=threading.Timer(.1,server.shutdown);stop.start()
            try:server.serve_forever(poll_interval=.01)
            finally:stop.join(timeout=2)
        assert broker.database.execute('select recipient from alerts').fetchall()==[('current',)]
        assert broker.database.execute('select count(*) from registrations').fetchone()[0]==0
    finally:broker.database.close()
