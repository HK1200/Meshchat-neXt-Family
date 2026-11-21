"""Own-app access to the loopback backend and private USB inspection metadata."""
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
from urllib.parse import urlsplit

HEADER = 'X-neXt-Session'
COOKIE = 'next_preview_session'
INFO_FILE = 'next-runtime-info.json'
# Other HTTP loopback ports must not receive this WebView's host-only cookie.
CSP = ("default-src 'self'; script-src 'self' blob: 'unsafe-eval' 'wasm-unsafe-eval'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
       "media-src 'self' data: blob: https:; font-src 'self' data: https:; "
       "connect-src 'self' https: wss:; worker-src 'self' blob:; "
       "frame-src 'self' blob:; frame-ancestors 'none'; object-src 'none'; "
       "base-uri 'none'; form-action 'self'")


class RuntimeAccess:
    def __init__(self, folder):
        self.path = Path(folder) / INFO_FILE
        self.capability = secrets.token_urlsafe(32)
        self.instance = secrets.token_hex(16)

    def allowed(self, request):
        supplied = request.headers.get(HEADER)
        if supplied is None:
            supplied = request.cookies.get(COOKIE)
        if not isinstance(supplied, str):
            return False
        try:
            return hmac.compare_digest(supplied.encode('utf-8'), self.capability.encode('ascii'))
        except UnicodeError:
            return False

    def write_info(self, origin):
        url = urlsplit(origin)
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
                or url.username is not None or url.password is not None or url.path or url.query or url.fragment):
            raise ValueError('Private runtime metadata requires the exact loopback origin')
        payload = dict(version=1, pid=os.getpid(), origin=origin,
                       instance=self.instance, capability=self.capability)
        fd, name = tempfile.mkstemp(prefix='.next-runtime-', dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def clear_info(self):
        try:
            if self.path.stat().st_size > 16384:
                return
            value = json.loads(self.path.read_text())
            if value.get('pid') == os.getpid() and value.get('instance') == self.instance:
                self.path.unlink()
        except (FileNotFoundError, OSError, ValueError, TypeError, AttributeError):
            pass
