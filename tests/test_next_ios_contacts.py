"""Local phonebook edits preserve independent signed conversation history."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"))
from loopback_probe import ConversationHistory


def test_rename_remove_and_restart_preserve_messages_read_state_and_other_contacts(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    alice, bob = "ab" * 16, "cd" * 16
    history.ensure_contact(alice, "Old Alice")
    history.ensure_contact(bob, "Bob")
    identifier = history.contacts()[alice]["id"]
    history.save(alice, dict(hash="aa" * 32, state="received", content="Saved private message", title="", created_at="2026-11-21T13:00:00Z"))
    history.mark_read(alice)
    history.rename_contact(identifier, "  Alice 雪  ")
    assert history.contacts()[alice]["name"] == "Alice 雪"
    assert history.custom_name(alice) == "Alice 雪"
    history.remove_contact(identifier)
    assert alice not in history.contacts()
    assert history.contacts()[bob]["name"] == "Bob"
    assert history.conversation_entries()[alice] == {"name": "Alice 雪", "is_contact": False}
    assert history.summary(alice)["unread_count"] == 0
    history.close()
    history = ConversationHistory(path)
    assert len(history.page(alice, {})) == 1
    assert history.page(alice, {})[0]["content"] == "Saved private message"
    assert history.conversation_entries()[alice]["name"] == "Alice 雪"
    assert len(history.contacts()) == 1
    history.set_custom_name(alice, "")
    assert history.conversation_entries()[alice]["name"] == alice
    history.close()


@pytest.mark.parametrize("name", [None, [], 4, "", "  ", "a" * 121, "bad\nname", "bad\0name", "bad\x7fname"])
def test_invalid_rename_cannot_change_any_saved_value(tmp_path, name):
    history = ConversationHistory(tmp_path / "history.sqlite3")
    address = "ab" * 16
    history.ensure_contact(address, "Original")
    before = history.contacts()
    with pytest.raises(ValueError):
        history.rename_contact(before[address]["id"], name)
    assert history.contacts() == before
    assert history.custom_name(address) is None
    history.close()


def test_missing_contact_and_invalid_address_cannot_change_saved_contacts(tmp_path):
    history = ConversationHistory(tmp_path / "history.sqlite3")
    history.ensure_contact("ab" * 16, "Saved")
    before = history.contacts()
    with pytest.raises(KeyError): history.rename_contact(999, "Missing")
    with pytest.raises(KeyError): history.remove_contact(999)
    with pytest.raises(ValueError): history.set_custom_name("not an address", "Label")
    history.set_custom_name("cd" * 16, "Local label only")
    assert history.contacts() == before
    assert "cd" * 16 not in history.conversation_entries()
    history.close()
