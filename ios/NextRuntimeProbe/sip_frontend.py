"""Backport the native iOS SIP platform to the checksum-verified 0.1.21 bundle.

Only the known SIP feature synchronization and network-default expressions are
changed. iOS requests carry the displayed call ID so delayed controls cannot
end a replacement call. This is not an Android bridge or a Linux impersonation.
"""
from pathlib import Path
import hashlib
import re

CHUNK = 'assets/shared-async-Bl2dehMi.js'
SOURCE_SHA256 = '68b6b8390dd8330ed196ae36d1ebffe530a29ae64e6915823839948928debc32'
# Whole source bytes are already covered by the pinned frontend ZIP checksum;
# the small exact expressions additionally fail closed when that bundle changes.
PLATFORM = re.compile(r'\["linux","windows"\]\.includes\((?:ws|e)\.platform\)')
COMMAND = 'a.post(Gt("/sip/command"),{...t,op:e})'
COMMAND_IOS = 'a.post(Gt("/sip/command"),{...t,...("ios"===ws.platform&&["answer","hangup","mute","hold","dtmf","speaker"].includes(e)?{call_id:ws.call_id}:{}),op:e})'


def rewrite(source):
    if len(PLATFORM.findall(source)) != 4 or source.count(COMMAND) != 1:
        raise ValueError('The pinned neXt SIP frontend changed; review the backport')
    for marker in ['Could not update SIP feature settings', '/sip/status', 'SIP calling is unavailable in this build']:
        if source.count(marker) != 1:
            raise ValueError('The pinned SIP module no longer has the expected boundaries')
    changed = PLATFORM.sub(lambda m: m[0].replace('["linux","windows"]', '["linux","windows","ios"]'), source)
    changed = changed.replace(COMMAND, COMMAND_IOS)
    return changed


def stage(frontend):
    path = Path(frontend) / CHUNK
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SOURCE_SHA256:
        raise ValueError("The pinned SIP frontend checksum changed")
    source = payload.decode("utf-8")
    changed = rewrite(source)
    path.write_text(changed, encoding="utf-8")
    return {'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'staged_sha256': hashlib.sha256(changed.encode()).hexdigest(),
            'ios_platform_checks': 4, 'call_identity_guard': True}


if __name__ == '__main__':
    import json,sys
    print(json.dumps(stage(Path(sys.argv[1]))))
