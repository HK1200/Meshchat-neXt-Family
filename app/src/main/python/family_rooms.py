"""Companion policy adapter around the pinned neXt RRC client."""
import base64,contextlib,json,re,threading,time,types,functools
from pathlib import Path
import RNS
from meshchatnext.src.backend.rrc import protocol as proto
from meshchatnext.src.backend.rrc.manager import RRCHub,RRCManager

def serialized(function):
    @functools.wraps(function)
    def wrapped(self,*args,**kwargs):
        with self._operation_lock:return function(self,*args,**kwargs)
    return wrapped

class RoomKeys:
    def __init__(self,owner):self.owner=owner
    def _key(self,hub,dest,room):return json.dumps([hub,dest,room],separators=(',',':'))
    def upsert(self,hub,dest,room,nonce,ciphertext):
        with self.owner.lock:
            self.owner.state['room_keys'][self._key(hub,dest,room)]={'hub_hash':hub,'dest_name':dest,'room':room,'nonce':base64.b64encode(nonce).decode(),'ciphertext':base64.b64encode(ciphertext).decode(),'updated_at':time.time()};self.owner.save()
    def get(self,hub,dest,room):
        with self.owner.lock:row=self.owner.state['room_keys'].get(self._key(hub,dest,room))
        if not row:return None
        return dict(row,nonce=base64.b64decode(row['nonce']),ciphertext=base64.b64decode(row['ciphertext']))
    def list_for_hub(self,hub,dest):
        with self.owner.lock:return [dict(r) for r in self.owner.state['room_keys'].values() if r['hub_hash']==hub and r['dest_name']==dest]
    def delete(self,hub,dest,room):
        with self.owner.lock:
            old=self.owner.state['room_keys'].pop(self._key(hub,dest,room),None)
            if old:self.owner.save()
        return int(old is not None)
    def delete_for_hub(self,hub,dest):
        with self.owner.lock:
            keys=[k for k,r in self.owner.state['room_keys'].items() if r['hub_hash']==hub and r['dest_name']==dest]
            for k in keys:self.owner.state['room_keys'].pop(k)
            if keys:self.owner.save()
        return len(keys)

class FamilyHub(RRCHub):
    def connect(self,*args,**kwargs):
        interface=RNS.Transport.next_hop_interface(self.hub_hash)
        if RNS.Transport.has_path(self.hub_hash) and (interface is None or not interface.online or getattr(interface,'detached',False) or interface not in RNS.Transport.interfaces):
            RNS.Transport.expire_path(self.hub_hash)
        return super().connect(*args,**kwargs)
    def policy(self,room):return self.manager.owner.policy(self.hub_hash.hex(),room)
    def join_room(self,room,key=None,silent=False):
        if not self.policy(room):raise ValueError('This room is not approved')
        return super().join_room(room,key=key,silent=silent)
    def _handle_chat(self,env,kind):
        if self.policy(env.get(proto.K_ROOM)):return super()._handle_chat(env,kind)
    def _handle_joined(self,env):
        if self.policy(env.get(proto.K_ROOM)):return super()._handle_joined(env)
    def _handle_parted(self,env):
        room=env.get(proto.K_ROOM);body=env.get(proto.K_BODY)
        r=room.strip().lower() if isinstance(room,str) else None
        with self._lock:
            own=self._own_hash()
            # Membership notifications identify peers, not link sessions. A
            # delayed departure of our old link must not remove the current
            # joined session. Explicit PART confirmations and ERROR-based
            # kicks/bans still use the normal handlers.
            if r and self.policy(r) and r in self.rooms and r not in self._pending_parts and isinstance(body,list) and own in body:
                remaining=[peer for peer in body if peer!=own]
                if not remaining:return
                env=dict(env);env[proto.K_BODY]=remaining
        return super()._handle_parted(env)
    def _record_message(self,msg,local=False):
        if self.policy(msg.room):return super()._record_message(msg,local=local)
    def _record_system(self,room,text,event=None):
        if self.policy(room):return super()._record_system(room,text,event=event)
    def _record_notice(self,msg):
        if msg.room and not self.policy(msg.room):return
        return super()._record_notice(msg)
    def _send_env(self,env):
        kind=env.get(proto.K_T);room=env.get(proto.K_ROOM)
        if kind==proto.T_JOIN and not self.policy(room):raise ValueError('This room is not approved')
        if kind in (proto.T_MSG,proto.T_ACTION):
            body=env.get(proto.K_BODY)
            listing=room is None and body=='/list' and getattr(self,'allow_listing',False)
            if not listing:
                policy=self.policy(room)
                if not policy:raise ValueError('This room is not approved')
                if policy['readOnly']:raise ValueError('This room is read only')
                if isinstance(body,str) and body.lstrip().startswith('/'):raise ValueError('Chat commands are disabled in the family companion')
        return super()._send_env(env)

FamilyHub._PACKET_HANDLERS={**RRCHub._PACKET_HANDLERS,proto.T_JOINED:FamilyHub._handle_joined,proto.T_PARTED:FamilyHub._handle_parted}

class FamilyManager(RRCManager):
    def __init__(self,owner):
        self.owner=owner
        super().__init__(owner.identity,str(owner.root/'rrc'),get_nickname=lambda:'neXt Family',history_per_room_cap=200,database=types.SimpleNamespace(rrc_room_keys=RoomKeys(owner)))
    def save(self):pass # The authenticated canonical approval list is the source of truth.
    def add_hub(self,hub_hash,dest_name=None,name=None):
        with self._lock:
            hub=next((h for h in self.hubs if h.hub_hash==hub_hash),None)
            if hub:return hub
            hub=FamilyHub(self,hub_hash,dest_name=proto.DEFAULT_DEST_NAME,name=name);hub.auto_list=False;hub.auto_who=False;hub.auto_reconnect=False
            self.hubs.append(hub)
        return hub

class FamilyRooms:
    def __init__(self,root,identity,state,lock,save):
        self.root=Path(root);self.identity=identity;self.state=state;self.lock=lock;self.save=save
        with lock:
            state.setdefault('rooms',[]);state.setdefault('room_keys',{});state.setdefault('next_room_id',max([0]+[r['id'] for r in state['rooms']])+1);save()
        self._policies={};self._discovery={};self._announces={};self._online=False;self._transport_versions=None;self._recovery_after=0.;self._operation_lock=threading.RLock()
        self.manager=FamilyManager(self);self._sync()
        owner=self
        class Hubs:
            aspect_filter=proto.DEFAULT_DEST_NAME
            receive_path_responses=True
            def received_announce(self,destination_hash,announced_identity,app_data,announce_packet_hash=None):
                name='Reticulum Relay Chat hub'
                with contextlib.suppress(Exception):
                    data=proto.decode(app_data)
                    if isinstance(data,dict) and isinstance(data.get('hub'),str):name=data['hub'][:64]
                key=destination_hash.hex();owner._announces[key]={'hubHash':key,'name':name,'seen':time.time()}
                if len(owner._announces)>100:owner._announces.pop(min(owner._announces,key=lambda k:owner._announces[k]['seen']))
                hub=owner.manager.find_hub_by_hex(key)
                if hub:hub.note_hub_announce()
        RNS.Transport.register_announce_handler(Hubs())
    def policy(self,hub,room):
        if not isinstance(room,str):return None
        return self._policies.get((hub,room.strip().lower()))
    def _canonical(self):
        with self.lock:return [dict(r) for r in self.state['rooms'] if r.get('service','reticulum')=='reticulum']
    def _clear_pending(self,hub,channel):
        with hub._lock:
            for mid,(message,when) in list(hub._pending_delivery.items()):
                if message.room==channel:message.delivery='cancelled';hub._pending_delivery.pop(mid,None)
            hub._rejoin_retry_rooms.discard(channel)
    def _sync(self):
        with self._operation_lock:
            records=self._canonical();self._policies={(r['key'],r['channel']):r for r in records}
            for hub in list(self.manager.hubs):
                allowed={r['channel'] for r in records if r['key']==hub.hub_hash.hex()}
                for channel in list(hub.rooms):
                    if channel not in allowed:
                        self._clear_pending(hub,channel)
                        with hub._lock:hub._pending_joins.discard(channel);hub._silent_joins.discard(channel)
                        hub.part_room(channel)
                for channel in allowed:
                    if self.policy(hub.hub_hash.hex(),channel)['readOnly']:self._clear_pending(hub,channel)
                if not allowed and hub.hub_hash.hex() not in self._discovery:
                    if self.manager._active_hub is hub:self.manager.set_active(None,None)
                    self.manager.remove_hub(hub)
            for record in records:
                hub=self.manager.add_hub(bytes.fromhex(record['key']),name=record['name']);hub.auto_reconnect=True
                added=record['channel'] not in hub.rooms
                if added:hub.add_room(record['channel']);hub._load_history()
                if self._online:
                    if hub.status==RRCHub.STATUS_CONNECTED:
                        if record['channel'] not in hub._pending_joins and self.identity.hash not in hub.members.get(record['channel'],set()):
                            with contextlib.suppress(Exception):hub.join_room(record['channel'],key=self.manager.get_room_key(hub,record['channel']))
                    else:hub.connect()
    @serialized
    def retire_interface(self,interface):
        # Send encrypted link teardown while the old physical path can still
        # carry it. Detaching TCP first leaves orphaned server sessions.
        self._recovery_after=time.monotonic()+30.
        for hub in list(self.manager.hubs):
            if getattr(getattr(hub,'link',None),'attached_interface',None) is interface:
                hub.disconnect();RNS.Transport.expire_path(hub.hub_hash)

    @serialized
    def transport(self,online,versions=None):
        changed=False
        if versions is not None:
            previous=self._transport_versions;self._transport_versions=dict(versions)
            if previous is not None and online:
                # A newly usable path must also wake disconnected hubs. They
                # have no link to invalidate, and another radio may have kept
                # the aggregate online flag true throughout the outage.
                changed=any(value[0] and previous.get(key)!=value for key,value in versions.items())
                for hub in list(self.manager.hubs):
                    interface=getattr(getattr(hub,'link',None),'attached_interface',None)
                    if interface is not None and id(interface) in previous and previous[id(interface)]!=versions.get(id(interface)):
                        # Another interface may keep Reticulum online while
                        # this room's encrypted session has lost its TCP/BLE link.
                        hub.disconnect();RNS.Transport.expire_path(hub.hub_hash);changed=True
        if bool(online)==self._online and not changed:
            now=time.monotonic()
            if online and now>=self._recovery_after:
                # A retired attempt can leave an approved hub quietly idle.
                # Respect normal scheduled backoff, but recover idle sessions
                # without requiring the child to reopen the room.
                idle=any(hub.auto_reconnect and hub.status==RRCHub.STATUS_DISCONNECTED and not (getattr(hub,'_reconnect_timer',None) and hub._reconnect_timer.is_alive()) for hub in self.manager.hubs)
                if idle:
                    self._recovery_after=now+30.;self._sync()
            return
        self._online=bool(online)
        if not self._online:
            for hub in list(self.manager.hubs):hub.disconnect()
        else:
            self._recovery_after=time.monotonic()+30.;self._sync()
    def _record(self,room_id):
        record=next((r for r in self._canonical() if r['id']==room_id),None)
        if not record:raise ValueError('This room is not approved')
        return record
    @serialized
    def save_room(self,payload):
        raw=payload.get('room',{});name=str(raw.get('name','')).strip();key=str(raw.get('key','')).strip().lower();channel=str(raw.get('channel','')).strip().lstrip('#').lower();rid=raw.get('id')
        if payload.get('approved') is not True:raise ValueError('Confirm guardian room approval')
        if not name or len(name)>32:raise ValueError('Use a room name of 1–32 characters')
        if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Use a 32-character Reticulum hub hash')
        if not channel or len(channel.encode('utf8'))>64 or any(ord(c)<32 or ord(c)==127 for c in channel):raise ValueError('Use a room name of 1–64 UTF-8 bytes without control characters')
        password=payload.get('password','')
        if not isinstance(password,str) or len(password.encode('utf8'))>256:raise ValueError('Room password is too long')
        with self.lock:
            old=next((r for r in self.state['rooms'] if r['id']==rid),None)
            if rid is not None and (not old or old.get('service','reticulum')!='reticulum'):raise ValueError('Unknown room ID')
            if any(r['id']!=rid and r['key']==key and r['channel']==channel for r in self.state['rooms']):raise ValueError('This room is already approved')
            if not old and len(self.state['rooms'])>=32:raise ValueError('Room limit reached')
            if not old:
                rid=self.state['next_room_id'];self.state['next_room_id']+=1
            record={'id':rid,'name':name,'key':key,'channel':channel,'service':'reticulum','readOnly':bool(raw.get('readOnly',False))}
            if old:self.state['rooms']=[record if r['id']==rid else r for r in self.state['rooms']]
            else:self.state['rooms'].append(record)
            self.save()
        self._policies={(r['key'],r['channel']):r for r in self._canonical()}
        if old and (old['key'],old['channel'])!=(key,channel):self.manager.database.rrc_room_keys.delete(old['key'],proto.DEFAULT_DEST_NAME,old['channel'])
        hub=self.manager.add_hub(bytes.fromhex(key),name=name)
        if password:self.manager.remember_room_key(hub,channel,password)
        elif payload.get('clearPassword'):self.manager.forget_room_key(hub,channel)
        self._sync()
        if self._online and hub.status==RRCHub.STATUS_CONNECTED and channel not in hub._pending_joins and self.identity.hash not in hub.members.get(channel,set()):
            with contextlib.suppress(Exception):hub.join_room(channel,key=self.manager.get_room_key(hub,channel))
        return rid
    @serialized
    def remove(self,room_id):
        record=self._record(room_id)
        with self.lock:self.state['rooms']=[r for r in self.state['rooms'] if r['id']!=room_id];self.save()
        self._sync()
        self.manager.database.rrc_room_keys.delete(record['key'],proto.DEFAULT_DEST_NAME,record['channel'])
    @serialized
    def open(self,room_id):
        record=self._record(room_id)
        if not self._online:raise ValueError('Reticulum is disconnected')
        hub=self.manager.find_hub_by_hex(record['key']);self.manager.set_active(hub,record['channel'])
        if hub.status!=RRCHub.STATUS_CONNECTED:hub.connect()
        elif self.identity.hash not in hub.members.get(record['channel'],set()):
            with contextlib.suppress(Exception):hub.join_room(record['channel'],key=self.manager.get_room_key(hub,record['channel']))
    @serialized
    def post(self,room_id,text):
        record=self._record(room_id)
        if record['readOnly']:raise ValueError('This room is read only')
        if not self._online:raise ValueError('Reticulum is disconnected')
        if not isinstance(text,str) or not text.strip():raise ValueError('Enter a message')
        if text.lstrip().startswith('/'):raise ValueError('Chat commands are disabled in the family companion')
        hub=self.manager.find_hub_by_hex(record['key'])
        if not hub or hub.status!=RRCHub.STATUS_CONNECTED or self.identity.hash not in hub.members.get(record['channel'],set()):raise ValueError('Join the approved room before posting')
        return hub.send_message(record['channel'],text.strip()).hex()
    @serialized
    def retry(self,room_id,seq):
        record=self._record(room_id)
        if record['readOnly']:raise ValueError('This room is read only')
        if type(seq) is not int or seq<=0:raise ValueError('Choose a failed message')
        hub=self.manager.find_hub_by_hex(record['key'])
        if not self._online or not hub or hub.status!=RRCHub.STATUS_CONNECTED or self.identity.hash not in hub.members.get(record['channel'],set()):raise ValueError('Join the approved room before retrying')
        message=next((m for m in hub.get_messages(record['channel']) if m.seq==seq),None)
        if not message or message.src!=self.identity.hash or message.delivery!='failed':raise ValueError('Only your own failed messages can be retried')
        return hub.retry_message(record['channel'],seq).hex()
    @serialized
    def close_view(self):self.manager.set_active(None,None)
    @serialized
    def discover(self,hub_hash):
        if not re.fullmatch('[a-fA-F0-9]{32}',str(hub_hash)):raise ValueError('Use a 32-character hub hash')
        if not self._online:raise ValueError('Reticulum is disconnected')
        key=hub_hash.lower()
        if key not in self._discovery and len(self._discovery)>=4:raise ValueError('Close another discovery session first')
        self._discovery[key]=time.time()+120
        hub=self.manager.add_hub(bytes.fromhex(key),name=self._announces.get(key,{}).get('name'))
        hub.allow_listing=True
        def listing():
            if hub.status!=RRCHub.STATUS_CONNECTED:hub.connect()
            deadline=time.time()+50
            while time.time()<deadline:
                if key not in self._discovery:return
                if hub.status==RRCHub.STATUS_CONNECTED:
                    hub.request_room_list();return
                time.sleep(.3)
        threading.Thread(target=listing,daemon=True).start()
    @serialized
    def snapshot(self):
        for key,expiry in list(self._discovery.items()):
            if expiry<time.time():
                self._discovery.pop(key,None)
                hub=self.manager.find_hub_by_hex(key)
                if hub:
                    hub.allow_listing=False
                    if not any(r['key']==key for r in self._canonical()):self.manager.remove_hub(hub)
        records=self._canonical();runtime={}
        for record in records:
            hub=self.manager.find_hub_by_hex(record['key'])
            if not hub:continue
            data=hub.to_dict();rows,_=hub.room_messages(record['channel'],limit=200)
            error=next((m.text for m in reversed(hub.notices) if m.kind=='error' and m.room in [None,record['channel']]),None)
            runtime[str(record['id'])]={'connected':data['connected'],'joined':self.identity.hash in hub.members.get(record['channel'],set()),'status':data['status_text'],'linkTransport':str(getattr(getattr(hub,'link',None),'attached_interface',None)),'linkStatus':getattr(getattr(hub,'link',None),'status',None),'pathTransport':str(RNS.Transport.next_hop_interface(hub.hub_hash)),'pathKnown':RNS.Transport.has_path(hub.hub_hash),'identityKnown':RNS.Identity.recall(hub.hub_hash) is not None,'rttMs':data.get('rtt_ms'),'error':error,'maxMessageBytes':hub.max_msg_body_bytes,'unread':hub.unread_counts.get(record['channel'],0),'messages':[r for r in rows if r['kind'] in ['msg','action']]}
            record['hasPassword']=self.manager.has_stored_room_key(hub,record['channel'])
        discoveries=[]
        for key in list(self._discovery):
            hub=self.manager.find_hub_by_hex(key)
            if hub:
                data=hub.to_dict();discoveries.append({'hubHash':key,'name':data['display_name'],'connected':data['connected'],'status':data['status_text'],'rooms':[{'channel':name,'topic':topic,'hasPassword':name in data['available_keyed_rooms']} for name,topic in data['available_rooms'].items()]})
        return {'rooms':records,'roomRuntime':runtime,'rrcHubs':sorted(list(self._announces.values()),key=lambda a:a['seen'],reverse=True),'roomDiscovery':discoveries,'rrcIdentity':self.identity.hash.hex()}
