# SPDX-License-Identifier: 0BSD
"""Private mock-provider proof; no Apple credentials, network or real calls."""

import base64
import hashlib
import json
from pathlib import Path
import sys

import pytest
import RNS
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app/src/main/python"), str(ROOT / "ios/push-provider")]
# Select this checkout before importing its unpackaged app/provider modules.
from family_call_wake import build_hint, destination_hash, voice_hash  # noqa: E402
from call_provider import CallProvider, SEAL_INFO  # noqa: E402
from provider import Unavailable  # noqa: E402


@pytest.fixture
def setup(tmp_path):
    caller, recipient = RNS.Identity(), RNS.Identity()
    owner = destination_hash("lxmf.delivery", recipient.get_public_key())
    code = bytes([1]) * 32
    subscriptions = {
        owner: dict(enrollment_hash=hashlib.sha256(code).hexdigest(), allow_calls=True)
    }
    sent = []
    provider = CallProvider(
        "private-calls",
        subscriptions,
        tmp_path / "calls.sqlite3",
        lambda token, payload: sent.append((token, payload)),
    )
    registration = dict(
        recipient_key=recipient.get_public_key().hex(),
        token="ab" * 32,
        callers=[voice_hash(caller.get_public_key())],
    )
    authorization = "Bearer " + code.hex()
    assert provider.register(registration, authorization) == 204
    yield dict(
        caller=caller,
        recipient=recipient,
        owner=owner,
        subscriptions=subscriptions,
        provider=provider,
        sent=sent,
        registration=registration,
        authorization=authorization,
    )
    provider.database.close()


def hint(s, **kwargs):
    return build_hint(
        s["caller"],
        voice_hash(s["recipient"].get_public_key()),
        "private-calls",
        issued=1000,
        **kwargs,
    )


def unseal(s, payload):
    assert set(payload) == {"aps", "next_call"}
    data = payload["next_call"]
    assert set(data) == {"v", "key", "nonce", "cipher"} and data["v"] == 1
    private = x25519.X25519PrivateKey.from_private_bytes(
        s["recipient"].get_private_key()[:32]
    )
    shared = private.exchange(
        x25519.X25519PublicKey.from_public_bytes(base64.b64decode(data["key"]))
    )
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=SEAL_INFO).derive(
        shared
    )
    plain = AESGCM(key).decrypt(
        base64.b64decode(data["nonce"]),
        base64.b64decode(data["cipher"]),
        SEAL_INFO + bytes.fromhex(voice_hash(s["recipient"].get_public_key())),
    )
    return json.loads(plain)


def test_addresses_match_standard_reticulum_and_only_recipient_can_read_payload(setup):
    s = setup
    public = s["recipient"].get_public_key()
    assert (
        voice_hash(public)
        == RNS.Destination.hash_from_name_and_identity(
            "lxst.telephony", s["recipient"]
        ).hex()
    )
    assert (
        s["owner"]
        == RNS.Destination.hash_from_name_and_identity(
            "lxmf.delivery", s["recipient"]
        ).hex()
    )
    packet = hint(s)
    assert s["provider"].notify(packet, now=1000) == 204
    assert len(s["sent"]) == 1 and s["sent"][0][0] == "ab" * 32
    sealed = s["sent"][0][1]
    assert packet["sender"] not in json.dumps(sealed) and packet[
        "recipient"
    ] not in json.dumps(sealed)
    assert unseal(s, sealed) == packet
    other = dict(s, recipient=RNS.Identity())
    with pytest.raises(InvalidTag):
        unseal(other, sealed)
    assert s["provider"].notify(packet, now=1000) == 204 and len(s["sent"]) == 1


@pytest.mark.parametrize(
    "field", ["recipient", "call", "sender", "signature", "issued"]
)
def test_tampering_cannot_create_an_alert(setup, field):
    s = setup
    packet = hint(s)
    packet[field] = (
        1001
        if field == "issued"
        else ("00" * 64 if field in ("sender", "signature") else "00" * 16)
    )
    assert s["provider"].notify(packet, now=1000) == 403 and not s["sent"]


def test_unapproved_signed_caller_and_cross_audience_are_rejected(setup):
    s = setup
    other = RNS.Identity()
    packet = build_hint(
        other, voice_hash(s["recipient"].get_public_key()), "private-calls", issued=1000
    )
    assert s["provider"].notify(packet, now=1000) == 403
    packet = build_hint(
        s["caller"],
        voice_hash(s["recipient"].get_public_key()),
        "different-provider",
        issued=1000,
    )
    assert s["provider"].notify(packet, now=1000) == 403 and not s["sent"]


@pytest.mark.parametrize(
    "issued,status", [(969, 403), (970, 204), (1010, 204), (1011, 403)]
)
def test_call_window_is_short_and_bounded(setup, issued, status):
    s = setup
    packet = build_hint(
        s["caller"],
        voice_hash(s["recipient"].get_public_key()),
        "private-calls",
        issued=issued,
    )
    assert s["provider"].notify(packet, now=1000) == status


@pytest.mark.parametrize(
    "change", ["bool-time", "extra-field", "bad-call", "bad-signature"]
)
def test_invalid_shapes_are_rejected_before_delivery(setup, change):
    s = setup
    packet = hint(s)
    if change == "bool-time":
        packet["issued"] = True
    elif change == "extra-field":
        packet["audio"] = "not allowed"
    elif change == "bad-call":
        packet["call"] = "not-a-call"
    else:
        packet["signature"] = "zz" * 64
    assert s["provider"].notify(packet, now=1000) == 400 and not s["sent"]


def test_cancellation_is_domain_separated_and_can_arrive_before_wake(setup):
    s = setup
    packet = hint(s)
    cancel = hint(s, call_id=packet["call"], cancel=True)
    assert s["provider"].cancel(packet, now=1000) == 403
    assert s["provider"].notify(cancel, now=1000) == 403
    assert s["provider"].cancel(cancel, now=1000) == 204
    assert s["provider"].notify(packet, now=1000) == 204 and not s["sent"]
    status, value = s["provider"].lookup(
        s["owner"], packet["call"], s["authorization"], now=1000
    )
    assert status == 200 and value["state"] == "cancelled"


def test_remote_end_never_sends_another_voip_push(setup):
    s = setup
    packet = hint(s)
    assert s["provider"].notify(packet, now=1000) == 204
    assert (
        s["provider"].cancel(hint(s, call_id=packet["call"], cancel=True), now=1000)
        == 204
    )
    assert len(s["sent"]) == 1
    assert (
        s["provider"].lookup(s["owner"], packet["call"], s["authorization"], now=1000)[
            1
        ]["state"]
        == "cancelled"
    )
    wrong = build_hint(
        RNS.Identity(),
        packet["recipient"],
        "private-calls",
        call_id=packet["call"],
        issued=1000,
        cancel=True,
    )
    assert s["provider"].cancel(wrong, now=1000) == 403


def test_revocation_and_operator_opt_out_stop_future_alerts(setup):
    s = setup
    s["registration"]["token"] = None
    assert s["provider"].register(s["registration"], s["authorization"]) == 204
    assert s["provider"].notify(hint(s), now=1000) == 403
    s["registration"]["token"] = "cd" * 32
    s["subscriptions"][s["owner"]]["allow_calls"] = False
    assert s["provider"].register(s["registration"], s["authorization"]) == 403
    s["subscriptions"][s["owner"]]["allow_calls"] = True
    assert s["provider"].register(s["registration"], s["authorization"]) == 204
    s["subscriptions"][s["owner"]]["allow_calls"] = False
    assert s["provider"].notify(hint(s), now=1000) == 403
    assert s["provider"].prune(now=1000) == 1 and not s["sent"]


def test_send_failure_can_retry_without_a_false_acceptance(setup):
    s = setup
    packet = hint(s)
    original = s["provider"].send

    def fail(*args):
        raise Unavailable("private fixture")

    s["provider"].send = fail
    assert s["provider"].notify(packet, now=1000) == 503
    assert (
        s["provider"].database.execute("SELECT COUNT(*) FROM call_wakes").fetchone()[0]
        == 0
    )
    s["provider"].send = original
    assert s["provider"].notify(packet, now=1000) == 204 and len(s["sent"]) == 1


def test_rate_limit_preserves_cancel_and_duplicate_semantics(setup):
    s = setup
    packets = [hint(s) for _ in range(5)]
    for packet in packets[:4]:
        assert s["provider"].notify(packet, now=1000) == 204
    assert s["provider"].notify(packets[4], now=1000) == 429
    assert s["provider"].notify(packets[0], now=1000) == 204
    assert (
        s["provider"].cancel(hint(s, call_id=packets[0]["call"], cancel=True), now=1000)
        == 204
    )
    assert len(s["sent"]) == 4


def test_lookup_is_private_and_metadata_expires_without_permanent_call_history(setup):
    s = setup
    packet = hint(s)
    assert s["provider"].notify(packet, now=1000) == 204
    assert s["provider"].lookup(
        s["owner"], packet["call"], "Bearer " + "ff" * 32, now=1000
    ) == (403, None)
    assert (
        s["provider"].lookup(s["owner"], packet["call"], s["authorization"], now=1031)[
            1
        ]["state"]
        == "expired"
    )
    assert s["provider"].prune(now=1121) == 1
    assert s["provider"].lookup(
        s["owner"], packet["call"], s["authorization"], now=1121
    ) == (404, None)
    assert s["provider"].notify(packet, now=1121) == 403


def test_registered_key_must_belong_to_the_enrollment_owner(setup):
    s = setup
    registration = dict(
        s["registration"], recipient_key=RNS.Identity().get_public_key().hex()
    )
    assert s["provider"].register(registration, s["authorization"]) == 403
    assert s["provider"].register(s["registration"], "Bearer " + "ff" * 32) == 403
    assert s["provider"].notify(hint(s), now=1000) == 204


def test_voip_transport_has_immediate_expiry_and_keeps_token_out_of_arguments(
    tmp_path, monkeypatch, setup
):
    import subprocess
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from call_service import VoIPAPNs

    keyfile = tmp_path / "test-only.p8"
    keyfile.write_bytes(
        ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    calls = []

    def execute(args, **options):
        calls.append((args, options))
        return subprocess.CompletedProcess(args, 0, stdout="200")

    monkeypatch.setattr(subprocess, "run", execute)
    send = VoIPAPNs(
        dict(
            topic="org.example.private",
            team="AAAAAAAAAA",
            key_id="BBBBBBBBBB",
            key_file=str(keyfile),
            environment="development",
            id_key="ef" * 32,
        )
    )
    s = setup
    assert s["provider"].notify(hint(s), now=1000) == 204
    token, payload = s["sent"][0]
    send(token, payload)
    args, options = calls[0]
    assert token not in " ".join(args) and "--http2" in args
    config = options["input"]
    assert "apns-topic: org.example.private.voip" in config
    assert "apns-push-type: voip" in config and "apns-expiration: 0" in config
    assert "apns-collapse-id" not in config and hint(s)["sender"] not in config
    assert json.loads(json.loads(config.split("data = ")[1])) == payload
    configured_urls = [
        json.loads(line.removeprefix("url = "))
        for line in config.splitlines()
        if line.startswith("url = ")
    ]
    assert configured_urls == [f"https://api.sandbox.push.apple.com/3/device/{token}"]


def test_private_http_enrollment_call_lookup_and_cancel_without_another_push(setup):
    import queue
    import threading
    import time
    import urllib.error
    import urllib.request
    from call_service import CallHandler
    from provider import ProviderHTTPServer

    s = setup
    with ProviderHTTPServer(("127.0.0.1", 0), CallHandler) as server:
        server.provider = s["provider"]
        server.timeout = 3

        def exchange(path, data, authorization="", raw=None):
            results = queue.Queue()

            def client():
                request = urllib.request.Request(
                    "http://127.0.0.1:" + str(server.server_port) + path,
                    data=json.dumps(data).encode() if raw is None else raw,
                    headers={
                        "Authorization": authorization,
                        "Content-Type": "application/json",
                    },
                )
                try:
                    response = urllib.request.urlopen(request, timeout=3)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    results.put((response.status, response.headers, response.read()))

            thread = threading.Thread(target=client)
            thread.start()
            server.handle_request()
            thread.join(timeout=4)
            assert not thread.is_alive()
            return results.get(timeout=1)

        assert exchange("/v1/call-subscription", s["registration"])[0] == 403
        assert (
            exchange("/v1/call-subscription", s["registration"], s["authorization"])[0]
            == 204
        )
        packet = build_hint(
            s["caller"], voice_hash(s["recipient"].get_public_key()), "private-calls"
        )
        assert exchange("/v1/call-alert", packet)[0] == 204
        lookup = dict(owner=s["owner"], call=packet["call"])
        assert exchange("/v1/call-state", lookup)[0] == 403
        status, headers, raw = exchange("/v1/call-state", lookup, s["authorization"])
        assert status == 200 and headers["Cache-Control"] == "no-store"
        assert json.loads(raw) == dict(state="ringing", hint=packet)
        cancellation = build_hint(
            s["caller"],
            packet["recipient"],
            "private-calls",
            call_id=packet["call"],
            issued=int(time.time()),
            cancel=True,
        )
        assert exchange("/v1/call-cancel", cancellation)[0] == 204
        assert len(s["sent"]) == 1
        assert (
            json.loads(exchange("/v1/call-state", lookup, s["authorization"])[2])[
                "state"
            ]
            == "cancelled"
        )
        assert exchange("/v1/call-state", {}, raw=b"{")[0] == 400
        assert exchange("/v1/call-alert", {}, raw=b"x" * 2049)[0] == 400
        assert exchange("/v1/mailbox-alert", {})[0] == 404
        disabled = dict(s["registration"], token=None)
        assert exchange("/v1/call-subscription", disabled, s["authorization"])[0] == 204
        assert exchange("/v1/call-state", lookup, s["authorization"])[0] == 404


def test_call_service_requires_private_files_and_explicit_call_opt_in(tmp_path):
    from call_service import load_config

    tmp_path.chmod(0o700)
    key = tmp_path / "key.p8"
    key.write_text("private fixture; no signing operation")
    key.chmod(0o600)
    config = dict(
        audience="private-calls",
        database=str(tmp_path / "calls.sqlite"),
        subscriptions={"ab" * 16: dict(enrollment_hash="cd" * 32, allow_calls=True)},
        apns=dict(
            topic="org.example.private",
            team="AAAAAAAAAA",
            key_id="BBBBBBBBBB",
            key_file=str(key),
        ),
    )
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    assert load_config(path) == config
    path.chmod(0o644)
    with pytest.raises(ValueError, match="configuration must be private"):
        load_config(path)
    path.chmod(0o600)
    config["subscriptions"]["ab" * 16]["allow_calls"] = False
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="explicit authorization"):
        load_config(path)
    config["subscriptions"]["ab" * 16]["allow_calls"] = True
    config["apns"]["topic"] = "org.example.private\nInjected: header"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="Apple application identity"):
        load_config(path)


def test_operator_revocation_blocks_lookup_before_idle_cleanup(setup):
    s = setup
    packet = hint(s)
    assert s["provider"].notify(packet, now=1000) == 204
    s["subscriptions"][s["owner"]]["allow_calls"] = False
    assert s["provider"].lookup(
        s["owner"], packet["call"], s["authorization"], now=1000
    ) == (403, None)
    assert s["provider"].notify(packet, now=1000) == 403
    # Token removal remains possible after the operator withdraws its grant.
    assert (
        s["provider"].register(dict(s["registration"], token=None), s["authorization"])
        == 204
    )


def test_native_fixture_is_reproducible_from_public_test_keys():
    from call_provider import seal

    fixture = json.loads(
        (ROOT / "ios/NextRuntimeProbe/Tests/call-wake-fixture.json").read_text()
    )
    recipient = RNS.Identity.from_bytes(bytes(range(64)))
    caller = RNS.Identity.from_bytes(bytes(range(64, 128)))
    assert fixture["recipientPublicKey"] == recipient.get_public_key().hex()
    assert fixture["recipientMessaging"] == destination_hash("lxmf.delivery", recipient.get_public_key())
    assert fixture["recipient"] == voice_hash(recipient.get_public_key())
    assert fixture["caller"] == voice_hash(caller.get_public_key())
    for name, issued, cancel, forged in [
        ("valid", 1000, False, False),
        ("expired", 969, False, False),
        ("future", 1011, False, False),
        ("forged", 1000, False, True),
        ("cancel", 1000, True, False),
    ]:
        packet = build_hint(
            caller,
            fixture["recipient"],
            "private-calls",
            call_id="03" * 16,
            issued=issued,
            cancel=cancel,
        )
        if forged:
            packet["signature"] = "00" * 64
        assert fixture["vectors"][name] == seal(
            packet,
            recipient.get_public_key().hex(),
            ephemeral=x25519.X25519PrivateKey.from_private_bytes(bytes([1]) * 32),
            nonce=bytes([2]) * 12,
        )
