"""Explicit mailbox opt-in, one retry, and truthful delivery semantics."""
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import sys
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'ios/NextRuntimeProbe'), str(ROOT / 'app/src/main/python')]
import LXMF
from outbound_mailbox import retry_via_mailbox
from offline_mailbox import OfflineMailbox
from test_next_ios_offline_mailbox import Router


def test_existing_mailbox_migration_preserves_address_and_never_enables_sending(tmp_path):
    path = tmp_path / 'existing.sqlite3'
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE next_mailbox (id INTEGER PRIMARY KEY CHECK(id=1), address TEXT NOT NULL)')
    db.execute('INSERT INTO next_mailbox VALUES (1, ?)', ('ab'*16,))
    db.execute('CREATE TABLE messages (content TEXT)')
    db.execute("INSERT INTO messages VALUES ('keep private history')"); db.commit()
    mailbox = OfflineMailbox(db, Router(), object(), lambda: None)
    assert mailbox.address == 'ab'*16 and mailbox.outbound_node() is None
    assert mailbox.snapshot()['send_fallback'] is False
    mailbox.configure({'address':'ab'*16, 'send_fallback':True})
    assert mailbox.outbound_node() == bytes.fromhex('ab'*16)
    mailbox.close(); db.close()
    db = sqlite3.connect(path)
    restored = OfflineMailbox(db, Router(), object(), lambda: None)
    assert restored.outbound_node() == bytes.fromhex('ab'*16)
    restored.configure({'address':''})
    assert restored.outbound_node() is None and not restored.send_fallback
    assert db.execute('SELECT content FROM messages').fetchone()[0] == 'keep private history'
    db.close()


@pytest.mark.parametrize('payload',[{'address':'','send_fallback':True}, {'address':'ab'*16,'send_fallback':1}, {'address':'ab'*16,'send_fallback':'yes'}])
def test_invalid_opt_in_does_not_change_saved_relay(tmp_path,payload):
    db=sqlite3.connect(tmp_path/'history.sqlite3')
    mailbox=OfflineMailbox(db,Router(),object(),lambda:None)
    mailbox.configure({'address':'ab'*16})
    with pytest.raises(ValueError):mailbox.configure(payload)
    assert mailbox.address=='ab'*16 and mailbox.outbound_node() is None
    db.close()


class OutboundRouter:
    def __init__(self): self.sent=[]; self.node=None
    def set_outbound_propagation_node(self,node): self.node=node
    def handle_outbound(self,message): self.sent.append(message)


def failed_message():
    return SimpleNamespace(state=LXMF.LXMessage.FAILED, desired_method=LXMF.LXMessage.DIRECT,
        packed=b'original',delivery_attempts=5,next_delivery_attempt=999,
        hash=b'h'*32,timestamp=1700000000,fields={LXMF.FIELD_REPLY_TO:b'r'*32})


def test_one_fallback_preserves_message_identity_timestamp_reply_and_stops_after_retry():
    message=failed_message();router=OutboundRouter();node=b'n'*16
    before=(message.hash,message.timestamp,message.fields.copy())
    assert retry_via_mailbox(message,router,node,node,automatic=True)
    assert router.sent==[message] and router.node==node
    assert (message.hash,message.timestamp,message.fields)==before
    assert message.desired_method==LXMF.LXMessage.PROPAGATED
    assert message.packed is None and message.delivery_attempts==0 and not hasattr(message,'next_delivery_attempt')
    assert not retry_via_mailbox(message,router,node,node,automatic=True)
    assert len(router.sent)==1


@pytest.mark.parametrize('automatic,selected,current',[(False,b'n'*16,b'n'*16),(True,None,None),(True,b'n'*16,None),(True,b'n'*16,b'x'*16)])
def test_manual_direct_off_or_changed_opt_in_cannot_submit_to_relay(automatic,selected,current):
    message=failed_message();router=OutboundRouter()
    assert not retry_via_mailbox(message,router,selected,current,automatic=automatic)
    assert not router.sent and router.node is None and message.packed==b'original'


def test_submission_error_remains_failed_and_does_not_loop():
    message=failed_message();router=OutboundRouter();node=b'n'*16
    def fail(_):raise OSError('private relay detail')
    router.handle_outbound=fail
    assert not retry_via_mailbox(message,router,node,node,automatic=True)
    assert message.state==LXMF.LXMessage.FAILED
    assert not retry_via_mailbox(message,router,node,node,automatic=True)


def run_outbound_http(folder, ready, settings, recipient_public, pipe):
    import asyncio
    import json
    import RNS
    from messaging_probe import MessagingProbe
    from loopback_probe import serve
    original = MessagingProbe.__init__
    def initialize(self,*args,**kwargs):
        original(self,*args,**kwargs)
        identity=RNS.Identity(create_keys=False);identity.load_public_key(recipient_public)
        address=RNS.Destination.hash_from_name_and_identity('lxmf.delivery',identity)
        RNS.Identity.remember(None,address,recipient_public)
    MessagingProbe.__init__=initialize
    original_compose=MessagingProbe.compose
    def compose(self,*args,**kwargs):
        if (folder/'pause-next-compose').exists():
            import time
            (folder/'compose-paused').touch()
            deadline=time.monotonic()+15
            while not (folder/'resume-compose').exists():
                if time.monotonic()>deadline:raise TimeoutError('Private fixture barrier timed out')
                time.sleep(.05)
            (folder/'pause-next-compose').unlink()
        return original_compose(self,*args,**kwargs)
    MessagingProbe.compose=compose
    # Exercise the actual signature verifier and actual relay spool. Only the
    # APNs delivery and HTTPS transport are mocked; no Apple credentials exist.
    import mailbox_push
    sys.path.insert(0, str(ROOT / 'ios/push-provider'))
    from provider import Provider
    sender = RNS.Identity.from_file(str(folder/'reticulum/identity'))
    identity = RNS.Identity(create_keys=False); identity.load_public_key(recipient_public)
    destination = RNS.Destination.hash_from_name_and_identity('lxmf.delivery',identity).hex()
    def alert(token, packet):
        with (folder/'mock-alerts.jsonl').open('a') as output:
            output.write(json.dumps({'token':token,'packet':packet})+'\n')
    def post(route,payload):
        assert route.provider == 'https://alerts.example.invalid'
        hint = json.loads(payload)
        assert set(hint) == {'recipient','message','sender','issued','signature'}
        # Like the real single-threaded HTTP provider, own its SQLite connection
        # on the thread that verifies the request rather than borrowing the app loop's.
        provider = Provider('private outbound test', folder.parent/'relay/lxmf/messagestore',
            {destination: {'token':'mock-device','senders':[sender.get_public_key().hex()]}}, folder/'mock-provider.sqlite3', alert)
        try: return provider.notify(hint)
        finally: provider.database.close()
    mailbox_push._post = post
    frontend=folder/'frontend';frontend.mkdir(exist_ok=True)
    (frontend/'index.html').write_text('<html>Private outbound mailbox fixture</html>')
    asyncio.run(serve(ready,frontend,settings,device=True))


@pytest.mark.parametrize("delivery_method", ["propagated", None], ids=["manual", "automatic"])
def test_real_http_message_and_attachment_are_relayed_while_recipient_offline(tmp_path,monkeypatch,delivery_method):
    import base64,json,os,socket
    from contextlib import ExitStack
    import RNS
    from test_ios_tcp_runtime import run_mailbox,start_process
    from test_next_ios_mailbox_commit import run_recipient,rpc,wait as wait_recipient
    from test_next_ios_tcp_integration import api,backend,start,wait
    root=Path(__file__).resolve().parents[1]
    monkeypatch.setenv('PYTHONPATH',os.pathsep.join([str(root/'ios/NextRuntimeProbe'),str(root/'app/src/main/python'),os.environ.get('PYTHONPATH','')]))
    source_identity=RNS.Identity()
    source_address=RNS.Destination.hash_from_name_and_identity('lxmf.delivery',source_identity).hex()
    known_sender=(source_address,source_identity.get_public_key().hex())
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    with ExitStack() as stack:
        relay=start_process(stack,run_mailbox,tmp_path/'relay',port)
        assert relay.poll(10);mailbox=relay.recv()
        receiver_folder=tmp_path/'receiver'
        with ExitStack() as offline_setup:
            recipient=start_process(offline_setup,run_recipient,receiver_folder,port,mailbox,known_sender)
            assert recipient.poll(12);recipient_public=recipient.recv()
        identity=RNS.Identity(create_keys=False);identity.load_public_key(recipient_public)
        recipient_address=RNS.Destination.hash_from_name_and_identity('lxmf.delivery',identity).hex()
        sender_folder=tmp_path/'sender';(sender_folder/'reticulum').mkdir(parents=True)
        assert source_identity.to_file(str(sender_folder/'reticulum/identity'))
        settings=sender_folder/'settings.json'
        settings.write_text(json.dumps({'peers':[dict(id='private-relay',host='127.0.0.1',port=port,enabled=True)]}))
        ready=sender_folder/'backend.url';start(stack,run_outbound_http,sender_folder,ready,settings,recipient_public)
        wait(ready.exists);base=backend(ready);token=api(base,'auth/csrf')[1]['csrf_token']
        wait(lambda:any(row['online'] for row in api(base,'preview/reticulum-connections')[1]['peers']))
        assert api(base,'telephone/contacts',body={'name':'Private offline recipient','lxmf_address':recipient_address},token=token)[0]==200
        assert api(base,'preview/mailbox',body={'address':mailbox},token=token)[0]==200
        file_bytes=b'Private encrypted relay attachment\x00\xff'
        draft={'delivery_method':'propagated','lxmf_message':{'destination_hash':recipient_address,
            'content':'Offline neXt relay proof','fields':{'file_attachments':[{'file_name':'proof.bin','file_bytes':base64.b64encode(file_bytes).decode()}]}}}
        assert api(base,'lxmf-messages/send',body={**draft,'delivery_method':'propagated'},token=token)[0]==400
        assert api(base,'lxmf-messages/conversation/'+recipient_address)[1]['lxmf_messages']==[]
        assert api(base,'preview/mailbox',body={'address':mailbox,'send_fallback':True},token=token)[0]==200
        contact_id=api(base,'telephone/contacts')[1]['contacts'][0]['id']
        route_path=f'telephone/contacts/{contact_id}/mailbox-alert-route'
        assert api(base,route_path,body={'route':{'provider':'https://alerts.example.invalid','audience':'private outbound test','relay':mailbox}},token=token)[0]==200
        assert not (sender_folder/'mock-alerts.jsonl').exists()
        draft['delivery_method']=delivery_method
        response=api(base,'lxmf-messages/send',body=draft,token=token)
        assert response[0]==200,response
        message_hash=response[1]['lxmf_message']['hash']
        def accepted():
            rows=api(base,'lxmf-messages/conversation/'+recipient_address)[1]['lxmf_messages']
            return next((row for row in rows if row['hash']==message_hash and row['state']=='sent'),None)
        sent=wait(accepted,timeout=60)
        assert sent['method']=='propagated' and sent['state']!='delivered'
        wait(lambda:(sender_folder/'mock-alerts.jsonl').exists())
        hints=[json.loads(line) for line in (sender_folder/'mock-alerts.jsonl').read_text().splitlines()]
        assert len(hints)==1 and hints[0]['token']=='mock-device'
        stored=list((tmp_path/'relay/lxmf/messagestore').iterdir())
        assert stored and all(b'Offline neXt relay proof' not in p.read_bytes() and file_bytes not in p.read_bytes() for p in stored if p.is_file())
        with ExitStack() as online:
            recipient=start_process(online,run_recipient,receiver_folder,port,mailbox,known_sender)
            assert recipient.poll(12) and recipient.recv()==recipient_public
            wait_recipient(recipient,lambda row:row['online'])
            rpc(recipient,'allow-save');rpc(recipient,'sync')
            received=wait_recipient(recipient,lambda row:row['complete'] and row['count']==1)
            assert received['texts']==['Offline neXt relay proof']
            rpc(recipient,'sync');assert wait_recipient(recipient,lambda row:row['complete'])['count']==1
        with sqlite3.connect(receiver_folder/'history.sqlite3') as db:
            payload=json.loads(db.execute('SELECT payload FROM messages').fetchone()[0])
        assert payload['hash']==message_hash
        assert base64.b64decode(payload['fields']['file_attachments'][0]['file_bytes'])==file_bytes
        assert api(base,'preview/mailbox',body={'address':'','send_fallback':False},token=token)[1]['status']=='off'
        assert api(base,'lxmf-messages/send',body={**draft,'delivery_method':'propagated'},token=token)[0]==400
        # An opt-out during a worker's path/compose wait must win before submission.
        from concurrent.futures import ThreadPoolExecutor
        assert api(base,'preview/mailbox',body={'address':mailbox,'send_fallback':True},token=token)[0]==200
        assert api(base,'config')[1]['config']['lxmf_preferred_propagation_node_destination_hash']==mailbox
        (sender_folder/'pause-next-compose').touch()
        pending={'delivery_method':'propagated','lxmf_message':{'destination_hash':recipient_address,'content':'Must never reach relay'}}
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(api,base,'lxmf-messages/send',body=pending,token=token)
            wait(lambda:(sender_folder/'compose-paused').exists())
            assert api(base,'config',method='PATCH',body={'auto_send_failed_messages_to_propagation_node':False},token=token)[0]==200
            assert api(base,'config')[1]['config']['lxmf_preferred_propagation_node_destination_hash'] is None
            (sender_folder/'resume-compose').touch()
            assert future.result(timeout=10)[0]==400
        rows=api(base,'lxmf-messages/conversation/'+recipient_address)[1]['lxmf_messages']
        assert len(rows)==1 and rows[0]['hash']==message_hash
