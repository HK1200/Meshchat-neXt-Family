"""Resolve the signed voice library bundled with the iOS app."""
import ctypes
from functools import lru_cache
from pathlib import Path


def library_path():
    return Path(__file__).resolve().parents[1] / "Frameworks/FamilyVoiceCodecs.framework/FamilyVoiceCodecs"


@lru_cache(maxsize=1)
def library():
    return ctypes.CDLL(str(library_path()))


def load_pyogg_library(name, tests):
    if name != "opus":
        return None
    native = library()
    return native if all(test(native) for test in tests) else None
