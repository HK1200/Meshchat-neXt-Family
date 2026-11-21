"""The released Reticulum Relay Chat client/server in isolated neXt storage."""
import asyncio
import contextlib
from pathlib import Path


class RelayRuntime:
    def __init__(self, folder, identity, reticulum, contacts, nickname, broadcast):
        from meshchatnext.src.backend.database import Database
        from meshchatnext.src.backend.config_manager import ConfigManager
        self.loop=asyncio.get_running_loop()
        self.folder=Path(folder)/'relay-chat';self.folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.database=Database(str(self.folder/'rooms.sqlite3'));self.database.initialize()
        self.config=ConfigManager(self.database)
        self.contacts=contacts;self.names={};self.refresh_contacts()
        self.nickname=nickname;self.identity=identity;self.closed=False;self.enabled=False;self.broadcast=broadcast
        self.rrc_manager=None;self.rrc_server_manager=None
        self.lifecycle_lock=asyncio.Lock()
        import threading
        self.discovery_lock=threading.RLock();self.discovery_registered=False
        self.reticulum=reticulum
        from meshchatnext.src.backend.announce_manager import AnnounceManager
        self.announces=AnnounceManager(self.database,self.config)
        self.aspect_filter="rrc.hub"

    def make_managers(self):
        from meshchatnext.src.backend.rrc.manager import RRCManager
        from meshchatnext.src.backend.rrc.server import RRCServerManager
        self.rrc_manager=RRCManager(self.identity,str(self.folder),get_nickname=self.nickname,
            get_name_for_identity_hash=self.contact_name,database=self.database)
        self.rrc_server_manager=RRCServerManager(str(self.folder),owner_identity=self.identity.hash)
        self.rrc_manager.set_server_manager(self.rrc_server_manager)
        self.rrc_manager.set_change_callback(lambda hub:self.emit({'type':'rrc.change','hub_hash':hub.hub_hash.hex() if hub else None}))
        self.rrc_server_manager.set_change_callback(lambda hub:self.emit({'type':'rrc.server.change','hub_id':hub.hub_id if hub else None}))
        self.rrc_manager.set_message_callback(self.message)

    def settings(self):
        return {'rrc_enabled':self.config.rrc_enabled.get(),
                'rrc_unread_badges_enabled':self.config.rrc_unread_badges_enabled.get()}

    async def configure(self,payload):
        if (not isinstance(payload,dict) or not payload or set(payload)-set(self.settings())
                or any(type(value) is not bool for value in payload.values())):
            raise ValueError('Relay Chat switches must be on or off')
        async with self.lifecycle_lock:
            with self.database.provider:
                for key,value in payload.items():getattr(self.config,key).set(value)
            self.enabled=self.config.rrc_enabled.get()
            if self.enabled:
                if self.rrc_manager is None:
                    self.make_managers()
                    await asyncio.to_thread(self.rrc_server_manager.load)
                    await asyncio.to_thread(self.rrc_manager.load)
                    # Loading restores rooms/keys/history; the released service
                    # deliberately starts saved auto-reconnect hubs separately.
                    await asyncio.to_thread(self.rrc_manager.connect_auto_reconnect_hubs)
            else:await self.stop_managers()
        return self.settings()

    async def stop_managers(self):
        client,self.rrc_manager=self.rrc_manager,None
        server,self.rrc_server_manager=self.rrc_server_manager,None
        if client is not None:await asyncio.to_thread(client.shutdown)
        if server is not None:await asyncio.to_thread(server.shutdown)

    def refresh_contacts(self):
        # RNS callbacks run on workers; they must not access the UI-owned
        # conversation SQLite connection.
        self.names={key:row['name'] for key,row in self.contacts().items()}

    def contact_name(self, identity_hash):
        import RNS
        try:
            value=bytes.fromhex(identity_hash) if isinstance(identity_hash,str) else bytes(identity_hash)
            if len(value)!=16:return None
            peer=RNS.Destination.hash_from_name_and_identity('lxmf.delivery',value).hex()
            return self.names.get(peer)
        except (ValueError,TypeError):return None

    def emit(self,event):
        if not self.closed and self.enabled:
            with contextlib.suppress(RuntimeError):
                self.loop.call_soon_threadsafe(self.broadcast,event)

    def message(self,hub,message):
        self.emit({'type':'rrc.message','hub_hash':hub.hub_hash.hex() if hub else None,
                   'room':message.room,'message':message.to_dict(),'mention':bool(getattr(message,'mention',False))})

    def _mark_rrc_mention_notifications_viewed(self,hub,room):
        from meshchatnext.src.backend.rrc.protocol import normalize_room
        if room:
            with contextlib.suppress(ValueError):
                self.database.misc.dismiss_unviewed_notifications(notification_type='rrc_mention',
                    remote_hash=hub+':'+normalize_room(room))

    def received_announce(self,destination_hash,announced_identity,app_data):
        import RNS
        with self.discovery_lock:
            if self.closed or not self.enabled or not isinstance(destination_hash,bytes) or len(destination_hash)!=16:return
            if destination_hash!=RNS.Destination.hash_from_name_and_identity(self.aspect_filter,announced_identity.hash):return
            self.announces.upsert_announce(self.reticulum,announced_identity,destination_hash,self.aspect_filter,app_data,None)
            self.database.announces.trim_announces_for_aspect(self.aspect_filter,2500)
            manager=self.rrc_manager
            if manager:
                hub=manager.find_hub_by_hex(destination_hash.hex())
                if hub:hub.note_hub_announce()

    def discovered(self,query):
        import base64
        from meshchatnext.src.backend.rrc import protocol
        if not self.enabled:return []
        try:limit=int(query.get('limit',200))
        except (ValueError,TypeError):raise ValueError('Choose a valid hub list limit') from None
        if not 0<=limit<=2500:raise ValueError('Choose a valid hub list limit')
        rows=self.announces.get_filtered_announces(aspect=self.aspect_filter,limit=limit)
        search=str(query.get('search') or query.get('query') or '').casefold()
        result=[]
        for row in rows:
            entry=dict(row);name=''
            with contextlib.suppress(Exception):
                metadata=protocol.decode(base64.b64decode(entry.get('app_data') or ''))
                if isinstance(metadata,dict) and isinstance(metadata.get('hub'),str):
                    name=''.join(c for c in metadata['hub'] if c.isprintable())[:120]
            entry['display_name']=name or 'Relay Chat hub'
            if not search or search in entry['display_name'].casefold() or search in entry['destination_hash']:
                result.append(entry)
        return result

    def register(self,router):
        from aiohttp import web
        from meshchatnext.src.backend.http.routes.rrc import register_rrc_routes
        routes=web.RouteTableDef();register_rrc_routes(routes,self);router.add_routes(routes)

    async def start(self):
        # Empty first-run configuration creates no room/server and sends no
        # announce. Stored auto-reconnect choices are the user's own settings.
        import RNS
        if not self.discovery_registered:
            RNS.Transport.register_announce_handler(self);self.discovery_registered=True
        await self.configure({'rrc_enabled':self.config.rrc_enabled.get()})

    async def close(self):
        import RNS
        with self.discovery_lock:
            self.closed=True
            if self.discovery_registered:
                RNS.Transport.deregister_announce_handler(self);self.discovery_registered=False
        async with self.lifecycle_lock:await self.stop_managers()
        self.database.provider.close_all()
