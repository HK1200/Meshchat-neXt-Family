"""Private TCP interoperability with the released, unmodified RNCP engine."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ['NEXT_TEST_BACKEND_SOURCE']).resolve()
sys.path[:0] = [str(ROOT / 'ios/NextRuntimeProbe'), str(BACKEND)]
import RNS
from meshchatnext.src.backend.rncp_handler import RNCPHandler


def config(folder, kind, port):
    folder.mkdir(parents=True, exist_ok=False)
    endpoint = ('listen_ip = 127.0.0.1\nlisten_port = ' if kind == 'TCPServerInterface' else 'target_host = 127.0.0.1\ntarget_port = ')
    (folder / 'config').write_text('[reticulum]\nshare_instance = No\nenable_transport = No\n[interfaces]\n[[Private file proof]]\ntype = ' + kind + '\nenabled = Yes\n' + endpoint + str(port) + '\n')
    value = RNS.Reticulum(configdir=str(folder), loglevel=1)
    for interface in tuple(RNS.Transport.interfaces): interface.ingress_control = False
    return value


async def peer(folder, port, allowed):
    reticulum = config(folder / 'rns', 'TCPServerInterface', port)
    identity = RNS.Identity()
    files = RNCPHandler(reticulum, identity, str(folder / 'files'))
    address = files.setup_receive_destination(allowed_hashes=[allowed], fetch_allowed=True)
    shared = folder / 'files/rncp_shared'
    payload = b'Private standard RNCP fixture\x00' * 2048 + os.urandom(32)
    (shared / 'fixture.bin').write_bytes(payload)
    events = []
    def receive(event):
        events.append(event)
        (folder / 'events.json').write_text(json.dumps(events))
    files.on_receive_completed = receive
    (folder / 'ready.json').write_text(json.dumps(dict(address=address, identity=identity.hash.hex(), payload_sha256=hashlib.sha256(payload).hexdigest(), payload_size=len(payload))))
    announced = set()
    end = time.monotonic() + 180
    while time.monotonic() < end:
        for interface in tuple(RNS.Transport.interfaces):
            if getattr(interface, 'online', False) and getattr(interface, 'OUT', False) and id(interface) not in announced:
                interface.ingress_control = False
                files.receive_destination.announce(attached_interface=interface)
                announced.add(id(interface))
        command = folder / 'command.json'
        if command.exists():
            value = json.loads(command.read_text()); command.unlink()
            result = await files.send_file(bytes.fromhex(value['destination']), str(shared / 'fixture.bin'), timeout=10)
            (folder / 'reverse-result.json').write_text(json.dumps(result))
        await asyncio.sleep(.05)


async def client(folder, port, identity, ready):
    from aiohttp import FormData, web
    from aiohttp.test_utils import TestClient, TestServer
    from file_runtime import FileRuntime
    reticulum = config(folder / 'client-rns', 'TCPClientInterface', port)
    events = []
    async def publish(value): events.append(value)
    files = FileRuntime(SimpleNamespace(reticulum=reticulum, source=SimpleNamespace(identity=identity)), folder / 'client-files', lambda value: False, publish)
    app = web.Application(); files.register(app.router)
    deadline = time.monotonic() + 20
    while not RNS.Transport.has_path(bytes.fromhex(ready['address'])):
        assert time.monotonic() < deadline, 'No private RNCP route'
        await asyncio.sleep(.05)
    payload = os.urandom(90_000) + b'private-byte-proof'
    async with TestClient(TestServer(app)) as http:
        try:
            form = FormData(); form.add_field('file', payload, filename='chosen.bin', content_type='application/octet-stream')
            response = await http.post('/api/v1/preview/rncp/upload', data=form)
            assert response.status == 200, await response.text()
            imported = await response.json()
            response = await http.post('/api/v1/rncp/send', json=dict(destination_hash=ready['address'], file_path=imported['file_path'], timeout=10))
            result = await response.json(); assert response.status == 200 and result['status'] == 'completed', result
            end = time.monotonic() + 10
            remote = folder / 'peer/files/rncp_received/chosen.bin'
            while not remote.exists():
                assert time.monotonic() < end
                await asyncio.sleep(.05)
            assert remote.read_bytes() == payload
            response = await http.post('/api/v1/rncp/fetch', json=dict(destination_hash=ready['address'], file_path='fixture.bin', timeout=10))
            fetched = await response.json(); assert response.status == 200 and fetched['status'] == 'completed', fetched
            assert hashlib.sha256(Path(fetched['file_path']).read_bytes()).hexdigest() == ready['payload_sha256']
            response = await http.post('/api/v1/rncp/listen', json=dict(allowed_hashes=[ready['identity']], fetch_allowed=False))
            listener = await response.json(); assert response.status == 200, listener
            for interface in tuple(RNS.Transport.interfaces):
                if getattr(interface, 'online', False) and getattr(interface, 'OUT', False):
                    files.handler.receive_destination.announce(attached_interface=interface)
            await asyncio.sleep(.2)
            (folder / 'peer/command.json').write_text(json.dumps(dict(destination=listener['destination_hash'])))
            end = time.monotonic() + 25
            while not any(event.get('type') == 'rncp.receive.completed' and event.get('status') == 'completed' for event in events):
                assert time.monotonic() < end, 'No reverse RNCP completion event'
                await asyncio.sleep(.05)
            completed = next(event for event in events if event.get('type') == 'rncp.receive.completed' and event.get('status') == 'completed')
            assert hashlib.sha256(Path(completed['saved_path']).read_bytes()).hexdigest() == ready['payload_sha256']
            response = await http.get('/api/v1/preview/rncp/files')
            listing = await response.json(); assert len(listing['files']) == 2
            for row in listing['files']:
                response = await http.get('/api/v1/preview/rncp/files/' + row['id'] + '/download')
                assert response.status == 200
                assert hashlib.sha256(await response.read()).hexdigest() == ready['payload_sha256']
            response = await http.post('/api/v1/rncp/stop', json={})
            assert response.status == 200 and not files.handler.get_listener_status()['listening']
            proof = dict(private_loopback_only=True,public_radio_packets=False,released_unmodified_peer_engine=True,
                         selected_upload_bytes=len(payload),send_bytes_match=True,fetch_bytes_match=True,
                         approved_reverse_receive_bytes_match=True,native_export_routes_match=True,
                         listener_stops=True,receiver_source='iOS FileRuntime',actual_ipad=False)
            (folder / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n'); print(json.dumps(proof))
        finally:
            await files.close()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--folder', required=True, type=Path); parser.add_argument('--port', type=int); parser.add_argument('--allowed')
    args = parser.parse_args(); folder = args.folder.resolve()
    if args.port is not None:
        asyncio.run(peer(folder, args.port, args.allowed)); return
    folder.mkdir(parents=True, exist_ok=False)
    identity = RNS.Identity()
    with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    with (folder / 'peer.log').open('w') as log:
        process = subprocess.Popen([sys.executable, __file__, '--folder', str(folder / 'peer'), '--port', str(port), '--allowed', identity.hash.hex()], stdout=log, stderr=subprocess.STDOUT)
        try:
            end = time.monotonic() + 20
            while not (folder / 'peer/ready.json').exists():
                assert process.poll() is None, 'Private RNCP peer failed'
                assert time.monotonic() < end
                time.sleep(.05)
            ready = json.loads((folder / 'peer/ready.json').read_text())
            asyncio.run(asyncio.wait_for(client(folder, port, identity, ready), 90))
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()


if __name__ == '__main__': main()
