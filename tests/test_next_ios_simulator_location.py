"""The synthetic GPS receiver cannot acknowledge unsigned or public fixtures."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import LXMF
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'ios'), str(ROOT/'app/src/main/python')]
from simulator_location_fixture import valid_synthetic_location
from meshchatnext.src.backend.telemetry_utils import Telemeter


def message(*, signed=True, text='', lat=48.75, lon=-122.48, age=0, extra=False):
    now = time.time()
    packed = Telemeter.pack(time_utc=now, location={
        'latitude':lat, 'longitude':lon, 'altitude':0, 'accuracy':10,
        'speed':0, 'bearing':0, 'last_update':now-age})
    fields = {LXMF.FIELD_TELEMETRY:packed}
    if extra:
        fields[LXMF.FIELD_FILE_ATTACHMENTS] = [['unexpected.txt', b'not a GPS fixture']]
    return SimpleNamespace(signature_validated=signed, content_as_string=lambda:text, fields=fields)


def test_accepts_only_the_fresh_synthetic_signed_location():
    assert valid_synthetic_location(message())


@pytest.mark.parametrize('changes', [
    {'signed':False}, {'text':'message'}, {'lat':49}, {'lon':-123},
    {'age':180}, {'age':-90}, {'extra':True}])
def test_rejects_invalid_fixture(changes):
    assert not valid_synthetic_location(message(**changes))


@pytest.mark.parametrize('packed', [b'', b'invalid', b'x'*65537, None, 'not bytes'])
def test_rejects_malformed_telemetry(packed):
    value = message()
    value.fields[LXMF.FIELD_TELEMETRY] = packed
    assert not valid_synthetic_location(value)


def test_location_fixture_cannot_start_a_public_peer(tmp_path):
    spec = importlib.util.spec_from_file_location('isolated_location_peer', ROOT/'ios/simulator-peer.py')
    peer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(peer)
    folder = tmp_path/'must-not-exist'
    with pytest.raises(ValueError, match='loopback'):
        peer.main(folder, public=True, location_echo=True)
    assert not folder.exists()
