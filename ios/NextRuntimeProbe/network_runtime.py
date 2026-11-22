# SPDX-License-Identifier: 0BSD
"""Local Reticulum diagnostics using the same handlers as the desktop app."""
import asyncio
import json
import re

from aiohttp import web
import RNS
from meshchatnext.src.backend.rnpath_handler import RNPathHandler
from meshchatnext.src.backend.rnstatus_handler import RNStatusHandler
from meshchatnext.src.backend.reticulum_pathfinding import path_metadata_for_api


def jsonable(value):
    if isinstance(value, (bytes, bytearray)): return value.hex()
    if isinstance(value, dict): return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)): return [jsonable(item) for item in value]
    return value


class NetworkRuntime:
    def __init__(self, probe, blocked):
        self.probe, self.blocked = probe, blocked
        self.paths = RNPathHandler(probe.reticulum)
        self.status = RNStatusHandler(probe.reticulum)
        self.reads = asyncio.Semaphore(2)

    def register(self, router):
        for path in ('rnstatus', 'interface-stats', 'reticulum/interfaces', 'rnpath/table', 'rnpath/rates'):
            router.add_get('/api/v1/' + path, self.api)
        router.add_get('/api/v1/destination/{destination_hash}/path', self.api)
        for action in ('request', 'drop', 'drop-via', 'drop-queues'):
            router.add_post('/api/v1/rnpath/' + action, self.api)

    async def read(self, function, **kwargs):
        # Keep the slot occupied until the worker really exits, even on timeout.
        await self.reads.acquire()
        worker = asyncio.create_task(asyncio.to_thread(function, **kwargs))
        worker.add_done_callback(lambda task: self.reads.release())
        try:
            return await asyncio.wait_for(asyncio.shield(worker), 5)
        except BaseException:
            worker.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            raise

    @staticmethod
    def address(value):
        if not isinstance(value, str) or not re.fullmatch('[0-9a-fA-F]{32}', value):
            raise ValueError('Enter a 32-character Reticulum destination')
        return value.lower()

    @staticmethod
    def number(query, name, default=None, minimum=0, maximum=128):
        raw = query.get(name)
        if raw in (None, ''): return default
        value = int(raw)
        if not minimum <= value <= maximum: raise ValueError('Invalid ' + name)
        return value

    @staticmethod
    def flag(query, name):
        value = query.get(name, 'false').lower()
        if value not in ('true', 'false', '1', '0'): raise ValueError('Invalid ' + name)
        return value in ('true', '1')

    def interfaces(self):
        rows = {}
        for row in self.probe.connections.snapshot():
            rows['neXt TCP ' + row['id']] = {
                'type': 'TCPClientInterface', 'target_host': row['host'],
                'target_port': row['port'], 'interface_enabled': row['enabled'],
            }
        for interface in tuple(RNS.Transport.interfaces):
            name = getattr(interface, 'name', None)
            if name and 'RNode' in type(interface).__name__:
                rows[name] = {'type': 'RNodeInterface', 'interface_enabled': True}
        return {'interfaces': rows}

    def path(self, address):
        destination = bytes.fromhex(address)
        own = getattr(self.probe, 'source', None)
        if own and destination in (own.hash, own.identity.hash):
            return {'path': {'hops': 0, 'next_hop': address, 'next_hop_interface': 'Local'},
                    'path_stale': False, 'path_unresponsive': False}
        metadata = path_metadata_for_api(destination)
        result = None
        if RNS.Transport.has_path(destination):
            hops = RNS.Transport.hops_to(destination)
            via = self.probe.reticulum.get_next_hop(destination)
            if type(hops) is int and isinstance(via, (bytes, bytearray)):
                result = {'hops': hops, 'next_hop': via.hex(),
                          'next_hop_interface': self.probe.reticulum.get_next_hop_if_name(destination)}
        return {'path': result, **metadata}

    async def api(self, request):
        try:
            # Do not silently perform a local query when the user requested a remote node.
            if any(request.query.get(key) for key in ('remote', 'identity_path', 'identity_name')):
                raise ValueError('Remote diagnostics are not available in this iOS build')
            path = request.path.removeprefix('/api/v1/')
            if request.method == 'POST':
                body = bytearray()
                async for part in request.content.iter_chunked(4096):
                    body.extend(part)
                    if len(body) > 4096: raise ValueError('Request is too large')
                data = json.loads(body) if body else {}
                action = path.removeprefix('rnpath/')
                field = 'transport_instance_hash' if action == 'drop-via' else 'destination_hash'
                if not isinstance(data, dict) or set(data) != (set() if action == 'drop-queues' else {field}):
                    raise ValueError('Invalid path action')
                address = None if action == 'drop-queues' else self.address(data[field])
                if action == 'request' and self.blocked(address):
                    raise ValueError('This destination is blocked')
                # SDK mutations are synchronous; no await between approval and transmission.
                result = {'success': {'request': self.paths.request_path, 'drop': self.paths.drop_path,
                          'drop-via': self.paths.drop_all_via, 'drop-queues': self.paths.drop_announce_queues}[action](
                              *(() if address is None else (address,)))}
            elif path == 'rnstatus':
                result = await self.read(self.status.get_status,
                    include_link_stats=self.flag(request.query, 'include_link_stats'),
                    sorting=request.query.get('sorting'), sort_reverse=self.flag(request.query, 'sort_reverse'),
                    show_all=self.flag(request.query, 'show_all'))
            elif path == 'rnpath/table':
                result = await self.read(self.paths.get_path_table,
                    max_hops=self.number(request.query, 'max_hops'), hops=self.number(request.query, 'hops'),
                    page=self.number(request.query, 'page', 1, 1, 100000),
                    limit=self.number(request.query, 'limit', 50, 0, 1000),
                    search=request.query.get('search'), interface=request.query.get('interface'))
            elif path == 'rnpath/rates':
                result = {'rates': await self.read(self.paths.get_rate_table)}
            elif path == 'reticulum/interfaces':
                result = self.interfaces()
            elif path.startswith('destination/'):
                if self.flag(request.query, 'request'):
                    raise ValueError('Path requests require an explicit POST action')
                result = await self.read(self.path, address=self.address(request.match_info['destination_hash']))
            else:
                result = jsonable(await self.read(self.probe.reticulum.get_interface_stats))
                for row in result.get('interfaces', []):
                    if row.get('short_name'): row['interface_name'] = row['short_name']
            return web.json_response(jsonable(result), headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError) as error:
            return web.json_response({'message': str(error)}, status=400)
        except (TimeoutError, OSError, RuntimeError):
            return web.json_response({'message': 'Reticulum diagnostics are temporarily unavailable'}, status=503)
