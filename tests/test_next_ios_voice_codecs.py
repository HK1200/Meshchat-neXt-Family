"""Real LXST round trips with the exact iOS ctypes Codec2 adapter."""
import ctypes
import ctypes.util
import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ios/NextRuntimeProbe"))
from voice_codec_probe import check_voice_codecs


@pytest.fixture
def native_codec2(monkeypatch):
    # Use the actual production adapter, backed by the local native Codec2
    # library. Xcode separately verifies the bundled iOS framework variant.
    # Import the real codec first so monkeypatch restores its original module
    # reference even when this fixture is the first code to import LXST.
    module = importlib.import_module("LXST.Codecs.Codec2")
    library = ctypes.CDLL(ctypes.util.find_library("codec2"))
    monkeypatch.setitem(sys.modules, "family_ios_codecs", SimpleNamespace(library=lambda: library))
    spec = importlib.util.spec_from_file_location("pycodec2", ROOT / "ios/VoiceRuntime/pycodec2.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    monkeypatch.setitem(sys.modules, "pycodec2", adapter)
    monkeypatch.setattr(module, "pycodec2", adapter)
    return module


def test_real_opus_and_ios_codec2_round_trips(native_codec2):
    result = check_voice_codecs()
    assert result["ok"] and not result["network_used"] and not result["microphone_used"]
    assert len(result["checks"]) == 10
    assert {row["setting"] for row in result["checks"] if row["codec"] == "opus"} == {0, 1, 2}
    assert {row["setting"] for row in result["checks"] if row["codec"] == "codec2"} == {700, 1200, 1300, 1400, 1600, 2400, 3200}
    assert all(row["rms"] > 0.00001 for row in result["checks"])


def test_a_silent_decoder_does_not_pass(native_codec2, monkeypatch):
    monkeypatch.setattr(native_codec2.Codec2, "decode", lambda self, packet: np.zeros((320, 1)))
    with pytest.raises(ValueError, match="silence"):
        check_voice_codecs()


def test_invalid_pcm_does_not_pass(native_codec2, monkeypatch):
    monkeypatch.setattr(native_codec2.Codec2, "decode", lambda self, packet: np.full((320, 1), np.nan))
    with pytest.raises(ValueError, match="invalid PCM"):
        check_voice_codecs()
