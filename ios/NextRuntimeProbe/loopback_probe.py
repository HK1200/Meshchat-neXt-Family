"""Exercise the HTTP and Reticulum imports separately from neXt's desktop startup."""

import asyncio
from html import escape
import importlib
import secrets
import socket
from pathlib import Path

from aiohttp import web


async def start():
    # Reserve the ephemeral port before passing the listening socket to aiohttp.
    # Keeping socket ownership here avoids a bind-close-rebind race.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    runner = None
    try:
        listener.bind(("127.0.0.1", 0))
        host, port = listener.getsockname()
        authority = f"{host}:{port}"
        route = f"/{secrets.token_urlsafe(24)}"
        runtime = {
            name: getattr(importlib.import_module(name), "__version__", "imported")
            for name in ("aiohttp", "RNS", "LXMF")
        }

        async def health(request):
            if request.host != authority:
                raise web.HTTPBadRequest()
            headers = {
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            }
            if "text/html" in request.headers.get("Accept", ""):
                report = "".join(f"<li>{escape(name)} {escape(str(version))}</li>"
                                 for name, version in runtime.items())
                return web.Response(
                    text=f"<!doctype html><html lang='en'><meta charset='utf-8'>"
                         f"<title>neXt runtime</title><h1>neXt runtime ready</h1><ul>{report}</ul></html>",
                    content_type="text/html", headers=headers,
                )
            return web.json_response(runtime, headers=headers)

        app = web.Application()
        app.router.add_get(route, health)
        runner = web.AppRunner(app, access_log=None, handle_signals=False)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        return runner, f"http://{authority}{route}"
    except BaseException:
        if runner is not None:
            await runner.cleanup()
        listener.close()
        raise


async def serve(ready_file=None):
    runner, url = await start()
    try:
        if ready_file is None:
            print(url, flush=True)
        else:
            ready = Path(ready_file)
            staging = ready.with_suffix(".tmp")
            staging.write_text(url, encoding="utf-8")
            staging.replace(ready)
        await asyncio.Future()
    finally:
        await runner.cleanup()


def run_for_app(ready_file):
    asyncio.run(serve(ready_file))


if __name__ == "__main__":
    asyncio.run(serve())
