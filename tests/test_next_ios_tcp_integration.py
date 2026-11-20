"""Actual neXt HTTP and LXMF delivery over two isolated loopback interfaces."""
from contextlib import ExitStack
import json
import multiprocessing
from pathlib import Path
import socket
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_hub(folder, ports, pipe):
    import LXMF
    import RNS
    folder.mkdir()
    config = "[reticulum]\nshare_instance = No\nenable_transport = Yes\n[interfaces]\n"
    for index, port in enumerate(ports):
        config += f"[[Private {index}]]\ntype = TCPServerInterface\nenabled = Yes\nlisten_ip = 127.0.0.1\nlisten_port = {port}\n"
    (folder / "config").write_text(config)
    RNS.Reticulum(configdir=str(folder), loglevel=1)
    identity = RNS.Identity()
    router = LXMF.LXMRouter(identity=identity, storagepath=str(folder / "lxmf"), autopeer=False)
    source = router.register_delivery_identity(identity, display_name="Private neXt echo", stamp_cost=0)
    def received(message):
        if not message.signature_validated:
            return
        identity = RNS.Identity.recall(message.source_hash)
        target = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
        router.handle_outbound(LXMF.LXMessage(target, source, "Echo: " + message.content_as_string(), fields=message.fields, desired_method=LXMF.LXMessage.DIRECT))
    router.register_delivery_callback(received)
    class ObservedNames:
        aspect_filter = "lxmf.delivery"
        def received_announce(self, destination_hash, announced_identity, app_data):
            (folder / "observed-name.json").write_text(json.dumps({"address": destination_hash.hex(),
                "name": LXMF.display_name_from_app_data(app_data)}))
    RNS.Transport.register_announce_handler(ObservedNames())
    source.announce()
    pipe.send(source.hash.hex())
    pipe.recv()


def run_server(folder, ready, settings, pipe):
    run_server_mode(folder, ready, settings, True, pipe)


def run_server_mode(folder, ready, settings, device, pipe):
    import asyncio
    sys.path[:0] = [str(ROOT / "ios/NextRuntimeProbe"), str(ROOT / "app/src/main/python")]
    from loopback_probe import serve
    frontend = folder / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "index.html").write_text("<html>Private test</html>")
    asyncio.run(serve(ready, frontend, settings, device=device))


def start(stack, target, *args):
    context = multiprocessing.get_context("spawn")
    pipe, worker = context.Pipe()
    process = context.Process(target=target, args=(*args, worker))
    process.start()
    worker.close()
    def stop():
        pipe.close()
        if process.is_alive(): process.terminate()
        process.join(timeout=5)
        if process.is_alive(): process.kill(); process.join()
        process.close()
    stack.callback(stop)
    return process, pipe


def wait(condition, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value: return value
        time.sleep(0.1)
    raise AssertionError("Private neXt integration condition timed out")


def api(base, path, *, body=None, token=None, method=None):
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = f"http://{urlsplit(base).netloc}"
    if token is not None: headers["X-CSRF-Token"] = token
    request = Request(urljoin(base, "/api/v1/" + path),
        data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    try:
        with urlopen(request, timeout=45) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, error.read().decode()


def test_neXt_backup_delivery_peer_controls_and_restart_preserve_identity_and_history(tmp_path):
    listeners = [socket.socket() for _ in range(2)]
    for listener in listeners: listener.bind(("127.0.0.1", 0))
    ports = [listener.getsockname()[1] for listener in listeners]
    for listener in listeners: listener.close()
    config = {"peers": [dict(id=name, host="127.0.0.1", port=port, enabled=True)
                         for name, port in zip(("primary", "backup"), ports)]}
    app = tmp_path / "next-app"
    app.mkdir()
    settings = app / "settings.json"
    settings.write_text(json.dumps(config))
    with ExitStack() as stack:
        _, hub = start(stack, run_hub, tmp_path / "hub", ports)
        assert hub.poll(10)
        address = hub.recv()
        with ExitStack() as first:
            ready = app / "first.url"
            start(first, run_server, app, ready, settings)
            wait(ready.exists)
            base = ready.read_text()
            assert base.endswith("/#/messages")  # No typed test address required.
            assert api(base, "telephone/contacts")[1]["contacts"] == []
            token = api(base, "auth/csrf")[1]["csrf_token"]
            def connected():
                rows = api(base, "preview/reticulum-connections")[1]["peers"]
                return rows if len(rows) == 2 and all(row["online"] for row in rows) else None
            rows = wait(connected)
            assert api(base, "preview/reticulum-connections", body=config)[0] == 403
            duplicate = dict(peers=[dict(rows[0]), dict(rows[0], id="duplicate")])
            assert api(base, "preview/reticulum-connections", body=duplicate, token=token)[0] == 400
            assert api(base, "telephone/contacts", body={"name": "Private echo", "lxmf_address": address}, token=token)[0] == 200
            identity = (app / "reticulum/identity").read_bytes()
            profile = {"display_name": "Private iOS name", "theme": "dark"}
            assert api(base, "config", body=profile, method="PATCH")[0] == 403
            assert api(base, "config", body=profile, method="PATCH", token=token)[0] == 200
            observed = tmp_path / "hub/observed-name.json"
            def announced_name():
                try:
                    return json.loads(observed.read_text()).get("name") == profile["display_name"]
                except (FileNotFoundError, ValueError):
                    return False
            wait(announced_name)
            current = api(base, "config")[1]["config"]
            assert current["identity_hash"] != current["lxmf_address_hash"]
            assert current["display_name"] == profile["display_name"]
            assert api(base, "preview/reticulum-connection")[1]["theme"] == "dark"
            assert api(base, "config", body={"display_name": "changed", "theme": "invalid"}, method="PATCH", token=token)[0] == 400
            assert api(base, "config")[1]["config"]["display_name"] == profile["display_name"]
            rows[0]["enabled"] = False
            status, result = api(base, "preview/reticulum-connections", body=dict(peers=rows), token=token)
            assert status == 200 and not result["peers"][0]["online"] and result["peers"][1]["online"]
            assert (app / "reticulum/identity").read_bytes() == identity
            text = "Private backup route test"
            assert api(base, "lxmf-messages/send", body={"lxmf_message": {"destination_hash": address, "content": text}}, token=token)[0] == 200
            def arrived():
                messages = api(base, "lxmf-messages/conversation/" + address)[1]["lxmf_messages"]
                delivered = any(row["is_outbound"] and row["content"] == text and row["state"] == "delivered" for row in messages)
                reply = any(not row["is_outbound"] and row["content"] == "Echo: " + text for row in messages)
                return messages if delivered and reply else None
            wait(arrived, 45)
            # Native AppStorage passes the saved peer list back on the next launch.
            settings.write_text(json.dumps(dict(peers=result["peers"])))
        observed.unlink(missing_ok=True)
        ready = app / "second.url"
        start(stack, run_server, app, ready, settings)
        wait(ready.exists)
        base = ready.read_text()
        assert (app / "reticulum/identity").read_bytes() == identity
        current = api(base, "config")[1]["config"]
        assert current["display_name"] == "Private iOS name" and current["theme"] == "dark"
        observed = tmp_path / "hub/observed-name.json"
        def restarted_name():
            try:
                return json.loads(observed.read_text()).get("name") == "Private iOS name"
            except (FileNotFoundError, ValueError):
                return False
        wait(restarted_name)
        assert [row["enabled"] for row in api(base, "preview/reticulum-connections")[1]["peers"]] == [False, True]
        contacts = api(base, "telephone/contacts")[1]["contacts"]
        assert len(contacts) == 1 and contacts[0]["lxmf_address"] == address
        messages = api(base, "lxmf-messages/conversation/" + address)[1]["lxmf_messages"]
        assert any(row["content"] == "Echo: " + text for row in messages)

        summary = api(base, "lxmf/conversations")[1]["conversations"][0]
        assert summary["is_unread"] and summary["unread_count"] == 1
        assert summary["latest_message_preview"] == "Echo: " + text
        token = api(base, "auth/csrf")[1]["csrf_token"]
        read_path = "lxmf/conversations/" + address + "/mark-as-read"
        assert api(base, read_path, body={})[0] == 403
        assert api(base, "lxmf/conversations/bulk-mark-as-read", body={"destination_hashes": [address, "bad"]}, token=token)[0] == 400
        assert api(base, "lxmf/conversations")[1]["conversations"][0]["is_unread"]
        assert api(base, read_path, body={}, token=token)[0] == 200
        assert not api(base, "lxmf/conversations")[1]["conversations"][0]["is_unread"]
        assert api(base, "lxmf/conversations/bulk-mark-as-read", body={"mark_all": True}, token=token)[0] == 200


def test_simulator_profile_identity_and_signed_history_survive_actual_restart(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    app = tmp_path / "simulator-app"
    app.mkdir()
    settings = app / "settings.json"
    with ExitStack() as stack:
        _, hub = start(stack, run_hub, tmp_path / "hub", [port])
        assert hub.poll(10)
        address = hub.recv()
        settings.write_text(json.dumps({"address": address, "peers": [dict(id="private", host="127.0.0.1", port=port, enabled=True)]}))
        with ExitStack() as first:
            ready = app / "first.url"
            start(first, run_server_mode, app, ready, settings, False)
            wait(ready.exists)
            base = ready.read_text()
            own = ready.with_suffix(".address").read_text()
            token = api(base, "auth/csrf")[1]["csrf_token"]
            assert api(base, "config", body={"display_name": "Private simulator", "theme": "dark"}, method="PATCH", token=token)[0] == 200
            assert api(base, "lxmf-messages/send", body={"lxmf_message": {"destination_hash": address, "content": "Simulator persistence"}}, token=token)[0] == 200
            def received():
                return any(row["content"] == "Echo: Simulator persistence" for row in api(base, "lxmf-messages/conversation/" + address)[1]["lxmf_messages"])
            wait(received)
            identity = (app / "reticulum-simulator/identity").read_bytes()
        ready = app / "second.url"
        start(stack, run_server_mode, app, ready, settings, False)
        wait(ready.exists)
        base = ready.read_text()
        assert (app / "reticulum-simulator/identity").read_bytes() == identity
        assert ready.with_suffix(".address").read_text() == own
        current = api(base, "config")[1]["config"]
        assert current["display_name"] == "Private simulator" and current["theme"] == "dark"
        assert any(row["content"] == "Echo: Simulator persistence" for row in api(base, "lxmf-messages/conversation/" + address)[1]["lxmf_messages"])
        assert api(base, "lxmf/conversations")[1]["conversations"][0]["is_unread"]
        assert all(row["host"] == "127.0.0.1" for row in api(base, "preview/reticulum-connections")[1]["peers"])


def test_signed_file_and_photo_delivery_download_and_restart(tmp_path):
    import base64
    listener = socket.socket(); listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]; listener.close()
    app = tmp_path / "attachment-app"; app.mkdir(); settings = app / "settings.json"
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=")
    content = b"Private attachment with exact bytes: \x00\xff"
    with ExitStack() as stack:
        _, hub = start(stack, run_hub, tmp_path / "hub", [port]); assert hub.poll(10); address = hub.recv()
        settings.write_text(json.dumps({"address": address, "peers": [dict(id="private", host="127.0.0.1", port=port, enabled=True)]}))
        with ExitStack() as first:
            ready = app / "first.url"; start(first, run_server, app, ready, settings); wait(ready.exists); base = ready.read_text()
            token = api(base, "auth/csrf")[1]["csrf_token"]
            fields = {"file_attachments": [{"file_name": "../../safe.txt", "file_bytes": base64.b64encode(content).decode()}], "image": {"image_type": "html", "image_bytes": base64.b64encode(png).decode()}}
            status, result = api(base, "lxmf-messages/send", body={"lxmf_message": {"destination_hash": address, "content": "", "fields": fields}}, token=token)
            assert status == 200, result
            def arrived():
                messages = api(base, "lxmf-messages/conversation/" + address)[1]["lxmf_messages"]
                return next((row for row in messages if row["state"] == "received" and row.get("fields", {}).get("image")), None)
            received = wait(arrived)
            assert received["fields"]["file_attachments"][0]["file_bytes"] is None
            assert received["fields"]["image"]["image_bytes"] is None
            message_hash = received["hash"]
            summary = api(base, "lxmf/conversations")[1]["conversations"][0]
            assert summary["has_attachments"] and summary["latest_message_preview"] == "Echo: "
        ready = app / "second.url"; start(stack, run_server, app, ready, settings); wait(ready.exists); base = ready.read_text()
        for kind, data, content_type in [("file", content, "application/octet-stream"), ("image", png, "image/png")]:
            with urlopen(urljoin(base, "/api/v1/lxmf-messages/attachment/" + message_hash + "/" + kind)) as response:
                assert response.read() == data
                assert response.headers["Content-Type"].startswith(content_type)
                assert response.headers["X-Content-Type-Options"] == "nosniff"
                if kind == "file": assert "safe.txt" in response.headers["Content-Disposition"] and ".." not in response.headers["Content-Disposition"]
        for suffix in ("file?file_index=-1", "file?file_index=99", "file?file_index=abc", "audio"):
            with pytest.raises(HTTPError) as error:
                urlopen(urljoin(base, "/api/v1/lxmf-messages/attachment/" + message_hash + "/" + suffix))
            assert error.value.code == 404
