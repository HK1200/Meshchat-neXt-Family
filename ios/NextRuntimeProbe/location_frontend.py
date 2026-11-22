"""Connect only the reviewed, checksum-pinned chat timer to native GPS sessions."""
import hashlib
from pathlib import Path

CHUNK = 'assets/shared-async-CTgMST9W.js'
# The prior SIP compatibility step verifies this upstream source without rewriting it.
SHA256 = '1ce2c089b8ad7b6c88444fa12f4ac0272f5bead5e9e7afcaa14a7ca96ee0b867'


def rewrite(source, client):
    start = 'function uo(e,t,a){'
    end = 'function mo('
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError('The pinned location controls changed; review the native binding')
    left = source.index(start)
    right = source.index(end, left)
    legacy = source[left:right]
    if not legacy.endswith('}'):
        raise ValueError('Unexpected location function boundary')
    legacy = legacy.replace(start, 'function __nextLegacyLocation(e,t,a){', 1)
    if client.count('export function createNativeLocationClient') != 1:
        raise ValueError('Missing native location client')
    factory = client.replace('export function createNativeLocationClient', 'function __nextCreateNativeLocationClient', 1)
    bridge = '''
const __nextNativeLocations=__nextCreateNativeLocationClient({sessions:co,
 request:async(method,body)=>{const path="/api/v1/preview/location-sessions"+(method==="GET"?"?summary=1":"");const response=await window.api[method.toLowerCase()](path,body);return response.data;},
 report:(message,type)=>nn.emit(Xt.TOAST,{message,type})});
function uo(e,t,a){if(__nextNativeLocations.handles(e,a)){__nextNativeLocations.start(e,t,a);return;}return __nextLegacyLocation(e,t,a);}
'''
    return source[:left] + legacy + factory + bridge + source[right:]


def stage(frontend):
    target = Path(frontend) / CHUNK
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('The pinned location frontend checksum changed')
    client = Path(__file__).with_name('native-location-client.mjs').read_text()
    target.write_text(rewrite(raw.decode(), client))


if __name__ == '__main__':
    import sys
    stage(sys.argv[1])
