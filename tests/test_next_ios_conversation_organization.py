"""Existing neXt folder/pin UI contracts use durable data, never placeholders."""

import json
import sqlite3
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ios/NextRuntimeProbe"), str(ROOT / "app/src/main/python")]
from conversation_organization import ConversationOrganization  # noqa: E402
from loopback_probe import ConversationHistory  # noqa: E402

A, B, C = "aa" * 16, "bb" * 16, "cc" * 16


@pytest.fixture
def store(tmp_path):
    history = ConversationHistory(tmp_path / "messages.sqlite3")
    try:
        yield history, ConversationOrganization(history)
    finally:
        history.close()


def message(
    history, address, number, *, state="received", fields=None, content="Private text"
):
    return history.save(
        address,
        {
            "hash": f"{number:064x}",
            "source_hash": address,
            "destination_hash": "dd" * 16,
            "content": content,
            "title": "",
            "state": state,
            "fields": fields or {},
            "created_at": f"2026-11-21T10:00:{number:02d}+00:00",
        },
    )


def test_folders_pins_and_history_survive_reopening_and_folder_deletion(
    store, tmp_path
):
    history, organization = store
    history.ensure_contact(A, "Åsa")
    original = message(history, A, 1)
    folder = organization.create("Friends")
    organization.move([A], folder)
    assert organization.toggle(A) is True
    before = organization.export()
    reopened = ConversationHistory(tmp_path / "messages.sqlite3")
    try:
        saved = ConversationOrganization(reopened)
        assert saved.export() == before and saved.pins() == [A]
        assert (
            saved.conversations({"folder_id": str(folder)})["conversations"][0][
                "destination_hash"
            ]
            == A
        )
        saved.rename(folder, "Radio friends")
        saved.delete(folder)
        assert saved.export() == {"folders": [], "mappings": []}
        assert reopened.message(original["hash"])["content"] == "Private text"
        assert list(reopened.contacts()) == [A] and saved.pins() == [A]
        assert saved.toggle(A) is False and saved.pins() == []
    finally:
        reopened.close()


def test_name_unread_failure_attachment_folder_and_paging_filters(store):
    history, organization = store
    for address, label in ((A, "Åsa"), (B, "Bravo"), (C, "Charlie")):
        history.ensure_contact(address, label)
    message(
        history,
        A,
        1,
        fields={"file_attachments": [{"file_name": "note.txt", "file_bytes": "YQ=="}]},
    )
    message(history, B, 2, state="failed")
    message(history, A, 3)
    message(history, C, 4, content="!NFLOC1:geo:48,-122")
    folder = organization.create("Friends")
    organization.move([A], folder)

    def addresses(query):
        return [
            row["destination_hash"]
            for row in organization.conversations(query)["conversations"]
        ]

    assert addresses({"search": "åSA"}) == [A]
    assert addresses({"filter_unread": "true"}) == [A]
    assert addresses({"filter_failed": "true"}) == [B]
    assert addresses({"filter_has_attachments": "true"}) == [A], (
        "Older attachments must remain searchable"
    )
    assert addresses({"search": "NFLOC1"}) == [], "Telemetry is not a text conversation"
    assert addresses({"folder_id": str(folder)}) == [A]
    assert set(addresses({"folder_id": "0"})) == {B, C}
    organization.toggle(B)
    assert addresses({"limit": "1"}) == [B], (
        "Pinned peers must be included on the first page"
    )
    assert addresses({"limit": "1", "offset": "1"}) == [A]
    history.mark_read(A)
    assert addresses({"filter_unread": "true"}) == []
    for query in (
        {"limit": "0"},
        {"offset": "-1"},
        {"folder_id": "bad"},
        {"filter_unread": "sometimes"},
        {"search": "x" * 257},
    ):
        with pytest.raises(ValueError):
            organization.conversations(query)


def test_import_remaps_ids_preserves_other_folders_and_rolls_back_failed_writes(store):
    history, organization = store
    existing = organization.create("Existing")
    organization.move([A], existing)
    archive = {
        "folders": [{"id": 501, "name": "Imported"}],
        "mappings": [{"peer_hash": B, "folder_id": 501}],
    }
    organization.import_(archive)
    rows = organization.export()
    assert {row["name"] for row in rows["folders"]} == {"Existing", "Imported"}
    imported = next(row["id"] for row in rows["folders"] if row["name"] == "Imported")
    assert imported != 501
    assert {(row["peer_hash"], row["folder_id"]) for row in rows["mappings"]} == {
        (A, existing),
        (B, imported),
    }
    assert history.contacts() == {}, "Folder imports cannot approve contacts"
    before = organization.export()
    with pytest.raises(ValueError):
        organization.import_(
            {
                "folders": archive["folders"],
                "mappings": [{"peer_hash": C, "folder_id": 999}],
            }
        )
    assert organization.export() == before
    history.db.execute(
        "CREATE TRIGGER synthetic_failure BEFORE INSERT ON lxmf_folders WHEN NEW.name = 'Blocked' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        organization.import_(
            {
                "folders": [
                    {"id": 1, "name": "Would roll back"},
                    {"id": 2, "name": "Blocked"},
                ],
                "mappings": [],
            }
        )
    assert organization.export() == before


@pytest.mark.parametrize("label", [None, "", " \n ", "x" * 121, "Bad\x00name"])
def test_invalid_names_never_change_saved_folders(store, label):
    _, organization = store
    folder = organization.create("Keep")
    before = organization.export()
    with pytest.raises(ValueError):
        organization.rename(folder, label)
    assert organization.export() == before


def test_actual_private_api_matches_frontend_shapes_and_preserves_restart(tmp_path):
    from test_next_ios_tcp_integration import api, backend, run_server, start, wait

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {"peers": [{"id": "off", "host": "127.0.0.1", "port": 9, "enabled": False}]}
        )
    )
    ready = tmp_path / "backend.url"
    with ExitStack() as stack:
        start(stack, run_server, tmp_path, ready, settings)
        wait(ready.exists)
        base = backend(ready)
        assert api(base, "lxmf/folders") == (200, [])
        assert api(base, "lxmf/conversation-pins") == (200, {"peer_hashes": []})
        token = api(base, "auth/csrf")[1]["csrf_token"]
        assert api(base, "lxmf/folders", body={"name": "Private"})[0] == 403
        assert (
            api(base, "lxmf/folders", body={"name": "Private"}, token=token)[0] == 200
        )
        folder = api(base, "lxmf/folders")[1][0]["id"]
        assert (
            api(
                base,
                "telephone/contacts",
                body={"name": "Known contact", "lxmf_address": A},
                token=token,
            )[0]
            == 200
        )
        assert api(
            base,
            "lxmf/conversation-pins/toggle",
            body={"destination_hash": A},
            token=token,
        )[1] == {"peer_hashes": [A], "pinned": True}
        assert (
            api(
                base,
                "lxmf/conversations/move-to-folder",
                body={"peer_hashes": [A], "folder_id": folder},
                token=token,
            )[0]
            == 200
        )
        assert (
            len(
                api(base, "lxmf/conversations?folder_id=" + str(folder))[1][
                    "conversations"
                ]
            )
            == 1
        )
        assert api(base, "lxmf/conversations?folder_id=0")[1]["conversations"] == []
        assert api(base, "lxmf/conversations?search=missing")[1]["conversations"] == []
        assert (
            api(base, "lxmf/folders", body={"name": "x" * 5000}, token=token)[0] == 413
        )
        bulk = [f"{number:032x}" for number in range(1, 201)]
        assert (
            api(
                base,
                "lxmf/conversations/move-to-folder",
                body={"peer_hashes": bulk, "folder_id": folder},
                token=token,
            )[0]
            == 200
        )
        saved = api(base, "lxmf/folders/export")[1]
        identity = api(base, "preview/push-enrollment-state")[1]["address"]
    ready.unlink()
    with ExitStack() as stack:
        start(stack, run_server, tmp_path, ready, settings)
        wait(ready.exists)
        base = backend(ready)
        assert api(base, "lxmf/folders/export")[1] == saved
        assert api(base, "lxmf/conversation-pins")[1] == {"peer_hashes": [A]}
        assert api(base, "preview/push-enrollment-state")[1]["address"] == identity
        assert (
            api(base, "telephone/contacts")[1]["contacts"][0]["name"] == "Known contact"
        )
        token = api(base, "auth/csrf")[1]["csrf_token"]
        assert (
            api(base, f"lxmf/folders/{folder}", method="DELETE", token=token)[0] == 200
        )
        assert api(base, "lxmf/folders/export")[1] == {"folders": [], "mappings": []}
        assert api(base, "telephone/contacts")[1]["total_count"] == 1


def test_supported_folder_export_can_be_imported_again_without_losing_unicode(tmp_path):
    from test_next_ios_tcp_integration import api, backend, run_server, start, wait

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {"peers": [{"id": "off", "host": "127.0.0.1", "port": 9, "enabled": False}]}
        )
    )
    ready = tmp_path / "backend.url"
    document = {
        "folders": [
            {"id": number, "name": str(number) + "📍" * 110} for number in range(1, 257)
        ],
        "mappings": [
            {"peer_hash": f"{number:032x}", "folder_id": 1 + number % 256}
            for number in range(1000)
        ],
    }
    with ExitStack() as stack:
        start(stack, run_server, tmp_path, ready, settings)
        wait(ready.exists)
        base = backend(ready)
        token = api(base, "auth/csrf")[1]["csrf_token"]
        assert api(base, "lxmf/folders/import", body=document, token=token)[0] == 200
        exported = api(base, "lxmf/folders/export")[1]
        assert len(exported["folders"]) == 256 and len(exported["mappings"]) == 1000
        assert api(base, "lxmf/folders/import", body=exported, token=token)[0] == 200
        assert api(base, "lxmf/folders/export")[1] == exported
        assert api(base, "telephone/contacts")[1]["total_count"] == 0
