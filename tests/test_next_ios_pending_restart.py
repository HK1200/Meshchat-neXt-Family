"""A process dies after durable commit; standard signed LXMF recovers on restart."""
from contextlib import ExitStack
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_crashing_sender(folder, ready, settings, after_delivery, pipe):
    sys.path[:0] = [str(ROOT/'ios/NextRuntimeProbe'), str(ROOT/'app/src/main/python')]
    from messaging_probe import MessagingProbe
    from test_next_ios_tcp_integration import run_server
    original = MessagingProbe.send
    def crash_before_transport(self, message):
        def crash(_message):
            (folder/'committed-before-crash.json').write_text(json.dumps(dict(hash=message.hash.hex(), source=self.source.hash.hex())))
            os._exit(73)
        if after_delivery:
            # The peer's real delivery proof arrives, but its local completion
            # callback is interrupted before it can commit Delivered.
            message.register_delivery_callback(crash)
            return original(self, message)
        # No mock transport succeeds: exit before handing any packet to LXMF.
        crash(message)
    MessagingProbe.send = crash_before_transport
    run_server(folder, ready, settings, pipe)


def run_recovered_sender(folder, ready, settings, pipe):
    sys.path[:0] = [str(ROOT/'ios/NextRuntimeProbe'), str(ROOT/'app/src/main/python')]
    from messaging_probe import MessagingProbe
    from test_next_ios_tcp_integration import run_server
    original = MessagingProbe.send
    def observe(self, message):
        with (folder/'recovered-submissions.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(hash=message.hash.hex()))+'\n')
        return original(self, message)
    MessagingProbe.send = observe
    run_server(folder, ready, settings, pipe)


@pytest.mark.parametrize('case', ['recover', 'delete', 'corrupt', 'disabled-relay', 'ack-before-commit'])
def test_cold_restart_recovers_original_signed_attachments_without_restoring_deleted_history(tmp_path, monkeypatch, case):
    from test_next_ios_tcp_integration import api, backend, run_hub, start, wait
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(ROOT/'ios/NextRuntimeProbe'),str(ROOT/'app/src/main/python'),str(ROOT/'tests'),os.environ.get('PYTHONPATH','')]))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port=listener.getsockname()[1]
    with ExitStack() as stack:
        hub_process, hub = start(stack, run_hub, tmp_path/'hub', [port])
        assert hub.poll(10); target=hub.recv()
        folder=tmp_path/'sender'; folder.mkdir()
        settings=folder/'settings.json'; settings.write_text(json.dumps(dict(address=target,peers=[dict(id='private',host='127.0.0.1',port=port,enabled=True)])))
        ready=folder/'backend.url'
        first, _ = start(stack, run_crashing_sender, folder, ready, settings, case == 'ack-before-commit')
        wait(ready.exists); base=backend(ready); token=api(base,'auth/csrf')[1]['csrf_token']
        wait(lambda:any(row['online'] for row in api(base,'preview/reticulum-connections')[1]['peers']))
        file_bytes=b'Private restart resource\x00\xff'*2500
        photo=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=')
        content='Committed before interruption: Привет 🌲'
        draft=dict(lxmf_message=dict(destination_hash=target,content=content,fields=dict(
            file_attachments=[dict(file_name='restart.bin',file_bytes=base64.b64encode(file_bytes).decode())],
            image=dict(image_bytes=base64.b64encode(photo).decode()))))
        if case == 'ack-before-commit':
            try:
                response = api(base,'lxmf-messages/send',body=draft,token=token)
                assert response[0] == 200, response
            except (OSError, http.client.RemoteDisconnected): pass
            wait(lambda:(folder/'committed-before-crash.json').exists(),timeout=55)
        else:
            with pytest.raises((OSError, http.client.RemoteDisconnected)):
                api(base,'lxmf-messages/send',body=draft,token=token)
        first.join(timeout=15); assert first.exitcode==73
        saved=json.loads((folder/'committed-before-crash.json').read_text())
        database=folder/('messages-'+saved['source']+'.sqlite3')
        identity_sha=hashlib.sha256((folder/'reticulum/identity').read_bytes()).hexdigest()
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT state FROM messages WHERE hash=?',(saved['hash'],)).fetchone()==('sending',)
            assert db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0]==1
        if case == 'delete':
            sys.path[:0]=[str(ROOT/'ios/NextRuntimeProbe'),str(ROOT/'app/src/main/python')]
            from loopback_probe import ConversationHistory
            history=ConversationHistory(database)
            assert history.delete_conversations([target])==[saved['hash']]
            history.close()
        elif case == 'corrupt':
            with sqlite3.connect(database) as db:
                packet=db.execute('SELECT packet FROM next_pending_messages').fetchone()[0]
                packet=packet[:40]+bytes([packet[40]^1])+packet[41:]
                db.execute('UPDATE next_pending_messages SET packet=?',(packet,))
        elif case == 'disabled-relay':
            import LXMF
            with sqlite3.connect(database) as db:
                # A valid saved propagated intent cannot override a mailbox
                # that is currently off. The signed content is unchanged.
                choices=dict(method=LXMF.LXMessage.PROPAGATED,automatic=False,relay='ab'*16,route=None)
                db.execute('UPDATE next_pending_messages SET policy=?',(json.dumps(choices),))
        ready.unlink()
        recovered, _ = start(stack, run_recovered_sender, folder, ready, settings)
        wait(ready.exists); base=backend(ready)
        assert hashlib.sha256((folder/'reticulum/identity').read_bytes()).hexdigest()==identity_sha
        wait(lambda:any(row['online'] for row in api(base,'preview/reticulum-connections')[1]['peers']))
        if case in ('delete', 'corrupt', 'disabled-relay'):
            if case == 'delete':
                import time
                time.sleep(3)
                assert api(base,'lxmf-messages/conversation/'+target)[1]['lxmf_messages']==[]
            else:
                wait(lambda:any(row['hash']==saved['hash'] and row['state']=='failed' for row in api(base,'lxmf-messages/conversation/'+target)[1]['lxmf_messages']),timeout=15)
            assert not (folder/'recovered-submissions.jsonl').exists()
            with sqlite3.connect(database) as db:
                assert db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0]==0
        else:
            def complete():
                rows=api(base,'lxmf-messages/conversation/'+target)[1]['lxmf_messages']
                return (next((row for row in rows if row['hash']==saved['hash'] and row['state']=='delivered'),None)
                    and next((row for row in rows if row['content']=='Echo: '+content and not row['is_outbound']),None))
            incoming=wait(complete,timeout=65)
            submissions=[json.loads(line) for line in (folder/'recovered-submissions.jsonl').read_text().splitlines()]
            assert submissions==[dict(hash=saved['hash'])]
            with sqlite3.connect(database) as db:
                payload=json.loads(db.execute('SELECT payload FROM messages WHERE hash=?',(incoming['hash'],)).fetchone()[0])
                assert base64.b64decode(payload['fields']['file_attachments'][0]['file_bytes'])==file_bytes
                assert base64.b64decode(payload['fields']['image']['image_bytes'])==photo
                assert db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0]==0
        proof=dict(private_loopback_only=True,process_exit_after_commit=73,identity_preserved=True,
                   case=case,deleted_not_replayed=case=='delete',signed_resource_recovered=case in ('recover','ack-before-commit'),
                   original_message_hash=saved['hash'],file_bytes=len(file_bytes),actual_ipad=False)
        (tmp_path/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
