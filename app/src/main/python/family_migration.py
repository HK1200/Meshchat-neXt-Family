"""One-release profile transfer between the two signed Android Family packages."""

import json
import re
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

MAX_PROFILE_BYTES = 4 * 1024**3
MAX_STATE_BYTES = 32 * 1024**2
MAX_ENTRIES = 17_000
ATTACHMENT = re.compile(r"attachments/[0-9a-f]{32}(?:-[0-9]{1,2})?\.bin")
MAP = re.compile(r"maps/[0-9a-f]{32}\.mbtiles")


def allowed_entry(name):
    return name in {"state.json", "identity"} or ATTACHMENT.fullmatch(name) or MAP.fullmatch(name)


def export_profile(root, state, destination):
    identity = root / "identity"
    if not state.get("setup_complete") or not identity.is_file():
        raise ValueError("Wait for Family to finish starting before transferring.")
    snapshot = json.dumps(state).encode()
    if len(snapshot) > MAX_STATE_BYTES:
        raise ValueError("Family settings exceed the transfer limit.")
    files = [identity]
    for folder in ("attachments", "maps"):
        files.extend(path for path in (root / folder).glob("*")
                     if allowed_entry(path.relative_to(root).as_posix()) and path.is_file() and not path.is_symlink())
    if len(files) >= MAX_ENTRIES or len(snapshot) + sum(path.stat().st_size for path in files) > MAX_PROFILE_BYTES:
        raise ValueError("The Family profile exceeds the transfer limit.")
    with ZipFile(destination, "x", compression=ZIP_STORED) as archive:
        archive.writestr("state.json", snapshot)
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())


def import_profile(root, archive_path):
    import RNS

    with tempfile.TemporaryDirectory(prefix="family-transfer-", dir=root.parent) as temporary:
        staged = Path(temporary)
        names = set()
        size = 0
        with ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ENTRIES:
                raise ValueError("Too many files in the Family transfer.")
            for entry in entries:
                name = entry.filename
                limit = MAX_STATE_BYTES if name == "state.json" else 64 if name == "identity" else MAX_PROFILE_BYTES
                if not allowed_entry(name) or name in names or entry.file_size > limit or entry.compress_type != ZIP_STORED:
                    raise ValueError("Invalid Family transfer file.")
                size += entry.file_size
                if size > MAX_PROFILE_BYTES:
                    raise ValueError("The Family profile exceeds the transfer limit.")
                names.add(name)
                target = staged / name
                target.parent.mkdir(exist_ok=True)
                with archive.open(entry) as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination, length=64 * 1024)
        if not {"state.json", "identity"} <= names:
            raise ValueError("The Family transfer is incomplete.")
        state = json.loads((staged / "state.json").read_bytes())
        if not isinstance(state, dict) or state.get("setup_complete") is not True:
            raise ValueError("The transferred Family profile is incomplete.")
        for name in ("contacts", "messages"):
            if not isinstance(state.get(name), list):
                raise ValueError("Invalid Family profile.")
        identity = RNS.Identity.from_file(str(staged / "identity"))
        if not identity or len(identity.get_private_key()) != 64:
            raise ValueError("The Reticulum identity is invalid.")
        # Don't resume live location sharing from another app without a new start.
        if isinstance(state.get("location_policy"), dict):
            state["location_policy"]["until"] = 0
        (staged / "state.json").write_text(json.dumps(state))
        for folder in ("attachments", "maps"):
            (root / folder).mkdir(exist_ok=True)
        for name in names - {"state.json"}:
            (staged / name).chmod(0o600)
            (staged / name).replace(root / name)
        # Publish setup_complete only after identity, maps and attachments exist.
        (staged / "state.json").chmod(0o600)
        (staged / "state.json").replace(root / "state.json")
        return state
