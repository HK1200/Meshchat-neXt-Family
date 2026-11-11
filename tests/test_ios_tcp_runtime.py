"""Exercise the first iOS runtime mode on an isolated local Reticulum network."""
from contextlib import ExitStack, suppress
import ctypes.util
import importlib.util
import json
import math
import multiprocessing
import os
import platform
import runpy
from pathlib import Path
import socket
import struct
import sys
import threading
import time

import pytest


pytestmark = pytest.mark.skipif(importlib.util.find_spec("RNS") is None, reason="Requires Reticulum")
PUBLIC_PEERS = [
    pytest.param(False, id="loopback"),
    pytest.param(True, id="rmap", marks=pytest.mark.skipif(
        os.getenv("FAMILY_TEST_RMAP") != "1", reason="Opt-in public peer test"
    )),
]


def run_hub(folder, port, pipe):
    import RNS

    folder.mkdir()
    (folder / "config").write_text(
        "[reticulum]\nshare_instance = No\nenable_transport = Yes\n"
        "[interfaces]\n[[Local Hub]]\ntype = TCPServerInterface\nenabled = Yes\n"
        f"listen_ip = 127.0.0.1\nlisten_port = {port}\n"
    )
    RNS.Reticulum(configdir=str(folder), loglevel=1)
    pipe.send(True)
    pipe.recv()


def run_room_hub(folder, port, pipe):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, os.environ.get("FAMILY_IOS_TCP_TEST_RUNTIME") or str(root / "app/src/main/python"))
    import RNS
    from meshchatnext.src.backend.rrc.server import RRCServerManager

    folder.mkdir()
    (folder / "config").write_text(
        "[reticulum]\nshare_instance = No\nenable_transport = Yes\n"
        "[interfaces]\n[[Local Room Hub]]\ntype = TCPServerInterface\nenabled = Yes\n"
        f"listen_ip = 127.0.0.1\nlisten_port = {port}\n"
    )
    RNS.Reticulum(configdir=str(folder), loglevel=1)
    manager = RRCServerManager(str(folder))
    hub = manager.create_hub(name="Family test room hub")
    hub.rooms.register_room("family-test", key="private room test key")
    pipe.send(hub.dest_hash.hex())
    pipe.recv()


def run_family(folder, pipe):
    staged = os.environ.get("FAMILY_IOS_TCP_TEST_RUNTIME")
    source = staged or Path(__file__).resolve().parents[1] / "app/src/main/python"
    sys.path.insert(0, str(source))
    native_crypto = os.getenv("FAMILY_IOS_TEST_NATIVE_CRYPTO") == "1"
    if staged and native_crypto:
        class WithoutCBORX:
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "cborx":
                    raise ModuleNotFoundError("Use the iOS CBOR implementation", name=fullname)

        sys.meta_path.insert(0, WithoutCBORX())
    if staged and not native_crypto:
        class WithoutNativeModules:
            def find_spec(self, fullname, path=None, target=None):
                if fullname.partition(".")[0] in {"cryptography", "java", "serial"} or fullname == "multiprocessing.connection":
                    raise ModuleNotFoundError(fullname)

        sys.meta_path.insert(0, WithoutNativeModules())
        # Keep the host loader and OS information while exercising LXMF's iOS path.
        platform.uname()
        sys.platform = "ios"
    import family_backend
    if staged and not native_crypto:
        import RNS
        from LXMF import LXStamper

        assert RNS.Cryptography.Provider.backend() == "internal"
        assert LXStamper.IS_IOS
    radio_port = os.getenv("FAMILY_IOS_TEST_RNODE_PORT")
    if radio_port:
        from RNS.Interfaces.RNodeInterface import TCPConnection

        TCPConnection.TARGET_PORT = int(radio_port)
    voice_enabled = os.getenv("FAMILY_IOS_TEST_VOICE") == "1"
    family_backend.initialize(folder, tcp_only=True, ios_voice=voice_enabled)
    try:
        while True:
            action, payload = pipe.recv()
            if voice_enabled and action == "test_voice_pcm":
                call_id = payload["callId"]
                family_backend.voice_push(call_id, bytes.fromhex(payload["pcm"]))
                pipe.send({"ok": True, "output": family_backend.voice_pull(call_id).hex()})
            else:
                pipe.send(json.loads(family_backend.request(json.dumps({"action": action, "payload": payload}))))
    except EOFError:
        pass


def start_process(stack, target, *args):
    context = multiprocessing.get_context("spawn")
    pipe, worker = context.Pipe()
    process = context.Process(target=target, args=(*args, worker))
    process.start()
    worker.close()

    def stop():
        pipe.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
        process.close()

    stack.callback(stop)
    return pipe


def request(pipe, action, *, succeeds=True, **payload):
    pipe.send((action, payload))
    assert pipe.poll(8), f"No response to {action}"
    result = pipe.recv()
    assert result["ok"] is succeeds, result
    return result


def wait_status(pipe, condition, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = request(pipe, "status")
        if condition(status):
            return status
        time.sleep(0.2)
    rows = [row["status"] for messages in status["messages"].values() for row in messages]
    pytest.fail(f"Status timed out. Backend error {status['error']!r}, message statuses {rows}")


@pytest.mark.parametrize("public_peer", PUBLIC_PEERS)
def test_tcp_runtime_delivers_only_into_approved_conversations(tmp_path, public_peer):
    with ExitStack() as stack:
        if public_peer:
            host, port = "rmap.world", 4242
        else:
            host = "127.0.0.1"
            with socket.socket() as sock:
                sock.bind((host, 0))
                port = sock.getsockname()[1]
            hub = start_process(stack, run_hub, tmp_path / "hub", port)
            assert hub.poll(8) and hub.recv()
        families = [start_process(stack, run_family, tmp_path / name) for name in ("a", "b")]

        tokens, addresses = [], []
        for pipe in families:
            assert not request(pipe, "status")["setupComplete"]
            password = "local test guardian password"
            request(pipe, "setup", password=password, confirmation=password, reticulumEnabled=False)
            request(pipe, "rnode", succeeds=False)
            token = request(pipe, "unlock", password=password)["token"]
            if public_peer:
                request(pipe, "device_name", token=token, name="Family TCP test")
            request(pipe, "peer", token=token, host=host, port=port, enabled=True)
            status = wait_status(pipe, lambda s: s["ready"] and s["tcpOnline"])
            assert not status["rnodeRuntime"]["online"] and not status["meshcore"]
            tokens.append(token)
            addresses.append(status["address"])

        def approve(index):
            pipe = families[index]
            contact = {"id": 1, "name": "Other Family", "addresses": {"lxmf": addresses[1 - index]}}
            request(pipe, "contacts", succeeds=False, contacts=[contact])
            request(pipe, "contacts", token=tokens[index], contacts=[contact])

        def send(index, text):
            pipe = families[index]
            request(pipe, "send", contactId=1, text=text, method="auto")
            wait_status(pipe, lambda s: any(
                row["text"] == text and row["status"] == "Delivered"
                for row in s["messages"]["1"]
            ))

        def wait_incoming(index, text):
            wait_status(families[index], lambda s: any(
                row["incoming"] and row["text"] == text for row in s["messages"]["1"]
            ))

        request(families[0], "send", succeeds=False, contactId=1, text="Unapproved")
        approve(0)
        send(0, "Before recipient approval")
        assert request(families[1], "status")["messages"] == {}
        approve(1)
        send(0, "Approved outbound")
        wait_incoming(1, "Approved outbound")
        send(1, "Approved reply")
        wait_incoming(0, "Approved reply")
        assert not any(
            row["text"] == "Before recipient approval"
            for row in request(families[1], "status")["messages"]["1"]
        )

        if not public_peer:
            request(families[0], "location_policy", succeeds=False, mapEnabled=True, userControls=False, contactIds=[1])
            for pipe, token in zip(families, tokens):
                request(pipe, "location_policy", token=token, mapEnabled=True, userControls=False, contactIds=[1])
            request(families[0], "location_start", succeeds=False, duration="15")
            request(families[0], "location_start", token=tokens[0], duration="ongoing")
            request(families[0], "location_sample", fix={"latitude": 48.75, "longitude": -122.48, "accuracy": 10})
            received = wait_status(families[1], lambda s: "1" in s["location"]["locations"])
            assert received["location"]["locations"]["1"]["latitude"] == 48.75
            assert all(row["text"].strip() for row in received["messages"]["1"])
            request(families[0], "location_suspend")
            location = request(families[0], "status")["location"]
            assert location["duration"] == "ongoing" and not location["hasFreshFix"]
            request(families[0], "location_stop", token=tokens[0])
            previous = request(families[0], "status")["tcpSession"]
            request(families[0], "tcp_network_changed")
            restarted = wait_status(families[0], lambda s: s["tcpSession"] and s["tcpSession"] != previous)
            assert restarted["address"] == addresses[0]
            send(0, "After network change")
            wait_incoming(1, "After network change")


def run_simulator_peer(folder, public_peer, _pipe):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, os.environ.get("FAMILY_IOS_TCP_TEST_RUNTIME") or str(root / "app/src/main/python"))
    runpy.run_path(str(root / "ios/simulator-peer.py"))["main"](folder, public_peer, drop_test=not public_peer)


@pytest.mark.parametrize("public_peer", PUBLIC_PEERS)
def test_simulator_echo_fixture(tmp_path, public_peer):
    with ExitStack() as stack:
        folder = tmp_path / "echo"
        start_process(stack, run_simulator_peer, folder, public_peer)
        fixture = folder / "peer.json"
        deadline = time.monotonic() + 30
        while not fixture.exists():
            assert time.monotonic() < deadline, "Simulator echo peer did not publish its manifest"
            time.sleep(0.2)
        peer = json.loads(fixture.read_text())

        client = start_process(stack, run_family, tmp_path / "client")
        password = "local test guardian password"
        request(client, "setup", password=password, confirmation=password, reticulumEnabled=False)
        token = request(client, "unlock", password=password)["token"]
        request(client, "device_name", token=token, name="Family iOS simulator test")
        request(client, "peer", token=token, host=peer["host"], port=peer["port"], enabled=True)
        request(client, "contacts", token=token, contacts=[
            {"id": 1, "name": "Echo peer", "addresses": {"lxmf": peer["address"]}}
        ])
        initial = wait_status(client, lambda s: s["tcpOnline"])["tcpSession"]

        def round_trip(text):
            request(client, "send", contactId=1, text=text, method="auto")

            def complete(status):
                rows = status["messages"]["1"]
                return (
                    any(row["incoming"] and row["text"] == "Echo: " + text for row in rows)
                    and any(not row["incoming"] and row["text"] == text and row["status"] == "Delivered" for row in rows)
                )

            wait_status(client, complete, timeout=90)

        round_trip(peer["message"])
        if not public_peer:
            after = wait_status(client, lambda s: s["tcpSession"] and s["tcpSession"] != initial)["tcpSession"]
            assert after.split(":")[0] == initial.split(":")[0]
            round_trip(peer["reconnectMessage"])


def run_mailbox(folder, port, pipe):
    import LXMF
    import RNS

    folder.mkdir()
    (folder / "config").write_text(
        "[reticulum]\nshare_instance = No\nenable_transport = Yes\n"
        "[interfaces]\n[[Private mailbox]]\ntype = TCPServerInterface\nenabled = Yes\n"
        f"listen_ip = 127.0.0.1\nlisten_port = {port}\n"
    )
    RNS.Reticulum(configdir=str(folder), loglevel=2)
    router = LXMF.LXMRouter(storagepath=str(folder), autopeer=False, propagation_cost=13)
    router.enable_propagation()
    pipe.send(router.propagation_destination.hash.hex())
    pipe.recv()


def run_mailbox_sender(folder, port, mailbox, pipe):
    import LXMF
    import RNS

    folder.mkdir()
    (folder / "config").write_text(
        "[reticulum]\nshare_instance = No\nenable_transport = No\n"
        "[interfaces]\n[[Mailbox client]]\ntype = TCPClientInterface\nenabled = Yes\n"
        f"target_host = 127.0.0.1\ntarget_port = {port}\n"
    )
    RNS.Reticulum(configdir=str(folder), loglevel=2)
    approved_identity, other_identity = RNS.Identity(), RNS.Identity()
    router = LXMF.LXMRouter(identity=approved_identity, storagepath=str(folder), autopeer=False)
    approved = router.register_delivery_identity(approved_identity, stamp_cost=0)
    other = RNS.Destination(other_identity, RNS.Destination.IN, RNS.Destination.SINGLE, "lxmf", "delivery")
    pipe.send((approved.hash.hex(), approved_identity.get_public_key().hex()))
    recipient_key = pipe.recv()
    recipient = RNS.Identity(create_keys=False)
    recipient.load_public_key(recipient_key)
    destination = RNS.Destination(recipient, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")

    mailbox_hash = bytes.fromhex(mailbox)
    router.set_outbound_propagation_node(mailbox_hash)
    RNS.Transport.request_path(mailbox_hash)
    deadline = time.monotonic() + 20
    while not RNS.Transport.has_path(mailbox_hash):
        assert time.monotonic() < deadline
        time.sleep(0.2)

    messages = [
        LXMF.LXMessage(destination, approved, "Approved while offline", desired_method=LXMF.LXMessage.PROPAGATED),
        LXMF.LXMessage(destination, other, "Unapproved while offline", desired_method=LXMF.LXMessage.PROPAGATED),
    ]
    for message in messages:
        router.handle_outbound(message)
    deadline = time.monotonic() + 50
    while any(message.state != LXMF.LXMessage.SENT for message in messages):
        assert time.monotonic() < deadline, [message.state for message in messages]
        time.sleep(0.2)
    pipe.send(True)
    pipe.recv()


def test_mailbox_recovers_only_approved_messages_after_restart(tmp_path, monkeypatch):
    import RNS

    # The relay and sender use the same packaged LXMF as the Family client.
    root = Path(__file__).resolve().parents[1]
    source = os.environ.get("FAMILY_IOS_TCP_TEST_RUNTIME") or str(root / "app/src/main/python")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, (source, os.environ.get("PYTHONPATH")))))
    monkeypatch.syspath_prepend(source)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with ExitStack() as stack:
        relay = start_process(stack, run_mailbox, tmp_path / "relay", port)
        assert relay.poll(10)
        mailbox = relay.recv()
        sender = start_process(stack, run_mailbox_sender, tmp_path / "sender", port, mailbox)
        assert sender.poll(10)
        approved, public_key = sender.recv()
        folder = tmp_path / "family"
        with ExitStack() as running_recipient:
            client = start_process(running_recipient, run_family, folder)
            password = "local test guardian password"
            request(client, "setup", password=password, confirmation=password, reticulumEnabled=False)
            token = request(client, "unlock", password=password)["token"]
            request(client, "mailbox_config", succeeds=False, address=mailbox)
            request(client, "mailbox_config", succeeds=False, token=token, address="invalid")
            request(client, "mailbox_config", token=token, address=mailbox)
            request(client, "peer", token=token, host="127.0.0.1", port=port, enabled=True)
            wait_status(client, lambda s: s["ready"] and s["tcpOnline"])
            request(client, "contacts", token=token, contacts=[{
                "id": 1, "name": "Approved sender", "addresses": {"lxmf": approved}, "identityPublicKey": public_key
            }])
            recipient_identity = RNS.Identity.from_file(str(folder / "identity"))
        sender.send(recipient_identity.get_public_key())
        assert sender.poll(55) and sender.recv()

        client = start_process(stack, run_family, folder)
        state = wait_status(client, lambda s: s["ready"] and s["tcpOnline"])
        assert state["mailbox"]["address"] == mailbox
        assert state["messages"]["1"] == []
        request(client, "mailbox_sync")
        state = wait_status(client, lambda s: s["mailbox"]["status"] == "complete")
        assert [row["text"] for row in state["messages"]["1"]] == ["Approved while offline"]
        request(client, "mailbox_sync")
        state = wait_status(client, lambda s: s["mailbox"]["status"] == "complete")
        assert len(state["messages"]["1"]) == 1


def test_tcp_runtime_rejoins_saved_password_room(tmp_path, monkeypatch):
    if importlib.util.find_spec("cryptography") is None or importlib.util.find_spec("cborx") is None:
        pytest.skip("Requires Relay Chat host dependencies")
    monkeypatch.setenv("FAMILY_IOS_TEST_NATIVE_CRYPTO", "1")
    password = "local test guardian password"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with ExitStack() as stack:
        server = start_process(stack, run_room_hub, tmp_path / "room-hub", port)
        assert server.poll(12), "Room hub did not start"
        hub_hash = server.recv()
        clients = [start_process(stack, run_family, tmp_path / name) for name in ("first", "second")]
        for client in clients:
            request(client, "setup", password=password, confirmation=password, reticulumEnabled=False)
            token = request(client, "unlock", password=password)["token"]
            request(client, "peer", token=token, host="127.0.0.1", port=port, enabled=True)
            ready = wait_status(client, lambda state: state["tcpOnline"])
            assert not ready["roomError"], ready["roomError"]
            approval = {"name": "Test room", "key": hub_hash, "channel": "family-test", "service": "reticulum"}
            card = json.dumps({"format": "next-family-room", "version": 1, "service": "reticulum",
                               "hubHash": hub_hash, "room": "family-test", "name": "Test room"})
            request(client, "qr_parse", succeeds=False, target="room", text=card)
            assert request(client, "qr_parse", token=token, target="room", text=card)["roomCard"] == approval
            request(client, "room_save", succeeds=False, room=approval, approved=True)
            request(client, "room_save", token=token, room=approval, approved=True, password="private room test key")
            joined = wait_status(client, lambda state: state["roomRuntime"].get("1", {}).get("joined"), timeout=40)
            assert joined["rooms"][0]["hasPassword"]
        request(clients[0], "room_close")
        previous = request(clients[0], "status")["tcpSession"]
        request(clients[0], "tcp_network_changed")
        wait_status(clients[0], lambda state: state["tcpSession"] not in (None, previous)
                    and state["roomRuntime"]["1"]["joined"], timeout=50)
        request(clients[0], "room_post", roomId=1, text="Hello from the approved room")
        wait_status(clients[1], lambda state: any(
            row["text"] == "Hello from the approved room" for row in state["roomRuntime"]["1"]["messages"]
        ))


def test_wifi_rnode_negotiates_configuration_and_battery(tmp_path, monkeypatch):
    if not os.getenv("FAMILY_IOS_TCP_TEST_RUNTIME"):
        pytest.skip("Requires the staged iOS TCP-only RNode driver")
    with ExitStack() as stack:
        listener = stack.enter_context(socket.socket())
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(10)
        monkeypatch.setenv("FAMILY_IOS_TEST_RNODE_PORT", str(listener.getsockname()[1]))

        def serve():
            with listener.accept()[0] as connection, suppress(ConnectionResetError, BrokenPipeError):
                pending = b""
                while data := connection.recv(4096):
                    pending += data
                    frames = pending.split(b"\xc0")
                    pending = frames.pop()
                    for frame in filter(None, frames):
                        command = frame[0]
                        reply = {0x08: b"\x08\x46", 0x50: b"\x50\x01\x50", 0x48: b"\x48\x80",
                                 0x49: b"\x49\x01"}.get(command)
                        if command in (1, 2, 3, 4, 5, 6, 11, 12):
                            reply = frame
                        if reply is not None:
                            connection.sendall(b"\xc0" + reply + b"\xc0")
                        if command == 6 and frame[1:] == b"\x01":
                            connection.sendall(b"\xc0\x27\x01\x4b\xc0")

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        client = start_process(stack, run_family, tmp_path / "rnode-client")
        password = "local test guardian password"
        request(client, "setup", password=password, confirmation=password, reticulumEnabled=False)
        token = request(client, "unlock", password=password)["token"]
        wait_status(client, lambda state: state["ready"])
        config = {"enabled": True, "transport": "tcp", "endpoint": "127.0.0.1", "frequency": "914.875",
                  "bandwidth": "125", "sf": 8, "cr": 7, "power": 17}
        request(client, "rnode", config=config, succeeds=False)
        request(client, "rnode", token=token, config=config)
        status = wait_status(client, lambda state: state["rnodeRuntime"]["online"])
        assert status["online"] and not status["tcpOnline"]
        assert status["rnodeRuntime"]["battery"] == {"percent": 75, "state": "discharging"}
        request(client, "rnode", token=token, config=None)
        assert not request(client, "status")["rnodeRuntime"]["online"]
    server.join(timeout=5)


def test_ios_voice_policy_and_remote_hangup(tmp_path, monkeypatch):
    if importlib.util.find_spec("LXST") is None:
        pytest.skip("Requires LXST and the host voice dependencies")
    monkeypatch.setenv("FAMILY_IOS_TEST_VOICE", "1")
    monkeypatch.setenv("FAMILY_IOS_TEST_NATIVE_CRYPTO", "1")
    password = "local test guardian password"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with ExitStack() as stack:
        hub = start_process(stack, run_hub, tmp_path / "voice-hub", port)
        assert hub.poll(8) and hub.recv()
        clients = [start_process(stack, run_family, tmp_path / name) for name in ("caller", "receiver")]
        tokens, addresses = [], []
        for client in clients:
            request(client, "setup", password=password, confirmation=password, reticulumEnabled=False)
            token = request(client, "unlock", password=password)["token"]
            request(client, "peer", token=token, host="127.0.0.1", port=port, enabled=True)
            wait_status(client, lambda state: state["tcpOnline"])
            request(client, "voice_config", succeeds=False, enabled=True)
            request(client, "voice_config", token=token, enabled=True)
            request(client, "voice_presence", foreground=True)
            voice = wait_status(client, lambda state: state["voice"]["ready"])["voice"]
            tokens.append(token)
            addresses.append(voice["address"])
        request(clients[0], "voice_call", succeeds=False, contactId=1)
        for index, client in enumerate(clients):
            contact = {"id": 1, "name": "Approved voice peer", "addresses": {"lxst": addresses[1-index]}}
            request(client, "contacts", token=tokens[index], contacts=[contact])
        request(clients[0], "voice_call", contactId=1)
        deadline = time.monotonic() + 35
        history = set()
        while time.monotonic() < deadline:
            caller = request(clients[0], "status")["voice"]
            incoming = request(clients[1], "status")["voice"]
            history.add((caller["call_state"], incoming["call_state"], caller["error"], incoming["error"]))
            if incoming["call_state"] == "incoming":
                break
            time.sleep(.2)
        assert incoming["call_state"] == "incoming", history
        assert incoming["caller_name"] == "Approved voice peer"
        request(clients[1], "voice_answer", callId=incoming["call_id"])
        connected = [wait_status(client, lambda state: state["voice"]["call_state"] == "connected")["voice"]
                     for client in clients]
        outputs = [False, False]
        for sequence in range(75):
            frame = struct.pack("<960h", *(int(5000 * math.sin((sequence * 960 + sample) * .0576))
                                           for sample in range(960))).hex()
            for index, client in enumerate(clients):
                result = request(client, "test_voice_pcm", callId=connected[index]["call_id"], pcm=frame)
                outputs[index] |= any(bytes.fromhex(result["output"]))
            if all(outputs):
                break
            time.sleep(.02)
        assert all(outputs), "Both approved peers must receive non-silent PCM"
        request(clients[1], "voice_presence", foreground=False)
        for client in clients:
            wait_status(client, lambda state: state["voice"]["call_state"] == "idle")
        request(clients[1], "voice_hangup", callId=incoming["call_id"])
        assert request(clients[1], "status")["voice"]["call_state"] == "idle"
