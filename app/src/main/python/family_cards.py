"""Offline contact/room cards. Parsing never approves or joins anything."""
import json,re
from urllib.parse import parse_qs, urlsplit

def validate_public_key(address,key):
    import RNS
    if not isinstance(key,str) or not re.fullmatch('[a-fA-F0-9]{128}',key):raise ValueError('Invalid identity public key')
    identity=RNS.Identity(create_keys=False);identity.load_public_key(bytes.fromhex(key))
    if RNS.Destination.hash_from_name_and_identity('lxmf.delivery',identity).hex()!=address.lower():raise ValueError('Public key does not match this LXMF address')
    return key.lower()

def parse(raw,target='contact'):
    if not isinstance(raw,str) or not 0<len(raw.strip())<=8192:raise ValueError('Use a code of up to 8 KB')
    text=raw.strip()
    if target=='room':
        try:data=json.loads(text)
        except Exception:raise ValueError('Use a neXt Family room card')
        if not isinstance(data,dict) or data.get('format')!='next-family-room' or data.get('version')!=1 or data.get('service') not in ['reticulum','meshcore']:raise ValueError('Unsupported room card')
        key=data.get('hubHash') if data['service']=='reticulum' else data.get('publicKey')
        length=32 if data['service']=='reticulum' else 64
        if not isinstance(key,str) or not re.fullmatch('[a-fA-F0-9]{%s}'%length,key):raise ValueError('Invalid room server address')
        channel=data.get('room','')
        if data['service']=='reticulum' and (not isinstance(channel,str) or not channel.strip() or len(channel.encode())>64 or any(ord(c)<32 for c in channel)):raise ValueError('Invalid Relay Chat room name')
        return dict(name=str(data.get('name',''))[:32],service=data['service'],channel=channel,key=key.lower())
    if re.fullmatch('[a-fA-F0-9]{32}',text):return {'addresses':{'lxmf':text.lower()}}
    if re.fullmatch('[a-fA-F0-9]{64}',text):return {'addresses':{'meshcore':text.lower()}}
    match=re.fullmatch(r'lxma://([a-fA-F0-9]{32}):([a-fA-F0-9]{128})',text,re.I)
    if match:
        address,key=match.groups();return {'addresses':{'lxmf':address.lower()},'identityPublicKey':validate_public_key(address,key)}
    match=re.fullmatch(r'lxmf://([a-fA-F0-9]{32})',text,re.I)
    if match:return {'addresses':{'lxmf':match[1].lower()}}
    if text.startswith('{'):
        data=json.loads(text)
        if data.get('format')!='next-family-contact' or data.get('version')!=1:raise ValueError('Unsupported contact card')
        addresses=data.get('addresses')
        if not isinstance(addresses,dict) or not any(addresses.values()):raise ValueError('Contact has no addresses')
        result={'name':str(data.get('name',''))[:32],'addresses':addresses}
        if data.get('identityPublicKey'):result['identityPublicKey']=validate_public_key(addresses.get('lxmf',''),data['identityPublicKey'])
        return result
    if text.lower().startswith('meshcore://contact/add?'):
        params=parse_qs(urlsplit(text).query,max_num_fields=16)
        keys=params.get('public_key',[])
        if params.get('type')!=['1']:
            raise ValueError('Use a MeshCore companion contact code for direct messages.')
        if len(keys)!=1 or not re.fullmatch(r'[a-fA-F0-9]{64}',keys[0]):
            raise ValueError('The QR code must contain a full MeshCore public key.')
        return {'name':params.get('name',[''])[0][:32],'addresses':{'meshcore':keys[0].lower()}}
    if re.fullmatch(r'meshcore://[a-fA-F0-9]{64}',text,re.I):return {'addresses':{'meshcore':text[11:].lower()}}
    if re.fullmatch(r'sips?:[^\s@]+@[^\s@]+',text,re.I):return {'addresses':{'sip':text}}
    raise ValueError('Unsupported QR code. Use a neXt contact QR or family contact/room card.')
