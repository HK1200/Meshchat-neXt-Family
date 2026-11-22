"""Bind only the checksum-pinned Opus preview to bounded native WAV playback."""

import hashlib
from pathlib import Path

CHUNK = "assets/MessagesPage-CsPVgupz.js"
SHA256 = "c36946e8c29de599e8c09814edbd45e8c3beb221251ef16dc349848e00d24bb1"
BEFORE = ',t=ao(t,2097152);const s=new Blob([t],{type:"audio/opus"})'
AFTER = ';const __nextWav=t.length>=12&&t[0]===82&&t[1]===73&&t[2]===70&&t[3]===70&&t[8]===87&&t[9]===65&&t[10]===86&&t[11]===69;t=ao(t,__nextWav?8388652:2097152);const s=new Blob([t],{type:__nextWav?"audio/wav":"audio/ogg"})'


def rewrite(source):
    if source.count(BEFORE) != 1:
        raise ValueError("The pinned voice player changed; review iOS audio playback")
    return source.replace(BEFORE, AFTER)


def stage(frontend):
    path = Path(frontend) / CHUNK
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("The pinned audio frontend checksum changed")
    path.write_text(rewrite(data.decode()))


if __name__ == "__main__":
    import sys

    stage(Path(sys.argv[1]))
