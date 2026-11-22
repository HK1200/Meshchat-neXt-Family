# SPDX-License-Identifier: 0BSD
"""Bind mobile guards to exact released transfer methods, never caller code."""
import hashlib
import inspect
import textwrap
import types
from meshchatnext.src.backend import rncp_handler

SEND_SHA256 = 'd423eee45ed9c6440aa65b3b0dbd1519f5b00354fcbfa59a5a967ae10e868636'
FETCH_SHA256 = '4c7c20d0cc0e5ced7d0faeaca122b4fcf646cd61af9dbb9448b0e7a15911a50c'


def guarded_source(source):
    if hashlib.sha256(source.encode()).hexdigest() != FETCH_SHA256:
        raise ValueError('Review the changed RNCP fetch engine before packaging iOS')
    changes = [
        ('            if asyncio.get_running_loop().time() > resolve_deadline:',
         '            if current_resource is None and asyncio.get_running_loop().time() > resolve_deadline:'),
        ('        listener_identity = RNS.Identity.recall(destination_hash)',
         '        if not self._mobile_fetch_destination_allowed(destination_hash): raise PermissionError("This destination is blocked")\n        listener_identity = RNS.Identity.recall(destination_hash)'),
        ('        link = RNS.Link(listener_destination)',
         '        link = RNS.Link(listener_destination)\n        self._mobile_link_opened(link)'),
        ('        link.identify(self.identity)',
         '        if not self._mobile_fetch_destination_allowed(destination_hash): raise PermissionError("This destination is blocked")\n        link.identify(self.identity)'),
        ('        link.set_resource_strategy(RNS.Link.ACCEPT_ALL)',
         '        link.set_resource_strategy(RNS.Link.ACCEPT_APP)\n        link.set_resource_callback(lambda advert: self._mobile_fetch_accept(advert, destination_hash))'),
        ('            current_resource = resource\n',
         '            current_resource = resource\n            self.active_transfers[resource.hash.hex()] = {"resource": resource, "status": "fetching", "started_at": time.time()}\n'),
        ('            try:\n                if resource.status == RNS.Resource.COMPLETE:',
         '            try:\n                if self._is_cancelled(resource.hash.hex()) or not self._mobile_fetch_destination_allowed(destination_hash):\n                    resource_status = "cancelled"\n                    return\n                if resource.status == RNS.Resource.COMPLETE:'),
        ('            finally:\n                resource_resolved = True',
         '            finally:\n                resource_resolved = True\n                self._mobile_fetch_release(resource)\n                entry = self.active_transfers.get(resource.hash.hex())\n                if entry is not None:\n                    entry["status"] = resource_status\n                    entry["saved_path"] = saved_filename\n                self._on_transfer_terminal(resource.hash.hex())'),
        ('        if resource_status == "completed":',
         '        if resource_status == "cancelled":\n            link.teardown()\n            raise InterruptedError("Transfer cancelled")\n        if resource_status == "completed":'),
    ]
    for before, after in changes:
        if source.count(before) != 1: raise ValueError('RNCP fetch guard location changed')
        source = source.replace(before, after)
    return textwrap.dedent(source)


def guarded_send_source(source):
    if hashlib.sha256(source.encode()).hexdigest() != SEND_SHA256:
        raise ValueError('Review the changed RNCP sender before packaging iOS')
    changes = [
        ('        receiver_identity = RNS.Identity.recall(destination_hash)',
         '        if not self._mobile_fetch_destination_allowed(destination_hash): raise PermissionError("This destination is blocked")\n        receiver_identity = RNS.Identity.recall(destination_hash)'),
        ('        link = RNS.Link(receiver_destination)',
         '        link = RNS.Link(receiver_destination)\n        self._mobile_link_opened(link)'),
        ('        link.identify(self.identity)',
         '        if not self._mobile_fetch_destination_allowed(destination_hash): raise PermissionError("This destination is blocked")\n        link.identify(self.identity)'),
    ]
    before = '''        resource = RNS.Resource(
            await asyncio.to_thread(open, file_path, "rb"),
            link,
            metadata=metadata,
            callback=progress_callback,
            progress_callback=progress_callback,
            auto_compress=auto_compress,
        )'''
    after = '''        if not self._mobile_fetch_destination_allowed(destination_hash): raise PermissionError("This destination is blocked")
        handle = open(file_path, "rb")
        try:
            resource = RNS.Resource(
                handle, link, metadata=metadata, callback=progress_callback,
                progress_callback=progress_callback, auto_compress=auto_compress,
            )
        except BaseException:
            handle.close()
            raise'''
    changes.append((before, after))
    for before, after in changes:
        if source.count(before) != 1: raise ValueError('RNCP sender guard location changed')
        source = source.replace(before, after)
    return textwrap.dedent(source)


def install(handler, *, accept, allowed, release, opened):
    # Only checksum-pinned first-party methods are compiled. Each handler gets
    # a private namespace; neither the engine class nor global RNS is modified.
    fetch = guarded_source(inspect.getsource(rncp_handler.RNCPHandler.fetch_file))
    send = guarded_send_source(inspect.getsource(rncp_handler.RNCPHandler.send_file))
    namespace = dict(vars(rncp_handler))
    exec(compile(fetch + '\n' + send, '<verified-mobile-rncp-guards>', 'exec'), namespace)
    handler.fetch_file = types.MethodType(namespace['fetch_file'], handler)
    handler.send_file = types.MethodType(namespace['send_file'], handler)
    handler._mobile_fetch_accept = accept
    handler._mobile_fetch_destination_allowed = allowed
    handler._mobile_fetch_release = release
    handler._mobile_link_opened = opened
