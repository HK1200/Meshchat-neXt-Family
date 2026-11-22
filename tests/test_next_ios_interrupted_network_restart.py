# SPDX-License-Identifier: 0BSD
"""Normal signed submission survives a real TCP interruption and process exit."""
from contextlib import ExitStack
import base64
import hashlib
import json
import socket
import sqlite3
import time

from next_gated_tcp import GatedProxy
from test_next_ios_tcp_integration import api,backend,run_hub,run_server,start,wait


def test_committed_attachment_recovers_after_network_hold_and_process_termination(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));target_port=listener.getsockname()[1]
    with ExitStack() as stack:
        _receiver,commands=start(stack,run_hub,tmp_path/'receiver',[target_port])
        assert commands.poll(10);destination=commands.recv()
        proxy=GatedProxy(0,target_port).start()
        # Cleanup refers to the current proxy after the mid-test replacement.
        stack.callback(lambda:proxy.close() if proxy.thread.is_alive() else None)
        settings=dict(address=destination,peers=[dict(id='private',host='127.0.0.1',port=proxy.port,enabled=True)])
        folder=tmp_path/'sender';folder.mkdir()
        fixture=folder/'settings.json';fixture.write_text(json.dumps(settings))
        ready=folder/'backend.url'
        sender,_=start(stack,run_server,folder,ready,fixture)
        wait(ready.exists);base=backend(ready)
        own=ready.with_suffix('.address').read_text()
        token=api(base,'auth/csrf')[1]['csrf_token']
        last_request=0
        def announced():
            nonlocal last_request
            if time.monotonic()-last_request>2:
                commands.send({'announce':True});last_request=time.monotonic()
            observed=tmp_path/'receiver/observed-name.json'
            return (observed.exists() and json.loads(observed.read_text())['address']==own
                    and any(row['destination_hash']==destination for row in api(base,'announces')[1]['announces']))
        wait(announced)
        proxy.held.set();before_bytes=proxy.forwarded[0]
        content='Normal interrupted send: Привет 🌲'
        attachment=b'Exact private resource\x00\xff'*2500
        photo=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=')
        draft=dict(lxmf_message=dict(destination_hash=destination,content=content,fields=dict(
            file_attachments=[dict(file_name='restart.bin',file_bytes=base64.b64encode(attachment).decode())],
            image=dict(image_bytes=base64.b64encode(photo).decode()))))
        status,result=api(base,'lxmf-messages/send',body=draft,token=token)
        assert status==200,result
        saved=result['lxmf_message'];assert saved['state']=='sending'
        time.sleep(.2);assert proxy.forwarded[0]==before_bytes
        sender.terminate();sender.join(timeout=5);assert not sender.is_alive()
        proxy.close()
        database=folder/('messages-'+own+'.sqlite3')
        identity_sha=hashlib.sha256((folder/'reticulum/identity').read_bytes()).hexdigest()
        with sqlite3.connect(database) as db:
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            packet=db.execute('SELECT packet FROM next_pending_messages WHERE hash=?',(saved['hash'],)).fetchone()[0]
            assert len(packet)>len(attachment)
            assert db.execute('SELECT state FROM messages WHERE hash=?',(saved['hash'],)).fetchone()==('sending',)
        proxy=GatedProxy(proxy.port,target_port).start()
        ready.unlink()
        _recovered,_=start(stack,run_server,folder,ready,fixture)
        wait(ready.exists);base=backend(ready)
        assert hashlib.sha256((folder/'reticulum/identity').read_bytes()).hexdigest()==identity_sha
        commands.send({'announce':True})
        def completed():
            rows=api(base,'lxmf-messages/conversation/'+destination)[1]['lxmf_messages']
            sent=next((row for row in rows if row['hash']==saved['hash'] and row['state']=='delivered'),None)
            echo=next((row for row in rows if row['content']=='Echo: '+content and not row['is_outbound']),None)
            return echo if sent and echo else None
        echo=wait(completed,timeout=75)
        with sqlite3.connect(database) as db:
            restored=json.loads(db.execute('SELECT payload FROM messages WHERE hash=?',(echo['hash'],)).fetchone()[0])
            assert base64.b64decode(restored['fields']['file_attachments'][0]['file_bytes'])==attachment
            assert base64.b64decode(restored['fields']['image']['image_bytes'])==photo
            assert db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0]==0
        (tmp_path/'proof.json').write_text(json.dumps(dict(normal_api_no_send_hooks=True,
            loopback_only=True,held_bytes_not_forwarded=True,original_hash=saved['hash'],
            exact_file_bytes=len(attachment),identity_preserved=True,cold_restart_delivered=True,
            actual_ipad=False),indent=2)+'\n')
