"""Durable neXt conversation organization using the desktop API contracts.

These are local labels only. They never create contacts, approve a caller,
subscribe a sender to push, or transmit an announce/message.
"""

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone

from aiohttp import web

PREFIX = "/api/v1/lxmf"


def peer(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Enter a Reticulum messaging address")
    return value


def identifier(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("Invalid folder identifier")
    return value


def name(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > 120
        or len(value.encode("utf-8")) > 512
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError(
            "Use a folder name of at most 120 characters without control characters"
        )
    return value.strip()


class ConversationOrganization:
    def __init__(self, history, *, cancel_outbound=None):
        self.history = history
        self.cancel_outbound = cancel_outbound
        self.db = history.db
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS lxmf_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lxmf_conversation_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, peer_hash TEXT NOT NULL UNIQUE,
                    folder_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS next_conversation_folder ON lxmf_conversation_folders(folder_id);
                CREATE TABLE IF NOT EXISTS lxmf_conversation_pins (
                    peer_hash TEXT PRIMARY KEY, pinned_at INTEGER NOT NULL
                );
            """)

    def folders(self):
        return [
            dict(zip(("id", "name", "created_at", "updated_at"), row))
            for row in self.db.execute(
                "SELECT id, name, created_at, updated_at FROM lxmf_folders ORDER BY name, id"
            )
        ]

    def _folder(self, folder_id):
        folder_id = identifier(folder_id)
        if not self.db.execute(
            "SELECT 1 FROM lxmf_folders WHERE id = ?", (folder_id,)
        ).fetchone():
            raise KeyError(folder_id)
        return folder_id

    def _unique_name(self, value, exclude=None):
        value = name(value)
        row = self.db.execute(
            "SELECT id FROM lxmf_folders WHERE name = ?", (value,)
        ).fetchone()
        if row and row[0] != exclude:
            raise ValueError("A folder with this name already exists")
        return value

    def create(self, value):
        value = self._unique_name(value)
        if self.db.execute("SELECT COUNT(*) FROM lxmf_folders").fetchone()[0] >= 256:
            raise ValueError("At most 256 conversation folders may be saved")
        stamp = datetime.now(timezone.utc).isoformat()
        with self.db:
            return self.db.execute(
                "INSERT INTO lxmf_folders(name, created_at, updated_at) VALUES (?, ?, ?)",
                (value, stamp, stamp),
            ).lastrowid

    def rename(self, folder_id, value):
        folder_id = self._folder(folder_id)
        value = self._unique_name(value, folder_id)
        with self.db:
            self.db.execute(
                "UPDATE lxmf_folders SET name = ?, updated_at = ? WHERE id = ?",
                (value, datetime.now(timezone.utc).isoformat(), folder_id),
            )

    def delete(self, folder_id):
        folder_id = self._folder(folder_id)
        with self.db:
            self.db.execute(
                "DELETE FROM lxmf_conversation_folders WHERE folder_id = ?",
                (folder_id,),
            )
            self.db.execute("DELETE FROM lxmf_folders WHERE id = ?", (folder_id,))

    def pins(self):
        return [
            row[0]
            for row in self.db.execute(
                "SELECT peer_hash FROM lxmf_conversation_pins ORDER BY pinned_at DESC, peer_hash"
            )
        ]

    def toggle(self, address):
        address = peer(address)
        with self.db:
            exists = self.db.execute(
                "SELECT 1 FROM lxmf_conversation_pins WHERE peer_hash = ?", (address,)
            ).fetchone()
            if exists:
                self.db.execute(
                    "DELETE FROM lxmf_conversation_pins WHERE peer_hash = ?", (address,)
                )
            else:
                self.db.execute(
                    "INSERT INTO lxmf_conversation_pins VALUES (?, ?)",
                    (address, time.time_ns()),
                )
        return not bool(exists)

    def _move(self, addresses, folder_id):
        stamp = datetime.now(timezone.utc).isoformat()
        for address in addresses:
            if folder_id is None:
                self.db.execute(
                    "DELETE FROM lxmf_conversation_folders WHERE peer_hash = ?",
                    (address,),
                )
            else:
                self.db.execute(
                    """INSERT INTO lxmf_conversation_folders(peer_hash, folder_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?) ON CONFLICT(peer_hash) DO UPDATE SET
                    folder_id = excluded.folder_id, updated_at = excluded.updated_at
                    WHERE lxmf_conversation_folders.folder_id <> excluded.folder_id""",
                    (address, folder_id, stamp, stamp),
                )

    def move(self, addresses, folder_id):
        if not isinstance(addresses, list) or not 0 < len(addresses) <= 1000:
            raise ValueError("Select between 1 and 1000 conversations")
        addresses = [peer(address) for address in addresses]
        if folder_id is not None:
            folder_id = self._folder(folder_id)
        with self.db:
            self._move(addresses, folder_id)

    def delete_conversations(self, addresses):
        pending = self.history.delete_conversations(addresses)
        if self.cancel_outbound is not None:
            for message_hash in pending:
                try:
                    if re.fullmatch(r"[a-f0-9]{64}", message_hash):
                        self.cancel_outbound(bytes.fromhex(message_hash))
                except Exception:
                    # History is already committed locally. A transport
                    # callback cannot restore it even if cancellation fails.
                    logging.getLogger(__name__).warning(
                        "A queued message could not be cancelled during local history removal"
                    )

    def export(self):
        return {
            "folders": self.folders(),
            "mappings": [
                dict(
                    zip(
                        ("id", "peer_hash", "folder_id", "created_at", "updated_at"),
                        row,
                    )
                )
                for row in self.db.execute(
                    "SELECT id, peer_hash, folder_id, created_at, updated_at FROM lxmf_conversation_folders ORDER BY id"
                )
            ],
        }

    def import_(self, body):
        if not isinstance(body, dict) or set(body) != {"folders", "mappings"}:
            raise ValueError("Choose an exported folder document")
        folders, mappings = body["folders"], body["mappings"]
        if (
            not isinstance(folders, list)
            or len(folders) > 256
            or not isinstance(mappings, list)
            or len(mappings) > 1000
        ):
            raise ValueError("The folder document is too large")
        names = {}
        for row in folders:
            if not isinstance(row, dict):
                raise ValueError("Invalid folder entry")
            old_id, label = identifier(row.get("id")), name(row.get("name"))
            if old_id in names or label in names.values():
                raise ValueError("Duplicate exported folder")
            names[old_id] = label
        assignments = []
        for row in mappings:
            if (
                not isinstance(row, dict)
                or type(row.get("folder_id")) is not int
                or row["folder_id"] not in names
            ):
                raise ValueError("A mapping references an unknown folder")
            assignments.append((peer(row.get("peer_hash")), row["folder_id"]))
        existing = {row["name"]: row["id"] for row in self.folders()}
        if len(set(existing) | set(names.values())) > 256:
            raise ValueError("At most 256 conversation folders may be saved")
        # Validate the whole document first; a failed write rolls back every
        # folder and assignment rather than leaving a partial import.
        stamp = datetime.now(timezone.utc).isoformat()
        with self.db:
            for label in names.values():
                if label not in existing:
                    existing[label] = self.db.execute(
                        "INSERT INTO lxmf_folders(name, created_at, updated_at) VALUES (?, ?, ?)",
                        (label, stamp, stamp),
                    ).lastrowid
            for address, old_id in assignments:
                self._move([address], existing[names[old_id]])

    @staticmethod
    def _number(query, key, default, maximum, *, zero=True):
        text = query.get(key)
        if text is None:
            return default
        if not isinstance(text, str) or not re.fullmatch(r"[0-9]{1,10}", text):
            raise ValueError("Invalid conversation pagination")
        value = int(text)
        if not (0 if zero else 1) <= value <= maximum:
            raise ValueError("Invalid conversation pagination")
        return value

    def conversations(self, query):
        limit = self._number(query, "limit", 50, 200, zero=False)
        offset = self._number(query, "offset", 0, 1_000_000)
        search = query.get("search", query.get("q", "")).strip().casefold()
        if len(search) > 256:
            raise ValueError("Search is too long")

        def flag(primary, alternate):
            value = query.get(primary, query.get(alternate, "false"))
            if value not in ("true", "false", "1", "0"):
                raise ValueError("Invalid conversation filter")
            return value in ("true", "1")

        unread = flag("unread", "filter_unread")
        failed = flag("failed", "filter_failed")
        attachments = flag("has_attachments", "filter_has_attachments")
        folder_id = self._number(query, "folder_id", None, 2**31 - 1)
        assignments = {
            row[0]: row[1]
            for row in self.db.execute(
                "SELECT peer_hash, folder_id FROM lxmf_conversation_folders"
            )
        }
        pinned = self.pins()
        pin_order = {
            address: len(pinned) - index for index, address in enumerate(pinned)
        }
        pins = set(pinned)
        rows = []
        for address, entry in self.history.conversation_entries().items():
            assigned = assignments.get(address)
            if folder_id is not None and (
                assigned is not None if folder_id == 0 else assigned != folder_id
            ):
                continue
            summary = self.history.summary(address)
            if (
                unread
                and not summary["is_unread"]
                or failed
                and not summary["failed_messages_count"]
            ):
                continue
            if (
                search
                and search
                not in " ".join(
                    str(value or "")
                    for value in (
                        address,
                        entry["name"],
                        summary["latest_message_preview"],
                        summary["latest_message_title"],
                    )
                ).casefold()
            ):
                continue
            if (
                attachments
                and not self.db.execute(
                    "SELECT 1 FROM messages WHERE peer = ? AND "
                    + self.history.VISIBLE
                    + " AND (json_type(payload, '$.fields.image') = 'object' OR json_array_length(payload, '$.fields.file_attachments') > 0) LIMIT 1",
                    (address,),
                ).fetchone()
            ):
                continue
            rows.append(
                {
                    "destination_hash": address,
                    "display_name": entry["name"],
                    "is_contact": entry["is_contact"],
                    "folder_id": assigned,
                    "is_pinned": address in pins,
                    **summary,
                }
            )
        rows.sort(
            key=lambda row: (
                row["is_pinned"],
                pin_order.get(row["destination_hash"], 0),
                row["updated_at"] or "",
                row["destination_hash"],
            ),
            reverse=True,
        )
        return {"conversations": rows[offset : offset + limit]}

    async def _body(self, request, *, importing=False, bulk=False):
        limit = 1024 * 1024 if importing else 64 * 1024 if bulk else 4096
        body = bytearray()
        async for chunk in request.content.iter_chunked(4096):
            body.extend(chunk)
            if len(body) > limit:
                raise web.HTTPRequestEntityTooLarge(
                    max_size=limit, actual_size=len(body)
                )
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value

    async def handle(self, request):
        path = request.path.removeprefix(PREFIX)
        try:
            if request.method == "GET":
                if path == "/folders":
                    return web.json_response(self.folders())
                if path == "/folders/export":
                    return web.json_response(self.export())
                if path == "/conversation-pins":
                    return web.json_response({"peer_hashes": self.pins()})
                if path == "/conversations":
                    return web.json_response(self.conversations(request.query))
            if path == "/folders" and request.method == "POST":
                data = await self._body(request)
                self.create(data.get("name"))
                result = "Folder created"
            elif path == "/folders/import" and request.method == "POST":
                self.import_(await self._body(request, importing=True))
                result = "Folders and mappings imported"
            elif path == "/conversation-pins/toggle" and request.method == "POST":
                data = await self._body(request)
                pinned = self.toggle(data.get("destination_hash"))
                return web.json_response({"peer_hashes": self.pins(), "pinned": pinned})
            elif path == "/conversations/move-to-folder" and request.method == "POST":
                data = await self._body(request, bulk=True)
                self.move(data.get("peer_hashes"), data.get("folder_id"))
                result = "Conversations moved"
            elif path == "/conversations/bulk-delete" and request.method == "POST":
                data = await self._body(request, bulk=True)
                if set(data) != {"destination_hashes"}:
                    raise ValueError("Select conversations to delete")
                self.delete_conversations(data["destination_hashes"])
                result = "Conversations deleted"
            elif re.fullmatch(r"/folders/[1-9][0-9]{0,17}", path):
                folder_id = int(path.rsplit("/", 1)[1])
                if request.method == "PATCH":
                    self.rename(folder_id, (await self._body(request)).get("name"))
                    result = "Folder renamed"
                elif request.method == "DELETE":
                    self.delete(folder_id)
                    result = "Folder deleted"
                else:
                    raise web.HTTPMethodNotAllowed(request.method, ["PATCH", "DELETE"])
            else:
                raise web.HTTPNotFound()
            return web.json_response({"message": result})
        except KeyError:
            raise web.HTTPNotFound() from None
        except (ValueError, TypeError, UnicodeError, RecursionError) as error:
            return web.json_response({"message": str(error)}, status=400)
        except sqlite3.Error:
            return web.json_response(
                {
                    "message": "Conversation settings could not be saved. Previous settings are preserved."
                },
                status=503,
            )

    def register(self, router):
        for path in (
            "/folders",
            "/folders/export",
            "/conversation-pins",
            "/conversations",
        ):
            router.add_get(PREFIX + path, self.handle)
        for path in (
            "/folders",
            "/folders/import",
            "/conversation-pins/toggle",
            "/conversations/move-to-folder",
            "/conversations/bulk-delete",
        ):
            router.add_post(PREFIX + path, self.handle)
        for method in ("PATCH", "DELETE"):
            router.add_route(method, PREFIX + "/folders/{id}", self.handle)
