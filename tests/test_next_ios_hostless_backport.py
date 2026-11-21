"""Exercise the pinned-wheel repair with LXST's actual failing Null mixer."""
from pathlib import Path
import importlib
import sys
from types import SimpleNamespace
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ios/NextRuntimeProbe"))
from hostless_audio_patch import backport_hostless_mixer


def source():
    return (ROOT / "tests/fixtures/next-021-hostless-lifecycle.py.txt").read_bytes()


def test_pinned_wheel_backport_repairs_the_real_missing_backend_and_restores_it(monkeypatch):
    from LXST.Codecs import Null
    mixer = importlib.import_module("LXST.Mixer")
    monkeypatch.setattr(mixer, "Backend", None)
    old = {}; exec(compile(source(), 'unmodified-upstream-lifecycle', 'exec'), old)
    old['install_hostless_lxst_audio']()
    try:
        with pytest.raises(AttributeError, match='SAMPLERATE'): mixer.Mixer(codec=Null())
    finally: old['reset_hostless_lxst_audio_for_tests']()
    patched = {}; exec(compile(backport_hostless_mixer(source()), 'staged-lifecycle', 'exec'), patched)
    try:
        patched['install_hostless_lxst_audio']()
        assert mixer.Mixer(codec=Null()).samplerate == 48000
        assert patched['install_hostless_lxst_audio']()
    finally: patched['reset_hostless_lxst_audio_for_tests']()
    assert mixer.Backend is None


def test_pinned_backport_never_replaces_a_real_or_new_backend(monkeypatch):
    mixer = importlib.import_module("LXST.Mixer")
    backend = SimpleNamespace(SAMPLERATE=44100)
    monkeypatch.setattr(mixer, "Backend", backend)
    patched = {}; exec(compile(backport_hostless_mixer(source()), 'staged-lifecycle', 'exec'), patched)
    try:
        patched['install_hostless_lxst_audio']()
        assert mixer.Backend is backend
    finally: patched['reset_hostless_lxst_audio_for_tests']()
    assert mixer.Backend is backend


@pytest.mark.parametrize('payload', [b'changed upstream source', source().replace(b'WEB_AUDIO_SAMPLE_RATE', b'CHANGED_SAMPLE_RATE')])
def test_unknown_source_fails_closed_instead_of_shipping_a_partial_patch(payload):
    with pytest.raises(ValueError): backport_hostless_mixer(payload)
