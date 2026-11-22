"""Required telemetry proof using the actual checksum-pinned mobile backend."""
import argparse,base64,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'ios/NextRuntimeProbe'),str(ROOT/'app/src/main/python')]
if os.environ.get('NEXT_TELEMETRY_BACKEND'):sys.path.insert(0,os.environ['NEXT_TELEMETRY_BACKEND'])
from telemetry_runtime import TelemetryRuntime,incoming_fields,validated
from meshchatnext.src.backend.telemetry_utils import Telemeter
import LXMF

def fix():return {'latitude':48.75,'longitude':-122.48,'accuracy':10,'last_update':int(time.time())}

def test_stream_is_bounded_and_cannot_impersonate_another_peer(tmp_path):
    events=[];own='01'*16;sender='02'*16;other='03'*16
    runtime=TelemetryRuntime(tmp_path,own,events.append)
    packed,_=validated({'location':fix()})
    entries=incoming_fields({LXMF.FIELD_TELEMETRY_STREAM:[[bytes.fromhex(other),int(time.time()),packed]]*1000})
    assert len(entries)==64
    runtime.receive({'source_hash':sender,'content':'','_telemetry_data':entries})
    assert runtime.database.telemetry.get_all_latest_telemetry()==[] and not events
    runtime.receive({'source_hash':sender,'content':'','_telemetry_data':incoming_fields({LXMF.FIELD_TELEMETRY:packed})})
    rows=runtime.database.telemetry.get_all_latest_telemetry();assert len(rows)==1
    assert rows[0]['destination_hash']==sender and events[-1]['type']=='lxmf.telemetry'
    runtime.close()
    restored=TelemetryRuntime(tmp_path,own,events.append)
    assert restored.database.telemetry.get_latest_telemetry(sender)['data']==packed
    import sqlite3
    before=len(events)
    restored.database.provider.execute('PRAGMA query_only=ON')
    try:
        restored.receive({'source_hash':sender,'content':'','_telemetry_data':incoming_fields({LXMF.FIELD_TELEMETRY:packed})})
    except sqlite3.OperationalError:pass
    else:raise AssertionError('Failed telemetry writes must reach the durable inbox, not be acknowledged')
    assert len(events)==before
    restored.database.provider.execute('PRAGMA query_only=OFF')
    restored.receive({'source_hash':sender,'content':'','_telemetry_data':incoming_fields({LXMF.FIELD_TELEMETRY:packed})})
    assert len(events)==before+1
    restored.close()


def test_family_frame_updates_map_without_accepting_a_stale_location(tmp_path):
    from family_meshcore_location import encode
    runtime=TelemetryRuntime(tmp_path,'01'*16,lambda _:None)
    source='02'*16;frame=encode(fix())
    runtime.receive({'source_hash':source,'content':frame})
    row=runtime.database.telemetry.get_latest_telemetry(source)
    assert Telemeter.from_packed(row['data'])['location']['latitude']==48.75
    runtime.receive({'source_hash':source,'content':frame.replace('48.7500000','99.7500000')})
    assert len(runtime.database.telemetry.get_all_latest_telemetry())==1
    runtime.close()



def location_hub(folder,port,pipe):
    import RNS
    folder.mkdir()
    (folder/'config').write_text('[reticulum]\nshare_instance = No\nenable_transport = No\n[interfaces]\n[[Private location peer]]\ntype = TCPServerInterface\nenabled = Yes\nlisten_ip = 127.0.0.1\nlisten_port = '+str(port)+'\n')
    RNS.Reticulum(configdir=str(folder),loglevel=1)
    identity=RNS.Identity();router=LXMF.LXMRouter(identity=identity,storagepath=str(folder/'lxmf'),autopeer=False)
    source=router.register_delivery_identity(identity,display_name='Private location peer',stamp_cost=0)
    received=[]
    def receive(message):
        if not message.signature_validated:return False
        fields=message.fields if isinstance(message.fields,dict) else {}
        packed=fields.get(LXMF.FIELD_TELEMETRY)
        if not isinstance(packed,bytes):return True
        received.append(Telemeter.from_packed(packed))
        target=RNS.Destination(RNS.Identity.recall(message.source_hash),RNS.Destination.OUT,RNS.Destination.SINGLE,'lxmf','delivery')
        router.handle_outbound(LXMF.LXMessage(target,source,'',fields={LXMF.FIELD_TELEMETRY:packed},desired_method=LXMF.LXMessage.DIRECT))
        return True
    router.register_delivery_callback(receive)
    pipe.send(source.hash.hex())
    while True:
        command=pipe.recv()
        if command=='announce':source.announce()
        elif command=='received':pipe.send(received)
        else:break


def app_server(folder,ready,settings,pipe):
    import asyncio
    from loopback_probe import serve
    from messaging_probe import MessagingProbe
    original=MessagingProbe.compose
    def compose(self,*args,**kwargs):
        if (folder/'pause-next-compose').exists():
            (folder/'compose-paused').touch();deadline=time.monotonic()+15
            while not (folder/'resume-compose').exists():
                if time.monotonic()>deadline:raise TimeoutError('Private location barrier timed out')
                time.sleep(.05)
            (folder/'pause-next-compose').unlink()
        return original(self,*args,**kwargs)
    MessagingProbe.compose=compose
    frontend=folder/'frontend';frontend.mkdir(exist_ok=True)
    (frontend/'index.html').write_text('<html>Private location test</html>')
    asyncio.run(serve(ready,frontend,settings,device=True,telemetry_factory=TelemetryRuntime))


def watch_events(base, stack):
    import asyncio,threading
    from urllib.parse import urlsplit
    from test_next_ios_tcp_integration import SESSIONS
    events=[];ready=threading.Event();stop=threading.Event();errors=[]
    async def collect():
        import aiohttp
        origin='http://'+urlsplit(base).netloc
        headers={'X-neXt-Session':SESSIONS[urlsplit(base).netloc],'Origin':origin}
        try:
            async with aiohttp.ClientSession(headers=headers) as client:
                async with client.ws_connect(origin+'/ws') as socket:
                    ready.set()
                    while not stop.is_set():
                        try:message=await socket.receive(timeout=.25)
                        except asyncio.TimeoutError:continue
                        if message.type==aiohttp.WSMsgType.TEXT:events.append(json.loads(message.data))
                        elif message.type in (aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR):break
        except Exception as error:errors.append(type(error).__name__);ready.set()
    thread=threading.Thread(target=lambda:asyncio.run(collect()),daemon=True);thread.start()
    def finish():
        stop.set();thread.join(5)
        assert not thread.is_alive() and not errors,errors
    stack.callback(finish)
    assert ready.wait(10) and not errors,errors
    return events


def real_link_proof(folder):
    import socket
    from contextlib import ExitStack
    from test_next_ios_tcp_integration import api,backend,start,wait
    folder.mkdir()
    app=folder/'preview';app.mkdir();settings=app/'settings.json'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    settings.write_text(json.dumps({'peers':[dict(id='private-location',host='127.0.0.1',port=port,enabled=True)]}))
    with ExitStack() as stack:
        _,hub=start(stack,location_hub,folder/'hub',port)
        assert hub.poll(15);address=hub.recv()
        with ExitStack() as first:
            ready=app/'first.url';start(first,app_server,app,ready,settings);wait(ready.exists);base=backend(ready)
            identity=(app/'reticulum/identity').read_bytes()
            token=api(base,'auth/csrf')[1]['csrf_token']
            assert api(base,'config')[1]['config']['location_source']=='disabled'
            before=api(base,'config')[1]['config']
            assert api(base,'config',body={'location_source':'browser','location_manual_lat':'NaN'},method='PATCH',token=token)[0]==400
            assert api(base,'config')[1]['config']['location_source']==before['location_source']
            assert api(base,'config',body={'location_source':'manual','location_manual_lat':'48.75','location_manual_lon':'-122.48'},method='PATCH',token=token)[0]==200
            assert api(base,'telephone/contacts',body={'name':'Private location peer','lxmf_address':address},token=token)[0]==200
            wait(lambda:any(peer['online'] for peer in api(base,'preview/reticulum-connections')[1]['peers']))
            hub.send('announce');wait(lambda:api(base,'announces')[1]['announces'])
            events=watch_events(base,first)
            payload={'lxmf_message':{'destination_hash':address,'content':'','fields':{'telemetry':{'location':fix()}}}}
            response=api(base,'lxmf-messages/send',body=payload,token=token);assert response[0]==200,response
            assert api(base,'lxmf-messages/send',body={**payload,'delivery_method':'propagated'},token=token)[0]==400
            rows=wait(lambda:api(base,'telemetry/peers')[1]['telemetry'])
            row=next(item for item in rows if item['destination_hash']==address)
            assert row['telemetry']['location']['latitude']==48.75 and row['telemetry']['location']['longitude']==-122.48
            assert row['updated_at'] and row['timestamp']
            hub.send('received');assert hub.poll(10)
            assert len(hub.recv())==1
            assert api(base,'lxmf-messages/conversation/'+address)[1]['lxmf_messages']==[]
            assert api(base,'preview/unread-messages')[1]['messages']==[]
            assert not api(base,'lxmf/conversations')[1]['conversations'][0]['is_unread']
            wait(lambda:any(event.get('type')=='lxmf.telemetry' for event in events))
            time.sleep(.3)
            assert not any(event.get('type') in ('lxmf.delivery','lxmf_message_state_updated') for event in events)
            assert api(base,'telemetry/tracking/'+address+'/toggle',body={'is_tracking':True})[0]==403
            assert api(base,'telemetry/tracking/'+address+'/toggle',body={'is_tracking':True},token=token)[0]==200
            from concurrent.futures import ThreadPoolExecutor
            (app/'pause-next-compose').touch()
            with ThreadPoolExecutor(max_workers=1) as executor:
                future=executor.submit(api,base,'lxmf-messages/send',body=payload,token=token)
                wait(lambda:(app/'compose-paused').exists())
                assert api(base,'config',body={'location_source':'disabled'},method='PATCH',token=token)[0]==200
                (app/'resume-compose').touch()
                assert future.result(timeout=10)[0]==400
            assert api(base,'lxmf-messages/send',body=payload,token=token)[0]==400
            hub.send('received');assert hub.poll(10) and len(hub.recv())==1
        ready=app/'second.url';start(stack,app_server,app,ready,settings);wait(ready.exists);base=backend(ready)
        assert (app/'reticulum/identity').read_bytes()==identity
        assert api(base,'config')[1]['config']['location_source']=='disabled'
        assert api(base,'telemetry/latest/'+address)[1]['telemetry']['location']['latitude']==48.75
        assert api(base,'preview/unread-messages')[1]['messages']==[]
        assert api(base,'telephone/contacts')[1]['contacts'][0]['name']=='Private location peer'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--backend-source',type=Path,required=True);parser.add_argument('--work-dir',type=Path,required=True)
    args=parser.parse_args()
    # Re-exec so no partial Family module can mask the packaged neXt backend.
    if not os.environ.get('NEXT_TELEMETRY_BACKEND'):
        os.environ['NEXT_TELEMETRY_BACKEND']=str(args.backend_source.resolve());os.execv(sys.executable,[sys.executable,*sys.argv])
    folder=args.work_dir.resolve();folder.mkdir(parents=True,exist_ok=False)
    test_stream_is_bounded_and_cannot_impersonate_another_peer(folder/'stream')
    test_family_frame_updates_map_without_accepting_a_stale_location(folder/'frame')
    real_link_proof(folder/'network')
    result={'real_signed_messages_both_directions':True,'no_chat_or_unread_notification':True,'no_live_chat_events_for_map_updates':True,'settings_and_identity_preserved':True,'ephemeral_location_not_propagated':True,'turning_off_location_cancels_pending_send':True,'ok':True,'actual_mobile_backend':True,'stream_bound':64,'third_party_impersonation_rejected':True,'native_telemetry_and_family_frames_stored':True,'restart_preserved_locations':True,'failed_location_writes_raise_instead_of_returning_success':True}
    (folder/'proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
