"""Create a clean disposable UI simulator matching the native-test target."""
import json
import re
import subprocess
import sys
import uuid


def descriptor(inventory, source_id, family):
    if family not in ('iPhone', 'iPad'): raise ValueError('Choose a supported simulator family')
    uuid.UUID(source_id)
    matches=[]
    for runtime, devices in inventory.get('devices',{}).items():
        for device in devices:
            if device.get('udid')==source_id: matches.append((runtime,device))
    if len(matches)!=1: raise ValueError('The selected simulator must exist exactly once')
    runtime,device=matches[0]
    if not re.fullmatch(r'com\.apple\.CoreSimulator\.SimRuntime\.iOS-\d+(?:-\d+)*',runtime):
        raise ValueError('The selected target must use iOS')
    if int(runtime.split('iOS-')[1].split('-')[0])<17: raise ValueError('iOS 17 or newer is required')
    kind=device.get('deviceTypeIdentifier','')
    if (device.get('isAvailable') is not True or not device.get('name','').startswith(family+' ')
            or not re.fullmatch(r'com\.apple\.CoreSimulator\.SimDeviceType\.[A-Za-z0-9-]+',kind)):
        raise ValueError('The selected target must have its available device type recorded')
    return kind,runtime


def main(source_id,family):
    inventory=json.loads(subprocess.check_output(['xcrun','simctl','list','devices','available','--json'],text=True))
    kind,runtime=descriptor(inventory,source_id,family)
    name='neXt-UI-'+family+'-'+uuid.uuid4().hex[:12]
    created=subprocess.check_output(['xcrun','simctl','create',name,kind,runtime],text=True).strip()
    uuid.UUID(created)
    if created==source_id: raise RuntimeError('UI tests require a new disposable simulator')
    print(created)


if __name__=='__main__':main(*sys.argv[1:])
