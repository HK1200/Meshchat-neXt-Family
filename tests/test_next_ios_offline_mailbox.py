"""Mailbox opt-in, durable settings, bounded retries and connection retirement."""
from pathlib import Path
import sqlite3
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"))
from offline_mailbox import OfflineMailbox


class Router:
    PR_IDLE, PR_COMPLETE = 0, 10
    propagation_transfer_state = 0
    def __init__(self): self.requests = []; self.cancels = 0
    def cancel_propagation_node_requests(self):
        self.cancels += 1; self.propagation_transfer_state = self.PR_IDLE
    def set_outbound_propagation_node(self, address): self.address = address
    def request_messages_from_propagation_node(self, identity, max_messages):
        self.requests.append((self.address, identity, max_messages))
        self.propagation_transfer_state = 2


def setup(path):
    db, router, now, connection = sqlite3.connect(path), Router(), [100], [None]
    mailbox = OfflineMailbox(db, router, 'own-private-identity', lambda: connection[0], clock=lambda: now[0], wall=lambda: 1700000000)
    return mailbox, db, router, now, connection


def test_default_off_does_not_contact_relay_and_address_survives_restart(tmp_path):
    mailbox, db, router, now, connection = setup(tmp_path/'history.db')
    connection[0] = ('private-radio',1)
    assert mailbox.tick()['status'] == 'off'
    assert not router.requests and not router.cancels
    assert mailbox.configure({'address': ' ' + 'AB'*16 + ' '})['address'] == 'ab'*16
    mailbox.tick()
    assert router.requests == [(bytes.fromhex('ab'*16), 'own-private-identity', 50)]
    mailbox.close(); db.close()
    restored, db, router, now, connection = setup(tmp_path/'history.db')
    assert restored.address == 'ab'*16
    assert restored.tick()['status'] == 'waiting' and not router.requests
    db.close()


@pytest.mark.parametrize('payload', [None, [], {}, {'address':1}, {'address':'x'*32}, {'address':'ab'*15}, {'address':'ab'*16,'enabled':True}, {'address':'http://example.com'}])
def test_invalid_settings_never_change_saved_relay(tmp_path, payload):
    mailbox, db, router, now, connection = setup(tmp_path/'history.db')
    mailbox.configure({'address':'ab'*16})
    before = router.cancels
    with pytest.raises(ValueError): mailbox.configure(payload)
    assert mailbox.address == 'ab'*16 and router.cancels == before
    assert db.execute('SELECT address FROM next_mailbox').fetchone()[0] == 'ab'*16
    db.close()


def test_completion_polling_reconnect_and_shutdown_are_bounded(tmp_path):
    mailbox, db, router, now, connection = setup(tmp_path/'history.db')
    mailbox.configure({'address':'ab'*16}); connection[0] = ('radio',1)
    mailbox.tick(); mailbox.tick(force=True)
    assert len(router.requests) == 1  # No parallel download, even on repeated taps.
    router.propagation_transfer_state = router.PR_COMPLETE
    assert mailbox.tick()['last_checked_at'] == 1700000000
    now[0] += 299; mailbox.tick(); assert len(router.requests) == 1
    now[0] += 1; mailbox.tick(); assert len(router.requests) == 2
    connection[0] = None; mailbox.tick()
    assert router.propagation_transfer_state == router.PR_IDLE
    connection[0] = ('radio',2); mailbox.tick(); assert len(router.requests) == 3
    mailbox.close(); mailbox.tick(force=True); assert len(router.requests) == 3
    db.close()


def test_timeout_failure_backoff_disable_and_save_failure_preserve_data(tmp_path):
    mailbox, db, router, now, connection = setup(tmp_path/'history.db')
    db.execute('CREATE TABLE messages (text TEXT)'); db.execute("INSERT INTO messages VALUES ('keep')"); db.commit()
    mailbox.configure({'address':'ab'*16}); connection[0] = ('radio',1)
    mailbox.tick(); now[0] += 120
    assert mailbox.tick()['status'] == 'failed'
    now[0] += 59; mailbox.tick(); assert len(router.requests) == 1
    now[0] += 1; mailbox.tick(); assert len(router.requests) == 2
    db.execute('PRAGMA query_only=ON')
    with pytest.raises(sqlite3.OperationalError): mailbox.configure({'address':'cd'*16})
    assert mailbox.address == 'ab'*16 and router.propagation_transfer_state == 2
    db.execute('PRAGMA query_only=OFF')
    mailbox.configure({'address':''}); now[0] += 500; mailbox.tick(force=True)
    assert mailbox.snapshot()['status'] == 'off' and len(router.requests) == 2
    assert db.execute('SELECT text FROM messages').fetchone()[0] == 'keep'
    db.close()


def test_request_failure_is_visible_and_retries_without_reconnect(tmp_path):
    mailbox, db, router, now, connection = setup(tmp_path/'history.db')
    mailbox.configure({'address':'ab'*16}); connection[0] = ('radio',1)
    original = router.request_messages_from_propagation_node
    def fail(*args, **kwargs): raise OSError('private network detail must not be exposed')
    router.request_messages_from_propagation_node = fail
    result = mailbox.tick()
    assert result['status'] == 'failed' and 'private network' not in result['error']
    router.request_messages_from_propagation_node = original
    now[0] += 60
    assert mailbox.tick()['status'] == 'syncing'
    assert len(router.requests) == 1
    db.close()


@pytest.mark.parametrize("label", ["opportunistic", "direct", "propagated"])
def test_received_messages_show_the_actual_lxmf_delivery_method(label):
    from types import SimpleNamespace
    from loopback_probe import record
    import LXMF
    # Use library constants, not a fixture-specific interpretation of values.
    actual = {"opportunistic": LXMF.LXMessage.OPPORTUNISTIC, "direct": LXMF.LXMessage.DIRECT, "propagated": LXMF.LXMessage.PROPAGATED}[label]
    message = SimpleNamespace(fields={}, hash=b'a'*32, source_hash=b'b'*16,
        destination_hash=b'c'*16, timestamp=1700000000, method=actual,
        content_as_string=lambda: 'private synthetic message')
    assert record(message, 'received')['method'] == label
