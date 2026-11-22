# SPDX-License-Identifier: 0BSD
"""Explain the mobile RNSh contract on the checksum-pinned released page."""
import hashlib
from pathlib import Path

CHUNK = 'assets/RNSHManagerPage-lLPkRtCV.js'
SHA256 = '7bf77a34eae1fb0b208d14ec87a036f211c1d6039115bb4f6ace0ba7d223c200'
BEFORE = 'return C(),F("div",L,['
NOTICE = ('Connect to remote RNSh hosts using this app’s identity and interfaces. '
          'Sessions run while neXt is active. Hosting a local shell requires desktop neXt. '
          'Saved sessions do not run commands again until you press Start.')


def rewrite(source):
    if source.count(BEFORE) != 1:
        raise ValueError('The pinned terminal page changed; review its mobile guidance')
    import json
    after = BEFORE + 'v("p",{class:"px-3 py-2 text-sm text-sem-fg-muted border-b border-sem-border",role:"note"},' + json.dumps(NOTICE) + '),'
    return source.replace(BEFORE, after)


def stage(folder):
    path = Path(folder) / CHUNK
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('The pinned terminal frontend checksum changed')
    path.write_text(rewrite(data.decode()))


if __name__ == '__main__':
    import sys
    stage(sys.argv[1])
