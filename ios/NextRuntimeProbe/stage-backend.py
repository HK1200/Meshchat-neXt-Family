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
            payload = archive.read(entry)
            if entry.filename == "meshchatnext/src/backend/meshcore_credentials.py":
                before = b'                if transport_platform() == "linux":'
                after = b'                import sys\n                if sys.platform == "ios":\n                    from meshcore_keychain import IOSNodePasswords\n                    self._provider = IOSNodePasswords()\n                elif transport_platform() == "linux":'
                if payload.count(before) != 1:
                    raise ValueError("The pinned credential-provider source changed")
                payload = payload.replace(before, after)
            if entry.filename == "meshchatnext/src/backend/meshcore_repeats.py":
                replacements = (
                    (b"    from Crypto.Cipher import AES", b"    from family_ios_meshcore_crypto import AES"),
                    (b"    from Crypto.Protocol.DH import key_agreement\n    from Crypto.PublicKey import ECC",
                     b"    from meshcore_repeat_crypto import shared_secret"),
                    (b"""    secret = key_agreement(
        static_priv=ECC.construct(curve="Curve25519", seed=private[:32]),
        static_pub=ECC.construct(curve="Curve25519", point_x=u),
        kdf=lambda value: value,
    )""", b"    secret = shared_secret(private[:32], u)"),
                )
                for before, after in replacements:
                    if payload.count(before) != 1:
                        raise ValueError("The pinned repeat-fingerprint source changed")
                    payload = payload.replace(before, after)
            if entry.filename == "meshchatnext/src/backend/sip_desktop_network.py":
                # iOS injects NWPathMonitor routes and has no psutil extension.
                # Desktop discovery can still import its own dependency lazily.
                before = b"import psutil\n"
                after = b""
                if payload.count(before) != 1:
                    raise ValueError("The pinned SIP network source changed")
                payload = payload.replace(before, after)
                before = b"    try:\n        if route_text is None:"
                after = b"    import psutil\n    try:\n        if route_text is None:"
                if payload.count(before) != 1:
                    raise ValueError("The pinned SIP discovery source changed")
                payload = payload.replace(before, after)
            target.write_bytes(payload)
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
