"""Real loopback sockets recover without replacing the application or its access key."""
import asyncio
from pathlib import Path
import socket
import sys

import pytest
from aiohttp import ClientSession, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe'))
from loopback_listener import ResumableListener


def test_reclaimed_listener_recovers_on_the_same_port_and_keeps_private_state():
    async def run():
        epoch = [0]
        retained = {"message": "private saved fixture", "session": "synthetic-session"}
        async def status(request):
            if request.headers.get("X-Session") != retained["session"]:
                raise web.HTTPForbidden()
            return web.json_response(retained)
        app = web.Application(); app.router.add_get('/status', status)
        runner = web.AppRunner(app); await runner.setup()
        listener = ResumableListener(runner, lambda: epoch[0])
        try:
            host, port = await listener.start()
            assert host == '127.0.0.1'
            endpoint = f'http://{host}:{port}/status'
            async with ClientSession() as client:
                async with client.get(endpoint, headers={'X-Session': retained['session']}) as response:
                    assert await response.json() == retained
                assert not await listener.recover()
                # Simulate a listener whose transport no longer accepts connections.
                listener.site._server.close(); await listener.site._server.wait_closed()
                with pytest.raises(OSError):
                    await asyncio.open_connection(host, port)
                epoch[0] += 1
                assert await listener.recover()
                assert listener.port == port
                async with client.get(endpoint, headers={'X-Session': retained['session']}) as response:
                    assert response.status == 200 and await response.json() == retained
                async with client.get(endpoint, headers={'X-Session': 'stale-token'}) as response:
                    assert response.status == 403
                assert not await listener.recover()
        finally:
            await runner.cleanup()
    asyncio.run(run())


def test_a_failed_resume_bind_can_retry_without_losing_its_requested_generation():
    async def run():
        epoch = [0]; app = web.Application(); runner = web.AppRunner(app)
        await runner.setup(); listener = ResumableListener(runner, lambda: epoch[0])
        blocker = socket.socket(); blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            host, port = await listener.start()
            await listener.site.stop(); listener.site = None
            blocker.bind((host, port)); blocker.listen()
            epoch[0] = 1
            with pytest.raises(OSError): await listener.recover()
            assert listener.seen == 0 and listener.port == port
            blocker.close()
            assert await listener.recover()
            reader, writer = await asyncio.open_connection(host, port)
            writer.close(); await writer.wait_closed()
            assert listener.seen == 1
        finally:
            blocker.close(); await runner.cleanup()
    asyncio.run(run())


def test_repeated_resume_does_not_accumulate_listeners_or_file_descriptors():
    async def run():
        epoch = [0]; runner = web.AppRunner(web.Application()); await runner.setup()
        listener = ResumableListener(runner, lambda: epoch[0])
        try:
            await listener.start()
            baseline = len(list(Path('/proc/self/fd').iterdir())) if Path('/proc/self/fd').exists() else None
            for _ in range(25):
                epoch[0] += 1
                assert await listener.recover()
                assert len(runner.addresses) == 1
                assert runner.addresses[0] == ('127.0.0.1', listener.port)
            if baseline is not None:
                assert len(list(Path('/proc/self/fd').iterdir())) <= baseline + 1
        finally:
            await runner.cleanup()
    asyncio.run(run())
