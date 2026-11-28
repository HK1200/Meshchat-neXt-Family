"""Native deletion challenges must get genuine signed fixture replies."""

from contextlib import ExitStack
import json
import os
import pytest
from pathlib import Path
import subprocess
import sys

from test_next_ios_tcp_integration import api, backend, run_server, start, wait

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("store_capture", [False, True])
def test_actual_private_fixture_echoes_all_three_native_ui_challenges(tmp_path, store_capture):
    folder = tmp_path / "peer"
    with (tmp_path / "echo.log").open("w") as log, ExitStack() as stack:
        environment = dict(os.environ)
        environment.pop("FAMILY_STORE_SCREENSHOTS", None)
        if store_capture:
            environment["FAMILY_STORE_SCREENSHOTS"] = "1"
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "ios/simulator-peer.py"),
                str(folder),
                "local-no-drop",
                "attachment-echo",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
        )

        def stop():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        stack.callback(stop)
        wait(lambda: (folder / "peer.json").is_file(), timeout=30)
        fixture = json.loads((folder / "peer.json").read_text())
        assert fixture["host"] == "127.0.0.1"
        assert fixture["message"].startswith("Hello from simulator ")
        assert ("captureMessage" in fixture) == store_capture
        if store_capture:
            assert fixture["captureMessage"] == "Made it home safely."
            assert fixture["captureReply"] == "Thanks! I will be there soon."
        assert fixture["deleteMessage"] == "Delete proof: " + fixture["message"]
        assert fixture["freshMessage"] == "Fresh after delete: " + fixture["message"]
        app = tmp_path / "app"
        app.mkdir()
        ready = app / "backend.url"
        settings = app / "peers.json"
        settings.write_text(
            json.dumps(
                dict(
                    address=fixture["address"],
                    peers=[
                        dict(
                            id="isolated",
                            host="127.0.0.1",
                            port=fixture["port"],
                            enabled=True,
                        )
                    ],
                )
            )
        )
        start(stack, run_server, app, ready, settings)
        wait(ready.is_file)
        base = backend(ready)
        token = api(base, "auth/csrf")[1]["csrf_token"]
        challenges = ("message", "deleteMessage", "freshMessage")
        if store_capture:
            challenges = ("captureMessage",) + challenges
        for key in challenges:
            text = fixture[key]
            expected_reply = fixture["captureReply"] if key == "captureMessage" else "Echo: " + text
            status, _ = api(
                base,
                "lxmf-messages/send",
                token=token,
                body={
                    "lxmf_message": {
                        "destination_hash": fixture["address"],
                        "content": text,
                    },
                },
            )
            assert status == 200

            def echoed():
                rows = api(base, "lxmf-messages/conversation/" + fixture["address"])[1][
                    "lxmf_messages"
                ]
                return any(
                    row["content"] == expected_reply
                    and row["state"] == "received"
                    and row["source_hash"] == fixture["address"]
                    for row in rows
                )

            wait(echoed, timeout=65)


def test_store_capture_refuses_public_peer_before_creating_a_network_fixture(tmp_path):
    folder = tmp_path / "must-not-exist"
    result = subprocess.run(
        [sys.executable, str(ROOT / "ios/simulator-peer.py"), str(folder), "rmap"],
        env=dict(os.environ, FAMILY_STORE_SCREENSHOTS="1"),
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert "Store screenshot fixtures must stay on loopback" in result.stderr
    assert not folder.exists()
