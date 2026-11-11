import asyncio
import importlib.util
import json
from pathlib import Path
import signal
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest


PYTHON = Path(__file__).resolve().parents[1] / "app/src/main/python"
LXMF_ADDRESS = "ab" * 16
MESHCORE_KEY = "cd" * 32
COMPANION_KEY = "ef" * 32


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.syspath_prepend(str(PYTHON))
    spec = importlib.util.spec_from_file_location("fallback_backend", PYTHON / "family_backend.py")
    module = importlib.util.module_from_spec(spec)
    with patch.object(signal, "signal", signal.signal):
        spec.loader.exec_module(module)
    module._state = {
        "setup_complete": True,
        "contacts": [{"id": 1, "name": "Test contact", "addresses": {
            "lxmf": LXMF_ADDRESS, "meshcore": MESHCORE_KEY,
        }}],
        "messages": [],
        "meshcore": {"enabled": True, "publicKey": COMPANION_KEY},
    }
    module._peer = SimpleNamespace(online=True)
    module._meshcore = SimpleNamespace(connected=True)
    module._save = Mock()
    module._snapshot = lambda: {}
    module._dispatch_message = Mock()
    return module


def submit(backend, method="auto", text="Test"):
    result = json.loads(backend.request(json.dumps({"action": "send", "payload": {
        "contactId": 1, "method": method, "text": text,
    }})))
    assert result["ok"], result
    return backend._dispatch_message.call_args.args


@pytest.mark.parametrize("initial", ["reticulum", "meshcore"])
def test_automatic_switches_once_and_keeps_one_conversation_row(backend, initial):
    alternate = "meshcore" if initial == "reticulum" else "reticulum"
    if initial == "meshcore":
        backend._peer.online = False
    mid, service, _, text, on_failure = submit(backend)
    assert service == initial
    backend._peer.online = True

    assert on_failure("Failed · test")
    row, = backend._state["messages"]
    assert row["id"] == mid
    assert row["service"] == alternate
    assert row["fallbackFrom"]["service"] == initial
    assert backend._dispatch_message.call_args.args == (mid, alternate, row["peer"], text)
    assert not on_failure("Failed again")
    assert backend._dispatch_message.call_count == 2
    assert backend._message_routes(backend._state["contacts"][0])[0]["service"] == alternate


@pytest.mark.parametrize(("method", "text"), [("reticulum", "Test"), ("meshcore", "Test"), ("auto", "é" * 81)])
def test_manual_routes_and_oversized_meshcore_text_do_not_fallback(backend, method, text):
    assert submit(backend, method, text)[-1] is None


@pytest.mark.parametrize("change", ["remove", "replace", "disconnect"])
def test_fallback_rechecks_approval_and_availability(backend, change):
    on_failure = submit(backend)[-1]
    if change == "remove":
        backend._state["contacts"].clear()
    elif change == "replace":
        backend._state["contacts"][0]["addresses"]["meshcore"] = "12" * 32
    else:
        backend._meshcore.connected = False

    assert not on_failure("Failed · test")
    assert backend._dispatch_message.call_count == 1


def test_reticulum_no_path_switches_to_meshcore(backend, monkeypatch):
    monkeypatch.setitem(sys.modules, "RNS", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "LXMF", SimpleNamespace())
    backend._await_identity = Mock(return_value=None)
    mid, _, peer, text, on_failure = submit(backend)

    backend._send(mid, peer, text, on_failure)

    assert backend._state["messages"][0]["service"] == "meshcore"
    assert backend._dispatch_message.call_count == 2


@pytest.mark.parametrize("started", [False, True])
def test_reticulum_router_switches_after_exhausting_attempts(backend, monkeypatch, started):
    class Message:
        FAILED, REJECTED, CANCELLED = range(3)
        hash = None

        def __init__(self, *args, **kwargs):
            self.state = None

        def register_delivery_callback(self, callback):
            pass

        def register_failed_callback(self, callback):
            self.failed = callback

        def send(self):
            pass

    def handle_outbound(message):
        if started:
            message.send()
        message.state = Message.FAILED
        message.failed(message)

    destination = Mock(OUT=1, SINGLE=2)
    monkeypatch.setitem(sys.modules, "RNS", SimpleNamespace(Destination=destination))
    monkeypatch.setitem(sys.modules, "LXMF", SimpleNamespace(LXMessage=Message))
    backend._await_identity = Mock(return_value=object())
    backend._delivery_method = Mock()
    backend._router = SimpleNamespace(handle_outbound=handle_outbound)
    mid, _, peer, text, on_failure = submit(backend)

    backend._send(mid, peer, text, on_failure)

    row, = backend._state["messages"]
    assert row["service"] == "meshcore"
    assert backend._dispatch_message.call_count == 2
    assert row["fallbackFrom"]["status"].startswith("Not confirmed" if started else "Failed")


@pytest.mark.parametrize(("payload", "confirmed_failure"), [
    ({"error_code": 3}, True),
    ({}, True),
    ({"reason": "no_event_received"}, False),
    ({"error": "Bluetooth disconnected during write"}, False),
])
def test_meshcore_firmware_rejection_is_distinct_from_uncertain_delivery(backend, monkeypatch, payload, confirmed_failure):
    import family_meshcore

    backend._peer.online = False
    mid, _, peer, text, on_failure = submit(backend)
    backend._peer.online = True
    event_type = SimpleNamespace(ERROR=1, MSG_SENT=2)
    monkeypatch.setitem(sys.modules, "meshcore", SimpleNamespace(EventType=event_type))
    radio = family_meshcore.FamilyMeshCore.__new__(family_meshcore.FamilyMeshCore)
    radio.state, radio.lock, radio.save = backend._state, backend._lock, backend._save
    radio.contacts, radio.connected = {peer: {}}, True
    commands = SimpleNamespace(send_msg=AsyncMock(return_value=SimpleNamespace(type=event_type.ERROR, payload=payload)))
    radio.session = SimpleNamespace(_lock=asyncio.Lock(), _client=SimpleNamespace(commands=commands))

    asyncio.run(radio._send(mid, peer, text, on_failure))

    row, = backend._state["messages"]
    assert row["service"] == "reticulum"
    assert backend._dispatch_message.call_count == 2
    assert row["fallbackFrom"]["status"].startswith("Failed" if confirmed_failure else "Not confirmed")


@pytest.mark.parametrize("receipt_arrives", [True, False])
def test_accepted_meshcore_message_waits_for_receipt_then_falls_back(backend, monkeypatch, receipt_arrives):
    import family_meshcore

    backend._peer.online = False
    mid, _, peer, text, on_failure = submit(backend)
    backend._peer.online = True
    event_type = SimpleNamespace(ERROR=1, MSG_SENT=2)
    monkeypatch.setitem(sys.modules, "meshcore", SimpleNamespace(EventType=event_type))
    radio = family_meshcore.FamilyMeshCore.__new__(family_meshcore.FamilyMeshCore)
    radio.state, radio.lock, radio.save = backend._state, backend._lock, backend._save
    radio.contacts, radio.connected = {peer: {}}, True
    radio._acks, radio._pending, radio.rooms = {}, {}, Mock()
    ack = b"abcd"
    commands = SimpleNamespace(send_msg=AsyncMock(return_value=SimpleNamespace(
        type=event_type.MSG_SENT, payload={"expected_ack": ack, "suggested_timeout": 30000},
    )))
    radio.session = SimpleNamespace(_lock=asyncio.Lock(), _client=SimpleNamespace(commands=commands))

    asyncio.run(radio._send(mid, peer, text, on_failure))

    row, = backend._state["messages"]
    assert row["status"].endswith("awaiting receipt")
    assert backend._dispatch_message.call_count == 1
    _, deadline, _ = radio._pending[ack.hex()]
    with patch.object(family_meshcore.time, "time", return_value=deadline - 1):
        radio._expire_receipts()
        assert backend._dispatch_message.call_count == 1
        if receipt_arrives:
            radio._ack(SimpleNamespace(payload={"code": ack}, attributes={}))
    with patch.object(family_meshcore.time, "time", return_value=deadline + 1):
        radio._expire_receipts()
        radio._expire_receipts()
    if receipt_arrives:
        assert row["status"].startswith("Delivered")
        assert backend._dispatch_message.call_count == 1
    else:
        assert row["service"] == "reticulum"
        assert row["fallbackFrom"]["status"] == "Not confirmed · MeshCore receipt timed out"
        assert backend._dispatch_message.call_count == 2


def test_attachment_only_uses_reticulum_and_is_private_to_approved_chat(backend, tmp_path):
    import base64

    backend._root = tmp_path
    data = b"example file bytes"
    payload = {"contactId": 1, "method": "auto", "text": "",
               "attachment": {"name": "../example.txt", "data": base64.b64encode(data).decode()}}
    result = json.loads(backend.request(json.dumps({"action": "send", "payload": payload})))
    assert result["ok"], result
    row, = backend._state["messages"]
    assert row["attachment"] == {"name": "example.txt", "size": len(data)}
    assert backend._dispatch_message.call_args.args == (row["id"], "reticulum", LXMF_ADDRESS, "", None)
    assert backend.read_attachment(1, row["id"]) == data
    with pytest.raises(ValueError, match="unavailable"):
        backend.read_attachment(2, row["id"])
    payload["method"] = "meshcore"
    result = json.loads(backend.request(json.dumps({"action": "send", "payload": payload})))
    assert not result["ok"] and "Reticulum" in result["error"]
    assert len(backend._state["messages"]) == 1


def test_verified_attachment_only_message_and_photo_appear_in_chat(backend, tmp_path):
    import LXMF

    backend._root = tmp_path
    photo = b"sample photo bytes"
    message = SimpleNamespace(source_hash=bytes.fromhex(LXMF_ADDRESS), signature_validated=True,
                              hash=b"example-photo", content_as_string=lambda: "",
                              fields={LXMF.FIELD_IMAGE: ["png", photo]})
    backend._receive(message)
    backend._receive(message)
    row, = backend._state["messages"]
    assert row["incoming"] and row["attachment"] == {"name": "photo.png", "size": len(photo)}
    assert backend.read_attachment(1, row["id"]) == photo
    message.source_hash = b"unapproved-peer!"
    message.hash = b"different-photo"
    backend._receive(message)
    assert len(backend._state["messages"]) == 1
