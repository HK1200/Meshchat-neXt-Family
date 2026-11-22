"""Native private Reticulum/MeshCore location, without public or mailbox copies."""
import asyncio
import json
from pathlib import Path
import sqlite3

from aiohttp import web
from location_sessions import LocationSessions


class LocationRuntime:
    def __init__(self, folder, probe, history, telemetry, *, native=None):
        self.probe, self.history, self.telemetry = probe, history, telemetry
        self.meshcore = None
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
        rows = {f'reticulum:{identity}:{address}': dict(
            name=row['name'], service='reticulum', online=self.probe.online, address=address)
            for address, row in self.history.conversation_entries().items()
            if getattr(self, 'recipient_allowed', lambda peer: True)(address)}
        if self.meshcore is not None:
            rows.update(await self.meshcore.location_recipients())
        return rows

    async def transmit(self, target, fix, guard):
        if target.get('service') == 'meshcore':
            if self.meshcore is None: return False
            key = 'meshcore:' + target['owner'] + ':' + target['address'] + ':' + target['generation']
            session = self.manager.sessions.get(key)
            generation = self.manager.native_generation
            if session is None or not await guard(): return False

            def current():
                # Called again by AndroidConnection in its final native-send
                # thread, after waiting for its write lock. No disk or RF here.
                if (self.manager.closed or not self.manager.armed
                        or self.manager.sessions.get(key) is not session
                        or not session.active(self.manager.clock())
                        or not self.manager.clock()-120 <= fix['last_update'] <= self.manager.clock()+300):
                    return False
                native = self.native_write_status()
                return (native.get('can_submit') is True and native.get('generation') == generation
                        and (session.background or native.get('foreground') is True))

            return await self.meshcore.send_native_location(target, fix, guard, current)
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

    def native_write_status(self):
        """Read current native consent at the final Bluetooth handoff, never start GPS."""
        import _next_location
        reply = _next_location.request(json.dumps(dict(op='status', session=self.manager.token,
            active=False, until=0, background=False, revisions=[])))
        if not isinstance(reply, str) or len(reply) > 16384:
            raise RuntimeError('Invalid native location status')
        value = json.loads(reply)
        if not isinstance(value, dict) or value.get('ok') is not True:
            raise RuntimeError('Native location consent is unavailable')
        return value

    async def contact_removed(self, address):
        key = f'reticulum:{self.probe.source.identity.hash.hex()}:{address}'
        if key in self.manager.sessions: await self.manager.stop(key)

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
                if request.method == 'GET': result = await self.manager.snapshot(include_recipients=request.query.get('summary') != '1')
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
                        if (not {'request_id', 'consent_epoch'}.issubset(payload)
                                or not isinstance(payload['request_id'], str) or type(payload['consent_epoch']) is not int):
                            raise ValueError('Review the current sharing controls before starting')
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
