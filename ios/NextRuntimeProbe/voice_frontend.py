"""Bind the pinned neXt call buttons to the call displayed at activation.

These patches are confined to the iOS preview bundle. Capturing before the
first await prevents a microphone prompt or delayed request controlling a
replacement call. The original source checksums are required before changes.
"""
import hashlib
from pathlib import Path

CHUNKS = {
    "app-C1lU8zPZ.js": "f765bef83ae627ba5098121a40855563ef18afce7a48aa9dd80f5e6c5614ef7e",
    "CallPage-kCZk-idq.js": "bc2bea6c00959415d5a7eec8ee0c20b107e4f0614b8b394f5ad5fd324f83c147",
}


def replace_once(source, before, after):
    if source.count(before) != 1: raise ValueError("The pinned telephone controls changed; review the iOS call binding")
    return source.replace(before, after)


def rewrite(source, *, page):
    route = "k" if page else "Te"
    functions = ["async answerCall(){", "async hangupCall(){", "async toggleMicrophone(){",
                 "async toggleSpeaker(){", "async setPttActive(e){",
                 "async switchCallMode(e){" if page else "async toggleDuplexMode(){"]
    if page: functions.append("async switchAudioProfile(e){")
    for marker in functions:
        source = replace_once(source, marker, marker + "const __nextVoiceCall=this.activeCall?.call_id;")
    for operation in ("answer", "hangup"):
        before = f'window.api.post({route}("/telephone/{operation}"))'
        source = replace_once(source, before, before[:-1] + ',{call_id:__nextVoiceCall})')
    for mode in ("transmit", "receive"):
        before = f'const t={route}(e?"/telephone/unmute-{mode}":"/telephone/mute-{mode}");await window.api.post(t)'
        source = replace_once(source, before, before[:-1] + ',{call_id:__nextVoiceCall})')
    before = f'window.api.post({route}("/telephone/ptt"),{{active:t}})'
    source = replace_once(source, before, before.replace("{active:t}", "{active:t,call_id:__nextVoiceCall}"))
    for mode in (("call-mode", "audio-profile") if page else ("call-mode",)):
        before = f'window.api.post({route}(`/telephone/switch-{mode}/${{e}}`))'
        source = replace_once(source, before, before[:-1] + ',{call_id:__nextVoiceCall})')
    return source


def stage(frontend):
    for name, expected in CHUNKS.items():
        path = frontend / "assets" / name
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected: raise ValueError("The pinned telephone frontend checksum changed")
        path.write_text(rewrite(payload.decode(), page=name.startswith("CallPage-")))


if __name__ == "__main__":
    import sys
    stage(Path(sys.argv[1]))
