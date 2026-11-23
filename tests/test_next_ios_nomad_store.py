# SPDX-License-Identifier: 0BSD
"""Browser data is local, bounded and independent of the messaging identity."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('next_nomad_store', Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe/nomad_store.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
NomadStore = MODULE.NomadStore
ADDRESS = 'a1' * 16


def test_bookmarks_and_explicit_identification_survive_restart(tmp_path):
    path = tmp_path / 'browser.sqlite'
    store = NomadStore(path)
    try:
        saved = store.save_favourite(ADDRESS.upper(), 'Map\x00 station')
        assert saved['destination_hash'] == ADDRESS and saved['display_name'] == 'Map station'
        assert not store.should_identify_on_connect(ADDRESS)
        store.save_favourite(ADDRESS, 'Station', identify=True)
    finally:
        store.close()
    reopened = NomadStore(path)
    try:
        assert reopened.should_identify_on_connect(ADDRESS)
        assert len(reopened.favourites()) == 1
        reopened.remove_favourite(ADDRESS)
        assert not reopened.should_identify_on_connect(ADDRESS)
        assert reopened.favourites() == []
    finally:
        reopened.close()
    assert path.stat().st_mode & 0o777 == 0o600


def test_archives_preserve_content_and_deduplicate_the_same_page(tmp_path):
    store = NomadStore(tmp_path / 'browser.sqlite')
    try:
        first = store.archive_page(ADDRESS, '/page/index.mu', 'Hello `!World`!')
        assert store.archive_page(ADDRESS, '/page/index.mu', 'Hello `!World`!')['id'] == first['id']
        newer = store.archive_page(ADDRESS, '/page/index.mu', 'Changed')
        assert len(store.get_archived_page_versions(ADDRESS, '/page/index.mu')) == 2
        assert store.get_archived_page_by_id(first['id'])['content'] == 'Hello `!World`!'
        store.remove_archives([newer['id']])
        assert store.get_archived_page_by_id(newer['id']) is None
        assert store.get_archived_page_by_id(first['id']) is not None
    finally:
        store.close()


@pytest.mark.parametrize('limit', ['max_archive_bytes', 'max_archives'])
def test_archive_eviction_bounds_both_bytes_and_count(tmp_path, limit):
    store = NomadStore(tmp_path / 'browser.sqlite')
    try:
        if limit == 'max_archive_bytes': store.max_archive_bytes = 12
        else: store.max_archives = 2
        for index in range(5): store.archive_page(ADDRESS, '/page/index.mu', f'page {index}')
        rows = store.archives()
        assert len(rows) == 2
        assert [store.get_archived_page_by_id(row['id'])['content'] for row in rows] == ['page 4', 'page 3']
        assert sum(row['size'] for row in rows) == 12
    finally:
        store.close()


def test_invalid_archive_inputs_do_not_modify_existing_pages(tmp_path):
    store = NomadStore(tmp_path / 'browser.sqlite')
    try:
        store.archive_page(ADDRESS, '/page/index.mu', 'keep')
        before = store.archives()
        for address, path, content in [(True, '/page/index.mu', 'bad'), ('bad', '/page/index.mu', 'bad'),
                (ADDRESS, 'file:///private/data', 'bad'), (ADDRESS, '/page/\x00', 'bad'),
                (ADDRESS, '/page/index.mu', b'not text'), (ADDRESS, '/page/index.mu', 'x' * (store.max_page_bytes + 1))]:
            with pytest.raises(ValueError): store.archive_page(address, path, content)
            assert store.archives() == before
        for identifiers in ([True], [0], ['1'], [1] * (store.max_archives + 1)):
            with pytest.raises(ValueError): store.remove_archives(identifiers)
            assert store.archives() == before
    finally:
        store.close()


def test_bookmark_capacity_does_not_prevent_renaming_an_existing_entry(tmp_path):
    store = NomadStore(tmp_path / 'browser.sqlite')
    store.max_favourites = 1
    try:
        store.save_favourite(ADDRESS, 'First')
        with pytest.raises(ValueError): store.save_favourite('b2' * 16, 'Second')
        assert store.save_favourite(ADDRESS, 'Renamed')['display_name'] == 'Renamed'
        with pytest.raises(ValueError): store.save_favourite(ADDRESS, 'Bad setting', identify='false')
        assert store.favourite(ADDRESS)['display_name'] == 'Renamed'
    finally:
        store.close()


def test_an_empty_history_and_archive_removal_do_not_create_identity_files(tmp_path):
    store = NomadStore(tmp_path / 'browser.sqlite')
    try:
        assert store.archives() == []
        assert store.get_archived_page_by_id(True) is None
        assert store.get_archived_page_by_id(-1) is None
        store.archive_page(ADDRESS, '/page/index.mu', 'temporary')
        store.remove_archives()
        assert store.archives() == []
    finally:
        store.close()
    assert not any(p.name in ('identity', 'state.json', 'messages.sqlite3') for p in tmp_path.rglob('*'))


def test_import_is_atomic_and_cannot_enable_new_identity_disclosure(tmp_path):
    store = NomadStore(tmp_path / 'browser.sqlite')
    try:
        store.save_favourite(ADDRESS, 'Already approved', identify=True)
        second = 'b2' * 16
        assert store.import_favourites([
            {'destination_hash': ADDRESS, 'display_name': 'Renamed', 'identify_on_connect': False},
            {'destination_hash': second, 'display_name': 'Imported', 'identify_on_connect': True},
        ]) == 2
        assert store.should_identify_on_connect(ADDRESS)
        assert not store.should_identify_on_connect(second)
        before = store.favourites()
        with pytest.raises(ValueError):
            store.import_favourites([{'destination_hash': ADDRESS, 'display_name': 'Must not save'},
                                    {'destination_hash': 'invalid', 'display_name': 'Bad row'}])
        assert store.favourites() == before
        store.max_favourites = 2
        with pytest.raises(ValueError): store.import_favourites([{'destination_hash': 'c3' * 16}])
        assert store.favourites() == before
    finally: store.close()


def test_archive_search_is_bounded_and_does_not_return_content_unless_requested(tmp_path):
    store = NomadStore(tmp_path / 'browser.sqlite')
    try:
        store.save_favourite(ADDRESS, 'Trail station')
        store.archive_page(ADDRESS, '/page/index.mu', 'Road conditions')
        store.archive_page('b2' * 16, '/page/weather.mu', 'Clear')
        assert len(store.archive_rows('trail')) == 1
        assert len(store.archive_rows('ROAD')) == 1
        assert store.archive_rows("' OR 1=1 --") == []
        row = store.archive_rows(destination=ADDRESS)[0]
        assert 'content' not in row and row['preview'] == 'Road conditions'
        assert store.archive_rows(destination=ADDRESS, include_content=True)[0]['content'] == 'Road conditions'
        with pytest.raises(ValueError): store.archive_rows('x' * 257)
        with pytest.raises(ValueError): store.archive_rows(destination='not an address')
    finally: store.close()


def test_old_versions_are_evicted_and_oversized_identifiers_cannot_reach_sqlite(tmp_path):
    store = NomadStore(tmp_path / 'browser.sqlite')
    try:
        for index in range(8): store.archive_page(ADDRESS, '/page/index.mu', str(index))
        assert len(store.archives()) == store.max_versions
        assert [store.get_archived_page_by_id(row['id'])['content'] for row in store.archives()] == ['7','6','5','4','3']
        assert store.get_archived_page_by_id(2**80) is None
        before = store.archives()
        with pytest.raises(ValueError): store.remove_archives([2**80])
        assert store.archives() == before
    finally: store.close()
