"""Local deletion cannot revoke contacts or be undone by a late receipt."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ios/NextRuntimeProbe"), str(ROOT / "app/src/main/python")]
from loopback_probe import ConversationHistory  # noqa: E402

PEER = "ab" * 16


def row(number, state="received"):
    return {
        "hash": f"{number:064x}",
        "content": "Private saved message",
        "state": state,
        "source_hash": PEER,
        "destination_hash": "cd" * 16,
        "is_outbound": state != "received",
        "created_at": "2026-11-21T12:00:00+00:00",
    }


def test_late_delivery_cannot_recreate_a_deleted_message_after_restart(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    try:
        saved = history.save(PEER, row(1, "delivered"))
        history.delete(saved["hash"])
        assert history.save(PEER, row(1, "delivered")) is None
        assert history.message(saved["hash"]) is None
    finally:
        history.close()
    restored = ConversationHistory(path)
    try:
        assert restored.save(PEER, row(1, "delivered")) is None
        assert restored.page(PEER, {}) == []
        assert restored.notification_candidates() == []
        incoming = restored.save(PEER, row(2))
        assert incoming["id"] > saved["id"]
        assert restored.summary(PEER)["unread_count"] == 1
    finally:
        restored.close()


def test_bulk_delete_cancels_pending_packets_without_revoking_contacts_or_restoring_receipts(
    tmp_path,
):
    from conversation_organization import ConversationOrganization

    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    other = "ef" * 16
    cancelled = []

    def cancel(packet):
        cancelled.append(packet)
        assert history.save(PEER, row(2, "delivered")) is None

    organization = ConversationOrganization(history, cancel_outbound=cancel)
    try:
        history.ensure_contact(PEER, "Approved peer")
        history.ensure_contact(other, "Keep")
        contacts = history.contacts()
        first = history.save(PEER, row(1))
        history.save(PEER, row(2, "sending"))
        kept = history.save(other, row(3))
        folder = organization.create("Friends")
        organization.move([PEER, other], folder)
        organization.toggle(PEER)
        organization.toggle(other)
        organization.delete_conversations([PEER, PEER])
        assert cancelled == [bytes.fromhex(row(2)["hash"])]
        assert history.contacts() == contacts
        assert (
            PEER not in history.conversation_entries()
            and other in history.conversation_entries()
        )
        assert (
            history.page(PEER, {}) == [] and history.message(kept["hash"]) is not None
        )
        assert [item["peer"] for item in history.notification_candidates()] == [other]
        assert organization.pins() == [other]
        assert [item["peer_hash"] for item in organization.export()["mappings"]] == [
            other
        ]
        assert history.save(PEER, first) is None
        organization.delete_conversations([PEER])  # Safe to retry a completed deletion.
        assert len(cancelled) == 1
    finally:
        history.close()
    restored = ConversationHistory(path)
    try:
        assert (
            restored.contacts() == contacts
            and PEER not in restored.conversation_entries()
        )
        assert restored.save(PEER, row(1)) is None
        fresh = restored.save(PEER, row(4))
        assert fresh["id"] > kept["id"] and PEER in restored.conversation_entries()
        assert len(restored.page(PEER, {})) == 1
    finally:
        restored.close()


def test_failed_bulk_cleanup_rolls_back_messages_markers_and_metadata(tmp_path):
    import sqlite3
    import pytest
    from conversation_organization import ConversationOrganization

    history = ConversationHistory(tmp_path / "history.sqlite3")
    cancelled = []
    organization = ConversationOrganization(history, cancel_outbound=cancelled.append)
    try:
        history.ensure_contact(PEER, "Keep")
        original = history.save(PEER, row(1))
        folder = organization.create("Keep folder")
        organization.move([PEER], folder)
        organization.toggle(PEER)
        before = organization.export()
        history.db.execute(
            "CREATE TRIGGER synthetic_delete_failure BEFORE DELETE ON lxmf_conversation_folders BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError):
            organization.delete_conversations([PEER])
        assert history.message(original["hash"]) is not None
        assert PEER in history.conversation_entries()
        assert history.notification_candidates()[0]["hash"] == original["hash"]
        assert organization.export() == before and organization.pins() == [PEER]
        assert history.save(PEER, original) is not None
        assert cancelled == []
    finally:
        history.close()


def test_invalid_bulk_selection_preserves_every_selected_conversation(tmp_path):
    import pytest

    history = ConversationHistory(tmp_path / "history.sqlite3")
    try:
        history.ensure_contact(PEER, "Keep")
        original = history.save(PEER, row(1))
        for selection in (
            [],
            True,
            [None],
            [PEER, "bad"],
            [PEER, "cd" * 16],
            [PEER] * 1001,
        ):
            with pytest.raises(ValueError):
                history.delete_conversations(selection)
            assert history.message(original["hash"]) is not None
            assert PEER in history.conversation_entries()
    finally:
        history.close()


def test_transport_cancel_failure_does_not_undo_local_deletion(tmp_path):
    from conversation_organization import ConversationOrganization

    history = ConversationHistory(tmp_path / "history.sqlite3")

    def cancel(_):
        raise RuntimeError("Synthetic unavailable queue")

    try:
        history.ensure_contact(PEER, "Keep")
        saved = history.save(PEER, row(1, "sending"))
        organization = ConversationOrganization(history, cancel_outbound=cancel)
        organization.delete_conversations([PEER])
        assert (
            history.message(saved["hash"]) is None
            and history.contacts()[PEER]["name"] == "Keep"
        )
        assert history.save(PEER, row(1, "failed")) is None
    finally:
        history.close()


def test_private_delete_api_preserves_identity_contacts_and_new_signed_messages(
    tmp_path,
):
    import json
    import socket
    from contextlib import ExitStack
    from test_next_ios_tcp_integration import (
        api,
        backend,
        run_hub,
        run_server,
        start,
        wait,
    )

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    app = tmp_path / "app"
    app.mkdir()
    ready = app / "backend.url"
    with ExitStack() as stack:
        _, hub = start(stack, run_hub, tmp_path / "hub", [port])
        assert hub.poll(20)
        address = hub.recv()
        settings = app / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "address": address,
                    "peers": [
                        {
                            "id": "private",
                            "host": "127.0.0.1",
                            "port": port,
                            "enabled": True,
                        }
                    ],
                }
            )
        )
        start(stack, run_server, app, ready, settings)
        wait(ready.exists)
        base = backend(ready)
        token = api(base, "auth/csrf")[1]["csrf_token"]
        identity = (app / "reticulum/identity").read_bytes()
        own = api(base, "config")[1]["config"]["lxmf_address_hash"]
        text = "Private signed history deletion test"
        assert (
            api(
                base,
                "lxmf-messages/send",
                body={"lxmf_message": {"destination_hash": address, "content": text}},
                token=token,
            )[0]
            == 200
        )

        def history():
            return api(base, "lxmf-messages/conversation/" + address)[1][
                "lxmf_messages"
            ]

        wait(
            lambda: any(item["content"] == "Echo: " + text for item in history()),
            timeout=45,
        )
        before = history()
        maximum = max(item["id"] for item in before)
        contacts = api(base, "telephone/contacts")[1]
        assert (
            api(
                base,
                "lxmf/conversation-pins/toggle",
                body={"destination_hash": address},
                token=token,
            )[0]
            == 200
        )
        assert (
            api(
                base,
                "lxmf/conversations/bulk-delete",
                body={"destination_hashes": [address]},
            )[0]
            == 403
        )
        assert (
            api(
                base,
                "lxmf/conversations/bulk-delete",
                body={"destination_hashes": [address]},
                token=token,
            )[0]
            == 200
        )
        assert (
            history() == []
            and api(base, "lxmf/conversations")[1]["conversations"] == []
        )
        assert api(base, "preview/unread-messages")[1]["messages"] == []
        assert api(base, "telephone/contacts")[1] == contacts
        assert api(base, "lxmf/conversation-pins")[1] == {"peer_hashes": []}
        hub.send(
            {"send_to": own, "content": "Fresh signed message after local deletion"}
        )
        wait(
            lambda: any(
                item["content"] == "Fresh signed message after local deletion"
                for item in history()
            ),
            timeout=45,
        )
        after = history()
        assert len(after) == 1 and after[0]["id"] > maximum
        assert all(after[0]["hash"] != old["hash"] for old in before)
        assert (app / "reticulum/identity").read_bytes() == identity
        assert api(base, "telephone/contacts")[1] == contacts
        assert len(api(base, "lxmf/conversations")[1]["conversations"]) == 1
