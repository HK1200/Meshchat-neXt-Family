"""CoreBluetooth adapter for the embedded iOS runtime."""
import base64
from collections import deque
import json
import threading
import time
from types import SimpleNamespace
import uuid

_errors = {}
_error_lock = threading.RLock()


def last_error(target):
    with _error_lock:
        return _errors.get(target.upper(), "")


def request(operation, **values):
    from _family_bluetooth import request as native_request
    result = json.loads(native_request(json.dumps(dict(operation=operation, **values))))
    if result.get("error"):
        if values.get("id"):
            with _error_lock:_errors[values["id"].upper()] = str(result["error"])
        raise ConnectionError(result["error"])
    if operation == "open":
        with _error_lock:_errors.pop(values["id"].upper(), None)
    return result


def device_id(value):
    try:
        return str(uuid.UUID(value)).upper()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Select a discovered Bluetooth radio") from None


class NativeSession:
    def __init__(self, kind, target, **options):
        if kind != "ble":
            raise ValueError("iOS radio transport requires Bluetooth LE")
        self.address = device_id(target)
        self.events = deque()
        self.closed = False
        self.opened = False
        self.lock = threading.RLock()

    def start(self):
        with self.lock:
            request("open", id=self.address)
            self.opened = True

    def poll(self, milliseconds):
        deadline = time.monotonic() + milliseconds / 1000
        while True:
            with self.lock:
                if self.closed:
                    return SimpleNamespace(kind="closed", data=b"", detail="")
                if not self.events:
                    self.events.extend(request("poll", id=self.address).get("events", []))
                if self.events:
                    event = self.events.popleft()
                    if event["type"] == "error":
                        with _error_lock:_errors[self.address] = event.get("detail", "Bluetooth connection failed")
                    elif event["type"] == "ready":
                        with _error_lock:_errors.pop(self.address, None)
                    return SimpleNamespace(kind=event["type"], data=base64.b64decode(event.get("data", "")), detail=event.get("detail", ""))
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)

    def send(self, data):
        with self.lock:
            if self.closed:
                raise ConnectionError("Bluetooth session is closed")
            request("send", id=self.address, data=base64.b64encode(data).decode("ascii"))

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.opened:
                request("close", id=self.address)


class Serial:
    """Serial byte stream used by Reticulum's existing RNode KISS parser."""
    def __init__(self, port, **options):
        self.session = NativeSession("ble", port.removeprefix("familyble://"))
        self.buffer = bytearray()
        self.lock = threading.RLock()
        self.is_open = False
        self.first_write = True
        try:
            self.session.start()
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                event = self.session.poll(200)
                if event and event.kind == "ready":
                    self.is_open = True
                    return
                if event and event.kind in ("closed", "error"):
                    raise ConnectionError(event.detail or "Bluetooth disconnected")
            raise TimeoutError("Bluetooth radio connection timed out")
        except BaseException:
            self.session.close()
            raise

    def _event(self, event):
        if event is None:
            return
        if event.kind == "data":
            self.buffer.extend(event.data)
        elif event.kind in ("error", "closed"):
            self.is_open = False
            raise ConnectionError(event.detail or "Bluetooth disconnected")

    @property
    def in_waiting(self):
        with self.lock:
            self._event(self.session.poll(0))
            return len(self.buffer)

    def read(self, size=1):
        with self.lock:
            result = bytes(self.buffer[:size])
            del self.buffer[:size]
            return result

    def write(self, data):
        with self.lock:
            if not self.is_open:
                raise ConnectionError("Bluetooth radio is closed")
            self.session.send(data)
            deadline = time.monotonic() + (180 if self.first_write else 15)
            while time.monotonic() < deadline:
                event = self.session.poll(100)
                if event and event.kind == "written":
                    self.first_write = False
                    return len(data)
                self._event(event)
            self.close()
            raise TimeoutError("Bluetooth radio write timed out")

    def close(self):
        with self.lock:
            self.is_open = False
            self.session.close()
