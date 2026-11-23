# SPDX-License-Identifier: 0BSD
"""Bounded private bookmarks and explicit page archives for the iOS browser."""
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import threading
import unicodedata


class NomadStore:
    max_page_bytes = 4 * 1_048_576
    max_archive_bytes = 32 * 1_048_576
    max_archives = 128
    max_versions = 5
    max_favourites = 1000

    def __init__(self, path):
        self.lock = threading.RLock()
        self.closed = False
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY, hash TEXT UNIQUE NOT NULL,
                destination_hash TEXT NOT NULL, page_path TEXT NOT NULL,
                content TEXT NOT NULL, created_at TEXT NOT NULL,
                size INTEGER NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS favourites (
                destination_hash TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                aspect TEXT NOT NULL, identify_on_connect INTEGER NOT NULL DEFAULT 0)''')
            self.db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        path.chmod(0o600)

    @staticmethod
    def address(value):
        if not isinstance(value, str) or not re.fullmatch('[a-fA-F0-9]{32}', value):
            raise ValueError('Enter a 32-character Reticulum destination')
        return value.lower()

    @staticmethod
    def page_path(value):
        if (not isinstance(value, str) or not value.startswith('/')
                or len(value.encode('utf-8')) > 2048
                or any(ord(c) < 32 for c in value)):
            raise ValueError('Enter a page path beginning with /')
        return value

    def archive_page(self, address, path, content):
        address, path = self.address(address), self.page_path(path)
        if not isinstance(content, str):
            raise ValueError('A page must contain text')
        encoded = content.encode('utf-8')
        if not 0 < len(encoded) <= self.max_page_bytes:
            raise ValueError('This page exceeds the archive size limit')
        digest = hashlib.sha256(address.encode() + b'\0' + path.encode() + b'\0' + encoded).hexdigest()
        with self.lock, self.db:
            self.db.execute('''INSERT OR IGNORE INTO pages
                (hash,destination_hash,page_path,content,created_at,size) VALUES (?,?,?,?,?,?)''',
                (digest, address, path, content, datetime.now(timezone.utc).isoformat(), len(encoded)))
            self.db.execute('''DELETE FROM pages WHERE destination_hash=? AND page_path=? AND id NOT IN
                (SELECT id FROM pages WHERE destination_hash=? AND page_path=? ORDER BY id DESC LIMIT ?)''',
                (address, path, address, path, self.max_versions))
            self.db.execute('''DELETE FROM pages WHERE id NOT IN
                (SELECT id FROM pages ORDER BY id DESC LIMIT ?)''', (self.max_archives,))
            while self.db.execute('SELECT COALESCE(sum(size),0) FROM pages').fetchone()[0] > self.max_archive_bytes:
                self.db.execute('DELETE FROM pages WHERE id=(SELECT min(id) FROM pages)')
            row = self.db.execute('SELECT * FROM pages WHERE hash=?', (digest,)).fetchone()
            return dict(row) if row else None

    def get_archived_page_versions(self, address, path):
        address, path = self.address(address), self.page_path(path)
        with self.lock:
            return [dict(row) for row in self.db.execute('''SELECT id,hash,destination_hash,page_path,created_at
                FROM pages WHERE destination_hash=? AND page_path=? ORDER BY id DESC''', (address, path))]

    def get_archived_page_by_id(self, identifier):
        if type(identifier) is not int or not 0 < identifier < 2**63:
            return None
        with self.lock:
            row = self.db.execute('SELECT * FROM pages WHERE id=?', (identifier,)).fetchone()
            return dict(row) if row else None

    def archives(self):
        with self.lock:
            return [dict(row) for row in self.db.execute('''SELECT id,hash,destination_hash,page_path,created_at,size
                FROM pages ORDER BY id DESC''')]

    def archive_rows(self, query='', destination=None, *, include_content=False):
        if not isinstance(query, str) or len(query) > 256:
            raise ValueError('Enter a shorter archive search')
        if destination is not None: destination = self.address(destination)
        columns = "p.id,p.hash,p.destination_hash,p.page_path,p.created_at,p.size,COALESCE(f.display_name,'') AS node_name,"
        columns += 'p.content' if include_content else 'substr(p.content,1,2000) AS preview'
        conditions, values = [], []
        if destination:
            conditions.append('p.destination_hash=?'); values.append(destination)
        if query:
            conditions.append("(instr(lower(p.page_path),lower(?))>0 OR instr(lower(p.content),lower(?))>0 OR instr(lower(COALESCE(f.display_name,'')),lower(?))>0)")
            values.extend((query, query, query))
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        with self.lock:
            if self.closed: return []
            return [dict(row) for row in self.db.execute('SELECT ' + columns +
                ' FROM pages p LEFT JOIN favourites f ON f.destination_hash=p.destination_hash' + where + ' ORDER BY p.id DESC', values)]

    def remove_archives(self, identifiers=None):
        if identifiers is not None and (not isinstance(identifiers, list) or len(identifiers) > self.max_archives
                or any(type(value) is not int or not 0 < value < 2**63 for value in identifiers)):
            raise ValueError('Choose saved pages to remove')
        with self.lock, self.db:
            if identifiers is None:
                self.db.execute('DELETE FROM pages')
            else:
                self.db.executemany('DELETE FROM pages WHERE id=?', ((value,) for value in identifiers))

    def save_favourite(self, address, name, *, identify=False):
        address = self.address(address)
        if not isinstance(name, str) or len(name.encode('utf-8')) > 512 or type(identify) is not bool:
            raise ValueError('Enter a short bookmark name and an identification preference')
        name = ''.join(c for c in name if not unicodedata.category(c).startswith('C')).strip() or address
        with self.lock, self.db:
            existing = self.db.execute('SELECT 1 FROM favourites WHERE destination_hash=?', (address,)).fetchone()
            if existing is None and self.db.execute('SELECT count(*) FROM favourites').fetchone()[0] >= self.max_favourites:
                raise ValueError('The bookmark limit has been reached')
            self.db.execute('''INSERT INTO favourites VALUES (?,?,'nomadnetwork.node',?)
                ON CONFLICT(destination_hash) DO UPDATE SET display_name=excluded.display_name,
                identify_on_connect=excluded.identify_on_connect''', (address, name, int(identify)))
        return self.favourite(address)

    def favourite(self, address):
        address = self.address(address)
        with self.lock:
            row = self.db.execute('SELECT * FROM favourites WHERE destination_hash=?', (address,)).fetchone()
            return dict(row) if row else None

    def favourites(self):
        with self.lock:
            return [dict(row) for row in self.db.execute('SELECT * FROM favourites ORDER BY display_name COLLATE NOCASE,destination_hash')]

    def should_identify_on_connect(self, address):
        row = self.favourite(address)
        return bool(row and row['identify_on_connect'])

    def remove_favourite(self, address):
        address = self.address(address)
        with self.lock, self.db:
            self.db.execute('DELETE FROM favourites WHERE destination_hash=?', (address,))

    def import_favourites(self, entries):
        if not isinstance(entries, list) or len(entries) > self.max_favourites:
            raise ValueError('Choose at most 1000 NomadNet bookmarks')
        proposed = {}
        for entry in entries:
            if not isinstance(entry, dict) or entry.get('aspect', 'nomadnetwork.node') != 'nomadnetwork.node':
                raise ValueError('This browser imports NomadNet bookmarks only')
            address = self.address(entry.get('destination_hash'))
            name = entry.get('display_name', '')
            if not isinstance(name, str) or len(name.encode('utf-8')) > 512:
                raise ValueError('Enter a short bookmark name')
            name = ''.join(c for c in name if not unicodedata.category(c).startswith('C')).strip() or address
            proposed[address] = name
        with self.lock, self.db:
            existing = {row['destination_hash']: bool(row['identify_on_connect']) for row in self.db.execute('SELECT * FROM favourites')}
            if len(set(existing) | set(proposed)) > self.max_favourites:
                raise ValueError('The bookmark limit has been reached')
            # Imported data cannot authorize new identity disclosure. Preserve
            # only identification the user already explicitly enabled locally.
            self.db.executemany("""INSERT INTO favourites VALUES (?,?,'nomadnetwork.node',?)
                ON CONFLICT(destination_hash) DO UPDATE SET display_name=excluded.display_name""",
                ((address, name, int(existing.get(address, False))) for address, name in proposed.items()))
        return len(proposed)

    def layout(self):
        with self.lock:
            row = self.db.execute("SELECT value FROM metadata WHERE key='layout'").fetchone()
            return json.loads(row[0]) if row else None

    def save_layout(self, value):
        from meshchatnext.src.backend.favourites_layout import MAX_LAYOUT_JSON_BYTES, normalize_favourites_layout
        if len(json.dumps(value, ensure_ascii=False).encode('utf-8')) > MAX_LAYOUT_JSON_BYTES:
            raise ValueError('The bookmark layout is too large')
        normal = normalize_favourites_layout(value)
        if normal is None:
            raise ValueError('Choose valid bookmark sections')
        for section, addresses in normal['favouritesBySection'].items():
            accepted = []
            for address in addresses:
                if re.fullmatch('[a-fA-F0-9]{32}', address) and address.lower() not in accepted:
                    accepted.append(address.lower())
            normal['favouritesBySection'][section] = accepted
        encoded = json.dumps(normal, ensure_ascii=False, separators=(',', ':'))
        with self.lock, self.db:
            self.db.execute("INSERT INTO metadata VALUES ('layout',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encoded,))
        return normal

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.db.close()
