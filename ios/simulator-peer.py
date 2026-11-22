"""Disposable LXMF echo peer for local and public simulator smoke tests."""
import json
from pathlib import Path
import secrets
import socket
import time
import sys
import threading

import LXMF
import RNS


def main(folder, public, drop_test=False, attachment_echo=False, location_echo=False):
    if public and location_echo:
        raise ValueError("Synthetic location fixtures must stay on loopback")
    if public and attachment_echo:
        raise ValueError("Attachment fixtures must stay on loopback")
    folder.mkdir()
    config = "[reticulum]\nshare_instance = No\n"
    if public:
        host = "rmap.world"
        for port in (4343, 4242):
            try:
                with socket.create_connection((host, port), timeout=5):
                    break
            except OSError as error:
                print(f"{host}:{port} unavailable: {error}", flush=True)
        else:
            raise RuntimeError(f"Neither published RMAP TCP port is reachable on {host}")
        config += (
            "enable_transport = No\n[interfaces]\n[[Public Test Peer]]\n"
            f"type = TCPClientInterface\nenabled = Yes\ntarget_host = {host}\ntarget_port = {port}\n"
        )
    else:
        host = "127.0.0.1"
        with socket.socket() as listener:
            listener.bind((host, 0))
            port = listener.getsockname()[1]
        config += (
            "enable_transport = Yes\n[interfaces]\n[[Simulator Test]]\n"
            f"type = TCPServerInterface\nenabled = Yes\nlisten_ip = {host}\nlisten_port = {port}\n"
        )
    (folder / "config").write_text(config)
    RNS.Reticulum(configdir=str(folder), loglevel=1)
    if public:
        deadline = time.monotonic() + 25
        while not any(interface.online for interface in RNS.Transport.interfaces):
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Could not connect the echo peer to {host}:{port}")
            time.sleep(0.2)
    identity = RNS.Identity()
    router = LXMF.LXMRouter(identity=identity, storagepath=str(folder / "lxmf"), autopeer=False)
    destination = router.register_delivery_identity(identity, display_name="Simulator echo peer", stamp_cost=0)

    challenge = "Hello from simulator " + secrets.token_hex(4)
    reconnect_message = "Hello after reconnect " + secrets.token_hex(4) if drop_test else None
    # Explicit private-only challenges for independent native history deletion.
    delete_message = "Delete proof: " + challenge if not public else None
    fresh_message = "Fresh after delete: " + challenge if not public else None
    location_receipt = "Location receipt: " + challenge if location_echo else None

    def drop_client(_):
        from RNS.Interfaces.TCPInterface import TCPServerInterface

        for listener in RNS.Transport.interfaces:
            if isinstance(listener, TCPServerInterface):
                for client in tuple(listener.spawned_interfaces):
                    if client.socket is not None:
                        try:
                            client.socket.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass

    def diagnostic(event, message):
        if not public:
            kind = {challenge: "initial", reconnect_message: "reconnect",
                    delete_message: "delete", fresh_message: "fresh"}.get(message.content_as_string(), "unknown")
            if location_echo and message.content_as_string() == "": kind = "synthetic_location"
            print(json.dumps({"event": event, "fixture": kind}), flush=True)

    def reply(message, location=False):
        deadline = time.monotonic() + 45
        next_request = 0
        while time.monotonic() < deadline:
            if RNS.Transport.has_path(message.source_hash) and RNS.Identity.recall(message.source_hash):
                verified = message if message.signature_validated else LXMF.LXMessage.unpack_from_bytes(message.packed)
                if verified.signature_validated:
                    reply_to = verified.source
                    text = verified.content_as_string()
                    if location:
                        from simulator_location_fixture import valid_synthetic_location
                        if not valid_synthetic_location(verified):
                            diagnostic("synthetic_location_rejected", message)
                            return
                        diagnostic("signed_synthetic_location_verified", message)
                    fields = None
                    if attachment_echo and not location:
                        import base64
                        fields = {LXMF.FIELD_FILE_ATTACHMENTS: [["next-test.txt", b"Private signed attachment test"]],
                                  LXMF.FIELD_IMAGE: ["png", base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=")]}
                    response = LXMF.LXMessage(
                        reply_to, destination, location_receipt if location else "Echo: " + text, fields=fields, desired_method=LXMF.LXMessage.DIRECT
                    )
                    def delivered(_):
                        diagnostic("echo_delivered", message)
                        if reconnect_message and text == challenge: drop_client(_)
                    response.register_delivery_callback(delivered)
                    response.register_failed_callback(lambda _: diagnostic("echo_failed", message))
                    router.handle_outbound(response)
                    diagnostic("echo_queued", message)
                return
            now = time.monotonic()
            if now >= next_request:
                RNS.Transport.request_path(message.source_hash)
                next_request = now + 10
            time.sleep(0.2)
        print("No return path to the simulator test client", flush=True)

    def echo(message):
        location = (location_echo and message.content_as_string() == "" and
                    isinstance(message.fields, dict) and LXMF.FIELD_TELEMETRY in message.fields)
        if not location and message.content_as_string() not in (challenge, reconnect_message, delete_message, fresh_message):
            return
        if message.signature_validated or message.unverified_reason == LXMF.LXMessage.SOURCE_UNKNOWN:
            diagnostic("message_received", message)
            threading.Thread(target=reply, args=(message, location), daemon=True).start()

    router.register_delivery_callback(echo)
    destination.announce()
    pending = folder / "peer.tmp"
    payload = {
        "host": host, "port": port, "address": destination.hash.hex(),
        "message": challenge, "reconnectMessage": reconnect_message,
        "deleteMessage": delete_message, "freshMessage": fresh_message,
    }
    if location_echo: payload["locationReceipt"] = location_receipt
    pending.write_text(json.dumps(payload))
    pending.replace(folder / "peer.json")
    threading.Event().wait()


if __name__ == "__main__":
    public = len(sys.argv) > 2 and sys.argv[2] == "rmap"
    main(Path(sys.argv[1]), public, drop_test=not public and sys.argv[2:3] != ["local-no-drop"], attachment_echo=sys.argv[3:4] == ["attachment-echo"], location_echo=sys.argv[4:5] == ["location-echo"])
