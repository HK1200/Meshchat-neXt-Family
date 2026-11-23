"""Private sender/provider tests. No radio, Apple credential or public HTTP."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import sqlite3
import sys
import threading
import uuid

import pytest
import RNS

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ios/NextRuntimeProbe"), str(ROOT / "app/src/main/python"), str(ROOT / "ios/push-provider")]
import call_alerts
from call_provider import CallProvider
from family_call_wake import destination_hash, voice_hash


@pytest.fixture
def profile(tmp_path):
    own, peer = RNS.Identity(), RNS.Identity()
    address = destination_hash("lxmf.delivery", peer.get_public_key())
    entry = dict(provider="https://example.invalid", audience="private-calls", public_key=peer.get_public_key().hex())
    contact = {address: {"id": 1, "name": "Private name"}}
    return SimpleNamespace(folder=tmp_path, own=own, peer=peer, address=address, entry=entry, contacts=contact)


def call(p, **changes):
    fields = dict(id=uuid.uuid4().hex, peer=voice_hash(p.peer.get_public_key()), requested_peer=p.address, incoming=False)
    return SimpleNamespace(**{**fields, **changes})


def finish(manager):
    handles = tuple(manager.pending.values())
    manager.close()
    for handle in handles:
        if handle.thread:
            handle.thread.join(timeout=6)
            assert not handle.thread.is_alive()


def test_route_changes_are_private_atomic_and_independent(profile):
    p = profile
    first = call_alerts.save_route(p.folder, p.address, p.entry)
    assert first.voice == voice_hash(p.peer.get_public_key())
    other = RNS.Identity(); address = destination_hash("lxmf.delivery", other.get_public_key())
    entry = {**p.entry, "public_key": other.get_public_key().hex()}
    call_alerts.save_route(p.folder, address, entry)
    path = p.folder / "call-alert-routes.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert p.own.get_private_key().hex() not in path.read_text()
    assert "Private name" not in path.read_text()
    call_alerts.save_route(p.folder, p.address, None)
    assert call_alerts.route_for(p.folder, p.address) is None
    assert call_alerts.route_for(p.folder, address) is not None


@pytest.mark.parametrize("field,value", [("provider", "http://example.invalid"), ("provider", "https://user:pass@example.invalid"),
    ("provider", "https://example.invalid/path"), ("provider", "https://example.invalid?secret=x"),
    ("provider", "https://example.invalid#fragment"), ("provider", "https://example.invalid:0"),
    ("audience", "bad/name"), ("audience", "private-calls\n"), ("public_key", "00" * 64)])
def test_route_validation_preserves_existing_settings(profile, field, value):
    p = profile
    call_alerts.save_route(p.folder, p.address, p.entry)
    original = (p.folder / "call-alert-routes.json").read_bytes()
    with pytest.raises(ValueError): call_alerts.save_route(p.folder, p.address, {**p.entry, field: value})
    assert (p.folder / "call-alert-routes.json").read_bytes() == original


def test_failed_atomic_replace_and_symlinks_never_overwrite_other_data(profile, monkeypatch):
    p = profile; call_alerts.save_route(p.folder, p.address, p.entry)
    path = p.folder / "call-alert-routes.json"; original = path.read_bytes()
    def fail(*_): raise OSError("private fixture")
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail)
        with pytest.raises(OSError): call_alerts.save_route(p.folder, p.address, None)
    assert path.read_bytes() == original
    assert not list(p.folder.glob(".call-alerts-*"))
    target = p.folder / "preserved.json"; path.rename(target); path.symlink_to(target)
    assert call_alerts.route_for(p.folder, p.address) is None
    with pytest.raises(OSError): call_alerts.save_route(p.folder, p.address, p.entry)
    assert target.read_bytes() == original


@pytest.mark.parametrize("condition", ["no_route", "incoming", "not_saved", "blocked", "wrong_peer"])
def test_unapproved_or_unconfigured_calls_never_send_hints(profile, condition):
    p = profile; requests = []
    if condition != "no_route": call_alerts.save_route(p.folder, p.address, p.entry)
    if condition == "not_saved": p.contacts.clear()
    manager = call_alerts.CallAlerts(p.folder, p.own, lambda: p.contacts,
        lambda _: condition == "blocked", sender=lambda *args: requests.append(args), wall_clock=lambda: 1000)
    outgoing = call(p, incoming=condition == "incoming")
    if condition == "wrong_peer": outgoing.peer = outgoing.requested_peer = "00" * 16
    try: manager.started(outgoing)
    finally: finish(manager)
    assert requests == []


@pytest.mark.parametrize("lost_ack", [False, True, "exception"])
def test_real_provider_accepts_one_signed_wake_and_ordered_cancellation(profile, lost_ack):
    p = profile; call_alerts.save_route(p.folder, p.address, p.entry)
    sent = []; operations = []; received = threading.Event(); worker_state = {}
    code = bytes([1]) * 32
    def post(route, operation, raw):
        if "provider" not in worker_state:
            provider = CallProvider("private-calls", {p.address: dict(enrollment_hash=hashlib.sha256(code).hexdigest(), allow_calls=True)},
                p.folder / "provider.sqlite3", lambda token, payload: sent.append(payload))
            assert provider.register(dict(recipient_key=p.peer.get_public_key().hex(), token="ab" * 32,
                callers=[voice_hash(p.own.get_public_key())]), "Bearer " + code.hex()) == 204
            worker_state["provider"] = provider
        provider = worker_state["provider"]
        packet = json.loads(raw); operations.append((operation, packet))
        assert set(packet) == {"recipient", "call", "sender", "issued", "signature"}
        if operation == "call-alert":
            result = provider.notify(packet, now=1000); received.set()
            if lost_ack == "exception": raise OSError("Response lost after acceptance")
            return 503 if lost_ack else result
        result = provider.cancel(packet, now=1000)
        worker_state["lookup"] = provider.lookup(p.address, packet["call"], "Bearer " + code.hex(), now=1000)
        provider.database.close()
        return result
    manager = call_alerts.CallAlerts(p.folder, p.own, lambda: p.contacts, lambda _: False, sender=post, wall_clock=lambda: 1000)
    outgoing = call(p)
    try:
        manager.started(outgoing)
        assert received.wait(5)
        manager.started(outgoing)  # Repeated lifecycle callback is not a second wake.
    finally: finish(manager)
    assert [kind for kind, _ in operations] == ["call-alert", "call-cancel"]
    assert len(sent) == 1
    assert worker_state["lookup"][0] == 200 and worker_state["lookup"][1]["state"] == "cancelled"
    from test_family_call_wake import unseal
    assert unseal(dict(recipient=p.peer), sent[0]) == operations[0][1]
    assert p.own.get_private_key().hex() not in json.dumps(operations)
    assert "Private name" not in json.dumps(operations)


def test_route_removal_while_post_is_in_flight_cancels_the_original_attempt(profile):
    p = profile; call_alerts.save_route(p.folder, p.address, p.entry)
    entered = threading.Event(); release = threading.Event(); operations = []
    def post(route, operation, raw):
        operations.append(operation)
        if operation == "call-alert":
            entered.set(); assert release.wait(5)
        return 204
    manager = call_alerts.CallAlerts(p.folder, p.own, lambda: p.contacts, lambda _: False, sender=post, wall_clock=lambda: 1000)
    outgoing = call(p)
    try:
        manager.started(outgoing); assert entered.wait(5)
        call_alerts.save_route(p.folder, p.address, None)
        release.set()
        manager.pending[outgoing.id].thread.join(timeout=5)
    finally:
        release.set(); finish(manager)
    assert operations == ["call-alert", "call-cancel"]


def test_transport_rejects_http_and_unknown_operations_without_network(profile):
    p = profile
    route = call_alerts.Route("http://127.0.0.1", "private-calls", p.peer.get_public_key().hex())
    assert call_alerts.post(route, "call-alert", b"{}") == 400
    assert call_alerts.post(route, "unrelated", b"{}") == 400


@pytest.mark.parametrize("removal", ["delete", "block"])
def test_private_contact_route_api_rechecks_binding_and_cleans_up_on_revocation(tmp_path, removal):
    from contextlib import ExitStack
    from urllib.error import HTTPError
    from urllib.parse import urlsplit
    from urllib.request import urlopen
    from test_next_ios_tcp_integration import api, backend, start, wait
    from test_next_ios_call_enrollment import run_native_policy_server
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"peers": [{"id": "off", "host": "127.0.0.1", "port": 9, "enabled": False}]}))
    ready = tmp_path / "backend.url"
    peer = RNS.Identity(); address = destination_hash("lxmf.delivery", peer.get_public_key())
    route = dict(provider="https://example.invalid", audience="private-calls", public_key=peer.get_public_key().hex())
    with ExitStack() as stack:
        start(stack, run_native_policy_server, tmp_path, ready, settings); wait(ready.exists)
        base = backend(ready); token = api(base, "auth/csrf")[1]["csrf_token"]
        assert api(base, "telephone/contacts", body={"name": "Approved call recipient", "lxmf_address": address}, token=token)[0] == 200
        contact = next(row for row in api(base, "telephone/contacts")[1]["contacts"] if row["lxmf_address"] == address)
        path = f"telephone/contacts/{contact['id']}/call-alert-route"
        assert api(base, path, body={"route": route}, token=token)[0] == 200
        assert api(base, path)[1]["route"] == route
        saved = (tmp_path / "call-alert-routes.json").read_bytes()
        with pytest.raises(HTTPError) as denied:
            urlopen("http://" + urlsplit(base).netloc + "/api/v1/" + path, timeout=5)
        assert denied.value.code == 403
        wrong = {**route, "public_key": RNS.Identity().get_public_key().hex()}
        assert api(base, path, body={"route": wrong}, token=token)[0] == 400
        assert (tmp_path / "call-alert-routes.json").read_bytes() == saved
        if removal == "delete":
            assert api(base, f"telephone/contacts/{contact['id']}", method="DELETE", token=token)[0] == 200
        else:
            assert api(base, "blocked-destinations", body={"destination_hash": address}, token=token)[0] == 200
        assert call_alerts.route_for(tmp_path, address) is None
        assert api(base, path)[0] == 404


def test_hint_workers_never_access_the_app_loops_sqlite_connection(profile):
    p = profile; call_alerts.save_route(p.folder, p.address, p.entry)
    database = sqlite3.connect(":memory:")
    database.execute("CREATE TABLE contacts (address TEXT, id INTEGER)")
    database.execute("INSERT INTO contacts VALUES (?, 1)", (p.address,))
    def contacts(): return {row[0]: {"id": row[1]} for row in database.execute("SELECT address, id FROM contacts")}
    received, cancelled = threading.Event(), threading.Event()
    operations = []
    def post(route, operation, raw):
        operations.append(operation)
        (received if operation == "call-alert" else cancelled).set()
        return 204
    manager = call_alerts.CallAlerts(p.folder, p.own, contacts, lambda _: False, sender=post, wall_clock=lambda: 1000)
    try:
        manager.started(call(p))
        assert received.wait(5), "A worker must not silently drop its hint by reading main-thread SQLite"
        database.execute("DELETE FROM contacts")
        manager.refresh_contacts()
        assert cancelled.wait(5), "Removing approval must cancel even before the voice call ends"
    finally:
        finish(manager); database.close()
    assert operations == ["call-alert", "call-cancel"]


def test_actual_packaging_command_includes_both_sender_modules_without_checkout_imports(tmp_path):
    import subprocess
    script = (ROOT / "ios/NextRuntimeProbe/test-simulators.sh").read_text().splitlines()
    command, = [line for line in script if line.startswith("cp ") and '"$probe/call_alerts.py"' in line]
    (tmp_path / "staged").mkdir()
    subprocess.run(["bash", "-c", 'set -eu\nfamily_ios="$1"\nprobe="$2"\n' + command,
        "stage-private-call-helpers", str(ROOT / "ios"), str(ROOT / "ios/NextRuntimeProbe")], cwd=tmp_path, check=True)
    code = '''
import pathlib, socket, sys
sys.path.insert(0, sys.argv[1])
class ForbiddenSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        raise AssertionError("Import and route editing cannot create a socket")
socket.socket = ForbiddenSocket
import call_alerts, family_call_wake
for module in (call_alerts, family_call_wake):
    assert pathlib.Path(module.__file__).resolve().parent == pathlib.Path(sys.argv[1]).resolve()
manager = call_alerts.CallAlerts(pathlib.Path(sys.argv[1]), None, lambda: {}, lambda _: False)
manager.close()
print("Packaged call-alert modules import without a checkout or network")
'''
    result = subprocess.run([sys.executable, "-I", "-c", code, str(tmp_path / "staged")], cwd=tmp_path,
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
