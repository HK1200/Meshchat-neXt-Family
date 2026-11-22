"""Native Reticulum location sessions, with no public broadcast or mailbox copy."""
import asyncio
import json
from pathlib import Path
import sqlite3

from aiohttp import web
from location_sessions import LocationSessions


class LocationRuntime:
    def __init__(self, folder, probe, history, telemetry, *, native=None):
        self.probe, self.history, self.telemetry = probe, history, telemetry
        folder = Path(folder) / 'native-location'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = folder / 'sessions.sqlite3'
        self.database = sqlite3.connect(path)
        path.chmod(0o600)
        self.native = native or self._native
        self.manager = LocationSessions(self.database, self.catalog, self.native, self.transmit)

    async def _native(self, request):
        import _next_location
        result = await asyncio.to_thread(_next_location.request, json.dumps(request, allow_nan=False))
        if not isinstance(result, str) or len(result) > 16384:
            raise RuntimeError('Invalid native location response')
        return json.loads(result)

    async def catalog(self):
        if self.telemetry.settings()['location_source'] != 'browser': return {}
        identity = self.probe.source.identity.hash.hex()
        return {f'reticulum:{identity}:{address}': dict(
            name=row['name'], service='reticulum', online=self.probe.online, address=address)
            for address, row in self.history.conversation_entries().items()}

    async def transmit(self, target, fix, guard):
        from telemetry_runtime import outbound
        # The shipped neXt location UI converts CoreLocation/browser m/s to
        # the kilometres-per-hour value used by its standard telemetry.
        wire_fix = {**fix, 'speed': fix.get('speed', 0) * 3.6}
        fields = {'telemetry': {'location': wire_fix}}
        _, packed = outbound(fields)
        message = await asyncio.to_thread(self.probe.compose, '', bytes.fromhex(target['address']), packed,
                                          delivery_method='direct', propagation_node=None)
        if not await guard(): return False
        # A path search may have taken many seconds. Validate the original fix
        # again, and never copy private live telemetry to an offline mailbox.
        outbound(fields)
        message.pack()
        self.probe.send(message)
        return True

    async def tick(self):
        try:
            await self.manager.tick()
        except (RuntimeError, OSError, sqlite3.Error):
            self.manager.error = 'Location sharing could not refresh. Check permissions and saved recipients.'
            # No GPS or delivery should survive an unhandled settings failure.
            self.manager.armed = False
            self.manager._cancel(list(self.manager.workers))
            try: await self.manager._native('suspend', {})
            except (RuntimeError, OSError): pass

    async def close(self):
        try: await self.manager.close()
        finally: self.database.close()

    def register(self, router):
        async def handle(request):
            try:
                if request.method == 'GET': result = await self.manager.snapshot()
                else:
                    if request.content_length is not None and request.content_length > 4096:
                        raise ValueError('Location controls are too large')
                    raw = bytearray()
                    async for part in request.content.iter_chunked(4096):
                        raw.extend(part)
                        if len(raw) > 4096: raise ValueError('Location controls are too large')
                    payload = json.loads(raw)
                    if not isinstance(payload, dict): raise ValueError('Choose a location action')
                    action = payload.get('action')
                    if action == 'start':
                        if set(payload) - {'action', 'targets', 'duration', 'background', 'request_id', 'consent_epoch', 'deadline'}:
                            raise ValueError('Unsupported sharing controls')
                        result = await self.manager.start(payload.get('targets'), payload.get('duration'),
                            background=payload.get('background', False), request_id=payload.get('request_id'),
                            consent_epoch=payload.get('consent_epoch'), deadline=payload.get('deadline'))
                    elif action == 'stop':
                        if set(payload) - {'action', 'target', 'request_id'}: raise ValueError('Unsupported stop controls')
                        result = await self.manager.stop(payload.get('target'), payload.get('request_id'))
                    elif action == 'resume' and set(payload) == {'action'}:
                        await self.manager.resume(); result = await self.manager.snapshot()
                    else: raise ValueError('Choose Start, Stop or Resume')
                return web.json_response(result, headers={'Cache-Control': 'no-store'})
            except (ValueError, TypeError) as error:
                return web.json_response({'message': str(error)}, status=400)
            except (RuntimeError, OSError, sqlite3.Error):
                return web.json_response({'message': 'Location action could not finish. Check sharing status before leaving the app.'}, status=503)
        router.add_get('/api/v1/preview/location-sessions', handle)
        router.add_post('/api/v1/preview/location-sessions', handle)
