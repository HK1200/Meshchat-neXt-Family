"""A bounded transport-thread handoff that acknowledges only committed inbox data."""
import asyncio
from concurrent.futures import Future
import math
import threading


class DurableInbox:
    def __init__(self, loop, commit, *, timeout=20):
        if asyncio.get_running_loop() is not loop:
            raise ValueError('Create the inbox on its running event loop')
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 0 < timeout <= 30):
            raise ValueError('Use a bounded inbox acknowledgment timeout')
        self.loop = loop
        self.commit = commit
        self.timeout = timeout
        self.owner = threading.get_ident()
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.pending = set()
        self.error = ''

    def _commit(self, row):
        try:
            accepted = self.commit(row) is True
        except Exception:
            accepted = False
        self.error = '' if accepted else 'A received message has not been saved yet.'
        return accepted

    def _execute(self, result, row):
        with self.lock:
            if self.closed.is_set():
                result.cancel()
                return
            if not result.set_running_or_notify_cancel():
                return
        result.set_result(self._commit(row))

    def receive(self, row):
        if self.closed.is_set() or self.loop.is_closed():
            return False
        if threading.get_ident() == self.owner:
            return self._commit(row)
        result = Future()
        with self.lock:
            if self.closed.is_set():
                return False
            self.pending.add(result)
        try:
            self.loop.call_soon_threadsafe(self._execute, result, row)
            return result.result(timeout=self.timeout) is True
        except Exception:
            result.cancel()
            self.error = 'A received message has not been saved yet.'
            return False
        finally:
            with self.lock:
                self.pending.discard(result)

    def close(self):
        with self.lock:
            self.closed.set()
            for result in self.pending:
                result.cancel()
            self.pending.clear()
