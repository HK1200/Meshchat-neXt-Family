"""neXt's existing MeshCore service using the native iOS BLE transport.

Keeps radio identity/history isolated from Reticulum and never opens a radio
until it has been explicitly selected. Family approval rules are not reused.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web


def ble_target(kind, target, *, device):
    if not device:
        raise ValueError("Radios are disabled in the private simulator profile")
    if kind != "ble":
        raise ValueError("Choose Bluetooth LE on iPhone or iPad")
    from family_ios_bluetooth import device_id
    return device_id(target)


async def bluetooth_devices(*, device):
    if not device:
        return []
    from family_ios_bluetooth import request
    await asyncio.to_thread(request, "scan")
    await asyncio.sleep(6)
    reply = await asyncio.to_thread(request, "devices")
    return [{"address": row["id"], "name": row.get("name") or "Bluetooth radio"}
            for row in reply.get("devices", [])]


def session_factory(*, device):
    from meshchatnext.src.backend.meshcore_session import MeshCoreSession
    from meshchatnext.src.backend.meshcore_transport import AndroidConnection
    from family_ios_bluetooth import NativeSession

    def connection(kind, target, **options):
        target = ble_target(kind, target, device=device)
        return AndroidConnection(kind, target, native_factory=NativeSession, **options)
    return MeshCoreSession(connection_factory=connection)


def service_factory(folder, *, device, **options):
    from meshchatnext.src.backend.meshcore_service import MeshCoreService

    class IOSService(MeshCoreService):
        def status(self):
            result = super().status()
            result.update(radio_platform="ios", bluetooth_discovery_supported=device)
            return result

    return IOSService(folder, session_factory=lambda: session_factory(device=device), **options)


class NextMeshCore:
    def __init__(self, folder, identity, contacts, broadcast, *, device):
        from meshchatnext.src.backend.meshcore_fleet import MeshCoreFleet
        self.device = device
        self.folder = Path(folder) / "meshcore"
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.fleet = MeshCoreFleet(
            self.folder,
            service_factory=lambda folder, **options: service_factory(folder, device=device, **options),
            notification_sink=broadcast,
        )
        self.owner = SimpleNamespace(
            identity=identity, config=None, meshcore_service=self.fleet,
            database=SimpleNamespace(contacts=SimpleNamespace(
                get_contact=lambda contact_id: next(
                    (entry for entry in contacts().values() if entry["id"] == contact_id), None))),
        )

    async def start(self):
        await self.fleet.start()

    async def close(self):
        await self.fleet.close()

    def register(self, router):
        from meshchatnext.src.backend.meshcore_http import register_meshcore_routes
        definitions = web.RouteTableDef()
        register_meshcore_routes(definitions, self.owner)
        original = definitions[0].handler

        async def handle(request):
            action = request.match_info["action"]
            if request.method == "GET" and action == "bluetooth-devices":
                try:
                    devices = await bluetooth_devices(device=self.device)
                    return web.json_response({"result": devices}, headers={"Cache-Control": "no-store"})
                except ConnectionError as error:
                    return web.json_response({"message": str(error)}, status=503)
            if request.method == "GET" and action == "usb-devices":
                return web.json_response({"result": []}, headers={"Cache-Control": "no-store"})
            if request.method == "POST":
                if not self.device:
                    return web.json_response({"message": "Radios are disabled in the private simulator profile"}, status=403)
                if action in ("connect", "radio-add"):
                    try:
                        body = await request.json()
                        if not isinstance(body, dict):
                            raise ValueError("Choose a Bluetooth radio")
                        ble_target(body.get("kind"), body.get("target"), device=self.device)
                    except (ValueError, TypeError):
                        return web.json_response({"message": "Select a discovered Bluetooth LE radio"}, status=400)
                if action == "usb-permission":
                    return web.json_response({"message": "Use Bluetooth LE on iPhone or iPad"}, status=400)
            return await original(request)

        router.add_get("/api/v1/meshcore/{action}", handle)
        router.add_post("/api/v1/meshcore/{action}", handle)
