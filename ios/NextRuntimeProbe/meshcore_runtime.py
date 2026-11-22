"""neXt's existing MeshCore service using the native iOS BLE transport.

Keeps radio identity/history isolated from Reticulum and never opens a radio
until it has been explicitly selected. Family approval rules are not reused.
"""

import asyncio
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web



# Only the explicitly started native location task carries this guard. Ordinary
# chat/admin writes retain the backend's existing behavior and permission checks.
NATIVE_LOCATION_GUARD = ContextVar("next_native_meshcore_location_guard", default=None)


def protect_native_location_writes(connection):
    original = connection.send

    async def send(data):
        context = NATIVE_LOCATION_GUARD.get()
        if context is None:
            return await original(data)
        from meshchatnext.src.backend.meshcore_private_location import WRITE_GUARD, LocationPermissionChanged
        asynchronous, synchronous = context
        if not await asynchronous():
            raise LocationPermissionChanged("Native location sharing stopped before the radio write")
        inherited = WRITE_GUARD.get()

        def check():
            if inherited is not None: inherited()
            try: permitted = synchronous()
            except (OSError, RuntimeError, ValueError, TypeError) as error:
                raise LocationPermissionChanged("Native location permission could not be checked") from error
            if not permitted:
                raise LocationPermissionChanged("Native location sharing changed before the radio handoff")

        token = WRITE_GUARD.set(check)
        try:
            return await original(data)
        finally:
            WRITE_GUARD.reset(token)

    connection.send = send
    return connection


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
        return protect_native_location_writes(AndroidConnection(kind, target, native_factory=NativeSession, **options))
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
        from meshcore_notices import MeshCoreNotices
        self.notices = MeshCoreNotices(self.folder / "native-alerts.sqlite3")

        async def notify(event):
            await asyncio.to_thread(self.notices.save, event)
            await broadcast(event)

        self.fleet = MeshCoreFleet(
            self.folder,
            service_factory=lambda folder, **options: service_factory(folder, device=device, **options),
            notification_sink=notify,
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

    async def location_recipients(self):
        """Saved private users with existing explicit share permission only."""
        rows = {}
        for radio in self.fleet.radio_rows():
            owner = radio.get("owner")
            if not isinstance(owner, str) or len(owner) != 64: continue
            service = self.fleet.resolve(radio["id"], owner)
            store = service._store
            if store is None: continue
            def read():
                result = []
                for contact in store.contacts(owner):
                    if contact["kind"] != 1 or not contact["active"]: continue
                    try: policy = store.private_location_policy(owner, contact["peer"])
                    except ValueError: continue
                    if policy["share"] and policy["generation"]:
                        result.append((contact, policy))
                return result
            selected = await asyncio.to_thread(read)
            # Reading disk can overlap a radio removal or identity replacement.
            try:
                if self.fleet.resolve(radio["id"], owner) is not service: continue
            except ValueError:
                continue
            for contact, policy in selected:
                key = "meshcore:" + owner + ":" + contact["peer"] + ":" + policy["generation"]
                rows[key] = dict(name=contact["name"] + " (" + radio.get("label", "MeshCore") + ")", service="meshcore", online=radio.get("connected") is True,
                    address=contact["peer"], owner=owner, radio=radio["id"], generation=policy["generation"])
        return rows

    async def send_native_location(self, target, fix, asynchronous, synchronous):
        import uuid
        service = self.fleet.resolve(target["radio"], target["owner"])
        if not await asynchronous(): return False
        token = NATIVE_LOCATION_GUARD.set((asynchronous, synchronous))
        try:
            result = await service.call("messages", "send_private_location", peer=target["address"],
                fix=fix, request_id=uuid.uuid4().hex, generation=target["generation"], expected_owner=target["owner"])
            return result.get("state") == "accepted"
        finally:
            NATIVE_LOCATION_GUARD.reset(token)

    async def notification_candidates(self):
        owners = {row["owner"] for row in self.fleet.radio_rows() if row.get("owner")}
        return await asyncio.to_thread(
            self.notices.candidates,
            lambda: self.fleet._shared_store(self.folder / "history.sqlite"),
            owners,
        )

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
