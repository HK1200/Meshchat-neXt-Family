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


def main(folder, public):
    folder.mkdir()
    config = "[reticulum]\nshare_instance = No\n"
    if public:
        host, port = "rmap.world", 4242
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

    def reply(message):
        deadline = time.monotonic() + 45
        next_request = 0
        while time.monotonic() < deadline:
            if RNS.Transport.has_path(message.source_hash) and RNS.Identity.recall(message.source_hash):
                verified = message if message.signature_validated else LXMF.LXMessage.unpack_from_bytes(message.packed)
                if verified.signature_validated:
                    reply_to = verified.source
                    response = LXMF.LXMessage(
                        reply_to, destination, "Echo: " + challenge, desired_method=LXMF.LXMessage.DIRECT
                    )
                    response.register_failed_callback(lambda _: print("Simulator echo delivery failed", flush=True))
                    router.handle_outbound(response)
                return
            now = time.monotonic()
            if now >= next_request:
                RNS.Transport.request_path(message.source_hash)
                next_request = now + 10
            time.sleep(0.2)
        print("No return path to the simulator test client", flush=True)

    def echo(message):
        if message.content_as_string() != challenge:
            return
        if message.signature_validated or message.unverified_reason == LXMF.LXMessage.SOURCE_UNKNOWN:
            threading.Thread(target=reply, args=(message,), daemon=True).start()

    router.register_delivery_callback(echo)
    destination.announce()
    pending = folder / "peer.tmp"
    pending.write_text(json.dumps({"host": host, "port": port, "address": destination.hash.hex(), "message": challenge}))
    pending.replace(folder / "peer.json")
    threading.Event().wait()


if __name__ == "__main__":
    main(Path(sys.argv[1]), len(sys.argv) > 2 and sys.argv[2] == "rmap")
