"""Real identity aliases, durable bans, and released HTTP contracts."""
import asyncio
from pathlib import Path
import sqlite3
import sys

import pytest
import RNS

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'ios/NextRuntimeProbe'), str(ROOT/'app/src/main/python')]
from blocked_destinations import PeerBlocks, aliases
from block_runtime import BlockRuntime
from loopback_probe import ConversationHistory
from conversation_organization import ConversationOrganization


def identities(monkeypatch):
    own, remote, other = RNS.Identity(), RNS.Identity(), RNS.Identity()
    mapping = {}
    for identity in (own, remote, other):
        for aspect in ('lxmf.delivery', 'lxst.telephony'):
            mapping[RNS.Destination.hash_from_name_and_identity(aspect, identity)] = identity
        mapping[identity.hash] = identity
    monkeypatch.setattr(RNS.Identity, 'recall', lambda raw, **kwargs:mapping.get(raw))
    def lxmf(identity): return RNS.Destination.hash_from_name_and_identity('lxmf.delivery', identity).hex()
    return own, remote, other, lxmf


def test_blocks_all_verified_identity_aliases_and_preserves_other_peers_after_restart(tmp_path, monkeypatch):
    own, remote, other, lxmf = identities(monkeypatch)
    db = sqlite3.connect(tmp_path/'blocks.sqlite3')
    try:
        blocks = PeerBlocks(db, own)
        assert len(blocks.add(lxmf(remote))) == 3
        assert all(blocks.denies(key) for key in aliases(lxmf(remote)))
        assert not blocks.denies(lxmf(other)) and not blocks.denies(lxmf(own))
        restored = PeerBlocks(db, own)
        assert restored.snapshot() == blocks.snapshot()
        restored.remove(remote.hash.hex())
        assert restored.snapshot() == [] and not restored.denies(lxmf(remote))
    finally: db.close()


@pytest.mark.parametrize('value', [None, True, 12, '', 'a'*31, 'g'*32, '../'+'a'*29])
def test_invalid_addresses_cannot_change_blocks(value):
    db = sqlite3.connect(':memory:')
    try:
        blocks = PeerBlocks(db, RNS.Identity())
        with pytest.raises(ValueError): blocks.add(value)
        assert blocks.snapshot() == []
        assert blocks.denies(value)
    finally: db.close()


def test_own_identity_cannot_be_banished(monkeypatch):
    own, _, _, lxmf = identities(monkeypatch)
    db = sqlite3.connect(':memory:')
    try:
        blocks = PeerBlocks(db, own)
        for key in aliases(lxmf(own)):
            with pytest.raises(ValueError, match='own'): blocks.add(key)
        assert blocks.snapshot() == []
    finally: db.close()


def test_failed_database_commit_does_not_change_live_ban_snapshot(monkeypatch):
    own, remote, _, lxmf = identities(monkeypatch)
    db = sqlite3.connect(':memory:')
    blocks = PeerBlocks(db, own)
    db.execute("CREATE TRIGGER reject_ban BEFORE INSERT ON next_blocked_destinations BEGIN SELECT RAISE(ABORT, 'failure fixture'); END")
    with pytest.raises(sqlite3.IntegrityError): blocks.add(lxmf(remote))
    assert not blocks.denies(lxmf(remote)) and blocks.snapshot() == []
    db.close()


def test_http_banishment_revokes_consent_deletes_only_target_and_unblock_does_not_restore_history(tmp_path, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    own, remote, other, lxmf = identities(monkeypatch)
    async def run():
        history = ConversationHistory(tmp_path/'history.sqlite3')
        history.ensure_contact(lxmf(remote), 'Banish fixture')
        history.ensure_contact(lxmf(other), 'Keep fixture')
        blocks = PeerBlocks(history.db, own)
        revoked, events = [], []
        async def revoke(keys): revoked.append(keys)
        async def changed(): events.append(blocks.snapshot())
        app = web.Application()
        BlockRuntime(blocks, history, ConversationOrganization(history), revoke, changed).register(app.router)
        try:
            async with TestClient(TestServer(app)) as client:
                response = await client.post('/api/v1/blocked-destinations', json={'destination_hash':lxmf(remote)})
                assert response.status == 200 and revoked == [aliases(lxmf(remote))]
                assert lxmf(remote) not in history.contacts() and lxmf(other) in history.contacts()
                assert not history.conversation_entries().get(lxmf(remote))
                listed = await (await client.get('/api/v1/blocked-destinations')).json()
                assert len(listed['blocked_destinations']) == 3 and len(events) == 1
                response = await client.delete('/api/v1/blocked-destinations/'+remote.hash.hex())
                assert response.status == 200 and blocks.snapshot() == []
                assert lxmf(remote) not in history.contacts()  # No deleted data resurrected.
                for body in ({'destination_hash':'x'*32}, {'destination_hash':lxmf(remote),'extra':True}):
                    assert (await client.post('/api/v1/blocked-destinations',json=body)).status == 400
        finally: history.close()
    asyncio.run(run())


def test_native_voice_and_location_use_the_same_destination_ban(tmp_path, monkeypatch):
    from test_next_ios_voice_runtime import fixture
    from test_next_ios_location_runtime import fixture as location_fixture
    own, remote, _, lxmf = identities(monkeypatch)
    async def run():
        voice, native, db = fixture()
        blocks = PeerBlocks(db, own); blocks.add(lxmf(remote))
        voice.destination_blocked = blocks.denies
        voice.config.telephone_enabled.value = True
        assert not voice.message_allowed(lxmf(remote))
        assert not voice.caller_allowed(remote.hash)
        previous = list(native.requests)
        with pytest.raises(ValueError, match='blocked'): await voice.dial(lxmf(remote))
        assert native.requests == previous
        runtime = location_fixture(tmp_path)
        runtime.history.conversation_entries = lambda:{lxmf(remote):{'name':'Private fixture'}}
        runtime.recipient_allowed = lambda peer:not blocks.denies(peer)
        assert await runtime.catalog() == {}
        blocks.remove(lxmf(remote))
        assert voice.message_allowed(lxmf(remote))
        assert await runtime.catalog()
        await runtime.close(); await voice.close(); db.close()
    asyncio.run(run())


def test_real_signed_messages_cannot_recreate_banished_history_and_ban_survives_restart(tmp_path):
    from contextlib import ExitStack
    import json
    import socket
    from test_next_ios_tcp_integration import api, backend, run_hub, run_server, start, wait
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    app = tmp_path/'app'; app.mkdir()
    settings = app/'peers.json'
    with ExitStack() as stack:
        _, hub = start(stack, run_hub, tmp_path/'hub', [port])
        assert hub.poll(15)
        remote = hub.recv()
        settings.write_text(json.dumps({'address':remote, 'peers':[
            {'id':'private-block-test','host':'127.0.0.1','port':port,'enabled':True}]}))
        own = None
        for index in range(2):
            with ExitStack() as lifetime:
                ready = app/f'backend-{index}.url'
                start(lifetime, run_server, app, ready, settings)
                wait(ready.is_file)
                base = backend(ready)
                token = api(base, 'auth/csrf')[1]['csrf_token']
                config = api(base, 'config')[1]['config']
                if own is None: own = config['lxmf_address_hash']
                else: assert config['lxmf_address_hash'] == own
                def received(text):
                    rows = api(base, 'lxmf-messages/conversation/'+remote)[1]['lxmf_messages']
                    return any(row['content'] == text and row['state'] == 'received' for row in rows)
                wait(lambda:api(base,'preview/reticulum-connections')[1]['peers'][0]['online'])
                wait(lambda:api(base,'config')[1]['config'].get('last_announced_at'))
                hub.send({'announce':True})
                wait(lambda:any(row['destination_hash'] == remote for row in
                    api(base,'announces?include_blocked=true')[1]['announces']))
                if index == 0:
                    # Ensure the fixture has the sender path before issuing a private message.
                    def sender_known():
                        observed = tmp_path/'hub/observed-name.json'
                        return observed.exists() and json.loads(observed.read_text())['address'] == own
                    wait(sender_known)
                    hub.send({'send_to':own,'content':'Before private ban'})
                    wait(lambda:received('Before private ban'))
                    assert api(base,'blocked-destinations',body={'destination_hash':remote})[0] == 403
                    assert received('Before private ban')
                    assert api(base,'blocked-destinations',body={'destination_hash':remote},token=token)[0] == 200
                listed = api(base,'blocked-destinations')[1]['blocked_destinations']
                assert remote in {row['destination_hash'] for row in listed}
                assert api(base,'telephone/contacts')[1]['contacts'] == []
                assert not received('Before private ban')
                text = f'Blocked private packet {index}'
                hub.send({'send_to':own,'content':text})
                def delivered():
                    hub.send({'delivery_status':text})
                    return hub.poll(5) and hub.recv()
                wait(delivered,timeout=45)
                assert not received(text)
                assert api(base,'preview/unread-messages')[1]['messages'] == []
                with sqlite3.connect(app/f'messages-{own}.sqlite3') as db:
                    assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0
                    assert db.execute('SELECT COUNT(*) FROM notification_metadata').fetchone()[0] == 0
                if index == 1:
                    assert api(base,'blocked-destinations/'+remote,method='DELETE',token=token)[0] == 200
                    assert api(base,'blocked-destinations')[1]['blocked_destinations'] == []
                    hub.send({'send_to':own,'content':'After private unblock'})
                    wait(lambda:received('After private unblock'))


def test_a_ban_during_call_initialization_is_checked_again_before_native_dial():
    from test_next_ios_voice_runtime import fixture
    async def run():
        voice, native, db = fixture()
        voice.config.telephone_enabled.value = True
        voice.destination_blocked = lambda peer:False
        async def delayed_engine(): voice.destination_blocked = lambda peer:True
        voice.ensure_engine = delayed_engine
        try:
            with pytest.raises(ValueError, match='blocked before'): await voice.dial('ab'*16)
            assert not any(row['op'] == 'dial' for row in native.requests)
            assert voice.call is None
        finally: await voice.close(); db.close()
    asyncio.run(run())


def test_discovery_exact_lookup_can_resolve_a_banished_identity_without_mismatching_names(tmp_path):
    from discovery import ClientDiscovery
    store = ClientDiscovery(tmp_path/'discovery.sqlite3', 'ab'*16)
    remote = RNS.Identity(); other = RNS.Identity()
    destination = RNS.Destination.hash_from_name_and_identity('lxmf.delivery', remote)
    store.received_announce(destination, remote, b'Private remote')
    store.received_announce(RNS.Destination.hash_from_name_and_identity('lxmf.delivery', other), other, b'Other')
    try:
        for key in (destination.hex(), remote.hash.hex(),
                    RNS.Destination.hash_from_name_and_identity('lxst.telephony', remote).hex()):
            rows = store.page({'destination_hash':key, 'include_blocked':'true'})
            assert len(rows) == 1 and rows[0]['identity_hash'] == remote.hash.hex()
            assert rows[0]['display_name'] == 'Private remote'
        assert store.page({'destination_hash':'01'*16}) == []
        with pytest.raises(ValueError): store.page({'destination_hash':'not-an-address'})
    finally: store.close()


def run_held_sender(folder, ready, settings, pipe):
    from test_next_ios_tcp_integration import run_server, wait
    from messaging_probe import MessagingProbe
    original = MessagingProbe.compose
    def held(self, *args, **kwargs):
        (folder/'compose-waiting').write_text('private-path-search')
        wait(lambda:(folder/'compose-release').exists(), timeout=25)
        return original(self, *args, **kwargs)
    MessagingProbe.compose = held
    run_server(folder, ready, settings, pipe)


def test_banishment_during_real_path_preparation_prevents_packet_submission(tmp_path):
    from contextlib import ExitStack
    from concurrent.futures import ThreadPoolExecutor
    import json
    import socket
    from test_next_ios_tcp_integration import api, backend, run_hub, start, wait
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    folder = tmp_path/'app'; folder.mkdir()
    settings = folder/'peers.json'
    with ExitStack() as lifetime:
        _, hub = start(lifetime, run_hub, tmp_path/'hub', [port])
        assert hub.poll(15); remote = hub.recv()
        settings.write_text(json.dumps({'address':remote,'peers':[
            {'id':'private-path-test','host':'127.0.0.1','port':port,'enabled':True}]}))
        ready = folder/'backend.url'
        start(lifetime, run_held_sender, folder, ready, settings)
        wait(ready.exists); base = backend(ready)
        token = api(base,'auth/csrf')[1]['csrf_token']
        wait(lambda:api(base,'preview/reticulum-connections')[1]['peers'][0]['online'])
        hub.send({'announce':True})
        wait(lambda:any(row['destination_hash'] == remote for row in api(base,'announces')[1]['announces']))
        with ThreadPoolExecutor(max_workers=1) as executor:
            sending = executor.submit(api,base,'lxmf-messages/send', token=token,
                body={'lxmf_message':{'destination_hash':remote,'content':'Must not leave after ban'}})
            try:
                wait(lambda:(folder/'compose-waiting').exists())
                assert api(base,'blocked-destinations',body={'destination_hash':remote},token=token)[0] == 200
            finally: (folder/'compose-release').write_text('release-private-fixture')
            status, result = sending.result(timeout=45)
            assert status == 400 and 'blocked before submission' in result
        assert api(base,'lxmf-messages/conversation/'+remote)[1]['lxmf_messages'] == []


@pytest.mark.parametrize('event',['ringing','established'])
def test_network_call_accepted_before_ban_cannot_ring_or_attach_audio_afterward(event):
    from test_next_ios_voice_runtime import fixture
    async def run():
        voice, native, db = fixture()
        voice.config.telephone_enabled.value = True
        try:
            engine = await voice.ensure_engine()
            voice.destination_blocked = lambda peer:True
            voice.transport_event(engine, event, RNS.Identity())
            assert voice.ending is not None
            await voice.ending
            assert voice.call is None and not voice.pcm_ready
            assert not any(row.get('state') in ('incoming','connected') for row in native.requests)
            assert voice.call_history({})['call_history'] == []
        finally: await voice.close(); db.close()
    asyncio.run(run())
