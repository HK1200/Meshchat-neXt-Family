"""Choose before submission using current availability and recent delivery evidence."""
import math,time

def choices(contact, messages, available, owner='', now=None, text=None):
    now=time.time() if now is None else now
    result=[]
    for service,key in [('reticulum','lxmf'),('meshcore','meshcore')]:
        peer=contact.get('addresses',{}).get(key,'').lower()
        if not peer or not available.get(service):continue
        if service=='meshcore' and text is not None and len(text.encode('utf-8'))>160:continue
        successes=failures=0.;last_success=0.;last_failure=0.
        for row in messages:
            if row.get('incoming'):continue
            attempt=row if row.get('service','reticulum')==service else row.get('fallbackFrom',{})
            if attempt.get('peer','').lower()!=peer:continue
            if service=='meshcore' and attempt.get('owner','')!=owner:continue
            age=max(0,now-row.get('timestamp',0))
            if age>7*86400:continue
            weight=math.exp(-age/86400)
            status=attempt.get('status','')
            if status.startswith('Delivered'):
                successes+=weight;last_success=max(last_success,row.get('timestamp',0))
            elif status.startswith(('Failed','Not confirmed')):
                failures+=weight;last_failure=max(last_failure,row.get('timestamp',0))
        score=(2+successes)/(3+successes+failures)
        # A fresh failure matters more than old successes.
        if last_failure>last_success and now-last_failure<300:score-=.35
        reason='Available · no recent delivery evidence'
        if successes or failures:reason='Recent delivery confirmations' if last_success>=last_failure else 'Recent delivery failure'
        result.append({'service':service,'reason':reason,'_score':score+(0.01 if service=='reticulum' else 0)})
    result.sort(key=lambda route:route['_score'],reverse=True)
    return [{k:v for k,v in route.items() if k!='_score'} for route in result]
