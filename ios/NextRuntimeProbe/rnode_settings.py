"""Saved, opt-in RNode transport for the native neXt preview.

Uses the same validated radio profile and Bluetooth byte stream as Family.
No radio or Bluetooth permission request is started for an unconfigured profile.
"""

import json
import threading
import time
from pathlib import Path


class RNodeSettings:
    def __init__(
        self,
        folder,
        reticulum,
        source,
        retire_links,
        *,
        device,
        factory=None,
        clock=time.monotonic,
        wall_clock=time.time,
    ):
        self.path = Path(folder) / "rnode.json"
        self.reticulum = reticulum
        self.source = source
        self.retire_links = retire_links
        self.device = device
        self.factory = factory
        self.clock = clock
        self.wall_clock = wall_clock
        self.last_announced_at = None
        self.lock = threading.RLock()
        self.radio = None
        self.config = None
        self.last_announce = None
        self.error = ""
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.config = self.normalize(raw)
                if self.config["enabled"]:
                    self._configure_radio()
            except (OSError, ValueError, TypeError):
                # A broken optional radio profile must not stop TCP messaging.
                # Keep its original bytes until the user explicitly saves a repair.
                self.config = None
                self.error = "Saved RNode settings could not be read. Review and save them again."

    def normalize(self, raw):
        if not isinstance(raw, dict) or raw.get("transport") not in ("ble", "tcp"):
            raise ValueError("Choose Bluetooth LE or Wi-Fi RNode")
        from family_radios import validate

        config = validate(raw)
        if not self.device and config["enabled"]:
            raise ValueError("Radio transmission is unavailable in simulator tests")
        return config

    def _ready(self):
        with self.lock:
            self.last_announce = None

    def _configure_radio(self):
        if self.radio is None:
            from family_radios import Radio

            factory = self.factory or Radio
            self.radio = factory(
                self.reticulum,
                on_ready=self._ready,
                on_retire=self.retire_links,
                network_only=True,
            )
        self.radio.configure(self.config)

    def apply(self, raw):
        config = self.normalize(raw)
        from family_radios import public

        with self.lock:
            if config == self.config and self.radio is not None:
                runtime = self.radio.snapshot()
                if runtime["online"] or runtime.get("connecting"):
                    return self.snapshot()
            temporary = self.path.with_suffix(".tmp")
            # Persist the public editor units; validation normalizes them on load.
            with temporary.open("w", encoding="utf-8") as stream:
                import os

                os.fchmod(stream.fileno(), 0o600)
                json.dump(public(config), stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            self.config = config
            self.error = ""
            self.last_announce = None
            if config["enabled"] or self.radio is not None:
                self._configure_radio()
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            runtime = (
                self.radio.snapshot()
                if self.radio
                else {
                    "online": False,
                    "connecting": False,
                    "error": self.error,
                    "battery": None,
                }
            )
            settings = None
            if self.config is not None:
                from family_radios import public

                settings = public(self.config)
            return {"settings": settings, "runtime": runtime}

    def request_announce(self):
        with self.lock:
            self.last_announce = None

    def announce_due(self, interval=3600):
        with self.lock:
            interface = self.radio.interface if self.radio else None
            if (
                not self.config
                or not self.config["enabled"]
                or interface is None
                or not interface.online
                or getattr(interface, "detached", False)
                or not self.radio.snapshot()["online"]
            ):
                self.last_announce = None
                return
            now = self.clock()
            if self.last_announce is not None and (interval == 0 or now - self.last_announce < interval):
                return
            try:
                self.source.announce(attached_interface=interface)
            except Exception:
                return  # Retry a failed announce; never record it as sent.
            self.last_announce = now
            self.last_announced_at = int(self.wall_clock())
            return True

    def close(self):
        with self.lock:
            if self.radio is not None:
                self.radio.configure(None)
