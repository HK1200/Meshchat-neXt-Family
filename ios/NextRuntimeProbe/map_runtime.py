"""The released neXt map services, isolated in this app's own storage."""
from pathlib import Path


class MapRuntime:
    def __init__(self, folder, identity, reticulum, broadcast):
        from meshchatnext.src.backend.config_manager import ConfigManager
        from meshchatnext.src.backend.database import Database
        from meshchatnext.src.backend.map_manager import MapManager
        from meshchatnext.src.backend.map_overlay_manager import MapOverlayManager
        from meshchatnext.src.backend.map_data_manager import MapDataManager
        from meshchatnext.src.backend.rns_link_manager import RnsLinkManager
        import threading
        self.identity = identity
        self.reticulum = reticulum
        self.discovery_lock = threading.RLock()
        self.closed = False
        self.discovery_registered = False
        self.folder = Path(folder) / "map-tools"
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database = Database(str(self.folder / "tools.sqlite3"))
        self.database.initialize()
        self.config = ConfigManager(self.database)
        directory = self.folder / "maps"
        directory.mkdir(mode=0o700, exist_ok=True)
        if self.config.map_mbtiles_dir.get() is None: self.config.map_mbtiles_dir.set(str(directory))
        self.map_manager = MapManager(self.config, str(self.folder))
        self.regional_map_download = None
        self.links = RnsLinkManager(self_identity_getter=lambda: identity,
                                   reticulum_getter=lambda: reticulum, broadcast_event=broadcast)
        self.map_overlay_manager = MapOverlayManager(self.config, self.database, str(self.folder),
            identity=identity, reticulum=reticulum)
        self.map_data_manager = MapDataManager(self.config, self.database, str(self.folder), identity,
            reticulum=reticulum, link_manager_getter=lambda: self.links,
            overlay_manager_getter=lambda: self.map_overlay_manager)
        from meshchatnext.src.backend.announce_manager import AnnounceManager
        from meshchatnext.src.backend.map_data_manager import MAP_ASPECT
        self.announces = AnnounceManager(self.database, self.config)
        self.aspect_filter = MAP_ASPECT
        self.map_keys = {key for key in vars(self.config) if key.startswith("map_")} | {"announce_store_map_data"}

    def settings(self):
        return {key: getattr(self.config, key).get() for key in self.map_keys}

    def update_settings(self, values):
        """Validate the whole request before any writes; paths use dedicated routes."""
        from meshchatnext.src.backend.config_manager import ConfigManager
        from meshchatnext.src.backend.map_overlay_manager import CONFIG_CLAMPS
        if not isinstance(values, dict) or not values or set(values) - self.map_keys:
            raise ValueError("Choose supported map settings")
        for key, value in values.items():
            item = getattr(self.config, key)
            if key in ("map_offline_path", "map_mbtiles_dir"):
                raise ValueError("Select map files using the offline map controls")
            if isinstance(item, ConfigManager.BoolConfig):
                if type(value) is not bool: raise ValueError("Map switches must be on or off")
            elif isinstance(item, ConfigManager.IntConfig):
                if type(value) is not int: raise ValueError("Use a whole-number map setting")
            elif not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
                raise ValueError("Use a valid map setting")
            if key in CONFIG_CLAMPS and not CONFIG_CLAMPS[key][0] <= value <= CONFIG_CLAMPS[key][1]:
                raise ValueError("Map setting is outside the supported range")
            if key == "map_default_zoom" and not 0 <= value <= 22:
                raise ValueError("Choose a map zoom between 0 and 22")
            if key in ("map_default_lat", "map_default_lon"):
                import math
                try: coordinate = float(value)
                except ValueError: raise ValueError("Use a valid map coordinate") from None
                limit = 85.05112878 if key.endswith("lat") else 180
                if not math.isfinite(coordinate) or not -limit <= coordinate <= limit:
                    raise ValueError("Use a valid map coordinate")
            if key == "map_coordinate_format" and value not in ("wgs84", "mgrs", "utm", "olc"):
                raise ValueError("Choose a supported coordinate format")
        with self.database.provider:
            for key, value in values.items(): getattr(self.config, key).set(value)
        if any(key.startswith("map_data_") for key in values):
            self.map_data_manager.update_settings()
        return self.settings()

    def _require_outbound_http(self, feature):
        from meshchatnext.src.backend.privacy_mode import ensure_outbound_http_allowed
        ensure_outbound_http_allowed(self.config, feature=feature)

    def register(self, router):
        # The enclosing runtime applies its session, origin, Host and CSRF
        # middleware to these same production route handlers.
        from aiohttp import web
        from meshchatnext.src.backend.http.routes.map import register_map_routes
        routes = web.RouteTableDef()
        register_map_routes(routes, self)
        # Imports are validated under a temporary unique name. A malformed or
        # duplicate upload must never overwrite the current map.
        for route in routes:
            if (route.method, route.path) not in (("POST", "/api/v1/map/offline"), ("GET", "/api/v1/map/tiles/{z}/{x}/{y}")):
                router.add_route(route.method, route.path, route.handler, **route.kwargs)
        router.add_post("/api/v1/map/offline", self.upload)
        router.add_get("/api/v1/map/tiles/{z}/{x}/{y}", self.tile)

    async def upload(self, request):
        import asyncio, threading, uuid
        from aiohttp import web
        from family_maps import MapStore
        from meshchatnext.src.backend.http.uploads import write_field_to_path, UPLOAD_LIMITS, PayloadTooLargeError
        temporary = None
        validated = None
        try:
            reader = await request.multipart()
            field = await reader.next()
            if field is None or field.name != "file": raise ValueError("Choose an MBTiles file")
            from attachment_fields import filename
            name = filename(field.filename)
            if not name.lower().endswith(".mbtiles"): raise ValueError("Choose an MBTiles file")
            # The hardened validator denies extension loading, writes, ATTACH
            # and unapproved SQL functions while inspecting imported SQLite.
            store = MapStore(self.folder, {}, threading.RLock(), lambda: None)
            temporary = store.root / ("import-" + uuid.uuid4().hex + ".tmp")
            await write_field_to_path(field, str(temporary), min(UPLOAD_LIMITS["map_offline_mbtiles"], 2 * 1024**3))
            imported = await asyncio.to_thread(store.install, temporary, name)
            validated = store.root / (imported["id"] + ".mbtiles")
            target = store.root / (Path(name).stem[:100] + "-" + imported["id"] + ".mbtiles")
            validated.replace(target)
            self.map_manager.close()
            with self.database.provider:
                self.config.map_offline_path.set(str(target))
                self.config.map_offline_enabled.set(True)
            return web.json_response({"message": "Map imported", "metadata": self.map_manager.get_metadata()})
        except PayloadTooLargeError:
            return web.json_response({"message": "Choose a map smaller than 2 GB"}, status=413)
        except (ValueError, OSError) as error:
            return web.json_response({"message": str(error)}, status=400)
        finally:
            if temporary: temporary.unlink(missing_ok=True)
            if validated: validated.unlink(missing_ok=True)

    async def tile(self, request):
        from aiohttp import web
        from family_maps import image_type
        from meshchatnext.src.backend.map_manager import TRANSPARENT_TILE
        try:
            z, x, y = (int(request.match_info[key].removesuffix(".png")) for key in ("z", "x", "y"))
            if not 0 <= z <= 22 or not 0 <= x < 2**z or not 0 <= y < 2**z: raise ValueError()
            data = self.map_manager.get_tile(z, x, y)
            if data is None: data = TRANSPARENT_TILE
            return web.Response(body=data, content_type=image_type(data), headers={"Cache-Control": "no-store"})
        except (ValueError, TypeError):
            return web.json_response({"message": "Invalid map tile"}, status=400)

    def received_announce(self, destination_hash, announced_identity, app_data):
        import RNS
        with self.discovery_lock:
            if self.closed or not isinstance(destination_hash, bytes) or len(destination_hash) != 16: return
            if destination_hash != RNS.Destination.hash_from_name_and_identity(self.aspect_filter, announced_identity.hash): return
            self.announces.upsert_announce(self.reticulum, announced_identity, destination_hash,
                                          self.aspect_filter, app_data, None)

    async def start(self):
        import RNS
        if not self.discovery_registered:
            RNS.Transport.register_announce_handler(self)
            self.discovery_registered = True
        self.map_data_manager.start()
        self.map_overlay_manager.start_scheduler()

    async def close(self):
        import RNS
        with self.discovery_lock:
            self.closed = True
            if self.discovery_registered:
                RNS.Transport.deregister_announce_handler(self)
                self.discovery_registered = False
        download = self.regional_map_download
        if download is not None:
            download.cancel()
            task = getattr(download, "task", None)
            if task is not None:
                import asyncio
                await asyncio.gather(task, return_exceptions=True)
        self.map_data_manager.stop()
        pending = tuple(self.map_overlay_manager._job_tasks)
        scheduler = self.map_overlay_manager._scheduler_task
        self.map_overlay_manager.stop_scheduler()
        for task in pending: task.cancel()
        import asyncio
        await asyncio.gather(*pending, *([scheduler] if scheduler else []), return_exceptions=True)
        self.map_manager.close()
        self.database.provider.close_all()
