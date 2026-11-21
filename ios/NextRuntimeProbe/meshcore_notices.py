"""Durable metadata-only alert queue for incoming MeshCore private messages."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading


class MeshCoreNotices:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self.path.chmod(0o600)
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS notices (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT NOT NULL UNIQUE, owner TEXT NOT NULL,
                target TEXT NOT NULL, payload TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS notices_target ON notices(owner,target,sequence)')

    @contextmanager
    def _db(self):
        with self.lock:
            connection = sqlite3.connect(self.path)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def save(self, event):
        # Location/control messages are filtered by the existing MeshCore store;
        # only its persisted direct-message alerts reach this queue. No text,
        # contact nickname, coordinates or attachment is copied here.
        if not isinstance(event, dict) or event.get('kind') != 'direct':
            return
        owner, target, message_id, created = (event.get(k) for k in ('owner','target','id','created'))
        if (not isinstance(owner,str) or not re.fullmatch('[a-f0-9]{64}',owner)
                or not isinstance(target,str) or not re.fullmatch('[a-f0-9]{64}',target)
                or not isinstance(message_id,str) or not 1 <= len(message_id) <= 128
                or type(created) not in (int,float) or not math.isfinite(created)):
            raise ValueError('Invalid persisted MeshCore alert')
        key = 'meshcore-' + hashlib.sha256(f'{owner}:direct:{target}'.encode()).hexdigest()
        if event.get('notification_key') != key:
            raise ValueError('MeshCore alert target mismatch')
        payload = dict(owner=owner,kind='direct',target=target,id=message_id,created=created,notification_key=key)
        fingerprint = hashlib.sha256(json.dumps([owner,'direct',target,message_id],separators=(',',':')).encode()).hexdigest()
        with self._db() as db:
            db.execute('INSERT OR IGNORE INTO notices(hash,owner,target,payload) VALUES (?,?,?,?)',
                       (fingerprint,owner,target,json.dumps(payload)))
            db.execute('DELETE FROM notices WHERE sequence < (SELECT COALESCE(MAX(sequence),0)-10000 FROM notices)')

    def candidates(self, store_factory, owners=None):
        with self._db() as db:
            rows = db.execute('''SELECT sequence,hash,payload FROM notices n
                WHERE sequence=(SELECT MAX(sequence) FROM notices latest
                    WHERE latest.owner=n.owner AND latest.target=n.target)
                ORDER BY sequence DESC LIMIT 100''').fetchall()
        if not rows:
            return []
        store = store_factory()
        result=[]
        for sequence, fingerprint, raw in rows:
            event=json.loads(raw)
            if owners is not None and event["owner"] not in owners:
                continue
            try:
                store.message_details(event['owner'],'direct',event['target'],event['id'])
                if not store.notification_allowed(event):
                    continue
            except (KeyError,ValueError):
                continue
            peer=hashlib.sha256(f"{event['owner']}:direct:{event['target']}".encode()).hexdigest()[:32]
            result.append(dict(id=sequence,hash=fingerprint,peer=peer,meshcoreKey=event['notification_key']))
        return result
