"""Released block-destination API, guarded by the loopback session middleware."""
import json
import sqlite3
from aiohttp import web


class BlockRuntime:
    def __init__(self, blocks, history, organization, revoke, changed):
        self.blocks, self.history, self.organization = blocks, history, organization
        self.revoke, self.changed = revoke, changed

    def register(self, router):
        router.add_get('/api/v1/blocked-destinations', self.api)
        router.add_post('/api/v1/blocked-destinations', self.api)
        router.add_delete('/api/v1/blocked-destinations/{peer}', self.api)

    async def api(self, request):
        try:
            if request.method == 'GET':
                return web.json_response({'blocked_destinations':self.blocks.snapshot()},
                                         headers={'Cache-Control':'no-store'})
            if request.method == 'POST':
                raw = bytearray()
                async for part in request.content.iter_chunked(4096):
                    raw.extend(part)
                    if len(raw) > 4096: raise ValueError('Block settings are too large')
                body = json.loads(raw)
                if not isinstance(body, dict) or set(body) != {'destination_hash'}:
                    raise ValueError('Choose the Reticulum destination to block')
                keys = self.blocks.checked_aliases(body['destination_hash'])
                # Revoke local sending consent before removing its contact.
                await self.revoke(keys)
                self.blocks.add(body['destination_hash'])
                known = [key for key in keys if key in self.history.contacts()
                         or self.history.has_conversation(key)]
                if known: self.organization.delete_conversations(known)
                with self.history.db:
                    self.history.db.executemany('DELETE FROM contacts WHERE lxmf_address = ?', [(key,) for key in keys])
                    self.history.db.executemany('DELETE FROM destination_names WHERE address = ?', [(key,) for key in keys])
            else:
                self.blocks.remove(request.match_info['peer'])
            await self.changed()
            return web.json_response({'message':'ok'})
        except (ValueError, TypeError) as error:
            return web.json_response({'message':str(error)}, status=400)
        except (OSError, RuntimeError, sqlite3.Error):
            return web.json_response({'message':'Blocking could not finish. Review blocked destinations before retrying.'}, status=503)
