"""Opt-in MeshCore companion and approved direct messaging, separate from RNS."""
import asyncio,concurrent.futures,hashlib,math,re,threading,time,uuid

def key(value):
    if not isinstance(value,str) or not re.fullmatch('[a-fA-F0-9]{64}',value):raise ValueError('Use a full 64-character MeshCore public key')
    return value.lower()

def validate_config(raw):
    if not isinstance(raw,dict) or type(raw.get('enabled')) is not bool or type(raw.get('receive',False)) is not bool:raise ValueError('Invalid MeshCore settings')
    kind=raw.get('transport');target=str(raw.get('target','')).strip()
    if kind=='ble':
        if not re.fullmatch(r'(?:[a-fA-F0-9]{2}:){5}[a-fA-F0-9]{2}',target):raise ValueError('Select a Bluetooth companion address')
    elif kind=='usb':
        if not re.fullmatch(r'/dev/bus/usb/\d{3}/\d{3}',target):raise ValueError('Select an attached USB companion')
    else:raise ValueError('Choose Bluetooth or USB for MeshCore')
    return {'enabled':raw['enabled'],'receive':raw.get('receive',False),'transport':kind,'target':target}

class FamilyMeshCore:
    def __init__(self,state,lock,save,session_factory=None,context=None):
        self.state=state;self.lock=lock;self.save=save;self.context=context;self.session_factory=session_factory
        state.setdefault('meshcore',None);self.session=None;self.connected=False;self.error='';self.name='';self.model='';self.owner='';self.contacts={};self.devices=[];self.scanning=False;self.announces={};self.receive_count=0;self.receive_status='No private messages received';self.revision=0;self._acks={};self._pending={};self._subscriptions=[]
        self._advert_pending = False
        self._advert_status = ''
        self._advert_write = None
        self._battery = None
        self._battery_attempt = None
        self._battery_pending = False
        from family_meshcore_rooms import MeshCoreRooms
        self.identity=None;self.locations=None;self._location_write=None;self._location_pending={};self.location_status='Not sharing';self.rooms=MeshCoreRooms(self)
        self.loop=asyncio.new_event_loop();self._apply_lock=None
        threading.Thread(target=self._run,daemon=True).start()
    def _run(self):
        asyncio.set_event_loop(self.loop);self._apply_lock=asyncio.Lock();self.loop.create_task(self._watch());self.loop.run_forever()
    def _submit(self,operation):
        future=asyncio.run_coroutine_threadsafe(operation,self.loop)
        def done(result):
            try:result.result()
            except (concurrent.futures.CancelledError,asyncio.CancelledError):pass
            except Exception as exc:
                with self.lock:self.error=str(exc)[:200]
        future.add_done_callback(done);return future
    def _config(self):
        with self.lock:return dict(self.state['meshcore']) if self.state['meshcore'] else None
    def allowed(self):return {c['addresses']['meshcore']:c for c in self.state['contacts'] if c.get('addresses',{}).get('meshcore')}
    def configure(self,raw):
        config=validate_config(raw) if raw is not None else None
        with self.lock:
            old=self.state['meshcore'];self.revision+=1;revision=self.revision
            if config and old and all(config[k]==old[k] for k in ['transport','target']) and old.get('publicKey'):config['publicKey']=old['publicKey']
            self.state['meshcore']=config;self.connected=False;self.error='';self.save()
            if self.locations:self.locations.reconcile()
        self._submit(self._apply(revision))
    def scan(self):
        with self.lock:
            if self.scanning:return
            self.scanning=True;self.devices=[]
        async def operation():
            try:
                from meshchatnext.src.backend.meshcore_transport import scan_ble
                from family_radios import _context
                devices=await scan_ble(self.context or _context,duration=6)
                with self.lock:self.devices=devices
            finally:
                with self.lock:self.scanning=False
        self._submit(operation())
    async def _close(self):
        self.rooms.disconnected()
        self.connected=False;self.contacts={};self.announces={};self.owner='';self.name='';self.model=''
        with self.lock:
            self._battery = None
            self._battery_attempt = None
            pending=list(self._pending.values())
            self._pending.clear();self._acks.clear();self._location_write=None;self._location_pending={};self.save()
        for mid,_,on_failure in pending:
            self._send_failed(mid,'Not confirmed · MeshCore companion disconnected',on_failure)
        for subscription in self._subscriptions:
            try:subscription.unsubscribe()
            except Exception:pass
        self._subscriptions=[]
        if self.session:
            await self.session.disconnect();self.session=None
    async def _apply(self,revision):
        async with self._apply_lock:
            if revision!=self.revision:return
            if self.connected and self.session and self.session.is_connected:return
            await self._close();config=self._config()
            if not config or not config['enabled']:return
            from meshchatnext.src.backend.meshcore_session import MeshCoreSession
            from family_radios import _context
            if self.session_factory:self.session=self.session_factory()
            else:
                from meshchatnext.src.backend.meshcore_transport import AndroidConnection
                self.session=MeshCoreSession(connection_factory=lambda kind,target,**options:AndroidConnection(kind,target,send_guard=lambda payload,write:self._guard_send(revision,payload,write),**options))
            try:
                await self.session.connect(config['transport'],config['target'],context=self.context or _context)
                identity=await self.session.read_identity();owner=key(identity['public_key'])
                if config.get('publicKey') and owner!=config['publicKey']:raise ValueError('Companion identity changed. Remove and approve this radio again.')
                if revision!=self.revision:await self._close();return
                with self.lock:
                    self.owner=owner;self.name=identity['name'][:64];self.model=str((self.session._device_info or {}).get('model',''))[:64]
                    self.state['meshcore']['publicKey']=owner;self.save()
                await self._contacts()
                from meshcore import EventType
                self._subscriptions=[self.session._client.subscribe(EventType.ACK,self._ack),self.session._client.subscribe(EventType.CONTACT_MSG_RECV,lambda event:self.receive(event.payload or {}))]
                for name in ['ADVERTISEMENT','NEW_CONTACT']:
                    event_type=getattr(EventType,name,None)
                    if event_type:self._subscriptions.append(self.session._client.subscribe(event_type,self._announce))
                with self.lock:self.connected=True;self.error=''
            except BaseException:
                await self._close();raise
    async def _contacts(self):
        from meshcore import EventType
        event=await self.session._client.commands.send(b'\x04',[EventType.CONTACTS,EventType.ERROR]);payload=self.session._payload(event)
        contacts={}
        for candidate,value in payload.items():
            try:peer=key(value.get('public_key',candidate))
            except ValueError:continue
            contacts[peer]=dict(value,public_key=peer)
        with self.lock:self.contacts=contacts
        return contacts
    def refresh_contacts(self):
        async def operation():
            if not self.connected:raise ValueError('Connect a MeshCore companion first')
            async with self.session._lock:await self._contacts()
        return self._submit(operation())
    def request_battery(self):
        with self.lock:
            session = self.session
            if not self.connected or not session or not session.is_connected or self._battery_pending:
                return
            now = time.monotonic()
            if self._battery_attempt is not None and now - self._battery_attempt < 30:
                return
            self._battery_attempt = now
            self._battery_pending = True
            revision = self.revision
        self._submit(self._read_battery(session, revision))

    async def _read_battery(self, session, revision):
        voltage = None
        try:
            result = await session.read_battery()
            value = result.get('voltage_mv')
            if type(value) is int and 2500 <= value <= 4500:
                voltage = value
        except Exception:
            # Battery telemetry is optional and must not replace connection errors.
            pass
        finally:
            with self.lock:
                self._battery_pending = False
                if revision == self.revision and session is self.session and self.connected:
                    self._battery = (time.monotonic(), voltage) if voltage is not None else None

    def send_advert(self, flood):
        if type(flood) is not bool:
            raise ValueError('Choose a local or flood advert')
        with self.lock:
            session = self.session
            config = self.state['meshcore'] or {}
            if not (self.connected and session and session.is_connected and self.owner
                    and config.get('enabled') and config.get('publicKey') == self.owner):
                raise ValueError('Connect an approved MeshCore companion first')
            if self._advert_pending:
                raise ValueError('A MeshCore advert is already in progress')
            self._advert_pending = True
            self._advert_status = 'Submitting advert to the companion…'
            revision = self.revision
        self._submit(self._send_advert(session, revision, flood))

    async def _send_advert(self, session, revision, flood):
        scope = 'Flood' if flood else 'Local'
        payload = bytes((7, 1)) if flood else bytes((7,))
        status = f'{scope} advert was not confirmed by the companion.'
        try:
            async with session._lock:
                with self.lock:
                    if revision != self.revision or session is not self.session or not self.connected:
                        return
                    self._advert_write = (revision, payload)
                try:
                    session._payload(await session._client.commands.send_advert(flood=flood))
                    status = f'{scope} advert accepted by the companion.'
                finally:
                    with self.lock:
                        self._advert_write = None
        except Exception:
            pass
        finally:
            with self.lock:
                self._advert_status = status
                self._advert_pending = False

    def _guard_send(self,revision,payload,write):
        with self.lock:
            config=self.state['meshcore'] or {}
            if revision!=self.revision or not config.get('enabled'):raise ValueError('MeshCore configuration changed')
            command=payload[0]
            if command in [1,4,5,22]:return write() # setup and contact queries; no RF
            if payload == b'\x14':  # Local battery query, no RF.
                if not self.connected or not self.owner or config.get('publicKey') != self.owner:
                    raise ValueError('Companion identity is not approved')
                return write()
            if command == 7:
                if (not self.connected or not self.owner or config.get('publicKey') != self.owner
                        or self._advert_write != (revision, payload)):
                    raise ValueError('MeshCore advert is not authorized')
                return write()
            if command==10:
                if not self.connected or not config.get('receive'):raise ValueError('Receiving is disabled')
                return write()
            if command in [2,9,26,29] and (not self.connected or config.get('publicKey')!=self.owner):raise ValueError('Companion identity is not approved')
            if command==9:
                if len(payload)<34:raise ValueError('Invalid radio contact')
                peer=payload[1:33].hex();kind=payload[33]
                if not ((kind==1 and peer in self.allowed()) or (kind==3 and self.rooms.policy(peer))):raise ValueError('Radio contact is not approved')
                return write()
            if command in [26,29]:
                if len(payload)<33:raise ValueError('Invalid room command')
                peer=payload[1:33].hex();policy=self.rooms.policy(peer)
                if command==29:
                    if not policy and peer not in self.rooms.cleanup_logout:raise ValueError('Room is not approved')
                    result=write();self.rooms.cleanup_logout.discard(peer);return result
                if not policy or not self.rooms._runtime(peer).get('joining'):raise ValueError('Room login is not approved')
                matches=[p for p in self.contacts if p.startswith(peer[:12])]
                if len(matches)!=1 or matches[0]!=peer or self.contacts[peer].get('type')!=3:raise ValueError('Room identity is ambiguous')
                return write()
            if command==2:
                if len(payload)<14 or payload[1]!=0:raise ValueError('Chat commands are disabled')
                prefix=payload[7:13].hex();matches=[peer for peer in self.contacts if peer.startswith(prefix)]
                if len(matches)!=1:raise ValueError('Recipient is not uniquely approved')
                peer=matches[0];kind=self.contacts[peer].get('type')
                if payload[13:].startswith(b'!NFLOC'):
                    permit=self._location_write
                    if not permit or permit!=(peer,payload[13:],self.locations.generation,self.revision,self.owner) or not self.locations.can_send(self.locations.mesh_peer(peer,self.owner),permit[2]):raise ValueError('Location sharing is not authorized')
                if kind==1 and peer in self.allowed():return write()
                room=self.rooms.policy(peer);runtime=self.rooms._runtime(peer)
                if kind!=3 or not room or room['readOnly'] or not runtime['joined'] or runtime.get('owner')!=self.owner:raise ValueError('Room posting is not approved')
                if payload[13:].lstrip().startswith(b'/'):raise ValueError('Chat commands are disabled')
                return write()
            raise ValueError('This companion command is not enabled in the family app')

    def _announce(self,event):
        payload=event.payload or {}
        peer=payload.get('public_key')
        try:peer=key(peer)
        except ValueError:return
        with self.lock:
            self.announces[peer]={**self.announces.get(peer,{}),**payload,'public_key':peer}
            if len(self.announces)>200:self.announces.pop(next(iter(self.announces)))
    def _ack(self,event):
        code=(event.payload or {}).get('code') or (event.attributes or {}).get('code')
        if isinstance(code,bytes):code=code.hex()
        if not isinstance(code,str):return
        with self.lock:
            self._acks[code]=time.time()
            if len(self._acks)>256:self._acks.pop(next(iter(self._acks)))
            self.rooms.ack(code)
            if code in getattr(self,'_location_pending',{}):
                self._location_pending.pop(code,None);self.location_status='Private location delivered · MeshCore receipt' 
            pending=self._pending.pop(code,None)
            if pending:
                mid,_,_=pending
                row=next((m for m in self.state['messages'] if m['id']==mid),None)
                if row:row['status']='Delivered · MeshCore receipt';row['deliveredAt']=time.time();self.save()
    def receive(self,payload):
        prefix=payload.get('pubkey_prefix');text=payload.get('text')
        self.receive_count=getattr(self,'receive_count',0)+1;self.receive_status='Private message received; checking approval'
        if type(payload.get('sender_timestamp')) is not int or not 0<=payload['sender_timestamp']<2**32 or not isinstance(text,str) or not text.strip():return
        if not isinstance(prefix,str) or not re.fullmatch('[a-fA-F0-9]{12}',prefix) or not isinstance(text,str) or payload.get('txt_type')==1:return
        with self.lock:
            config=self.state['meshcore'] or {}
            if not config.get('enabled') or not config.get('receive') or config.get('publicKey')!=self.owner:return
            candidates=[peer for peer in self.contacts if peer.startswith(prefix.lower())]
            if len(candidates)!=1:self.receive_status='Sender prefix is missing or ambiguous';return
            peer=candidates[0]
            if self.contacts[peer].get('type')==3 and self.rooms.receive(peer,payload):return
            if peer not in self.allowed() or self.contacts[peer].get('type')!=1:self.receive_status='Sender is not an approved messaging client';return
            if text.startswith('!NFLOC'):
                if payload.get('txt_type')!=0:return
                try:
                    from family_meshcore_location import decode
                    if self.locations and self.locations.receive_fix(self.locations.mesh_peer(peer,self.owner),decode(text),'meshcore'):self.receive_status='Approved private location saved'
                except (ValueError,TypeError):self.receive_status='Invalid private location discarded'
                return
            fingerprint=hashlib.sha256((self.owner+peer+str(payload.get('sender_timestamp'))+text).encode()).hexdigest()
            if any(m.get('hash')==fingerprint for m in self.state['messages']):return
            self.state['messages'].append({'id':uuid.uuid4().hex,'hash':fingerprint,'peer':peer,'owner':self.owner,'service':'meshcore','text':text[:4096],'timestamp':time.time(),'incoming':True,'status':'Received · MeshCore direct'})
            self.state['messages']=self.state['messages'][-500:];self.receive_status='Approved private message saved';self.save()
    async def _drain(self):
        from meshcore import EventType
        async with self.session._lock:
            for _ in range(32):
                config=self._config()
                if not config or not config['enabled'] or not config['receive']:return
                event=await self.session._client.commands.get_msg();payload=self.session._payload(event)
                if event.type==EventType.NO_MORE_MSGS:return
                if event.type==EventType.CONTACT_MSG_RECV:self.receive(payload)
    async def _watch(self):
        retry=0
        while True:
            await asyncio.sleep(3);config=self._config()
            try:
                if not config or not config['enabled']:continue
                if not self.connected or not self.session or not self.session.is_connected:
                    if time.time()<retry:continue
                    retry=time.time()+15
                    await self._apply(self.revision)
                if self.connected and config.get('receive'):await self._drain()
                self.rooms.tick()
                for code,deadline in list(self._location_pending.items()):
                    if time.time()>deadline:self._location_pending.pop(code,None);self.location_status='Private location not confirmed' 
                self._expire_receipts()
            except Exception as exc:
                with self.lock:self.error=str(exc)[:200]

    def _expire_receipts(self):
        now=time.time()
        with self.lock:
            expired=[self._pending.pop(code) for code,(_,deadline,_) in list(self._pending.items()) if now>deadline]
        for mid,_,on_failure in expired:
            self._send_failed(mid,'Not confirmed · MeshCore receipt timed out',on_failure)

    def _send_failed(self,mid,status,on_failure):
        if on_failure is not None and on_failure(status):return
        with self.lock:
            row=next((m for m in self.state['messages'] if m['id']==mid),None)
            if row and row.get('service')=='meshcore' and not row['status'].startswith('Delivered'):
                row['status']=status;self.save()

    def send(self,mid,peer,text,on_failure=None):return self._submit(self._send(mid,peer,text,on_failure))
    async def _send(self,mid,peer,text,on_failure=None):
        may_have_sent=False
        try:
            peer=key(peer)
            if not text.strip() or len(text.encode())>160:raise ValueError('MeshCore messages support 1–160 UTF-8 bytes')
            if not self.connected or not self.session:raise ValueError('MeshCore companion is disconnected')
            async with self.session._lock:
                with self.lock:
                    contact=self.allowed().get(peer)
                    if not contact:raise ValueError('Contact approval was removed')
                    name=contact['name'].encode()[:31].decode('utf-8','ignore') or 'Approved contact'
                if peer not in self.contacts:
                    self.session._payload(await self.session._client.commands.add_contact({'public_key':peer,'type':1,'flags':0,'out_path':'','out_path_len':-1,'out_path_hash_mode':-1,'adv_name':name,'last_advert':0,'adv_lat':0,'adv_lon':0}))
                    await self._contacts()
                    if peer not in self.contacts:raise ValueError('Companion could not add this approved contact')
                with self.lock:
                    if peer not in self.allowed():raise ValueError('Contact approval was removed')
                    if not self.connected or not (self.state['meshcore'] or {}).get('enabled'):raise ValueError('MeshCore is disabled')
                    if len([candidate for candidate in self.contacts if candidate.startswith(peer[:12])])!=1:raise ValueError('Companion has an ambiguous contact prefix')
                from meshcore import EventType
                started=time.time()
                with self.lock:
                    row=next((m for m in self.state['messages'] if m['id']==mid),None)
                    stamp=max(int(started),max((m.get('meshcoreTimestamp',0) for m in self.state['messages'] if m.get('peer')==peer),default=0)+1)
                    if row:row['meshcoreTimestamp']=stamp;self.save()
                may_have_sent=True
                event=await self.session._client.commands.send_msg(peer,text,timestamp=stamp,attempt=0)
                # The library also uses ERROR for host timeouts and write failures.
                # Only the companion's explicit rejection proves it declined the message.
                if event is not None and event.type==EventType.ERROR and (event.payload=={} or 'error_code' in (event.payload or {})):
                    may_have_sent=False
                    raise ValueError('MeshCore companion rejected the message')
                if event is None or event.type!=EventType.MSG_SENT:raise ValueError('MeshCore companion did not confirm acceptance')
                payload=event.payload;ack=payload.get('expected_ack')
                if not isinstance(ack,bytes) or len(ack)!=4:raise ValueError('Invalid MeshCore receipt token')
                code=ack.hex();timeout=float(payload.get('suggested_timeout',30000))/1000
                if not math.isfinite(timeout) or not 0<=timeout<=86400:raise ValueError('Invalid MeshCore receipt timeout')
                with self.lock:
                    row=next((m for m in self.state['messages'] if m['id']==mid),None)
                    if row:
                        early=self._acks.get(code,0)>=started-.5
                        row['status']='Delivered · MeshCore receipt' if early else 'Accepted by MeshCore radio · awaiting receipt'
                        if not early:
                            deadline=time.time()+min(300,max(5,timeout*1.2))
                            self._pending[code]=(mid,deadline,on_failure)
                        self.save()
        except Exception as exc:
            status=('Not confirmed · ' if may_have_sent else 'Failed · ')+str(exc)[:160]
            self._send_failed(mid,status,on_failure)
    def send_location(self,target,fix,generation):
        return self._submit(self._send_location(target,fix,generation,self.revision))
    async def _send_location(self,target,fix,generation,revision):
        try:
            from family_meshcore_location import encode
            _,owner,peer=target.split(':');peer=key(peer);frame=encode(fix)
            if not self.connected or not self.session:raise ValueError('MeshCore is disconnected')
            async with self.session._lock:
                with self.lock:
                    if revision!=self.revision or owner!=self.owner or not self.locations or not self.locations.can_send(target,generation):raise ValueError('Location permission changed')
                    if peer not in self.allowed():raise ValueError('Location contact is not approved')
                    contact=self.allowed()[peer]
                if peer not in self.contacts:
                    name=contact['name'].encode()[:31].decode('utf-8','ignore') or 'Approved contact'
                    self.session._payload(await self.session._client.commands.add_contact({'public_key':peer,'type':1,'flags':0,'out_path':'','out_path_len':-1,'out_path_hash_mode':-1,'adv_name':name,'last_advert':0,'adv_lat':0,'adv_lon':0}))
                    await self._contacts()
                with self.lock:
                    if revision!=self.revision or owner!=self.owner or not self.locations.can_send(target,generation):raise ValueError('Location permission changed')
                    if self.contacts.get(peer,{}).get('type')!=1:raise ValueError('Location recipient is not a messaging client')
                    if len([p for p in self.contacts if p.startswith(peer[:12])])!=1:raise ValueError('Location contact is ambiguous')
                    self._location_write=(peer,frame.encode(),generation,revision,owner)
                try:
                    from meshcore import EventType
                    started=time.time()
                    event=await self.session._client.commands.send_msg(peer,frame,timestamp=int(started),attempt=0)
                    if event is None or event.type!=EventType.MSG_SENT:raise ValueError('Radio did not confirm acceptance')
                    ack=event.payload.get('expected_ack')
                    if not isinstance(ack,bytes) or len(ack)!=4:raise ValueError('Invalid location receipt token')
                    code=ack.hex()
                    with self.lock:
                        early=self._acks.get(code,0)>=started-.5
                        self.location_status='Private location delivered · MeshCore receipt' if early else 'Private location accepted by radio · awaiting receipt'
                        if not early:self._location_pending[code]=time.time()+60
                finally:self._location_write=None
        except Exception as exc:
            with self.lock:self.location_status='Location not sent or unconfirmed: '+str(exc)[:120]

    def snapshot(self):
        with self.lock:
            config=self.state['meshcore'];candidates={**self.contacts}
            for peer,advert in self.announces.items():
                candidates[peer]={**candidates.get(peer,{}),**advert}
            battery = None
            if self.connected and self.session and self.session.is_connected and self._battery:
                read_at, voltage = self._battery
                if time.monotonic() - read_at < 75:
                    battery = {'voltage_mv': voltage}
            return {'advertPending':self._advert_pending,'advertStatus':self._advert_status,'battery':battery,'enabled':bool(config and config['enabled']),'config':dict(config) if config else None,'locationStatus':self.location_status,'receiveCount':self.receive_count,'receiveStatus':self.receive_status,'connected':self.connected,'name':self.name,'model':self.model,'publicKey':self.owner or (config or {}).get('publicKey',''),'error':self.error,'scanning':self.scanning,'devices':list(self.devices),
                    'clientAnnounces':[{'name':str(c.get('adv_name','Messaging client'))[:64],'service':'meshcore','address':peer,'seen':c.get('last_advert',0)} for peer,c in candidates.items() if c.get('type')==1],
                    'roomAnnounces':[{'name':str(c.get('adv_name','Room server'))[:64],'service':'meshcore','key':peer,'kind':3} for peer,c in candidates.items() if c.get('type')==3]}
