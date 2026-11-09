"""Room-scoped visual labels. Never modifies contact or location approval."""
import json,re
class RoomNames:
 def __init__(self,state,lock,save):self.state=state;self.lock=lock;self.save=save;state.setdefault('room_names',{})
 def _key(self,room,participant):return json.dumps([room.get('service','reticulum'),room['key'],participant],separators=(',',':'))
 def set(self,room_id,participant,name):
  with self.lock:
   room=next((r for r in self.state.get('rooms',[]) if r['id']==room_id),None)
   if not room:raise ValueError('This room is not approved')
   pattern='[a-f0-9]{8}' if room.get('service','reticulum')=='meshcore' else '[a-f0-9]{32}'
   if not isinstance(participant,str) or not re.fullmatch(pattern,participant):raise ValueError('Invalid room participant identity')
   if not isinstance(name,str) or len(name)>48 or any(ord(c)<32 or ord(c)==127 for c in name):raise ValueError('Use a name of up to 48 characters without control characters')
   label=name.strip();key=self._key(room,participant)
   if label:
    if key not in self.state['room_names'] and len(self.state['room_names'])>=1000:raise ValueError('Participant name limit reached')
    self.state['room_names'][key]=label
   else:self.state['room_names'].pop(key,None)
   self.save()
 def decorate(self,data):
  with self.lock:
   for room in data.get('rooms',[]):
    runtime=data.get('roomRuntime',{}).get(str(room['id']),{});rows=[]
    for original in runtime.get('messages',[]):
     row=dict(original);participant=row.get('participantId') or row.get('src','');pattern='[a-f0-9]{8}' if room.get('service','reticulum')=='meshcore' else '[a-f0-9]{32}'
     if isinstance(participant,str) and re.fullmatch(pattern,participant):
      reported=str(row.get('nick') or participant[:8])[:64];label=self.state['room_names'].get(self._key(room,participant),'');row.update(participantId=participant,reportedName=reported,savedName=label,nick=label or reported)
     rows.append(row)
    runtime['messages']=rows
   return data
