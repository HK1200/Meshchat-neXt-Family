"""Approved-contact location policy and neXt-compatible signed LXMF telemetry."""
import math,time
from meshchatnext.src.backend.telemetry_utils import Telemeter

def valid_fix(raw,now=None):
    now=time.time() if now is None else now
    if not isinstance(raw,dict):raise ValueError('Invalid location')
    result={}
    for key,default in [('latitude',None),('longitude',None),('altitude',0),('speed',0),('bearing',0),('accuracy',0),('last_update',now)]:
        value=raw.get(key,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Invalid '+key)
        result[key]=value
    if not -90<=result['latitude']<=90 or not -180<=result['longitude']<=180:raise ValueError('Invalid coordinates')
    if not 0<=result['accuracy']<=655.35 or not 0<=result['speed']<=1000 or not 0<=result['bearing']<=360 or not -12000<=result['altitude']<=100000:raise ValueError('Invalid location measurements')
    if not now-86400<=result['last_update']<=now+300:raise ValueError('Location time is invalid or too old')
    return result

MOVING_UPDATE_SECONDS = 60
STOPPED_UPDATE_SECONDS = 300
MOVING_SAMPLE_MS = 30_000
STOPPED_SAMPLE_MS = 90_000


def location_moved(previous, current):
    """Treat a displacement as movement only when it exceeds GPS uncertainty."""
    lat_a, lat_b = map(math.radians, (previous['latitude'], current['latitude']))
    delta_lon = math.radians(current['longitude'] - previous['longitude'])
    arc = math.sin((lat_b - lat_a) / 2)**2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2)**2
    metres = 12_742_000 * math.asin(math.sqrt(max(0, min(1, arc))))
    return metres >= max(50, previous['accuracy'] + current['accuracy'])


class FamilyLocation:
    def __init__(self,state,lock,save,cancel):
        self.state=state;self.lock=lock;self.save=save;self.cancel=cancel;self.fix=None;self.error='';self.generation=0;self.sent={};self.receive_count=0;self.receive_status='No approved telemetry received'
        self.motion_anchor = None
        self.stationary = False
        state.setdefault('location_policy',{'mapEnabled':True,'userControls':False,'recipients':[],'until':0})
        state.setdefault('locations',{})
    def approved(self):
        result={};owner=(self.state.get('meshcore') or {}).get('publicKey','')
        for c in self.state['contacts']:
            addresses=c.get('addresses',{})
            if addresses.get('lxmf'):result[addresses['lxmf']]=c
            if addresses.get('meshcore') and len(owner)==64:result['meshcore:'+owner+':'+addresses['meshcore']]=c
        return result
    def mesh_peer(self,peer,owner):return 'meshcore:'+owner+':'+peer

    def allowed(self):
        return set(self.state['location_policy']['recipients'])&self.approved().keys()
    def active(self,now=None):
        now=time.time() if now is None else now;p=self.state['location_policy']
        return bool(p['mapEnabled'] and self.allowed() and (p['until']==-1 or p['until']>now))
    def stop(self):
        with self.lock:
            policy = self.state['location_policy']
            policy['until'] = 0
            policy.pop('duration', None)
            self.fix = None
            self.motion_anchor = None
            self.stationary = False
            self.generation+=1;self.sent={};self.cancel();self.save()
    def suspend_samples(self):
        with self.lock:
            self.fix = None
            self.motion_anchor = None
            self.stationary = False
            self.generation += 1
            self.cancel()

    def configure(self,payload):
        map_enabled=payload.get('mapEnabled');user_controls=payload.get('userControls');ids=payload.get('contactIds')
        if not isinstance(map_enabled,bool) or not isinstance(user_controls,bool) or not isinstance(ids,list):raise ValueError('Invalid location policy')
        contacts={c['id']:c for c in self.state['contacts']}
        if any(type(cid) is not int or cid not in contacts or cid not in {c['id'] for c in self.approved().values()} for cid in ids):raise ValueError('Choose contacts with an approved Reticulum or configured MeshCore address')
        with self.lock:
            p=self.state['location_policy'];p.update(mapEnabled=map_enabled,userControls=user_controls,recipients=[peer for peer,c in self.approved().items() if c['id'] in ids])
            self.generation+=1;self.cancel();self.sent={}
            self.state['locations']={peer:fix for peer,fix in self.state['locations'].items() if peer in self.allowed() and map_enabled}
            if not map_enabled or not self.allowed():
                p['until'] = 0
                p.pop('duration', None)
                self.fix = None
                self.motion_anchor = None
                self.stationary = False
            self.save()
    def start(self,duration,guardian):
        if not guardian and not self.state['location_policy']['userControls']:raise ValueError('Location sharing is managed by your guardian')
        if duration not in ['15','60','ongoing'] or (duration=='ongoing' and not guardian):raise ValueError('Choose an allowed sharing duration')
        with self.lock:
            p=self.state['location_policy']
            if not p['mapEnabled'] or not self.allowed():raise ValueError('A guardian must approve location contacts first')
            self.generation+=1;self.cancel();self.sent={}
            p['until'] = -1 if duration == 'ongoing' else time.time() + int(duration) * 60
            p['duration'] = duration
            self.motion_anchor = None
            self.stationary = False
            self.error='';self.save()
    def permissions(self,guardian):return guardian or self.state['location_policy']['userControls']
    def reconcile(self):
        with self.lock:
            self.state['location_policy']['recipients']=[peer for peer in self.state['location_policy']['recipients'] if peer in self.approved()]
            allowed=self.allowed();self.state['locations']={peer:fix for peer,fix in self.state['locations'].items() if peer in allowed}
            if not self.active() and self.state['location_policy']['until']!=0:self.stop()
            self.generation+=1;self.cancel();self.save()
    def record(self, raw):
        with self.lock:
            if not self.active():
                return MOVING_SAMPLE_MS
            now = time.time()
            fix = valid_fix(raw, now)
            if fix['last_update'] < now - 120 or (self.fix and fix['last_update'] <= self.fix['last_update']):
                return STOPPED_SAMPLE_MS if self.stationary else MOVING_SAMPLE_MS
            self.fix = fix
            self.error = ''
            # Coarse fixes are useful to share, but are not proof that a phone is stationary.
            if 0 < fix['accuracy'] <= 60:
                anchor = self.motion_anchor
                if anchor is None or fix['speed'] >= 1 or location_moved(anchor, fix):
                    self.motion_anchor = fix
                    self.stationary = False
                elif fix['last_update'] - anchor['last_update'] >= MOVING_UPDATE_SECONDS:
                    self.stationary = True
            return STOPPED_SAMPLE_MS if self.stationary else MOVING_SAMPLE_MS
    def receive(self,peer,packed):
        with self.lock:
            self.receive_count+=1
            if not self.state['location_policy']['mapEnabled'] or peer not in self.allowed():self.receive_status='Location permission not granted';return
            if not isinstance(packed,(bytes,bytearray)) or len(packed)>8192:self.receive_status='Invalid telemetry bytes';return
            packed=bytes(packed)
            decoded=Telemeter.from_packed(packed)
            if not decoded or not decoded.get('location'):self.receive_status='No valid location in telemetry';return
            try:fix=valid_fix(decoded['location'])
            except ValueError as exc:self.receive_status=str(exc);return
            self.receive_fix(peer,fix,'reticulum')
    def receive_fix(self,peer,fix,service):
        with self.lock:
            if not self.state['location_policy']['mapEnabled'] or peer not in self.allowed():return False
            fix=valid_fix(fix)
            previous=self.state['locations'].get(peer)
            if previous and previous['last_update']>=fix['last_update']:return False
            self.state['locations'][peer]=dict(fix,service=service);self.receive_status='Approved private location received';self.save();return True
    def tick(self,online,send):
        with self.lock:
            if not self.active():
                if self.state['location_policy']['until']!=0:self.stop()
                return
            if not online or not self.fix or self.fix['last_update']<time.time()-120:return
            availability=online if isinstance(online,dict) else {'reticulum':online}
            selected={}
            for peer in sorted(self.allowed(),key=lambda p:p.startswith('meshcore:')):
                service='meshcore' if peer.startswith('meshcore:') else 'reticulum'
                cid=self.approved()[peer]['id']
                if availability.get(service) and cid not in selected:selected[cid]=peer
            now = time.monotonic()
            for cid, peer in selected.items():
                previous = self.sent.get(cid)
                if previous:
                    sent_at, sent_fix = previous
                    elapsed = now - sent_at
                    if elapsed < MOVING_UPDATE_SECONDS:
                        continue
                    if elapsed < STOPPED_UPDATE_SECONDS and not location_moved(sent_fix, self.fix):
                        continue
                self.sent[cid] = (now, self.fix)
                send(peer, dict(self.fix), self.generation)
    def can_send(self,peer,generation):return self.active() and peer in self.allowed() and generation==self.generation
    def snapshot(self):
        with self.lock:
            p=self.state['location_policy'];allowed=self.allowed()
            active = self.active()
            duration = None
            if active:
                duration = 'ongoing' if p['until'] == -1 else p.get('duration')
            return {'mapEnabled':p['mapEnabled'],'userControls':p['userControls'],'active':active,'until':p['until'],'duration':duration,
                    'contactIds':sorted({c['id'] for peer,c in self.approved().items() if peer in allowed}),
                    'locations':{str(c['id']):self.state['locations'][peer] for peer,c in sorted(self.approved().items(),key=lambda item:self.state['locations'].get(item[0],{}).get('last_update',0)) if peer in allowed and peer in self.state['locations'] and p['mapEnabled']},
                    'receiveCount':self.receive_count,'receiveStatus':self.receive_status,'error':self.error,'hasFreshFix':bool(self.fix and self.fix['last_update']>=time.time()-120)}
