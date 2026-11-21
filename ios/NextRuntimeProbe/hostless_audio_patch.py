"""Carry the reviewed neXt hostless-mixer repair into the pinned 0.1.21 wheel.

Remove this backport when the checksum-pinned backend wheel contains the repair.
The enclosing stager verifies the complete upstream wheel before calling this.
"""


def backport_hostless_mixer(payload):
    replacements = (
        (b"import contextlib\n", b"import contextlib\nimport importlib\n", 1),
        (b"import threading\n", b"import threading\nfrom types import SimpleNamespace\n", 1),
        (b"_ORIG_LINE_SINK = None\nWEB_AUDIO_SAMPLE_RATE", b"_ORIG_LINE_SINK = None\n_HOSTLESS_MIXER_BACKEND = None\nWEB_AUDIO_SAMPLE_RATE", 1),
        (b"    global _HOSTLESS_AUDIO_INSTALLED, _ORIG_LINE_SOURCE, _ORIG_LINE_SINK\n", b"    global _HOSTLESS_AUDIO_INSTALLED, _ORIG_LINE_SOURCE, _ORIG_LINE_SINK\n    global _HOSTLESS_MIXER_BACKEND\n", 2),
        (b"        from LXST.Primitives import Telephony as lxst_telephony\n    except Exception as exc:", b"        from LXST.Primitives import Telephony as lxst_telephony\n\n        mixer_module = importlib.import_module(\"LXST.Mixer\")\n    except Exception as exc:", 1),
        (b'    _ORIG_LINE_SOURCE = getattr(lxst_telephony, "LineSource", None)', b'''    if mixer_module.Backend is None:
        _HOSTLESS_MIXER_BACKEND = SimpleNamespace(SAMPLERATE=WEB_AUDIO_SAMPLE_RATE)
        mixer_module.Backend = _HOSTLESS_MIXER_BACKEND

    _ORIG_LINE_SOURCE = getattr(lxst_telephony, "LineSource", None)''', 1),
        (b"    _HOSTLESS_AUDIO_INSTALLED = False\n    _ORIG_LINE_SOURCE = None", b'''    with contextlib.suppress(Exception):
        mixer_module = importlib.import_module("LXST.Mixer")
        if (
            _HOSTLESS_MIXER_BACKEND is not None
            and mixer_module.Backend is _HOSTLESS_MIXER_BACKEND
        ):
            mixer_module.Backend = None
    _HOSTLESS_MIXER_BACKEND = None
    _HOSTLESS_AUDIO_INSTALLED = False
    _ORIG_LINE_SOURCE = None''', 1),
    )
    for before, after, count in replacements:
        if payload.count(before) != count:
            raise ValueError("The pinned hostless audio source changed; review the mixer backport")
        payload = payload.replace(before, after)
    compile(payload, "staged-web-audio-bridge", "exec")
    return payload
