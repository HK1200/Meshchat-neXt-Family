from pathlib import Path
import sqlite3
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/python'))
from family_maps import MapStore


def pack(store, name, coords, high=12):
    source = store.root / ('import-' + name + '.tmp')
    with sqlite3.connect(source) as db:
        db.execute('create table metadata(name text, value text)')
        db.execute("insert into metadata values('format','png')")
        db.execute('create table tiles(zoom_level integer,tile_column integer,tile_row integer,tile_data blob)')
        for z, x, y in [*coords, (high, 0, 0)]:
            db.execute('insert into tiles values(?,?,?,?)', (z, x, 2**z-1-y, b'\x89PNG\r\n\x1a\n' + name.encode()))
    return store.install(source, name)['id']


def test_available_region_fills_missing_tiles_and_removal_preserves_other_pack(tmp_path):
    state = {}
    store = MapStore(tmp_path, state, threading.RLock(), lambda: None)
    pnw = pack(store, 'pnw', [(9, 100, 100)])
    other = pack(store, 'outside-pnw', [(9, 200, 200)])
    store.select(pnw)
    assert store.best_tile(pnw, 9, 200, 200)['bytes'].endswith(b'outside-pnw')
    assert store.best_tile(pnw, 9, 100, 100)['bytes'].endswith(b'pnw')
    assert store.best_tile(pnw, 9, 300, 300) is None
    store.remove(other)
    assert state['active_map'] == pnw
    assert store.best_tile(pnw, 9, 200, 200) is None
    assert store.best_tile(pnw, 9, 100, 100)['bytes'].endswith(b'pnw')


def test_best_detail_wins_and_invalid_coordinates_never_read_tiles(tmp_path):
    store = MapStore(tmp_path, {}, threading.RLock(), lambda: None)
    low = pack(store, 'low', [(9, 100, 100)], high=9)
    high = pack(store, 'high', [(9, 100, 100)], high=12)
    assert store.best_tile(low, 9, 100, 100)['bytes'].endswith(b'high')
    assert store.best_tile(high, 9, -1, 100) is None
    assert store.best_tile(high, '9', 100, 100) is None


def test_repeated_tile_reads_close_database_descriptors(tmp_path):
    import pytest
    descriptors = Path('/proc/self/fd')
    if not descriptors.exists():
        pytest.skip('Linux descriptor accounting')
    store = MapStore(tmp_path, {}, threading.RLock(), lambda: None)
    key = pack(store, 'private', [(9, 100, 100)])
    before = len(list(descriptors.iterdir()))
    for _ in range(100):
        assert store.best_tile(key, 9, 100, 100)
        assert store.best_tile(key, 9, 101, 100) is None
    assert len(list(descriptors.iterdir())) <= before + 2


def test_best_available_request_cannot_bypass_active_map_or_location_policy(monkeypatch):
    import importlib.util
    import json
    import signal
    from types import SimpleNamespace
    from unittest.mock import Mock
    spec = importlib.util.spec_from_file_location('private_map_policy_backend', Path(__file__).resolve().parents[1] / 'app/src/main/python/family_backend.py')
    backend = importlib.util.module_from_spec(spec)
    original = signal.signal
    try:
        spec.loader.exec_module(backend)
    finally:
        signal.signal = original
    backend._tcp_only = True
    backend._state = {'active_map': 'pnw', 'location_policy': {'mapEnabled': False}}
    reader = Mock(return_value=None)
    backend._maps = SimpleNamespace(best_tile=reader)
    def request(map_id):
        return json.loads(backend.request(json.dumps({'action': 'map_tile', 'payload': {
            'mapId': map_id, 'bestAvailable': True, 'z': 9, 'x': 100, 'y': 100}})))
    assert not request('pnw')['ok']
    backend._state['location_policy']['mapEnabled'] = True
    assert not request('unapproved-map')['ok']
    reader.assert_not_called()
    assert request('pnw') == {'ok': True, 'tile': None}
    reader.assert_called_once_with('pnw', 9, 100, 100)
