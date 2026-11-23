# SPDX-License-Identifier: 0BSD
"""RNCP using the released engine, with local files confined to its own storage."""
import asyncio
import contextlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
import uuid

from aiohttp import web
from aiohttp.helpers import content_disposition_header
from meshchatnext.src.backend.rncp_handler import RNCPHandler
from mobile_rncp_guard import install as install_fetch_guard

MAX_FILE = 2 * 1024 * 1024 * 1024
RESERVE = 128 * 1024 * 1024


class FileRuntime:
    def __init__(self, probe, folder, blocked, publish):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.shared = self.folder / 'rncp_shared'
        self.received = self.folder / 'rncp_received'
        for path in (self.shared, self.received):
            path.mkdir(mode=0o700, exist_ok=True)
        self.blocked, self.publish = blocked, publish
        self.loop = asyncio.get_running_loop()
        self.handler = RNCPHandler(probe.reticulum, probe.source.identity, str(self.folder))
        self.handler.on_receive_completed = lambda value: self.event({'type': 'rncp.receive.completed', **value})
        self.closed = False
        self.links = {}
        self.reservations = {}
        self.receive_lock = threading.Lock()
        self.receive_segments = {}
        self.receive_links = {}
        original = self.handler._receive_resource_callback
        concluded = self.handler._receive_resource_concluded
        def release_link(link):
            with self.receive_lock:
                for key in [key for key in self.reservations if key[0] == id(link)]:
                    self.reservations.pop(key, None)
                    self.receive_segments.pop(key, None)
                self.receive_links.pop(id(link), None)
        self.release_receive_link = release_link
        def reserve(advertisement):
            size = advertisement.get_data_size()
            segment_hash = advertisement.get_hash()
            first_hash = getattr(advertisement, 'o', segment_hash)
            index = getattr(advertisement, 'i', 1)
            count = getattr(advertisement, 'l', 1)
            link = getattr(advertisement, 'link', None)
            if (self.closed or link is None or type(size) is not int or not 0 <= size <= MAX_FILE
                    or not isinstance(segment_hash, bytes) or len(segment_hash) != 32
                    or not isinstance(first_hash, bytes) or len(first_hash) != 32
                    or type(index) is not int or type(count) is not int
                    or not 1 <= index <= count <= MAX_FILE + 1): return False
            key = (id(link), first_hash)
            with self.receive_lock:
                previous = self.receive_segments.get(key)
                if previous is not None:
                    # Standard RNS announces each segment with a distinct hash,
                    # but reserves the complete file's size on every advert.
                    # Continue only this link's next segment of the same file.
                    if (index != previous[0] + 1 or count != previous[1]
                            or size != self.reservations[key]
                            or segment_hash == previous[2]): return False
                else:
                    if index != 1 or first_hash != segment_hash: return False
                    if len(self.reservations) >= 2 or shutil.disk_usage(self.folder).free <= size + sum(self.reservations.values()) + RESERVE:
                        return False
                    self.reservations[key] = size
                self.receive_segments[key] = (index, count, segment_hash)
                if id(link) not in self.receive_links:
                    self.receive_links[id(link)] = link
                    setter = getattr(link, 'set_link_closed_callback', None)
                    if callable(setter):
                        previous_closed = getattr(getattr(link, 'callbacks', None), 'link_closed', None)
                        def closed(ended, previous_closed=previous_closed):
                            release_link(ended)
                            if callable(previous_closed): previous_closed(ended)
                        setter(closed)
            return True
        def release(resource):
            first_hash = getattr(resource, 'original_hash', resource.hash)
            with self.receive_lock:
                key = (id(resource.link), first_hash)
                self.reservations.pop(key, None)
                self.receive_segments.pop(key, None)
        self.release_receive_resource = release
        def receive(advertisement):
            identity = advertisement.link.get_remote_identity()
            return (identity is not None and not blocked(identity.hash.hex())
                    and original(advertisement) and reserve(advertisement))
        def finish(resource):
            release(resource)
            identity = resource.link.get_remote_identity()
            if self.closed or self.handler._is_cancelled(resource.hash.hex()) or identity is None or blocked(identity.hash.hex()):
                self.handler.cancel_transfer(resource.hash.hex())
                self.event({'type': 'rncp.receive.completed', 'transfer_id': resource.hash.hex(), 'status': 'cancelled', 'saved_path': None, 'error': None})
                return
            concluded(resource)
        self.handler._receive_resource_callback = receive
        self.handler._receive_resource_concluded = finish
        install_fetch_guard(self.handler,
            accept=lambda advert, destination: not blocked(destination.hex()) and reserve(advert),
            allowed=lambda destination: not self.closed and not blocked(destination.hex()),
            release=release,
            opened=lambda link: self.links.__setitem__(asyncio.current_task(), link))
        self.slots = asyncio.Semaphore(2)
        self.events = set()
        self.pending = set()
        self.transfers = {}

    def event(self, value):
        def schedule():
            if self.closed: return
            task = self.loop.create_task(self.publish(value))
            self.events.add(task)
            task.add_done_callback(self.events.discard)
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(schedule)

    def register(self, router):
        router.add_get('/api/v1/rncp/status', self.status)
        router.add_get('/api/v1/rncp/transfer/{transfer_id}', self.transfer)
        for name in ('send', 'fetch', 'listen', 'stop', 'cancel'):
            router.add_post('/api/v1/rncp/' + name, self.action)
        router.add_post('/api/v1/preview/rncp/upload', self.upload)
        router.add_get('/api/v1/preview/rncp/files', self.files)
        router.add_get('/api/v1/preview/rncp/files/{file_id}/download', self.download)

    @staticmethod
    def address(raw):
        if not isinstance(raw, str) or not re.fullmatch('[a-fA-F0-9]{32}', raw):
            raise ValueError('Enter a 32-character Reticulum destination')
        return raw.lower()

    @staticmethod
    def flag(data, name):
        value = data.get(name, False)
        if type(value) is not bool:
            raise ValueError('Invalid ' + name)
        return value

    @staticmethod
    def timeout(data):
        value = data.get('timeout')
        if value in (None, ''): return None
        if type(value) not in (int, float, str): raise ValueError('Invalid timeout')
        value = float(value)
        if not math.isfinite(value) or not 1 <= value <= 600: raise ValueError('Choose a timeout from 1 to 600 seconds')
        return value

    def local(self, raw, root, *, directory=False):
        if not isinstance(raw, str) or not raw or '\x00' in raw: raise ValueError('Choose a local file or directory')
        candidate = Path(raw)
        path = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if not path.is_relative_to(root.resolve()): raise ValueError('That path is outside RNCP storage')
        if directory:
            if not path.is_dir(): raise ValueError('Choose an existing RNCP directory')
        elif not path.is_file() or path.stat().st_size > MAX_FILE:
            raise ValueError('Choose an existing file up to 2 GiB')
        return str(path)

    async def body(self, request):
        data = bytearray()
        async with asyncio.timeout(5):
            while len(data) <= 8192:
                part = await request.content.read(8193 - len(data))
                if not part: break
                data.extend(part)
        if len(data) > 8192: raise ValueError('Request is too large')
        result = json.loads(data or b'{}')
        if not isinstance(result, dict): raise ValueError('Invalid request')
        return result

    async def status(self, request):
        return web.json_response(self.handler.get_listener_status(), headers={'Cache-Control': 'no-store'})

    async def transfer(self, request):
        value = request.match_info['transfer_id']
        if not re.fullmatch('[a-fA-F0-9]{64}', value): raise web.HTTPBadRequest(text='Invalid transfer')
        result = self.handler.get_transfer_status(value.lower())
        if result is None: raise web.HTTPNotFound()
        return web.json_response(result, headers={'Cache-Control': 'no-store'})

    async def action(self, request):
        if self.closed: raise web.HTTPServiceUnavailable(text='File transfers are stopped')
        task = asyncio.current_task()
        self.pending.add(task)
        acquired = False
        transfer_id = None
        try:
            data = await self.body(request)
            action = request.path.rsplit('/', 1)[-1]
            if action == 'stop':
                self.handler.teardown_receive_destination()
                for tid, value in list(self.handler.active_transfers.items()):
                    if value.get('status') == 'receiving': self.cancel(tid)
                return web.json_response({'message': 'RNCP listener stopped'})
            if action == 'cancel':
                value = data.get('transfer_id')
                if value is not None and (not isinstance(value, str) or not re.fullmatch('[a-fA-F0-9]{64}', value)):
                    raise ValueError('Invalid transfer')
                return web.json_response(self.cancel(value.lower() if value else None))
            if action == 'listen':
                values = data.get('allowed_hashes', [])
                if not isinstance(values, list) or len(values) > 100: raise ValueError('Approve at most 100 sender identities')
                allowed = list(dict.fromkeys(self.address(value) for value in values))
                if any(self.blocked(value) for value in allowed): raise ValueError('A sender is blocked')
                fetch = self.flag(data, 'fetch_allowed')
                jail = self.local(data.get('fetch_jail') or str(self.shared), self.shared, directory=True)
                address = self.handler.setup_receive_destination(allowed_hashes=allowed, fetch_allowed=fetch,
                    fetch_jail=jail, allow_overwrite=self.flag(data, 'allow_overwrite'))
                return web.json_response({'destination_hash': address, 'message': 'RNCP listener started'})
            destination = self.address(data.get('destination_hash'))
            if self.blocked(destination): raise ValueError('This destination is blocked')
            timeout = self.timeout(data)
            if action == 'send':
                raw = data.get('file_path')
                try: path = self.local(raw, self.shared)
                except ValueError: path = self.local(raw, self.received)
                options = dict(file_path=path, no_compress=self.flag(data, 'no_compress'))
                function = self.handler.send_file
            else:
                remote = data.get('file_path')
                if not isinstance(remote, str) or not remote or len(remote.encode('utf-8')) > 4096 or '\x00' in remote:
                    raise ValueError('Enter a remote file path')
                directory = self.local(data.get('save_path') or str(self.received), self.received, directory=True)
                options = dict(file_path=remote, save_path=directory, allow_overwrite=self.flag(data, 'allow_overwrite'))
                function = self.handler.fetch_file
            self.transfers[task] = None
            await asyncio.wait_for(self.slots.acquire(), 1)
            acquired = True
            if self.closed: raise asyncio.CancelledError()
            if self.blocked(destination): raise ValueError('This destination is blocked')
            def started(value):
                nonlocal transfer_id
                transfer_id = value
                self.transfers[task] = value
            def progress(value):
                if transfer_id:
                    self.event({'type': 'rncp.transfer.progress', 'transfer_id': transfer_id, 'progress': value})
                    if self.blocked(destination): self.cancel(transfer_id)
            # Standard RNCP resource watchdogs and explicit Cancel govern data
            # transfers. A path timeout must not cut off a healthy slow-radio file.
            result = await function(destination_hash=bytes.fromhex(destination), timeout=timeout,
                on_transfer_started=started, on_progress=progress, **options)
            self.event({'type': 'rncp.' + action + '.completed', **result})
            return web.json_response(result)
        except (ValueError, PermissionError, FileNotFoundError, json.JSONDecodeError) as error:
            return web.json_response({'message': str(error)}, status=400)
        except TimeoutError:
            return web.json_response({'message': 'The transfer timed out; check the route and peer'}, status=504)
        except InterruptedError:
            return web.json_response({'message': 'Transfer cancelled'}, status=409)
        except asyncio.CancelledError:
            if self.closed: raise
            return web.json_response({'message': 'Transfer cancelled'}, status=409)
        except Exception:
            return web.json_response({'message': 'The RNCP transfer failed'}, status=502)
        finally:
            if transfer_id:
                value = self.handler.get_transfer_status(transfer_id)
                if value and value['status'] not in ('completed', 'failed', 'cancelled', 'error'):
                    self.cancel(transfer_id)
            link = self.links.pop(task, None)
            if link is not None:
                with contextlib.suppress(Exception): link.teardown()
                self.release_receive_link(link)
            if acquired: self.slots.release()
            self.pending.discard(task)
            self.transfers.pop(task, None)

    async def upload(self, request):
        if self.closed: raise web.HTTPServiceUnavailable(text='File transfers are stopped')
        task = asyncio.current_task()
        self.pending.add(task)
        path = folder = None
        complete = False
        acquired = False
        try:
            await asyncio.wait_for(self.slots.acquire(), 1)
            acquired = True
            async with asyncio.timeout(300):
                reader = await request.multipart()
                field = await reader.next()
                if field is None or field.name != 'file': raise ValueError('Choose a file')
                name = field.filename
                if (not isinstance(name, str) or not name or name in ('.', '..') or '/' in name or '\\' in name
                        or len(name.encode('utf-8')) > 255 or any(ord(c) < 32 for c in name)):
                    raise ValueError('Invalid file name')
                folder = self.shared / uuid.uuid4().hex
                folder.mkdir(mode=0o700)
                path = folder / name
                size = 0
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'wb') as stream:
                    while chunk := await field.read_chunk(64 * 1024):
                        size += len(chunk)
                        if size > MAX_FILE: raise ValueError('Choose a file up to 2 GiB')
                        if shutil.disk_usage(self.folder).free < len(chunk) + RESERVE: raise ValueError('Not enough free space to import the file')
                        stream.write(chunk)
                if await reader.next() is not None: raise ValueError('Choose one file at a time')
                complete = True
                return web.json_response({'file_path': str(path), 'size': size, 'name': name})
        except (ValueError, AssertionError) as error:
            return web.json_response({'message': str(error)}, status=400)
        except TimeoutError:
            return web.json_response({'message': 'File import timed out'}, status=504)
        except OSError:
            return web.json_response({'message': 'Could not save the selected file'}, status=507)
        finally:
            try:
                if not complete and path is not None: path.unlink(missing_ok=True)
                if not complete and folder is not None:
                    with contextlib.suppress(OSError): folder.rmdir()
            finally:
                if acquired: self.slots.release()
                self.pending.discard(task)

    def inventory(self):
        import hashlib
        rows = []
        for path in self.received.iterdir():
            if path.is_file() and path.resolve().is_relative_to(self.received.resolve()):
                relative = path.relative_to(self.received).as_posix()
                rows.append({'id': hashlib.sha256(relative.encode()).hexdigest()[:32], 'name': path.name, 'size': path.stat().st_size, '_path': path})
                if len(rows) >= 1000: break
        return sorted(rows, key=lambda row: (row['name'].casefold(), row['id']))

    async def files(self, request):
        return web.json_response({'files': [{k: v for k, v in row.items() if k != '_path'} for row in self.inventory()]}, headers={'Cache-Control': 'no-store'})

    async def download(self, request):
        identifier = request.match_info['file_id']
        if not re.fullmatch('[a-f0-9]{32}', identifier): raise web.HTTPNotFound()
        row = next((row for row in self.inventory() if row['id'] == identifier), None)
        if row is None: raise web.HTTPNotFound()
        return web.FileResponse(row['_path'], headers={'Content-Disposition': content_disposition_header('attachment', filename=row['name']), 'Cache-Control': 'no-store'})

    def cancel(self, transfer_id=None, *, cancel_pending=True):
        # Keep resources before the standard handler drops terminal refs, and
        # preserve completed records when Cancel all is pressed.
        keys = [transfer_id] if transfer_id else list(self.handler.active_transfers)
        cancelled = []
        for key in keys:
            entry = self.handler.active_transfers.get(key)
            if not entry or entry.get('status') in ('completed', 'cancelled', 'failed', 'error'): continue
            resource = entry.get('resource')
            self.handler.cancel_transfer(key)
            cancelled.append(key)
            if resource is not None:
                with contextlib.suppress(Exception): resource.cancel()
                if hasattr(resource, 'link'): self.release_receive_resource(resource)
        pending = []
        if cancel_pending:
            try: current = asyncio.current_task()
            except RuntimeError: current = None
            pending = [task for task, key in list(self.transfers.items())
                       if task is not current and (transfer_id is None or key == transfer_id)]
            for task in pending: self.loop.call_soon_threadsafe(task.cancel)
        result = {'cancelled': cancelled}
        if pending: result['pending_cancelled'] = len(pending)
        return result

    async def close(self):
        self.closed = True
        self.cancel(cancel_pending=False)
        self.handler.teardown_receive_destination()
        for link in tuple(self.links.values()):
            with contextlib.suppress(Exception): link.teardown()
        self.links.clear()
        with self.receive_lock:
            self.reservations.clear()
            self.receive_segments.clear()
            self.receive_links.clear()
        pending = tuple(task for task in self.pending if task is not asyncio.current_task())
        for task in pending: task.cancel()
        if pending: await asyncio.gather(*pending, return_exceptions=True)
        if self.events: await asyncio.gather(*tuple(self.events), return_exceptions=True)
