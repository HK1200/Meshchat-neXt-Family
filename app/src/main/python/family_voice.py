"""Approved LXST calls with native Android PCM; no host audio or auto-answer."""
import sys,threading,time,uuid

PCM_BYTES_PER_MS = 96
PLAYBACK_CHUNK = 20 * PCM_BYTES_PER_MS


class VoicePlaybackBuffer:
 """Bounded 48 kHz mono PCM buffer. The Android audio clock paces playback."""

 def __init__(self):
  self.clear()

 def clear(self):
  self.pcm=bytearray()
  self.playing=False
  self.underruns=0
  self.dropped_bytes=0

 def append(self,pcm):
  self.pcm.extend(pcm)
  excess=len(self.pcm)-500*PCM_BYTES_PER_MS
  if excess>0:
   del self.pcm[:excess]
   self.dropped_bytes+=excess

 def pull(self):
  if not self.playing:
   if len(self.pcm)<120*PCM_BYTES_PER_MS:return b''
   self.playing=True
  if len(self.pcm)<PLAYBACK_CHUNK:
   self.playing=False
   self.underruns+=1
   return b''
  chunk=bytes(self.pcm[:PLAYBACK_CHUNK])
  del self.pcm[:PLAYBACK_CHUNK]
  return chunk


def check_default_codec(profiles):
 """Check that the bundled codec can run before accepting call signaling."""
 import numpy as np
 from types import SimpleNamespace

 profile=profiles.DEFAULT_PROFILE
 samples=(np.sin(np.arange(48*profiles.get_frame_time(profile))*0.0576)*0.25).astype(np.float32).reshape(-1,1)
 try:
  encoder=profiles.get_codec(profile)
  decoder=profiles.get_codec(profile)
  pcm_endpoint=SimpleNamespace(channels=1,samplerate=48000)
  encoder.source=pcm_endpoint
  decoder.sink=pcm_endpoint
  decoded=decoder.decode(encoder.encode(samples))
  if decoded.shape!=samples.shape or not np.all(np.isfinite(decoded)) or not np.any(decoded):
   raise ValueError('Opus returned invalid audio')
 except Exception as exc:
  raise RuntimeError(f'Reticulum voice codec could not start: {exc}') from exc


class FamilyVoice:
 def __init__(self,identity,state,lock,save,gate=None,route_context=None,autostart=True):
  self.identity=identity;self.state=state;self.lock=lock;self.save=save;self.gate=gate;self.phone=None;self.error='';self.phase='idle';self.profiles=None;self.peer='';self.target='';self.call_id='';self.name='';self.generation=0;self.input=None;self.pcm=VoicePlaybackBuffer();self.sent=0;self.received=0;self.muted=False;self._setup=threading.Lock();self._dialling=False
  self.route_context=route_context or (lambda address:'reticulum');self.outgoing=False;self.connected_at=0.;self.quality_context='';self.last_rtt=None
  state.setdefault('voiceEnabled',False);state.setdefault('callQuality',[])
  if state['voiceEnabled'] and autostart:threading.Thread(target=self._ensure,daemon=True).start()
 def _gate(self,acquire):
  if self.gate:return self.gate(acquire)
  from java import jclass
  from family_radios import _context
  gate=jclass('org.meshchat.family.preview.FamilyCallGate')
  if acquire:return bool(gate.acquire(_context,'reticulum'))
  gate.release('reticulum');return True
 def _contact(self,identity_hash):
  import RNS
  address=RNS.Destination.hash_from_name_and_identity('lxst.telephony',identity_hash).hex()
  return next((c for c in self.state['contacts'] if c.get('addresses',{}).get('lxst','').lower()==address),None)
 def allowed(self,identity_hash):
  with self.lock:return bool(self.state.get('voiceEnabled') and self._contact(identity_hash))
 def configure(self,enabled):
  if type(enabled) is not bool:raise ValueError('Invalid voice setting')
  with self.lock:self.state['voiceEnabled']=enabled;self.save()
  if enabled:threading.Thread(target=self._ensure,daemon=True).start()
  else:
   self.hangup()
   def close():
    with self._setup:
     with self.lock:phone=self.phone;self.phone=None
     if phone:phone.teardown()
   threading.Thread(target=close,daemon=True).start()
 def _ensure(self):
  with self._setup:
   if self.phone or not self.state.get('voiceEnabled'):return
   try:
    from lxst_pyogg_ctypes_compat import ensure_lxst_pyogg_ctypes_compat
    ensure_lxst_pyogg_ctypes_compat()
    from LXST.Network import LinkSource
    if not hasattr(LinkSource,"samplerate"):LinkSource.samplerate=48000
    from LXST.Primitives import Telephony
    from RNS.vendor import umsgpack
    if sys.platform == 'ios':check_default_codec(Telephony.Profiles)
    self._install_audio(Telephony)
    phone=Telephony.Telephone(self.identity,auto_answer=None,allowed=self.allowed,wait_time=30)
    phone.destination.set_default_app_data(lambda: umsgpack.packb([self.state.get('device_name','neXt Family'),None,None]))
    # LXST 0.5.4's worker reads ANNOUNCE_INTERVAL directly. Family schedules
    # announcements on its enabled routes, so suppress the library's broadcast.
    phone.last_announce=time.time();phone.ANNOUNCE_INTERVAL=2**31-1
    phone.set_busy_tone_time(0);phone.set_connect_timeout(30)
    phone.set_ringing_callback(self._ring);phone.set_established_callback(self._connected);phone.set_ended_callback(self._ended)
    if not self.state.get('voiceEnabled'):phone.teardown();return
    with self.lock:self.phone=phone;self.profiles=Telephony.Profiles;self.error=''
   except Exception as exc:self.error=str(exc)[:200]
 def _install_audio(self,telephony):
  import numpy as np
  from LXST.Sources import LocalSource
  from LXST.Sinks import LocalSink
  from LXST.Codecs import Raw
  manager=self
  class Input(LocalSource):
   def __init__(self,preferred_device=None,target_frame_ms=60,codec=None,sink=None,**kwargs):
    from lxst_audio_processing import prepare_capture_filters
    self.filters=prepare_capture_filters(kwargs.get('filters'))
    self.target_frame_ms=target_frame_ms or 60;self.codec=codec or Raw(channels=1,bitdepth=16);self.sink=sink;self.channels=1;self.samplerate=48000;self.bitdepth=16;self.should_run=False
    self.frame_bytes=round(self.target_frame_ms*PCM_BYTES_PER_MS)
    self.pending=bytearray()
    manager.input=self
   def start(self):self.should_run=True
   def stop(self):
    with manager.lock:self.should_run=False;self.pending.clear()
   def can_receive(self,from_source=None):return True
   def handle_frame(self,frame,source=None):pass
   def push(self,data):
    if not self.should_run or not self.sink:return 0
    self.pending.extend(data)
    sent=0
    while len(self.pending)>=self.frame_bytes:
     frame=bytes(self.pending[:self.frame_bytes])
     del self.pending[:self.frame_bytes]
     if self.sink.can_receive(from_source=self):
      samples=(np.frombuffer(frame,dtype='<i2').astype(np.float32)/32768.0).reshape(-1,1)
      for audio_filter in self.filters:samples=audio_filter.handle_frame(samples,self.samplerate)
      self.sink.handle_frame(self.codec.encode(samples),self)
      sent+=1
    return sent
  class Output(LocalSink):
   def __init__(self,*args,**kwargs):self.samplerate=48000;self.channels=1;self.bitdepth=16;self.streaming=False;self.should_run=False;self.buffer_max_height=3;self.autostart_min=1
   def start(self):self.should_run=True;self.streaming=True
   def stop(self):self.should_run=False;self.streaming=False
   def can_receive(self,from_source=None):return True
   def wait_for_frames(self):pass
   def enable_low_latency(self):pass
   def handle_frame(self,frame,source=None):
    with manager.lock:
     if manager.phase!='connected' or not manager.state.get('voiceEnabled'):return
     data=np.asarray(frame,dtype=np.float32)
     if data.ndim==2 and data.shape[1]>1:data=data.mean(axis=1)
     pcm=(np.clip(data,-1,1)*32767).astype('<i2').tobytes()
     if not pcm or len(pcm)>65536:return
     manager.pcm.append(pcm);manager.received+=1
  telephony.LineSource=Input;telephony.LineSink=Output
 def _ring(self,identity):
  with self.lock:
   contact=self._contact(identity.hash)
   if not self.allowed(identity.hash) or not self._gate(True):threading.Thread(target=self.hangup,daemon=True).start();return
   self.outgoing=False;self.connected_at=0.;self.last_rtt=None
   self.generation+=1;self.call_id=uuid.uuid4().hex;self.phase='incoming';self.peer=identity.hash.hex();self.target=contact['addresses']['lxst'];self.name=contact['name'];self.error='';self.sent=0;self.received=0
 def _connected(self,identity):
  with self.lock:
   if self.phase not in ['calling','incoming'] or not self.call_id or not self.allowed(identity.hash):threading.Thread(target=self.hangup,daemon=True).start();return
   self.peer=identity.hash.hex();self.phase='connected';self.connected_at=time.time();self.last_rtt=getattr(getattr(self.phone,'active_call',None),'rtt',None);self.name=self._contact(identity.hash)['name']
 def _ended(self,identity=None):
  with self.lock:
   if self.outgoing and self.target and ((self.connected_at and time.time()-self.connected_at>=3) or self.error):
    metrics={};rtt=getattr(getattr(self.phone,'active_call',None),'rtt',None) or self.last_rtt
    if isinstance(rtt,(int,float)) and 0<=rtt<60:metrics['rtt_ms']=rtt*1000
    self.state['callQuality']=(self.state.get('callQuality',[])+[{'service':'reticulum','target':self.target,'context':self.quality_context,'timestamp':time.time(),'failed':bool(self.error),'metrics':metrics}])[-64:];self.save()
   if self.outgoing and self.phase in ('finding','calling') and not self.error:
    self.error='The Reticulum call ended before audio connected.'
   self.outgoing=False;self.connected_at=0.
   self.generation+=1;self.phase='idle';self.peer='';self.target='';self.call_id='';self.muted=False;self._gate(False)
   self.pcm.clear()
 def call(self,contact_id,automatic=False):
  with self.lock:
   contact=next((c for c in self.state['contacts'] if c['id']==contact_id),None)
   address=contact.get('addresses',{}).get('lxst','') if contact else ''
   if not address:raise ValueError('This contact has no approved Reticulum voice address')
   if not self.state.get('voiceEnabled') or not self.phone:raise ValueError(self.error or 'Enable Reticulum calling in guardian settings')
   if self.phase!='idle' or self._dialling or self.phone.active_call:raise ValueError('A Reticulum call is already active')
   if not self._gate(True):raise ValueError('Another call is active or Family is in the background')
   self.outgoing=True;self.connected_at=0.;self.quality_context=self.route_context(address)
   self.generation+=1;generation=self.generation;self.phase='finding';self._dialling=True;self.target=address;self.call_id=uuid.uuid4().hex;self.name=contact['name'];self.error='';self.sent=0;self.received=0
  def dial():
   try:
    import RNS
    target=bytes.fromhex(address);deadline=time.monotonic()+30
    if not RNS.Transport.has_path(target):RNS.Transport.request_path(target)
    while not RNS.Transport.has_path(target):
     if generation!=self.generation:return
     if time.monotonic()>deadline:raise ValueError('No Reticulum voice path is available')
     time.sleep(.2)
    identity=RNS.Identity.recall(target)
    if automatic and self.route_context(address).startswith('radio:'):raise ValueError('Radio path is too slow for this voice profile')
    with self.lock:
     if generation!=self.generation:return
     if not identity or not self.allowed(identity.hash):raise ValueError('Voice identity is not approved')
     self.peer=identity.hash.hex();self.phase='calling'
    self.phone.call(identity)
   except Exception as exc:
    with self.lock:
     if generation==self.generation:self.error=str(exc)[:200];self._ended()
   finally:
    with self.lock:self._dialling=False
  threading.Thread(target=dial,daemon=True).start()
 def answer(self,call_id):
  with self.lock:
   if not call_id or call_id!=self.call_id or self.phase!='incoming':raise ValueError('The incoming call has changed')
   if not self.allowed(bytes.fromhex(self.peer)):raise ValueError('Contact approval was removed')
   import RNS
   identity=self.phone.active_call.get_remote_identity()
   if not identity or identity.hash.hex()!=self.peer:raise ValueError('The incoming identity changed')
  def answer_call():
   try:self.phone.answer(identity)
   except Exception as exc:self.error=str(exc)[:200];self.hangup()
  threading.Thread(target=answer_call,daemon=True).start()
 def hangup(self,call_id=None):
  with self.lock:
   # A delayed UI/notification action for an ended call must not affect a newer call.
   if call_id is not None and call_id!=self.call_id:return
   self.generation+=1;self.phase='ending' if self.phone and self.phone.active_call else 'idle'
   if self.phase=='idle':self._ended();return
  def end():
   try:self.phone.hangup()
   finally:self._ended()
  threading.Thread(target=end,daemon=True).start()
 def reconcile(self):
  with self.lock:
   if (self.peer and not self.allowed(bytes.fromhex(self.peer))) or (self.target and not any(c.get('addresses',{}).get('lxst','')==self.target for c in self.state['contacts'])):self.hangup()
 def push(self,call_id,data):
  with self.lock:
   if call_id!=self.call_id or self.phase!='connected' or not self.allowed(bytes.fromhex(self.peer)) or self.muted or not self.input:return
   data=bytes(data)
   if not data or len(data)>11520 or len(data)%2:return
   try:self.sent+=self.input.push(data)
   except Exception as exc:
    self.error=f'Reticulum microphone audio failed: {exc}'[:200]
    self.hangup(call_id)
 def pull(self,call_id):
  with self.lock:
   if call_id!=self.call_id or self.phase!='connected' or not self.peer or not self.allowed(bytes.fromhex(self.peer)):return b''
   return self.pcm.pull()
 def set_muted(self,muted):
  with self.lock:
   self.muted=muted
   if muted and self.input:self.input.pending.clear()
 def snapshot(self):
  with self.lock:
   call=getattr(self.phone,'active_call',None)
   profile=getattr(call,'profile',None)
   profile_name=self.profiles.profile_name(profile) if self.profiles and profile is not None else ''
   return {'enabled':self.state.get('voiceEnabled',False),'ready':self.phone is not None,'address':self.phone.destination.hash.hex() if self.phone and self.phone.destination else '', 'call_state':self.phase,'call_id':self.call_id,'caller_name':self.name,'error':self.error,'sentFrames':self.sent,'receivedFrames':self.received,'playbackUnderruns':self.pcm.underruns,'playbackDroppedMs':self.pcm.dropped_bytes//PCM_BYTES_PER_MS,'muted':self.muted,'target':self.target,'profile':profile_name}
