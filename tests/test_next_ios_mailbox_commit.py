"""Real encrypted relay messages remain available after a failed neXt inbox save."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import os
import socket
import sys
import time

from test_ios_tcp_runtime import run_mailbox, run_mailbox_sender, start_process

ROOT = Path(__file__).resolve().parents[1]


def run_recipient(folder, port, mailbox, known_sender, pipe):
    sys.path[:0] = [str(ROOT/'ios/NextRuntimeProbe'), str(ROOT/'app/src/main/python')]
    from durable_inbox import DurableInbox
    from offline_mailbox import OfflineMailbox
    from loopback_probe import ConversationHistory, record
    from messaging_probe import MessagingProbe
    import RNS

    async def run():
        folder.mkdir(exist_ok=True)
        fail = True
        def commit(row):
            if fail: raise OSError('synthetic private inbox save failure')
            history.save(row['source_hash'], row)
            return True
        inbox = DurableInbox(asyncio.get_running_loop(), commit)
        probe = MessagingProbe(dict(peers=[dict(id='private',host='127.0.0.1',port=port,enabled=True)]),
                               folder, lambda message: inbox.receive(record(message, 'received')), device=False)
        history = ConversationHistory(folder/'history.sqlite3')
        receiver = OfflineMailbox(history.db, probe.router, probe.source.identity,
                                  lambda: ('test-peer', 1) if probe.connections.online else None)
        receiver.configure({'address': mailbox})
        address, public_key = known_sender
        identity = RNS.Identity(create_keys=False); identity.load_public_key(bytes.fromhex(public_key))
        assert RNS.Destination.hash_from_name_and_identity('lxmf.delivery', identity).hex() == address
        # Supply the trusted fixture's public announce identity, not a contact
        # approval. The other sender intentionally remains unverifiable.
        RNS.Identity.remember(None, bytes.fromhex(address), bytes.fromhex(public_key))
        pipe.send(probe.source.identity.get_public_key())
        def snapshot():
            return dict(online=probe.connections.online, phase=probe.router.propagation_transfer_state,
                        complete=probe.router.propagation_transfer_state == probe.router.PR_COMPLETE,
                        count=history.db.execute('select count(*) from messages').fetchone()[0],
                        contacts=len(history.contacts()),
                        texts=[row['content'] for peer in history.conversation_entries() for row in history.page(peer,{})],
                        save_error=bool(inbox.error))
        try:
            while True:
                command = await asyncio.to_thread(pipe.recv)
                if command == 'status': pipe.send(snapshot())
                elif command == 'allow-save': fail = False; pipe.send(True)
                elif command == 'sync':
                    receiver.tick(force=True)
                    pipe.send(snapshot())
                else: break
        finally:
            inbox.close(); receiver.close(); probe.close(); history.close()
    asyncio.run(run())


def rpc(pipe, command):
    pipe.send(command)
    assert pipe.poll(10), 'Private recipient did not respond'
    return pipe.recv()


def wait(pipe, predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = rpc(pipe, 'status')
        if predicate(value): return value
        time.sleep(.1)
    raise AssertionError('Private neXt mailbox condition timed out')


def test_real_mailbox_retains_messages_until_next_inbox_commit_succeeds(tmp_path, monkeypatch):
    source = str(ROOT/'app/src/main/python')
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([source, str(ROOT/'ios/NextRuntimeProbe'), os.environ.get('PYTHONPATH','')]))
    monkeypatch.syspath_prepend(source)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0)); port = listener.getsockname()[1]
    with ExitStack() as stack:
        relay = start_process(stack, run_mailbox, tmp_path/'relay', port)
        assert relay.poll(10); mailbox = relay.recv()
        sender = start_process(stack, run_mailbox_sender, tmp_path/'sender', port, mailbox)
        assert sender.poll(10); known_sender = sender.recv()
        folder = tmp_path/'next'
        with ExitStack() as first:
            recipient = start_process(first, run_recipient, folder, port, mailbox, known_sender)
            assert recipient.poll(10); public_key = recipient.recv()
        sender.send(public_key)
        assert sender.poll(55) and sender.recv()
        recipient = start_process(stack, run_recipient, folder, port, mailbox, known_sender)
        assert recipient.poll(10); assert recipient.recv() == public_key
        wait(recipient, lambda s:s['online'])
        rpc(recipient, 'sync')
        failed = wait(recipient, lambda s:s['complete'])
        assert failed['count'] == 0 and failed['save_error']
        rpc(recipient, 'allow-save'); rpc(recipient, 'sync')
        saved = wait(recipient, lambda s:s['complete'] and s['count'] == 1)
        assert saved['texts'] == ['Approved while offline']
        assert saved['contacts'] == 0
        assert not saved['save_error']
        # A verified adult neXt sender may start a chat without being in the
        # phonebook. Unknown signing keys are not treated as valid messages.
        rpc(recipient, 'sync')
        repeated = wait(recipient, lambda s:s['complete'])
        assert repeated['count'] == 1
