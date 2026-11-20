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
        router.handle_outbound(LXMF.LXMessage(target, source, "Echo: " + message.content_as_string(), desired_method=LXMF.LXMessage.DIRECT))
    router.register_delivery_callback(received)
    source.announce()
    pipe.send(source.hash.hex())
    pipe.recv()


def run_server(folder, ready, settings, pipe):
    import asyncio
    sys.path[:0] = [str(ROOT / "ios/NextRuntimeProbe"), str(ROOT / "app/src/main/python")]
    from loopback_probe import serve
    frontend = folder / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "index.html").write_text("<html>Private test</html>")
    asyncio.run(serve(ready, frontend, settings, device=True))


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


def api(base, path, *, body=None, token=None):
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = f"http://{urlsplit(base).netloc}"
    if token is not None: headers["X-CSRF-Token"] = token
    request = Request(urljoin(base, "/api/v1/" + path),
        data=json.dumps(body).encode() if body is not None else None, headers=headers)
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
        ready = app / "second.url"
        start(stack, run_server, app, ready, settings)
        wait(ready.exists)
        base = ready.read_text()
        assert (app / "reticulum/identity").read_bytes() == identity
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
