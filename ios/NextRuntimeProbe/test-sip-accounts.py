"""Exercise the pinned account store through the iOS vault adapter; no SIP sockets.

The native Keychain implementation is checked separately in app-hosted XCTest.
This verifies that the actual staged account store never persists a password.
"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

from meshchatnext.src.backend.sip_desktop_store import SipAccounts
from sip_native import IOSPasswords


slots = {}
def request(raw):
    value = json.loads(raw)
    assert value.pop('domain') == 'sip'
    op, account = value['op'], value['account']
    if op == 'password-save': slots[account] = value['password']
    elif op == 'password-remove': slots.pop(account, None)
    elif op == 'password-load': return json.dumps({'ok': True, 'value': slots[account]})
    else: raise AssertionError('Unexpected credential operation')
    return '{"ok":true}'

sys.modules['_next_credentials'] = SimpleNamespace(request=request)
with tempfile.TemporaryDirectory(prefix='next-private-sip-store-') as folder:
    path = Path(folder) / 'sip/accounts.json'
    vault = IOSPasswords()
    store = SipAccounts(path, vault=vault)
    secret = 'private synthetic SIP fixture'
    account = store.save({'extension': '9001', 'host': '127.0.0.1', 'port': 55162, 'save_password': True}, secret)
    assert store.password(account['id']) == secret
    assert secret not in path.read_text()
    reopened = SipAccounts(path, vault=vault)
    assert reopened.accounts == store.accounts
    assert reopened.password(account['id']) == secret
    reopened.remove(account['id'])
    assert not slots
    assert not SipAccounts(path, vault=vault).accounts
print('Pinned SIP account metadata, secure-vault bridge, reload and removal checks passed; no registrations.')
