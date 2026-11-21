"""Transport acknowledgment follows the real SQLite commit on the owning loop."""
import asyncio
from pathlib import Path
import sqlite3
import sys
import threading
import time

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe'))
from durable_inbox import DurableInbox


def test_transport_thread_waits_until_its_row_is_durably_committed(tmp_path):
    async def run():
        path = tmp_path/'inbox.sqlite3'
        db = sqlite3.connect(path); db.execute('create table received (body text)'); db.commit()
        owner = threading.get_ident()
        def commit(row):
            assert threading.get_ident() == owner
            with db: db.execute('insert into received values (?)', (row,))
            return True
        inbox = DurableInbox(asyncio.get_running_loop(), commit)
        assert await asyncio.to_thread(inbox.receive, 'signed private fixture')
        with sqlite3.connect(path) as reader:
            assert reader.execute('select body from received').fetchall() == [('signed private fixture',)]
        assert not inbox.error
        inbox.close(); db.close()
    asyncio.run(run())


def test_failed_or_unspecified_commit_is_never_acknowledged():
    async def run():
        def failed(_row): raise OSError('synthetic storage failure')
        for commit in [failed, lambda _: False, lambda _: None]:
            inbox = DurableInbox(asyncio.get_running_loop(), commit)
            assert await asyncio.to_thread(inbox.receive, 'private fixture') is False
            assert inbox.error
            inbox.close()
    asyncio.run(run())


def test_same_loop_delivery_does_not_deadlock_waiting_for_itself():
    async def run():
        committed = []
        def commit(row): committed.append(row); return True
        inbox = DurableInbox(asyncio.get_running_loop(), commit)
        assert inbox.receive('same-loop fixture')
        assert committed == ['same-loop fixture']
        inbox.close()
    asyncio.run(run())


def test_timeout_cancels_an_unstarted_write_instead_of_acknowledging_it():
    async def run():
        committed = []
        def commit(row): committed.append(row); return True
        inbox = DurableInbox(asyncio.get_running_loop(), commit, timeout=.03)
        results = []
        worker = threading.Thread(target=lambda: results.append(inbox.receive('timed-out fixture')))
        worker.start()
        # Deliberately keep the loop occupied until this bounded worker expires.
        worker.join(timeout=1)
        assert not worker.is_alive() and results == [False]
        await asyncio.sleep(.01)
        assert committed == []
        inbox.close()
    asyncio.run(run())


def test_shutdown_releases_waiting_workers_without_writing_or_acknowledging():
    async def run():
        inbox = DurableInbox(asyncio.get_running_loop(), lambda _: True)
        results = []
        worker = threading.Thread(target=lambda: results.append(inbox.receive('pending fixture')))
        worker.start()
        deadline = time.monotonic() + 1
        while not inbox.pending and time.monotonic() < deadline: time.sleep(.001)
        inbox.close(); worker.join(timeout=1)
        assert not worker.is_alive() and results == [False]
        assert inbox.receive('closed fixture') is False
        await asyncio.sleep(.01)
    asyncio.run(run())


@pytest.mark.parametrize('timeout', [0, -1, 31, True, float('inf'), float('nan'), '20'])
def test_wait_budget_is_bounded(timeout):
    async def run():
        with pytest.raises(ValueError): DurableInbox(asyncio.get_running_loop(), lambda _: True, timeout=timeout)
    asyncio.run(run())
