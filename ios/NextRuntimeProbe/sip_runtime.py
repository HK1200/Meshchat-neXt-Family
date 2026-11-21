"""Own-app SIP account lifecycle through the native iOS transport.

Uses the released account policy and command service, with iOS Keychain and the
OS default route. Call controls remain unavailable until the native call adapter
is connected; registering must never imply that calls or locked alerts work.
"""
from pathlib import Path
from types import SimpleNamespace

from sip_native import IOSPasswords, IOSSIPEngine, networks


class NextSIPRuntime:
    def __init__(self, folder, *, device, service_factory=None, vault=None,
                 engine_factory=IOSSIPEngine, network_provider=networks):
        self.service = None
        self.error = ""
        if not device:
            self.error = "SIP accounts are disabled in the isolated simulator profile"
            return
        from meshchatnext.src.backend.sip_desktop_store import SipAccounts
        if service_factory is None:
            from meshchatnext.src.backend.sip_desktop_service import DesktopSipService
            service_factory = DesktopSipService
        try:
            store = SipAccounts(Path(folder) / "sip/accounts.json", vault=vault if vault is not None else IOSPasswords())
            self.service = service_factory(store, None, engine_factory=engine_factory,
                                           networks=network_provider)
        except (ValueError, OSError, TypeError, KeyError):
            self.error = "SIP account settings could not be opened; other services remain available"

    def status(self):
        value = self.service.status() if self.service else {
            "available": False, "state": "unavailable", "accounts": [],
            "registered": False, "call_state": "idle",
        }
        value.update(platform="ios", account_management_available=self.service is not None,
                     available=False, calling_available=False,
                     native_telecom_available=False)
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

        class AccountsOnly:
            @property
            def store(self):
                return adapter.service.store

            def status(self):
                return adapter.status()

            async def reconcile(self):
                await adapter.service.reconcile()

            async def command(self, operation, **values):
                if operation not in {"save", "remove", "connect", "disconnect", "resume", "status"}:
                    raise ValueError("Native SIP call controls are not available yet")
                await adapter.service.command(operation, **values)
                return adapter.status()

        owner = SimpleNamespace(sip_desktop_service=AccountsOnly() if self.service else None,
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
