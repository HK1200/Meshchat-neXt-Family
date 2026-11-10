"""Guardian-configured RNode interfaces; Android USB and RNode-over-IP."""
import json,re,threading
from decimal import Decimal
_context=None

def set_context(context):
    global _context
    _context=context
    from usb4a import usb
    usb.set_context(context)
    from java import jclass
    jclass("org.able.BLE").setAppContext(context)

def usb_devices():
    from usb4a import usb
    manager=usb.get_usb_manager()
    return [{'path':str(d.getDeviceName()),'name':str(d.getProductName() or 'USB serial device'),
             'vendor':int(d.getVendorId()),'product':int(d.getProductId()),'permission':bool(manager.hasPermission(d))}
            for d in usb.get_usb_device_list()]

def bluetooth(action,address=None):
    from java import jclass
    helper=jclass('org.meshchat.family.preview.RadioBluetooth')
    if action=='scan':return json.loads(str(helper.scan(_context)))
    if action=='pair':return bool(helper.pair(_context,address))
    return json.loads(str(helper.snapshot()))

def frequency_hz(raw):
    """Normalize radio profile frequencies from MHz, kHz, or Hz."""
    error='Enter an RNode frequency from 137 to 1020 MHz, for example 914.875 MHz or 914875000 Hz.'
    text=str(raw).strip()
    if len(text)>32:raise ValueError(error)
    match=re.fullmatch(r'([0-9]+(?:[.,][0-9]+)*)\s*(mhz|khz|hz)?',text,re.I)
    if not match:raise ValueError(error)
    value,unit=match.groups()
    unit=unit.lower() if unit else None
    if re.fullmatch(r'[0-9]{1,3}(?:,[0-9]{3})+',value) and (value.count(',')>1 or unit in ['khz','hz']):
        value=value.replace(',','')
    elif re.fullmatch(r'[0-9]+[.,][0-9]+',value):
        value=value.replace(',','.')
    elif not value.isascii() or not value.isdigit():
        raise ValueError(error)
    amount=Decimal(value)
    scales={'mhz':1000000,'khz':1000,'hz':1}
    for scale in (scales[unit],) if unit else scales.values():
        hz=amount*scale
        if 137000000<=hz<=1020000000 and hz==hz.to_integral_value():return int(hz)
    raise ValueError(error)

def validate(raw):
    if not isinstance(raw,dict):raise ValueError('Invalid RNode settings')
    enabled=raw.get('enabled',False)
    if not isinstance(enabled,bool):raise ValueError('Invalid enable setting')
    transport=raw.get('transport','usb');endpoint=str(raw.get('endpoint','')).strip()
    if transport not in ['usb','tcp','ble','classic']:raise ValueError('Choose USB, Bluetooth or Wi-Fi RNode')
    if transport=='usb':
        if not re.fullmatch(r'/dev/bus/usb/\d{3}/\d{3}',endpoint):raise ValueError('Choose a detected USB device')
    elif transport in ['ble','classic']:
        if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',endpoint):raise ValueError('Select the Bluetooth RNode address')
    elif not re.fullmatch(r'[A-Za-z0-9.-]{1,253}',endpoint):raise ValueError('Enter the RNode hostname or IPv4 address without a port')
    def number(key,low,high,scale=1):
        value=float(raw.get(key,''))*scale
        if not low<=value<=high or not value.is_integer():raise ValueError('Invalid '+key)
        return int(value)
    return dict(enabled=enabled,transport=transport,endpoint=endpoint,
        frequency=frequency_hz(raw.get('frequency','')),
        bandwidth=number('bandwidth',7800,500000,1000),sf=number('sf',5,12),
        cr=number('cr',5,8),power=number('power',0,30))

def exact_devices(devices,address):
    return [d for d in devices if str(d.getAddress()).lower()==str(address).lower()]

def public(config):
    if not config:return None
    return dict(config,frequency=config['frequency']/1000000,bandwidth=config['bandwidth']/1000)

def prepare_ble(module):
    # Bonded-device security/service setup can exceed the upstream seven-second
    # window. Do not repeatedly abort an in-progress Android GATT connection.
    module.BLEConnection.CONNECT_TIMEOUT=30.0
    module.BLEConnection.RECONNECT_WAIT=5.0
    if not getattr(module.BLEConnection,'_family_exact_target',False):
        original=module.BLEConnection.find_target_devices
        def exact(connection):
            devices=original(connection)
            return exact_devices(devices,connection.target_bt_addr) if connection.target_bt_addr else devices
        module.BLEConnection.find_target_devices=exact
        module.BLEConnection._family_exact_target=True
    if not getattr(module.BLEConnection,'_family_lifecycle_safe',False):
        original_address=getattr(module.BLEConnection,'connect_by_device_address',None)
        original_cleanup=getattr(module.BLEConnection,'cleanup',None)
        original_connect=getattr(module.BLEConnection,'connect_device',None)
        if original_address:
            def connect_address(connection,address,autoconnect=True):
                if not connection.should_run:return
                return original_address(connection,address,autoconnect)
            module.BLEConnection.connect_by_device_address=connect_address
        if original_cleanup:
            def cleanup(connection):
                connection.should_run=False
                try:connection.close_gatt()
                finally:
                    connection.connected=False;connection.rx_char=None;connection.tx_char=None
                    original_cleanup(connection)
            module.BLEConnection.cleanup=cleanup
        if original_connect:
            def connect_device(connection):
                if not connection.should_run:return
                try:return original_connect(connection)
                finally:
                    if not connection.should_run:
                        connection.close_gatt();connection.connected=False;connection.rx_char=None;connection.tx_char=None
            module.BLEConnection.connect_device=connect_device
        module.BLEConnection._family_lifecycle_safe=True

class Radio:
    def __init__(self,reticulum,on_ready=None,on_retire=None):
        self.reticulum=reticulum;self.interface=None;self.error='';self.config=None;self.applied=None;self.on_ready=on_ready;self.on_retire=on_retire
        self._last_ready=None
        self._lock=threading.RLock();self._pending=threading.Event()
        threading.Thread(target=self._worker,daemon=True).start()
        threading.Thread(target=self._monitor,daemon=True).start()
    def _monitor(self):
        import time
        while True:
            time.sleep(1)
            with self._lock:
                interface=self.interface
                ready=bool(self.config and self.config['enabled'] and self.config==self.applied and interface and interface.online)
                notify=ready and interface is not self._last_ready
                self._last_ready=interface if ready else None
            if notify and self.on_ready:
                try:self.on_ready()
                except Exception:pass
    def configure(self,config):
        with self._lock:self.config=dict(config) if config else None
        self._pending.set()
    def _worker(self):
        while True:
            self._pending.wait();self._pending.clear()
            with self._lock:config=dict(self.config) if self.config else None;old=self.interface;self.interface=None;self.error=''
            try:
                import RNS
                if old:
                    if self.on_retire:self.on_retire(old)
                    old.detach()
                    if old in RNS.Transport.interfaces:RNS.Transport.interfaces.remove(old)
                if not config or not config['enabled']:continue
                from RNS.Interfaces.Android import RNodeInterface as module
                RNodeInterface=module.RNodeInterface
                # A new radio session needs its own battery report.
                if not getattr(RNodeInterface, '_family_resets_battery', False):
                    reset = RNodeInterface.resetRadioState
                    def reset_with_battery(interface, original=reset):
                        interface.r_battery_state = interface.BATTERY_STATE_UNKNOWN
                        interface.r_battery_percent = 0
                        return original(interface)
                    RNodeInterface.resetRadioState = reset_with_battery
                    RNodeInterface._family_resets_battery = True
                # Never fall back to another paired radio.
                prepare_ble(module)
                args={'name':'Family RNode','frequency':config['frequency'],'bandwidth':config['bandwidth'],
                      'txpower':config['power'],'spreadingfactor':config['sf'],'codingrate':config['cr'],'flow_control':False}
                if config['transport']=='tcp':args.update(tcp_host=config['endpoint'],force_tcp=True)
                elif config['transport']=='ble':args.update(ble_addr=config['endpoint'],force_ble=True)
                elif config['transport']=='classic':args.update(allow_bluetooth=True,target_device_address=config['endpoint'])
                else:
                    from usb4a import usb
                    device=usb.get_usb_device(config['endpoint'])
                    if not device:raise ValueError('USB radio is not attached. Reconnect it and save its settings.')
                    if not usb.has_usb_permission(device):
                        usb.request_usb_permission(device)
                        raise ValueError('Allow Android USB access, then save the RNode settings again.')
                    args['port']=config['endpoint']
                interface=RNodeInterface(RNS.Transport,args)
                if config['transport']=='ble':
                    from family_radio_pacing import install
                    install(interface)
                self.reticulum._add_interface(interface)
                with self._lock:self.interface=interface;self.applied=config
            except Exception as exc:
                with self._lock:self.error=str(exc)
    def snapshot(self):
        with self._lock:
            interface=self.interface;enabled=bool(self.config and self.config['enabled']);current=getattr(self,'applied',self.config)==self.config
            online = bool(enabled and current and interface and interface.online)
            battery = None
            if online and hasattr(interface, 'get_battery_state_string'):
                state = interface.get_battery_state_string()
                percent = interface.get_battery_percent()
                if state in ('charging', 'charged', 'discharging') and type(percent) in (int, float) and 0 <= percent <= 100:
                    battery = {'percent': percent, 'state': state}
            return {'online':online,'battery':battery,'error':self.error or ('; '.join(str(e.get('description','Radio error')) for e in getattr(interface,'hw_errors',[])) if enabled and interface else '') or (getattr(getattr(interface,'ble',None),'last_error','') if enabled and interface and not interface.online else ''),
                    'connecting':bool(enabled and not self.error and (not interface or not interface.online)),
                    'reported':({k:getattr(interface,attribute,None) for k,attribute in [('frequencyHz','r_frequency'),('bandwidthHz','r_bandwidth'),('powerDbm','r_txpower'),('sf','r_sf'),('cr','r_cr')]} if interface else None),
                    'readyToTransmit':getattr(interface,'interface_ready',False) if interface else False,
                    'queuedPackets':getattr(interface,'_family_pacer').pending() if interface and hasattr(interface,'_family_pacer') else len(getattr(interface,'packet_queue',[])) if interface else 0,
                    'txBytes':getattr(interface,'txb',0) if interface else 0,'rxBytes':getattr(interface,'rxb',0) if interface else 0}
