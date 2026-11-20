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
    assert history.preferences() == {"display_name": "Test 雪", "theme": "dark"}
    history.update_preferences({"theme": "light"})
    assert history.preferences() == {"display_name": "Test 雪", "theme": "light"}
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
    assert history.preferences() == {"display_name": "Original", "theme": "dark"}
    history.close()
