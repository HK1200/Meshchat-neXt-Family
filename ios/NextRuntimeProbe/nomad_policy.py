# SPDX-License-Identifier: 0BSD
"""Per-runtime policy fences around the released Nomad downloader callbacks."""
from types import FunctionType


def guarded_handlers(runtime):
    from meshchatnext.src.backend.http.ws import handlers_nomad

    class CurrentPolicy:
        def link_established(self, link):
            with runtime.policy_lock:
                client = getattr(self, '_meshchatnext_client', None)
                blocked = runtime.denied(self.destination_hash.hex())
                if runtime.closed or blocked or self.is_cancelled or not getattr(client, 'active', True):
                    self.cancel()
                    self._deliver_failure('destination_blocked' if blocked else 'request_cancelled')
                    if self.private or blocked or runtime.closed:
                        link.teardown()
                    return
                # Permission changes use this same lock. Reticulum can submit
                # this request before a change commits, never after it commits.
                super().link_established(link)

        def _maybe_identify(self, link):
            with runtime.policy_lock:
                if (runtime.closed or self.is_cancelled or self.private
                        or runtime.denied(self.destination_hash.hex())
                        or not runtime.store.should_identify_on_connect(self.destination_hash.hex())):
                    return
                super()._maybe_identify(link)

    class Page(CurrentPolicy, handlers_nomad.NomadnetPageDownloader):
        pass

    class File(CurrentPolicy, handlers_nomad.NomadnetFileDownloader):
        pass

    result = dict(handlers_nomad.HANDLERS)
    for name in ('nomadnet.page.download', 'nomadnet.file.download'):
        original = result[name]
        namespace = dict(original.__globals__)
        namespace.update(NomadnetPageDownloader=Page, NomadnetFileDownloader=File)
        # Use the released handler code unchanged. Its private globals select
        # this runtime's guarded constructors; no global SDK monkeypatch occurs.
        guarded = FunctionType(original.__code__, namespace, original.__name__, original.__defaults__, original.__closure__)
        guarded.__kwdefaults__ = original.__kwdefaults__
        result[name] = guarded
    return result
