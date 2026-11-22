"""Opt-in LXMF mailbox receiving, owned by the app's asyncio loop.

This polls only while the runtime is executing. It is not an iOS background
wake mechanism. Outbound fallback requires its own explicit saved opt-in.
"""
import re
import time


def normalize_address(value):
    if not isinstance(value, str):
        raise ValueError("Enter a 32-character LXMF propagation node address")
    value = value.strip().lower()
    if value and not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Enter a 32-character LXMF propagation node address")
    return value


class OfflineMailbox:
    def __init__(self, database, router, identity, session, *, clock=time.monotonic, wall=time.time):
        self.database, self.router, self.identity, self.session = database, router, identity, session
        self.clock, self.wall = clock, wall
        with database:
            database.execute("CREATE TABLE IF NOT EXISTS next_mailbox (id INTEGER PRIMARY KEY CHECK(id=1), address TEXT NOT NULL)")
        columns = {row[1] for row in database.execute("PRAGMA table_info(next_mailbox)")}
        if "send_fallback" not in columns:
            with database:
                database.execute("ALTER TABLE next_mailbox ADD COLUMN send_fallback INTEGER NOT NULL DEFAULT 0")
        row = database.execute("SELECT address, send_fallback FROM next_mailbox WHERE id=1").fetchone()
        self.address = normalize_address(row[0]) if row else ""
        self.send_fallback = bool(row[1]) if row else False
        self.current_session = None
        self.next_check = 0
        self.started = None
        self.last_checked_at = None
        self.error = None
        self.closed = False

    def configure(self, payload):
        if not isinstance(payload, dict) or "address" not in payload or set(payload) - {"address", "send_fallback"}:
            raise ValueError("Choose an LXMF mailbox address, or leave it blank to turn it off")
        address = normalize_address(payload["address"])
        fallback = payload.get("send_fallback", self.send_fallback if address else False)
        if type(fallback) is not bool:
            raise ValueError("Choose whether to use the mailbox for failed sends")
        if fallback and not address:
            raise ValueError("Choose a mailbox before enabling failed-send fallback")
        if self.closed:
            raise RuntimeError("Mailbox is closed")
        if address != self.address or fallback != self.send_fallback:
            # Commit first: a failed settings save must not silently change the
            # selected relay or cancel the existing download.
            with self.database:
                self.database.execute("INSERT INTO next_mailbox (id, address, send_fallback) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET address=excluded.address, send_fallback=excluded.send_fallback", (address, int(fallback)))
            self.router.cancel_propagation_node_requests()
            self.address = address
            self.send_fallback = fallback
            self.current_session = None
            self.started = None
            self.next_check = 0
            self.error = None
            self.last_checked_at = None
        return self.snapshot()

    def snapshot(self):
        phase = self.router.propagation_transfer_state
        active = self.router.PR_IDLE < phase < self.router.PR_COMPLETE
        status = ("off" if not self.address else "failed" if self.error else
                  "syncing" if active else "complete" if self.last_checked_at else "waiting")
        return dict(address=self.address, send_fallback=self.send_fallback, status=status, last_checked_at=self.last_checked_at,
                    error=self.error, polling_interval_seconds=300)

    def outbound_node(self):
        if not self.closed and self.address and self.send_fallback:
            return bytes.fromhex(self.address)
        return None

    def tick(self, *, force=False):
        if self.closed or not self.address:
            return self.snapshot()
        now, session = self.clock(), self.session()
        if session != self.current_session:
            self.router.cancel_propagation_node_requests()
            self.current_session, self.started, self.next_check = session, None, 0
        if session is None:
            return self.snapshot()
        phase = self.router.propagation_transfer_state
        if self.started is not None:
            if phase == self.router.PR_COMPLETE:
                self.last_checked_at = int(self.wall())
                self.error = None
                self.started = None
                self.next_check = now + 300
            elif phase > self.router.PR_COMPLETE or now - self.started >= 120:
                self.router.cancel_propagation_node_requests()
                self.started = None
                self.error = "Mailbox check did not finish. It will retry."
                self.next_check = now + 60
            else:
                return self.snapshot()
        if not force and now < self.next_check:
            return self.snapshot()
        try:
            self.router.set_outbound_propagation_node(bytes.fromhex(self.address))
            self.router.request_messages_from_propagation_node(self.identity, max_messages=50)
            self.started, self.error = now, None
        except Exception:
            self.router.cancel_propagation_node_requests()
            self.started = None
            self.error = "Could not start the mailbox check. It will retry."
            self.next_check = now + 60
        return self.snapshot()

    def close(self):
        self.closed = True
        if self.address:
            self.router.cancel_propagation_node_requests()
