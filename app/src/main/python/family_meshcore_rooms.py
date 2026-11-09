"""Approved MeshCore room servers; radio commands remain guarded at handoff."""
import asyncio,base64,hashlib,math,re,time,uuid
class MeshCoreRooms:
 def __init__(self,manager):
  self.manager=manager;self.state=manager.state;self.lock=manager.lock;self.save=manager.save;self.runtime={};self.pending={};self.active=None;self.cleanup_logout=set()
  self.state.setdefault('rooms',[]);self.state.setdefault('next_room_id',max([0]+[r['id'] for r in self.state['rooms']])+1);self.state.setdefault('meshcore_room_keys',{});self.state.setdefault('meshcore_room_messages',{})
 def records(self):return [r for r in self.state['rooms'] if r.get('service','reticulum')=='meshcore']
 def policy(self,peer):return next((r for r in self.records() if r['key']==peer),None)
 def record(self,rid):
  record=next((r for r in self.records() if r['id']==rid),None)
  if not record:raise ValueError('This room is not approved')
  return record
 def _owner(self):return self.manager.owner or (self.state.get('meshcore') or {}).get('publicKey','')
 def _ready(self):
  config=self.state.get('meshcore') or {}
  if not self.manager.connected or config.get('publicKey')!=self.manager.owner:raise ValueError('Connect the approved MeshCore companion first')
  if not config.get('receive'):raise ValueError('Enable MeshCore receiving in guardian settings')
 def _runtime(self,peer):return self.runtime.setdefault(peer,{'joined':False,'status':'Not joined','error':'','uncertain':False})
 def save_room(self,payload):
  raw=payload.get('room',{});name=raw.get('name','');peer=raw.get('key','');rid=raw.get('id');password=payload.get('password','');readonly=raw.get('readOnly',False)
  if payload.get('approved') is not True:raise ValueError('Confirm guardian room approval')
  if not isinstance(name,str) or not name.strip() or len(name.strip())>32:raise ValueError('Use a room name of 1–32 characters')
  if not isinstance(peer,str) or not re.fullmatch('[a-fA-F0-9]{64}',peer):raise ValueError('Use the full 64-character MeshCore room-server key')
  peer=peer.lower()
  if type(readonly) is not bool:raise ValueError('Invalid room posting permission')
  if not isinstance(password,str) or '\0' in password or len(password.encode())>64:raise ValueError('Room password supports at most 64 UTF-8 bytes without NUL')
  with self.lock:
   old=next((r for r in self.state['rooms'] if r['id']==rid),None)
   if rid is not None and (type(rid) is not int or not old or old.get('service','reticulum')!='meshcore'):raise ValueError('Unknown MeshCore room ID')
   if any(r['id']!=rid and r['key']==peer for r in self.records()):raise ValueError('This room is already approved')
   if not old and len(self.state['rooms'])>=32:raise ValueError('Room limit reached')
   if old and old['key']!=peer:raise ValueError('Remove this approval before changing the server identity')
   cipher=None
   if password:
    identity=getattr(self.manager,'identity',None)
    if identity is None:raise ValueError('Secure room storage is starting')
    cipher=base64.b64encode(identity.encrypt(password.encode())).decode()
   if not old:rid=self.state['next_room_id'];self.state['next_room_id']+=1
   row={'id':rid,'name':name.strip(),'key':peer,'channel':'','service':'meshcore','readOnly':readonly}
   if old:self.state['rooms']=[row if r['id']==rid else r for r in self.state['rooms']]
   else:self.state['rooms'].append(row)
   if cipher:self.state['meshcore_room_keys'][str(rid)]=cipher
   elif payload.get('clearPassword'):self.state['meshcore_room_keys'].pop(str(rid),None)
   self.save()
   if cipher or payload.get('clearPassword'):self.runtime.pop(peer,None)
  return rid
 def remove(self,rid):
  with self.lock:
   row=self.record(rid);peer=row['key'];was_joined=bool(self._runtime(peer)['joined'] or self._runtime(peer).get('joining') or self._runtime(peer)['uncertain']);self.state['rooms']=[r for r in self.state['rooms'] if r['id']!=rid];self.state['meshcore_room_keys'].pop(str(rid),None);self.runtime.pop(peer,None);self.pending={code:value for code,value in self.pending.items() if value[0]!=rid};self.save()
   if self.active==rid:self.active=None
   if was_joined and self.manager.connected:
    self.cleanup_logout.add(peer)
    self.manager._submit(self._logout(peer,self.manager.revision,self.manager.owner))
 async def _logout(self,peer,revision,owner):
  try:
   if revision!=self.manager.revision or owner!=self.manager.owner:return
   session=self.manager.session
   async with session._lock:await session._client.commands.send_logout(peer)
  finally:
   with self.lock:self.cleanup_logout.discard(peer)
 def open(self,rid):
  with self.lock:
   row=self.record(rid);self._ready();self.active=rid;self._mark_read(rid);runtime=self._runtime(row['key'])
   if runtime['joined'] or runtime.get('joining'):return
   if runtime['uncertain']:raise ValueError('The previous login is unconfirmed. Reconnect the companion before retrying.')
   runtime.update(joining=True,status='Joining room…',error='');revision=self.manager.revision
  self.manager._submit(self._join(rid,revision))
 def close_view(self):
  with self.lock:self.active=None
 def _mark_read(self,rid):
  changed=False
  for row in self.state['meshcore_room_messages'].get(str(rid),[]):
   if row.get('owner')==self._owner() and row.get('incoming') and not row.get('read'):row['read']=True;changed=True
  if changed:self.save()
 async def _contact(self,peer,name):
  manager=self.manager
  if peer not in manager.contacts:
   manager.session._payload(await manager.session._client.commands.add_contact({'public_key':peer,'type':3,'flags':0,'out_path':'','out_path_len':-1,'out_path_hash_mode':-1,'adv_name':name,'last_advert':0,'adv_lat':0,'adv_lon':0}))
   await manager._contacts()
  candidates=[p for p in manager.contacts if p.startswith(peer[:12])]
  if len(candidates)!=1 or candidates[0]!=peer or manager.contacts[peer].get('type')!=3:raise ValueError('Select an unambiguous room-server identity')
 async def _join(self,rid,revision):
  from meshcore import EventType
  manager=self.manager;peer=None;sent=False;subscriptions=[]
  try:
   with self.lock:
    row=self.record(rid);peer=row['key'];cipher=self.state['meshcore_room_keys'].get(str(rid));password=getattr(manager,'identity').decrypt(base64.b64decode(cipher)).decode() if cipher else '';self._ready()
   async with manager.session._lock:await self._contact(peer,row['name'])
   future=asyncio.get_running_loop().create_future()
   def receive(event):
    prefix=(event.payload or {}).get('pubkey_prefix') or (event.attributes or {}).get('pubkey_prefix')
    with self.lock:
     valid=revision==manager.revision and self.policy(peer) and self._owner()==manager.owner
    if valid and prefix==peer[:12] and not future.done():future.set_result(event)
   subscriptions=[manager.session._client.subscribe(t,receive) for t in [EventType.LOGIN_SUCCESS,EventType.LOGIN_FAILED]]
   async with manager.session._lock:
    with self.lock:self.record(rid);self._ready()
    result=await manager.session._client.commands._send_login_raw(peer,password);password='';sent=True
   if result is None or result.type!=EventType.MSG_SENT:raise ValueError('The companion did not confirm login submission')
   suggested=(result.payload or {}).get('suggested_timeout',20000);timeout=min(90,max(20,float(suggested)/1000*1.5)) if type(suggested) in [int,float] and math.isfinite(suggested) else 30
   response=await asyncio.wait_for(future,timeout)
   with self.lock:
    self.record(rid)
    if revision!=manager.revision:raise ValueError('The companion connection changed')
    if response.type==EventType.LOGIN_FAILED:raise ValueError('The room server rejected the login')
    self._runtime(peer).update(joined=True,joining=False,status='Joined',error='',owner=manager.owner)
  except Exception as exc:
   with self.lock:
    if peer and revision==manager.revision and self.policy(peer):self._runtime(peer).update(joined=False,joining=False,status='Not joined',error=str(exc)[:160],uncertain=sent and isinstance(exc,TimeoutError))
  finally:
   for subscription in subscriptions:
    try:subscription.unsubscribe()
    except Exception:pass
 def post(self,rid,text):
  with self.lock:
   row=self.record(rid);self._ready();runtime=self._runtime(row['key'])
   if row['readOnly']:raise ValueError('This room is read only')
   if not runtime['joined'] or runtime.get('owner')!=self.manager.owner:raise ValueError('Join the approved room before posting')
   if not isinstance(text,str) or not text.strip() or '\0' in text or len(text.strip().encode())>160:raise ValueError('Room messages support 1–160 UTF-8 bytes without NUL')
   if text.lstrip().startswith('/'):raise ValueError('Chat commands are disabled in the family companion')
   mid=uuid.uuid4().hex;record={'id':mid,'msg_id':mid,'owner':self.manager.owner,'src':self.manager.owner,'text':text.strip(),'incoming':False,'timestamp':time.time(),'delivery':'sending','nick':'You'};self.state['meshcore_room_messages'].setdefault(str(rid),[]).append(record);self.state['meshcore_room_messages'][str(rid)]=self.state['meshcore_room_messages'][str(rid)][-200:];self.save()
  self.manager._submit(self._post(rid,mid,record['text'],self.manager.revision,record['owner']))
  return mid
 async def _post(self,rid,mid,text,revision,owner):
  manager=self.manager
  try:
   from meshcore import EventType
   async with manager.session._lock:
    with self.lock:
     row=self.record(rid);self._ready()
     if revision!=manager.revision or owner!=manager.owner:raise ValueError('The companion changed before posting')
    clock=manager.session._payload(await manager.session._client.commands.get_time()).get('time')
    if type(clock) is not int or not 0<=clock<2**32-1:raise ValueError('Invalid companion clock')
    with self.lock:
     history=self.state['meshcore_room_messages'].get(str(rid),[]);stamp=max(int(time.time()),clock+1,max((m.get('meshcoreTimestamp',0)+1 for m in history),default=0));record=next(m for m in history if m['id']==mid)
     if stamp>time.time()+60:raise ValueError('The companion clock is too far ahead')
     record['meshcoreTimestamp']=stamp;self.save()
    started=time.time()
    event=await manager.session._client.commands.send_msg(row['key'],text,timestamp=stamp,attempt=0)
    if event is None or event.type!=EventType.MSG_SENT:raise ValueError('Post acceptance is not confirmed')
    ack=(event.payload or {}).get('expected_ack');timeout=(event.payload or {}).get('suggested_timeout',30000)
    if not isinstance(ack,bytes) or len(ack)!=4 or type(timeout) not in [int,float] or not math.isfinite(timeout) or not 0<=timeout<=86400000:raise ValueError('Invalid room delivery receipt')
    with self.lock:
     if record.get('delivery')!='sent':
      if manager._acks.get(ack.hex(),0)>=started:record['delivery']='sent';record['status']='Delivered to room server · MeshCore receipt'
      else:
       record['delivery']='accepted';record['status']='Accepted by radio · awaiting room receipt';self.pending[ack.hex()]=(rid,mid,owner,time.time()+max(5,timeout/1000*1.2))
     self.save()
  except Exception as exc:
   with self.lock:
    record=next((m for m in self.state['meshcore_room_messages'].get(str(rid),[]) if m['id']==mid),None)
    if record:record['delivery']='failed';record['status']='Not confirmed · '+str(exc)[:120];self.save()
 def receive(self,peer,payload):
  with self.lock:
   row=self.policy(peer)
   if not row:return False
   config=self.state.get('meshcore') or {}
   if not self.manager.connected or not config.get('enabled') or not config.get('receive') or config.get('publicKey')!=self.manager.owner:return True
   text=payload.get('text');stamp=payload.get('sender_timestamp');author=payload.get('signature')
   if payload.get('txt_type')!=2 or not isinstance(author,str) or not re.fullmatch('[a-fA-F0-9]{8}',author) or not isinstance(text,str) or not text.strip() or len(text.encode())>4096 or type(stamp) is not int or not 0<=stamp<2**32:return True
   author=author.lower();owner=self.manager.owner;fingerprint=hashlib.sha256((owner+peer+author+str(stamp)+text).encode()).hexdigest();history=self.state['meshcore_room_messages'].setdefault(str(row['id']),[])
   if any(m.get('hash')==fingerprint for m in history):return True
   if author==owner[:8]:
    pending=next((m for m in reversed(history) if not m.get('incoming') and m.get('owner')==owner and m.get('text')==text and m.get('delivery') in ['sending','accepted','failed']),None)
    if pending:pending.update(delivery='sent',status='Relayed by room server',hash=fingerprint);self.save();return True
   matches=[(p,v) for p,v in self.manager.contacts.items() if p.startswith(author) and v.get('type')==1];name=author
   if len(matches)==1:
    contact=next((c for c in self.state['contacts'] if c.get('addresses',{}).get('meshcore')==matches[0][0]),None);name=str(contact['name'] if contact else matches[0][1].get('adv_name',author))[:64]
   history.append({'id':uuid.uuid4().hex,'hash':fingerprint,'owner':owner,'src':author,'participantId':author,'nick':name,'text':text,'incoming':True,'timestamp':time.time(),'senderTimestamp':stamp,'delivery':'received','read':self.active==row['id']});self.state['meshcore_room_messages'][str(row['id'])]=history[-200:];self.save();return True
 def ack(self,code):
  with self.lock:
   item=self.pending.pop(code,None)
   if not item:return
   rid,mid,owner,deadline=item
   if owner!=self.manager.owner or not any(r['id']==rid for r in self.records()):return
   row=next((m for m in self.state['meshcore_room_messages'].get(str(rid),[]) if m['id']==mid and m.get('owner')==owner),None)
   if row:row['delivery']='sent';row['status']='Delivered to room server · MeshCore receipt';self.save()
 def tick(self):
  with self.lock:
   for code,(rid,mid,owner,deadline) in list(self.pending.items()):
    if time.time()<deadline:continue
    self.pending.pop(code,None);row=next((m for m in self.state['meshcore_room_messages'].get(str(rid),[]) if m['id']==mid and m.get('owner')==owner),None)
    if row and row.get('delivery')!='sent':row['delivery']='unconfirmed';row['status']='Not confirmed · room receipt timed out';self.save()
 def disconnected(self):
  with self.lock:
   for rid,mid,owner,deadline in self.pending.values():
    row=next((m for m in self.state['meshcore_room_messages'].get(str(rid),[]) if m['id']==mid and m.get('owner')==owner),None)
    if row and row.get('delivery')!='sent':row['delivery']='unconfirmed';row['status']='Not confirmed · companion disconnected';self.save()
   self.pending.clear();self.runtime.clear();self.cleanup_logout.clear();self.active=None
 def snapshot(self):
  with self.lock:
   records=[];runtime={};owner=self._owner()
   for original in self.records():
    row=dict(original,hasPassword=str(original['id']) in self.state['meshcore_room_keys']);records.append(row);data=self._runtime(row['key']);history=[dict(m) for m in self.state['meshcore_room_messages'].get(str(row['id']),[]) if m.get('owner')==owner]
    runtime[str(row['id'])]={'connected':self.manager.connected,'joined':data['joined'] and data.get('owner')==owner,'status':data['status'] if self.manager.connected else 'MeshCore disconnected','error':data['error'],'maxMessageBytes':160,'unread':sum(bool(m.get('incoming') and not m.get('read')) for m in history),'messages':history}
   return {'rooms':records,'roomRuntime':runtime}
