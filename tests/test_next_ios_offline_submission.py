# SPDX-License-Identifier: 0BSD
"""Ordinary sends commit before pathfinding on a disconnected known peer."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import socket
import sqlite3
import time

from next_gated_tcp import GatedProxy
from test_next_ios_tcp_integration import api, backend, run_hub, run_server, start, wait


def test_known_contact_message_is_saved_while_tcp_is_down_then_delivered_once(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); target = listener.getsockname()[1]
    with ExitStack() as stack:
        _, hub = start(stack, run_hub, tmp_path/'receiver', [target])
        assert hub.poll(10); address = hub.recv()
        proxy = GatedProxy(0, target).start()
        stack.callback(lambda: proxy.close() if proxy.thread.is_alive() else None)
        folder = tmp_path/'sender'; folder.mkdir()
        settings = folder/'settings.json'
        settings.write_text(json.dumps(dict(address=address, peers=[dict(
            id='private', host='127.0.0.1', port=proxy.port, enabled=True)])))
        ready = folder/'backend.url'
        start(stack, run_server, folder, ready, settings)
        wait(ready.exists); base = backend(ready)
        token = api(base, 'auth/csrf')[1]['csrf_token']
        own = ready.with_suffix('.address').read_text()
        last_request = 0
        def announced():
            nonlocal last_request
            if time.monotonic()-last_request > 2:
                hub.send({'announce': True}); last_request = time.monotonic()
            return any(x['destination_hash']==address for x in api(base, 'announces')[1]['announces'])
        wait(announced)
        warmup = dict(lxmf_message=dict(destination_hash=address, content='Private warmup'))
        assert api(base, 'lxmf-messages/send', body=warmup, token=token)[0] == 200
        wait(lambda: any(x['content']=='Echo: Private warmup' for x in
             api(base, 'lxmf-messages/conversation/'+address)[1]['lxmf_messages']))
        proxy.close()
        wait(lambda: not api(base, 'preview/reticulum-connections')[1]['peers'][0]['online'])
        content = 'Queued before path recovery: Привет 🌲'
        with ThreadPoolExecutor(max_workers=1) as pool:
            submitted = pool.submit(api, base, 'lxmf-messages/send',
                body=dict(lxmf_message=dict(destination_hash=address, content=content)), token=token)
            wait(submitted.done, timeout=3)
            status, response = submitted.result()
        assert status == 200, response
        saved = response['lxmf_message']; assert saved['state']=='sending'
        database = folder/('messages-'+own+'.sqlite3')
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT state FROM messages WHERE hash=?', (saved['hash'],)).fetchone()==('sending',)
            assert db.execute('SELECT COUNT(*) FROM next_pending_messages WHERE hash=?', (saved['hash'],)).fetchone()==(1,)
        proxy = GatedProxy(proxy.port, target).start()
        wait(lambda: api(base, 'preview/reticulum-connections')[1]['peers'][0]['online'])
        # The standard transport requests the route. Do not edit the peer or
        # manually submit the saved message again after reconnection.
        def completed():
            rows = api(base, 'lxmf-messages/conversation/'+address)[1]['lxmf_messages']
            return (any(x['hash']==saved['hash'] and x['state']=='delivered' for x in rows)
                and any(x['content']=='Echo: '+content and not x['is_outbound'] for x in rows))
        wait(completed, timeout=90)
        rows = api(base, 'lxmf-messages/conversation/'+address)[1]['lxmf_messages']
        assert sum(x['hash']==saved['hash'] for x in rows)==1
        assert sum(x['content']=='Echo: '+content for x in rows)==1
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()==(0,)
        (tmp_path/'proof.json').write_text(json.dumps(dict(
            known_identity=True, saved_before_route=True, original_hash=saved['hash'],
            delivered_once=True, signed_echo=True, private_loopback_only=True,
            actual_ipad=False), indent=2)+'\n')
