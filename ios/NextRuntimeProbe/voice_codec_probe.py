"""Synthetic LXST codec checks; never uses a microphone, identity or network."""
import json
from types import SimpleNamespace


def check_voice_codecs():
    import numpy as np
    from LXST.Codecs.Opus import Opus
    from LXST.Codecs.Codec2 import Codec2

    results = []
    profiles = (Opus.PROFILE_VOICE_LOW, Opus.PROFILE_VOICE_MEDIUM, Opus.PROFILE_VOICE_HIGH)
    modes = (Codec2.CODEC2_700C, Codec2.CODEC2_1200, Codec2.CODEC2_1300, Codec2.CODEC2_1400,
             Codec2.CODEC2_1600, Codec2.CODEC2_2400, Codec2.CODEC2_3200)
    for kind, settings, factory, rate, samples in (
        ("opus", profiles, lambda setting: Opus(profile=setting), 48000, 960),
        ("codec2", modes, lambda setting: Codec2(mode=setting), 8000, 320),
    ):
        frame = (0.08 * np.sin(2 * np.pi * 440 * np.arange(samples) / rate)).astype(np.float32).reshape(-1, 1)
        for setting in settings:
            encoder, decoder = factory(setting), factory(setting)
            encoder.source = SimpleNamespace(samplerate=rate, channels=1)
            decoder.sink = SimpleNamespace(samplerate=rate, channels=1)
            energy = 0.0
            for _ in range(3):
                packet = encoder.encode(frame)
                if not packet:
                    raise ValueError("Voice encoder returned an empty packet")
                decoded = decoder.decode(packet)
                if decoded.shape != frame.shape or not np.isfinite(decoded).all():
                    raise ValueError("Voice decoder returned invalid PCM")
                energy = max(energy, float(np.sqrt(np.mean(decoded ** 2))))
            if energy <= 0.00001:
                raise ValueError("Voice decoder returned silence for the synthetic tone")
            results.append({"codec": kind, "setting": setting, "samples": samples,
                            "sample_rate": rate, "rms": energy})
    return {"ok": True, "checks": results, "microphone_used": False, "network_used": False}


def run_json():
    return json.dumps(check_voice_codecs(), allow_nan=False)
