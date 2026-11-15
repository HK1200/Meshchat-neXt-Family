"""Serve the released neXt frontend with an embedded simulator LXMF backend."""

import asyncio
from datetime import datetime, timezone
import json
import secrets
from pathlib import Path

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


async def serve(ready_file, frontend, fixture, *, device=False):
    loop = asyncio.get_running_loop()
    messages = {}
    clients = set()
    tasks = set()

    async def publish(kind, row):
        messages[row["hash"]] = row
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
    token = secrets.token_urlsafe(32)
    contact = "Test contact" if device else "Simulator Echo"
    conversation = {"destination_hash": peer, "display_name": contact, "unread_count": 0}
    display_name = "neXt iOS" if device else "neXt Simulator"
    config = {"lxmf_address_hash": own, "identity_hash": own, "display_name": display_name}
    responses = {
        "status": {"status": "ok", "network_ready": True, "ui_ready": True},
        "auth/status": {"auth_enabled": False, "authenticated": True},
        "auth/csrf": {"csrf_token": token},
        "config": {"config": config},
        "lxmf/conversations": {"conversations": [conversation]},
        "lxmf/conversation-pins": {"pinned_destination_hashes": []},
        "lxmf/folders": {"folders": []},
        f"destination/{peer}/custom-display-name": {"custom_display_name": None},
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
            if path in responses:
                return web.json_response(responses[path])
            if path == f"lxmf-messages/conversation/{peer}":
                return web.json_response({"lxmf_messages": list(messages.values())})
        if request.method == "POST":
            if request.headers.get("X-CSRF-Token") != token:
                raise web.HTTPForbidden()
            if path == f"lxmf/conversations/{peer}/mark-as-read":
                return web.json_response({"status": "success"})
            if path == "lxmf-messages/send":
                body = await request.json()
                draft = body.get("lxmf_message") or {}
                content = draft.get("content")
                if (draft.get("destination_hash") != peer or not isinstance(content, str)
                        or not content.strip() or draft.get("fields") or draft.get("reply_to_hash")):
                    return web.json_response({"message": f"Only plain texts to {contact} are supported"}, status=400)
                try:
                    message = await asyncio.to_thread(probe.compose, content)
                    message.pack()
                except TimeoutError as exc:
                    return web.json_response({"message": str(exc)}, status=504)

                def state_changed(updated, state):
                    loop.call_soon_threadsafe(schedule, "lxmf_message_state_updated", record(updated, state))

                message.register_delivery_callback(lambda updated: state_changed(updated, "delivered"))
                message.register_failed_callback(lambda updated: state_changed(updated, "failed"))
                row = record(message, "sending")
                messages[row["hash"]] = row
                probe.send(message)
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
