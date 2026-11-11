#!/usr/bin/env python3
"""Stage the pure-Python pieces for an embedded Family TCP runtime."""
from argparse import ArgumentParser
from hashlib import file_digest
from pathlib import Path, PurePosixPath
import shutil
from zipfile import ZipFile


RNS_SHA256 = "0e4aaf8cc47f770da34572d2215b45fea900e104b009551600eb9741a41faddf"
FAMILY_SOURCE = Path(__file__).resolve().parents[1] / "app/src/main/python"
FAMILY_MODULES = ("family_backend.py", "family_cards.py", "family_radios.py", "family_routes.py", "family_tcp.py", "family_location.py")


def standalone_rns(source):
    # Only shared-instance RPC uses multiprocessing. Family starts a standalone
    # Reticulum instance, so delay the import until one of those paths runs.
    replacements = {
        "import multiprocessing.connection\n": "",
        "        if self.is_shared_instance:\n            self.rpc_listener = multiprocessing.connection.Listener":
            "        if self.is_shared_instance:\n            import multiprocessing.connection\n"
            "            self.rpc_listener = multiprocessing.connection.Listener",
        "    def get_rpc_client(self): return multiprocessing.connection.Client":
            "    def get_rpc_client(self):\n        import multiprocessing.connection\n"
            "        return multiprocessing.connection.Client",
    }
    for before, after in replacements.items():
        if source.count(before) != 1:
            raise ValueError("The pinned Reticulum source no longer matches the standalone patch")
        source = source.replace(before, after)
    return source


def stage(wheel, destination):
    with wheel.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != RNS_SHA256:
            raise ValueError("Expected the pinned rns-1.5.7 wheel")
    with ZipFile(wheel) as archive:
        patched = standalone_rns(archive.read("RNS/Reticulum.py").decode())
        destination.mkdir(parents=True, exist_ok=False)
        for entry in archive.infolist():
            relative = PurePosixPath(entry.filename)
            if entry.is_dir() or relative.parts[0] not in {"RNS", "rns-1.5.7.dist-info"}:
                continue
            if ".." in relative.parts:
                raise ValueError("Unexpected wheel path")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(patched.encode() if relative.as_posix() == "RNS/Reticulum.py" else archive.read(entry))
    for module in FAMILY_MODULES:
        shutil.copyfile(FAMILY_SOURCE / module, destination / module)
    shutil.copytree(FAMILY_SOURCE / "LXMF", destination / "LXMF", ignore=shutil.ignore_patterns("__pycache__"))
    telemetry = Path("meshchatnext/src/backend/telemetry_utils.py")
    (destination / telemetry.parent).mkdir(parents=True)
    shutil.copyfile(FAMILY_SOURCE / telemetry, destination / telemetry)



if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("rns_wheel", type=Path)
    parser.add_argument("destination", type=Path, help="New directory for staged modules")
    args = parser.parse_args()
    stage(args.rns_wheel, args.destination)
