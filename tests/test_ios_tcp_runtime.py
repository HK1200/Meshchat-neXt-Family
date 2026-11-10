"""Exercise the first iOS runtime mode on an isolated local Reticulum network."""
from contextlib import ExitStack
import ctypes.util
import importlib.util
import json
import multiprocessing
import os
import platform
import runpy
from pathlib import Path
import socket
import sys
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


def run_family(folder, pipe):
    staged = os.environ.get("FAMILY_IOS_TCP_TEST_RUNTIME")
    source = staged or Path(__file__).resolve().parents[1] / "app/src/main/python"
    sys.path.insert(0, str(source))
    if staged:
        class WithoutNativeModules:
            def find_spec(self, fullname, path=None, target=None):
                if fullname.partition(".")[0] in {"cryptography", "java", "serial"} or fullname == "multiprocessing.connection":
                    raise ModuleNotFoundError(fullname)

        sys.meta_path.insert(0, WithoutNativeModules())
        # Keep the host loader and OS information while exercising LXMF's iOS path.
        platform.uname()
        sys.platform = "ios"
    import family_backend
    if staged:
        import RNS
        from LXMF import LXStamper

        assert RNS.Cryptography.Provider.backend() == "internal"
        assert LXStamper.IS_IOS
    family_backend.initialize(folder, tcp_only=True)
    try:
        while True:
            action, payload = pipe.recv()
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


def run_simulator_peer(folder, public_peer, _pipe):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, os.environ.get("FAMILY_IOS_TCP_TEST_RUNTIME") or str(root / "app/src/main/python"))
    runpy.run_path(str(root / "ios/simulator-peer.py"))["main"](folder, public_peer)


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
        wait_status(client, lambda s: s["tcpOnline"])
        request(client, "send", contactId=1, text=peer["message"], method="auto")
        received = "Echo: " + peer["message"]
        def round_trip_complete(status):
            rows = status["messages"]["1"]
            return (
                any(row["incoming"] and row["text"] == received for row in rows)
                and any(not row["incoming"] and row["status"] == "Delivered" for row in rows)
            )

        wait_status(client, round_trip_complete, timeout=90)


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
