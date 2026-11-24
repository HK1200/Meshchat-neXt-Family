"""Serve the released neXt frontend with an embedded LXMF backend."""

import asyncio
import contextlib
from datetime import datetime, timezone
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote
import base64
import LXMF

# iPadOS terminates sandboxed apps that call sendfile. Configure aiohttp
# before importing it so both the simulator and device use buffered reads.
os.environ["AIOHTTP_NOSENDFILE"] = "1"

from aiohttp import web

from messaging_probe import MessagingProbe, decode_reply_fields, reply_fields_for
import attachment_fields
from runtime_access import RuntimeAccess, COOKIE, CSP
from nomad_frame import public_frame_resource, build_nomad_crash_tab_csp
from durable_inbox import DurableInbox
from offline_mailbox import OfflineMailbox
import mailbox_push
import call_alerts
import durable_outbox
from loopback_listener import ResumableListener
from conversation_organization import ConversationOrganization
from blocked_destinations import PeerBlocks
from block_runtime import BlockRuntime
from contact_import import ContactImport


def record(message, state):
    raw_fields = message.fields if isinstance(message.fields, dict) else {}
    content = message.content_as_string()
    from telemetry_runtime import incoming_fields
    telemetry_data = incoming_fields(raw_fields)
    reply, fields = decode_reply_fields(raw_fields)
    fields.update(attachment_fields.incoming(raw_fields))
    return {
        "_telemetry_data": telemetry_data,
        "hash": message.hash.hex(),
        "source_hash": message.source_hash.hex(),
        "destination_hash": message.destination_hash.hex(),
        "content": content,
        "title": "",
        "fields": fields,
        "reply_to_hash": reply,
        "state": state,
        "method": {LXMF.LXMessage.PROPAGATED: "propagated", LXMF.LXMessage.OPPORTUNISTIC: "opportunistic"}.get(getattr(message, "method", None), "direct"),
        "created_at": datetime.fromtimestamp(message.timestamp, timezone.utc).isoformat(),
        "progress": 100 if state in ("delivered", "sent") else 0,
        "is_outbound": state != "received",
        "is_private_telemetry": content.startswith("!NFLOC1:") or (
            not content.strip() and not fields and
            any(key in raw_fields for key in
                (LXMF.FIELD_TELEMETRY, LXMF.FIELD_TELEMETRY_STREAM))
        ),
    }


class ConversationHistory:
    VISIBLE = ("COALESCE(json_extract(payload, '$.is_private_telemetry'), 0) = 0 "
               "AND COALESCE(substr(json_extract(payload, '$.content'), 1, 8), '') != '!NFLOC1:'")
    def __init__(self, path, *, notification_floor=0):
        if type(notification_floor) is not int or not 0 <= notification_floor <= 9_000_000_000_000_000:
            raise ValueError("Invalid local notification baseline")
        self.db = sqlite3.connect(path)
        with self.db:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    hash TEXT NOT NULL UNIQUE,
                    peer TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
            """)
            self.db.execute("CREATE INDEX IF NOT EXISTS messages_peer ON messages(peer, id)")
            self.db.execute("CREATE TABLE IF NOT EXISTS destination_names (address TEXT PRIMARY KEY, name TEXT NOT NULL)")
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY,
                    lxmf_address TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL
                )
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS conversation_reads (
                    peer TEXT PRIMARY KEY,
                    through_id INTEGER NOT NULL
                )
            """)
            # Upgrading the preview must not label all old history as new.
            self.db.execute("""
                INSERT OR IGNORE INTO conversation_reads(peer, through_id)
                SELECT peer, MAX(id) FROM messages GROUP BY peer
            """)
            # Keep IDs monotonic even when the newest unread messages are
            # deleted. Native notification baselines must never hide a new DM.
            self.db.execute("CREATE TABLE IF NOT EXISTS next_runtime_counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            self.db.execute("INSERT OR IGNORE INTO next_runtime_counters VALUES ('message_id', 0)")
            self.db.execute("""UPDATE next_runtime_counters SET value = MAX(value,
                COALESCE((SELECT MAX(id) FROM messages), 0),
                COALESCE((SELECT MAX(through_id) FROM conversation_reads), 0), ?)
                WHERE name = 'message_id'""", (notification_floor,))
            # Retain only local packet identifiers, never deleted content.
            # Delivery/failure callbacks may arrive after the user deletes a chat.
            self.db.execute("CREATE TABLE IF NOT EXISTS deleted_message_hashes (hash TEXT PRIMARY KEY)")
            self.db.execute("CREATE TABLE IF NOT EXISTS hidden_conversations (peer TEXT PRIMARY KEY)")
            self.db.execute("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS notification_metadata (
                hash TEXT PRIMARY KEY, eligible INTEGER NOT NULL
            )""")
            # The preview did not notify before this migration. Keep old inbox
            # read state intact without retroactively alerting historical messages.
            self.db.execute("""INSERT OR IGNORE INTO notification_metadata
                SELECT hash, 0 FROM messages""")
            durable_outbox.schema(self.db)
            # Old previews did not retain a signed restart packet. Preserve
            # that truthful failure state; new journaled sends remain pending.
            self.db.execute("""
                UPDATE messages SET state = 'failed' WHERE state = 'sending'
                AND hash NOT IN (SELECT hash FROM next_pending_messages)
            """)

    def preferences(self, default_name="neXt iOS"):
        result = {"display_name": default_name, "theme": "system", "auto_announce_interval_seconds": 3600, "page_archiver_enabled": False}
        result.update(dict(self.db.execute("SELECT key, value FROM preferences WHERE key != 'last_announced_at'")))
        result["auto_announce_interval_seconds"] = int(result["auto_announce_interval_seconds"])
        result["page_archiver_enabled"] = result["page_archiver_enabled"] in (True, 1, "1")
        return result

    def last_announce_time(self):
        row = self.db.execute("SELECT value FROM preferences WHERE key = 'last_announced_at'").fetchone()
        if row is None:
            return None
        try:
            value = int(row[0])
            return value if value >= 0 else None
        except (ValueError, TypeError):
            return None

    def record_announce_time(self, timestamp):
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError("Invalid announce timestamp")
        with self.db:
            self.db.execute("INSERT INTO preferences VALUES ('last_announced_at', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (timestamp,))

    def update_preferences(self, changes, default_name="neXt iOS"):
        if not isinstance(changes, dict) or not changes or set(changes) - {"display_name", "theme", "auto_announce_interval_seconds", "page_archiver_enabled"}:
            raise ValueError("This iOS preview supports saving the display name, theme, announce interval and page archiving")
        values = dict(changes)
        if "display_name" in values:
            name = values["display_name"]
            if (not isinstance(name, str) or not name.strip() or len(name.strip().encode("utf-8")) > 128
                    or any(ord(character) < 32 or ord(character) == 127 for character in name)):
                raise ValueError("Enter a display name of at most 128 UTF-8 bytes without control characters")
            values["display_name"] = name.strip()
        if "theme" in values and values["theme"] not in ("light", "dark", "system"):
            raise ValueError("Choose Light, Dark or System theme")
        if "auto_announce_interval_seconds" in values:
            interval = values["auto_announce_interval_seconds"]
            if type(interval) is not int or interval not in (0, 900, 1800, 3600, 10800, 21600, 43200, 86400):
                raise ValueError("Choose a listed announce interval")
        if "page_archiver_enabled" in values and type(values["page_archiver_enabled"]) is not bool:
            raise ValueError("Choose whether to save visited pages")
        with self.db:
            self.db.executemany("INSERT INTO preferences VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                values.items())
        return self.preferences(default_name)

    def ensure_contact(self, address, name):
        with self.db:
            self.db.execute(
                "INSERT INTO contacts(lxmf_address, name) VALUES (?, ?) ON CONFLICT(lxmf_address) DO NOTHING",
                (address, name),
            )

    @staticmethod
    def contact_name(name, *, allow_empty=False):
        if (not isinstance(name, str) or len(name.strip()) > 120
                or any(ord(character) < 32 or ord(character) == 127 for character in name)
                or (not allow_empty and not name.strip())):
            raise ValueError("Use a name of at most 120 characters without control characters")
        return name.strip()

    def rename_contact(self, contact_id, name):
        name = self.contact_name(name)
        with self.db:
            row = self.db.execute("SELECT lxmf_address FROM contacts WHERE id = ?", (contact_id,)).fetchone()
            if row is None:
                raise KeyError(contact_id)
            self.db.execute("UPDATE contacts SET name = ? WHERE id = ?", (name, contact_id))
            self.db.execute("INSERT INTO destination_names VALUES (?, ?) ON CONFLICT(address) DO UPDATE SET name = excluded.name", (row[0], name))

    def remove_contact(self, contact_id):
        # Removing a phonebook entry never deletes messages, read state or
        # local conversation labels, and never changes another service's keys.
        with self.db:
            if self.db.execute("DELETE FROM contacts WHERE id = ?", (contact_id,)).rowcount != 1:
                raise KeyError(contact_id)

    def custom_name(self, address):
        row = self.db.execute("SELECT name FROM destination_names WHERE address = ?", (address,)).fetchone()
        return row[0] if row else None

    def set_custom_name(self, address, name):
        if not isinstance(address, str) or not re.fullmatch(r"[a-f0-9]{32}", address):
            raise ValueError("Enter a valid LXMF address")
        name = self.contact_name(name, allow_empty=True)
        with self.db:
            if name:
                self.db.execute("INSERT INTO destination_names VALUES (?, ?) ON CONFLICT(address) DO UPDATE SET name = excluded.name", (address, name))
            else:
                self.db.execute("DELETE FROM destination_names WHERE address = ?", (address,))

    def contacts(self):
        return {
            address: {"id": contact_id, "lxmf_address": address, "name": name}
            for contact_id, address, name in self.db.execute(
                "SELECT id, lxmf_address, name FROM contacts ORDER BY name COLLATE NOCASE, id"
            )
        }

    def conversation_entries(self):
        entries = {address: {**entry, "is_contact": True}
                   for address, entry in self.contacts().items()}
        for (address,) in self.db.execute("SELECT DISTINCT peer FROM messages WHERE " + self.VISIBLE):
            if re.fullmatch(r"[a-f0-9]{32}", address):
                entries.setdefault(address, {"name": address, "is_contact": False})
        for address, name in self.db.execute("SELECT address, name FROM destination_names"):
            if address in entries:
                entries[address]["name"] = name
        hidden = {row[0] for row in self.db.execute("SELECT peer FROM hidden_conversations")}
        return {address: entry for address, entry in entries.items() if address not in hidden}

    def has_conversation(self, address):
        return bool(isinstance(address, str) and re.fullmatch(r"[a-f0-9]{32}", address)
                    and self.db.execute("SELECT 1 FROM messages WHERE peer = ? AND " + self.VISIBLE + " LIMIT 1", (address,)).fetchone())

    def save(self, peer, row, *, pending=None):
        with self.db:
            if self.db.execute("SELECT 1 FROM deleted_message_hashes WHERE hash = ?", (row["hash"],)).fetchone():
                return None
            if pending is not None:
                durable_outbox.enqueue(self.db, row, *pending)
            elif row["state"] in ("failed", "sent", "delivered"):
                durable_outbox.remove(self.db, row["hash"])
            self.db.execute("DELETE FROM hidden_conversations WHERE peer = ?", (peer,))
            self.db.execute("INSERT OR IGNORE INTO conversation_reads VALUES (?, 0)", (peer,))
            payload = json.dumps({k: v for k, v in row.items() if k not in ("id", "state")})
            existing = self.db.execute("SELECT id FROM messages WHERE hash = ?", (row["hash"],)).fetchone()
            if existing is None:
                self.db.execute("""UPDATE next_runtime_counters SET value = MAX(value,
                    COALESCE((SELECT MAX(id) FROM messages), 0),
                    COALESCE((SELECT MAX(through_id) FROM conversation_reads), 0)) + 1
                    WHERE name = 'message_id'""")
                message_id = self.db.execute("SELECT value FROM next_runtime_counters WHERE name = 'message_id'").fetchone()[0]
            else:
                message_id = existing[0]
            self.db.execute("""
                INSERT INTO messages(id, hash, peer, state, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(hash) DO UPDATE SET state = excluded.state, payload = excluded.payload
            """, (message_id, row["hash"], peer, row["state"], payload))
            message_id, = self.db.execute(
                "SELECT id FROM messages WHERE hash = ?", (row["hash"],)
            ).fetchone()
            eligible = (row["state"] == "received" and not row.get("is_private_telemetry")
                        and not str(row.get("content", "")).startswith("!NFLOC1:"))
            self.db.execute("""INSERT INTO notification_metadata VALUES (?, ?)
                ON CONFLICT(hash) DO UPDATE SET eligible=excluded.eligible""", (row["hash"], int(eligible)))
        return {**row, "id": message_id}

    def page(self, peer, query):
        descending = query.get("order") == "desc"
        order = "DESC" if descending else "ASC"
        operator = "<" if descending else ">"
        count = min(max(int(query.get("count", 100)), 1), 250)
        after_id = int(query["after_id"]) if "after_id" in query else None
        rows = self.db.execute(f"""
            SELECT id, state, payload FROM messages
            WHERE peer = ? AND {self.VISIBLE} AND (? IS NULL OR id {operator} ?)
            ORDER BY id {order} LIMIT ?
        """, (peer, after_id, after_id, count))
        # Decode and discard each attachment blob before retaining the next
        # UI row. Downloads use message(), which preserves the original bytes.
        result = []
        for message_id, state, payload in rows:
            row = json.loads(payload)
            result.append(attachment_fields.slim({**row, "id": message_id, "state": state}))
        return result

    def mark_read(self, peer):
        with self.db:
            self.db.execute("""
                INSERT INTO conversation_reads(peer, through_id)
                VALUES (?, (SELECT COALESCE(MAX(id), 0) FROM messages WHERE peer = ?))
                ON CONFLICT(peer) DO UPDATE SET through_id = excluded.through_id
            """, (peer, peer))

    def summary(self, peer):
        unread, failed = self.db.execute(f"""
            SELECT COUNT(CASE WHEN state = 'received' AND id > COALESCE(
                (SELECT through_id FROM conversation_reads WHERE peer = ?), 0) THEN 1 END),
                COUNT(CASE WHEN state = 'failed' THEN 1 END)
            FROM messages WHERE peer = ? AND {self.VISIBLE}
        """, (peer, peer)).fetchone()
        latest = self.page(peer, {"order": "desc", "count": 1})
        row = latest[0] if latest else {}
        fields = row.get("fields") or {}
        files = fields.get("file_attachments") or []
        count = len(files) + bool(fields.get("image")) + bool(fields.get("audio"))
        preview = row.get("content")
        if not preview and count:
            preview = f"{count} attachments" if count > 1 else files[0]["file_name"] if files else "Photo" if fields.get("image") else "Voice message"
        return {
            "has_attachments": bool(count),
            "is_unread": bool(unread), "unread_count": unread, "failed_messages_count": failed,
            "latest_message_preview": preview, "latest_message_title": row.get("title"),
            "updated_at": row.get("created_at"),
        }

    def notification_candidates(self):
        # One current alert per unread conversation. Keep file/photo bytes
        # out of this query, even when a received attachment is near the size limit.
        rows = self.db.execute("""
            SELECT m.id, m.hash, m.peer FROM messages m JOIN (
                SELECT MAX(candidate.id) AS id FROM messages candidate
                JOIN notification_metadata n ON n.hash = candidate.hash AND n.eligible = 1
                LEFT JOIN conversation_reads r ON r.peer = candidate.peer
                WHERE candidate.state = 'received' AND candidate.id > COALESCE(r.through_id, 0)
                GROUP BY candidate.peer
            ) newest ON newest.id = m.id ORDER BY m.id DESC LIMIT 100
        """).fetchall()
        return [{"id": message_id, "hash": message_hash, "peer": peer}
                for message_id, message_hash, peer in rows
                if re.fullmatch(r"[a-f0-9]{64}", message_hash) and re.fullmatch(r"[a-f0-9]{32}", peer)]

    def message(self, message_hash):
        row = self.db.execute("SELECT payload FROM messages WHERE hash = ?", (message_hash,)).fetchone()
        return json.loads(row[0]) if row else None

    def message_for_reply(self, peer, message_hash):
        row = self.db.execute(
            "SELECT payload FROM messages WHERE peer = ? AND hash = ? AND " + self.VISIBLE, (peer, message_hash)
        ).fetchone()
        return json.loads(row[0]) if row is not None else None

    def delete(self, message_hash):
        with self.db:
            row = self.db.execute("SELECT state FROM messages WHERE hash = ?",
                                  (message_hash,)).fetchone()
            if row is None:
                raise KeyError(message_hash)
            if row[0] == "sending":
                raise ValueError("Message is still sending")
            self.db.execute("INSERT OR IGNORE INTO deleted_message_hashes VALUES (?)", (message_hash,))
            durable_outbox.remove(self.db, message_hash)
            self.db.execute("DELETE FROM messages WHERE hash = ?", (message_hash,))
            self.db.execute("DELETE FROM notification_metadata WHERE hash = ?", (message_hash,))

    def delete_conversations(self, addresses):
        if (not isinstance(addresses, list) or not 0 < len(addresses) <= 1000
                or any(not isinstance(address, str) or not re.fullmatch(r"[a-f0-9]{32}", address) for address in addresses)):
            raise ValueError("Select between 1 and 1000 existing conversations")
        addresses = list(dict.fromkeys(addresses))
        contacts = self.contacts()
        for address in addresses:
            if (address not in contacts and not self.has_conversation(address)
                    and not self.db.execute("SELECT 1 FROM hidden_conversations WHERE peer = ?", (address,)).fetchone()):
                raise ValueError("Select existing conversations")
        pending = []
        with self.db:
            for address in addresses:
                pending.extend(row[0] for row in self.db.execute(
                    "SELECT hash FROM messages WHERE peer = ? AND state IN ('sending', 'sent')", (address,)))
                self.db.execute("INSERT OR IGNORE INTO deleted_message_hashes SELECT hash FROM messages WHERE peer = ?", (address,))
                self.db.execute("DELETE FROM notification_metadata WHERE hash IN (SELECT hash FROM messages WHERE peer = ?)", (address,))
                self.db.execute("DELETE FROM next_pending_messages WHERE peer = ?", (address,))
                self.db.execute("DELETE FROM messages WHERE peer = ?", (address,))
                self.db.execute("DELETE FROM conversation_reads WHERE peer = ?", (address,))
                self.db.execute("INSERT OR IGNORE INTO hidden_conversations VALUES (?)", (address,))
                if self.db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'lxmf_conversation_folders'").fetchone():
                    self.db.execute("DELETE FROM lxmf_conversation_folders WHERE peer_hash = ?", (address,))
                if self.db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'lxmf_conversation_pins'").fetchone():
                    self.db.execute("DELETE FROM lxmf_conversation_pins WHERE peer_hash = ?", (address,))
        return pending

    def close(self):
        self.db.close()


async def serve(ready_file, frontend, fixture, *, device=False, peer_settings=None, meshcore_factory=None, sip_factory=None, voice_factory=None, map_factory=None, relay_factory=None, telemetry_factory=None, location_factory=None, network_factory=None, file_factory=None, terminal_factory=None, nomad_factory=None):
    loop = asyncio.get_running_loop()
    clients = set()
    tasks = set()
    voice = None
    call_sender = None
    maps = None
    relay = None
    telemetry = None
    location = None
    files = None
    terminal = None
    nomad = None
    closing = False
    pending_active = set()
    pending_retry_at = {}

    def persist(row):
        address = row["destination_hash"] if row["is_outbound"] else row["source_hash"]
        if not re.fullmatch(r"[a-f0-9]{32}", address):
            return None, False
        if address == own or blocks.denies(address):
            return None, True
        if not row["is_outbound"] and voice is not None and not voice.message_allowed(address):
            # Acknowledge the verified packet without creating history or alerts.
            return None, True
        if telemetry is not None and not row["is_outbound"]:
            telemetry.receive(row)
            if row.get("is_private_telemetry"):
                return None, True
        row = {key:value for key,value in row.items() if key != "_telemetry_data"}
        if address not in contacts and not history.has_conversation(address):
            # Deliberately consume unwanted telemetry without creating a chat.
            # A database error is different: it must leave mailbox data unacked.
            if row["is_outbound"] or row.get("is_private_telemetry"):
                return None, True
        saved = history.save(address, row)
        return (None if row.get("is_private_telemetry") else saved), True

    async def notify(kind, row):
        for client in tuple(clients):
            try:
                await client.send_json({"type": kind, "lxmf_message": attachment_fields.slim(row)})
            except (ConnectionError, RuntimeError):
                clients.discard(client)

    def track(coroutine):
        task = asyncio.create_task(coroutine)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def publish(kind, row):
        saved, accepted = persist(row)
        if saved is not None:
            await notify(kind, saved)
        return accepted

    def schedule(kind, row):
        track(publish(kind, row))

    def commit_received(row):
        saved, accepted = persist(row)
        if saved is not None:
            # Notify after commit, without making transport receipt depend on
            # a slow or disconnected web view consuming the WebSocket event.
            track(notify("lxmf.delivery", saved))
        return accepted

    inbox = DurableInbox(loop, commit_received)

    def inbound(message):
        return inbox.receive(record(message, "received"))

    settings = json.loads(fixture.read_text(encoding="utf-8"))
    if not device and peer_settings is not None:
        # Native persistence may alter only loopback peer settings in simulator tests.
        # Keep the signed echo fixture's identity/address; the transport validates every host.
        settings["peers"] = peer_settings["peers"]
        settings["notification_floor"] = peer_settings.get("notification_floor", 0)
    probe = MessagingProbe(settings, ready_file.parent, inbound, device=device)
    peer = probe.address.hex() if probe.address else None
    own = probe.source.hash.hex()
    history = ConversationHistory(ready_file.parent / f"messages-{own}.sqlite3",
                                  notification_floor=settings.get("notification_floor", 0))
    blocks = PeerBlocks(history.db, probe.source.identity)
    def mailbox_session():
        # Reconnects invalidate the relay link even if another parallel peer
        # stays online. Include only live, attached interfaces and their epochs.
        import RNS
        sessions = tuple(sorted((id(interface), getattr(interface, "family_connection_epoch", 0))
            for interface in tuple(RNS.Transport.interfaces)
            if getattr(interface, "online", False) and not getattr(interface, "detached", False)))
        return sessions or None
    mailbox = OfflineMailbox(history.db, probe.router, probe.source.identity, mailbox_session)
    token = secrets.token_urlsafe(32)
    access = RuntimeAccess(ready_file.parent)
    contact = "Test contact" if device else "Simulator Echo"
    if peer and not blocks.denies(peer):
        history.ensure_contact(peer, contact)
    contacts = history.contacts()
    display_name = "neXt iOS" if device else "neXt Simulator"
    config = {"lxmf_address_hash": own, "identity_hash": probe.source.identity.hash.hex(),
              "last_announced_at": history.last_announce_time(),
              **history.preferences(display_name)}
    def mailbox_config():
        return {"auto_send_failed_messages_to_propagation_node": mailbox.send_fallback,
                "lxmf_preferred_propagation_node_destination_hash": mailbox.address if mailbox.send_fallback else None}
    config.update(mailbox_config())
    probe.source.display_name = config["display_name"]
    responses = {
        "status": {"status": "ok", "network_ready": True, "ui_ready": True, "runtime_instance": access.instance},
        "auth/status": {"auth_enabled": False, "authenticated": True},
        "auth/csrf": {"csrf_token": token},
        "config": {"config": config},
    }

    announce_lock = asyncio.Lock()

    async def announce_routes(*, force=False):
        # Manual requests and the timer share one scheduler. Never mark a
        # queued/failed announce as sent, or race two identical transmissions.
        async with announce_lock:
            # Reticulum ignores equal-second announces for an existing route.
            # Preserve the real successful time through app restart, and wait
            # for the next wall-clock second rather than forging a timestamp.
            previous = config["last_announced_at"]
            now = time.time()
            if previous is not None and int(now) == previous:
                await asyncio.sleep(previous + 1.01 - now)
            if force:
                probe.connections.request_announce()
                probe.rnode.request_announce()
            interval = config["auto_announce_interval_seconds"]
            count = await asyncio.to_thread(probe.connections.announce_due, interval)
            count += bool(await asyncio.to_thread(probe.rnode.announce_due, interval))
            announced_at = probe.last_announced_at
            if count and announced_at is not None:
                history.record_announce_time(announced_at)
            if count and announced_at != config["last_announced_at"]:
                config["last_announced_at"] = announced_at
                for client in tuple(clients):
                    try:
                        await client.send_json({"type": "config", "config": config})
                    except (ConnectionError, RuntimeError):
                        clients.discard(client)
            return count

    async def meshcore_broadcast(event):
        for client in tuple(clients):
            try:
                await client.send_json(event)
            except (ConnectionError, RuntimeError):
                clients.discard(client)

    meshcore = (meshcore_factory(ready_file.parent, probe.source.identity,
                                history.contacts, meshcore_broadcast, device=device)
                if meshcore_factory else None)

    def before_call_policy_change():
        # Pause and persist native consent BEFORE SQLite can change. If the
        # process dies before the post-write digest arrives, a cold push still
        # cannot reuse the old permission snapshot.
        if not device or voice is None: return
        try:
            result = voice.request("call_policy_invalid")
        except Exception:
            raise web.HTTPServiceUnavailable(text="Call-alert permissions could not be saved; no policy change was made") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise web.HTTPServiceUnavailable(text="Call-alert permissions could not be saved; no policy change was made")

    @web.middleware
    async def local_only(request, handler):
        if request.host != authority:
            raise web.HTTPBadRequest()
        opaque_static = (request.headers.get("Origin") == "null" and request.method in ("GET", "HEAD")
                         and public_frame_resource(request.path))
        if request.headers.get("Origin") not in (None, f"http://{authority}") and not opaque_static:
            raise web.HTTPForbidden()
        if (request.path.startswith("/api/") or request.path == "/ws") and not access.allowed(request):
            raise web.HTTPForbidden(text="This local session is unavailable")
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.headers.get("X-CSRF-Token") != token:
            raise web.HTTPForbidden()
        try:
            response = await handler(request)
        finally:
            if call_sender and request.method in ("POST", "PUT", "DELETE", "PATCH"):
                call_sender.refresh_contacts()
            # A handler may save an edit before a later response/broadcast
            # fails. Revocation must still reach native code in that case.
            if device and voice and voice.available and request.method in ("POST", "PUT", "DELETE", "PATCH"):
                from push_receiving import notify_call_policy
                try:
                    notify_call_policy(history, probe.source, voice, block_snapshot=blocks.snapshot())
                except Exception:
                    raise web.HTTPServiceUnavailable(text="Call permissions changed; refresh call alerts before retrying") from None
        # The shell and opaque frame import several identical modules. Mark
        # every public variant, including the shell's no-Origin response, or
        # WebKit can reuse it for the frame without its required CORS headers.
        if public_frame_resource(request.path):
            response.headers["Vary"] = "Origin"
        if opaque_static:
            response.headers["Access-Control-Allow-Origin"] = "null"
            response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        if request.path == "/nomad-crash-tab.html":
            response.headers["Content-Security-Policy"] = build_nomad_crash_tab_csp(authority)
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Cache-Control"] = "no-store"
        return response

    async def api(request):
        path = request.match_info["path"]
        responses["status"]["inbox_error"] = inbox.error
        if path == "preview/call-enrollment-state" and request.method == "POST":
            from push_receiving import call_snapshot
            chunks, length = [], 0
            async for chunk in request.content.iter_chunked(8192):
                length += len(chunk)
                if length > 65536:
                    raise web.HTTPRequestEntityTooLarge(max_size=65536, actual_size=length)
                chunks.append(chunk)
            try:
                body = json.loads(b"".join(chunks))
                if type(body) is not dict or body.keys() != {"publicKeys"} or type(body["publicKeys"]) is not list:
                    raise ValueError("Invalid public key selection")
                value = call_snapshot(history, probe.source, voice, public_keys=body["publicKeys"], block_snapshot=blocks.snapshot())
            except (TypeError, ValueError):
                return web.json_response({"message": "Use at most 256 distinct public contact keys."}, status=400, headers={"Cache-Control": "no-store"})
            return web.json_response(value, headers={"Cache-Control": "no-store"})
        call_alert_route = re.fullmatch(r"telephone/contacts/([1-9][0-9]{0,17})/call-alert-route", path)
        if call_alert_route:
            contact_id = int(call_alert_route[1])
            entry = next((row for row in history.contacts().values() if row["id"] == contact_id), None)
            if entry is None: raise web.HTTPNotFound()
            recipient = entry["lxmf_address"]
            if blocks.denies(recipient): raise web.HTTPForbidden()
            try:
                if request.method == "GET":
                    route = call_alerts.route_for(ready_file.parent, recipient)
                elif request.method in ("POST", "DELETE"):
                    proposed = None
                    if request.method == "POST":
                        raw = bytearray()
                        async for chunk in request.content.iter_chunked(4096):
                            raw.extend(chunk)
                            if len(raw) > 4096: raise ValueError("Call-alert settings are too large")
                        body = json.loads(raw)
                        if type(body) is not dict or body.keys() != {"route"} or type(body["route"]) is not dict:
                            raise ValueError("Enter the provider, audience and bound contact key only")
                        proposed = body["route"]
                    current = history.contacts().get(recipient)
                    if current is None or current["id"] != contact_id or blocks.denies(recipient): raise web.HTTPNotFound()
                    route = call_alerts.save_route(ready_file.parent, recipient, proposed)
                else:
                    raise web.HTTPMethodNotAllowed(request.method, ["GET", "POST", "DELETE"])
                result = {"route": None if route is None else dict(
                    provider=route.provider, audience=route.audience, public_key=route.public_key)}
                if request.method == "GET":
                    # Match the released interface contract before a route is
                    # saved. An address alone cannot supply a public key.
                    result["public_key"] = None
                    with contextlib.suppress(Exception):
                        import RNS as route_rns
                        identity = route_rns.Identity.recall(bytes.fromhex(recipient))
                        if identity:
                            key = identity.get_public_key().hex()
                            if call_alerts.parse_route(recipient, dict(provider="https://identity.invalid",
                                    audience="identity", public_key=key)):
                                result["public_key"] = key
                return web.json_response(result, headers={"Cache-Control": "no-store"})
            except (ValueError, TypeError):
                return web.json_response({"message": "Use an HTTPS provider, audience and this contact's public key."}, status=400)
        alert_route = re.fullmatch(r"telephone/contacts/([1-9][0-9]{0,17})/mailbox-alert-route", path)
        if alert_route:
            contact_id = int(alert_route[1])
            entry = next((item for item in history.contacts().values() if item["id"] == contact_id), None)
            if entry is None:
                raise web.HTTPNotFound()
            recipient = entry["lxmf_address"]
            try:
                if request.method == "GET":
                    route = mailbox_push.route_for(ready_file.parent, recipient)
                elif request.method in ("POST", "DELETE"):
                    if request.method == "POST":
                        if request.content_length is not None and request.content_length > 4096:
                            raise ValueError("Recipient alert settings are too large")
                        encoded = bytearray()
                        async for chunk in request.content.iter_chunked(4096):
                            encoded.extend(chunk)
                            if len(encoded) > 4096:
                                raise ValueError("Recipient alert settings are too large")
                        body = json.loads(encoded)
                        if not isinstance(body, dict) or set(body) != {"route"} or not isinstance(body["route"], dict):
                            raise ValueError("Enter the provider, audience and mailbox relay only")
                        proposed = body["route"]
                    else:
                        proposed = None
                    # A contact removed while the request body was arriving
                    # cannot regain a saved route after its consent is gone.
                    current = history.contacts().get(recipient)
                    if current is None or current["id"] != contact_id:
                        raise web.HTTPNotFound()
                    route = mailbox_push.save_route(ready_file.parent, recipient, proposed)
                else:
                    raise web.HTTPMethodNotAllowed(request.method, ["GET", "POST", "DELETE"])
                return web.json_response({"route": None if route is None else {
                    "provider": route.provider, "audience": route.audience, "relay": route.relay}},
                    headers={"Cache-Control": "no-store"})
            except (ValueError, TypeError) as error:
                return web.json_response({"message": str(error)}, status=400)
            except OSError:
                return web.json_response({"message": "Recipient alert settings could not be saved. Previous settings are preserved."}, status=503)
        if request.method == "GET":
            if maps and path == "config": config.update(maps.settings())
            if telemetry and path == "config": config.update(telemetry.settings())
            if relay and path == "config": config.update(relay.settings())
            if path == "preview/contact-card":
                from family_cards import export_contact
                card = export_contact(config["display_name"], probe.source.identity,
                    bool(voice and voice.config.telephone_enabled.get()))
                return web.json_response({"contact_card": card}, headers={"Cache-Control": "no-store"})
            if path == "preview/call-enrollment-state":
                from push_receiving import call_snapshot
                try:
                    return web.json_response(call_snapshot(history, probe.source, voice, block_snapshot=blocks.snapshot()), headers={"Cache-Control": "no-store"})
                except ValueError:
                    return web.json_response({"message": "The call identity is unavailable. Reopen neXt before enrolling."}, status=503, headers={"Cache-Control": "no-store"})
            if path == "preview/push-enrollment-state":
                from push_receiving import snapshot
                return web.json_response(snapshot(history, probe.source, mailbox), headers={"Cache-Control": "no-store"})
            if path == "preview/mailbox":
                return web.json_response(mailbox.snapshot(), headers={"Cache-Control": "no-store"})
            if path == "preview/rnode":
                return web.json_response(probe.rnode.snapshot(), headers={"Cache-Control": "no-store"})
            if path == "preview/unread-messages":
                notices = history.notification_candidates()
                if meshcore:
                    notices += await meshcore.notification_candidates()
                return web.json_response({"messages": notices}, headers={"Cache-Control": "no-store"})
            if path == "announces":
                try:
                    if nomad and request.query.get("aspect") == "nomadnetwork.node":
                        return web.json_response({"announces": nomad.discovered(request.query)}, headers={"Cache-Control": "no-store"})
                    if relay and request.query.get("aspect") == "rrc.hub":
                        return web.json_response({"announces": relay.discovered(request.query)}, headers={"Cache-Control": "no-store"})
                    return web.json_response({"announces": [row for row in probe.discovery.page(request.query)
                        if request.query.get("include_blocked") == "true" or not blocks.denies(row["destination_hash"])]}, headers={"Cache-Control": "no-store"})
                except ValueError:
                    raise web.HTTPBadRequest(text="Invalid discovery search or pagination") from None
            if path == "preview/reticulum-connections":
                return web.json_response({"peers": probe.connections.snapshot()}, headers={"Cache-Control": "no-store"})
            if path == "preview/reticulum-connection":
                return web.json_response(
                    {"connected": probe.online, "enabledCount": sum(row["enabled"] for row in probe.connections.snapshot()), "theme": config["theme"]},
                    headers={"Cache-Control": "no-store"},
                )
            if path in responses:
                return web.json_response(responses[path])
            label = re.fullmatch(r"destination/([a-f0-9]{32})/custom-display-name", path)
            if label:
                return web.json_response({"custom_display_name": history.custom_name(label[1])})
            if path == "telephone/contacts":
                return web.json_response({"contacts": list(contacts.values()), "total_count": len(contacts)})
            if path.startswith("telephone/contacts/check/"):
                entry = contacts.get(path.rsplit("/", 1)[1])
                return web.json_response({"is_contact": entry is not None, "contact": entry, "id": entry["id"] if entry else None})
            if path.startswith("lxmf-messages/attachment/"):
                parts = path.split("/")
                if len(parts) != 4 or not re.fullmatch(r"[a-f0-9]{64}", parts[2]):
                    raise web.HTTPNotFound()
                row = history.message(parts[2])
                if row is None:
                    raise web.HTTPNotFound()
                fields = row.get("fields") or {}
                try:
                    if parts[3] == "image":
                        item = fields["image"]
                        data = base64.b64decode(item["image_bytes"], validate=True)
                        detected = attachment_fields.image_type(data)
                        if not detected: raise ValueError("Unsupported image")
                        content_type = "image/" + detected
                        disposition = "inline"
                    elif parts[3] == "audio":
                        import voice_notes
                        item = fields["audio"]
                        data = base64.b64decode(item["audio_bytes"], validate=True)
                        if not voice_notes.valid(item["audio_mode"], data): raise ValueError("Invalid recording")
                        if item["audio_mode"] == voice_notes.OPUS and request.query.get("raw") != "1":
                            data = await asyncio.to_thread(voice_notes.playable_wav, data)
                            content_type = "audio/wav"
                            disposition = "inline"
                        else:
                            content_type = "audio/ogg" if item["audio_mode"] == voice_notes.OPUS else "application/octet-stream"
                            disposition = "attachment; filename=voice-recording." + ("opus" if item["audio_mode"] == voice_notes.OPUS else "codec2")
                    elif parts[3] == "file":
                        index = int(request.query.get("file_index", "0"))
                        if index < 0: raise ValueError("Invalid file index")
                        item = fields["file_attachments"][index]
                        data = base64.b64decode(item["file_bytes"], validate=True)
                        content_type = "application/octet-stream"
                        disposition = "attachment; filename*=UTF-8''" + quote(attachment_fields.filename(item["file_name"]), safe="")
                    else:
                        raise web.HTTPNotFound()
                except (KeyError, ValueError, TypeError, IndexError):
                    raise web.HTTPNotFound()
                return web.Response(body=data, content_type=content_type,
                    headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff", "Cross-Origin-Resource-Policy": "same-origin", "Cache-Control": "private, no-store"})
            if path.startswith("lxmf-messages/conversation/"):
                address = path.rsplit("/", 1)[1]
                if address not in contacts and not history.has_conversation(address):
                    return web.json_response({"lxmf_messages": []})
                try:
                    return web.json_response({"lxmf_messages": [attachment_fields.slim(row) for row in history.page(address, request.query)]})
                except (ValueError, OverflowError):
                    raise web.HTTPBadRequest(text="Invalid history pagination")
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.headers.get("X-CSRF-Token") != token:
            raise web.HTTPForbidden()
        if request.method == "POST" and path in ("preview/mailbox", "preview/mailbox/sync"):
            try:
                if path.endswith("/sync"):
                    result = mailbox.tick(force=True)
                else:
                    result = mailbox.configure(await request.json())
                    config.update(mailbox_config())
                    await meshcore_broadcast({"type": "config", "config": config})
                return web.json_response(result, headers={"Cache-Control": "no-store"})
            except ValueError as error:
                return web.json_response({"message": str(error)}, status=400)
        contact_path = re.fullmatch(r"telephone/contacts/([1-9][0-9]{0,17})", path)
        if contact_path and request.method in ("PATCH", "DELETE"):
            try:
                if request.method == "PATCH":
                    body = await request.json()
                    if not isinstance(body, dict) or set(body) != {"name"}:
                        raise ValueError("This contact operation changes the name only")
                    history.rename_contact(int(contact_path[1]), body["name"])
                else:
                    entry = next((item for item in history.contacts().values() if item["id"] == int(contact_path[1])), None)
                    if entry is None: raise KeyError(contact_path[1])
                    before_call_policy_change()
                    if location:
                        try: await location.contact_removed(entry["lxmf_address"])
                        except (RuntimeError, OSError, sqlite3.Error):
                            return web.json_response({"message": "Location sharing could not be revoked; the contact was preserved."}, status=503)
                    mailbox_push.save_route(ready_file.parent, entry["lxmf_address"], None)
                    with contextlib.suppress(OSError, ValueError):
                        call_alerts.save_route(ready_file.parent, entry["lxmf_address"], None)
                    history.remove_contact(int(contact_path[1]))
            except KeyError:
                raise web.HTTPNotFound() from None
            except OSError:
                return web.json_response({"message": "Recipient alerts could not be revoked; the contact was preserved."}, status=503)
            except ValueError as error:
                return web.json_response({"message": str(error)}, status=400)
            contacts.clear()
            contacts.update(history.contacts())
            if voice: voice.refresh_call_contacts()
            return web.json_response({"message": "Contact updated" if request.method == "PATCH" else "Contact removed"})
        label_path = re.fullmatch(r"destination/([a-f0-9]{32})/custom-display-name/update", path)
        if label_path and request.method == "POST":
            try:
                body = await request.json()
                if not isinstance(body, dict) or set(body) != {"display_name"}:
                    raise ValueError("Enter a conversation name")
                history.set_custom_name(label_path[1], body["display_name"])
            except ValueError as error:
                return web.json_response({"message": str(error)}, status=400)
            return web.json_response({"message": "Custom display name updated"})
        if request.method == "POST" and path == "announce":
            if not await announce_routes(force=True):
                return web.json_response({"message": "No connected Reticulum interface could send the announce"}, status=503)
            return web.json_response({"status": "ok"})
        if request.method == "PATCH" and path == "config":
            try:
                payload = await request.json()
                if telemetry and isinstance(payload, dict) and telemetry.location_keys.intersection(payload):
                    config.update(telemetry.configure(payload))
                    if location: await location.tick()
                    await meshcore_broadcast({"type": "config", "config": config})
                    return web.json_response({"config": config})
                if isinstance(payload, dict) and "auto_send_failed_messages_to_propagation_node" in payload:
                    if set(payload) != {"auto_send_failed_messages_to_propagation_node"}:
                        raise ValueError("Change one mailbox setting at a time")
                    mailbox.configure({"address": mailbox.address,
                        "send_fallback": payload["auto_send_failed_messages_to_propagation_node"]})
                    config.update(mailbox_config())
                    await meshcore_broadcast({"type": "config", "config": config})
                    return web.json_response({"config": config})
                if relay and isinstance(payload, dict) and set(relay.settings()).intersection(payload):
                    config.update(await relay.configure(payload))
                    return web.json_response({"config": config})
                if maps and isinstance(payload, dict) and maps.map_keys.intersection(payload):
                    config.update(maps.update_settings(payload))
                    return web.json_response({"config": config})
                voice_keys = {"telephone_enabled", "telephone_audio_profile_id", "telephone_call_mode_id", *voice.call_policy} if voice else set()
                if voice and isinstance(payload, dict) and voice_keys.intersection(payload):
                    if len(payload) != 1: raise ValueError("Change one call setting at a time")
                    if "telephone_enabled" in payload: await voice.configure(payload["telephone_enabled"])
                    elif "telephone_audio_profile_id" in payload: await voice.set_profile(payload["telephone_audio_profile_id"], {})
                    elif "telephone_call_mode_id" in payload: await voice.set_mode(payload["telephone_call_mode_id"], {})
                    else: voice.set_call_policy(payload)
                    return web.json_response({"config": config})
                saved = history.update_preferences(payload, display_name)
            except ValueError as error:
                return web.json_response({"message": str(error)}, status=400)
            renamed = saved["display_name"] != config["display_name"]
            config.update(saved)
            probe.source.display_name = config["display_name"]
            if renamed:
                probe.connections.request_announce()
                probe.rnode.request_announce()
            for client in tuple(clients):
                try:
                    await client.send_json({"type": "config", "config": config})
                except (ConnectionError, RuntimeError):
                    clients.discard(client)
            return web.json_response({"config": config})
        if request.method == "DELETE" and path.startswith("lxmf-messages/"):
            message_hash = path.removeprefix("lxmf-messages/")
            try:
                history.delete(message_hash)
            except KeyError:
                raise web.HTTPNotFound()
            except ValueError as exc:
                return web.json_response({"message": str(exc)}, status=409)
            return web.json_response({"status": "success"})
        if request.method == "POST":
            if path == "preview/rnode":
                try:
                    return web.json_response(await asyncio.to_thread(probe.rnode.apply, await request.json()))
                except ValueError:
                    raise web.HTTPBadRequest(text="Invalid RNode profile; check the connection and radio settings") from None
            if path == "preview/reticulum-connections":
                body = await request.json()
                if not isinstance(body, dict) or "peers" not in body:
                    raise web.HTTPBadRequest(text="Expected a peer list")
                try:
                    peers = await asyncio.to_thread(probe.connections.apply, body)
                except ValueError as error:
                    return web.json_response({"message": str(error)}, status=400)
                return web.json_response({"peers": peers})
            if path == "telephone/contacts":
                body = await request.json()
                if not isinstance(body, dict):
                    raise web.HTTPBadRequest(text="Expected a contact object")
                address = body.get("lxmf_address")
                name = body.get("name")
                try:
                    name = history.contact_name(name)
                except ValueError as error:
                    return web.json_response({"message": str(error)}, status=400)
                if (not isinstance(address, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", address)
                        or address.lower() == own):
                    return web.json_response({"message": "Enter a name and a valid LXMF address"}, status=400)
                if blocks.denies(address):
                    return web.json_response({"message": "Unblock this Reticulum destination before adding it"}, status=403)
                if address.lower() in contacts:
                    return web.json_response({"message": "That LXMF address is already saved"}, status=409)
                before_call_policy_change()
                history.ensure_contact(address.lower(), name.strip())
                with history.db:
                    history.db.execute("DELETE FROM hidden_conversations WHERE peer = ?", (address.lower(),))
                contacts.update(history.contacts())
                if voice: voice.refresh_call_contacts()
                if relay: relay.refresh_contacts()
                return web.json_response({"message": "Contact added"})
            if path == "lxmf/conversations/bulk-mark-as-read":
                body = await request.json()
                if not isinstance(body, dict):
                    raise web.HTTPBadRequest(text="Expected a conversation selection")
                addresses = list(history.conversation_entries()) if body.get("mark_all") is True else body.get("destination_hashes")
                if (not isinstance(addresses, list) or len(addresses) > 1000
                        or any(not isinstance(address, str) or (address not in contacts and not history.has_conversation(address)) for address in addresses)):
                    raise web.HTTPBadRequest(text="Select existing conversations")
                for address in addresses:
                    history.mark_read(address)
                return web.json_response({"status": "success"})
            if path.startswith("lxmf/conversations/") and path.endswith("/mark-as-read"):
                address = path.removeprefix("lxmf/conversations/").removesuffix("/mark-as-read")
                if address not in contacts and not history.has_conversation(address):
                    raise web.HTTPNotFound()
                history.mark_read(address)
                return web.json_response({"status": "success"})
            if path == "lxmf-messages/send":
                body = await request.json()
                draft = body.get("lxmf_message") if isinstance(body, dict) else None
                if not isinstance(draft, dict):
                    raise web.HTTPBadRequest(text="Expected an LXMF message object")
                content = draft.get("content")
                address = draft.get("destination_hash")
                if not isinstance(address, str) or (address not in contacts and not history.has_conversation(address)) or not isinstance(content, str):
                    return web.json_response({"message": "Choose an LXMF contact or an existing conversation"}, status=400)
                if blocks.denies(address):
                    return web.json_response({"message": "This Reticulum destination is blocked"}, status=403)
                try:
                    raw_fields = draft.get("fields") or {}
                    telemetry_fields = {}
                    if telemetry is not None:
                        from telemetry_runtime import outbound
                        if isinstance(raw_fields, dict) and isinstance(raw_fields.get("telemetry"), dict) and "location" in raw_fields["telemetry"] and telemetry.settings()["location_source"] == "disabled":
                            raise ValueError("Enable location sharing in Settings before sending a location")
                        raw_fields, telemetry_fields = outbound(raw_fields)
                    location_generation = telemetry.generation if telemetry_fields else None
                    fields = await asyncio.to_thread(attachment_fields.outgoing, raw_fields, content)
                    fields.update(telemetry_fields)
                except ValueError as error:
                    return web.json_response({"message": str(error)}, status=400)
                if not content.strip() and not fields:
                    return web.json_response({"message": "Enter a message or choose an attachment"}, status=400)
                reply = draft.get("reply_to_hash")
                if reply is not None:
                    if not isinstance(reply, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", reply):
                        return web.json_response({"message": "Invalid reply message ID"}, status=400)
                    previous = history.message_for_reply(address, reply.lower())
                    if previous is None:
                        return web.json_response({"message": "The quoted message is unavailable in this conversation"}, status=404)
                    fields.update(reply_fields_for(reply, previous["content"]))
                delivery_method = body.get("delivery_method")
                selected_node = None if telemetry_fields or content.startswith("!NFLOC1:") else mailbox.outbound_node()
                try:
                    ordinary_message = not (telemetry_fields or content.startswith("!NFLOC1:") or
                        any(key in fields for key in (LXMF.FIELD_TELEMETRY, LXMF.FIELD_TELEMETRY_STREAM)))
                    message = await asyncio.to_thread(probe.compose, content, bytes.fromhex(address), fields,
                        delivery_method=delivery_method, propagation_node=selected_node,
                        allow_offline=ordinary_message)
                    if blocks.denies(address):
                        raise ValueError("This Reticulum destination was blocked before submission")
                    if telemetry_fields and telemetry.generation != location_generation:
                        raise ValueError("Location settings changed before the update could be sent")
                    if telemetry_fields:
                        outbound(draft.get("fields") or {})  # Recheck freshness after pathfinding.
                    if message.desired_method == LXMF.LXMessage.PROPAGATED:
                        if selected_node is None or mailbox.outbound_node() != selected_node:
                            raise ValueError("Mailbox sending was turned off or changed before submission")
                        probe.router.set_outbound_propagation_node(selected_node)
                    message.pack()
                except ValueError as exc:
                    return web.json_response({"message": str(exc)}, status=400)
                except TimeoutError as exc:
                    return web.json_response({"message": str(exc)}, status=504)

                expected_alert_route = mailbox_push.route_for(ready_file.parent, address) if address in history.contacts() else None

                failed = attach_delivery_callbacks(message, address, delivery_method is None, selected_node, expected_alert_route)
                pending = None
                outgoing = record(message, "sending")
                if not outgoing["is_private_telemetry"] and not telemetry_fields:
                    choices = durable_outbox.policy(message.desired_method, delivery_method is None, selected_node, expected_alert_route, recipient=message.destination.identity.get_public_key())
                    pending = (message.packed, choices)
                try:
                    row = history.save(address, outgoing, pending=pending)
                except ValueError as error:
                    return web.json_response({"message": str(error)}, status=400)
                except sqlite3.Error:
                    return web.json_response({"message": "The message could not be saved. Free some storage before trying again."}, status=503)
                if row is None:
                    return web.json_response({"message": "This exact packet was previously deleted. Please try sending again."}, status=409)
                if pending is not None: pending_active.add(message.hash.hex())
                try:
                    probe.send(message)
                except Exception:
                    message.state = LXMF.LXMessage.FAILED
                    if not failed(message):
                        await publish("lxmf_message_state_updated", {**row, "state": "failed"})
                        return web.json_response({"message": "Could not queue the message"}, status=502)
                return web.json_response({"lxmf_message": attachment_fields.slim(row)})
        raise web.HTTPNotFound()

    def attach_delivery_callbacks(message, address, automatic, selected_node, expected_alert_route):
        def state_changed(updated, state):
            async def committed_state():
                if closing: return
                await publish("lxmf_message_state_updated", record(updated, state))
                if state in ("failed", "sent", "delivered"):
                    pending_active.discard(updated.hash.hex())
            def on_loop():
                if not closing: track(committed_state())
            if not closing and not loop.is_closed(): loop.call_soon_threadsafe(on_loop)

        def delivered(updated):
            if closing: return
            state_changed(updated, "sent" if updated.method == LXMF.LXMessage.PROPAGATED else "delivered")
            if expected_alert_route is not None:
                mailbox_push.queue_accepted_hint(ready_file.parent, updated, expected_alert_route)

        def failed(updated):
            if closing: return False
            from outbound_mailbox import retry_via_mailbox
            if blocks.denies(address):
                pending_active.discard(updated.hash.hex())
                return False
            retried = retry_via_mailbox(updated, probe.router, selected_node,
                mailbox.outbound_node(), automatic=automatic)
            state_changed(updated, "sending" if retried else "failed")
            return retried

        message.register_delivery_callback(delivered)
        message.register_failed_callback(lambda updated: loop.call_soon_threadsafe(failed, updated) if not closing and not loop.is_closed() else None)
        return failed

    async def resume_pending_messages():
        if closing or mailbox_session() is None: return
        now = time.monotonic()
        with history.db:
            history.db.execute("DELETE FROM next_pending_messages WHERE hash NOT IN (SELECT hash FROM messages WHERE state='sending')")
        rows = history.db.execute("""SELECT p.hash, p.peer, p.policy
            FROM next_pending_messages p JOIN messages m ON m.hash=p.hash
            WHERE m.state='sending' ORDER BY m.id LIMIT 100""").fetchall()
        pending_active.intersection_update(row[0] for row in rows)
        active_peers = {row[1] for row in rows if row[0] in pending_active}
        remaining_peers = {row[1] for row in rows}
        for address in tuple(pending_retry_at):
            if address not in remaining_peers: pending_retry_at.pop(address, None)
        for key, address, raw_policy in rows:
            if key in pending_active or address in active_peers or now < pending_retry_at.get(address, 0): continue
            if blocks.denies(address) or history.db.execute("SELECT 1 FROM deleted_message_hashes WHERE hash=?", (key,)).fetchone():
                with history.db:
                    history.db.execute("UPDATE messages SET state='failed' WHERE hash=? AND state='sending'", (key,))
                    durable_outbox.remove(history.db, key)
                continue
            try:
                choices = durable_outbox.selected_policy(raw_policy)
                selected = bytes.fromhex(choices['relay']) if choices['relay'] else None
                if choices['method'] == LXMF.LXMessage.PROPAGATED and (selected is None or selected != mailbox.outbound_node()):
                    raise ValueError('Mailbox permission changed before restart recovery')
                packet = history.db.execute("SELECT packet FROM next_pending_messages WHERE hash=?", (key,)).fetchone()[0]
                message = durable_outbox.recreate(packet, key, address, probe, choices)
            except LookupError:
                # A restart may precede the recipient's next signed announce.
                pending_retry_at[address] = now + 30
                import RNS
                RNS.Transport.request_path(bytes.fromhex(address))
                return
            except Exception:
                previous = history.message(key)
                if previous is not None: await publish("lxmf_message_state_updated", {**previous, "state":"failed"})
                continue
            route = mailbox_push.route_for(ready_file.parent, address) if address in history.contacts() else None
            if durable_outbox.route_fingerprint(route) != choices['route']: route = None
            failed = attach_delivery_callbacks(message, address, choices['automatic'], selected, route)
            pending_active.add(key)
            if message.desired_method == LXMF.LXMessage.PROPAGATED:
                probe.router.set_outbound_propagation_node(selected)
            try: probe.send(message)
            except Exception:
                message.state = LXMF.LXMessage.FAILED
                failed(message)
            # Resume at most one packet per loop pass to avoid a startup burst.
            return

    async def websocket(request):
        client = web.WebSocketResponse(max_msg_size=14_000_000 if nomad is not None else 4 * 1024 * 1024)
        await client.prepare(request)
        clients.add(client)
        try:
            await client.send_json({"type": "config", "config": config})
            async for event in client:
                if event.type == web.WSMsgType.TEXT:
                    try:
                        data = event.json()
                    except ValueError:
                        continue
                    if isinstance(data, dict) and data.get("type") == "ping":
                        await client.send_json({"type": "pong"})
                    elif nomad is not None:
                        await nomad.handle(client, data)
        finally:
            if nomad is not None:
                nomad.disconnect(client)
            clients.discard(client)
        return client

    async def index(request):
        headers = {
            "Cache-Control": "no-store",
            "Content-Security-Policy": CSP.replace("connect-src 'self'", f"connect-src 'self' ws://{authority}"),
        }
        response = web.FileResponse(frontend / "index.html", headers=headers)
        if access.allowed(request):
            response.set_cookie(COOKIE, access.capability, httponly=True, samesite="Strict", path="/")
        return response

    async def disable_service_worker(request):
        # The embedded host is recreated on each launch and serves its assets locally.
        raise web.HTTPNotFound()

    app = web.Application(middlewares=[local_only], client_max_size=14_000_000)
    organization = ConversationOrganization(history, cancel_outbound=probe.router.cancel_outbound)
    organization.register(app.router)
    if network_factory:
        network_factory(probe, blocks.denies).register(app.router)
    if file_factory:
        async def file_event(value):
            for client in tuple(clients):
                try: await client.send_json(value)
                except (ConnectionError, RuntimeError): clients.discard(client)
        files = file_factory(probe, ready_file.parent / 'rncp' / own, blocks.denies, file_event)
        files.register(app.router)
    if terminal_factory:
        async def terminal_event(value):
            for client in tuple(clients):
                try: await client.send_json(value)
                except (ConnectionError, RuntimeError): clients.discard(client)
        terminal = terminal_factory(probe, ready_file.parent / 'rnsh' / own, blocks.denies, terminal_event)
        terminal.register(app.router)
    if nomad_factory:
        nomad = nomad_factory(ready_file.parent, probe, blocks.denies,
                              lambda event: track(meshcore_broadcast(event)), config)
        nomad.register(app.router)
    if voice_factory:
        def voice_interfaces():
            import RNS
            return tuple(RNS.Transport.interfaces)
        voice = voice_factory(history.db, probe.source.identity, history.contacts,
                              voice_interfaces, lambda: config["display_name"])
        def voice_settings_changed(values):
            config.update(values)
            async def broadcast_voice_settings():
                for client in tuple(clients):
                    try: await client.send_json({"type": "config", "config": config})
                    except (RuntimeError, ConnectionError): clients.discard(client)
            track(broadcast_voice_settings())
        voice.on_settings = voice_settings_changed
        voice.before_policy_change = before_call_policy_change
        call_sender = call_alerts.CallAlerts(ready_file.parent, probe.source.identity, history.contacts, blocks.denies)
        voice.on_call_start = call_sender.started
        voice.on_call_end = call_sender.ended
        async def stop_call_hints(_): call_sender.close()
        app.on_cleanup.insert(0, stop_call_hints)
        config.update(voice.settings_snapshot())
        voice.destination_blocked = blocks.denies
        voice.register(app.router)
        async def start_voice(_):
            await voice.start()
            if device and voice.available:
                from push_receiving import notify_call_policy
                try:
                    notify_call_policy(history, probe.source, voice, block_snapshot=blocks.snapshot())
                except Exception:
                    # The bridge requested local alert suspension. Preserve the
                    # messaging runtime even if native calling is unavailable.
                    voice.error = "Incoming call-alert permissions need review"
        async def stop_voice(_): await voice.close()
        app.on_startup.append(start_voice)
        app.on_cleanup.append(stop_voice)
    if map_factory:
        maps = map_factory(ready_file.parent, probe.source.identity, probe.reticulum,
                           lambda event: track(meshcore_broadcast(event)))
        config.update(maps.settings())
        maps.register(app.router)
        async def start_maps(_): await maps.start()
        async def stop_maps(_): await maps.close()
        app.on_startup.append(start_maps)
        app.on_cleanup.append(stop_maps)
    if telemetry_factory:
        telemetry = telemetry_factory(ready_file.parent, own, lambda event: track(meshcore_broadcast(event)))
        config.update(telemetry.settings())
        telemetry.register(app.router)
        async def stop_telemetry(_): telemetry.close()
        app.on_cleanup.append(stop_telemetry)
    if location_factory and telemetry:
        # Only the disposable loopback simulator can request this test source.
        # Device archives have no peer.json, so their normal settings are untouched.
        if not device and os.environ.get("NEXT_PROBE_LOCATION_FIXTURE") == "1":
            config.update(telemetry.configure({"location_source": "browser"}))
        location = location_factory(ready_file.parent, probe, history, telemetry)
        location.meshcore = meshcore
        location.recipient_allowed = lambda peer: not blocks.denies(peer)
        location.register(app.router)
        async def stop_location(_): await location.close()
        # Revoke GPS before closing telemetry's persistent settings.
        app.on_cleanup.insert(0, stop_location)
    if relay_factory:
        relay = relay_factory(ready_file.parent, probe.source.identity, probe.reticulum, history.contacts,
                              lambda: config["display_name"], lambda event: track(meshcore_broadcast(event)))
        config.update(relay.settings())
        relay.register(app.router)
        async def start_relay(_): await relay.start()
        async def stop_relay(_): await relay.close()
        app.on_startup.append(start_relay)
        app.on_cleanup.append(stop_relay)
    if meshcore:
        meshcore.register(app.router)
        await meshcore.start()
    sip = sip_factory(ready_file.parent, device=device) if sip_factory else None
    if sip:
        sip.register(app.router)
        async def start_sip(_app):
            await sip.start()
        async def stop_sip(_app):
            await sip.close()
        app.on_startup.append(start_sip)
        app.on_cleanup.append(stop_sip)
    async def revoke_blocked(keys):
        if nomad: nomad.begin_block(keys)
        for key in keys:
            if location: await location.contact_removed(key)
            mailbox_push.save_route(ready_file.parent, key, None)
            with contextlib.suppress(OSError, ValueError): call_alerts.save_route(ready_file.parent, key, None)

    async def blocks_changed():
        if nomad: nomad.reconcile_blocks()
        contacts.clear(); contacts.update(history.contacts())
        if relay: relay.refresh_contacts()
        if voice:
            voice.refresh_call_contacts()
            if voice.call and blocks.denies(voice.call.peer): voice.schedule_end(voice.call.id)
        await meshcore_broadcast({"type":"blocked_destinations", "blocked_destinations":blocks.snapshot()})

    BlockRuntime(blocks, history, organization, revoke_blocked, blocks_changed, before_change=before_call_policy_change).register(app.router)
    async def imported_contact_changed():
        contacts.clear(); contacts.update(history.contacts())
        if voice: voice.refresh_call_contacts()
        if relay: relay.refresh_contacts()

    ContactImport(history, blocks, own, imported_contact_changed, before_change=before_call_policy_change).register(app.router)
    app.router.add_route("*", "/api/v1/{path:.*}", api)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/", index)
    app.router.add_get("/service-worker.js", disable_service_worker)
    app.router.add_static("/", frontend)
    runner = web.AppRunner(app, access_log=None, handle_signals=False)
    await runner.setup()
    try:
        listener = ResumableListener(runner)
        host, port = await listener.start()
        authority = f"{host}:{port}"
        access.write_info(f"http://{authority}")
        staging = ready_file.with_suffix(".tmp")
        route = f"/#/messages/{peer}" if peer else "/#/messages"
        staging.write_text(f"http://{authority}{route}", encoding="utf-8")
        ready_file.with_suffix(".address").write_text(own, encoding="utf-8")
        staging.replace(ready_file)
        # Each connected route announces at startup/reconnect and hourly.
        # Simulator profiles are separately restricted to loopback only.
        while True:
            try:
                recovered = await listener.recover()
                if recovered and sip:
                    await sip.foreground()
            except OSError:
                # A failed foreground bind must not tear down messaging.
                pass
            await announce_routes()
            if relay: relay.refresh_contacts()
            mailbox.tick()
            await resume_pending_messages()
            if location: await location.tick()
            if terminal: await terminal.tick()
            await asyncio.sleep(1)
    finally:
        closing = True
        inbox.close()
        mailbox.close()
        access.clear_info()
        if meshcore:
            try:
                async with asyncio.timeout(30):
                    await meshcore.close()
            except (TimeoutError, ConnectionError, RuntimeError):
                pass
        if files: await files.close()
        if terminal: await terminal.close()
        if nomad: await nomad.close()
        probe.close()
        await runner.cleanup()
        if tasks:
            await asyncio.gather(*tasks)
        history.close()


def run_for_app(ready_file):
    resources = Path(__file__).parent
    ready = Path(ready_file)
    simulator = resources / "peer.json"
    fixture = simulator if simulator.is_file() else ready.with_suffix(".json")
    try:
        overrides = None
        if fixture == simulator and ready.with_suffix(".json").is_file():
            overrides = json.loads(ready.with_suffix(".json").read_text(encoding="utf-8"))
        from meshcore_runtime import NextMeshCore
        from sip_runtime import NextSIPRuntime
        from voice_runtime import ReticulumVoice
        from map_runtime import MapRuntime
        from relay_runtime import RelayRuntime
        from telemetry_runtime import TelemetryRuntime
        from location_runtime import LocationRuntime
        from network_runtime import NetworkRuntime
        from file_runtime import FileRuntime
        from terminal_runtime import TerminalRuntime
        from nomad_runtime import NomadRuntime
        asyncio.run(serve(ready, resources / "frontend", fixture, device=fixture != simulator,
                          peer_settings=overrides, meshcore_factory=NextMeshCore, sip_factory=NextSIPRuntime, voice_factory=ReticulumVoice, map_factory=MapRuntime, relay_factory=RelayRuntime, telemetry_factory=TelemetryRuntime, location_factory=LocationRuntime, network_factory=NetworkRuntime, file_factory=FileRuntime, terminal_factory=TerminalRuntime, nomad_factory=NomadRuntime))
    except Exception as error:
        ready.with_suffix(".error").write_text(str(error), encoding="utf-8")
        raise
