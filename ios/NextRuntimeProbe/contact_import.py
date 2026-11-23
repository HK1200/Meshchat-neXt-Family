"""Review a Reticulum contact code without trusting names or adding it silently."""
import json
import re
import sqlite3
from aiohttp import web
from family_cards import parse, validate_public_key


class ContactImport:
    def __init__(self, history, blocks, own, changed, remember=None, before_change=None):
        self.history, self.blocks, self.own, self.changed = history, blocks, own, changed
        if remember is None:
            import RNS
            remember = lambda address, key:RNS.Identity.remember(None, bytes.fromhex(address), bytes.fromhex(key))
        self.remember = remember
        self.before_change = before_change
        with history.db:
            history.db.execute('CREATE TABLE IF NOT EXISTS next_contact_import_keys (address TEXT PRIMARY KEY, public_key TEXT NOT NULL)')
            history.db.execute('CREATE TRIGGER IF NOT EXISTS next_remove_import_key AFTER DELETE ON contacts BEGIN DELETE FROM next_contact_import_keys WHERE address = OLD.lxmf_address; END')
        # Only keys from explicitly saved contacts may be restored. Corrupt or
        # subsequently banished rows cannot seed Reticulum's identity cache.
        for peer, key in history.db.execute('SELECT k.address,k.public_key FROM next_contact_import_keys k JOIN contacts c ON c.lxmf_address = k.address LIMIT 10000'):
            try: value = self.decode('lxma://' + peer + ':' + key)
            except (ValueError, TypeError): continue
            self.remember(value['address'], value['key'])

    def decode(self, code):
        if not isinstance(code, str) or not 0 < len(code.encode('utf-8')) <= 8192:
            raise ValueError('Choose a contact code of up to 8 KB')
        if code.strip().startswith('{'):
            card = json.loads(code)
            if (not isinstance(card, dict) or type(card.get('version')) is not int
                    or set(card) - {'format','version','name','addresses','identityPublicKey'}
                    or not isinstance(card.get('name',''), str)):
                raise ValueError('Invalid Family contact card')
        value = parse(code)
        addresses = value.get('addresses')
        if not isinstance(addresses, dict): raise ValueError('Invalid contact addresses')
        address = addresses.get('lxmf')
        if not isinstance(address, str) or not re.fullmatch('[a-fA-F0-9]{32}', address):
            raise ValueError('Choose a Reticulum messaging contact code. MeshCore and SIP contacts use their own service menus.')
        address = address.lower()
        if address == self.own or address in self.blocks.own: raise ValueError('This code belongs to your own Reticulum identity')
        if self.blocks.denies(address): raise ValueError('Unblock this Reticulum contact before adding it')
        key = value.get('identityPublicKey')
        if key is not None:
            import RNS
            key = validate_public_key(address, key)
            identity = RNS.Identity(create_keys=False); identity.load_public_key(bytes.fromhex(key))
            if any(self.blocks.denies(peer) for peer in (identity.hash.hex(),
                    RNS.Destination.hash_from_name_and_identity('lxst.telephony', identity).hex())):
                raise ValueError('Unblock this Reticulum contact before adding it')
        name = self.history.contact_name(value.get('name',''), allow_empty=True)
        return {'address':address, 'name':name, 'key':key,
                'additional_services':sorted(service for service in ('meshcore','sip') if addresses.get(service))}

    def preview(self, code):
        value = self.decode(code)
        existing = self.history.contacts().get(value['address'])
        return {'address':value['address'], 'name':existing['name'] if existing else value['name'],
                'exists':existing is not None, 'public_key_matches':value['key'] is not None,
                'additional_services':value['additional_services']}

    def register(self, router):
        router.add_post('/api/v1/preview/contact-import/preview', self.api)
        router.add_post('/api/v1/preview/contact-import/save', self.api)

    async def api(self, request):
        try:
            raw = bytearray()
            async for part in request.content.iter_chunked(4096):
                raw.extend(part)
                if len(raw) > 50000: raise ValueError('The contact request is too large')
            body = json.loads(raw)
            saving = request.path.endswith('/save')
            if not isinstance(body,dict) or set(body) != ({'code','name'} if saving else {'code'}):
                raise ValueError('Choose one contact code and review its name')
            value = self.decode(body['code'])
            if saving:
                if value['address'] in self.history.contacts():
                    return web.json_response({'message':'That Reticulum contact is already saved'}, status=409)
                name = self.history.contact_name(body['name'])
                if value['key'] and self.history.db.execute('SELECT COUNT(*) FROM next_contact_import_keys').fetchone()[0] >= 10000:
                    raise ValueError('At most 10,000 contact public keys may be saved')
                if self.before_change: self.before_change()
                with self.history.db:
                    self.history.db.execute('INSERT INTO contacts(lxmf_address,name) VALUES (?,?)', (value['address'],name))
                    self.history.db.execute('DELETE FROM hidden_conversations WHERE peer = ?', (value['address'],))
                    if value['key']:
                        self.history.db.execute('INSERT INTO next_contact_import_keys VALUES (?,?)', (value['address'],value['key']))
                # A manually imported public key is bound to the destination
                # before it enters Reticulum's cache. Preview never remembers it.
                if value['key']: self.remember(value['address'],value['key'])
                await self.changed()
            return web.json_response(self.preview(body['code']), headers={'Cache-Control':'no-store'})
        except (ValueError, TypeError, KeyError) as error:
            return web.json_response({'message':str(error)}, status=400)
        except (OSError, RuntimeError, sqlite3.Error):
            return web.json_response({'message':'The contact could not finish saving. Review Contacts before retrying.'}, status=503)
