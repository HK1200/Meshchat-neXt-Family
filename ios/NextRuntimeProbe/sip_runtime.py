"""Own-app SIP account lifecycle through the native iOS transport.

Uses the released account policy and command service, with iOS Keychain and the
OS default route. Call controls require the linked native adapter and the exact
displayed call identity. Simulator profiles never open accounts.
"""
from pathlib import Path
from types import SimpleNamespace

from sip_native import IOSPasswords, IOSSIPEngine, networks, native_request


def native_service_factory(accounts, executable, **options):
    from meshchatnext.src.backend.sip_desktop_service import DesktopSipService

    class NativeService(DesktopSipService):
        async def command(self, operation, **fields):
            if operation not in {"answer", "hangup", "mute", "hold", "dtmf", "speaker"}:
                return await super().command(operation, **fields)
            async with self._lock:
                expected = fields.get("call_id")
                if (not expected or expected != self.call_id or not self._permitted()
                        or not self.engine or not self.engine.running):
                    raise ValueError("The displayed SIP call has ended or changed")
                payload = {}
                if operation in {"mute", "hold", "speaker"}:
                    if type(fields.get("value")) is not bool:
                        raise ValueError("Invalid SIP audio option")
                    payload["value"] = fields["value"]
                if operation == "dtmf":
                    if fields.get("digit") not in tuple("0123456789*#ABCD"):
                        raise ValueError("Invalid SIP keypad digit")
                    payload["digit"] = fields["digit"]
                await self.engine.command("digit" if operation == "dtmf" else operation, **payload)
                if self.call_id == expected:
                    if operation == "mute": self.muted = payload["value"]
                    if operation == "hold": self.held = payload["value"]
                    if operation == "speaker": self.speaker = payload["value"]
                return self.status()

        def _event(self, engine, event):
            if engine is self.engine and event.get("state") == "muted":
                self.muted = bool(event.get("code"))
            super()._event(engine, event)

    return NativeService(accounts, executable, **options)


class NextSIPRuntime:
    def __init__(self, folder, *, device, service_factory=None, vault=None,
                 engine_factory=IOSSIPEngine, network_provider=networks, capability_provider=None):
        self.service = None
        self.error = ""
        self.calling_available = False
        self.default_speaker = False
        if not device:
            self.error = "SIP accounts are disabled in the isolated simulator profile"
            return
        from meshchatnext.src.backend.sip_desktop_store import SipAccounts
        if capability_provider is None:
            capability_provider = lambda: native_request({"op": "capabilities"})
        try:
            capabilities = capability_provider()
            self.calling_available = capabilities.get("calling_available") is True
            self.default_speaker = capabilities.get("default_speaker") is True
        except (ConnectionError, RuntimeError):
            pass
        if service_factory is None:
            service_factory = native_service_factory
        try:
            store = SipAccounts(Path(folder) / "sip/accounts.json", vault=vault if vault is not None else IOSPasswords())
            self.service = service_factory(store, None, engine_factory=engine_factory,
                                           networks=network_provider)
            self.service.speaker = self.default_speaker
        except (ValueError, OSError, TypeError, KeyError):
            self.error = "SIP account settings could not be opened; other services remain available"

    def status(self):
        value = self.service.status() if self.service else {
            "available": False, "state": "unavailable", "accounts": [],
            "registered": False, "call_state": "idle",
        }
        value.update(platform="ios", account_management_available=self.service is not None,
                     available=self.service is not None and self.calling_available,
                     calling_available=self.calling_available,
                     speaker=getattr(self.service, "speaker", self.default_speaker),
                     native_telecom_available=self.calling_available)
        if self.error:
            value["error"] = self.error
        return value

    async def start(self):
        if self.service:
            await self.service.start()

    async def close(self):
        if self.service:
            await self.service.close()

    def register(self, router):
        from aiohttp import web
        from meshchatnext.src.backend.sip_desktop_http import register_sip_desktop_routes
        adapter = self

        class NativeTransport:
            @property
            def store(self):
                return adapter.service.store

            def status(self):
                return adapter.status()

            async def reconcile(self):
                await adapter.service.reconcile()

            async def command(self, operation, **values):
                allowed = {"save", "remove", "connect", "disconnect", "resume", "status"}
                if adapter.calling_available:
                    allowed |= {"call", "answer", "hangup", "mute", "hold", "dtmf", "speaker"}
                if operation not in allowed:
                    raise ValueError("Native SIP call controls are unavailable")
                await adapter.service.command(operation, **values)
                return adapter.status()

        owner = SimpleNamespace(sip_desktop_service=NativeTransport() if self.service else None,
                                sip_desktop_error=self.error)
        definitions = web.RouteTableDef()
        register_sip_desktop_routes(definitions, owner)
        # Keep the real iOS platform even when configuration is damaged or the
        # isolated simulator refuses accounts. The released fallback is desktop.
        async def status(_request):
            return web.json_response(self.status(), headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        for route in definitions:
            router.add_route(route.method, route.path,
                             status if route.method == "GET" else route.handler)
