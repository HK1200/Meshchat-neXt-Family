"""Send one signed, direct LXMF message through the private simulator peer."""

import json
from pathlib import Path
import secrets
import time

import LXMF
import RNS


class MessagingProbe:
    def __init__(self, fixture, workspace, on_receive=None):
        with fixture.open(encoding="utf-8") as source:
            peer = json.load(source)
        port = peer["port"]
        if peer.get("host") != "127.0.0.1" or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("The probe requires a private loopback peer")
        self.address = bytes.fromhex(peer["address"])
        if len(self.address) != RNS.Reticulum.TRUNCATED_HASHLENGTH // 8:
            raise ValueError("Invalid echo peer address")
        self.challenge = peer["message"]
        self.on_receive = on_receive
        folder = workspace / f"reticulum-{secrets.token_hex(8)}"
        folder.mkdir(mode=0o700)
        (folder / "config").write_text(
            "[reticulum]\nshare_instance = No\nenable_transport = No\n"
            "[interfaces]\n[[Simulator Echo]]\ntype = TCPClientInterface\nenabled = Yes\n"
            f"target_host = 127.0.0.1\ntarget_port = {port}\n",
            encoding="utf-8",
        )
        self.reticulum = RNS.Reticulum(configdir=str(folder), loglevel=1)
        identity = RNS.Identity()
        self.router = LXMF.LXMRouter(
            identity=identity, storagepath=str(folder / "lxmf"), autopeer=False,
        )
        self.source = self.router.register_delivery_identity(
            identity, display_name="neXt simulator probe", stamp_cost=0,
        )
        self.router.register_delivery_callback(self.receive)

    def receive(self, message):
        if self.on_receive and message.signature_validated and message.source_hash == self.address:
            self.on_receive(message)

    def compose(self, content):
        deadline = time.monotonic() + 35
        next_request = 0
        while time.monotonic() < deadline:
            if RNS.Transport.has_path(self.address):
                identity = RNS.Identity.recall(self.address)
                if identity:
                    break
            now = time.monotonic()
            if now >= next_request:
                RNS.Transport.request_path(self.address)
                next_request = now + 3
            time.sleep(0.2)
        else:
            raise TimeoutError("Could not find the private Reticulum peer")
        destination = RNS.Destination(
            identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery",
        )
        return LXMF.LXMessage(destination, self.source, content, desired_method=LXMF.LXMessage.DIRECT)

    def send(self, message):
        self.source.announce()
        self.router.handle_outbound(message)
