"""Compatibility and byte-budget checks for LXMF attachment fields."""
import base64
from pathlib import Path
import sys
import pytest
import LXMF
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"))
import attachment_fields as attachments

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=")


def test_files_and_photo_round_trip_use_actual_bytes_and_safe_names():
    raw = attachments.outgoing({"file_attachments": [{"file_name": "../../private\\note.txt", "file_size": 999, "file_bytes": base64.b64encode(b"Private test").decode()}],
        "image": {"image_type": "html", "image_bytes": base64.b64encode(PNG).decode()}})
    ui = attachments.incoming(raw)
    assert raw[LXMF.FIELD_IMAGE][0] == "png"
    assert ui["image"]["image_size"] == len(PNG)
    assert ui["file_attachments"][0] == {"file_name": "note.txt", "file_size": 12, "file_bytes": base64.b64encode(b"Private test").decode()}
    slim = attachments.slim({"fields": ui})
    assert slim["fields"]["image"]["image_bytes"] is None
    assert slim["fields"]["file_attachments"][0]["file_bytes"] is None
    assert ui["image"]["image_bytes"] is not None


@pytest.mark.parametrize("fields", [[], {"audio": {}}, {"image": None}, {"image": {"image_bytes": "!!!!"}},
    {"image": {"image_bytes": base64.b64encode(b"<svg onload='bad()'/>").decode()}},
    {"file_attachments": []}, {"file_attachments": [None]},
    {"file_attachments": [{"file_name": "x", "file_bytes": "not base64"}]}])
def test_invalid_or_unsupported_attachments_are_rejected_before_send(fields):
    with pytest.raises(ValueError): attachments.outgoing(fields)


def test_byte_budget_counts_content_and_all_files(monkeypatch):
    monkeypatch.setattr(attachments, "MAX_BYTES", 16)
    item = {"file_name": "x", "file_bytes": base64.b64encode(b"12345678").decode()}
    assert len(attachments.outgoing({"file_attachments": [item, item]})[LXMF.FIELD_FILE_ATTACHMENTS]) == 2
    with pytest.raises(ValueError): attachments.outgoing({"file_attachments": [item, item]}, "x")
    with pytest.raises(ValueError): attachments.outgoing({"file_attachments": [item] * 33})


def test_malformed_peer_fields_do_not_crash_or_overwrite_text():
    assert attachments.incoming({LXMF.FIELD_IMAGE: ["png", b"not an image"], LXMF.FIELD_FILE_ATTACHMENTS: [None, ["bad", "not bytes"]]}) == {}
    assert attachments.filename("..\\folder\\\r\nname.txt") == "name.txt"


def test_attachment_only_conversation_has_a_visible_preview(tmp_path):
    from loopback_probe import ConversationHistory
    history = ConversationHistory(tmp_path / "history.sqlite3")
    history.save("peer", {"hash": "file", "state": "received", "content": "", "fields": {"file_attachments": [{"file_name": "notes.txt", "file_size": 0, "file_bytes": ""}]}})
    assert history.summary("peer")["has_attachments"]
    assert history.summary("peer")["latest_message_preview"] == "notes.txt"
    history.save("peer", {"hash": "image", "state": "received", "content": "", "fields": {"image": {"image_type": "png", "image_size": len(PNG), "image_bytes": base64.b64encode(PNG).decode()}}})
    assert history.summary("peer")["latest_message_preview"] == "Photo"
    history.close()
