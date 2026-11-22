"""Verified Reticulum telemetry for the released map and location controls."""
import base64
import math
import re
import time
from pathlib import Path

import LXMF

MAX_PACKED = 65536


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid telemetry value')
    return value


def validated(raw, *, now=None):
    from meshchatnext.src.backend.telemetry_utils import Telemeter
    now = time.time() if now is None else now
    if not isinstance(raw, dict) or set(raw) - {'time', 'location', 'battery', 'physical_link'}:
        raise ValueError('Unsupported telemetry fields')
    stamp = raw.get('time', {}).get('utc', now) if isinstance(raw.get('time', {}), dict) else None
    stamp = number(stamp, now - 30*86400, now + 300)
    values = {}
    if 'location' in raw:
        from family_location import valid_fix
        fix = raw['location']
        if not isinstance(fix, dict) or set(fix) - {'latitude','longitude','altitude','accuracy','speed','bearing','last_update'}:
            raise ValueError('Invalid location fields')
        values['location'] = valid_fix(fix, now=now)
    if 'battery' in raw:
        battery = raw['battery']
        if not isinstance(battery, dict) or set(battery) != {'charge_percent','charging'} or type(battery['charging']) is not bool:
            raise ValueError('Invalid battery telemetry')
        values['battery'] = dict(charge_percent=number(battery['charge_percent'],0,100), charging=battery['charging'])
    if 'physical_link' in raw:
        link = raw['physical_link']
        if not isinstance(link, dict) or set(link) != {'rssi','snr','q'}:
            raise ValueError('Invalid link telemetry')
        values['physical_link'] = {key: None if link[key] is None else number(link[key], *limits)
            for key,limits in {'rssi':(-200,20),'snr':(-100,100),'q':(0,100)}.items()}
    if not values:
        raise ValueError('Choose location or sensor information to send')
    packed = Telemeter.pack(time_utc=stamp, **values)
    return packed, Telemeter.from_packed(packed)


def outbound(fields):
    """Remove only the supported telemetry field; attachments retain their policy."""
    if not isinstance(fields, dict):
        raise ValueError('Invalid message fields')
    attachments = dict(fields)
    raw = attachments.pop('telemetry', None)
    if raw is None:
        return attachments, {}
    packed, clean = validated(raw)
    if clean.get('location') and clean['location']['last_update'] < time.time()-120:
        raise ValueError('Get a fresh location before sending')
    return attachments, {LXMF.FIELD_TELEMETRY: packed}


def incoming_fields(fields):
    """Bound transport data before moving it onto the app's inbox loop."""
    result = []
    if not isinstance(fields, dict): return result
    raw = fields.get(LXMF.FIELD_TELEMETRY)
    if isinstance(raw, bytes) and 0 < len(raw) <= MAX_PACKED:
        result.append({'data':base64.b64encode(raw).decode('ascii')})
    stream = fields.get(LXMF.FIELD_TELEMETRY_STREAM)
    if isinstance(stream, (list, tuple)):
        for entry in stream[:64]:
            if not isinstance(entry,(list,tuple)) or len(entry) != 3: continue
            address, stamp, raw = entry
            if isinstance(address,bytes) and len(address)==16: address=address.hex()
            if not isinstance(address,str) or not re.fullmatch('[a-f0-9]{32}',address): continue
            try: number(stamp,0,9_000_000_000)
            except ValueError: continue
            if isinstance(raw,bytes) and 0 < len(raw) <= MAX_PACKED:
                result.append({'source':address,'timestamp':stamp,'data':base64.b64encode(raw).decode('ascii')})
    return result


class TelemetryRuntime:
    def __init__(self, folder, own, broadcast):
        from meshchatnext.src.backend.database import Database
        directory=Path(folder)/'location-data';directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.database=Database(str(directory/'state.sqlite3'));self.database.initialize()
        from meshchatnext.src.backend.config_manager import ConfigManager
        self.config=ConfigManager(self.database)
        self.own=own;self.broadcast=broadcast
        self.generation=0
        self.location_keys={'location_source','location_manual_lat','location_manual_lon','location_manual_alt'}

    def settings(self):
        return {key:getattr(self.config,key).get() for key in self.location_keys}

    def configure(self,payload):
        if not isinstance(payload,dict) or not payload or set(payload)-self.location_keys:
            raise ValueError('Choose supported location settings')
        for key,value in payload.items():
            if key=='location_source':
                if value not in ('disabled','browser','manual'):
                    raise ValueError('Choose Disabled, Browser GPS or Manual location on iOS')
            else:
                if not isinstance(value,str) or len(value)>32:raise ValueError('Enter a valid coordinate')
                bounds={'location_manual_lat':(-90,90),'location_manual_lon':(-180,180),'location_manual_alt':(-12000,100000)}[key]
                try:number(float(value),*bounds)
                except (ValueError,OverflowError):raise ValueError('Enter a valid coordinate') from None
        changed=any(getattr(self.config,key).get()!=value for key,value in payload.items())
        with self.database.provider:
            for key,value in payload.items():getattr(self.config,key).set(value)
        if changed:self.generation+=1
        return self.settings()

    def receive(self, row):
        """Called only after signature verification and current inbox policy."""
        from meshchatnext.src.backend.telemetry_utils import Telemeter
        source=row['source_hash']
        if not re.fullmatch('[a-f0-9]{32}',source) or source==self.own:return
        entries=list(row.get('_telemetry_data') or [])[:65]
        if str(row.get('content','')).startswith('!NFLOC1:'):
            from family_meshcore_location import decode
            try:
                fix=decode(row['content']);packed,_=validated({'location':fix})
                entries.append({'data':base64.b64encode(packed).decode('ascii')})
            except ValueError: pass
        last = None
        for entry in entries:
            # A signed stream does not authorize the sender to impersonate
            # another device's position. Cross-peer forwarding needs a future
            # explicit trust control, not an automatically approved contact.
            if not isinstance(entry,dict) or entry.get('source',source)!=source:continue
            try:
                encoded=entry['data']
                if not isinstance(encoded,str) or len(encoded)>((MAX_PACKED+2)//3)*4:continue
                raw=base64.b64decode(encoded,validate=True)
                if not raw or len(raw)>MAX_PACKED:continue
                values=Telemeter.from_packed(raw)
                if not values:continue
                if 'timestamp' in entry:values['time']={'utc':entry['timestamp']}
                packed,clean=validated(values)
            except (ValueError,TypeError,KeyError,OverflowError):continue
            # A storage error must reach DurableInbox, which retains the
            # encrypted relay message instead of acknowledging a lost fix.
            with self.database.provider:
                self.database.telemetry.upsert_telemetry(source,clean['time']['utc'],packed,received_from=self.own)
                self.database.telemetry.mark_response_received(source)
            last = clean
            self.broadcast({'type':'lxmf.telemetry','destination_hash':source,
                'timestamp':clean['time']['utc'],'telemetry':clean,'physical_link':None,
                'is_tracking':self.database.telemetry.is_tracking(source)})

        return last

    def register(self, router):
        from aiohttp import web
        from meshchatnext.src.backend.http.routes.telemetry import register_telemetry_routes
        routes=web.RouteTableDef();register_telemetry_routes(routes,self);router.add_routes(routes)

    def close(self):
        self.database.provider.close_all()
