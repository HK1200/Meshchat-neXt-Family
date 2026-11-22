# SPDX-License-Identifier: 0BSD
"""Private test-only TCP proxy: hold upstream bytes without altering them."""
import asyncio
import concurrent.futures
import threading

class GatedProxy:
    def __init__(self, port, target, host='127.0.0.1'):
        self.port, self.target, self.host = port, target, host
        self.held = threading.Event()
        self.started = concurrent.futures.Future()
        self.forwarded = [0, 0]
        self.tasks = set()
    async def accept(self, reader, writer):
        task = asyncio.current_task(); self.tasks.add(task)
        upstream = None; flows = []
        try:
            target_reader, upstream = await asyncio.open_connection('127.0.0.1', self.target)
            async def flow(source, destination, direction):
                while data := await source.read(4096):
                    while direction == 0 and self.held.is_set():
                        await asyncio.sleep(.01)
                    destination.write(data); await destination.drain()
                    self.forwarded[direction] += len(data)
            flows = [asyncio.create_task(flow(reader, upstream, 0)),
                     asyncio.create_task(flow(target_reader, writer, 1))]
            done, _ = await asyncio.wait(flows, return_when=asyncio.FIRST_COMPLETED)
            for completed in done: completed.result()
        except (OSError, ConnectionError): pass
        finally:
            for flow in flows: flow.cancel()
            await asyncio.gather(*flows, return_exceptions=True)
            for stream in (writer, upstream):
                if stream:
                    stream.close()
                    try: await stream.wait_closed()
                    except OSError: pass
            self.tasks.discard(task)
    async def serve(self):
        self.loop = asyncio.get_running_loop(); self.done = asyncio.Event()
        try:
            server = await asyncio.start_server(self.accept, self.host, self.port)
            self.started.set_result(server.sockets[0].getsockname()[1])
        except BaseException as error:
            self.started.set_exception(error); raise
        await self.done.wait()
        server.close()
        for task in tuple(self.tasks): task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        await server.wait_closed()
    def start(self):
        self.thread = threading.Thread(target=lambda:asyncio.run(self.serve()), daemon=True)
        self.thread.start(); self.port = self.started.result(timeout=10); return self
    def close(self):
        self.loop.call_soon_threadsafe(self.done.set)
        self.thread.join(timeout=10)
        if self.thread.is_alive(): raise RuntimeError('Private proxy did not close')
