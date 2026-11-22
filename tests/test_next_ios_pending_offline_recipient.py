# SPDX-License-Identifier: 0BSD
"""A pending offline delivery must not depend on another recipient announce."""
from contextlib import ExitStack
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]


def run_crashing_offline_sender(folder,ready,settings,recipient_public,pipe):
    sys.path[:0]=[str(ROOT/'ios/NextRuntimeProbe'),str(ROOT/'app/src/main/python')]
    from messaging_probe import MessagingProbe
    from test_next_ios_outbound_mailbox import run_outbound_http
    def stop_after_commit(self,message):
        (folder/'committed.json').write_text(json.dumps(dict(hash=message.hash.hex(),source=self.source.hash.hex())))
        os._exit(73)
    MessagingProbe.send=stop_after_commit
    run_outbound_http(folder,ready,settings,recipient_public,pipe)


def test_cold_restart_recovers_propagation_when_recipient_never_announces(tmp_path,monkeypatch):
    import RNS
    from test_ios_tcp_runtime import run_mailbox,start_process
    from test_next_ios_mailbox_commit import run_recipient,rpc,wait as recipient_wait
    from test_next_ios_tcp_integration import api,backend,run_server,start,wait
    monkeypatch.setenv('PYTHONPATH',os.pathsep.join([str(ROOT/'ios/NextRuntimeProbe'),str(ROOT/'app/src/main/python'),str(ROOT/'tests'),os.environ.get('PYTHONPATH','')]))
    sender_identity=RNS.Identity();recipient_identity=RNS.Identity()
    sender_address=RNS.Destination.hash_from_name_and_identity('lxmf.delivery',sender_identity).hex()
    recipient_address=RNS.Destination.hash_from_name_and_identity('lxmf.delivery',recipient_identity).hex()
    # Prepare the offline identity without starting a recipient transport. The
    # relay cannot possibly supply a cached announce for this destination.
    recipient_folder=tmp_path/'recipient';(recipient_folder/'reticulum-simulator').mkdir(parents=True)
    assert recipient_identity.to_file(str(recipient_folder/'reticulum-simulator/identity'))
    with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    with ExitStack() as stack:
        relay=start_process(stack,run_mailbox,tmp_path/'relay',port)
        assert relay.poll(10);mailbox=relay.recv()
        folder=tmp_path/'sender';(folder/'reticulum').mkdir(parents=True)
        assert sender_identity.to_file(str(folder/'reticulum/identity'))
        fixture=folder/'settings.json';fixture.write_text(json.dumps(dict(peers=[dict(id='private-relay',host='127.0.0.1',port=port,enabled=True)])))
        ready=folder/'backend.url'
        first,_=start(stack,run_crashing_offline_sender,folder,ready,fixture,recipient_identity.get_public_key())
        wait(ready.exists);base=backend(ready);token=api(base,'auth/csrf')[1]['csrf_token']
        wait(lambda:any(row['online'] for row in api(base,'preview/reticulum-connections')[1]['peers']))
        assert api(base,'telephone/contacts',body=dict(name='Offline private recipient',lxmf_address=recipient_address),token=token)[0]==200
        assert api(base,'preview/mailbox',body=dict(address=mailbox,send_fallback=True),token=token)[0]==200
        file_bytes=b'Offline restart resource\x00\xff'*1500
        draft=dict(delivery_method='propagated',lxmf_message=dict(destination_hash=recipient_address,
            content='Pending offline recipient',fields=dict(file_attachments=[dict(file_name='offline.bin',file_bytes=base64.b64encode(file_bytes).decode())])))
        try:api(base,'lxmf-messages/send',body=draft,token=token)
        except OSError:pass
        first.join(timeout=10);assert first.exitcode==73
        saved=json.loads((folder/'committed.json').read_text())
        database=folder/('messages-'+sender_address+'.sqlite3')
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0]==1
        ready.unlink();start(stack,run_server,folder,ready,fixture)
        wait(ready.exists);base=backend(ready)
        def accepted():
            rows=api(base,'lxmf-messages/conversation/'+recipient_address)[1]['lxmf_messages']
            return next((row for row in rows if row['hash']==saved['hash'] and row['state']=='sent'),None)
        sent=wait(accepted,timeout=45)
        assert sent['method']=='propagated' and not recipient_folder.joinpath('history.sqlite3').exists()
        recipient=start_process(stack,run_recipient,recipient_folder,port,mailbox,(sender_address,sender_identity.get_public_key().hex()))
        assert recipient.poll(12) and recipient.recv()==recipient_identity.get_public_key()
        recipient_wait(recipient,lambda row:row['online']);rpc(recipient,'allow-save');rpc(recipient,'sync')
        received=recipient_wait(recipient,lambda row:row['complete'] and row['count']==1)
        assert received['texts']==['Pending offline recipient']
        with sqlite3.connect(recipient_folder/'history.sqlite3') as db:
            payload=json.loads(db.execute('SELECT payload FROM messages').fetchone()[0])
        assert payload['hash']==saved['hash']
        assert base64.b64decode(payload['fields']['file_attachments'][0]['file_bytes'])==file_bytes
        assert hashlib.sha256((folder/'reticulum/identity').read_bytes()).digest()==hashlib.sha256(sender_identity.get_private_key()).digest()
