"""Bind only the checksum-pinned Opus preview to bounded native WAV playback."""

import hashlib
from pathlib import Path

CHUNK = "assets/MessagesPage-C8xqqKjq.js"
SHA256 = "5fe1132a0ec4df0d4fcf9839aac4ee8918e9142686524a8c9c33f49f137bda8f"
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
