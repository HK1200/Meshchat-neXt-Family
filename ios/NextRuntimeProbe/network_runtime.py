# SPDX-License-Identifier: 0BSD
"""Local Reticulum diagnostics using the same handlers as the desktop app."""
import asyncio
import json
import math
import os
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
    PROBE_BUDGET = 600
    def __init__(self, probe, blocked):
        self.probe, self.blocked = probe, blocked
        self.paths = RNPathHandler(probe.reticulum)
        self.status = RNStatusHandler(probe.reticulum)
        self.reads = asyncio.Semaphore(2)
        self.waits = asyncio.Semaphore(2)
        self.probe_slots = asyncio.Semaphore(1)
        self.prepare_request = lambda destination: prepare_fresh_path_request(probe.reticulum, destination)

    def register(self, router):
        router.add_post('/api/v1/rnprobe', self.probe_api)
        for path in ('rnstatus', 'interface-stats', 'reticulum/interfaces', 'reticulum/blackhole', 'rnpath/table', 'rnpath/rates'):
            router.add_get('/api/v1/' + path, self.api)
        router.add_get('/api/v1/rnpath/trace/{destination_hash}', self.api)
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

    def trace(self, address):
        # A display refresh must not broadcast a path request. The existing
        # explicit request action remains available when no route is known.
        snapshot = self.path(address)
        route = snapshot['path']
        if route is None:
            return {'error': 'No known path. Request a path first.'}
        hops = route['hops']
        local = getattr(getattr(self.probe, 'identity', None), 'hash', None)
        path = [{'type': 'local', 'hash': local.hex() if isinstance(local, bytes) else 'unknown',
                 'name': 'Local Node'}]
        if hops > 1:
            path.append({'type': 'hop', 'hash': route['next_hop'], 'name': 'Next Hop',
                         'interface': route['next_hop_interface'], 'hop_number': 1})
            if hops > 2:
                path.append({'type': 'unknown', 'count': hops - 2})
        destination = {'type': 'destination', 'hash': address, 'hops': hops,
                       'interface': route['next_hop_interface']}
        if hops == 0:
            destination['name'] = 'Local destination'
        path.append(destination)
        return {'destination': address, 'hops': hops, 'path': path,
                'interface': route['next_hop_interface'], 'next_hop': route['next_hop'],
                'path_stale': snapshot.get('path_stale', False),
                'path_unresponsive': snapshot.get('path_unresponsive', False)}

    async def probe_api(self, request):
        acquired = False
        try:
            body = bytearray()
            async with asyncio.timeout(5):
                while len(body) < 4097:
                    chunk = await request.content.read(4097 - len(body))
                    if not chunk: break
                    body.extend(chunk)
            if len(body) > 4096: raise ValueError('Probe request is too large')
            data = json.loads(body)
            allowed = {'destination_hash', 'full_name', 'size', 'probes', 'wait', 'timeout'}
            if not isinstance(data, dict) or not set(data) <= allowed: raise ValueError('Invalid probe request')
            address = self.address(data.get('destination_hash'))
            name = data.get('full_name')
            if not isinstance(name, str) or not 1 <= len(name) <= 256 or any(c.isspace() for c in name):
                raise ValueError('Enter the full destination name')
            app_name, aspects = RNS.Destination.app_and_aspects_from_name(name)
            if not app_name or not aspects or any(not part for part in aspects):
                raise ValueError('Enter the full destination name')
            size = self.number(data, 'size', 16, 1, max(1, RNS.Reticulum.MTU - 96))
            probes = self.number(data, 'probes', 1, 1, 50)
            def seconds(field, default, minimum, maximum):
                value = data.get(field, default)
                if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                    raise ValueError('Invalid ' + field)
                value = float(value)
                if not math.isfinite(value) or not minimum <= value <= maximum:
                    raise ValueError('Invalid ' + field)
                return value
            wait = seconds('wait', 0, 0, 120)
            raw_timeout = data.get('timeout')
            timeout = None if raw_timeout is None or (not isinstance(raw_timeout, bool) and raw_timeout in (0, '0')) else seconds('timeout', 0, 0.001, 600)
            def guard():
                if self.blocked(address): raise ValueError('This destination is blocked')
                if request.transport is None or request.transport.is_closing(): raise asyncio.CancelledError()
            async def pause(duration):
                end = asyncio.get_running_loop().time() + duration
                while asyncio.get_running_loop().time() < end:
                    guard()
                    await asyncio.sleep(min(.1, max(0, end - asyncio.get_running_loop().time())))
                guard()
            guard()
            await asyncio.wait_for(self.probe_slots.acquire(), 1)
            acquired = True
            guard()
            async with asyncio.timeout(self.PROBE_BUDGET):
                destination = bytes.fromhex(address)
                if timeout is None:
                    timeout = await self.read(lambda: path_response_window(destination, self.probe.reticulum))
                    guard()
                    timeout = float(timeout)
                    if not math.isfinite(timeout): raise ValueError('Invalid path response timeout')
                    timeout = min(600, max(1, timeout))
                deadline = asyncio.get_running_loop().time() + timeout
                if not RNS.Transport.has_path(destination):
                    guard(); self.prepare_request(destination)
                while not RNS.Transport.has_path(destination):
                    if asyncio.get_running_loop().time() >= deadline: raise TimeoutError('No Reticulum path')
                    await pause(.1)
                guard()
                identity = RNS.Identity.recall(destination)
                if identity is None or RNS.Destination.hash_from_name_and_identity(name, identity) != destination:
                    raise ValueError('Destination name does not match the known destination')
                target = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, app_name, *aspects)
                results = []
                for index in range(probes):
                    if index: await pause(wait)
                    guard()
                    packet = RNS.Packet(target, os.urandom(size)); packet.pack()
                    guard(); receipt = packet.send()
                    if receipt is None: raise RuntimeError('Reticulum did not create a probe receipt')
                    deadline = asyncio.get_running_loop().time() + timeout
                    while receipt.status == RNS.PacketReceipt.SENT and asyncio.get_running_loop().time() < deadline:
                        await pause(.1)
                    guard()
                    via, interface = await self.read(lambda: (self.probe.reticulum.get_next_hop(destination), self.probe.reticulum.get_next_hop_if_name(destination)))
                    guard()
                    result = {'probe_number': index + 1, 'size': size, 'destination': RNS.prettyhexrep(destination),
                              'via': ' via ' + RNS.prettyhexrep(via) if via else '',
                              'interface': ' on ' + interface if interface and interface != 'None' else '',
                              'status': 'timeout' if receipt.status == RNS.PacketReceipt.SENT else 'failed'}
                    if receipt.status == RNS.PacketReceipt.DELIVERED:
                        rtt = receipt.get_rtt()
                        proof = getattr(receipt, 'proof_packet', None)
                        stats = {key: value for key, value in ((key, getattr(proof, attr, None)) for key, attr in (('rssi', 'rssi'), ('snr', 'snr'), ('quality', 'q'))) if value is not None}
                        result.update(status='delivered', hops=RNS.Transport.hops_to(destination), rtt=rtt,
                                      rtt_string=f'{round(rtt, 3)} seconds' if rtt >= 1 else f'{round(rtt * 1000, 3)} milliseconds', reception_stats=stats)
                    results.append(result)
                result = {'results': results, 'sent': len(results),
                          'delivered': sum(row['status'] == 'delivered' for row in results),
                          'timeouts': sum(row['status'] == 'timeout' for row in results),
                          'failed': sum(row['status'] == 'failed' for row in results)}
                return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError) as error:
            return web.json_response({'message': str(error)}, status=400)
        except (TimeoutError, OSError, RuntimeError):
            return web.json_response({'message': 'Probe unavailable or timed out. Try fewer probes or a shorter wait.'}, status=503)
        finally:
            if acquired: self.probe_slots.release()

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
            elif path.startswith('rnpath/trace/'):
                result = await self.read(self.trace, address=self.address(request.match_info['destination_hash']))
            elif path == 'rnpath/table':
                result = await self.read(self.paths.get_path_table,
                    max_hops=self.number(request.query, 'max_hops'), hops=self.number(request.query, 'hops'),
                    page=self.number(request.query, 'page', 1, 1, 100000),
                    limit=self.number(request.query, 'limit', 50, 0, 1000),
                    search=request.query.get('search'), interface=request.query.get('interface'))
            elif path == 'rnpath/rates':
                result = {'rates': await self.read(self.paths.get_rate_table)}
            elif path == 'reticulum/blackhole':
                getter = getattr(self.probe.reticulum, 'get_blackholed_identities', None)
                if not callable(getter):
                    return web.json_response({'message': 'Transport blackhole information is unavailable in this Reticulum runtime'}, status=501)
                identities = await self.read(getter)
                if not isinstance(identities, dict):
                    raise RuntimeError('Invalid transport blackhole snapshot')
                formatted = {}
                for identity_hash, info in identities.items():
                    if not isinstance(identity_hash, bytes) or len(identity_hash) != 16 or not isinstance(info, dict):
                        raise RuntimeError('Invalid transport blackhole entry')
                    source = info.get('source')
                    if source is not None and not isinstance(source, bytes):
                        raise RuntimeError('Invalid transport blackhole source')
                    formatted[identity_hash.hex()] = {'source': source.hex() if source else None,
                        'until': info.get('until'), 'reason': info.get('reason')}
                result = {'blackholed_identities': formatted}
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
