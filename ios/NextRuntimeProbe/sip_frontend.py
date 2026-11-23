"""Verify the native iOS SIP platform already present in the pinned 0.1.27 bundle.

The upstream SIP feature synchronization includes iOS, and commands carry the
displayed call ID so delayed controls cannot end a replacement call. Preserve
those exact protections without applying the former backport a second time.
"""
from pathlib import Path
import hashlib
import re

CHUNK = 'assets/shared-async-_cCrMhk8.js'
SOURCE_SHA256 = '8140d1e928c9be0663968b0aa62017f4e4b3ed40d85d1d6a2488c74d9ac49e52'
# Whole source bytes are already covered by the pinned frontend ZIP checksum;
# the small exact expressions additionally fail closed when that bundle changes.
PLATFORM = re.compile(r'\["linux","windows","ios"\]\.includes\((?:ws|e)\.platform\)')
COMMAND = 'a.post(Gt("/sip/command"),{...t,...n,op:e})'
CALL_GUARD = 'const n="ios"===ws.platform&&["answer","hangup","mute","hold","dtmf","speaker"].includes(e)?{call_id:ws.call_id}:{}'


def rewrite(source):
    if len(PLATFORM.findall(source)) != 4 or source.count(COMMAND) != 1 or source.count(CALL_GUARD) != 1:
        raise ValueError('The pinned native SIP frontend changed; review its call protections')
    for marker in ['Could not update SIP feature settings', '/sip/status', 'SIP calling is unavailable in this build']:
        if source.count(marker) != 1:
            raise ValueError('The pinned SIP module no longer has the expected boundaries')
    # These protections are now upstream. Verify them rather than apply the old backport twice.
    return source


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
            'ios_platform_checks': 4, 'call_identity_guard': True, 'already_upstream': True}


if __name__ == '__main__':
    import json,sys
    print(json.dumps(stage(Path(sys.argv[1]))))
