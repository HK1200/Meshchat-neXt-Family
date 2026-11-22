"""Explicit native location sessions independent of a conversation's web view.

No GPS request is made at construction. Native sampling is started only by an
explicit start operation. A sender must call the supplied guard immediately
before handing a location to its transport, after any pathfinding await.
"""
import asyncio
import contextlib
from dataclasses import dataclass
import json
import hashlib
import math
import time
import uuid

from family_location import location_moved, valid_fix

DURATIONS = {'15': 15 * 60, '60': 60 * 60, 'ongoing': None}
MAX_TARGETS = 16
MOVING_INTERVAL = 60
STOPPED_INTERVAL = 300


@dataclass(frozen=True)
class Session:
    until: float
    duration: str
    revision: str

    def active(self, now):
        return self.until == -1 or self.until > now


class LocationSessions:
    def __init__(self, database, catalog, native, transmit, *, clock=time.time, monotonic=time.monotonic):
        self.db, self.catalog, self.native, self.transmit = database, catalog, native, transmit
        self.clock, self.monotonic = clock, monotonic
        self.token = uuid.uuid4().hex
        self.lock = asyncio.Lock()
        self.sessions = {}
        self.workers = {}
        self._all_workers = set()
        self.sent = {}
        self.retries = {}
        self.background = False
        self.error = ''
        self.location_status = ''
        self.closed = False
        self.armed = False
        self.fix = None
        self.native_generation = None
        self.generation = 0
        self.consent_epoch = 0
        self.cancelled_requests = {}
        with database:
            database.execute('CREATE TABLE IF NOT EXISTS next_location_sessions (target TEXT PRIMARY KEY, until REAL NOT NULL, duration TEXT NOT NULL, revision TEXT NOT NULL)')
            database.execute('CREATE TABLE IF NOT EXISTS next_location_options (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        try:
            rows = database.execute('SELECT target, until, duration, revision FROM next_location_sessions').fetchall()
            if len(rows) > MAX_TARGETS: raise ValueError('Too many saved recipients')
            for target, until, duration, revision in rows:
                self._target_key(target)
                if duration not in DURATIONS or type(until) not in (int, float) or not math.isfinite(until):
                    raise ValueError('Invalid saved sharing duration')
                if ((duration == 'ongoing' and until != -1)
                        or duration != 'ongoing' and (until < 0 or until > clock() + DURATIONS[duration] + 5)):
                    raise ValueError('Invalid saved sharing expiry')
                if not isinstance(revision, str) or len(revision) != 32 or any(c not in '0123456789abcdef' for c in revision):
                    raise ValueError('Invalid saved sharing generation')
                session = Session(until, duration, revision)
                if session.active(clock()): self.sessions[target] = session
            options = dict(database.execute('SELECT key,value FROM next_location_options'))
            background = json.loads(options.get('background', 'false'))
            if type(background) is not bool: raise ValueError('Invalid background preference')
            self.background = background
        except (ValueError, TypeError):
            # Preserve damaged data for recovery, but never start GPS from it.
            self.sessions = {}
            self.background = False
            self.error = 'Saved location sessions could not be read. Sharing is stopped.'

    @staticmethod
    def _target_key(target):
        if not isinstance(target, str) or not 1 <= len(target) <= 256 or any(ord(c) < 33 for c in target):
            raise ValueError('Choose a location recipient')
        return target

    def _active(self):
        now = self.clock()
        return {key: row for key, row in self.sessions.items() if row.active(now)}

    def _until(self, rows):
        values = [row.until for row in rows.values()]
        return -1 if -1 in values else max(values, default=0)

    async def _native(self, op, rows=None, **values):
        rows = self._active() if rows is None else rows
        result = await self.native(dict(op=op, session=self.token, active=bool(rows),
                                        until=self._until(rows), revisions=sorted(hashlib.sha256((key + ':' + row.revision).encode()).hexdigest()[:32]
                                                     for key, row in rows.items()),
                                        background=self.background, **values))
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise RuntimeError('The native location service could not complete this action')
        return result

    def _sensor_status(self, native):
        message = native.get('error')
        self.location_status = (message[:256] if isinstance(message, str) and message
                                else '' if native.get('can_submit') is True
                                else 'Waiting for permission or a fresh device location.')

    def _persist(self, rows):
        with self.db:
            self.db.execute('DELETE FROM next_location_sessions')
            self.db.executemany('INSERT INTO next_location_sessions VALUES(?,?,?,?)',
                                [(key, row.until, row.duration, row.revision) for key, row in rows.items()])
            self.db.execute('INSERT OR REPLACE INTO next_location_options VALUES(?,?)',
                            ('background', json.dumps(self.background)))

    def _cancel(self, targets):
        for key in targets:
            task = self.workers.pop(key, None)
            if task is not None: task.cancel()
            self.sent.pop(key, None)
            self.retries.pop(key, None)

    async def start(self, targets, duration, *, background=False, request_id=None, consent_epoch=None, deadline=None):
        if self.closed: raise RuntimeError('Location sharing is closed')
        request_id = uuid.uuid4().hex if request_id is None else request_id
        if (not isinstance(request_id, str) or len(request_id) != 32
                or any(c not in '0123456789abcdef' for c in request_id)):
            raise ValueError('Invalid sharing request')
        epoch = self.consent_epoch if consent_epoch is None else consent_epoch
        if type(epoch) is not int or epoch != self.consent_epoch: raise ValueError('Sharing controls changed; review the recipients again')
        if (not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS
                or not isinstance(duration, str) or duration not in DURATIONS or type(background) is not bool):
            raise ValueError('Choose up to 16 recipients and a sharing duration')
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or duration == 'ongoing' and deadline != -1
                or duration != 'ongoing' and not self.clock() < deadline <= self.clock() + DURATIONS[duration]):
            raise ValueError('Choose a current sharing expiry')
        for key in targets: self._target_key(key)
        if len(set(targets)) != len(targets): raise ValueError('Choose each recipient once')
        async with self.lock:
            if self.closed: raise RuntimeError('Location sharing is closed')
            if epoch != self.consent_epoch: raise ValueError('This sharing request was cancelled')
            if any((key, request_id) in self.cancelled_requests for key in targets):
                raise ValueError('This sharing request was cancelled')
            available = await self.catalog()
            if any(key not in available for key in targets):
                raise ValueError('A selected contact or radio is no longer available')
            # Starting a new selection is not consent to resume other saved
            # recipients. Those need the explicit Resume path and native grants.
            proposed = self._active() if self.armed else {}
            until = deadline if deadline is not None else (-1 if duration == 'ongoing' else self.clock() + DURATIONS[duration])
            for key in targets: proposed[key] = Session(until, duration, request_id)
            if len(proposed) > MAX_TARGETS: raise ValueError('Share with at most 16 recipients')
            previous_background = self.background
            self.background = background
            try:
                native = await self._native('start', proposed)
                self._sensor_status(native)
                self._persist(proposed)
            except BaseException:
                self.background = previous_background
                self.armed = False
                self.fix = None
                self._cancel(list(self.workers))
                with contextlib.suppress(Exception): await self._native('stop', {})
                raise
            self._cancel(targets)
            self.sessions = proposed
            self.armed = True
            self.fix = None
            self.native_generation = None
            self.generation += 1
            self.error = ''
        return await self.snapshot()

    async def resume(self):
        """Called only when the user returns to the app, never by a push wake."""
        async with self.lock:
            if self.closed or self.armed or not self._active(): return
            available = await self.catalog()
            rows = {key: row for key, row in self._active().items() if key in available}
            if not rows:
                await self._stop_locked(None)
                return
            try:
                self._persist(rows)
                await self._native('resume', rows)
            except BaseException:
                self.armed = False
                with contextlib.suppress(Exception): await self._native('stop', {})
                raise
            self.armed = True
            self.sessions = rows

    async def _stop_locked(self, target):
        proposed = self._active()
        if target is None: proposed.clear()
        else: proposed.pop(target, None)
        removed = set(self.sessions) - set(proposed)
        # In-memory revocation happens before disk I/O or native shutdown.
        self.sessions = proposed
        self._cancel(removed)
        self.generation += 1
        if not proposed:
            self.armed = False
            self.fix = None
            self.native_generation = None
            self.location_status = ''
        try:
            self._persist(proposed)
        finally:
            await self._native('configure' if proposed else 'stop', proposed)

    async def stop(self, target=None, request_id=None):
        if target is not None: self._target_key(target)
        if request_id is not None and (not isinstance(request_id, str) or len(request_id) != 32
                or any(c not in '0123456789abcdef' for c in request_id)):
            raise ValueError('Invalid sharing request')
        async with self.lock:
            if target is None:
                self.consent_epoch += 1
                self.cancelled_requests.clear()
            elif request_id is not None:
                self.cancelled_requests[(target, request_id)] = True
                if len(self.cancelled_requests) > 4096:
                    # Invalidate all old pending client requests instead of
                    # evicting a still-live cancellation and allowing it later.
                    self.consent_epoch += 1
                    self.cancelled_requests.clear()
                current = self.sessions.get(target)
                if current is None or current.revision != request_id:
                    return await self.snapshot()
            await self._stop_locked(target)
        return await self.snapshot()

    async def snapshot(self):
        available = await self.catalog()
        return dict(consent_epoch=self.consent_epoch, active=bool(self._active()) and self.armed, paused=bool(self._active()) and not self.armed,
                    background=self.background, error=self.error, location_status=self.location_status,
                    sessions=[dict(target=key, name=available.get(key, {}).get('name', 'Unavailable contact'),
                                   until=row.until, duration=row.duration, request_id=row.revision)
                              for key, row in sorted(self._active().items())],
                    recipients=[dict(id=key, name=value.get('name', 'Contact'),
                                     service=value.get('service'), online=value.get('online') is True)
                                for key, value in sorted(available.items())])

    async def _guard(self, key, revision, native_generation, fix=None):
        def current():
            row = self.sessions.get(key)
            return (not self.closed and self.armed and row is not None
                    and row.revision == revision and row.active(self.clock())
                    and (fix is None or self.clock() - 120 <= fix['last_update'] <= self.clock() + 300))
        if not current(): return False
        if key not in await self.catalog() or not current(): return False
        try: native = await self._native('status')
        except (RuntimeError, OSError): return False
        # Both lookups can yield to a stop, replacement, expiry or permission
        # change. Never use consent sampled before that asynchronous boundary.
        return (key in await self.catalog() and current() and native.get('can_submit') is True
                and native.get('generation') == native_generation)

    async def _deliver(self, key, target, session, fix, native_generation):
        try:
            guard = lambda: self._guard(key, session.revision, native_generation, fix)
            if not await guard(): return
            # The callback must check guard again after waiting for a radio/path.
            accepted = await self.transmit(target, dict(fix), guard)
            if accepted is True and await guard():
                self.sent[key] = (self.monotonic(), dict(fix))
                self.retries.pop(key, None)
                if not self.retries: self.error = ''
            elif await guard():
                count = self.retries.get(key, (0, 0))[0] + 1
                self.retries[key] = (count, self.monotonic() + min(300, 30 * 2**min(count-1, 4)))
        except asyncio.CancelledError:
            raise
        except Exception:
            if self.sessions.get(key) == session:
                self.error = 'Location delivery will retry when its connection recovers.'
                count = self.retries.get(key, (0, 0))[0] + 1
                self.retries[key] = (count, self.monotonic() + min(300, 30 * 2**min(count-1, 4)))
        finally:
            if self.workers.get(key) is asyncio.current_task(): self.workers.pop(key, None)

    async def tick(self):
        if self.closed: return
        async with self.lock:
            if self.closed: return
            available = await self.catalog()
            active = self._active()
            removed = set(self.sessions) - {key for key in active if key in available}
            if removed:
                self._cancel(removed)
                self.sessions = {key: row for key, row in active.items() if key in available}
                if not self.sessions:
                    self.armed = False
                    self.fix = None
                try: self._persist(self.sessions)
                finally: await self._native('configure' if self.sessions else 'stop', self.sessions)
            if not self.sessions or not self.armed: return
            try: native = await self._native('status')
            except (RuntimeError, OSError): return
            self._sensor_status(native)
            generation = native.get('generation')
            if native.get('can_submit') is not True or type(generation) is not int:
                self.fix = None
                return
            try:
                fix = valid_fix(native.get('fix'), self.clock())
                if fix['last_update'] < self.clock() - 120: return
            except ValueError: return
            self.fix, self.native_generation = fix, generation
            now = self.monotonic()
            for key, session in self._active().items():
                if key in self.workers or available[key].get('online') is not True: continue
                if self.retries.get(key, (0, 0))[1] > now: continue
                previous = self.sent.get(key)
                if previous:
                    elapsed = now - previous[0]
                    if elapsed < MOVING_INTERVAL or elapsed < STOPPED_INTERVAL and not location_moved(previous[1], fix): continue
                task = asyncio.create_task(self._deliver(key, available[key], session, fix, generation))
                self.workers[key] = task
                self._all_workers.add(task)
                task.add_done_callback(self._all_workers.discard)

    async def close(self):
        async with self.lock:
            self.closed = True
            self.armed = False
            tasks = list(self._all_workers)
            self._cancel(list(self.workers))
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(RuntimeError, OSError): await self._native('suspend', {})
