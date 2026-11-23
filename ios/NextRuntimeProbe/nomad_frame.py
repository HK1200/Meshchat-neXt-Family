# SPDX-License-Identifier: 0BSD
"""Public sandbox assets; private API/session access remains unavailable.

The CSP function is retained from the pinned neXt HTTP middleware without
importing its desktop-only dependencies into the mobile runtime.
"""
import re


def public_frame_resource(path):
    if path == '/nomad-crash-tab.html': return True
    return (isinstance(path, str) and len(path) <= 1024
        and re.fullmatch(r'/(assets|vendor/micron-parser-go)/[a-zA-Z0-9_@./-]+', path) is not None
        and not any(part in ('.', '..') for part in path.split('/')))


def build_nomad_crash_tab_csp(request_host: str | None = None) -> str:
    """CSP for /nomad-crash-tab.html only.

    Keeps Micron JS, Micron WASM (fetch + blob: wasm_exec inject), fonts, and
    inline styles. Drops map tiles, websocket, and other shell clearnet sources
    so CSS network paints cannot beacon even if style scrub misses.

    The frame is sandboxed without allow-same-origin, so the document runs in
    an opaque origin where 'self' never matches. Emit the request host as a
    literal source for both schemes so same-host asset URLs still load.
    """
    same_origin = "'self'"
    if request_host:
        same_origin = f"'self' http://{request_host} https://{request_host}"
    return (
        "default-src 'none'; "
        f"script-src {same_origin} 'wasm-unsafe-eval' blob:; "
        f"style-src {same_origin} 'unsafe-inline'; "
        f"font-src {same_origin} data:; "
        f"img-src {same_origin} data: blob:; "
        f"connect-src {same_origin}; "
        "worker-src 'none'; "
        "media-src 'none'; "
        "frame-src 'none'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'none'"
    )
