"""Private Reticulum TCP hub and LXMF echo peer for simulator smoke tests."""
import json
from pathlib import Path
import socket
import sys
import threading

import LXMF
import RNS


def main(folder):
    folder.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    (folder / "config").write_text(
        "[reticulum]\nshare_instance = No\nenable_transport = Yes\n"
        "[interfaces]\n[[Simulator Test]]\ntype = TCPServerInterface\nenabled = Yes\n"
        f"listen_ip = 127.0.0.1\nlisten_port = {port}\n"
    )
    RNS.Reticulum(configdir=str(folder), loglevel=1)
    identity = RNS.Identity()
    router = LXMF.LXMRouter(identity=identity, storagepath=str(folder / "lxmf"), autopeer=False)
    destination = router.register_delivery_identity(identity, display_name="Simulator echo peer", stamp_cost=0)

    def echo(message):
        if not message.signature_validated:
            return
        reply_to = RNS.Destination(message.source.identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
        reply = LXMF.LXMessage(reply_to, destination, "Echo: " + message.content_as_string(), desired_method=LXMF.LXMessage.DIRECT)
        router.handle_outbound(reply)

    router.register_delivery_callback(echo)
    destination.announce()
    pending = folder / "peer.tmp"
    pending.write_text(json.dumps({"host": "127.0.0.1", "port": port, "address": destination.hash.hex()}))
    pending.replace(folder / "peer.json")
    threading.Event().wait()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
