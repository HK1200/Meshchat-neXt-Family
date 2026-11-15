"""Direct LXMF transport for the iOS Messages preview."""

import re
import secrets
import time

import LXMF
import RNS


class MessagingProbe:
    def __init__(self, peer, workspace, on_receive=None, *, device=False):
        host = peer.get("host", "")
        port = peer.get("port")
        if (not isinstance(host, str) or len(host) > 253
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", host)
                or type(port) is not int or not 1 <= port <= 65535
                or (host != "127.0.0.1" and not device)):
            raise ValueError("Invalid Reticulum TCP peer")
        self.address = bytes.fromhex(peer["address"])
        if len(self.address) != RNS.Reticulum.TRUNCATED_HASHLENGTH // 8:
            raise ValueError("Invalid LXMF contact address")
        self.on_receive = on_receive
        folder = workspace / ("reticulum" if device else f"reticulum-{secrets.token_hex(8)}")
        folder.mkdir(mode=0o700, exist_ok=device)
        (folder / "config").write_text(
            "[reticulum]\nshare_instance = No\nenable_transport = No\n"
            "[interfaces]\n[[Reticulum TCP]]\ntype = TCPClientInterface\nenabled = Yes\n"
            f"target_host = {host}\ntarget_port = {port}\n",
            encoding="utf-8",
        )
        self.reticulum = RNS.Reticulum(configdir=str(folder), loglevel=1)
        identity_path = folder / "identity"
        if device and identity_path.exists():
            identity = RNS.Identity.from_file(str(identity_path))
            if identity is None:
                raise RuntimeError("Could not load the saved neXt identity")
        else:
            identity = RNS.Identity()
            if device:
                temporary = identity_path.with_suffix(".tmp")
                if not identity.to_file(str(temporary)):
                    raise RuntimeError("Could not save the neXt identity")
                temporary.chmod(0o600)
                temporary.replace(identity_path)
        self.router = LXMF.LXMRouter(
            identity=identity, storagepath=str(folder / "lxmf"), autopeer=False,
        )
        self.source = self.router.register_delivery_identity(
            identity, display_name="neXt iOS" if device else "neXt simulator probe", stamp_cost=0,
        )
        self.router.register_delivery_callback(self.receive)

    @property
    def online(self):
        return any(interface.online for interface in RNS.Transport.interfaces)

    def receive(self, message):
        if self.on_receive and message.signature_validated:
            self.on_receive(message)

    def compose(self, content, address):
        deadline = time.monotonic() + 35
        next_request = 0
        while time.monotonic() < deadline:
            if RNS.Transport.has_path(address):
                identity = RNS.Identity.recall(address)
                if identity:
                    break
            now = time.monotonic()
            if now >= next_request:
                RNS.Transport.request_path(address)
                next_request = now + 3
            time.sleep(0.2)
        else:
            raise TimeoutError("Could not find a Reticulum path to the contact")
        destination = RNS.Destination(
            identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery",
        )
        return LXMF.LXMessage(destination, self.source, content, desired_method=LXMF.LXMessage.DIRECT)

    def send(self, message):
        self.source.announce()
        self.router.handle_outbound(message)
