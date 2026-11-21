"""Persistent inbox state for the real neXt conversation list."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ios/NextRuntimeProbe"))
from loopback_probe import ConversationHistory


def message(identifier, state="received", content="Incoming"):
    return dict(hash=identifier, state=state, content=content, title="", created_at="2026-11-20T12:00:00+00:00")


def test_unread_survives_restart_and_marking_one_peer_does_not_hide_another(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    history.save("alice", message("a"))
    history.save("bob", message("b"))
    history.close()
    history = ConversationHistory(path)
    assert history.summary("alice")["unread_count"] == 1
    history.mark_read("alice")
    assert not history.summary("alice")["is_unread"]
    assert history.summary("bob")["is_unread"]
    history.close()
    history = ConversationHistory(path)
    assert not history.summary("alice")["is_unread"]
    assert history.summary("bob")["unread_count"] == 1
    history.close()


def test_receipt_updates_and_repeated_delivery_do_not_create_extra_unread(tmp_path):
    history = ConversationHistory(tmp_path / "history.sqlite3")
    history.save("alice", message("a"))
    history.save("alice", message("a"))
    assert history.summary("alice")["unread_count"] == 1
    history.mark_read("alice")
    history.save("alice", message("a"))
    history.save("alice", message("b", "sending", "Outgoing"))
    history.save("alice", message("b", "delivered", "Outgoing"))
    assert not history.summary("alice")["is_unread"]
    history.save("alice", message("c", content="New message"))
    assert history.summary("alice")["unread_count"] == 1
    assert history.summary("alice")["latest_message_preview"] == "New message"
    history.delete("c")
    assert not history.summary("alice")["is_unread"]
    history.close()


def test_upgrade_keeps_old_history_read_and_preserves_identity_independent_data(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    history.save("alice", message("a"))
    history.db.execute("DROP TABLE conversation_reads")
    history.db.commit()
    history.close()
    history = ConversationHistory(path)
    assert not history.summary("alice")["is_unread"]
    assert history.page("alice", {})[0]["content"] == "Incoming"
    history.save("alice", message("b"))
    assert history.summary("alice")["unread_count"] == 1
    history.close()


def test_deleting_last_read_message_does_not_hide_next_arrival(tmp_path):
    history = ConversationHistory(tmp_path / "history.sqlite3")
    history.save("alice", message("a"))
    history.mark_read("alice")
    history.delete("a")
    history.save("alice", message("b"))
    assert history.summary("alice")["is_unread"]
    history.mark_read("alice")
    history.save("alice", message("c", "failed", "Unsent"))
    summary = history.summary("alice")
    assert not summary["is_unread"]
    assert summary["failed_messages_count"] == 1
    assert summary["latest_message_preview"] == "Unsent"
    history.close()


def test_deleting_latest_unread_message_cannot_reuse_the_permission_baseline_id(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    peer = "ab" * 16
    history.save(peer, message("01" * 32))
    newest = history.save(peer, message("02" * 32))
    permission_baseline = newest["id"]
    history.delete(newest["hash"])
    history.close()
    history = ConversationHistory(path)
    arrival = history.save(peer, message("03" * 32))
    assert arrival["id"] > permission_baseline
    history.close()


def test_legacy_native_baseline_seeds_future_ids_without_changing_old_rows(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    original = history.save("ab" * 16, message("01" * 32))
    history.ensure_contact("ab" * 16, "Saved contact")
    history.close()
    history = ConversationHistory(path, notification_floor=50)
    assert history.page("ab" * 16, {})[0] == original
    assert len(history.contacts()) == 1
    arrival = history.save("ab" * 16, message("02" * 32))
    assert arrival["id"] > 50
    updated = history.save("ab" * 16, message("02" * 32, content="Updated receipt"))
    assert updated["id"] == arrival["id"]
    history.delete(arrival["hash"])
    history.close()
    history = ConversationHistory(path, notification_floor=0)
    later = history.save("ab" * 16, message("03" * 32))
    assert later["id"] > arrival["id"]
    history.close()


def test_counter_migration_keeps_preexisting_messages_and_read_watermarks(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    original = history.save("ab" * 16, message("01" * 32))
    history.mark_read("ab" * 16)
    history.db.execute("DROP TABLE next_runtime_counters")
    history.db.commit()
    history.close()
    history = ConversationHistory(path)
    assert history.page("ab" * 16, {})[0] == original
    assert not history.summary("ab" * 16)["is_unread"]
    assert history.save("ab" * 16, message("02" * 32))["id"] > original["id"]
    history.close()
