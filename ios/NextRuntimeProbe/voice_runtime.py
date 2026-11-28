"""neXt's existing LXST telephone with native iOS call controls and bounded PCM.

Owns no Reticulum instance or identity. All signaling/state changes run on the
app loop; only PCM exchange crosses from AVAudioEngine's serial worker.
"""
import asyncio
import contextlib
from dataclasses import dataclass, field
import json
import re
import sqlite3
import threading
import time
import uuid

from aiohttp import web


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", value):
        raise ValueError("Use a 32-character Reticulum voice address")
    return value.lower()


def native_request(value):
    from _next_voice import request
    text = json.dumps(value, allow_nan=False)
    if len(text.encode()) > 16_384:
        raise ValueError("Native call request is too large")
    result = json.loads(request(text))
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("The native call controller could not complete this action")
    return result


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value


class Configuration:
    def __init__(self, enabled=False, profile=None, mode=None):
        self.telephone_enabled = Value(enabled)
        self.telephone_audio_profile_id = Value(profile)
        self.telephone_call_mode_id = Value(mode)
        self.telephone_web_audio_enabled = Value(False)
        self.telephone_web_audio_allow_fallback = Value(False)


@dataclass
class Call:
    id: str
    peer: str
    name: str
    incoming: bool
    phase: str = "preparing"
    identity: str = ""
    requested_peer: str = ""
    muted: bool = False
    receive_muted: bool = False
    started_at: float = field(default_factory=time.time)
    connected_at: float = 0.
    capture_activity_at: float | None = None
    suppressed: bool = False


class VoiceEngine:
    """One telephone generation; retired workers cannot hang up its successor."""
    def __init__(self, identity, config, callbacks, loop):
        from meshchatnext.src.backend.telephone_manager import TelephoneManager
        from meshchatnext.src.backend.web_audio_bridge import WebAudioBridge
        self.manager = TelephoneManager(identity, config)
        self.manager.web_audio_required = True
        self.manager.set_callbacks(**callbacks)
        self.closed = False
        self.lock = threading.Lock()
        self.manager.init_telephone()
        phone = self.manager.telephone
        if phone is None: raise RuntimeError("Reticulum calling could not start")
        # Scheduling belongs to the app's attached interfaces, not LXST's
        # unscoped broadcast thread. Keep startup/hourly announces enabled here.
        phone.ANNOUNCE_INTERVAL = 2**31 - 1
        phone.last_announce = time.time()
        original_call = phone.call
        def guarded_call(*args, **kwargs):
            with self.lock:
                if not self.closed: return original_call(*args, **kwargs)
        phone.call = guarded_call
        self.bridge = WebAudioBridge(self.manager, config, force_enabled=True)
        self.bridge._loop = loop
        self.native_processing = False
        self._source = None
        self._filters = []
        original_tx = self.bridge._ensure_remote_tx
        def native_tx(telephone):
            original_tx(telephone)
            source = self.bridge.tx_source
            if source is not None:
                if source is not self._source:
                    self._source, self._filters = source, source.filters
                # AVAudioEngine's voice-processing unit supplies AEC/AGC.
                # Apply LXST capture processing only for the unprocessed fallback.
                source.filters = [] if self.native_processing else self._filters
        self.bridge._ensure_remote_tx = native_tx

    def push(self, data, native_processing):
        self.native_processing = native_processing
        self.bridge.push_client_frame(data)

    def dispose(self):
        self.closed = True
        with self.lock:
            self.manager.teardown()
            self.bridge.on_call_ended()


class PCMClient:
    def __init__(self, owner, call_id): self.owner, self.call_id = owner, call_id
    async def send_bytes(self, data): await self.owner.receive_pcm(self.call_id, data)


class ReticulumVoice:
    def __init__(self, database, identity, contacts, interfaces, display_name, *,
                 native=native_request, engine_factory=VoiceEngine, clock=time.monotonic):
        self.database, self.identity = database, identity
        self.contacts, self.interfaces, self.display_name = contacts, interfaces, display_name
        self.native, self.engine_factory, self.clock = native, engine_factory, clock
        self.loop = asyncio.get_running_loop()
        with database:
            database.execute("CREATE TABLE IF NOT EXISTS next_voice_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            database.execute("""CREATE TABLE IF NOT EXISTS next_voice_calls (
                id TEXT PRIMARY KEY, peer TEXT NOT NULL, identity_hash TEXT NOT NULL,
                name TEXT NOT NULL, incoming INTEGER NOT NULL, status TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL, timestamp REAL NOT NULL,
                missed_unread INTEGER NOT NULL)""")
        saved_error = ""
        try:
            values = {k: json.loads(v) for k, v in database.execute("SELECT key, value FROM next_voice_settings")}
            if type(values.get("enabled", False)) is not bool or any(values.get(key) is not None and type(values[key]) is not int for key in ("profile", "mode")):
                raise ValueError("Invalid saved call settings")
        except (ValueError, TypeError):
            values = {}
            saved_error = "Saved call settings could not be read. Calling is off; review privacy settings."
        self.config = Configuration(values.get("enabled", False), values.get("profile"), values.get("mode"))
        self.policy_contacts = frozenset()
        self.call_policy = {key: values.get(key, default) for key, default in
                            (("do_not_disturb_enabled", False), ("telephone_allow_calls_from_contacts_only", True),
                             ("block_all_from_strangers", False))}
        self.blocked_callers = values.get("blocked_callers", [])
        if (any(type(value) is not bool for value in self.call_policy.values())
                or not isinstance(self.blocked_callers, list)
                or any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value) for value in self.blocked_callers)):
            self.config.telephone_enabled.value = False
            self.call_policy = {key: True for key in self.call_policy}
            self.blocked_callers = []
            saved_error = "Saved caller policy could not be read. Calling is off; review privacy settings."
        self.session = uuid.uuid4().hex
        self.engine = None
        self.call = None
        self.closed = False
        self.error = saved_error
        self.task = None
        self.ending = None
        self.pcm_lock = threading.RLock()
        self.received = bytearray()
        self.playing = False
        self.pcm_call = ""
        self.pcm_ready = False
        self.sent_frames = self.received_frames = self.dropped_bytes = 0
        self.capture_bytes = self.received_bytes = self.played_bytes = 0
        self.pull_calls = self.empty_pulls = 0
        self.last_announces = {}
        self.last_native = 0.
        self.client = None
        self.setup_lock = asyncio.Lock()
        self.retired_engine = None
        self.poller = None
        self.available = False
        self.on_settings = None
        self.on_call_start = None
        self.on_call_end = None
        self.before_policy_change = None
        self.refresh_call_contacts()
        try:
            self.native(dict(op="open", session=self.session))
            if native is native_request:
                from _next_voice import bind
                bind(self.push, self.pull)
            self.available = True
        except (ImportError, RuntimeError, ValueError):
            self.error = "Native Reticulum calling is unavailable in this build"

    def save(self):
        with self.database:
            for key, value in (("enabled", self.config.telephone_enabled.get()),
                               ("profile", self.config.telephone_audio_profile_id.get()),
                               ("mode", self.config.telephone_call_mode_id.get()),
                               ("blocked_callers", self.blocked_callers), *self.call_policy.items()):
                self.database.execute("INSERT INTO next_voice_settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                      (key, json.dumps(value)))
        if self.on_settings: self.on_settings(self.settings_snapshot())

    def settings_snapshot(self):
        return {**self.call_policy, "telephone_enabled": self.config.telephone_enabled.get(),
                "telephone_audio_profile_id": self.config.telephone_audio_profile_id.get(),
                "telephone_call_mode_id": self.config.telephone_call_mode_id.get()}

    def request(self, operation, **values):
        return self.native(dict(op=operation, session=self.session, **values))

    def name_for(self, peer, identity=None):
        import RNS
        identity = identity or RNS.Identity.recall(bytes.fromhex(peer))
        lxmf = RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity).hex() if identity else None
        return next((row["name"] for key, row in self.contacts().items()
                     if key in (peer, lxmf)), "Reticulum caller")

    async def start(self):
        if self.available and self.config.telephone_enabled.get():
            try: await self.ensure_engine()
            except (RuntimeError, ValueError, ImportError, OSError) as error: self.error = str(error)[:240]
        self.poller = asyncio.create_task(self.poll_loop())

    async def poll_loop(self):
        while not self.closed:
            if self.config.telephone_enabled.get(): await self.tick()
            await asyncio.sleep(.1)

    async def ensure_engine(self):
        async with self.setup_lock:
            return await self._ensure_engine()

    async def _ensure_engine(self):
        if self.closed or not self.available: raise RuntimeError(self.error or "Calling is closed")
        if self.ending and self.ending is not asyncio.current_task():
            raise ValueError("The previous call is still closing")
        if self.retired_engine is not None: raise RuntimeError("The previous call could not be cleaned up")
        if self.engine is not None: return self.engine
        holder = {"pending": []}
        def forward(event, identity):
            if self.closed: return
            engine = holder.get("engine")
            if engine is None:
                holder["pending"].append((event, identity))
            else:
                self.loop.call_soon_threadsafe(self.transport_event, engine, event, identity)
        callbacks = {name: (lambda identity, event=name: forward(event, identity))
                     for name in ("ringing", "established", "ended")}
        engine = await asyncio.to_thread(self.engine_factory, self.identity, self.config, callbacks, self.loop)
        holder["engine"] = engine
        if self.closed or not self.config.telephone_enabled.get():
            await asyncio.to_thread(engine.dispose)
            raise ValueError("Reticulum calling was turned off")
        self.refresh_call_contacts()
        engine.manager.set_call_policy(allowed_fn=self.caller_allowed)
        outgoing = getattr(engine.manager.telephone, "call", None)
        if callable(outgoing):
            def checked_outgoing(identity, *args, **kwargs):
                if self.closed or engine is not self.engine or not self.config.telephone_enabled.get():
                    raise RuntimeError("This Reticulum calling session has ended")
                import RNS
                remote = getattr(identity, "hash", None)
                if not isinstance(remote, bytes) or len(remote) != 16:
                    raise ValueError("Invalid Reticulum peer identity")
                peers = (remote.hex(),
                    RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity).hex(),
                    RNS.Destination.hash_from_name_and_identity("lxst.telephony", identity).hex())
                if any(getattr(self, "destination_blocked", lambda peer: False)(peer) for peer in peers):
                    raise ValueError("This Reticulum identity was blocked before calling")
                return outgoing(identity, *args, **kwargs)
            # TelephoneManager resolves identities and paths asynchronously, then
            # invokes this exact boundary on its network worker. A preflight
            # address check cannot protect a newly discovered blocked identity.
            engine.manager.telephone.call = checked_outgoing
        self.engine = engine
        self.config.telephone_audio_profile_id.value = engine.manager.resolve_audio_profile_id()
        self.config.telephone_call_mode_id.value = engine.manager.resolve_call_mode_id()
        for event, identity in holder["pending"]:
            self.loop.call_soon(self.transport_event, engine, event, identity)
        holder["pending"].clear()
        return engine

    def refresh_call_contacts(self):
        # SQLite is owned by the app loop. LXST invokes the allowed callback
        # on its network worker, which reads only this immutable snapshot.
        self.policy_contacts = frozenset(self.contacts())

    def message_allowed(self, peer):
        # Global stranger blocking applies to received DMs even with calling off.
        return (isinstance(peer, str) and re.fullmatch(r"[a-f0-9]{32}", peer) is not None
                and not getattr(self, "destination_blocked", lambda peer: False)(peer)
                and (not self.call_policy["block_all_from_strangers"] or peer in self.policy_contacts))

    def caller_allowed(self, identity_hash):
        # neXt's normal incoming-call policy must be explicitly installed.
        # TelephoneManager deliberately rejects everyone until this happens.
        if not isinstance(identity_hash, (bytes, bytearray)) or len(identity_hash) != 16:
            return False
        try:
            import RNS
            aliases = {bytes(identity_hash).hex(),
                       RNS.Destination.hash_from_name_and_identity("lxmf.delivery", bytes(identity_hash)).hex(),
                       RNS.Destination.hash_from_name_and_identity("lxst.telephony", bytes(identity_hash)).hex()}
            if (not self.config.telephone_enabled.get() or self.call_policy["do_not_disturb_enabled"]
                    or aliases.intersection(self.blocked_callers)
                    or any(getattr(self, "destination_blocked", lambda peer: False)(peer) for peer in aliases)):
                return False
            if self.call_policy["telephone_allow_calls_from_contacts_only"] or self.call_policy["block_all_from_strangers"]:
                return bool(aliases.intersection(self.policy_contacts))
            return True
        except Exception:
            return False

    def set_call_policy(self, payload):
        if not isinstance(payload, dict) or not payload or set(payload) - (set(self.call_policy) | {"blocked_callers"}):
            raise ValueError("Choose a supported caller policy")
        if any(type(value) is not bool for key, value in payload.items() if key != "blocked_callers"):
            raise ValueError("Caller policy switches must be on or off")
        blocked = payload.get("blocked_callers", self.blocked_callers)
        if not isinstance(blocked, list) or len(blocked) > 10000:
            raise ValueError("Use a list of blocked Reticulum addresses")
        blocked = sorted({address(value) for value in blocked})
        changed = blocked != self.blocked_callers or any(self.call_policy[key] != value for key, value in payload.items() if key != "blocked_callers")
        if changed and self.before_policy_change: self.before_policy_change()
        self.refresh_call_contacts()
        self.call_policy.update({key: value for key, value in payload.items() if key != "blocked_callers"})
        self.blocked_callers = blocked
        self.save()
        return {**self.call_policy, "blocked_callers": blocked}

    async def configure(self, enabled):
        if type(enabled) is not bool: raise ValueError("Choose whether Reticulum calling is enabled")
        if enabled != self.config.telephone_enabled.get() and self.before_policy_change: self.before_policy_change()
        self.config.telephone_enabled.value = enabled
        self.error = ""
        self.save()
        if enabled:
            self.request("open")
            await self.ensure_engine()
        else:
            await self.end()
            if self.engine is not None:
                engine, self.engine = self.engine, None
                await asyncio.to_thread(engine.dispose)
        return self.snapshot()

    async def dial(self, peer):
        peer = address(peer)
        if getattr(self, "destination_blocked", lambda peer: False)(peer):
            raise ValueError("This Reticulum destination is blocked")
        if not self.config.telephone_enabled.get(): raise ValueError("Enable Reticulum calling first")
        if self.call or self.ending: raise ValueError("Another call is active or still closing")
        self.request("open")
        await self.ensure_engine()
        if getattr(self, "destination_blocked", lambda peer: False)(peer):
            raise ValueError("This Reticulum destination was blocked before calling")
        import RNS
        identity = RNS.Identity.recall(bytes.fromhex(peer))
        canonical = RNS.Destination.hash_from_name_and_identity("lxst.telephony", identity.hash).hex() if identity else peer
        self.error = ""
        call = Call(uuid.uuid4().hex, canonical, self.name_for(peer), False, requested_peer=peer)
        self.call = call
        try:
            self.request("dial", call_id=call.id, peer=peer, name=call.name)
        except Exception:
            self.call = None
            raise
        if self.on_call_start:
            with contextlib.suppress(Exception): self.on_call_start(call)
        return self.snapshot()

    def transport_event(self, engine, event, identity):
        if self.closed or engine is None or engine is not self.engine: return
        import RNS
        if event in ("ringing", "established") and identity is None: return
        peer = RNS.Destination.hash_from_name_and_identity("lxst.telephony", identity.hash).hex() if identity else None
        call = self.call
        if event in ("ringing", "established") and getattr(self, "destination_blocked", lambda peer: False)(peer):
            # A network worker may have accepted the call just before the ban.
            # Retire that engine without ever publishing ringing/audio/history.
            if call is None:
                call = Call(uuid.uuid4().hex, peer, "", True, "ending", identity.hash.hex(), suppressed=True)
                self.call = call
            elif call.peer != peer and call.requested_peer not in (peer, identity.hash.hex(),
                    RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity.hash).hex()):
                return
            self.schedule_end(call.id)
            return
        if event == "ringing" and call is None:
            call = Call(uuid.uuid4().hex, peer, self.name_for(peer, identity), True, "incoming", identity.hash.hex())
            self.call = call
            try: self.request("state", state="incoming", call_id=call.id, peer=call.peer, name=call.name)
            except RuntimeError:
                self.schedule_end(call.id)
                return
        elif call is None:
            return
        elif peer is not None and peer != call.peer:
            aliases = {peer, identity.hash.hex(), RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity.hash).hex()}
            if not call.incoming and call.requested_peer in aliases:
                call.peer = peer
            else:
                return
        if event == "ringing":
            if call.phase in ("connected", "ending"): return
            if not call.incoming:
                call.phase = "ringing"
                self.request("state", state="ringing", call_id=call.id, peer=call.peer)
        elif event == "established":
            if call.phase == "ending": return
            call.phase, call.identity = "connected", identity.hash.hex()
            if not call.connected_at: call.connected_at = time.time()
            self.client = PCMClient(self, call.id)
            if not engine.bridge.attach_client(self.client):
                self.error = "The native Reticulum audio bridge could not attach"
                self.schedule_end(call.id)
                return
            with self.pcm_lock:
                self.pcm_call, self.pcm_ready = call.id, True
                self.received.clear(); self.playing = False
            self.request("state", state="connected", call_id=call.id, peer=call.peer)
        elif event == "ended":
            # An old link's callback cannot end a newly ringing/established
            # link or a fresh path request on this telephone generation.
            phone = engine.manager.telephone
            if phone and getattr(phone, "active_call", None) is not None and getattr(phone, "call_status", 3) != 3: return
            if call.phase not in ("preparing", "finding", "ending"): self.schedule_end(call.id)

    async def receive_pcm(self, call_id, data):
        if not isinstance(data, bytes) or len(data) % 2: return
        with self.pcm_lock:
            if not self.pcm_ready or self.pcm_call != call_id or self.call is None or self.call.receive_muted: return
            self.received_bytes += len(data)
            self.dropped_bytes += max(0, len(data) - 48_000)
            self.received.extend(data[-48_000:])
            excess = len(self.received) - 48_000
            if excess > 0:
                del self.received[:excess]
                self.dropped_bytes += excess
            self.received_frames += 1

    def push(self, call_id, data, native_processing=False):
        if not isinstance(data, bytes) or not data or len(data) > 11_520 or len(data) % 2 or type(native_processing) is not bool: return
        with self.pcm_lock:
            if not self.pcm_ready or call_id != self.pcm_call or self.call is None or self.call.muted: return
            engine = self.engine
            if engine is not None:
                try:
                    engine.push(data, native_processing)
                    self.sent_frames += 1
                    self.capture_bytes += len(data)
                    self.call.capture_activity_at = self.clock()
                except Exception as error:
                    self.loop.call_soon_threadsafe(self.audio_failed, call_id, str(error)[:180])

    def audio_failed(self, call_id, detail):
        if self.call is not None and self.call.id == call_id:
            self.error = "Reticulum microphone audio failed: " + detail
            self.schedule_end(call_id)

    def pull(self, call_id):
        with self.pcm_lock:
            if not self.pcm_ready or call_id != self.pcm_call or self.call is None or self.call.receive_muted: return b""
            self.pull_calls += 1
            if not self.playing:
                if len(self.received) < 5_760:
                    self.empty_pulls += 1
                    return b""
                self.playing = True
            if len(self.received) < 1_920:
                self.playing = False
                self.empty_pulls += 1
                return b""
            result = bytes(self.received[:1_920]); del self.received[:1_920]
            self.played_bytes += len(result)
            return result

    def schedule_end(self, call_id):
        if self.call is not None and self.call.id == call_id and self.ending is None:
            self.ending = asyncio.create_task(self.end(call_id))

    async def end(self, call_id=None):
        if self.ending is not None and self.ending is not asyncio.current_task():
            await asyncio.shield(self.ending)
            return
        if call_id is not None and (self.call is None or self.call.id != call_id):
            raise ValueError("The call has changed")
        call = self.call
        if call is None: return
        self.ending = asyncio.current_task()
        call.phase = "ending"
        if self.on_call_end:
            with contextlib.suppress(Exception): self.on_call_end(call)
        self.client = None
        with self.pcm_lock:
            self.pcm_ready = False; self.pcm_call = ""; self.received.clear(); self.playing = False
        with contextlib.suppress(RuntimeError):
            self.request("state", state="ended", call_id=call.id, peer=call.peer)
        engine, self.engine = self.engine, None
        self.retired_engine = engine
        try:
            if engine is not None: await asyncio.to_thread(engine.dispose)
            self.retired_engine = None
            if self.task:
                # Retired call workers hold the old engine only. They cannot
                # mutate or hang up the replacement telephone generation.
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
                self.task = None
        finally:
            try: self.record_call(call)
            except sqlite3.Error:
                self.error = "The call ended, but its history could not be saved."
            if self.call is call: self.call = None
            self.ending = None
        if not self.closed and self.config.telephone_enabled.get():
            try:
                self.request("open")
                await self.ensure_engine()
            except (RuntimeError, ValueError) as error: self.error = str(error)[:240]

    async def dial_transport(self, call, engine):
        if self.call is not call or call.phase == "ending" or self.engine is not engine: return
        try:
            call.phase = "finding"
            await engine.manager.initiate(bytes.fromhex(call.peer), timeout_seconds=30)
            if self.call is call and call.phase not in ("connected", "ending"):
                if not engine.manager.telephone.active_call:
                    raise RuntimeError("The Reticulum call did not connect")
        except asyncio.CancelledError: raise
        except Exception as error:
            if self.call is call:
                self.error = str(error)[:240]
                self.schedule_end(call.id)

    async def tick(self):
        if self.closed or not self.available: return
        self.refresh_call_contacts()
        try:
            for event in self.request("poll").get("events", []):
                call = self.call
                if not isinstance(event, dict) or call is None or event.get("call_id") != call.id: continue
                operation = event.get("operation")
                if operation == "dial" and not call.incoming and call.phase == "preparing":
                    self.task = asyncio.create_task(self.dial_transport(call, self.engine))
                    call.phase = "finding"
                elif operation == "answer" and call.incoming and call.phase == "incoming":
                    identity = self.engine.manager.telephone.active_call.get_remote_identity()
                    if identity is None or identity.hash.hex() != call.identity: raise ValueError("The caller changed")
                    await asyncio.to_thread(self.engine.manager.telephone.answer, identity)
                elif operation in ("hangup", "audio_error"):
                    if operation == "audio_error": self.error = "The native microphone or speaker could not start"
                    self.schedule_end(call.id)
                elif operation == "mute" and type(event.get("value")) is bool:
                    call.muted = event["value"]
                    method = self.engine.manager.mute_transmit if call.muted else self.engine.manager.unmute_transmit
                    await asyncio.to_thread(method)
        except (RuntimeError, ValueError, ConnectionError) as error:
            self.error = str(error)[:240]
            if self.call: self.schedule_end(self.call.id)
            else:
                with contextlib.suppress(RuntimeError): self.request("open")
        if self.engine is not None and self.call is not None and self.call.phase == "connected":
            # Remote profile changes replace LXST pipelines even if the local
            # microphone is muted; heal receive-only audio on the app loop.
            self.engine.bridge.attach_client(self.client)
        if self.engine is not None and self.config.telephone_enabled.get():
            await self.announce_due()

    async def announce_due(self, force=False):
        if self.engine is None: return 0
        engine = self.engine
        count = 0
        for interface in self.interfaces():
            if not getattr(interface, "online", False) or getattr(interface, "detached", False) or not getattr(interface, "OUT", True): continue
            key = (id(interface), getattr(interface, "family_connection_epoch", 0))
            if not force and self.clock() - self.last_announces.get(key, float("-inf")) < 3600: continue
            try:
                await asyncio.to_thread(engine.manager.announce, attached_interface=interface, display_name=self.display_name())
                if self.engine is engine and engine.manager.telephone is not None and getattr(interface, "online", False) and not getattr(interface, "detached", False):
                    self.last_announces[key] = self.clock(); count += 1
            except (RuntimeError, OSError): pass
        return count

    def snapshot(self):
        call = self.call
        capabilities = {}
        if call is not None and call.phase == "connected":
            with contextlib.suppress(RuntimeError): capabilities = self.request("capabilities")
        capture_status = capabilities.get("capture_status")
        if call is not None and call.phase == "connected":
            if call.muted:
                capture_status = "Microphone muted."
            elif (call.capture_activity_at is not None
                  and 0 <= self.clock() - call.capture_activity_at < 2):
                capture_status = "Microphone audio is flowing."
        with self.pcm_lock:
            pcm = dict(pcm_capture_bytes=self.capture_bytes, pcm_received_bytes=self.received_bytes,
                       pcm_played_bytes=self.played_bytes, playback_queued_bytes=len(self.received),
                       playback_pull_calls=self.pull_calls, playback_empty_pulls=self.empty_pulls)
        phone = self.engine.manager.telephone if self.engine else None
        active = None
        if call is not None and call.phase != "ending":
            import RNS
            lxmf = RNS.Destination.hash_from_name_and_identity("lxmf.delivery", bytes.fromhex(call.identity)).hex() if call.identity else None
            active = dict(hash=call.id, call_id=call.id, remote_identity_hash=call.identity or call.peer,
                          remote_telephony_hash=call.peer, remote_destination_hash=lxmf,
                          remote_identity_name=call.name, is_incoming=call.incoming,
                          status={"preparing":2,"finding":2,"calling":2,"ringing":4,"incoming":4,"connected":6,"ending":3}[call.phase],
                          is_mic_muted=call.muted, is_speaker_muted=call.receive_muted, is_recording=False, is_voicemail=False,
                          audio_profile_id=getattr(getattr(phone, "active_call", None), "profile", None) or self.config.telephone_audio_profile_id.get(),
                          call_mode_id=self.engine.manager.get_active_mode_id() if self.engine else self.config.telephone_call_mode_id.get(),
                          is_half_duplex=self.engine.manager.is_half_duplex() if self.engine else False,
                          is_ptt_active=bool(self.engine.manager.ptt_active) if self.engine else False)
        return dict(**self.call_policy, speaker=capabilities.get("speaker"),
                    external_audio=capabilities.get("external_audio"), capture_status=capture_status,
                    microphone_permission=capabilities.get("microphone_permission"), platform="ios", enabled=self.config.telephone_enabled.get(), ready=phone is not None,
                    audio_timing=capabilities.get("audio_timing") if isinstance(capabilities.get("audio_timing"), dict) else {},
                    calling_available=self.available, address=phone.destination.hash.hex() if phone and phone.destination else "",
                    active_call=active, call_status=active["status"] if active else 3, is_busy=call is not None or self.ending is not None,
                    initiation_status=self.engine.manager.initiation_status if self.engine else None,
                    initiation_target_hash=call.peer if call else None, initiation_target_name=call.name if call else None,
                    error=self.error, missed_calls_unread_count=self.missed_count(),
                    preferred_audio_profile_id=self.config.telephone_audio_profile_id.get(),
                    voicemail=dict(is_recording=False, unread_count=0, latest_id=None),
                    web_audio=dict(enabled=False, required=False, allow_fallback=False, native_audio=True),
                    sent_frames=self.sent_frames, received_frames=self.received_frames, playback_dropped_bytes=self.dropped_bytes,
                    **pcm,
                    call_targets=[{"address": key, "name": row["name"]} for key, row in self.contacts().items()])

    def record_call(self, call):
        if call.suppressed: return
        status = "Completed" if call.connected_at else "Missed" if call.incoming else "Failed"
        duration = max(0, int(time.time() - call.connected_at)) if call.connected_at else 0
        with self.database:
            self.database.execute("INSERT OR IGNORE INTO next_voice_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (call.id, call.peer, call.identity, call.name, int(call.incoming), status,
                 duration, call.started_at, int(call.incoming and not call.connected_at)))

    def missed_count(self):
        return self.database.execute("SELECT COUNT(*) FROM next_voice_calls WHERE missed_unread = 1").fetchone()[0]

    def call_history(self, query):
        try:
            limit = int(query.get("limit", 10)); offset = int(query.get("offset", 0))
        except (TypeError, ValueError): raise ValueError("Use valid call-history page numbers") from None
        search = query.get("search", "")
        if (not 0 <= limit <= 250 or not 0 <= offset <= 1_000_000
                or not isinstance(search, str) or len(search) > 512):
            raise ValueError("Use valid call-history page and search limits")
        rows = self.database.execute("""SELECT id, peer, identity_hash, name, incoming, status,
            duration_seconds, timestamp FROM next_voice_calls
            WHERE name LIKE ? OR identity_hash LIKE ? OR peer LIKE ?
            ORDER BY timestamp DESC, rowid DESC LIMIT ? OFFSET ?""",
            ("%"+search+"%", "%"+search+"%", "%"+search+"%", limit, offset))
        import RNS
        contacts = self.contacts()
        result = []
        for call_id, peer, identity, name, incoming, status, duration, timestamp in rows:
            lxmf = RNS.Destination.hash_from_name_and_identity("lxmf.delivery", bytes.fromhex(identity)).hex() if identity else None
            contact = contacts.get(lxmf) or contacts.get(peer)
            result.append(dict(id=call_id, remote_identity_hash=identity or peer,
                               remote_identity_name=contact["name"] if contact else name,
                               remote_telephony_hash=peer, remote_destination_hash=lxmf,
                               is_incoming=bool(incoming), status=status, duration_seconds=duration,
                               timestamp=timestamp, is_contact=bool(contact)))
        return {"call_history": result}

    async def close(self):
        self.closed = True
        if self.poller:
            self.poller.cancel()
            await asyncio.gather(self.poller, return_exceptions=True)
            self.poller = None
        await self.end()
        if self.engine is not None:
            engine, self.engine = self.engine, None
            await asyncio.to_thread(engine.dispose)
        if self.available:
            with contextlib.suppress(RuntimeError): self.request("close")

    def control(self, operation, payload):
        call = self.call
        if not isinstance(payload, dict) or call is None or call.phase == "ending" or payload.get("call_id") != call.id:
            raise ValueError("The call has changed")
        if operation not in ("answer", "hangup", "mute", "speaker"):
            raise ValueError("Unsupported call control")
        if operation == "speaker" and call.phase != "connected": raise ValueError("Connect the call before changing its audio output")
        value = payload.get("value")
        if operation in ("mute", "speaker") and type(value) is not bool:
            raise ValueError("Choose a call control value")
        self.request(operation, call_id=call.id, **({"value": value} if value is not None else {}))
        return {"message": "ok"}

    def profile_choices(self):
        from LXST.Primitives.Telephony import Profiles
        from meshchatnext.src.backend.telephone_manager import TelephoneManager
        codec2 = TelephoneManager.codec2_available()
        narrow = {Profiles.BANDWIDTH_ULTRA_LOW, Profiles.BANDWIDTH_VERY_LOW, Profiles.BANDWIDTH_LOW}
        return {"default_audio_profile_id": Profiles.DEFAULT_PROFILE, "codec2_available": codec2,
                "audio_profiles": [{"id": key, "name": Profiles.profile_name(key), "available": codec2 or key not in narrow}
                                   for key in Profiles.available_profiles()]}

    async def set_profile(self, value, payload):
        if type(value) is not int: raise ValueError("Choose an available voice quality")
        previous = self.call
        if self.call is not None: self.require_call(payload)
        choices = self.profile_choices()
        if value not in {row["id"] for row in choices["audio_profiles"] if row["available"]}:
            raise ValueError("Choose an available voice quality")
        if self.engine is not None:
            value = await asyncio.to_thread(self.engine.manager.apply_preferred_profile, value)
        if previous is not None and self.call is not previous: raise ValueError("The call has changed")
        self.config.telephone_audio_profile_id.value = value
        self.save()
        return {"message": "ok", "profile_id": value, "requested_profile_id": value, "remapped": False}

    def mode_choices(self):
        from meshchatnext.src.backend import lxst_profiles_compat as modes
        return {"default_call_mode_id": modes.default_mode(), "call_modes": [
            {"id": key, "name": modes.mode_name(key), "abbrev": modes.mode_abbreviation(key),
             "is_half_duplex": key == modes.mode_half_duplex()} for key in modes.available_modes()]}

    def require_call(self, payload):
        if not isinstance(payload, dict) or self.call is None or self.call.phase == "ending" or payload.get("call_id") != self.call.id:
            raise ValueError("The call has changed")
        return self.call

    async def set_mode(self, value, payload):
        if type(value) is not int: raise ValueError("Choose an available duplex mode")
        previous = self.call
        if self.call is not None: self.require_call(payload)
        if value not in {row["id"] for row in self.mode_choices()["call_modes"]}:
            raise ValueError("Choose an available duplex mode")
        if self.engine is not None: value = await asyncio.to_thread(self.engine.manager.apply_preferred_mode, value)
        if previous is not None and self.call is not previous: raise ValueError("The call has changed")
        self.config.telephone_call_mode_id.value = value
        self.save()
        from meshchatnext.src.backend import lxst_profiles_compat as modes
        return {"message": "ok", "mode_id": value, "is_half_duplex": value == modes.mode_half_duplex(),
                "is_ptt_active": bool(self.engine.manager.ptt_active) if self.engine else False}

    async def set_ptt(self, payload):
        call = self.require_call(payload)
        if type(payload.get("active")) is not bool or call.phase != "connected":
            raise ValueError("Push-to-talk requires a connected half-duplex call")
        engine = self.engine
        accepted = await asyncio.to_thread(engine.manager.set_ptt_active, payload["active"])
        if self.call is not call: raise ValueError("The call has changed")
        if not accepted and payload["active"]:
            raise ValueError("Push-to-talk requires a connected half-duplex call")
        return {"message": "ok", "is_ptt_active": engine.manager.ptt_active,
                "is_half_duplex": engine.manager.is_half_duplex()}

    async def set_receive_muted(self, payload, muted):
        call = self.require_call(payload)
        call.receive_muted = muted
        with self.pcm_lock:
            self.received.clear(); self.playing = False
        method = self.engine.manager.mute_receive if muted else self.engine.manager.unmute_receive
        await asyncio.to_thread(method)
        return {"message": "ok"}

    def register(self, router):
        async def protected(handler, request):
            try: return web.json_response(await handler(request))
            except (ValueError, RuntimeError) as error:
                return web.json_response({"message": str(error)[:240]}, status=400)
        async def status(request): return self.snapshot()
        async def history(request):
            if request.method == "DELETE":
                with self.database: self.database.execute("DELETE FROM next_voice_calls")
                return {"message": "ok"}
            return self.call_history(request.query)
        async def missed_viewed(request):
            with self.database: self.database.execute("UPDATE next_voice_calls SET missed_unread = 0 WHERE missed_unread = 1")
            return {"message": "ok"}
        async def configure(request):
            value = await request.json()
            if not isinstance(value, dict) or set(value) != {"enabled"}: raise ValueError("Choose whether calling is enabled")
            return await self.configure(value["enabled"])
        async def policy(request):
            if request.method == "POST": return self.set_call_policy(await request.json())
            return {**self.call_policy, "blocked_callers": self.blocked_callers}
        async def dial(request): return await self.dial(request.match_info["peer"])
        async def control(request):
            payload = await request.json()
            mapping = {"answer":"answer", "hangup":"hangup", "mute-microphone":"mute", "unmute-microphone":"mute", "mute-transmit":"mute", "unmute-transmit":"mute"}
            operation = request.match_info["action"]
            if operation not in mapping: raise ValueError("Unsupported call control")
            if operation in ("mute-microphone", "unmute-microphone", "mute-transmit", "unmute-transmit"):
                payload = dict(payload, value=operation.startswith("mute-"))
            return self.control(mapping[operation], payload)
        async def speaker(request): return self.control("speaker", await request.json())
        async def profiles(request): return await asyncio.to_thread(self.profile_choices)
        async def profile(request): return await self.set_profile(int(request.match_info["profile"]), await request.json())
        async def modes(request): return await asyncio.to_thread(self.mode_choices)
        async def mode(request): return await self.set_mode(int(request.match_info["mode"]), await request.json())
        async def ptt(request): return await self.set_ptt(await request.json())
        async def receive(request): return await self.set_receive_muted(await request.json(), request.match_info["action"] == "mute-receive")
        def add(method, path, handler):
            async def wrapped(request): return await protected(handler, request)
            router.add_route(method, "/api/v1/" + path, wrapped)
        add("GET", "preview/reticulum-calling", status)
        add("POST", "preview/reticulum-calling", configure)
        add("GET", "preview/reticulum-call-policy", policy)
        add("POST", "preview/reticulum-call-policy", policy)
        add("GET", "telephone/status", status)
        add("GET", "telephone/history", history)
        add("DELETE", "telephone/history", history)
        add("POST", "telephone/missed-calls/mark-viewed", missed_viewed)
        add("POST", "telephone/native-speaker", speaker)
        add("GET", "telephone/audio-profiles", profiles)
        add("POST", "telephone/call/{peer}", dial)
        add("POST", "telephone/switch-audio-profile/{profile}", profile)
        add("GET", "telephone/call-modes", modes)
        add("POST", "telephone/switch-call-mode/{mode}", mode)
        add("POST", "telephone/ptt", ptt)
        add("POST", "telephone/{action:mute-receive|unmute-receive}", receive)
        add("POST", "telephone/{action:answer|hangup|mute-microphone|unmute-microphone|mute-transmit|unmute-transmit}", control)
