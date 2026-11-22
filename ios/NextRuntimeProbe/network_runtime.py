# SPDX-License-Identifier: 0BSD
"""Local Reticulum diagnostics using the same handlers as the desktop app."""
import asyncio
import json
import re

from aiohttp import web
import RNS
from meshchatnext.src.backend.rnpath_handler import RNPathHandler
from meshchatnext.src.backend.rnstatus_handler import RNStatusHandler
from meshchatnext.src.backend.reticulum_pathfinding import path_metadata_for_api, prepare_fresh_path_request
from meshchatnext.src.backend.path_utils import path_response_window


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
        self.waits = asyncio.Semaphore(2)
        self.prepare_request = lambda destination: prepare_fresh_path_request(probe.reticulum, destination)

    def register(self, router):
        for path in ('rnstatus', 'interface-stats', 'reticulum/interfaces', 'rnpath/table', 'rnpath/rates'):
            router.add_get('/api/v1/' + path, self.api)
        router.add_get('/api/v1/destination/{destination_hash}/path', self.api)
        router.add_post('/api/v1/destination/{destination_hash}/{action:path|request-path|drop-path}', self.api)
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
        if isinstance(raw, bool) or not isinstance(raw, (str, int)):
            raise ValueError('Invalid ' + name)
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

    async def wait_for_path(self, address, timeout):
        # Bound concurrent waits, and recheck a ban after every asynchronous boundary.
        await asyncio.wait_for(self.waits.acquire(), 1)
        try:
            if self.blocked(address): raise ValueError('This destination is blocked')
            snapshot = await self.read(self.path, address=address)
            if self.blocked(address): raise ValueError('This destination is blocked')
            if snapshot['path'] and not snapshot.get('path_stale') and not snapshot.get('path_unresponsive'):
                return snapshot
            destination = bytes.fromhex(address)
            if timeout is None:
                timeout = await self.read(lambda: path_response_window(destination, self.probe.reticulum))
                timeout = min(600, max(1, float(timeout)))
            if self.blocked(address): raise ValueError('This destination is blocked')
            self.prepare_request(destination)
            deadline = asyncio.get_running_loop().time() + timeout
            while not RNS.Transport.has_path(destination) and asyncio.get_running_loop().time() < deadline:
                if self.blocked(address): raise ValueError('This destination is blocked')
                await asyncio.sleep(0.1)
            if self.blocked(address): raise ValueError('This destination is blocked')
            return await self.read(self.path, address=address)
        finally:
            self.waits.release()

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
                if path.startswith('destination/'):
                    action = request.match_info['action']
                    address = self.address(request.match_info['destination_hash'])
                    allowed = {'timeout'} if action == 'path' else set()
                    if not isinstance(data, dict) or not set(data) <= allowed:
                        raise ValueError('Invalid path action')
                    if action == 'path':
                        raw = request.query.get('timeout', data.get('timeout'))
                        if isinstance(raw, bool): raise ValueError('Invalid timeout')
                        timeout = self.number({'timeout': raw}, 'timeout', None, 1, 600)
                        result = await self.wait_for_path(address, timeout)
                    else:
                        if action == 'request-path' and self.blocked(address):
                            raise ValueError('This destination is blocked')
                        function = self.paths.request_path if action == 'request-path' else self.paths.drop_path
                        result = {'success': function(address)}
                    return web.json_response(jsonable(result), headers={'Cache-Control': 'no-store'})
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
                stats = jsonable(await self.read(self.probe.reticulum.get_interface_stats))
                if not isinstance(stats, dict): stats = {'interfaces': []}
                for row in stats.get('interfaces') or []:
                    if row.get('short_name'):
                        row['interface_name'] = row['short_name']
                        for interface in tuple(RNS.Transport.interfaces):
                            if getattr(interface, 'name', None) == row['short_name'] and 'RNode' in type(interface).__name__:
                                row['bluetooth_connected'] = any(
                                    bool(getattr(getattr(interface, name, None), 'connected', False))
                                    for name in ('ble', 'bt_manager'))
                                if getattr(interface, 'r_battery_state', 0) == 0:
                                    row.pop('battery_percent', None)
                                break
                result = {'interface_stats': stats}
            return web.json_response(jsonable(result), headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError) as error:
            return web.json_response({'message': str(error)}, status=400)
        except (TimeoutError, OSError, RuntimeError):
            return web.json_response({'message': 'Reticulum diagnostics are temporarily unavailable'}, status=503)
