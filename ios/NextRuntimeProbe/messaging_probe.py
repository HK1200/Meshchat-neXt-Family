"""Direct LXMF transport for the iOS Messages preview."""

import re
import time

import LXMF
import RNS

from tcp_peers import TCPPeers, normalize_peers
from discovery import ClientDiscovery
from rnode_settings import RNodeSettings


def reply_fields_for(hash_hex, quote):
    return {
        LXMF.FIELD_REPLY_TO: bytes.fromhex(hash_hex),
        LXMF.FIELD_REPLY_QUOTE: quote[:1024].encode("utf-8"),
    }


def decode_reply_fields(fields):
    if not isinstance(fields, dict):
        return None, {}
    reply = fields.get(LXMF.FIELD_REPLY_TO)
    if not isinstance(reply, bytes) or len(reply) != 32:
        return None, {}
    quote = fields.get(LXMF.FIELD_REPLY_QUOTE)
    if not isinstance(quote, bytes):
        return reply.hex(), {}
    return reply.hex(), {"reply_quoted_content": quote.decode("utf-8", errors="replace")[:1024]}


class MessagingProbe:
    def __init__(self, peer, workspace, on_receive=None, *, device=False):
        normalize_peers(peer, device=device)
        raw_address = peer.get("address", "")
        if not isinstance(raw_address, str) or (raw_address and not re.fullmatch(r"[a-fA-F0-9]{32}", raw_address)):
            raise ValueError("Invalid LXMF contact address")
        self.address = bytes.fromhex(raw_address) if raw_address else None
        self.on_receive = on_receive
        folder = workspace / ("reticulum" if device else "reticulum-simulator")
        folder.mkdir(mode=0o700, exist_ok=True)
        (folder / "config").write_text(
            "[reticulum]\nshare_instance = No\nenable_transport = No\n"
            "[interfaces]\n",
            encoding="utf-8",
        )
        self.reticulum = RNS.Reticulum(configdir=str(folder), loglevel=1)
        identity_path = folder / "identity"
        if identity_path.exists():
            identity = RNS.Identity.from_file(str(identity_path))
            if identity is None:
                raise RuntimeError("Could not load the saved neXt identity")
        else:
            identity = RNS.Identity()
            temporary = identity_path.with_suffix(".tmp")
            if not identity.to_file(str(temporary)):
                raise RuntimeError("Could not save the neXt identity")
            temporary.chmod(0o600)
            temporary.replace(identity_path)
        self.router = LXMF.LXMRouter(
            identity=identity, storagepath=str(folder / "lxmf"), autopeer=False, delivery_limit=10_000,
        )
        self.source = self.router.register_delivery_identity(
            identity, display_name="neXt iOS" if device else "neXt simulator probe", stamp_cost=0,
        )
        self.router.register_delivery_callback(self.receive, require_propagation_delivery=True)
        self.discovery = ClientDiscovery(folder / "discovered-clients.sqlite3", self.source.hash.hex())
        RNS.Transport.register_announce_handler(self.discovery)
        self.connections = TCPPeers(self.reticulum, self.router, self.source, device=device)
        self.connections.apply(peer)
        self.rnode = RNodeSettings(workspace, self.reticulum, self.source,
                                   self.connections.retire_links, device=device)

    def close(self):
        self.rnode.close()
        self.connections.close()
        RNS.Transport.deregister_announce_handler(self.discovery)
        self.discovery.close()

    @property
    def online(self):
        return self.connections.online or self.rnode.snapshot()["runtime"]["online"]

    @property
    def last_announced_at(self):
        sent = [value for value in (self.connections.last_announced_at,
                                   self.rnode.last_announced_at) if value is not None]
        return max(sent, default=None)

    def receive(self, message):
        if self.on_receive and message.signature_validated:
            return self.on_receive(message) is True
        return False

    def compose(self, content, address, fields=None):
        deadline = time.monotonic() + 35
        next_request = 0
        while time.monotonic() < deadline:
            interface = RNS.Transport.next_hop_interface(address)
            usable = bool(interface and interface in RNS.Transport.interfaces
                          and interface.online and not getattr(interface, "detached", False))
            if not usable and RNS.Transport.has_path(address):
                RNS.Transport.expire_path(address)
            if usable:
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
        return LXMF.LXMessage(
            destination, self.source, content, fields=fields, desired_method=LXMF.LXMessage.DIRECT,
        )

    def send(self, message):
        self.router.handle_outbound(message)
