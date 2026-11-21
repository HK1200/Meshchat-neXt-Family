"""Serve the released neXt frontend with an embedded LXMF backend."""

import asyncio
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


def record(message, state):
    raw_fields = message.fields if isinstance(message.fields, dict) else {}
    content = message.content_as_string()
    reply, fields = decode_reply_fields(raw_fields)
    fields.update(attachment_fields.incoming(raw_fields))
    return {
        "hash": message.hash.hex(),
        "source_hash": message.source_hash.hex(),
        "destination_hash": message.destination_hash.hex(),
        "content": content,
        "title": "",
        "fields": fields,
        "reply_to_hash": reply,
        "state": state,
        "method": "direct",
        "created_at": datetime.fromtimestamp(message.timestamp, timezone.utc).isoformat(),
        "progress": 100 if state == "delivered" else 0,
        "is_outbound": state != "received",
        "is_private_telemetry": content.startswith("!NFLOC1:") or (
            not content.strip() and not fields and
            any(key in raw_fields for key in
                (LXMF.FIELD_TELEMETRY, LXMF.FIELD_TELEMETRY_STREAM))
        ),
    }


class ConversationHistory:
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
            self.db.execute("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS notification_metadata (
                hash TEXT PRIMARY KEY, eligible INTEGER NOT NULL
            )""")
            # The preview did not notify before this migration. Keep old inbox
            # read state intact without retroactively alerting historical messages.
            self.db.execute("""INSERT OR IGNORE INTO notification_metadata
                SELECT hash, 0 FROM messages""")
            # The preview has no persistent outbound queue. A send interrupted
            # by app termination is left visible as failed.
            self.db.execute("""
                UPDATE messages SET state = 'failed' WHERE state = 'sending'
            """)

    def preferences(self, default_name="neXt iOS"):
        result = {"display_name": default_name, "theme": "system", "auto_announce_interval_seconds": 3600}
        result.update(dict(self.db.execute("SELECT key, value FROM preferences WHERE key != 'last_announced_at'")))
        result["auto_announce_interval_seconds"] = int(result["auto_announce_interval_seconds"])
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
        if not isinstance(changes, dict) or not changes or set(changes) - {"display_name", "theme", "auto_announce_interval_seconds"}:
            raise ValueError("This iOS preview supports saving the display name, theme and announce interval")
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
        for (address,) in self.db.execute("SELECT DISTINCT peer FROM messages"):
            if re.fullmatch(r"[a-f0-9]{32}", address):
                entries.setdefault(address, {"name": address, "is_contact": False})
        for address, name in self.db.execute("SELECT address, name FROM destination_names"):
            if address in entries:
                entries[address]["name"] = name
        return entries

    def has_conversation(self, address):
        return bool(isinstance(address, str) and re.fullmatch(r"[a-f0-9]{32}", address)
                    and self.db.execute("SELECT 1 FROM messages WHERE peer = ? LIMIT 1", (address,)).fetchone())

    def save(self, peer, row):
        with self.db:
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
            WHERE peer = ? AND (? IS NULL OR id {operator} ?)
            ORDER BY id {order} LIMIT ?
        """, (peer, after_id, after_id, count))
        return [{**json.loads(payload), "id": message_id, "state": state} for message_id, state, payload in rows]

    def mark_read(self, peer):
        with self.db:
            self.db.execute("""
                INSERT INTO conversation_reads(peer, through_id)
                VALUES (?, (SELECT COALESCE(MAX(id), 0) FROM messages WHERE peer = ?))
                ON CONFLICT(peer) DO UPDATE SET through_id = excluded.through_id
            """, (peer, peer))

    def summary(self, peer):
        unread, failed = self.db.execute("""
            SELECT COUNT(CASE WHEN state = 'received' AND id > COALESCE(
                (SELECT through_id FROM conversation_reads WHERE peer = ?), 0) THEN 1 END),
                COUNT(CASE WHEN state = 'failed' THEN 1 END)
            FROM messages WHERE peer = ?
        """, (peer, peer)).fetchone()
        latest = self.page(peer, {"order": "desc", "count": 1})
        row = latest[0] if latest else {}
        fields = row.get("fields") or {}
        files = fields.get("file_attachments") or []
        count = len(files) + bool(fields.get("image"))
        preview = row.get("content")
        if not preview and count:
            preview = f"{count} attachments" if count > 1 else files[0]["file_name"] if files else "Photo"
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
            "SELECT payload FROM messages WHERE peer = ? AND hash = ?", (peer, message_hash)
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
            self.db.execute("DELETE FROM messages WHERE hash = ?", (message_hash,))
            self.db.execute("DELETE FROM notification_metadata WHERE hash = ?", (message_hash,))

    def close(self):
        self.db.close()


async def serve(ready_file, frontend, fixture, *, device=False, peer_settings=None, meshcore_factory=None, sip_factory=None):
    loop = asyncio.get_running_loop()
    clients = set()
    tasks = set()

    async def publish(kind, row):
        address = row["destination_hash"] if row["is_outbound"] else row["source_hash"]
        if not re.fullmatch(r"[a-f0-9]{32}", address) or address == own:
            return
        if address not in contacts and not history.has_conversation(address):
            # neXt is an adult messenger: a signed DM may begin a conversation
            # without adding its sender to the phonebook. Telemetry alone must
            # not create a new chat or location relationship.
            if row["is_outbound"] or row.get("is_private_telemetry"):
                return
        row = history.save(address, row)
        for client in tuple(clients):
            try:
                await client.send_json({"type": kind, "lxmf_message": attachment_fields.slim(row)})
            except (ConnectionError, RuntimeError):
                clients.discard(client)

    def schedule(kind, row):
        task = asyncio.create_task(publish(kind, row))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def inbound(message):
        loop.call_soon_threadsafe(schedule, "lxmf.delivery", record(message, "received"))

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
    token = secrets.token_urlsafe(32)
    access = RuntimeAccess(ready_file.parent)
    contact = "Test contact" if device else "Simulator Echo"
    if peer:
        history.ensure_contact(peer, contact)
    contacts = history.contacts()
    display_name = "neXt iOS" if device else "neXt Simulator"
    config = {"lxmf_address_hash": own, "identity_hash": probe.source.identity.hash.hex(),
              "last_announced_at": history.last_announce_time(),
              **history.preferences(display_name)}
    probe.source.display_name = config["display_name"]
    responses = {
        "status": {"status": "ok", "network_ready": True, "ui_ready": True, "runtime_instance": access.instance},
        "auth/status": {"auth_enabled": False, "authenticated": True},
        "auth/csrf": {"csrf_token": token},
        "config": {"config": config},
        "lxmf/conversation-pins": {"pinned_destination_hashes": []},
        "lxmf/folders": {"folders": []},
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

    @web.middleware
    async def local_only(request, handler):
        if request.host != authority:
            raise web.HTTPBadRequest()
        if request.headers.get("Origin") not in (None, f"http://{authority}"):
            raise web.HTTPForbidden()
        if (request.path.startswith("/api/") or request.path == "/ws") and not access.allowed(request):
            raise web.HTTPForbidden(text="This local session is unavailable")
        if request.method in ("POST", "DELETE", "PATCH") and request.headers.get("X-CSRF-Token") != token:
            raise web.HTTPForbidden()
        return await handler(request)

    async def api(request):
        path = request.match_info["path"]
        if request.method == "GET":
            if path == "preview/rnode":
                return web.json_response(probe.rnode.snapshot(), headers={"Cache-Control": "no-store"})
            if path == "preview/unread-messages":
                notices = history.notification_candidates()
                if meshcore:
                    notices += await meshcore.notification_candidates()
                return web.json_response({"messages": notices}, headers={"Cache-Control": "no-store"})
            if path == "announces":
                try:
                    return web.json_response({"announces": probe.discovery.page(request.query)}, headers={"Cache-Control": "no-store"})
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
            if path == "lxmf/conversations":
                return web.json_response({"conversations": [
                    {
                        "destination_hash": address,
                        "display_name": entry["name"],
                        "is_contact": entry["is_contact"],
                        **history.summary(address),
                    }
                    for address, entry in history.conversation_entries().items()
                ]})
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
        if request.method in ("POST", "DELETE", "PATCH") and request.headers.get("X-CSRF-Token") != token:
            raise web.HTTPForbidden()
        contact_path = re.fullmatch(r"telephone/contacts/([1-9][0-9]{0,17})", path)
        if contact_path and request.method in ("PATCH", "DELETE"):
            try:
                if request.method == "PATCH":
                    body = await request.json()
                    if not isinstance(body, dict) or set(body) != {"name"}:
                        raise ValueError("This contact operation changes the name only")
                    history.rename_contact(int(contact_path[1]), body["name"])
                else:
                    history.remove_contact(int(contact_path[1]))
            except KeyError:
                raise web.HTTPNotFound() from None
            except ValueError as error:
                return web.json_response({"message": str(error)}, status=400)
            contacts.clear()
            contacts.update(history.contacts())
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
                saved = history.update_preferences(await request.json(), display_name)
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
                if address.lower() in contacts:
                    return web.json_response({"message": "That LXMF address is already saved"}, status=409)
                history.ensure_contact(address.lower(), name.strip())
                contacts.update(history.contacts())
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
                try:
                    fields = attachment_fields.outgoing(draft.get("fields") or {}, content)
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
                try:
                    message = await asyncio.to_thread(probe.compose, content, bytes.fromhex(address), fields)
                    message.pack()
                except TimeoutError as exc:
                    return web.json_response({"message": str(exc)}, status=504)

                def state_changed(updated, state):
                    loop.call_soon_threadsafe(schedule, "lxmf_message_state_updated", record(updated, state))

                message.register_delivery_callback(lambda updated: state_changed(updated, "delivered"))
                message.register_failed_callback(lambda updated: state_changed(updated, "failed"))
                row = history.save(address, record(message, "sending"))
                try:
                    probe.send(message)
                except Exception:
                    await publish("lxmf_message_state_updated", {**row, "state": "failed"})
                    return web.json_response({"message": "Could not queue the message"}, status=502)
                return web.json_response({"lxmf_message": attachment_fields.slim(row)})
        raise web.HTTPNotFound()

    async def websocket(request):
        client = web.WebSocketResponse()
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
        finally:
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
    app.router.add_route("*", "/api/v1/{path:.*}", api)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/", index)
    app.router.add_get("/service-worker.js", disable_service_worker)
    app.router.add_static("/", frontend)
    runner = web.AppRunner(app, access_log=None, handle_signals=False)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        host, port = runner.addresses[0]
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
            await announce_routes()
            await asyncio.sleep(1)
    finally:
        access.clear_info()
        if meshcore:
            try:
                async with asyncio.timeout(30):
                    await meshcore.close()
            except (TimeoutError, ConnectionError, RuntimeError):
                pass
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
        asyncio.run(serve(ready, resources / "frontend", fixture, device=fixture != simulator,
                          peer_settings=overrides, meshcore_factory=NextMeshCore, sip_factory=NextSIPRuntime))
    except Exception as error:
        ready.with_suffix(".error").write_text(str(error), encoding="utf-8")
        raise
