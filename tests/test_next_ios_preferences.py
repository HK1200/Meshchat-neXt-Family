"""Profile settings retain history and reject incomplete/unsupported edits atomically."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"))
from loopback_probe import ConversationHistory


def test_saved_profile_survives_restart_and_partial_updates(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    assert history.preferences()["theme"] == "system"
    history.ensure_contact("ab" * 16, "Saved contact")
    history.update_preferences({"display_name": "  Test 雪  ", "theme": "dark"})
    history.close()
    history = ConversationHistory(path)
    assert history.preferences() == {"display_name": "Test 雪", "theme": "dark", "auto_announce_interval_seconds": 3600, "page_archiver_enabled": False}
    history.update_preferences({"theme": "light"})
    assert history.preferences() == {"display_name": "Test 雪", "theme": "light", "auto_announce_interval_seconds": 3600, "page_archiver_enabled": False}
    assert len(history.contacts()) == 1
    history.close()


@pytest.mark.parametrize("changes", [None, [], {}, {"theme": "wrong"}, {"theme": []},
    {"display_name": ""}, {"display_name": "\nName"}, {"display_name": 1},
    {"display_name": "雪" * 43}, {"identity_hash": "changed"},
    {"display_name": "New name", "theme": "wrong"}])
def test_invalid_profile_edits_do_not_change_saved_settings(tmp_path, changes):
    history = ConversationHistory(tmp_path / "history.sqlite3")
    history.update_preferences({"display_name": "Original", "theme": "dark"})
    with pytest.raises(ValueError):
        history.update_preferences(changes)
    assert history.preferences() == {"display_name": "Original", "theme": "dark", "auto_announce_interval_seconds": 3600, "page_archiver_enabled": False}
    history.close()


@pytest.mark.parametrize("interval", [0, 900, 1800, 3600, 10800, 21600, 43200, 86400])
def test_announce_interval_survives_restart_without_affecting_profile(tmp_path, interval):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    history.update_preferences({"display_name": "Saved name", "auto_announce_interval_seconds": interval})
    history.close()
    history = ConversationHistory(path)
    assert history.preferences()["auto_announce_interval_seconds"] == interval
    assert history.preferences()["display_name"] == "Saved name"
    history.close()


@pytest.mark.parametrize("interval", [True, False, -1, 1, 60, 3600.0, "3600", None, []])
def test_invalid_announce_interval_is_atomic(tmp_path, interval):
    history = ConversationHistory(tmp_path / "history.sqlite3")
    before = history.preferences()
    with pytest.raises(ValueError):
        history.update_preferences({"display_name": "Changed", "auto_announce_interval_seconds": interval})
    assert history.preferences() == before
    history.close()


def test_successful_announce_time_survives_restart_is_not_editable_and_keeps_profile(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    assert history.last_announce_time() is None
    history.record_announce_time(1_800_000_000)
    assert "last_announced_at" not in history.preferences()
    with pytest.raises(ValueError):
        history.update_preferences({"last_announced_at": 1_800_000_100})
    history.close()
    history = ConversationHistory(path)
    assert history.last_announce_time() == 1_800_000_000
    assert history.preferences()["auto_announce_interval_seconds"] == 3600
    history.close()


@pytest.mark.parametrize("floor", [True, False, -1, 9_000_000_000_000_001, 1.0, "1", None])
def test_invalid_native_notification_floor_never_opens_or_changes_history(tmp_path, floor):
    path = tmp_path / "history.sqlite3"
    with pytest.raises(ValueError):
        ConversationHistory(path, notification_floor=floor)
    assert not path.exists()


@pytest.mark.parametrize("enabled", [False, True])
def test_page_archive_preference_survives_restart_without_changing_contacts(tmp_path, enabled):
    path = tmp_path / "history.sqlite3"
    history = ConversationHistory(path)
    history.ensure_contact("ab" * 16, "Saved contact")
    history.update_preferences({"display_name": "Saved name", "page_archiver_enabled": enabled})
    history.close()
    history = ConversationHistory(path)
    assert history.preferences()["page_archiver_enabled"] is enabled
    assert history.preferences()["display_name"] == "Saved name"
    assert len(history.contacts()) == 1
    history.close()


@pytest.mark.parametrize("enabled", [None, 0, 1, "true", [], {}])
def test_invalid_archive_preference_is_atomic(tmp_path, enabled):
    history = ConversationHistory(tmp_path / "history.sqlite3")
    before = history.preferences()
    with pytest.raises(ValueError):
        history.update_preferences({"display_name": "Changed", "page_archiver_enabled": enabled})
    assert history.preferences() == before
    history.close()
