"""Restart records retain exact signed contents without replaying location."""
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'ios/NextRuntimeProbe'), str(ROOT / 'app/src/main/python')]
import LXMF
import RNS
import durable_outbox as module


@pytest.fixture
def db(tmp_path):
    database = sqlite3.connect(tmp_path / 'outbox.sqlite3')
    module.schema(database)
    database.commit()
    yield database
    database.close()


def sample(content='Pending signed message', fields=None):
    own, other = RNS.Identity(), RNS.Identity()
    source = RNS.Destination(own, RNS.Destination.OUT, RNS.Destination.SINGLE, 'lxmf', 'delivery')
    target = RNS.Destination(other, RNS.Destination.OUT, RNS.Destination.SINGLE, 'lxmf', 'delivery')
    RNS.Identity.remember(None, target.hash, other.get_public_key())
    message = LXMF.LXMessage(target, source, content, fields=fields or {}, desired_method=LXMF.LXMessage.DIRECT)
    message.pack()
    def create(identity, text, raw_fields, method):
        destination = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, 'lxmf', 'delivery')
        return LXMF.LXMessage(destination, source, text, fields=raw_fields, desired_method=method)
    probe = SimpleNamespace(source=source, _message=create)
    row = dict(hash=message.hash.hex(), destination_hash=target.hash.hex(), content=content, state='sending', is_outbound=True)
    delivery = module.policy(message.desired_method, True, None, None)
    return message, probe, row, delivery


def test_signed_text_file_photo_reply_survive_restart_with_identical_identifier(db):
    fields = {LXMF.FIELD_FILE_ATTACHMENTS: [['fixture.bin', b'file\x00bytes']], LXMF.FIELD_IMAGE: ['png', b'photo bytes'], LXMF.FIELD_REPLY_TO: b'r' * 32}
    original, probe, row, delivery = sample('Unicode reply: Привет 🌲', fields)
    with db:
        module.enqueue(db, row, original.packed, delivery)
    packed, saved = db.execute('SELECT packet, policy FROM next_pending_messages').fetchone()
    restored = module.recreate(packed, row['hash'], row['destination_hash'], probe, module.selected_policy(saved))
    assert restored.hash == original.hash
    assert restored.packed == original.packed
    assert restored.fields == fields and restored.timestamp == original.timestamp
    assert restored.source is probe.source and not restored.incoming


def test_queue_write_rolls_back_with_the_callers_history_transaction(db):
    original, probe, row, delivery = sample()
    with pytest.raises(OSError):
        with db:
            module.enqueue(db, row, original.packed, delivery)
            raise OSError('Failed history commit')
    assert db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0] == 0


@pytest.mark.parametrize('change', ['packet', 'hash', 'destination', 'source'])
def test_modified_or_different_identity_cannot_be_replayed(db, change):
    original, probe, row, delivery = sample()
    packet = original.packed
    if change == 'packet': packet = packet[:40] + bytes([packet[40] ^ 1]) + packet[41:]
    if change == 'hash': row['hash'] = 'ab' * 32
    if change == 'destination': row['destination_hash'] = 'ab' * 16
    if change == 'source': probe.source = sample()[1].source
    with pytest.raises(ValueError): module.recreate(packet, row['hash'], row['destination_hash'], probe, delivery)


@pytest.mark.parametrize('content,fields', [('!NFLOC1:geo:48,-122', {}), ('', {LXMF.FIELD_TELEMETRY: b'private fix'}), ('', {LXMF.FIELD_TELEMETRY_STREAM: [b'private fix']})])
def test_location_packets_are_never_restored_as_messages(content, fields):
    original, probe, row, delivery = sample(content, fields)
    with pytest.raises(ValueError, match='Location updates'):
        module.recreate(original.packed, row['hash'], row['destination_hash'], probe, delivery)


def test_queue_bounds_leave_previously_saved_packets_intact(db, monkeypatch):
    original, probe, row, delivery = sample()
    with db: module.enqueue(db, row, original.packed, delivery)
    before = db.execute('SELECT * FROM next_pending_messages').fetchall()
    monkeypatch.setattr(module, 'MAX_PENDING', 1)
    next_message, _, next_row, next_delivery = sample('Another message')
    with pytest.raises(ValueError):
        with db: module.enqueue(db, next_row, next_message.packed, next_delivery)
    assert db.execute('SELECT * FROM next_pending_messages').fetchall() == before


@pytest.mark.parametrize('raw', ['{}', '[]', '{"method":1}', '{"method":3,"automatic":"yes","relay":null,"route":null}'])
def test_invalid_delivery_choices_are_rejected(raw):
    with pytest.raises((ValueError, TypeError)): module.selected_policy(raw)


def test_pending_history_survives_cold_restart_but_legacy_unsent_rows_fail(tmp_path):
    from loopback_probe import ConversationHistory
    path = tmp_path / 'history.sqlite3'
    history = ConversationHistory(path)
    original, probe, row, delivery = sample()
    row['source_hash'] = probe.source.hash.hex()
    history.save(row['destination_hash'], row, pending=(original.packed, delivery))
    legacy = dict(row, hash='af' * 32)
    history.save(row['destination_hash'], legacy)
    history.close()
    restored = ConversationHistory(path)
    assert dict(restored.db.execute('SELECT hash,state FROM messages')) == {row['hash']:'sending', legacy['hash']:'failed'}
    assert restored.db.execute('SELECT packet FROM next_pending_messages').fetchone()[0] == original.packed
    restored.save(row['destination_hash'], dict(row, state='delivered'))
    assert restored.db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0] == 0
    restored.close()


def test_removing_pending_conversation_also_removes_restart_packet(tmp_path):
    from loopback_probe import ConversationHistory
    history = ConversationHistory(tmp_path / 'history.sqlite3')
    original, probe, row, delivery = sample()
    row['source_hash'] = probe.source.hash.hex()
    history.ensure_contact(row['destination_hash'], 'Private fixture')
    history.save(row['destination_hash'], row, pending=(original.packed, delivery))
    assert history.delete_conversations([row['destination_hash']]) == [row['hash']]
    assert history.db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0] == 0
    assert history.save(row['destination_hash'], dict(row,state='delivered')) is None
    assert history.contacts()[row['destination_hash']]['name'] == 'Private fixture'
    history.close()


def test_history_and_restart_packet_cannot_commit_separately(tmp_path):
    from loopback_probe import ConversationHistory
    history = ConversationHistory(tmp_path / 'history.sqlite3')
    original, probe, row, delivery = sample()
    with history.db:
        history.db.execute("CREATE TRIGGER reject_test_history BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT, 'simulated full database'); END")
    with pytest.raises(sqlite3.IntegrityError):
        history.save(row['destination_hash'], row, pending=(original.packed, delivery))
    assert history.db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0] == 0
    assert history.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0
    history.close()


def test_saved_public_key_recovers_without_recipient_in_volatile_cache(db, monkeypatch):
    import json
    original, probe, row, delivery = sample(fields={LXMF.FIELD_FILE_ATTACHMENTS:[['offline.bin',b'exact offline bytes']]})
    public = original.destination.identity.get_public_key()
    delivery=module.policy(original.desired_method,True,None,None,recipient=public)
    with db:module.enqueue(db,row,original.packed,delivery)
    packed,saved=db.execute('SELECT packet,policy FROM next_pending_messages').fetchone()
    assert json.loads(saved)['recipient']==public.hex()
    monkeypatch.setattr(RNS.Identity,'recall',lambda *args,**kwargs:None)
    restored=module.recreate(packed,row['hash'],row['destination_hash'],probe,module.selected_policy(saved))
    assert restored.packed==original.packed and restored.hash==original.hash
    assert restored.destination.identity.get_public_key()==public
    assert restored.destination.identity.get_private_key() is None


def test_wrong_recipient_key_cannot_be_enqueued_or_replayed(db):
    original,probe,row,delivery=sample()
    delivery=module.policy(original.desired_method,True,None,None,recipient=RNS.Identity().get_public_key())
    with pytest.raises(ValueError,match='does not match'):
        with db:module.enqueue(db,row,original.packed,delivery)
    assert db.execute('SELECT COUNT(*) FROM next_pending_messages').fetchone()[0]==0
    with pytest.raises(ValueError,match='does not match'):
        module.recreate(original.packed,row['hash'],row['destination_hash'],probe,delivery)


def test_legacy_policy_without_public_key_remains_readable_but_never_guesses(monkeypatch):
    import json
    original,probe,row,delivery=sample()
    delivery.pop('recipient')
    restored=module.selected_policy(json.dumps(delivery))
    assert restored['recipient'] is None
    assert module.recreate(original.packed,row['hash'],row['destination_hash'],probe,restored).hash==original.hash
    monkeypatch.setattr(RNS.Identity,'recall',lambda *args,**kwargs:None)
    with pytest.raises(LookupError):module.recreate(original.packed,row['hash'],row['destination_hash'],probe,restored)


@pytest.mark.parametrize('recipient',[True,123,'aa','zz'*64])
def test_malformed_saved_public_keys_are_rejected(recipient):
    import json
    _,_,_,delivery=sample();delivery['recipient']=recipient
    with pytest.raises(ValueError):module.selected_policy(json.dumps(delivery))
