"""Contact QR review is inert; only explicit Save persists a bound public key."""
import asyncio
from pathlib import Path
import sys
import json

import pytest
import RNS

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'ios/NextRuntimeProbe'), str(ROOT/'app/src/main/python')]
from contact_import import ContactImport
from blocked_destinations import PeerBlocks
from loopback_probe import ConversationHistory
from family_cards import export_contact


def fixture(tmp_path):
    own, remote = RNS.Identity(), RNS.Identity()
    history = ConversationHistory(tmp_path/'history.sqlite3')
    blocks = PeerBlocks(history.db, own)
    remembered, changes = [], []
    async def changed(): changes.append(True)
    importer = ContactImport(history, blocks,
        RNS.Destination.hash_from_name_and_identity('lxmf.delivery',own).hex(), changed,
        remember=lambda peer,key:remembered.append((peer,key)))
    return history, blocks, importer, remote, remembered, changes


def test_preview_parses_plain_address_uri_and_bound_family_card_without_saving(tmp_path):
    history, _, importer, remote, remembered, changes = fixture(tmp_path)
    address = RNS.Destination.hash_from_name_and_identity('lxmf.delivery',remote).hex()
    try:
        for code in (address, 'lxmf://'+address, export_contact('Private test',remote,True)):
            result = importer.preview(code)
            assert result['address'] == address and not result['exists']
        assert history.contacts() == {} and remembered == [] and changes == []
        assert importer.preview(export_contact('Private test',remote))['public_key_matches']
    finally: history.close()


def test_code_cannot_bind_a_different_key_or_add_self_or_bypass_banished_unknown_identity(tmp_path,monkeypatch):
    history, blocks, importer, remote, _, _ = fixture(tmp_path)
    address = RNS.Destination.hash_from_name_and_identity('lxmf.delivery',remote).hex()
    try:
        with pytest.raises(ValueError,match='match'): importer.preview('lxma://'+address+':'+RNS.Identity().get_public_key().hex())
        with pytest.raises(ValueError,match='own'): importer.preview(importer.own)
        monkeypatch.setattr(RNS.Identity,'recall',lambda *args,**kwargs:None)
        blocks.add(remote.hash.hex())
        with pytest.raises(ValueError,match='Unblock'): importer.preview(export_contact('Private',remote))
        assert history.contacts() == {}
    finally: history.close()


@pytest.mark.parametrize('value', ['', True, None, 'x'*8193, '雪'*4097,
    json.dumps({'format':'next-family-contact','version':True,'addresses':{'lxmf':'ab'*16}}),
    'meshcore://'+'ab'*32, 'sip:100@example.invalid'])
def test_invalid_or_other_service_codes_do_not_create_reticulum_contacts(tmp_path,value):
    history, _, importer, _, remembered, _ = fixture(tmp_path)
    try:
        with pytest.raises((ValueError,TypeError)): importer.preview(value)
        assert history.contacts() == {} and remembered == []
    finally: history.close()


def test_explicit_save_restores_key_on_restart_and_duplicate_never_changes_name(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestClient,TestServer
    history, blocks, importer, remote, remembered, changes = fixture(tmp_path)
    code = export_contact('Private QR fixture',remote,True)
    address = RNS.Destination.hash_from_name_and_identity('lxmf.delivery',remote).hex()
    async def run():
        app = web.Application(); importer.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/api/v1/preview/contact-import/preview',json={'code':code})
            assert response.status == 200 and not (await response.json())['exists']
            assert history.contacts() == {} and remembered == []
            response = await client.post('/api/v1/preview/contact-import/save',json={'code':code,'name':'Chosen nickname'})
            assert response.status == 200
            result = await response.json()
            assert result['exists'] and result['name'] == 'Chosen nickname'
            assert remembered == [(address,remote.get_public_key().hex())] and changes == [True]
            response = await client.post('/api/v1/preview/contact-import/save',json={'code':code,'name':'Overwrite'})
            assert response.status == 409 and history.contacts()[address]['name'] == 'Chosen nickname'
    try:
        asyncio.run(run())
        restored = ContactImport(history,blocks,importer.own,importer.changed,
            remember=lambda peer,key:remembered.append((peer,key)))
        assert restored.preview(code)['exists'] and len(remembered) == 2
        history.remove_contact(history.contacts()[address]['id'])
        assert history.db.execute('SELECT COUNT(*) FROM next_contact_import_keys').fetchone()[0] == 0
    finally: history.close()


def test_failed_atomic_contact_save_does_not_leave_contact_key_or_identity_cache(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestClient,TestServer
    history, _, importer, remote, remembered, changes = fixture(tmp_path)
    history.db.execute("CREATE TRIGGER reject_import_key BEFORE INSERT ON next_contact_import_keys BEGIN SELECT RAISE(ABORT, 'failure fixture'); END")
    async def run():
        app = web.Application(); importer.register(app.router)
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/api/v1/preview/contact-import/save',json={
                'code':export_contact('Private',remote),'name':'Private fixture'})
            assert response.status == 503
            assert history.contacts() == {} and remembered == [] and changes == []
            assert history.db.execute('SELECT COUNT(*) FROM next_contact_import_keys').fetchone()[0] == 0
    try: asyncio.run(run())
    finally: history.close()


def test_import_routes_share_private_session_and_csrf_and_make_contact_available_to_messaging(tmp_path):
    from contextlib import ExitStack
    from test_next_ios_tcp_integration import api,backend,run_server,start,wait
    app = tmp_path/'app';app.mkdir()
    settings = app/'peers.json';settings.write_text(json.dumps({'peers':[]}))
    remote = 'ab'*16
    with ExitStack() as lifetime:
        ready = app/'backend.url'
        start(lifetime,run_server,app,ready,settings)
        wait(ready.exists);base = backend(ready)
        token = api(base,'auth/csrf')[1]['csrf_token']
        assert api(base,'telephone/contacts')[1]['contacts'] == []
        assert api(base,'preview/contact-import/preview',body={'code':'lxmf://'+remote})[0] == 403
        status, draft = api(base,'preview/contact-import/preview',body={'code':'lxmf://'+remote},token=token)
        assert status == 200 and draft['address'] == remote and not draft['exists']
        assert api(base,'telephone/contacts')[1]['contacts'] == []
        status, saved = api(base,'preview/contact-import/save',body={'code':'lxmf://'+remote,'name':'Private QR fixture'},token=token)
        assert status == 200 and saved['exists'] and saved['name'] == 'Private QR fixture'
        contacts = api(base,'telephone/contacts')[1]['contacts']
        assert len(contacts) == 1 and contacts[0]['lxmf_address'] == remote
        assert contacts[0]['name'] == 'Private QR fixture'
