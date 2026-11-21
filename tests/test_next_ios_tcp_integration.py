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
    # This bounded private hub deliberately receives rapid same-identity startup,
    # rename and reconnect bursts. Ingress holds are a separate transport policy;
    # keep this delivery/persistence test independent of their 15-second windows.
    # Assert the loopback boundary before changing any fixture-only setting.
    from RNS.Interfaces.TCPInterface import TCPServerInterface
    listeners = [interface for interface in RNS.Transport.interfaces
                 if isinstance(interface, TCPServerInterface)]
    assert len(listeners) == len(ports)
    for interface in listeners:
        assert interface.bind_ip == "127.0.0.1"
        interface.ingress_control = False
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
    while True:
        command = pipe.recv()
        if not isinstance(command, dict):
            break
        if command.get("announce"):
            source.announce()
            continue
        address = bytes.fromhex(command["send_to"])
        identity = RNS.Identity.recall(address)
        assert identity is not None
        target = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
        router.handle_outbound(LXMF.LXMessage(target, source, command["content"], desired_method=LXMF.LXMessage.DIRECT))


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


SESSIONS = {}


def backend(ready):
    base = ready.read_text()
    info = json.loads((ready.parent / "next-runtime-info.json").read_text())
    assert info["origin"] == "http://" + urlsplit(base).netloc
    assert info["version"] == 1 and len(info["capability"]) == 43
    SESSIONS[urlsplit(base).netloc] = info["capability"]
    return base


def verify_private_session(base):
    origin = "http://" + urlsplit(base).netloc
    status = origin + "/api/v1/status"
    for headers in ({}, {"X-neXt-Session": "incorrect"}):
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(status, headers=headers), timeout=5)
        assert denied.value.code == 403
    secret = SESSIONS[urlsplit(base).netloc]
    with urlopen(Request(origin + "/", headers={"X-neXt-Session": secret}), timeout=5) as response:
        cookie = response.headers["Set-Cookie"]
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
        assert secret.encode() not in response.read()
        assert f"connect-src 'self' ws://{urlsplit(base).netloc} https: wss:" in response.headers["Content-Security-Policy"]
    with urlopen(Request(status, headers={"Cookie": cookie.split(";", 1)[0]}), timeout=5) as response:
        assert json.load(response)["runtime_instance"]
    with pytest.raises(HTTPError) as denied:
        urlopen(Request(status, headers={"X-neXt-Session": secret, "Origin": "http://example.invalid"}), timeout=5)
    assert denied.value.code == 403
    with urlopen(origin + "/", timeout=5) as response:
        assert response.headers.get("Set-Cookie") is None
    import asyncio
    import aiohttp
    async def websocket_access():
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.WSServerHandshakeError) as blocked:
                await session.ws_connect(origin + "/ws")
            assert blocked.value.status == 403
            async with session.ws_connect(origin + "/ws", headers={"Cookie": cookie.split(";", 1)[0]}) as ws:
                await ws.send_json({"type": "ping"})
                for _ in range(5):
                    if (await ws.receive_json(timeout=5))["type"] == "pong":
                        break
                else:
                    raise AssertionError("Authenticated WebSocket did not respond")
    asyncio.run(websocket_access())


def private_request(base, path):
    return Request(urljoin(base, path), headers={"X-neXt-Session": SESSIONS[urlsplit(base).netloc]})


def api(base, path, *, body=None, token=None, method=None):
    headers = {"X-neXt-Session": SESSIONS[urlsplit(base).netloc]}
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
            base = backend(ready)
            verify_private_session(base)
            assert base.endswith("/#/messages")  # No typed test address required.
            assert api(base, "telephone/contacts")[1]["contacts"] == []
            token = api(base, "auth/csrf")[1]["csrf_token"]
            radio = dict(enabled=False, transport="tcp", endpoint="127.0.0.1",
                         frequency=914.875, bandwidth=125, sf=8, cr=7, power=17)
            assert api(base, "preview/rnode")[1]["settings"] is None
            assert api(base, "preview/rnode", body=radio)[0] == 403
            status, saved_radio = api(base, "preview/rnode", body=radio, token=token)
            assert status == 200 and saved_radio["settings"] == radio
            assert not saved_radio["runtime"]["online"]
            assert api(base, "preview/rnode", body=dict(radio, sf=99), token=token)[0] == 400
            assert api(base, "preview/rnode")[1]["settings"] == radio
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
            discovered = wait(lambda: api(base, "announces?aspect=lxmf.delivery&search=Private")[1].get("announces"))
            assert discovered[0]["destination_hash"] == address
            assert discovered[0]["display_name"] == "Private neXt echo"
            status, error = api(base, "announces?limit=100000")
            assert status == 400 and error == "Invalid discovery search or pagination"
            # Native AppStorage passes the saved peer list back on the next launch.
            settings.write_text(json.dumps(dict(peers=result["peers"])))
        observed.unlink(missing_ok=True)
        ready = app / "second.url"
        start(stack, run_server, app, ready, settings)
        wait(ready.exists)
        base = backend(ready)
        assert (app / "reticulum/identity").read_bytes() == identity
        current = api(base, "config")[1]["config"]
        assert current["display_name"] == "Private iOS name" and current["theme"] == "dark"
        assert api(base, "preview/rnode")[1]["settings"] == radio
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
            base = backend(ready)
            own = ready.with_suffix(".address").read_text()
            token = api(base, "auth/csrf")[1]["csrf_token"]
            radio = dict(enabled=True, transport="tcp", endpoint="127.0.0.1",
                         frequency=914.875, bandwidth=125, sf=8, cr=7, power=17)
            assert api(base, "preview/rnode", body=radio, token=token)[0] == 400
            assert api(base, "preview/rnode")[1]["settings"] is None
            assert api(base, "config", body={"display_name": "Private simulator", "theme": "dark"}, method="PATCH", token=token)[0] == 200
            assert api(base, "lxmf-messages/send", body={"lxmf_message": {"destination_hash": address, "content": "Simulator persistence"}}, token=token)[0] == 200
            def received():
                return any(row["content"] == "Echo: Simulator persistence" for row in api(base, "lxmf-messages/conversation/" + address)[1]["lxmf_messages"])
            wait(received)
            identity = (app / "reticulum-simulator/identity").read_bytes()
        ready = app / "second.url"
        start(stack, run_server_mode, app, ready, settings, False)
        wait(ready.exists)
        base = backend(ready)
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
            ready = app / "first.url"; start(first, run_server, app, ready, settings); wait(ready.exists); base = backend(ready)
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
        ready = app / "second.url"; start(stack, run_server, app, ready, settings); wait(ready.exists); base = backend(ready)
        for kind, data, content_type in [("file", content, "application/octet-stream"), ("image", png, "image/png")]:
            with urlopen(private_request(base, "/api/v1/lxmf-messages/attachment/" + message_hash + "/" + kind)) as response:
                assert response.read() == data
                assert response.headers["Content-Type"].startswith(content_type)
                assert response.headers["X-Content-Type-Options"] == "nosniff"
                if kind == "file": assert "safe.txt" in response.headers["Content-Disposition"] and ".." not in response.headers["Content-Disposition"]
        for suffix in ("file?file_index=-1", "file?file_index=99", "file?file_index=abc", "audio"):
            with pytest.raises(HTTPError) as error:
                urlopen(private_request(base, "/api/v1/lxmf-messages/attachment/" + message_hash + "/" + suffix))
            assert error.value.code == 404


def test_signed_unsaved_sender_reaches_inbox_can_be_replied_to_and_survives_restart(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    app = tmp_path / "next-app"
    app.mkdir()
    settings = app / "settings.json"
    settings.write_text(json.dumps({"peers": [dict(id="private", host="127.0.0.1", port=port, enabled=True)]}))
    with ExitStack() as stack:
        _, hub = start(stack, run_hub, tmp_path / "hub", [port])
        assert hub.poll(10)
        sender = hub.recv()
        with ExitStack() as first:
            ready = app / "first.url"
            start(first, run_server, app, ready, settings)
            wait(ready.exists)
            base = backend(ready)
            own = api(base, "config")[1]["config"]["lxmf_address_hash"]
            observed = tmp_path / "hub/observed-name.json"
            wait(lambda: observed.exists() and json.loads(observed.read_text())["address"] == own)
            assert api(base, "telephone/contacts")[1]["contacts"] == []
            hub.send({"announce": True})
            wait(lambda: any(row["destination_hash"] == sender for row in api(base, "announces")[1]["announces"]))
            hub.send({"send_to": own, "content": "Signed first message from an unsaved sender"})
            conversations = wait(lambda: api(base, "lxmf/conversations")[1]["conversations"])
            assert len(conversations) == 1
            assert conversations[0]["destination_hash"] == sender
            assert not conversations[0]["is_contact"] and conversations[0]["is_unread"]
            incoming = api(base, "lxmf-messages/conversation/" + sender)[1]["lxmf_messages"]
            assert incoming[0]["content"] == "Signed first message from an unsaved sender"
            assert api(base, "preview/unread-messages")[1]["messages"][0]["peer"] == sender
            assert api(base, "telephone/contacts/check/" + sender)[1]["is_contact"] is False
            token = api(base, "auth/csrf")[1]["csrf_token"]
            assert api(base, "lxmf/conversations/" + sender + "/mark-as-read", body={}, token=token)[0] == 200
            assert not api(base, "preview/unread-messages")[1]["messages"]
            status, _ = api(base, "lxmf-messages/send", body={"lxmf_message": {"destination_hash": sender, "content": "Reply without saving a contact"}}, token=token)
            assert status == 200
            wait(lambda: any(row["content"] == "Echo: Reply without saving a contact" for row in api(base, "lxmf-messages/conversation/" + sender)[1]["lxmf_messages"]))
        ready = app / "second.url"
        start(stack, run_server, app, ready, settings)
        wait(ready.exists)
        base = backend(ready)
        assert api(base, "telephone/contacts")[1]["contacts"] == []
        rows = api(base, "lxmf/conversations")[1]["conversations"]
        assert len(rows) == 1 and not rows[0]["is_contact"]
        assert rows[0]["destination_hash"] == sender and rows[0]["is_unread"]
        assert len(api(base, "lxmf-messages/conversation/" + sender)[1]["lxmf_messages"]) == 3
        token = api(base, "auth/csrf")[1]["csrf_token"]
        assert api(base, "lxmf/conversations/bulk-mark-as-read", body={"mark_all": True}, token=token)[0] == 200
        assert not api(base, "preview/unread-messages")[1]["messages"]
