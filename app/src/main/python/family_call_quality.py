"""Conservative next-call selection; unknown quality is never presented as measured."""
import math,time

def finite(value,maximum):
 try:
  value=float(value)
  return value if math.isfinite(value) and 0<=value<=maximum else None
 except (TypeError,ValueError):return None

def rank(contact,sip,reticulum,history,now=None):
 now=time.time() if now is None else now
 result=[]
 for service,key,runtime in [('sip','sip',sip),('reticulum','lxst',reticulum)]:
  target=contact.get('addresses',{}).get(key,'')
  if not target or not runtime.get('available'):continue
  automatic=runtime.get('automatic',True);context=runtime.get('context','')
  samples=[row for row in history if isinstance(row,dict) and finite(row.get('timestamp'),now) is not None and row.get('service')==service and row.get('target')==target and row.get('context')==context and 0<=now-float(row.get('timestamp',0))<86400]
  weighted=total=0.;failures=[]
  for row in samples[-32:]:
   age=now-float(row['timestamp']);weight=math.exp(-age/21600)
   if row.get('failed'):
    failures.append(age);score=25.
   else:
    score=75.;metrics=row.get('metrics',{});metrics=metrics if isinstance(metrics,dict) else {}
    rtt=finite(metrics.get('rtt_ms'),60000);jitter=finite(metrics.get('jitter_ms'),10000);loss=finite(metrics.get('loss_pct'),100)
    if any(v is not None for v in [rtt,jitter,loss]):
     score=100.-(rtt or 0)/25.-(jitter or 0)/4.-(loss or 0)*8.
    score=max(0,min(100,score))
   weighted+=score*weight;total+=weight
  score=weighted/total if total else 70.
  reason='No recent call measurements'
  if samples:reason='Based on recent calls'
  if any(age<300 for age in failures):score-=25;reason='Recent connection failure'
  if not automatic:score=-1;reason=runtime.get('reason','This connection is too slow for automatic calling')
  result.append({'service':service,'automatic':automatic,'reason':reason,'measured':bool(samples),'score':round(max(-1,score),1)})
 result.sort(key=lambda row:(row['automatic'],row['score'],row['service']=='sip'),reverse=True)
 return result
