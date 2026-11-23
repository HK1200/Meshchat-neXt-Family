# SPDX-License-Identifier: 0BSD
"""The released Nomad browser protocol on the app's existing Reticulum stack.

This is a client, not a page-hosting daemon. Downloads use the upstream
NomadNet request handlers and bounded request/resource decoders unchanged.
"""
import asyncio
import json
import html
import tempfile
import zipfile
import threading
import sqlite3
from types import SimpleNamespace

from aiohttp import web
from nomad_store import NomadStore
from discovery import ClientDiscovery


class NomadDiscovery(ClientDiscovery):
    aspect_filter = "nomadnetwork.node"

    def display_name(self, app_data):
        return app_data.decode("utf-8", errors="replace") if app_data else "Anonymous Node"


class _Download:
    """Hold a mobile download slot until its final frame has actually drained."""
    def __init__(self, runtime, owner, envelope, address):
        self.runtime, self.owner, self.envelope, self.address = runtime, owner, envelope, address
        self.active = True
        self.timer = runtime.loop.call_later(600, lambda: asyncio.create_task(self.expire()))
        runtime.download_slots.add(self)

    def finish(self):
        self.active = False
        self.timer.cancel()
        self.runtime.download_slots.discard(self)

    def cancel(self):
        self.finish()
        for identifier, downloader in tuple(self.runtime.active_downloads.items()):
            if getattr(downloader, '_meshchatnext_client', None) is self:
                self.runtime.active_downloads.pop(identifier, None)
                downloader.cancel()

    async def expire(self):
        if not self.active: return
        try:
            await asyncio.wait_for(self.runtime._failure(self.owner, self.envelope, 'download_timed_out'), 1)
        except (TimeoutError, ConnectionError, RuntimeError):
            pass
        finally:
            self.cancel()
            # A stalled writer must not retain another resource after its slot
            # expires. Reconnect only this WebSocket; the runtime stays alive.
            if hasattr(self.owner, 'close'):
                try: await asyncio.wait_for(self.owner.close(), 1)
                except (TimeoutError, ConnectionError, RuntimeError): pass

    async def send_str(self, value):
        if not self.active or self.runtime.closed: return
        if self.runtime.denied(self.address):
            self.cancel()
            await self.runtime._failure(self.owner, self.envelope, 'destination_blocked')
            return
        row = json.loads(value)
        field = 'nomadnet_file_download' if self.envelope['type'] == 'nomadnet.file.download' else 'nomadnet_page_download'
        body = row.get(field, {})
        if row.get('type') != self.envelope['type'] or body.get('destination_hash') != self.address:
            self.cancel()
            raise ValueError('The download response belongs to another destination')
        try:
            await self.owner.send_str(value)
        except BaseException:
            self.cancel()
            raise
        if body.get('status') in ('success', 'failure'):
            self.finish()

    async def send_json(self, value):
        await self.send_str(json.dumps(value))


class NomadRuntime:
    def __init__(self, folder, probe, denied, broadcast, config):
        from meshchatnext.src.backend.async_utils import AsyncUtils
        from nomad_policy import guarded_handlers

        self.loop = asyncio.get_running_loop()
        AsyncUtils.set_main_loop(self.loop)
        self.policy_lock = threading.RLock()
        self.pending_blocks = frozenset()
        self.base_denied = denied
        self.handlers = guarded_handlers(self)
        self.identity, self.reticulum = probe.source.identity, probe.reticulum
        self.broadcast, self.config = broadcast, config
        self.store = NomadStore(folder / 'nomad-browser.sqlite3')
        import RNS
        own_node = RNS.Destination.hash_from_name_and_identity('nomadnetwork.node', self.identity).hex() if self.identity else ''
        self.discovery = NomadDiscovery(folder / 'nomad-discovery.sqlite3', own_node,
            on_change=lambda address: self.loop.call_soon_threadsafe(self.announce_changed, address))
        RNS.Transport.register_announce_handler(self.discovery)
        self.database = SimpleNamespace(misc=self.store, announces=self.store)
        self.active_downloads = {}
        self.download_slots = set()
        self.notifications = set()
        self.exporting = False
        self.folder = folder
        self.download_id_lock = asyncio.Lock()
        self.download_id_counter = 0
        self.download_speeds = []
        self.closed = False

    def denied(self, address):
        if self.base_denied(address): return True
        if self.pending_blocks:
            from blocked_destinations import aliases
            return bool(self.pending_blocks.intersection(aliases(address)))
        return False

    def notify_failure(self, proxy, reason):
        async def tell():
            try:
                async with asyncio.timeout(2):
                    await self._failure(proxy.owner, proxy.envelope, reason)
            except (TimeoutError, ConnectionError, RuntimeError):
                pass
        def schedule():
            if self.closed: return
            task = self.loop.create_task(tell())
            self.notifications.add(task)
            task.add_done_callback(self.notifications.discard)
        self.loop.call_soon_threadsafe(schedule)

    def begin_block(self, keys):
        with self.policy_lock:
            self.pending_blocks = self.pending_blocks | frozenset(keys)
            self.reconcile_blocks()

    def reconcile_blocks(self):
        from meshchatnext.src.backend.nomadnet_downloader import drop_cached_link
        with self.policy_lock:
            for proxy in tuple(self.download_slots):
                if self.denied(proxy.address):
                    proxy.cancel()
                    self.notify_failure(proxy, 'destination_blocked')
                    drop_cached_link(bytes.fromhex(proxy.address))
            self.pending_blocks = frozenset(key for key in self.pending_blocks if not self.base_denied(key))

    def revoke_identification(self, address):
        from meshchatnext.src.backend.nomadnet_downloader import drop_cached_link
        with self.policy_lock:
            drop_cached_link(bytes.fromhex(address))
            for proxy in tuple(self.download_slots):
                body = proxy.envelope.get('nomadnet_page_download', proxy.envelope.get('nomadnet_file_download', {}))
                if proxy.address == address and not body.get('private', False):
                    proxy.cancel()
                    self.notify_failure(proxy, 'identity_preference_changed')

    # These hooks distinguish a remote browser from desktop page hosting.
    # No local filesystem is exposed to a Reticulum request.
    def _has_running_local_page_node(self, _destination):
        return False

    def _try_serve_local_page_node(self, *_args, **_kwargs):
        return None

    def _try_serve_local_page_node_file(self, *_args, **_kwargs):
        return None

    def _register_page_file_grant(self, *_args):
        # Grants protect desktop local-node files. This client has no local node.
        return None

    def archive_page(self, address, path, content, is_manual=False):
        with self.policy_lock:
            if self.closed or self.denied(address):
                return None
            if not is_manual and not self.config.get('page_archiver_enabled', False):
                return None
            return self.store.archive_page(address, path, content)

    def get_archived_page_versions(self, address, path):
        # The released handler also checks a historical hash-prefixed path.
        if isinstance(path, str) and path.startswith(str(address) + ':/'):
            path = path[len(str(address)) + 1:]
        if self.closed or self.denied(address):
            return []
        return self.store.get_archived_page_versions(address, path)

    def announce_changed(self, address):
        if self.closed or self.denied(address): return
        rows = self.discovery.page({'aspect': 'nomadnetwork.node', 'destination_hash': address})
        if rows: self.broadcast({'type': 'announce', 'announce': rows[0]})

    def discovered(self, query):
        return [row for row in self.discovery.page(query) if not self.denied(row['destination_hash'])]

    def flush_all_archived_pages(self):
        self.store.remove_archives()

    async def send_config_to_websocket_clients(self):
        self.broadcast({'type': 'config', 'config': self.config})

    @staticmethod
    def _identifier(value):
        return type(value) is int and 0 < value < 2**63

    async def _failure(self, client, envelope, reason):
        kind = envelope.get('type')
        body_name = 'nomadnet_file_download' if kind == 'nomadnet.file.download' else 'nomadnet_page_download'
        body = envelope.get(body_name)
        body = body if isinstance(body, dict) else {}
        descriptions = {
            'destination_blocked': 'This node is blocked.',
            'download_timed_out': 'The download did not finish. Try again.',
            'identity_preference_changed': 'Identification changed. Reload this page.',
            'browser_closed': 'Reopen neXt to continue browsing.',
            'invalid_or_unavailable_request': 'This request is invalid or no longer available.',
            'too_many_downloads': 'Wait for the current downloads to finish.',
            'local_storage_unavailable': 'The page could not be saved. Check available device storage and try again.',
        }
        reply = {'type': 'error', 'message': descriptions.get(reason, reason), 'code': reason, body_name: {'status': 'failure', 'failure_reason': descriptions.get(reason, reason), 'code': reason,
            'destination_hash': body.get('destination_hash', ''), 'page_path': body.get('page_path', ''),
            'file_path': body.get('file_path', '')}}
        request = envelope.get('request_id')
        if (isinstance(request, str) and 0 < len(request) <= 64) or (type(request) is int and 0 <= request < 2**63):
            reply['request_id'] = request
        await client.send_json(reply)

    async def handle(self, client, envelope):
        if not isinstance(envelope, dict) or not isinstance(envelope.get('type'), str) or envelope['type'] not in self.handlers:
            return False
        if self.closed:
            await self._failure(client, envelope, 'browser_closed')
            return True
        kind = envelope['type']
        proxy = None
        cancelled_proxy = None
        try:
            size = len(json.dumps(envelope, ensure_ascii=False).encode('utf-8'))
            if size > (14_000_000 if kind == 'nomadnet.page.archive.add' else 16_384):
                raise ValueError('request_too_large')
            if kind in ('nomadnet.page.download', 'nomadnet.file.download'):
                field = 'nomadnet_page_download' if kind == 'nomadnet.page.download' else 'nomadnet_file_download'
                body = envelope.get(field)
                if not isinstance(body, dict):
                    raise ValueError('invalid_request')
                address = NomadStore.address(body.get('destination_hash'))
                path = body.get('page_path' if field == 'nomadnet_page_download' else 'file_path')
                NomadStore.page_path(path)
                if self.denied(address):
                    raise ValueError('destination_blocked')
                if len(self.download_slots) >= 4:
                    raise ValueError('too_many_downloads')
                if 'private' in body and type(body['private']) is not bool:
                    raise ValueError('invalid_private_preference')
                body['destination_hash'] = address
                proxy = _Download(self, client, envelope, address)
            elif kind == 'nomadnet.download.cancel':
                identifier = envelope.get('download_id')
                downloader = self.active_downloads.get(identifier) if self._identifier(identifier) else None
                stored = getattr(downloader, '_meshchatnext_client', None)
                if downloader is None or getattr(stored, 'owner', stored) is not client:
                    raise ValueError('download_not_owned')
                cancelled_proxy = stored if isinstance(stored, _Download) else None
            elif kind in ('nomadnet.page.archives.get', 'nomadnet.page.archive.add'):
                address = NomadStore.address(envelope.get('destination_hash'))
                NomadStore.page_path(envelope.get('page_path'))
                if self.denied(address):
                    raise ValueError('destination_blocked')
            elif kind == 'nomadnet.page.archive.load':
                if not self._identifier(envelope.get('archive_id')):
                    raise ValueError('invalid_archive')
                row = self.store.get_archived_page_by_id(envelope['archive_id'])
                if row and self.denied(row['destination_hash']):
                    raise ValueError('destination_blocked')
            await self.handlers[kind](self, proxy or client, envelope)
            if cancelled_proxy: cancelled_proxy.finish()
        except (ValueError, TypeError, UnicodeError, OverflowError) as error:
            if proxy: proxy.cancel()
            reason = str(error) if str(error) in {'too_many_downloads', 'destination_blocked'} else 'invalid_or_unavailable_request'
            await self._failure(client, envelope, reason)
        except (OSError, sqlite3.Error):
            if proxy: proxy.cancel()
            await self._failure(client, envelope, 'local_storage_unavailable')
        return True

    def disconnect(self, client):
        for proxy in tuple(self.download_slots):
            if proxy.owner is client: proxy.cancel()
        for identifier, downloader in tuple(self.active_downloads.items()):
            if getattr(downloader, '_meshchatnext_client', None) is client:
                self.active_downloads.pop(identifier, None)
                downloader.cancel()

    @staticmethod
    async def read_json(request, limit=4096):
        if request.content_length is not None and request.content_length > limit:
            raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=request.content_length)
        encoded = bytearray()
        async for chunk in request.content.iter_chunked(4096):
            if len(encoded) + len(chunk) > limit:
                raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=len(encoded) + len(chunk))
            encoded.extend(chunk)
        value = json.loads(encoded)
        if not isinstance(value, dict): raise ValueError('Choose a valid settings file')
        return value

    def register(self, router):
        async def favourites(request):
            aspect = request.query.get('aspect', 'nomadnetwork.node')
            rows = self.store.favourites() if aspect == 'nomadnetwork.node' else []
            return web.json_response({'favourites': rows, 'total_count': len(rows)}, headers={'Cache-Control': 'no-store'})

        async def update(request):
            try:
                address = request.match_info.get('address')
                if request.method == 'DELETE':
                    with self.policy_lock:
                        self.store.remove_favourite(address)
                        self.revoke_identification(address)
                    return web.json_response({'message': 'Bookmark removed'})
                value = await self.read_json(request)
                with self.policy_lock:
                    action = request.match_info.get('action', 'add')
                    if action == 'add':
                        if value.get('aspect', 'nomadnetwork.node') != 'nomadnetwork.node':
                            raise ValueError('Choose a NomadNet node')
                        previous = self.store.favourite(value.get('destination_hash'))
                        row = self.store.save_favourite(value.get('destination_hash'), value.get('display_name', ''),
                            identify=bool(previous and previous['identify_on_connect']))
                    else:
                        previous = self.store.favourite(address)
                        if previous is None and action == 'rename': raise web.HTTPNotFound()
                        previous_name = previous['display_name'] if previous else address
                        name = value.get('display_name', previous_name)
                        identify = value.get('enabled') if action == 'identify-on-connect' else bool(previous['identify_on_connect'])
                        row = self.store.save_favourite(address, name, identify=identify)
                    if action == 'identify-on-connect' and not row['identify_on_connect']:
                        self.revoke_identification(row['destination_hash'])
                return web.json_response({'favourite': row, 'message': 'Bookmark saved'})
            except (ValueError, TypeError):
                raise web.HTTPBadRequest(text='Review the bookmark name and address') from None

        async def imports(request):
            try:
                value = await self.read_json(request, 1024 * 1024)
                imported = self.store.import_favourites(value.get('favourites'))
                return web.json_response({'imported': imported, 'skipped': 0, 'message': 'Bookmarks imported'})
            except (ValueError, TypeError):
                raise web.HTTPBadRequest(text='Choose a valid NomadNet bookmark file. Existing bookmarks were preserved.') from None

        async def layout(request):
            try:
                if request.method == 'GET':
                    saved = self.store.layout()
                else:
                    value = await self.read_json(request, 256 * 1024)
                    saved = self.store.save_layout(value.get('layout'))
                return web.json_response({'layout': saved}, headers={'Cache-Control': 'no-store'})
            except (ValueError, TypeError):
                raise web.HTTPBadRequest(text='Choose valid bookmark sections') from None

        def filters(request):
            query = request.query.get('q', '').strip()
            if len(query) > 256: raise ValueError('Enter a shorter archive search')
            destination = request.query.get('destination_hash') or None
            if destination: destination = self.store.address(destination)
            return query, destination

        async def archive_detail(request):
            row = self.store.get_archived_page_by_id(int(request.match_info['identifier']))
            if row is None or self.denied(row['destination_hash']): raise web.HTTPNotFound()
            row['node_name'] = (self.store.favourite(row['destination_hash']) or {}).get('display_name', row['destination_hash'][:8])
            row['snippet'] = html.escape(row['content'][:240])
            return web.json_response({'archive': row}, headers={'Cache-Control': 'no-store'})

        async def archives(request):
            try:
                if request.method == 'DELETE':
                    value = await self.read_json(request)
                    ids = value.get('ids')
                    if not isinstance(ids, list) or not ids: raise ValueError('Choose pages to remove')
                    self.store.remove_archives(ids)
                    return web.json_response({'message': 'Selected saved pages removed'})
                query, destination = filters(request)
                page, limit = int(request.query.get('page', 1)), int(request.query.get('limit', 25))
                if not 1 <= page <= 10000 or not 1 <= limit <= 100: raise ValueError('Invalid archive page')
                include = request.query.get('include_content', 'false') == 'true'
                rows = await asyncio.to_thread(self.store.archive_rows, query, destination, include_content=include)
                rows = [row for row in rows if not self.denied(row['destination_hash'])]
                total = len(rows)
                rows = rows[(page - 1) * limit:page * limit]
                for row in rows:
                    preview = row.get('content', row.get('preview', ''))[:2000]
                    row.update(preview=preview, snippet=html.escape(preview[:240]))
                    row['node_name'] = row.get('node_name') or row['destination_hash'][:8]
                return web.json_response({'archives': rows, 'pagination': {'page': page, 'limit': limit,
                    'total_count': total, 'total_pages': (total + limit - 1) // limit}}, headers={'Cache-Control': 'no-store'})
            except (ValueError, TypeError, OverflowError):
                raise web.HTTPBadRequest(text='Review the selected saved pages or search') from None

        async def export_archives(request):
            if self.exporting: raise web.HTTPConflict(text='Wait for the current export to finish')
            self.exporting = True
            output = None
            keep_busy = False
            try:
                query, destination = filters(request)
                rows = await asyncio.to_thread(self.store.archive_rows, query, destination, include_content=True)
                rows = [row for row in rows if not self.denied(row['destination_hash'])]
                def package():
                    import re
                    output = tempfile.TemporaryFile(mode='w+b', dir=self.folder)
                    try:
                        total, manifest = 0, []
                        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                            for row in rows:
                                raw = row['content'].encode('utf-8')
                                total += len(raw)
                                if len(raw) > self.store.max_page_bytes or total > self.store.max_archive_bytes:
                                    raise ValueError('The saved-page export exceeds its storage bound')
                                relative = row['page_path'].split('`', 1)[0].strip('/')
                                parts = [re.sub(r'[^a-zA-Z0-9._ -]', '_', part).strip('. ')[:80] or '_' for part in relative.split('/') if part]
                                name = row['destination_hash'][:8] + '/' + '/'.join(parts or ['index.mu']) + '__' + str(row['id']) + '.mu'
                                archive.writestr(name, raw)
                                manifest.append({key: row[key] for key in ('id', 'hash', 'destination_hash', 'page_path', 'created_at')})
                                manifest[-1]['file'] = name
                            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                        length = output.tell(); output.seek(0)
                        if length > 64 * 1024 * 1024: raise ValueError('The export is too large')
                        return output, length
                    except BaseException:
                        output.close(); raise
                build = self.loop.create_task(asyncio.to_thread(package))
                try:
                    output, length = await asyncio.shield(build)
                except BaseException:
                    keep_busy = True
                    def release_unclaimed(done):
                        try:
                            abandoned, _ = done.result()
                            abandoned.close()
                        except BaseException:
                            pass
                        self.exporting = False
                    build.add_done_callback(release_unclaimed)
                    raise
                response = web.StreamResponse(headers={'Content-Type': 'application/zip', 'Content-Length': str(length),
                    'Content-Disposition': 'attachment; filename="meshchatnext-archives.zip"', 'Cache-Control': 'no-store',
                    'X-Content-Type-Options': 'nosniff'})
                await response.prepare(request)
                while True:
                    chunk = await asyncio.to_thread(output.read, 65536)
                    if not chunk: break
                    await response.write(chunk)
                await response.write_eof()
                return response
            except (ValueError, TypeError):
                raise web.HTTPBadRequest(text='Review the saved-page export filters') from None
            finally:
                if output: output.close()
                if not keep_busy: self.exporting = False

        router.add_get('/api/v1/favourites', favourites)
        router.add_post('/api/v1/favourites/add', update)
        router.add_post('/api/v1/favourites/import', imports)
        router.add_get('/api/v1/favourites/layout', layout)
        router.add_put('/api/v1/favourites/layout', layout)
        router.add_post('/api/v1/favourites/{address}/{action:rename|identify-on-connect}', update)
        router.add_delete('/api/v1/favourites/{address}', update)
        router.add_get('/api/v1/nomadnet/archives/export', export_archives)
        router.add_get('/api/v1/nomadnet/archives/{identifier:[0-9]{1,18}}', archive_detail)
        router.add_get('/api/v1/nomadnet/archives', archives)
        router.add_delete('/api/v1/nomadnet/archives', archives)

    async def close(self):
        with self.policy_lock:
            self.closed = True
            for proxy in tuple(self.download_slots): proxy.cancel()
        for _, downloader in tuple(self.active_downloads.items()):
            downloader.cancel()
        self.active_downloads.clear()
        if self.notifications:
            try:
                async with asyncio.timeout(2):
                    await asyncio.gather(*tuple(self.notifications), return_exceptions=True)
            except TimeoutError: pass
        from meshchatnext.src.backend.nomadnet_downloader import clear_all_nomadnet_cached_links
        clear_all_nomadnet_cached_links()
        import RNS
        RNS.Transport.deregister_announce_handler(self.discovery)
        self.discovery.close()
        self.store.close()
