import json
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
import RNS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/src/main/python"))
from family_migration import export_profile, import_profile


def test_transfer_keeps_identity_contacts_settings_and_history(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    identity = RNS.Identity()
    identity.to_file(str(old / "identity"))
    attachment = old / "attachments" / ("a" * 32 + "-0.bin")
    attachment.parent.mkdir()
    attachment.write_bytes(b"example attachment")
    state = {
        "setup_complete": True,
        "contacts": [{"name": "Guardian"}],
        "messages": [{"text": "Example message"}],
        "peer": {"host": "rmap.world", "port": 4242, "enabled": True},
        "location_policy": {"until": -1},
    }
    archive = tmp_path / "transfer.zip"
    export_profile(old, state, archive)
    restored = import_profile(new, archive)
    assert RNS.Identity.from_file(str(new / "identity")).hash == identity.hash
    assert restored["contacts"] == state["contacts"]
    assert restored["messages"] == state["messages"]
    assert restored["peer"] == state["peer"]
    assert restored["location_policy"]["until"] == 0
    assert (new / attachment.relative_to(old)).read_bytes() == b"example attachment"
    assert json.loads((new / "state.json").read_bytes()) == restored


def test_invalid_archive_cannot_replace_fresh_profile(tmp_path):
    root = tmp_path / "new"
    root.mkdir()
    original = b'{"setup_complete":false}'
    (root / "state.json").write_bytes(original)
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as file:
        file.writestr("state.json", '{"setup_complete":true}')
        file.writestr("../outside", "reject")
    with pytest.raises(ValueError, match="Invalid Family transfer"):
        import_profile(root, archive)
    assert (root / "state.json").read_bytes() == original
    assert not (tmp_path / "outside").exists()
