"""Stage the checksum-pinned public neXt backend and existing iOS MeshCore SDK."""

import argparse
import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import zipfile

NEXT_WHEEL_SHA256 = "bd67437f00d62323d5d12718832bf24a90d5c8d32556dfe15ebc88c8b2f0d294"


def stage(wheel, destination, family_ios):
    if hashlib.file_digest(wheel.open("rb"), "sha256").hexdigest() != NEXT_WHEEL_SHA256:
        raise ValueError("The neXt backend wheel checksum does not match")
    spec = importlib.util.spec_from_file_location("family_runtime_stager", family_ios / "stage-runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.stage_meshcore(destination, family_ios / "RuntimeBuild/meshcore-wheels")
    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe backend wheel member")
            if entry.is_dir():
                continue
            if path.parts[0] != "meshchatnext" and ".dist-info" not in path.parts[0]:
                continue
            # Code plus upstream notices; the frontend is already staged separately.
            if path.parts[0] == "meshchatnext" and path.suffix not in (".py", ".json", ".txt", ".md"):
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))
    import shutil
    shutil.copyfile(family_ios.parent / "app/src/main/python/family_ios_meshcore_crypto.py",
                    destination / "family_ios_meshcore_crypto.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("family_ios", type=Path)
    args = parser.parse_args()
    stage(args.wheel, args.destination, args.family_ios)
