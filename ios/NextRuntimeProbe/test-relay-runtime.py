"""Private CBOR2 iOS client versus unmodified desktop CBORx Relay Chat hub."""
import argparse,asyncio,json,os,socket,sys,time
from contextlib import ExitStack
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'ios/NextRuntimeProbe'),str(ROOT/'app/src/main/python')]
if os.environ.get('NEXT_RELAY_BACKEND'):sys.path.insert(0,os.environ['NEXT_RELAY_BACKEND'])
from test_next_ios_tcp_integration import api,backend,start,wait


def reference_hub(folder,port,reference_source,pipe):
    sys.path.insert(0,str(reference_source))
    import RNS
    from meshchatnext.src.backend.rrc import protocol
    from meshchatnext.src.backend.rrc.server import RRCServerManager
    from meshchatnext.src.backend.rrc.manager import RRCManager
    assert protocol.cborx.__name__=='cborx','Reference must use the real desktop codec'
    folder.mkdir()
    (folder/'config').write_text('[reticulum]\nshare_instance = No\nenable_transport = No\n[interfaces]\n[[Private Relay Chat]]\ntype = TCPServerInterface\nenabled = Yes\nlisten_ip = 127.0.0.1\nlisten_port = '+str(port)+'\n')
    RNS.Reticulum(configdir=str(folder),loglevel=1)
    servers=RRCServerManager(str(folder/'server'))
    server=servers.create_hub(name='Private Relay Interop',announce=False)
    assert servers.create_room(server.hub_id,'general')
    assert servers.create_room(server.hub_id,'private',key='private-test-key-201')
    identity=RNS.Identity()
    client=RRCManager(identity,str(folder/'reference-client'),get_nickname=lambda:'Standard peer')
    client.set_server_manager(servers)
    hub=client.add_hub(server.dest_hash,name='Private Relay Interop');hub.connect()
    wait(lambda:hub.to_dict()['connected'])
    hub.join_room('general');hub.join_room('private',key='private-test-key-201')
    seen=set()
    def message(hub,msg):
        if msg.kind=='msg' and msg.text.startswith('client ') and msg.text not in seen:
            seen.add(msg.text);hub.send_message(msg.room,'server echo: '+msg.text)
    client.set_message_callback(message)
    pipe.send({'hub_hash':server.dest_hash.hex(),'reference_codec':'cborx'})
    try:
        while True:
            command=pipe.recv()
            if command.get('op')=='announce':server.announce_now()
            elif command.get('op')=='seen':pipe.send(sorted(seen))
            elif command.get('op')=='stop':break
    finally:client.shutdown();servers.shutdown()


def server(folder,ready,settings,pipe):
    from loopback_probe import serve
    from relay_runtime import RelayRuntime
    from meshchatnext.src.backend.rrc import protocol
    assert protocol.cborx.__name__=='cbor2','iOS must use the portable codec'
    frontend=folder/'frontend';frontend.mkdir(exist_ok=True)
    (frontend/'index.html').write_text('<html>Private Relay Chat test</html>')
    asyncio.run(serve(ready,frontend,settings,device=True,relay_factory=RelayRuntime))


def extract_reference(wheel,folder):
    import hashlib,importlib.util,zipfile
    from pathlib import PurePosixPath
    spec=importlib.util.spec_from_file_location('next_stage_reference',ROOT/'ios/NextRuntimeProbe/stage-backend.py')
    stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
    if hashlib.file_digest(wheel.open('rb'),'sha256').hexdigest()!=stage.NEXT_WHEEL_SHA256:
        raise ValueError('Reference hub requires the exact released backend wheel')
    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.infolist():
            path=PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe reference package member')
            if entry.is_dir():continue
            if path.parts[0]!='meshchatnext' and '.dist-info' not in path.parts[0]:continue
            if path.parts[0]=='meshchatnext' and path.suffix not in ('.py','.json','.txt','.md'):continue
            target=folder.joinpath(*path.parts);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.read(entry))
    return folder


def main(folder,reference_source=None,reference_wheel=None):
    folder.mkdir(mode=0o700,parents=True,exist_ok=False)
    if reference_wheel is not None:reference_source=extract_reference(reference_wheel,folder/'desktop-reference')
    app=folder/'preview';app.mkdir();settings=app/'settings.json'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    settings.write_text(json.dumps({'peers':[dict(id='private-relay',host='127.0.0.1',port=port,enabled=True)]}))
    with ExitStack() as stack:
        _,reference=start(stack,reference_hub,folder/'reference',port,reference_source)
        assert reference.poll(20);details=reference.recv();assert details['reference_codec']=='cborx'
        hub_hash=details['hub_hash'];prefix='rrc/hubs/'+hub_hash
        with ExitStack() as first:
            ready=app/'first.url';start(first,server,app,ready,settings);wait(ready.exists);base=backend(ready)
            identity=(app/'reticulum/identity').read_bytes()
            assert api(base,'rrc/hubs')[1]['hubs']==[]
            assert api(base,'rrc/servers')[1]['hubs']==[]
            assert api(base,'rrc/hubs/order',body={'hub_hashes':[]},method='PUT')[0]==403
            token=api(base,'auth/csrf')[1]['csrf_token']
            wait(lambda:any(row['online'] for row in api(base,'preview/reticulum-connections')[1]['peers']))
            reference.send({'op':'announce'})
            announced=wait(lambda:api(base,'announces?aspect=rrc.hub')[1]['announces'])
            assert announced[0]['destination_hash']==hub_hash and announced[0]['display_name']=='Private Relay Interop'
            assert api(base,'announces?aspect=rrc.hub&search=Interop')[1]['announces']
            assert not api(base,'announces?aspect=rrc.hub&search=NoSuchHub')[1]['announces']
            assert not any(row['destination_hash']==hub_hash for row in api(base,'announces')[1]['announces'])
            assert api(base,'rrc/hubs',body={'hub_hash':hub_hash,'name':'Private test hub','connect':True},token=token)[0]==200
            wait(lambda:api(base,'rrc/hubs')[1]['hubs'][0]['connected'])
            for room in ('general','private'):
                payload={'room':room}
                if room=='private':payload.update(key='private-test-key-201',remember=True)
                assert api(base,prefix+'/rooms',body=payload,token=token)[0]==200
                text='client initial '+room
                assert api(base,prefix+'/rooms/'+room+'/messages',body={'text':text},token=token)[0]==200
                def received():
                    messages=api(base,prefix+'/rooms/'+room+'/messages')[1]['messages']
                    return messages if any(row['text']=='server echo: '+text for row in messages) and any(row['text']==text and row.get('delivery')=='sent' for row in messages) else None
                wait(received)
            reference.send({'op':'seen'});assert reference.poll(10)
            assert {'client initial general','client initial private'}.issubset(reference.recv())
            assert api(base,prefix+'/room-keys')[1]['keys'][0]['room']=='private'
            assert all(b'private-test-key-201' not in p.read_bytes() for p in (app/'relay-chat').rglob('*') if p.is_file())
            assert api(base,'telephone/contacts')[1]['contacts']==[]
            assert api(base,'lxmf/conversations')[1]['conversations']==[]
            assert api(base,'config',body={'rrc_enabled':False},method='PATCH',token=token)[0]==200
            assert api(base,'rrc/hubs')[0]==503
        ready=app/'second.url';start(stack,server,app,ready,settings);wait(ready.exists);base=backend(ready)
        assert (app/'reticulum/identity').read_bytes()==identity
        assert api(base,'config')[1]['config']['rrc_enabled'] is False
        assert api(base,'rrc/hubs')[0]==503
        token=api(base,'auth/csrf')[1]['csrf_token']
        assert api(base,'config',body={'rrc_enabled':True},method='PATCH',token=token)[0]==200
        reference.send({'op':'announce'})
        wait(lambda:api(base,'rrc/hubs')[1]['hubs'][0]['connected'])
        for room in ('general','private'):
            old=api(base,prefix+'/rooms/'+room+'/messages')[1]['messages']
            assert any(row['text']=='client initial '+room for row in old)
            assert any(row['text']=='server echo: client initial '+room for row in old)
            text='client after restart '+room
            assert api(base,prefix+'/rooms/'+room+'/messages',body={'text':text},token=token)[0]==200
            wait(lambda:any(row['text']=='server echo: '+text for row in api(base,prefix+'/rooms/'+room+'/messages')[1]['messages']))
        assert api(base,prefix,body={},method='DELETE',token=token)[0]==200
        assert api(base,'rrc/hubs')[1]['hubs']==[]
        assert api(base,'telephone/contacts')[1]['contacts']==[]
    proof={'ok':True,'public_network':False,'standard_desktop_codec':'cborx','mobile_codec':'pure-Python cbor2',
           'real_reticulum_link':True,'both_message_directions':True,'hub_receipts_confirmed':True,
           'public_and_keyed_private_rooms':True,'keys_encrypted_at_rest':True,'identity_unchanged':True,
           'history_and_rooms_survived_restart':True,'disabled_service_remained_off_after_restart':True,
           'stored_key_rejoined_after_enable':True,'put_csrf_required':True,'no_dm_contacts_or_conversations_created':True}
    (folder/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--work-dir',type=Path,required=True)
    parser.add_argument('--backend-source',type=Path,required=True)
    reference=parser.add_mutually_exclusive_group(required=True)
    reference.add_argument('--reference-source',type=Path);reference.add_argument('--reference-wheel',type=Path)
    args=parser.parse_args();os.environ['NEXT_RELAY_BACKEND']=str(args.backend_source.resolve());sys.path.insert(0,os.environ['NEXT_RELAY_BACKEND'])
    main(args.work_dir.resolve(),args.reference_source.resolve() if args.reference_source else None,args.reference_wheel.resolve() if args.reference_wheel else None)
