"""Private notification metadata never pages attachment bytes or announces location."""
from pathlib import Path
import sys
from types import SimpleNamespace
import time
import LXMF
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe'))
from loopback_probe import ConversationHistory, record

ALICE = 'ab' * 16
BOB = 'bc' * 16


def row(number, content='Private text', state='received', **extra):
    return dict(hash=f'{number:064x}', state=state, content=content, fields={}, **extra)


def test_alerts_include_latest_unread_message_without_saving_unknown_sender(tmp_path):
    history = ConversationHistory(tmp_path / 'history')
    history.ensure_contact(ALICE, 'Local nickname')
    history.ensure_contact(BOB, 'Other nickname')
    for number in [1, 2]: history.save(ALICE, row(number))
    history.save(BOB, row(3))
    history.save('cd' * 16, row(4))
    history.save(ALICE, row(5, state='delivered'))
    notices = history.notification_candidates()
    assert [notice['hash'] for notice in notices] == [f'{4:064x}', f'{3:064x}', f'{2:064x}']
    assert all(set(notice) == {'id', 'hash', 'peer'} for notice in notices)
    history.mark_read(ALICE)
    assert [n['peer'] for n in history.notification_candidates()] == ['cd' * 16, BOB]
    history.close()


def test_telemetry_is_silent_without_hiding_a_real_unread_message(tmp_path):
    history = ConversationHistory(tmp_path / 'history')
    history.ensure_contact(ALICE, 'Saved')
    history.save(ALICE, row(1))
    history.save(ALICE, row(2, content='!NFLOC1:geo:48.7,-122.4'))
    history.save(ALICE, row(3, content='', is_private_telemetry=True))
    assert [n['hash'] for n in history.notification_candidates()] == [f'{1:064x}']
    history.close()


def test_legacy_unread_state_survives_without_retroactive_alerts(tmp_path):
    path = tmp_path / 'history'
    history = ConversationHistory(path)
    history.ensure_contact(ALICE, 'Saved')
    history.save(ALICE, row(1))
    history.db.execute('DROP TABLE notification_metadata')
    history.db.commit(); history.close()
    history = ConversationHistory(path)
    assert history.summary(ALICE)['is_unread']
    assert history.notification_candidates() == []
    history.save(ALICE, row(2))
    assert len(history.notification_candidates()) == 1
    history.close()
    history = ConversationHistory(path)
    assert len(history.notification_candidates()) == 1
    history.delete(f'{2:064x}')
    assert history.notification_candidates() == []
    assert history.db.execute('SELECT COUNT(*) FROM notification_metadata').fetchone()[0] == 1
    history.close()


def test_notification_query_does_not_read_message_or_attachment_payload(tmp_path, monkeypatch):
    history = ConversationHistory(tmp_path / 'history')
    history.ensure_contact(ALICE, 'Saved')
    history.save(ALICE, row(1, content='Attached photo'))
    import loopback_probe
    def forbidden(*args, **kwargs): raise AssertionError('Notification query decoded a private message body')
    monkeypatch.setattr(loopback_probe.json, 'loads', forbidden)
    assert history.notification_candidates()[0]['hash'] == f'{1:064x}'
    history.close()


def test_signed_lxmf_telemetry_is_classified_without_alerting_chat_text():
    message = SimpleNamespace(fields={LXMF.FIELD_TELEMETRY: b'telemetry'}, hash=b'a'*32,
        source_hash=b'b'*16, destination_hash=b'c'*16, timestamp=time.time(),
        content_as_string=lambda: '')
    assert record(message, 'received')['is_private_telemetry']
    message.content_as_string = lambda: 'Ordinary text with optional telemetry'
    assert not record(message, 'received')['is_private_telemetry']


def test_non_dictionary_signed_fields_do_not_break_chat_recording():
    message = SimpleNamespace(fields="malformed", hash=b'a'*32, source_hash=b'b'*16,
        destination_hash=b'c'*16, timestamp=time.time(), content_as_string=lambda: 'Chat text')
    saved = record(message, 'received')
    assert saved['content'] == 'Chat text' and not saved['is_private_telemetry']


def test_incoming_conversation_does_not_create_phonebook_contact(tmp_path):
    path = tmp_path / 'history'
    history = ConversationHistory(path)
    history.save(ALICE, row(1))
    assert history.has_conversation(ALICE)
    assert not history.has_conversation('not-an-address')
    assert history.contacts() == {}
    assert history.conversation_entries()[ALICE] == {'name': ALICE, 'is_contact': False}
    history.close()
    history = ConversationHistory(path)
    assert history.summary(ALICE)['is_unread']
    assert history.contacts() == {}
    history.ensure_contact(ALICE, 'My nickname')
    assert list(history.conversation_entries()) == [ALICE]
    assert history.conversation_entries()[ALICE]['name'] == 'My nickname'
    assert history.conversation_entries()[ALICE]['is_contact']
    history.close()


def test_unsigned_dm_never_reaches_inbox_callback():
    from messaging_probe import MessagingProbe
    probe = object.__new__(MessagingProbe)
    received = []
    probe.on_receive = received.append
    probe.receive(SimpleNamespace(signature_validated=False))
    assert received == []
    signed = SimpleNamespace(signature_validated=True)
    probe.receive(signed)
    assert received == [signed]
