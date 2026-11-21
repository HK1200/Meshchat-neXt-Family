"""Recreate only the local HTTP listener after iOS reclaims a suspended socket."""
from aiohttp import web


def recovery_generation():
    try:
        from _next_lifecycle import generation
    except ImportError:
        return 0
    return generation()


class ResumableListener:
    def __init__(self, runner, generation=recovery_generation):
        self.runner = runner
        self.generation = generation
        self.seen = generation()
        self.site = None
        self.port = None

    async def start(self):
        candidate = web.TCPSite(self.runner, "127.0.0.1", self.port or 0)
        try:
            await candidate.start()
        except BaseException:
            await candidate.stop()
            raise
        self.site = candidate
        if self.port is None:
            self.port = self.runner.addresses[0][1]
        return "127.0.0.1", self.port

    async def recover(self):
        current = self.generation()
        if current == self.seen:
            return False
        if self.site is not None:
            await self.site.stop()
            self.site = None
        # Mark success only after binding. A transient failure is retried by
        # the next tick without changing identity, history or session tokens.
        await self.start()
        self.seen = current
        return True
