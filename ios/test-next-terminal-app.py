"""Verify RNSh wiring in the actual protected iOS server, without network peers."""
import asyncio
import json
import os
from pathlib import Path
import sys

from aiohttp import ClientSession

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ['NEXT_TEST_BACKEND_SOURCE']).resolve()
sys.path[:0] = [str(ROOT / 'ios/NextRuntimeProbe'), str(ROOT / 'app/src/main/python'), str(BACKEND)]
from loopback_probe import serve
from terminal_runtime import TerminalRuntime


async def main(folder):
    folder.mkdir(parents=True, exist_ok=False)
    frontend = folder / 'frontend'; frontend.mkdir(); (frontend / 'index.html').write_text('<!doctype html><title>Private runtime wiring</title>')
    fixture = folder / 'peer.json'; fixture.write_text(json.dumps({'peers': []}))
    ready = folder / 'ready.txt'
    task = asyncio.create_task(serve(ready, frontend, fixture, terminal_factory=TerminalRuntime))
    try:
        async with asyncio.timeout(20):
            while not ready.exists():
                if task.done(): await task
                await asyncio.sleep(.05)
        info = json.loads((folder / 'next-runtime-info.json').read_text())
        origin = info['origin']
        async with ClientSession() as client:
            endpoint = origin + '/api/v1/rnsh/sessions'
            assert (await client.get(endpoint)).status == 403
            headers = {'X-neXt-Session': info['capability']}
            response = await client.get(origin + '/api/v1/auth/csrf', headers=headers)
            assert response.status == 200
            headers['X-CSRF-Token'] = (await response.json())['csrf_token']
            assert (await client.get(endpoint, headers=headers)).status == 200
            assert (await client.post(endpoint, headers={'X-neXt-Session': info['capability']}, json={})).status == 403
            async with client.ws_connect(origin + '/ws', headers=headers) as ws:
                response = await client.post(endpoint, headers=headers, json={'destination': 'ab' * 16, 'autostart': False})
                assert response.status == 200, await response.text()
                identifier = (await response.json())['session']['id']
                response = await client.post(endpoint + '/' + identifier + '/clear', headers=headers, json={})
                assert response.status == 200
                async with asyncio.timeout(5):
                    while True:
                        event = await ws.receive_json()
                        if event.get('type') == 'rnsh.session.change':
                            assert event['session_id'] == identifier
                            break
                listed = await (await client.get(endpoint, headers=headers)).json()
                assert listed['sessions'][0]['id'] == identifier
                assert listed['sessions'][0]['status'] == 'stopped'
        proof = dict(actual_ios_server=True, session_capability_required=True, csrf_required=True,
                     real_routes_registered=True, websocket_change_delivered=True,
                     public_peers_enabled=False, commands_executed=False)
        (folder / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
        print(json.dumps(proof))
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    assert not (folder / 'next-runtime-info.json').exists()
    saved = list((folder / 'rnsh').glob('*/sessions.json'))
    assert len(saved) == 1 and json.loads(saved[0].read_text())[0]['config']['autostart'] is False


if __name__ == '__main__': asyncio.run(main(Path(sys.argv[1]).resolve()))
