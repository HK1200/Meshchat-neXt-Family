"""First live Reticulum TCP/LXMF test backend; standalone app identity and state."""
import hashlib,hmac,json,os,re,secrets,threading,time,uuid,signal
_original_signal=signal.signal
def _android_signal(sig,handler):
    try:return _original_signal(sig,handler)
    except ValueError as e:
        if "main thread of the main interpreter" in str(e):return None
        raise
signal.signal=_android_signal
from pathlib import Path

DEFAULT_DEVICE_NAME='neXt Family'
ANNOUNCE_INTERVAL=60*60
TCP_ONLY_ACTIONS=frozenset({
    'setup','status','unlock','lock','password','contacts','peer',
    'device_name','preferences','qr_parse','discover_client','conversation_read','send',
    'mailbox_config','mailbox_sync','tcp_network_changed',
    'location_policy','location_start','location_stop','location_sample','location_suspend',
    'room_save','room_remove','room_open','room_close','room_post','room_retry','room_discover','room_name',
})
_tcp_only=False
_lock=threading.RLock()
_root=None
_state=None
_rns=None
_router=None
_rooms=None
_room_error=''
_destination=None
_peer=None
_tcp_generation=0
_radio=None
_locations=None
_maps=None
_meshcore=None
_voice=None
_voice_deferred=False
_network_context="unknown"
_tcp_network_context=""
_room_names=None
_location_outbound={}
_error='Starting Reticulum'
_connecting=False
_connect_pending=False
_auth_failures=[]
_sessions={}
_outbound={}
_pending_inbound=set()
_announces={}
_client_lookup={}
_announce_lock=threading.RLock()
_announced_sessions={}
_announce_failures={}
_last_announce_primary={}
_path_request_lock=threading.Lock()
_path_request_last={}
_mailbox_lock=threading.Lock()
_mailbox_tcp_session=None

def _save():
    p=_root/'state.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(_state));os.chmod(tmp,0o600);tmp.replace(p)

def initialize(folder,*,tcp_only=False):
    global _root,_state,_locations,_maps,_meshcore,_room_names,_tcp_only
    with _lock:
        if _root:return
        _tcp_only=tcp_only
        _root=Path(folder);_root.mkdir(parents=True,exist_ok=True)
        p=_root/'state.json'
        existing=p.exists()
        _state=json.loads(p.read_text()) if existing else {'contacts':[],'messages':[],'peer':{'host':'rmap.world','port':4242,'enabled':False}}
        _state.setdefault('setup_complete',existing)
        _state.setdefault('device_name',DEFAULT_DEVICE_NAME)
        _state.setdefault('preferences',{'announceEnabled':False,'searchEnabled':False,'roomAnnounceEnabled':False})
        if 'password_salt' not in _state:
            _state['password_salt']=secrets.token_hex(16)
            _state['password_hash']='' if not existing else _password(secrets.token_urlsafe(32))
            _save()
    from family_room_names import RoomNames
    _room_names=RoomNames(_state,_lock,_save)
    if not _tcp_only:
        from family_meshcore import FamilyMeshCore
        _meshcore=FamilyMeshCore(_state,_lock,_save)
        from family_maps import MapStore
        _maps=MapStore(_root,_state,_lock,_save)
    from family_location import FamilyLocation
    _locations=FamilyLocation(_state,_lock,_save,_cancel_location)
    if _meshcore:_meshcore.locations=_locations
    threading.Thread(target=_location_loop,daemon=True).start()
    if _state['setup_complete']:threading.Thread(target=_start,daemon=True).start()

def _cancel_location():
    for peer,message in list(_location_outbound.items()):
        if _router and message is not None and message.state not in [8,253,254,255]:_router.cancel_outbound(message.message_id)
    _location_outbound.clear()

def record_location(raw):
    if _locations:
        return _locations.record(json.loads(raw))
    from family_location import MOVING_SAMPLE_MS
    return MOVING_SAMPLE_MS

def location_error(error):
    if _locations:_locations.error=str(error)[:200]

def _location_loop():
    while True:
        try:
            if _locations:_locations.tick({'reticulum':_online(),'meshcore':bool(_meshcore and _meshcore.connected)},lambda peer,fix,generation:threading.Thread(target=_send_location,args=(peer,fix,generation),daemon=True).start())
        except Exception as exc:
            if _locations:_locations.error='Location update failed: '+str(exc)[:150]
        time.sleep(10)

def _send_location(peer,fix,generation):
    if peer.startswith('meshcore:'):
        if _meshcore:_meshcore.send_location(peer,fix,generation)
        return
    import RNS,LXMF
    from meshchatnext.src.backend.telemetry_utils import Telemeter
    try:
        address=bytes.fromhex(peer)
        if not _locations.can_send(peer,generation):return
        identity=_await_identity(address,lambda:_locations.can_send(peer,generation))
        if identity is None:return
        with _lock:
            if not _locations.can_send(peer,generation) or fix['last_update']<time.time()-120:return
            existing=_location_outbound.get(peer)
            if existing is not None and existing.state not in [8,253,254,255]:return
            destination=RNS.Destination(identity,RNS.Destination.OUT,RNS.Destination.SINGLE,'lxmf','delivery')
            message=LXMF.LXMessage(destination,_destination,'',fields={LXMF.FIELD_TELEMETRY:Telemeter.pack(location=fix)},desired_method=_delivery_method(address))
            _location_outbound[peer]=message;_router.handle_outbound(message)
    except Exception as exc:
        if _locations:_locations.error=str(exc)[:200]

def install_map(path,name,token):
    try:
        with _lock:_authorized({'token':token})
        return _install_map(path,name)
    except Exception as exc:return json.dumps({'ok':False,'error':str(exc)[:200]})

def install_catalog_map(path):
    return _install_map(path,'PNW and southern BC')

def _install_map(path,name):
    try:return json.dumps({'ok':True,'pack':_maps.install(path,name)})
    except Exception as exc:return json.dumps({'ok':False,'error':str(exc)[:200]})

def map_tile(key,z,x,y):return _maps.tile(key,z,x,y) if _maps else None

def map_source(z,x,y):return _maps.source(z,x,y) if _maps else ''

def _password(value):
    return hashlib.pbkdf2_hmac('sha256',value.encode(),bytes.fromhex(_state['password_salt']),200000).hex()

def _authorized(payload):
    if not _state.get('setup_complete'):raise ValueError('Finish guardian setup first.')
    token=payload.get('token','');now=time.time()
    if token not in _sessions or _sessions[token]<now:raise ValueError('Unlock guardian settings again.')

def _start():
    global _rns,_router,_destination,_error,_rooms,_room_error,_radio,_voice
    try:
        import RNS,LXMF
        folder=_root/'reticulum';folder.mkdir(exist_ok=True)
        (folder/'config').write_text('[reticulum]\nshare_instance = No\nenable_transport = No\n[interfaces]\n')
        _rns=RNS.Reticulum(configdir=str(folder),loglevel=2)
        identity_path=_root/'identity'
        identity=RNS.Identity.from_file(str(identity_path)) if identity_path.exists() else RNS.Identity()
        if not identity_path.exists():identity.to_file(str(identity_path));os.chmod(identity_path,0o600)
        _router=LXMF.LXMRouter(identity=identity,storagepath=str(_root/'lxmf'),autopeer=False,enforce_stamps=False)
        with _announce_lock,_lock:
            _destination=_router.register_delivery_identity(identity,display_name=_state['device_name'],stamp_cost=0)
        _router.register_delivery_callback(_receive)
        if not _tcp_only:
            _meshcore.identity=identity
            from family_voice import FamilyVoice
            _voice=FamilyVoice(identity,_state,_lock,_save,route_context=_voice_route_context,autostart=not _voice_deferred)
        try:
            from family_rooms import FamilyRooms
            _rooms=FamilyRooms(_root,identity,_state,_lock,_save)
        except Exception as exc:
            _room_error=str(exc)
            import traceback;traceback.print_exc()
        class Clients:
            aspect_filter='lxmf.delivery'
            receive_path_responses=True
            def received_announce(self,destination_hash,announced_identity,app_data,announce_packet_hash=None):
                _remember_client(destination_hash,app_data)
        RNS.Transport.register_announce_handler(Clients())
        with _lock:
            for m in _state['messages']:
                if not m.get('incoming') and not m['status'].startswith(('Delivered','Failed','Not sent','Not confirmed')):
                    m['status']='Interrupted · delivery not confirmed'
            _save()
        if not _tcp_only:
            from family_radios import Radio
            _radio=Radio(_rns,on_ready=_announce_available_routes,on_retire=lambda interface:_rooms.retire_interface(interface) if _rooms else None);_radio.configure(_state.get('rnode'))
        for contact in _state['contacts']:
            if contact.get('identityPublicKey'):RNS.Identity.remember(None,bytes.fromhex(contact['addresses']['lxmf']),bytes.fromhex(contact['identityPublicKey']))
        _error=''
        _connect()
    except Exception as e:
        _error=str(e)
        import traceback;traceback.print_exc()

def _connect():
    global _peer,_error,_connecting,_connect_pending,_tcp_generation
    with _lock:
        if _connecting:
            _connect_pending=True;return
        _connecting=True
    try:
        if not _rns:return
        import RNS
        from family_tcp import FamilyTCPInterface
        if _peer:
            if _rooms:_rooms.retire_interface(_peer)
            if _router:
                for cache in (_router.direct_links,_router.backchannel_links):
                    for address,link in cache.copy().items():
                        if (link.attached_interface is _peer or
                            (link.status==RNS.Link.PENDING and RNS.Transport.next_hop_interface(address) is _peer)):
                            link.teardown()
            _peer.detach()
            if _peer in RNS.Transport.interfaces:RNS.Transport.interfaces.remove(_peer)
            _peer=None
            _announce_available_routes()
        with _lock:peer=dict(_state['peer'])
        if peer['enabled']:
            interface=FamilyTCPInterface(RNS.Transport,{'name':'Family TCP','target_host':peer['host'],'target_port':peer['port'],'connect_timeout':8})
            _rns._add_interface(interface)
            with _lock:
                _tcp_generation+=1
                _peer=interface
            _error=''
            _announce_available_routes()
    except Exception as e:_error=str(e)
    finally:
        with _lock:
            _connecting=False
            pending=_connect_pending
            _connect_pending=False
        if pending:threading.Thread(target=_connect,daemon=True).start()

def _online():
    return bool((_peer and _peer.online) or (_radio and _radio.snapshot()['online']))

def _contact(peer):
    return next((c for c in _state['contacts'] if c.get('addresses',{}).get('lxmf','').lower()==peer),None)

def _receive(message):
    peer=message.source_hash.hex()
    with _lock:
        if not _contact(peer):return
    if not message.signature_validated:
        import LXMF
        if getattr(message,'unverified_reason',None)!=LXMF.LXMessage.SOURCE_UNKNOWN:return
        key=message.hash.hex()
        with _lock:
            if key in _pending_inbound or len(_pending_inbound)>=16:return
            _pending_inbound.add(key)
        def resolve():
            try:
                import RNS
                RNS.Transport.request_path(message.source_hash)
                deadline=time.time()+45
                while time.time()<deadline:
                    with _lock:
                        if not _contact(peer):return
                    if RNS.Identity.recall(message.source_hash):
                        verified=LXMF.LXMessage.unpack_from_bytes(message.packed)
                        if verified.signature_validated:_receive(verified)
                        return
                    time.sleep(.3)
            finally:
                with _lock:_pending_inbound.discard(key)
        threading.Thread(target=resolve,daemon=True).start()
        return
    with _lock:
        contact=_contact(peer)
        if not contact:return
        if _locations:
            import LXMF
            fields=getattr(message,'fields',{}) or {}
            if LXMF.FIELD_TELEMETRY in fields:_locations.receive(peer,fields[LXMF.FIELD_TELEMETRY])
        if not message.content_as_string().strip():return
        if any(m.get('hash')==message.hash.hex() for m in _state['messages']):return
        if _tcp_only and not contact.get('identityPublicKey'):
            contact['identityPublicKey']=message.source.identity.get_public_key().hex()
        _state['messages'].append({'id':uuid.uuid4().hex,'hash':message.hash.hex(),'peer':peer,'text':message.content_as_string()[:4096],'status':'Received · signature verified','incoming':True,'timestamp':time.time()})
        _state['messages']=_state['messages'][-500:];_save()

def _update(mid,status):
    with _lock:
        row=next((m for m in _state['messages'] if m['id']==mid),None)
        if row and row.get('service','reticulum')=='reticulum' and not row['status'].startswith('Delivered'):
            row['status']=status
            if status=='Delivered':row['deliveredAt']=time.time()
            _save()

def _usable_path(address):
    import RNS
    interface=RNS.Transport.next_hop_interface(address)
    usable=bool(interface and interface in RNS.Transport.interfaces and interface.online and not getattr(interface,'detached',False))
    if not usable and RNS.Transport.has_path(address):RNS.Transport.expire_path(address)
    return usable

def _await_identity(address,permitted,timeout=60):
    """Bounded, coalesced discovery survives a lost first radio request."""
    import RNS
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if not permitted():return None
        identity=RNS.Identity.recall(address)
        if _usable_path(address) and identity:return identity
        now=time.monotonic()
        with _path_request_lock:
            request=now-_path_request_last.get(address,float('-inf'))>=20
            if request:_path_request_last[address]=now
        if request:RNS.Transport.request_path(address)
        time.sleep(.3)
    return None

def _remember_client(destination_hash,app_data):
    import LXMF
    address=destination_hash.hex()
    if _destination and destination_hash==_destination.hash:return
    try:name=LXMF.display_name_from_app_data(app_data) or 'Unnamed messaging client'
    except Exception:name='Unnamed messaging client'
    with _lock:
        _announces[address]={'name':str(name)[:64],'service':'lxmf','address':address,'seen':time.time()}
        if len(_announces)>200:_announces.pop(min(_announces,key=lambda key:_announces[key]['seen']))

def _find_client(address,token):
    global _client_lookup
    import RNS
    destination=bytes.fromhex(address)
    def permitted():
        with _lock:return _sessions.get(token,0)>time.time()
    message='No client answered. Check the address and ask them to announce their Reticulum messaging identity.'
    client=None
    try:
        identity=_await_identity(destination,permitted,timeout=25)
        if identity and RNS.Destination.hash_from_name_and_identity('lxmf.delivery',identity)==destination:
            with _lock:
                if permitted():
                    _remember_client(destination,RNS.Identity.recall_app_data(destination))
                    client=dict(_announces[address])
                    message='Messaging client found. Review the address before approving it.'
        elif identity:
            message='This address belongs to a different Reticulum service.'
    except Exception:
        message='The Reticulum lookup failed. Check your connection and try again.'
    finally:
        with _lock:
            allowed=permitted()
            _client_lookup={'pending':False,'message':message if allowed else ''}
            if client and allowed:_client_lookup['client']=client

def _delivery_method(address):
    import RNS,LXMF
    interface=RNS.Transport.next_hop_interface(address)
    return LXMF.LXMessage.OPPORTUNISTIC if _radio and interface is _radio.interface else LXMF.LXMessage.DIRECT

def _dispatch_message(mid,service,peer,text,on_failure=None):
    if service=='reticulum':
        threading.Thread(target=_send,args=(mid,peer,text,on_failure),daemon=True).start()
    else:
        _meshcore.send(mid,peer,text,on_failure)

def _retry_message(mid,contact_id,service,peer,alternate,alternate_peer,status):
    """Switch a single conversation row to its other approved destination."""
    with _lock:
        row=next((m for m in _state['messages'] if m['id']==mid),None)
        contact=next((c for c in _state['contacts'] if c['id']==contact_id),None)
        if not row or not contact or row.get('service')!=service or row.get('peer')!=peer:
            return False
        if row['status'].startswith(('Delivered','Cancelled')):return False
        addresses=contact['addresses']
        current_key,alternate_key=('lxmf','meshcore') if service=='reticulum' else ('meshcore','lxmf')
        if addresses.get(current_key,'').lower()!=peer or addresses.get(alternate_key,'').lower()!=alternate_peer:
            return False
        if not any(route['service']==alternate for route in _message_routes(contact,row['text'])):
            return False
        text=row['text']
        row['fallbackFrom']={key:row[key] for key in ('service','peer','owner')}
        row['fallbackFrom']['status']=status
        row.update(service=alternate,peer=alternate_peer,
                   owner=(_state.get('meshcore') or {}).get('publicKey','') if alternate=='meshcore' else '',
                   status='Trying MeshCore' if alternate=='meshcore' else 'Trying Reticulum')
        row.pop('hash',None)
        _outbound.pop(mid,None)
        _save()
    _dispatch_message(mid,alternate,alternate_peer,text)
    return True

def _send(mid,peer,text,on_failure=None):
    send_started=False
    message=None
    def fail(status):
        if send_started:status='Not confirmed · Reticulum'
        if on_failure is None or not on_failure(status):
            _update(mid,status)
    try:
        import RNS,LXMF
        if not _online():raise ValueError('No Reticulum connection is online')
        def permitted():
            with _lock:return _contact(peer) is not None
        identity=_await_identity(bytes.fromhex(peer),permitted)
        if identity is None:
            if not permitted():raise ValueError('Contact approval was removed')
            raise ValueError('No path to contact after 60 seconds')
        dest=RNS.Destination(identity,RNS.Destination.OUT,RNS.Destination.SINGLE,'lxmf','delivery')
        class TrackedMessage(LXMF.LXMessage):
            def send(self):
                nonlocal send_started
                send_started=True
                return super().send()
        # On an RNode, short messages can avoid a multi-packet link handshake.
        message=TrackedMessage(dest,_destination,text,desired_method=_delivery_method(bytes.fromhex(peer)),include_ticket=True)
        message.register_delivery_callback(lambda m:_update(mid,'Delivered'))
        def failed(m):
            if m.state!=LXMF.LXMessage.CANCELLED:
                fail('Failed · Reticulum could not send')
        message.register_failed_callback(failed)
        # Recheck approval immediately before handing the packet to LXMF.
        with _lock:
            if not _contact(peer):raise ValueError('Contact approval was removed')
            row=next((m for m in _state['messages'] if m['id']==mid),None)
            if row is None:return
            _outbound[mid]=message
            row['status']='Sending'
            _router.handle_outbound(message)
            if row['service']=='reticulum':
                row['hash']=message.hash.hex() if message.hash else None
                _save()
    except Exception as e:
        # The router can report failure synchronously before raising.
        if message is None or message.state not in (LXMF.LXMessage.FAILED,LXMF.LXMessage.REJECTED,LXMF.LXMessage.CANCELLED):
            fail('Failed · '+str(e))

def _message_routes(contact,text=None):
    from family_routes import choices
    return choices(contact,_state['messages'],{
        'reticulum':_online(),
        'meshcore':bool(_meshcore and _meshcore.connected),
    },owner=(_state.get('meshcore') or {}).get('publicKey',''),text=text)

def _room_transport_versions():
    versions={}
    if _peer:versions[id(_peer)]=(bool(_peer.online),getattr(_peer,'family_connection_epoch',0))
    radio=getattr(_radio,'interface',None) if _radio else None
    if radio:versions[id(radio)]=(bool(radio.online),getattr(getattr(radio,'ble',None),'connected_time',None))
    return versions

def _announce_available_routes():
    """Advertise each enabled service at startup, on route changes, and hourly."""
    if _destination is None:return
    import RNS
    with _announce_lock:
        versions=_room_transport_versions();radio=getattr(_radio,'interface',None)
        with _lock:
            peer_enabled=bool(_state['peer'].get('enabled'))
            radio_enabled=bool((_state.get('rnode') or {}).get('enabled'))
            voice=_voice.phone if _voice and _state.get('voiceEnabled') and not _voice_deferred else None
        candidates=(_peer if peer_enabled else None,radio if radio_enabled and _radio and _radio.snapshot()['online'] else None)
        interfaces=[interface for interface in candidates if interface is not None and interface.online and not getattr(interface,'detached',False) and interface in RNS.Transport.interfaces and id(interface) in versions]
        services=[('text',_destination)]
        if voice:services.append(('voice',voice))
        else:_last_announce_primary.pop('voice',None)
        live={(service,id(interface)) for service,_ in services for interface in interfaces}
        for key in (_announced_sessions.keys()|_announce_failures.keys())-live:
            _announced_sessions.pop(key,None);_announce_failures.pop(key,None)
        if not interfaces:
            _last_announce_primary.clear()
            return
        primary=id(interfaces[0])
        now=time.monotonic()
        for service,endpoint in services:
            for interface in interfaces:
                route=id(interface)
                key=(service,route)
                name=_state.get('device_name',DEFAULT_DEVICE_NAME)
                version=(versions[route],endpoint,name)
                primary_session=(route,version)
                preferred=route==primary and _last_announce_primary.get(service)!=primary_session
                previous=_announced_sessions.get(key)
                if previous and previous[0]==version and now-previous[1]<ANNOUNCE_INTERVAL and not preferred:continue
                if now-_announce_failures.get(key,float('-inf'))<10:continue
                try:
                    with _lock:
                        if service=='voice' and (_voice_deferred or not _state.get('voiceEnabled') or _voice.phone is not endpoint):continue
                        endpoint.announce(attached_interface=interface)
                    _announced_sessions[key]=(version,now);_announce_failures.pop(key,None)
                    if route==primary:_last_announce_primary[service]=primary_session
                except Exception:_announce_failures[key]=now

def _conversation_messages(contact):
    """Project approved direct rows while the caller holds the state lock."""
    peer=contact['addresses'].get('lxmf','').lower()
    mesh_peer=contact['addresses'].get('meshcore','').lower()
    owner=(_state.get('meshcore') or {}).get('publicKey','')
    return [dict(m,pending=False) for m in _state['messages'] if (m.get('service','reticulum')=='reticulum' and m['peer']==peer) or (m.get('service')=='meshcore' and m['peer']==mesh_peer and m.get('owner')==owner)]


def _mailbox_snapshot():
    address=_state.get('mailbox','')
    if not address:return {'address':'','status':'disabled'}
    if not _router:return {'address':address,'status':'waiting'}
    phase=_router.propagation_transfer_state
    if phase==_router.PR_COMPLETE:status='complete'
    elif _router.PR_IDLE<phase<_router.PR_COMPLETE:status='syncing'
    elif phase>_router.PR_COMPLETE:status='failed'
    else:status='waiting'
    return {'address':address,'status':status}

def _configure_mailbox(payload):
    _authorized(payload)
    address=payload.get('address','')
    if not isinstance(address,str) or (address and not re.fullmatch('[0-9a-fA-F]{32}',address)):
        raise ValueError('Enter a 32-character LXMF propagation node address.')
    address=address.lower()
    with _mailbox_lock:
        if address==_state.get('mailbox',''):return
        if _router:_router.cancel_propagation_node_requests()
        with _lock:
            previous=_state.get('mailbox','')
            _state['mailbox']=address
            try:_save()
            except OSError:
                _state['mailbox']=previous
                raise

def _tcp_session():
    with _lock:
        return f'{_tcp_generation}:{_peer.family_connection_epoch}' if _peer and _peer.online else None

def _sync_mailbox():
    global _mailbox_tcp_session
    with _mailbox_lock:
        address=_state.get('mailbox','')
        session=_tcp_session()
        if not address or not _router or not _destination or session is None:return _mailbox_snapshot()
        if session!=_mailbox_tcp_session:
            _router.cancel_propagation_node_requests()
            _mailbox_tcp_session=session
        phase=_router.propagation_transfer_state
        if _router.PR_IDLE<phase<_router.PR_COMPLETE:return _mailbox_snapshot()
        _router.set_outbound_propagation_node(bytes.fromhex(address))
        _router.request_messages_from_propagation_node(_destination.identity,max_messages=50)
        return _mailbox_snapshot()

def _snapshot():
    import RNS
    _announce_available_routes()
    room_data={'rooms':[],'roomRuntime':{},'rrcHubs':[],'roomDiscovery':[],'roomError':_room_error}
    if _rooms:
        try:
            _rooms.transport(_online(),_room_transport_versions());room_data.update(_rooms.snapshot())
        except Exception as exc:room_data['roomError']=str(exc)
    with _lock:
        for mid,message in list(_outbound.items()):
            if message.state==4:_update(mid,'Sent · awaiting delivery proof')
        result={'messagingEnabled':bool(_state['peer'].get('enabled') or (_state.get('rnode') or {}).get('enabled') or (_state.get('meshcore') or {}).get('enabled')),'setupComplete':bool(_state.get('setup_complete')),'ready':_destination is not None,'online':_online(),'connecting':_connecting,'error':_error,'address':_destination.hash.hex() if _destination else '', 'peer':dict(_state['peer']),'contacts':_state['contacts'],'announces':sorted(_announces.values(),key=lambda a:a['seen'],reverse=True),'messages':{}}
        for c in _state['contacts']:
            result['messages'][str(c['id'])]=_conversation_messages(c)
        from family_radios import public
        result['rnode']=public(_state.get('rnode'))
        result['rnodeRuntime']=_radio.snapshot() if _radio else {'online':False,'connecting':False,'error':''}
        result['messageRoutes']={str(c['id']):_message_routes(c) for c in _state['contacts']}
        result['tcpOnline']=bool(_peer and _peer.online)
        if _tcp_only:
            result['mailbox']=_mailbox_snapshot()
            result['tcpSession']=_tcp_session()
        result['voice']=_voice.snapshot() if _voice else {'enabled':bool(_state.get('voiceEnabled',False)),'ready':False,'call_state':'idle'}
        result['meshcore']=_meshcore.snapshot() if _meshcore else {}
        if _meshcore:result['announces']+=result['meshcore']['clientAnnounces']
        result['activeMap']=_state.get('active_map','pnw')
        result['mapPacks']=_maps.snapshot() if _maps else []
        result['location']=_locations.snapshot() if _locations else {}
        if _meshcore:result['location']['meshcoreStatus']=_meshcore.location_status
        result['preferences']=dict(_state.get('preferences',{}))
        result['deviceName']=_state.get('device_name',DEFAULT_DEVICE_NAME)
        result['clientLookup']=dict(_client_lookup)
        if _meshcore:
            mc_rooms=_meshcore.rooms.snapshot();room_data['rooms']+=mc_rooms['rooms'];room_data['roomRuntime'].update(mc_rooms['roomRuntime'])
        if _room_names:room_data=_room_names.decorate(room_data)
        result.update(room_data)
        return result

def background(lock_guardian=True):
    if lock_guardian:_sessions.clear()
    if _rooms:_rooms.close_view()
    if _meshcore:_meshcore.rooms.close_view()

def request(raw):
    global _client_lookup
    try:
        if len(raw)>1500000:raise ValueError('Request is too large')
        data=json.loads(raw);action=data.get('action');p=data.get('payload',{})
        if _tcp_only and action not in TCP_ONLY_ACTIONS:
            raise ValueError('This build supports Reticulum TCP messaging only.')
        if action=='setup':
            with _lock:
                if _state.get('setup_complete'):raise ValueError('Guardian setup is already complete')
                password=p.get('password');confirmation=p.get('confirmation');enabled=p.get('reticulumEnabled')
                if not isinstance(password,str) or not 8<=len(password)<=128:raise ValueError('Use a password of 8–128 characters.')
                if password!=confirmation:raise ValueError('The passwords do not match.')
                if type(enabled) is not bool:raise ValueError('Choose whether to enable Reticulum TCP.')
                _state['password_salt']=secrets.token_hex(16);_state['password_hash']=_password(password);_state['password_changed']=True;_state['setup_complete']=True;_state['peer']['enabled']=enabled;_save()
            threading.Thread(target=_start,daemon=True).start()
            return json.dumps({'ok':True,**_snapshot()})
        if action=='radio_batteries':
            if _meshcore and _state.get('setup_complete'):
                _meshcore.request_battery()
            return json.dumps({'ok': True})
        if action=='runtime_diagnostics':
            _authorized(p)
            import sys,traceback
            # Frame locations only: never capture locals, source lines or keys.
            threads=[]
            for frame in list(sys._current_frames().values())[:128]:
                threads.append([{'file':Path(item.filename).name,'function':item.name,'line':item.lineno} for item in traceback.extract_stack(frame,limit=12)])
            hubs=[]
            if _rooms:
                for hub in list(_rooms.manager.hubs):
                    timer=getattr(hub,'_reconnect_timer',None)
                    hubs.append({'hubHash':hub.hub_hash.hex(),'status':hub.status,'autoReconnect':hub.auto_reconnect,'manualDisconnect':hub._manual_disconnect,'connectEpoch':getattr(hub,'_connect_epoch',0),'reconnectAttempts':hub._reconnect_attempts,'reconnectScheduled':bool(timer and timer.is_alive())})
            return json.dumps({'ok':True,'threads':threads,'hubs':hubs})
        if action=='tcp_network_changed':
            if not _tcp_only:raise ValueError('iOS network status is only available in the TCP build')
            with _lock:reconnect=bool(_rns and _state['peer'].get('enabled'))
            if reconnect:threading.Thread(target=_connect,daemon=True).start()
            return json.dumps({'ok':True})
        if action in ['mailbox_config','mailbox_sync']:
            if not _tcp_only:raise ValueError('Mailbox sync is only available in the TCP build')
            if action=='mailbox_sync':return json.dumps({'ok':True,'mailbox':_sync_mailbox()})
            _configure_mailbox(p)
            return json.dumps({'ok':True,**_snapshot()})
        if action=='unlock':
            if not _state.get('setup_complete'):raise ValueError('Finish guardian setup first.')
            now=time.time();_auth_failures[:]=[t for t in _auth_failures if now-t<60]
            if len(_auth_failures)>=5:raise ValueError('Too many attempts. Wait a minute.')
            if not hmac.compare_digest(_password(str(p.get('password',''))),_state['password_hash']):
                _auth_failures.append(now);raise ValueError('Incorrect guardian password')
            _auth_failures.clear()
            token=secrets.token_urlsafe(32);_sessions[token]=time.time()+900;return json.dumps({'ok':True,'token':token})
        if action=='lock':_sessions.pop(p.get('token',''),None);return json.dumps({'ok':True})
        if isinstance(action,str) and action.startswith('room_'):
            if action in ['room_save','room_remove','room_discover','room_name']:_authorized(p)
            if action=='room_name':
                _room_names.set(p.get('roomId'),p.get('participantId'),p.get('name'))
            elif action=='room_close':
                if _rooms:_rooms.close_view()
                if _meshcore:_meshcore.rooms.close_view()
            elif action=='room_discover':
                if p.get('service')=='meshcore':
                    if not _meshcore:raise ValueError('MeshCore is starting')
                    _meshcore.refresh_contacts()
                else:
                    if not _rooms:raise ValueError(_room_error or 'Room service is starting')
                    _rooms.discover(p.get('hubHash'))
            else:
                old=next((r for r in _state.get('rooms',[]) if r['id']==(p.get('room',{}).get('id') if action=='room_save' else p.get('roomId'))),None)
                service=p.get('room',{}).get('service','reticulum') if action=='room_save' else old.get('service','reticulum') if old else 'reticulum'
                if service not in ['reticulum','meshcore']:raise ValueError('Unsupported room service')
                if old and old.get('service','reticulum')!=service:raise ValueError('Remove this approval before changing room service')
                adapter=_meshcore.rooms if service=='meshcore' and _meshcore else _rooms if service=='reticulum' else None
                if not adapter:raise ValueError('Room service is starting')
                if action=='room_save':adapter.save_room(p)
                elif action=='room_remove':adapter.remove(p.get('roomId'))
                elif action=='room_open':
                    if service=='meshcore' and _rooms:_rooms.close_view()
                    elif service=='reticulum' and _meshcore:_meshcore.rooms.close_view()
                    adapter.open(p.get('roomId'))
                elif action=='room_post':adapter.post(p.get('roomId'),p.get('text'))
                elif action=='room_retry':
                    if service!='reticulum':raise ValueError('Only Relay Chat messages support this retry')
                    adapter.retry(p.get('roomId'),p.get('seq'))
                else:raise ValueError('Unsupported room action')
        elif action in ['meshcore_config','meshcore_scan','meshcore_contacts']:
            _authorized(p)
            if not _meshcore:raise ValueError('MeshCore is starting')
            if action=='meshcore_config':_meshcore.configure(p.get('config'))
            elif action=='meshcore_scan':_meshcore.scan()
            else:_meshcore.refresh_contacts()
        elif action=='authorize_map_import':
            _authorized(p)
            return json.dumps({'ok':True})
        elif action=='map_remove':
            _authorized(p)
            if not _maps:raise ValueError('Map service is starting')
            _maps.remove(p.get('mapId'))
        elif _tcp_only and action in ['location_sample','location_suspend']:
            if action=='location_sample':
                _locations.record(p.get('fix'))
            else:
                _locations.suspend_samples()
            return json.dumps({'ok':True})
        elif action in ['location_policy','location_start','location_stop','authorize_location']:
            if not _locations:raise ValueError('Location service is starting')
            guardian=False
            try:_authorized(p);guardian=True
            except ValueError:pass
            if action=='location_policy':
                _authorized(p);_locations.configure(p)
            elif action=='authorize_location':
                if not _locations.permissions(guardian):raise ValueError('Location sharing is managed by your guardian')
            elif action=='location_start':_locations.start(str(p.get('duration','15')),guardian)
            elif action=='location_stop':
                if not _locations.permissions(guardian):raise ValueError('Location sharing is managed by your guardian')
                _locations.stop()
        elif action in ['authorize_update_config','authorize_apk_share']:
            _authorized(p)
            return json.dumps({'ok': True})
        elif action=='authorize_camera':
            _authorized(p)
        elif action=='qr_parse':
            _authorized(p)
            from family_cards import parse
            return json.dumps({'ok':True,'card':parse(p.get('text'),p.get('target','contact'))})
        elif action=='device_name':
            name=p.get('name')
            with _announce_lock,_lock:
                _authorized(p)
                if not isinstance(name,str) or not 1<=len(name.strip())<=32 or not name.strip().isprintable():
                    raise ValueError('Enter a device name of 1–32 printable characters.')
                name=name.strip()
                previous=_state['device_name']
                if name!=previous:
                    _state['device_name']=name
                    try:_save()
                    except OSError:
                        _state['device_name']=previous
                        raise
                    if _destination is not None:_destination.display_name=name
        elif action=='preferences':
            _authorized(p)
            values=p.get('values',{})
            if not isinstance(values,dict) or any(k not in ['announceEnabled','searchEnabled','roomAnnounceEnabled'] or not isinstance(v,bool) for k,v in values.items()):raise ValueError('Invalid discovery preferences')
            with _lock:_state['preferences'].update(values);_save()
        elif action=='discover_client':
            _authorized(p)
            address=p.get('address','')
            if not isinstance(address,str) or not re.fullmatch('[0-9a-fA-F]{32}',address):
                raise ValueError('Enter a 32-character LXMF address.')
            address=address.lower()
            if not _online():raise ValueError('Connect Reticulum before looking up a client.')
            if _destination and address==_destination.hash.hex():raise ValueError('This is Family’s own address.')
            with _lock:
                if _client_lookup.get('pending'):raise ValueError('A client lookup is already running.')
                _client_lookup={'pending':True,'message':'Looking for this messaging client…'}
            threading.Thread(target=_find_client,args=(address,p['token']),daemon=True).start()
            return json.dumps({'ok':True})
        elif action=='discover':
            _authorized(p)
            if not _rns:raise ValueError('Reticulum is still starting')
            import RNS
            for c in _state['contacts']:
                address=c.get('addresses',{}).get('lxmf','')
                if address:RNS.Transport.request_path(bytes.fromhex(address))
        elif action=='password':
            _authorized(p);value=p.get('password','')
            if not isinstance(value,str) or not 8<=len(value)<=128:raise ValueError('Use a password of 8–128 characters.')
            with _lock:
                _state['password_salt']=secrets.token_hex(16);_state['password_hash']=_password(value);_state['password_changed']=True;_save()
            keep=p['token'];_sessions.clear();_sessions[keep]=time.time()+900
        elif action=='contacts':
            _authorized(p);contacts=p.get('contacts');seen=set();voice_seen=set();ids=set()
            if not isinstance(contacts,list) or len(contacts)>100:raise ValueError('Invalid contact list')
            for c in contacts:
                if not isinstance(c.get('id'),int) or c['id'] in ids:raise ValueError('Invalid contact ID')
                ids.add(c['id'])
                address=c.get('addresses',{}).get('lxmf','').lower()
                if address and (not re.fullmatch('[a-f0-9]{32}',address) or address in seen):raise ValueError('Invalid or duplicate LXMF address')
                if address:seen.add(address)
                voice_address=c.get('addresses',{}).get('lxst','').lower()
                if voice_address and (not re.fullmatch('[a-f0-9]{32}',voice_address) or voice_address in voice_seen):raise ValueError('Invalid or duplicate Reticulum voice address')
                if voice_address:voice_seen.add(voice_address)
                mesh_address=c.get('addresses',{}).get('meshcore','')
                if mesh_address and (not re.fullmatch('[a-f0-9]{64}',mesh_address) or mesh_address in seen):raise ValueError('Invalid or duplicate full MeshCore public key')
                if mesh_address:seen.add(mesh_address)
                if c.get('identityPublicKey'):
                    from family_cards import validate_public_key
                    validate_public_key(address,c['identityPublicKey'])
                if not isinstance(c.get('name'),str) or not c['name'].strip() or len(c['name'])>32:raise ValueError('Invalid contact name')
            with _lock:
                if _tcp_only:
                    known_keys={c['addresses'].get('lxmf','').lower():c['identityPublicKey']
                                for c in _state['contacts'] if c.get('identityPublicKey')}
                    for contact in contacts:
                        address=contact['addresses'].get('lxmf','').lower()
                        if address in known_keys and not contact.get('identityPublicKey'):
                            contact['identityPublicKey']=known_keys[address]
                _state['contacts']=contacts
                if _locations:_locations.reconcile()
                if _voice:_voice.reconcile()
                import RNS
                for contact in contacts:
                    if contact.get('identityPublicKey'):RNS.Identity.remember(None,bytes.fromhex(contact['addresses']['lxmf']),bytes.fromhex(contact['identityPublicKey']))
                for mid,message in list(_outbound.items()):
                    row=next((m for m in _state['messages'] if m['id']==mid),None)
                    if row and not _contact(row['peer']) and message.state not in [8,253,254,255]:
                        if _router:_router.cancel_outbound(message.message_id)
                        row['status']='Cancelled · contact approval removed'
                _save()
        elif action in ['bluetooth_scan','bluetooth_devices','bluetooth_pair']:
            _authorized(p)
            from family_radios import bluetooth
            address=p.get('address','')
            if action=='bluetooth_pair' and not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',address):raise ValueError('Invalid Bluetooth address')
            value=bluetooth({'bluetooth_scan':'scan','bluetooth_devices':'devices','bluetooth_pair':'pair'}[action],address)
            return json.dumps({'ok':True,'devices':value} if isinstance(value,list) else {'ok':True,'pairing':value})
        elif action=='usb_devices':
            _authorized(p)
            from family_radios import usb_devices
            return json.dumps({'ok':True,'devices':usb_devices()})
        elif action=='rnode':
            _authorized(p)
            from family_radios import validate
            config=validate(p.get('config')) if p.get('config') is not None else None
            with _lock:_state['rnode']=config;_save()
            if _radio:_radio.configure(config)
        elif action=='peer':
            _authorized(p);host=str(p.get('host','')).strip();port=int(p.get('port',0))
            if not re.fullmatch('[A-Za-z0-9.-]{1,253}',host) or not 1<=port<=65535:raise ValueError('Invalid TCP host or port')
            with _lock:_state['peer']={'host':host,'port':port,'enabled':bool(p.get('enabled',True))};_save()
            threading.Thread(target=_connect,daemon=True).start()
        elif action=='voice_resolve':
            _authorized(p)
            import RNS
            contact=next((c for c in _state['contacts'] if c['id']==p.get('contactId')),None)
            if not contact or not contact.get('addresses',{}).get('lxmf'):raise ValueError('Select an approved LXMF contact')
            identity=RNS.Identity.recall(bytes.fromhex(contact['addresses']['lxmf']))
            if not identity:raise ValueError('Receive a signed message or discover this contact first')
            return json.dumps({'ok':True,'address':RNS.Destination.hash_from_name_and_identity('lxst.telephony',identity).hex()})
        elif action in ['voice_config','voice_call','voice_answer','voice_hangup','voice_mute']:
            if not _voice:raise ValueError('Reticulum is still starting')
            if action=='voice_config':_authorized(p);_voice.configure(p.get('enabled'))
            elif action=='voice_call':_voice.call(p.get('contactId'),automatic=p.get('automatic') is True)
            elif action=='voice_answer':_voice.answer(p.get('callId'))
            elif action=='voice_hangup':_voice.hangup(p.get('callId'))
            elif action=='voice_mute':
                if type(p.get('muted')) is not bool:raise ValueError('Invalid mute setting')
                _voice.set_muted(p['muted'])
        elif action=='conversation_read':
            with _lock:
                contact=next((c for c in _state['contacts'] if c['id']==p.get('contactId')),None)
                if contact is None:raise ValueError('Contact is not approved')
                # Never enter room/status locks while holding the state lock.
                # Background room snapshots acquire those locks in reverse order.
                visible=_conversation_messages(contact)
                requested=p.get('messageIds',[])
                if not isinstance(requested,list) or len(requested)>500:raise ValueError('Invalid message selection')
                allowed={m['id'] for m in visible if m.get('incoming') and m['id'] in requested}
                for row in _state['messages']:
                    if row['id'] in allowed:row['read']=True
                _save()
        elif action=='send':
            with _lock:
                c=next((c for c in _state['contacts'] if c['id']==p.get('contactId')),None)
                if not c:raise ValueError('Contact is not approved')
                method=p.get('method','auto')
                automatic=method=='auto'
                if method not in ['auto','reticulum','meshcore']:raise ValueError('Unsupported message method')
                reticulum=bool(c['addresses'].get('lxmf') and _online())
                meshcore=bool(c['addresses'].get('meshcore') and _meshcore and _meshcore.connected)
                if automatic:
                    options=_message_routes(c,str(p.get('text','')).strip())
                    method=options[0]['service'] if options else 'auto'
                if method=='reticulum' and not reticulum:raise ValueError('Reticulum is not connected or not approved for this contact')
                if method=='meshcore' and not meshcore:raise ValueError('MeshCore is not connected or not approved for this contact')
                if method=='auto':raise ValueError('Messaging is not connected for this contact')
                text=str(p.get('text','')).strip()
                if not text or len(text)>4096:raise ValueError('Message must contain 1–4096 characters')
                if method=='meshcore' and len(text.encode())>160:raise ValueError('MeshCore messages support at most 160 UTF-8 bytes')
                mid=uuid.uuid4().hex;peer=c['addresses']['lxmf' if method=='reticulum' else 'meshcore'].lower()
                owner=(_state.get('meshcore') or {}).get('publicKey','') if method=='meshcore' else ''
                _state['messages']=_state['messages'][-499:]
                _state['messages'].append({'id':mid,'peer':peer,'owner':owner,'service':method,'text':text,'incoming':False,'status':'Finding path' if method=='reticulum' else 'Sending to MeshCore companion','timestamp':time.time()});_save()
                alternate,alternate_key=('meshcore','meshcore') if method=='reticulum' else ('reticulum','lxmf')
                alternate_peer=c['addresses'].get(alternate_key,'').lower()
                on_failure=None
                if automatic and alternate_peer and (alternate!='meshcore' or len(text.encode())<=160):
                    def on_failure(status):
                        return _retry_message(mid,c['id'],method,peer,alternate,alternate_peer,status)
            _dispatch_message(mid,method,peer,text,on_failure)
        elif action not in ['status','contacts','peer','password','discover']:raise ValueError('Unsupported action')
        return json.dumps({'ok':True,**_snapshot()})
    except Exception as e:return json.dumps({'ok':False,'error':str(e)})

# Native audio bridge only: these are never exposed as Javascript request actions.
def voice_state():return json.dumps(_voice.snapshot() if _voice else {'enabled':bool((_state or {}).get('voiceEnabled',False)),'ready':False,'call_state':'idle'})
def voice_push(call_id,data):
    if _voice:_voice.push(call_id,data)
def voice_pull(call_id):return _voice.pull(call_id) if _voice else b''
def voice_audio_error(detail):
    if _voice:_voice.error=str(detail)[:160];_voice.hangup()

# Called by the native host with its own SIP snapshot, never from request payloads.
def _voice_route_context(address):
    import RNS
    interface=RNS.Transport.next_hop_interface(bytes.fromhex(address))
    radio=getattr(_radio,'interface',None)
    if (radio is not None and interface is radio) or (not (_peer and _peer.online) and radio and radio.online):
        c=_state.get('rnode') or {}
        return 'radio:'+':'.join(str(c.get(k,'')) for k in ['endpoint','frequency','bandwidth','sf','cr'])
    p=_state['peer'];return 'tcp:'+p['host']+':'+str(p['port'])+':'+_network_context

def call_routes(sip_json):
    from family_call_quality import rank
    sip=json.loads(sip_json);results={}
    with _lock:
        contacts=list(_state['contacts']);history=list(_state.get('callQuality',[]))
    for contact in contacts:
        address=contact.get('addresses',{}).get('lxst','')
        context=_voice_route_context(address) if address else ''
        radio=context.startswith('radio:')
        reticulum={'available':bool(_voice and _voice.snapshot()['ready'] and _state.get('voiceEnabled') and _online()),'automatic':not radio,'context':context,'reason':'Radio link is too slow for this voice profile'}
        account=next((a for a in sip.get('accounts',[]) if a.get('id')==sip.get('selected')), {})
        sip_context=sip.get('quality_context','unknown')
        sr={'available':bool(sip.get('enabled') and sip.get('registered')),'context':sip_context}
        results[str(contact['id'])]=rank(contact,sr,reticulum,history+sip.get('route_quality',[]))
    return json.dumps(results)

def approved_call_target(contact_id,method):
    with _lock:
        contact=next((c for c in _state['contacts'] if c['id']==contact_id),None)
        if not contact or method not in ['sip','reticulum']:raise ValueError('Call contact is not approved')
        address=contact.get('addresses',{}).get('sip' if method=='sip' else 'lxst','')
        if not address:raise ValueError('Call method is not approved')
        return address

def set_voice_deferred(deferred):
    global _voice_deferred
    previous=_voice_deferred;_voice_deferred=bool(deferred)
    if previous and not _voice_deferred and _voice and _state.get('voiceEnabled'):
        threading.Thread(target=_voice._ensure,daemon=True).start()

def set_network_context(context):
    global _network_context,_tcp_network_context
    context=str(context)[:128]
    with _lock:
        _network_context=context
        if not context.partition(':')[0].isdigit() or context==_tcp_network_context:return
        reconnect=bool(_tcp_network_context and _state and _state['peer'].get('enabled') and _rns)
        _tcp_network_context=context
    if reconnect:threading.Thread(target=_connect,daemon=True).start()
