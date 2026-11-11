"""Install the pinned native wheel variant for the current Xcode target."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile


if __name__ == "__main__":
    sdk, architectures, target = sys.argv[1:]
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "room-wheels.json").read_text())
    arches = architectures.split()
    if len(arches) != 1:
        raise ValueError("Build one simulator architecture at a time for the native Python extensions")
    for entry in manifest[f"{sdk}-{arches[0]}"]:
        wheel = root / "RuntimeBuild/room-wheels" / entry["file"]
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Checksum mismatch for {wheel.name}")
        with ZipFile(wheel) as archive:
            archive.extractall(target)
