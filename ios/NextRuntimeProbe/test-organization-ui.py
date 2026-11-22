"""Private browser proof against the exact archived iOS frontend, with RF off."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--playwright", type=Path)
    parser.add_argument("--server", action="store_true")
    args = parser.parse_args()
    frontend = args.frontend.resolve()
    folder = args.work_dir.resolve()
    if args.server:
        sys.path[:0] = [str(ROOT), str(ROOT.parents[1] / "app/src/main/python")]
        from loopback_probe import serve

        asyncio.run(
            serve(folder / "backend.url", frontend, folder / "peers.json", device=True)
        )
        return
    assert (frontend / "index.html").is_file()
    assert args.playwright and args.playwright.is_dir()
    folder.mkdir(parents=True, exist_ok=False)
    os.chmod(folder, 0o700)
    (folder / "peers.json").write_text(
        json.dumps(
            {"peers": [{"id": "off", "host": "127.0.0.1", "port": 9, "enabled": False}]}
        )
    )
    with (folder / "backend.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--server",
                "--frontend",
                str(frontend),
                "--work-dir",
                str(folder),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 30
            while not (folder / "backend.url").exists():
                assert server.poll() is None, "The owned private backend exited"
                assert time.monotonic() < deadline, (
                    "The owned private backend did not become ready"
                )
                time.sleep(0.1)
            subprocess.run(
                [
                    "node",
                    str(ROOT / "test-organization-ui.cjs"),
                    str(folder),
                    str(args.playwright.resolve()),
                ],
                check=True,
                timeout=150,
            )
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
