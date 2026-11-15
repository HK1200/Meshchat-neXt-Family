"""Serve the released neXt frontend with an embedded LXMF backend."""

import asyncio
from datetime import datetime, timezone
import json
import os
import re
import secrets
import sqlite3
from pathlib import Path

# iPadOS terminates sandboxed apps that call sendfile. Configure aiohttp
# before importing it so both the simulator and device use buffered reads.
os.environ["AIOHTTP_NOSENDFILE"] = "1"

from aiohttp import web

from messaging_probe import MessagingProbe


def record(message, state):
    return {
        "hash": message.hash.hex(),
        "source_hash": message.source_hash.hex(),
        "destination_hash": message.destination_hash.hex(),
        "content": message.content_as_string(),
        "title": "",
        "fields": {},
        "state": state,
        "method": "direct",
        "created_at": datetime.fromtimestamp(message.timestamp, timezone.utc).isoformat(),
        "progress": 100 if state == "delivered" else 0,
        "is_outbound": state != "received",
    }


class ConversationHistory:
    def __init__(self, path):
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
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY,
                    lxmf_address TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL
                )
            """)
            # The preview has no persistent outbound queue. A send interrupted
            # by app termination is left visible as failed.
            self.db.execute("""
                UPDATE messages SET state = 'failed' WHERE state = 'sending'
            """)

    def ensure_contact(self, address, name):
        with self.db:
            self.db.execute(
                "INSERT INTO contacts(lxmf_address, name) VALUES (?, ?) ON CONFLICT(lxmf_address) DO NOTHING",
                (address, name),
            )

    def contacts(self):
        return {
            address: {"id": contact_id, "lxmf_address": address, "name": name}
            for contact_id, address, name in self.db.execute(
                "SELECT id, lxmf_address, name FROM contacts ORDER BY name COLLATE NOCASE, id"
            )
        }

    def save(self, peer, row):
        with self.db:
            payload = json.dumps({k: v for k, v in row.items() if k not in ("id", "state")})
            self.db.execute("""
                INSERT INTO messages(hash, peer, state, payload) VALUES (?, ?, ?, ?)
                ON CONFLICT(hash) DO UPDATE SET state = excluded.state, payload = excluded.payload
            """, (row["hash"], peer, row["state"], payload))
            message_id, = self.db.execute(
                "SELECT id FROM messages WHERE hash = ?", (row["hash"],)
            ).fetchone()
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

    def delete(self, message_hash):
        with self.db:
            row = self.db.execute("SELECT state FROM messages WHERE hash = ?",
                                  (message_hash,)).fetchone()
            if row is None:
                raise KeyError(message_hash)
            if row[0] == "sending":
                raise ValueError("Message is still sending")
            self.db.execute("DELETE FROM messages WHERE hash = ?", (message_hash,))

    def close(self):
        self.db.close()


async def serve(ready_file, frontend, fixture, *, device=False):
    loop = asyncio.get_running_loop()
    clients = set()
    tasks = set()

    async def publish(kind, row):
        address = row["destination_hash"] if row["is_outbound"] else row["source_hash"]
        if address not in contacts:
            return
        row = history.save(address, row)
        for client in tuple(clients):
            try:
                await client.send_json({"type": kind, "lxmf_message": row})
            except (ConnectionError, RuntimeError):
                clients.discard(client)

    def schedule(kind, row):
        task = asyncio.create_task(publish(kind, row))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def inbound(message):
        loop.call_soon_threadsafe(schedule, "lxmf.delivery", record(message, "received"))

    settings = json.loads(fixture.read_text(encoding="utf-8"))
    probe = MessagingProbe(settings, ready_file.parent, inbound, device=device)
    peer = probe.address.hex()
    own = probe.source.hash.hex()
    history = ConversationHistory(ready_file.parent / f"messages-{own}.sqlite3" if device else ":memory:")
    token = secrets.token_urlsafe(32)
    contact = "Test contact" if device else "Simulator Echo"
    history.ensure_contact(peer, contact)
    contacts = history.contacts()
    display_name = "neXt iOS" if device else "neXt Simulator"
    config = {"lxmf_address_hash": own, "identity_hash": own, "display_name": display_name}
    responses = {
        "status": {"status": "ok", "network_ready": True, "ui_ready": True},
        "auth/status": {"auth_enabled": False, "authenticated": True},
        "auth/csrf": {"csrf_token": token},
        "config": {"config": config},
        "lxmf/conversation-pins": {"pinned_destination_hashes": []},
        "lxmf/folders": {"folders": []},
    }

    @web.middleware
    async def local_only(request, handler):
        if request.host != authority:
            raise web.HTTPBadRequest()
        if request.headers.get("Origin") not in (None, f"http://{authority}"):
            raise web.HTTPForbidden()
        return await handler(request)

    async def api(request):
        path = request.match_info["path"]
        if request.method == "GET":
            if device and path == "preview/reticulum-connection":
                return web.json_response(
                    {"connected": probe.online},
                    headers={"Cache-Control": "no-store"},
                )
            if path in responses:
                return web.json_response(responses[path])
            if path == "lxmf/conversations":
                return web.json_response({"conversations": [
                    {
                        "destination_hash": address,
                        "display_name": entry["name"],
                        "is_contact": True,
                        "unread_count": 0,
                    }
                    for address, entry in contacts.items()
                ]})
            if path == "telephone/contacts":
                return web.json_response({"contacts": list(contacts.values()), "total_count": len(contacts)})
            if path.startswith("telephone/contacts/check/"):
                entry = contacts.get(path.rsplit("/", 1)[1])
                return web.json_response({"is_contact": entry is not None, "contact": entry, "id": entry["id"] if entry else None})
            if path.startswith("lxmf-messages/conversation/"):
                address = path.rsplit("/", 1)[1]
                if address not in contacts:
                    return web.json_response({"lxmf_messages": []})
                try:
                    return web.json_response({"lxmf_messages": history.page(address, request.query)})
                except (ValueError, OverflowError):
                    raise web.HTTPBadRequest(text="Invalid history pagination")
        if request.method in ("POST", "DELETE") and request.headers.get("X-CSRF-Token") != token:
            raise web.HTTPForbidden()
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
            if path == "telephone/contacts" and device:
                body = await request.json()
                if not isinstance(body, dict):
                    raise web.HTTPBadRequest(text="Expected a contact object")
                address = body.get("lxmf_address")
                name = body.get("name")
                if (not isinstance(address, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", address)
                        or address.lower() == own or not isinstance(name, str)
                        or not name.strip() or len(name.strip()) > 120):
                    return web.json_response({"message": "Enter a name and a valid LXMF address"}, status=400)
                if address.lower() in contacts:
                    return web.json_response({"message": "That LXMF address is already saved"}, status=409)
                history.ensure_contact(address.lower(), name.strip())
                contacts.update(history.contacts())
                return web.json_response({"message": "Contact added"})
            if path.startswith("lxmf/conversations/") and path.endswith("/mark-as-read"):
                return web.json_response({"status": "success"})
            if path == "lxmf-messages/send":
                body = await request.json()
                draft = body.get("lxmf_message") if isinstance(body, dict) else None
                if not isinstance(draft, dict):
                    raise web.HTTPBadRequest(text="Expected an LXMF message object")
                content = draft.get("content")
                address = draft.get("destination_hash")
                if (not isinstance(address, str) or address not in contacts or not isinstance(content, str)
                        or not content.strip() or draft.get("fields") or draft.get("reply_to_hash")):
                    return web.json_response({"message": "Only plain texts to saved LXMF contacts are supported"}, status=400)
                try:
                    message = await asyncio.to_thread(probe.compose, content, bytes.fromhex(address))
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
                return web.json_response({"lxmf_message": row})
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
            "Content-Security-Policy": "frame-ancestors 'none'; object-src 'none'; base-uri 'none'",
        }
        return web.FileResponse(frontend / "index.html", headers=headers)

    async def disable_service_worker(request):
        # The embedded host is recreated on each launch and serves its assets locally.
        raise web.HTTPNotFound()

    app = web.Application(middlewares=[local_only])
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
        staging = ready_file.with_suffix(".tmp")
        staging.write_text(f"http://{authority}/#/messages/{peer}", encoding="utf-8")
        if device:
            ready_file.with_suffix(".address").write_text(own, encoding="utf-8")
        staging.replace(ready_file)
        if device:
            # Announce only after the TCP link comes up, including after reconnect.
            online = False
            while True:
                connected = probe.online
                if connected and not online:
                    await asyncio.to_thread(probe.source.announce)
                online = connected
                await asyncio.sleep(1)
        else:
            await asyncio.Future()
    finally:
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
        asyncio.run(serve(ready, resources / "frontend", fixture, device=fixture != simulator))
    except Exception as error:
        ready.with_suffix(".error").write_text(str(error), encoding="utf-8")
        raise
