"""Call enrollment may disclose only bound public identity and allowed callers."""
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
import RNS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"))
from push_receiving import call_snapshot


def source(identity):
    return SimpleNamespace(identity=identity, hash=RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity))


def history(*identities):
    return SimpleNamespace(contacts=lambda: {
        RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity).hex(): {
            "name": f"Saved {index}",
            "lxmf_address": RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity).hex(),
        } for index, identity in enumerate(identities)
    })


def test_call_snapshot_binds_both_destinations_without_disclosing_private_keys(monkeypatch):
    own, allowed, denied = RNS.Identity(), RNS.Identity(), RNS.Identity()
    keys = {RNS.Destination.hash_from_name_and_identity("lxmf.delivery", i): i for i in (allowed, denied)}
    monkeypatch.setattr(RNS.Identity, "recall", keys.get)
    voice = SimpleNamespace(available=True, closed=False, config=SimpleNamespace(telephone_enabled=SimpleNamespace(get=lambda: True)),
        call_policy={"do_not_disturb_enabled": False}, caller_allowed=lambda key: key == allowed.hash)
    result = call_snapshot(history(allowed, denied), source(own), voice)
    assert len(result["policyDigest"]) == 64
    assert {row["addresses"]["lxmf"] for row in result["savedContacts"]} == {source(allowed).hash.hex(), source(denied).hash.hex()}
    assert {key: value for key, value in result.items() if key not in {"savedContacts", "policyDigest"}} == {
        "address": source(own).hash.hex(),
        "voiceAddress": RNS.Destination.hash_from_name_and_identity("lxst.telephony", own).hex(),
        "identityPublicKey": own.get_public_key().hex(),
        "enabled": True,
        "contacts": [{"name": "Saved 0", "identityPublicKey": allowed.get_public_key().hex(), "addresses": {
            "lxmf": source(allowed).hash.hex(), "voice": RNS.Destination.hash_from_name_and_identity("lxst.telephony", allowed).hex()}}],
    }
    assert own.get_private_key().hex() not in repr(result)
    assert denied.get_public_key().hex() not in repr(result)


@pytest.mark.parametrize("condition", ["missing", "disabled", "closed", "unavailable", "dnd"])
def test_unavailable_or_stopped_calling_does_not_authorize_any_push_callers(monkeypatch, condition):
    own, peer = RNS.Identity(), RNS.Identity()
    monkeypatch.setattr(RNS.Identity, "recall", lambda _: peer)
    voice = SimpleNamespace(available=condition != "unavailable", closed=condition == "closed",
        config=SimpleNamespace(telephone_enabled=SimpleNamespace(get=lambda: condition != "disabled")),
        call_policy={"do_not_disturb_enabled": condition == "dnd"}, caller_allowed=lambda _: True)
    result = call_snapshot(history(peer), source(own), None if condition == "missing" else voice)
    assert result["enabled"] is False and result["contacts"] == []


def test_recalled_key_under_another_destination_is_not_eligible(monkeypatch):
    own, peer, wrong = RNS.Identity(), RNS.Identity(), RNS.Identity()
    monkeypatch.setattr(RNS.Identity, "recall", lambda _: wrong)
    voice = SimpleNamespace(available=True, closed=False,
        config=SimpleNamespace(telephone_enabled=SimpleNamespace(get=lambda: True)),
        call_policy={"do_not_disturb_enabled": False}, caller_allowed=lambda _: True)
    assert call_snapshot(history(peer), source(own), voice)["contacts"] == []
    mismatched = source(own); mismatched.hash = source(wrong).hash
    with pytest.raises(ValueError): call_snapshot(history(), mismatched, voice)


def test_actual_call_enrollment_endpoint_requires_private_session(tmp_path):
    import json
    from contextlib import ExitStack
    from urllib.error import HTTPError
    from urllib.parse import urlsplit
    from urllib.request import urlopen
    from test_next_ios_tcp_integration import api, backend, run_server, start, wait
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"peers": [{"id": "off", "host": "127.0.0.1", "port": 9, "enabled": False}]}))
    ready = tmp_path / "backend.url"
    with ExitStack() as stack:
        start(stack, run_server, tmp_path, ready, settings); wait(ready.exists)
        base = backend(ready)
        with pytest.raises(HTTPError) as denied:
            urlopen("http://" + urlsplit(base).netloc + "/api/v1/preview/call-enrollment-state", timeout=5)
        assert denied.value.code == 403
        status, result = api(base, "preview/call-enrollment-state")
        assert status == 200 and result["enabled"] is False and result["contacts"] == []
        public = RNS.Identity(create_keys=False); public.load_public_key(bytes.fromhex(result["identityPublicKey"]))
        assert result["address"] == source(public).hash.hex()
        assert result["voiceAddress"] == RNS.Destination.hash_from_name_and_identity("lxst.telephony", public).hex()
        assert set(result) == {"address", "voiceAddress", "identityPublicKey", "enabled", "contacts", "savedContacts", "policyDigest"}


def enabled_voice():
    voice = SimpleNamespace(available=True, closed=False, blocked_callers=[],
        config=SimpleNamespace(telephone_enabled=SimpleNamespace(get=lambda: True)),
        call_policy={"do_not_disturb_enabled": False, "telephone_allow_calls_from_contacts_only": True})
    voice.caller_allowed = lambda key: key.hex() not in voice.blocked_callers
    return voice


def test_cold_recall_loss_can_use_only_bound_previously_selected_public_keys(monkeypatch):
    own, peer, stranger = RNS.Identity(), RNS.Identity(), RNS.Identity()
    voice = enabled_voice()
    monkeypatch.setattr(RNS.Identity, "recall", lambda _: peer)
    original = call_snapshot(history(peer), source(own), voice)
    assert len(original["contacts"]) == 1
    monkeypatch.setattr(RNS.Identity, "recall", lambda _: None)
    def forbidden(*args, **kwargs):
        raise AssertionError("Enrollment metadata must not install routing identities")
    monkeypatch.setattr(RNS.Identity, "remember", forbidden)
    cold = call_snapshot(history(peer), source(own), voice)
    assert cold["contacts"] == [] and cold["policyDigest"] == original["policyDigest"]
    restored = call_snapshot(history(peer), source(own), voice, public_keys=[peer.get_public_key().hex()])
    assert restored == original
    wrong = call_snapshot(history(peer), source(own), voice, public_keys=[stranger.get_public_key().hex()])
    assert wrong["contacts"] == [] and wrong["savedContacts"] == original["savedContacts"]
    voice.blocked_callers = [peer.hash.hex()]
    blocked = call_snapshot(history(peer), source(own), voice, public_keys=[peer.get_public_key().hex()])
    assert blocked["contacts"] == [] and blocked["policyDigest"] != original["policyDigest"]


@pytest.mark.parametrize("keys", [False, {}, (), "not a list", ["ab"], ["GG" * 64], ["ab" * 64] * 257, ["ab" * 64] * 2])
def test_previously_selected_key_hints_are_bounded_public_inputs_only(keys):
    with pytest.raises(ValueError):
        call_snapshot(history(), source(RNS.Identity()), enabled_voice(), public_keys=keys)


def test_policy_digest_tracks_permission_changes_not_codec_or_volatile_cache(monkeypatch):
    own, peer = RNS.Identity(), RNS.Identity()
    monkeypatch.setattr(RNS.Identity, "recall", lambda _: None)
    voice = enabled_voice()
    initial = call_snapshot(history(peer), source(own), voice)
    voice.config.profile = 64
    assert call_snapshot(history(peer), source(own), voice)["policyDigest"] == initial["policyDigest"]
    voice.call_policy["do_not_disturb_enabled"] = True
    stopped = call_snapshot(history(peer), source(own), voice)
    assert not stopped["enabled"] and stopped["savedContacts"] == initial["savedContacts"]
    assert stopped["policyDigest"] != initial["policyDigest"]
    voice.call_policy["do_not_disturb_enabled"] = False
    assert call_snapshot(history(), source(own), voice)["policyDigest"] != initial["policyDigest"]
    a = call_snapshot(history(peer), source(own), voice, block_snapshot=[{"destination_hash": "ab" * 16, "created_at": 1}])
    b = call_snapshot(history(peer), source(own), voice, block_snapshot=[{"destination_hash": "ab" * 16, "created_at": 2}])
    assert a["policyDigest"] == b["policyDigest"] != initial["policyDigest"]


def test_native_cold_refresh_is_authenticated_csrf_protected_bounded_and_read_only(tmp_path):
    import json
    from contextlib import ExitStack
    from urllib.error import HTTPError
    from urllib.parse import urlsplit
    from urllib.request import Request, urlopen
    from test_next_ios_tcp_integration import SESSIONS, api, backend, run_server, start, wait
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"peers": [{"id": "off", "host": "127.0.0.1", "port": 9, "enabled": False}]}))
    ready = tmp_path / "backend.url"
    with ExitStack() as stack:
        start(stack, run_server, tmp_path, ready, settings); wait(ready.exists)
        base = backend(ready)
        path = "preview/call-enrollment-state"
        token = api(base, "auth/csrf")[1]["csrf_token"]
        assert api(base, path, body={"publicKeys": []})[0] == 403
        status, before = api(base, path)
        assert status == 200
        for invalid in ({}, {"publicKeys": None}, {"publicKeys": "bad"}, {"publicKeys": [], "private": "must not be accepted"}, {"publicKeys": ["bad"]}):
            assert api(base, path, body=invalid, token=token)[0] == 400
        public = RNS.Identity().get_public_key().hex()
        assert api(base, path, body={"publicKeys": [public]}, token=token) == (200, before)
        assert api(base, "telephone/contacts")[1]["contacts"] == []
        headers = {"X-neXt-Session": SESSIONS[urlsplit(base).netloc], "X-CSRF-Token": token, "Content-Type": "application/json"}
        endpoint = "http://" + urlsplit(base).netloc + "/api/v1/" + path
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(endpoint, data=json.dumps({"publicKeys": []}).encode(), method="POST"), timeout=5)
        assert denied.value.code == 403
        with pytest.raises(HTTPError) as bounded:
            urlopen(Request(endpoint, data=b"x" * 65537, headers=headers, method="POST"), timeout=5)
        assert bounded.value.code == 413
        assert api(base, path)[1] == before
