# SPDX-License-Identifier: 0BSD
"""Real standard Nomad requests through the protected iOS app WebSocket."""
import asyncio
import base64
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_next_ios_tcp_integration import SESSIONS, api, backend, start, wait

PAGE = '`!Private Nomad test`!\nExact text over Reticulum.\n'
FILE = bytes(range(256)) * 4096


def node(folder, port, pipe):
    import RNS
    folder.mkdir()
    (folder / 'config').write_text('[reticulum]\nshare_instance=No\nenable_transport=Yes\n[interfaces]\n[[Private]]\ntype=TCPServerInterface\nenabled=Yes\nlisten_ip=127.0.0.1\nlisten_port=' + str(port) + '\n')
    RNS.Reticulum(configdir=str(folder), loglevel=1)
    for interface in RNS.Transport.interfaces:
        assert interface.bind_ip == '127.0.0.1'
        interface.ingress_control = False
    identity = RNS.Identity()
    destination = RNS.Destination(identity, RNS.Destination.IN, RNS.Destination.SINGLE, 'nomadnetwork', 'node')
    def record(path, remote_identity):
        with (folder / 'requests.jsonl').open('a') as stream:
            stream.write(json.dumps({'path': path, 'identity': remote_identity.hash.hex() if remote_identity else None}) + '\n')
    def page(path, data, request_id, link_id, remote_identity, requested_at):
        record(path, remote_identity)
        return PAGE.encode()
    def file(path, data, request_id, link_id, remote_identity, requested_at):
        record(path, remote_identity)
        return ['test.bin', FILE]
    destination.register_request_handler('/page/index.mu', response_generator=page, allow=RNS.Destination.ALLOW_ALL)
    destination.register_request_handler('/file/test.bin', response_generator=file, allow=RNS.Destination.ALLOW_ALL)
    pipe.send(destination.hash.hex())
    while pipe.recv() == 'announce': destination.announce(app_data=b'Private Nomad node')


def server(folder, ready, settings, pipe):
    sys.path[:0] = [str(ROOT / 'ios/NextRuntimeProbe'), str(Path(os.environ['NEXT_TEST_BACKEND_SOURCE']).resolve()), str(ROOT / 'app/src/main/python')]
    from loopback_probe import serve
    from nomad_runtime import NomadRuntime
    frontend = folder / 'frontend'; frontend.mkdir()
    (frontend / 'index.html').write_text('<html>Private Nomad fixture</html>')
    (frontend / 'assets').mkdir()
    (frontend / 'assets/frame.js').write_text('export const fixture = true;')
    (frontend / 'nomad-crash-tab.html').write_text('<html>Private opaque renderer</html>')
    asyncio.run(serve(ready, frontend, settings, device=True, nomad_factory=NomadRuntime))


def test_standard_page_and_file_arrive_through_actual_app_routes(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    folder = tmp_path / 'app'; folder.mkdir()
    settings = folder / 'settings.json'
    settings.write_text(json.dumps({'peers': [{'id': 'private', 'host': '127.0.0.1', 'port': port, 'enabled': True}]}))
    ready = folder / 'backend.url'
    with ExitStack() as stack:
        _, remote = start(stack, node, tmp_path / 'node', port)
        assert remote.poll(10); address = remote.recv()
        start(stack, server, folder, ready, settings)
        wait(ready.exists); base = backend(ready)
        last = 0
        def discovered():
            nonlocal last
            if time.monotonic() - last > 2:
                remote.send('announce'); last = time.monotonic()
            status, result = api(base, 'announces?aspect=nomadnetwork.node')
            return status == 200 and any(row['destination_hash'] == address for row in result['announces'])
        wait(discovered)
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        import pytest
        origin = 'http://' + urlsplit(base).netloc
        for endpoint in ('favourites', 'nomadnet/archives', 'nomadnet/archives/export'):
            with pytest.raises(HTTPError) as denied:
                urlopen(Request(origin + '/api/v1/' + endpoint), timeout=5)
            assert denied.value.code == 403
        before = api(base, 'favourites')[1]['favourites']
        assert api(base, 'favourites/add', body={'destination_hash': address, 'display_name': 'Rejected without CSRF'})[0] == 403
        assert api(base, 'favourites')[1]['favourites'] == before
        for endpoint in ('/assets/frame.js', '/nomad-crash-tab.html'):
            # The shell loads shared modules before the opaque frame. Its
            # initial/cache-validated responses must vary too, or WebKit can
            # reuse a no-CORS response and silently strand the renderer.
            for headers in ({}, {'Origin': origin}):
                with urlopen(Request(origin + endpoint, headers=headers), timeout=5) as response:
                    assert response.headers['Vary'] == 'Origin'
                    assert 'Access-Control-Allow-Origin' not in response.headers
                    etag = response.headers['ETag']
                    response.read()
                with pytest.raises(HTTPError) as cached:
                    urlopen(Request(origin + endpoint, headers={**headers, 'If-None-Match': etag}), timeout=5)
                assert cached.value.code == 304
                assert cached.value.headers['Vary'] == 'Origin'
            with urlopen(Request(origin + endpoint, headers={'Origin': 'null'}), timeout=5) as response:
                assert response.status == 200
                assert response.headers['Access-Control-Allow-Origin'] == 'null'
                assert 'Access-Control-Allow-Credentials' not in response.headers
                if endpoint.endswith('.html'):
                    assert "default-src 'none'" in response.headers['Content-Security-Policy']
                    assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
            with pytest.raises(HTTPError) as denied:
                urlopen(Request(origin + endpoint, headers={'Origin': 'https://example.invalid'}), timeout=5)
            assert denied.value.code == 403
        for endpoint in ('/api/v1/config', '/ws'):
            with pytest.raises(HTTPError) as denied:
                urlopen(Request(origin + endpoint, headers={'Origin': 'null', 'X-neXt-Session': SESSIONS[urlsplit(base).netloc]}), timeout=5)
            assert denied.value.code == 403
        token = api(base, 'auth/csrf')[1]['csrf_token']
        assert api(base, 'favourites/add', body={'destination_hash': address, 'display_name': 'Saved node'}, token=token)[0] == 200
        assert api(base, 'favourites?aspect=nomadnetwork.node')[1]['favourites'][0]['destination_hash'] == address
        assert api(base, 'config', body={'page_archiver_enabled': True}, method='PATCH', token=token)[0] == 200
        assert api(base, 'favourites/' + address + '/identify-on-connect', body={'enabled': True}, token=token)[0] == 200
        async def exchange():
            import aiohttp
            origin = 'http://' + urlsplit(base).netloc
            async with aiohttp.ClientSession(headers={'X-neXt-Session': SESSIONS[urlsplit(base).netloc]}) as session:
                async with session.ws_connect(origin + '/ws') as ws:
                    async def download(kind, field, path_key, path, request, private=True, timeout=60):
                        await ws.send_json({'type': kind, 'request_id': request,
                            field: {'destination_hash': address, path_key: path, 'private': private}})
                        chunks = []
                        async with asyncio.timeout(timeout):
                            while True:
                                row = await ws.receive_json()
                                if row.get('request_id') != request: continue
                                value = row[field]
                                assert value['status'] != 'failure', value
                                if value['status'] == 'chunk':
                                    chunks.append(base64.b64decode(value['chunk_b64'], validate=True))
                                if value['status'] == 'success':
                                    if value.get('chunked'):
                                        raw = b''.join(chunks)
                                        assert len(raw) == value['total'] and hashlib.sha256(raw).hexdigest() == value['sha256']
                                        return raw
                                    return value
                    page = await download('nomadnet.page.download', 'nomadnet_page_download', 'page_path', '/page/index.mu', 'page')
                    assert page['page_content'] == PAGE
                    file = await download('nomadnet.file.download', 'nomadnet_file_download', 'file_path', '/file/test.bin', 'file')
                    assert (base64.b64decode(file['file_bytes'], validate=True) if isinstance(file, dict) else file) == FILE
                    assert api(base, 'nomadnet/archives')[1]['archives'] == [], 'Private browsing must not create page archives'
                    public = await download('nomadnet.page.download', 'nomadnet_page_download', 'page_path', '/page/index.mu', 'public', private=False)
                    assert public['page_content'] == PAGE
                    original = [{key: row[key] for key in ('id', 'host', 'port', 'enabled')}
                        for row in api(base, 'preview/reticulum-connections')[1]['peers']]
                    assert len(original) == 1 and original[0]['enabled']
                    assert api(base, 'preview/reticulum-connections', body={'peers': [dict(original[0], enabled=False)]}, token=token)[0] == 200
                    assert api(base, 'preview/reticulum-connections', body={'peers': original}, token=token)[0] == 200
                    wait(lambda: api(base, 'preview/reticulum-connections')[1]['peers'][0]['online'], timeout=5)
                    recovered = await download('nomadnet.page.download', 'nomadnet_page_download', 'page_path', '/page/index.mu', 'after-peer-reconnect', private=False, timeout=5)
                    assert recovered['page_content'] == PAGE
        asyncio.run(exchange())
        assert len(api(base, 'nomadnet/archives')[1]['archives']) == 1
        observed = [json.loads(line) for line in (tmp_path / 'node/requests.jsonl').read_text().splitlines()]
        assert len(observed) == 4
        assert all(row['identity'] is None for row in observed[:2]), 'Private browsing must override saved identification'
        import RNS
        expected = RNS.Identity.from_file(str(folder / 'reticulum/identity')).hash.hex()
        assert all(row['identity'] == expected for row in observed[2:]), 'Ordinary browsing identifies only after explicit opt-in'
