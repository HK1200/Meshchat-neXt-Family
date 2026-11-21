"""Durable unread alert metadata without message content or radio access."""
import hashlib
from pathlib import Path
import stat
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe'))
from meshcore_notices import MeshCoreNotices

OWNER='a'*64
PEER='b'*64


def event(message='first',owner=OWNER,target=PEER):
    return dict(owner=owner,target=target,kind='direct',id=message,created=100,
                notification_key='meshcore-'+hashlib.sha256(f'{owner}:direct:{target}'.encode()).hexdigest(),
                text='private example content not retained',name='private nickname')


class Store:
    def __init__(self):self.read=False;self.deleted=False
    def message_details(self,*args):
        if self.deleted:raise ValueError('deleted')
        return {}
    def notification_allowed(self,event):return not self.read


def test_unread_notice_persists_without_text_and_duplicates_once(tmp_path):
    path=tmp_path/'alerts.sqlite3';queue=MeshCoreNotices(path);store=Store()
    queue.save(event());first=queue.candidates(lambda:store)
    queue.save(event());assert queue.candidates(lambda:store)==first
    assert len(first)==1 and first[0]['meshcoreKey']==event()['notification_key']
    assert set(first[0])=={'id','hash','peer','meshcoreKey'}
    assert len(first[0]['hash'])==64 and len(first[0]['peer'])==32
    assert MeshCoreNotices(path).candidates(lambda:store)==first
    assert stat.S_IMODE(path.stat().st_mode)==0o600
    data=path.read_bytes()
    assert b'private example content' not in data and b'private nickname' not in data
    queue.save(event('second'));assert queue.candidates(lambda:store)[0]['id']>first[0]['id']
    assert len(queue.candidates(lambda:store))==1


def test_read_or_deleted_messages_do_not_alert(tmp_path):
    queue=MeshCoreNotices(tmp_path/'alerts.sqlite3');queue.save(event());store=Store()
    store.read=True;assert queue.candidates(lambda:store)==[]
    store.read=False;store.deleted=True;assert queue.candidates(lambda:store)==[]


def test_empty_queue_does_not_open_message_store_and_owners_are_separate(tmp_path):
    queue=MeshCoreNotices(tmp_path/'alerts.sqlite3')
    assert queue.candidates(lambda:pytest.fail('unconfigured radio store was opened'))==[]
    queue.save(event());queue.save(event(owner='c'*64))
    candidates=queue.candidates(Store)
    assert len(candidates)==2 and len({row['peer'] for row in candidates})==2


def test_non_private_events_are_not_turned_into_private_alerts(tmp_path):
    queue=MeshCoreNotices(tmp_path/'alerts.sqlite3')
    for kind in ['channel','tactical',None]:queue.save(dict(event(),kind=kind))
    assert queue.candidates(Store)==[]


@pytest.mark.parametrize('changes',[{'owner':OWNER+'\n'},{'target':'https://example.invalid'},{'id':''},{'created':float('nan')},{'notification_key':'meshcore-'+'0'*64}])
def test_invalid_events_are_rejected(tmp_path,changes):
    queue=MeshCoreNotices(tmp_path/'alerts.sqlite3')
    with pytest.raises(ValueError):queue.save(dict(event(),**changes))
    assert queue.candidates(Store)==[]


def test_removed_radio_identity_cannot_generate_native_alerts(tmp_path):
    queue=MeshCoreNotices(tmp_path/'alerts.sqlite3');queue.save(event())
    assert queue.candidates(Store, owners=set())==[]
    assert queue.candidates(Store, owners={'c'*64})==[]
    assert len(queue.candidates(Store, owners={OWNER}))==1
