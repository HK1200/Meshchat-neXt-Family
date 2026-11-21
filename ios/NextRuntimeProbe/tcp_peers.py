"""Validated TCP peer settings and per-interface lifecycle for native neXt iOS."""

import ipaddress
import re
import threading
import time

DEFAULT_ENDPOINTS = (
    ("rmap.world", 4343), ("rmap.world", 4242),
    ("reticulum.washmesh.net", 7242), ("rns.chimesh.org", 4242),
)


def normalize_peers(settings, *, device):
    rows = settings.get("peers")
    if rows is None:
        host, port = settings.get("host", "rmap.world"), settings.get("port", 4343)
        primary = (str(host).strip().lower().rstrip("."), port)
        default_profile = device and primary in DEFAULT_ENDPOINTS[:2]
        endpoints = list(DEFAULT_ENDPOINTS) if default_profile else [(host, port)]
        if device and not default_profile:
            endpoints += [endpoint for endpoint in DEFAULT_ENDPOINTS if endpoint != primary]
        rows = [dict(id=f"peer-{index}", host=host, port=port,
                     enabled=bool(default_profile or index == 0))
                for index, (host, port) in enumerate(endpoints)]
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError("Choose at most 32 TCP peers")
    result, identifiers, endpoints = [], set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid TCP peer")
        identifier, host = row.get("id"), row.get("host")
        port, enabled = row.get("port"), row.get("enabled")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier) or identifier in identifiers:
            raise ValueError("Each TCP peer needs a unique identifier")
        if not isinstance(host, str):
            raise ValueError("Enter a hostname or IP address")
        host = host.strip().lower().rstrip(".")
        try:
            host = str(ipaddress.ip_address(host))
        except ValueError:
            if len(host) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
                raise ValueError("Enter a hostname or IP address without a URL or port")
        if type(port) is not int or not 1 <= port <= 65535 or type(enabled) is not bool:
            raise ValueError("Use a port from 1 to 65535 and an on/off setting")
        if not device and host != "127.0.0.1":
            raise ValueError("Simulator tests must use loopback peers only")
        if (host, port) in endpoints:
            raise ValueError("That TCP hostname and port are already listed")
        identifiers.add(identifier); endpoints.add((host, port))
        result.append(dict(id=identifier, host=host, port=port, enabled=enabled))
    return result


class TCPPeers:
    def __init__(self, reticulum, router, source, *, device, factory=None, clock=time.monotonic, wall_clock=time.time):
        import RNS
        from family_tcp import FamilyTCPInterface
        self.reticulum, self.router, self.source = reticulum, router, source
        self.device, self.factory, self.clock = device, factory or FamilyTCPInterface, clock
        self.wall_clock = wall_clock
        self.last_announced_at = None
        self.transport, self.link_type = RNS.Transport, RNS.Link
        self.lock = threading.RLock()
        self.rows, self.interfaces, self.pending, self.errors, self.announced = [], {}, {}, {}, {}
        self.closed = False

    def apply(self, settings):
        rows = normalize_peers(settings, device=self.device)
        with self.lock:
            if self.closed:
                raise RuntimeError("TCP connections are closed")
            wanted = {row["id"]: row for row in rows if row["enabled"]}
            previous = {row["id"]: row for row in self.rows}
            self.rows = rows
            for identifier, interface in list(self.interfaces.items()):
                if identifier not in wanted or previous.get(identifier) != wanted[identifier]:
                    self._retire(interface)
                    self.interfaces.pop(identifier, None)
                    self.announced.pop(identifier, None)
            for identifier in list(self.pending):
                if identifier not in wanted or previous.get(identifier) != wanted[identifier]:
                    self.pending.pop(identifier, None)
            self.errors = {key: value for key, value in self.errors.items() if key in wanted and previous.get(key) == wanted[key]}
            for identifier, row in wanted.items():
                if identifier not in self.interfaces and identifier not in self.pending:
                    ticket = object()
                    self.pending[identifier] = ticket
                    threading.Thread(target=self._open, args=(row, ticket), daemon=True).start()
        return self.snapshot()

    def _open(self, row, ticket):
        interface = None
        try:
            interface = self.factory(self.transport, {"name": "neXt TCP " + row["id"],
                "target_host": row["host"], "target_port": row["port"], "connect_timeout": 8})
            with self.lock:
                if self.closed or self.pending.get(row["id"]) is not ticket:
                    interface.detach()
                    return
                self.reticulum._add_interface(interface)
                self.interfaces[row["id"]] = interface
                self.errors.pop(row["id"], None)
        except Exception:
            with self.lock:
                if self.pending.get(row["id"]) is ticket:
                    self.errors[row["id"]] = "Could not configure this TCP peer"
            if interface is not None:
                with self.lock:
                    self._retire(interface)
        finally:
            with self.lock:
                if self.pending.get(row["id"]) is ticket:
                    self.pending.pop(row["id"], None)

    def retire_links(self, interface):
        for cache in (self.router.direct_links, self.router.backchannel_links):
            for address, link in cache.copy().items():
                if (link.attached_interface is interface or
                    (link.status == self.link_type.PENDING and self.transport.next_hop_interface(address) is interface)):
                    link.teardown()
                    if cache.get(address) is link:
                        cache.pop(address, None)
    def _retire(self, interface):
        self.retire_links(interface)
        interface.detach()
        if interface in self.transport.interfaces:
            self.transport.interfaces.remove(interface)

    def snapshot(self):
        with self.lock:
            result = []
            for row in self.rows:
                interface = self.interfaces.get(row["id"])
                online = bool(interface and interface.online and not interface.detached)
                status = "Disabled" if not row["enabled"] else "Connected" if online else "Connecting" if row["id"] in self.pending else self.errors.get(row["id"], "Offline · retrying")
                result.append(dict(row, online=online, status=status))
            return result

    @property
    def online(self):
        return any(row["online"] for row in self.snapshot())

    def request_announce(self):
        with self.lock:
            self.announced.clear()

    def announce_due(self, interval=3600):
        sent = 0
        with self.lock:
            for identifier, interface in self.interfaces.items():
                if not interface.online or interface.detached:
                    continue
                epoch = getattr(interface, "family_connection_epoch", 0)
                previous = self.announced.get(identifier)
                now = self.clock()
                if previous and previous[0] == epoch and (interval == 0 or now - previous[1] < interval):
                    continue
                try:
                    self.source.announce(attached_interface=interface)
                except Exception:
                    continue  # A failed announce is due again at the next poll.
                self.announced[identifier] = (epoch, now)
                self.last_announced_at = int(self.wall_clock())
                sent += 1
        return sent

    def close(self):
        with self.lock:
            self.closed = True
            self.pending.clear()
            for interface in self.interfaces.values():
                self._retire(interface)
            self.interfaces.clear()
            self.announced.clear()
