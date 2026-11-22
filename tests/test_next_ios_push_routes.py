"""Explicit recipient routes, bounded private storage, and consent revocation."""
import json
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/src/main/python'))
import mailbox_push

ROUTE = {'provider': 'https://alerts.example.invalid', 'audience': 'private test', 'relay': 'ab' * 16}

@pytest.mark.parametrize('entry', [
    {**ROUTE, 'secret': 'not permitted'}, {**ROUTE, 'provider': 'http://example.invalid'},
    {**ROUTE, 'provider': 'https://name:password@example.invalid'},
    {**ROUTE, 'provider': 'https://example.invalid:0'},
    {**ROUTE, 'provider': 'https://example.invalid/path'},
    {**ROUTE, 'audience': 'line\nbreak'}, {**ROUTE, 'audience': ' '},
    {**ROUTE, 'relay': 'AB' * 16}, {**ROUTE, 'provider': True},
])
def test_invalid_route_cannot_replace_existing_consent(tmp_path, entry):
    mailbox_push.save_route(tmp_path, 'cd' * 16, ROUTE)
    before = (tmp_path / 'mailbox-push-routes.json').read_bytes()
    with pytest.raises(ValueError): mailbox_push.save_route(tmp_path, 'cd' * 16, entry)
    assert (tmp_path / 'mailbox-push-routes.json').read_bytes() == before


def test_private_atomic_storage_preserves_others_and_failed_write(tmp_path, monkeypatch):
    first, second = 'cd' * 16, 'ef' * 16
    mailbox_push.save_route(tmp_path, first, ROUTE)
    mailbox_push.save_route(tmp_path, second, ROUTE)
    path = tmp_path / 'mailbox-push-routes.json'
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    def fail(*_): raise OSError('synthetic full disk')
    with monkeypatch.context() as patch:
        patch.setattr(mailbox_push.os, 'replace', fail)
        with pytest.raises(OSError): mailbox_push.save_route(tmp_path, first, None)
    assert path.read_bytes() == before and list(tmp_path.glob('.mailbox-alerts-*')) == []
    mailbox_push.save_route(tmp_path, first, None)
    assert mailbox_push.route_for(tmp_path, first) is None
    assert mailbox_push.route_for(tmp_path, second) == mailbox_push.parse_route(ROUTE)


def test_oversized_storage_is_rejected_without_replacing_it(tmp_path):
    path = tmp_path / 'mailbox-push-routes.json'
    original = b' ' * (mailbox_push.MAX_ROUTE_BYTES + 1)
    path.write_bytes(original)
    assert mailbox_push.route_for(tmp_path, 'cd' * 16) is None
    with pytest.raises(ValueError): mailbox_push.save_route(tmp_path, 'cd' * 16, ROUTE)
    assert path.read_bytes() == original


def test_actual_private_http_requires_saved_contact_and_csrf_and_revokes_on_removal(tmp_path):
    from test_next_ios_tcp_integration import api, backend, run_server, start, wait
    settings = tmp_path / 'settings.json'
    settings.write_text(json.dumps({'peers': [{'id': 'off', 'host': '127.0.0.1', 'port': 9, 'enabled': False}]}))
    ready = tmp_path / 'backend.url'
    with ExitStack() as stack:
        start(stack, run_server, tmp_path, ready, settings)
        wait(ready.exists); base = backend(ready); token = api(base, 'auth/csrf')[1]['csrf_token']
        assert api(base, 'telephone/contacts/1/mailbox-alert-route', body={'route': ROUTE}, token=token)[0] == 404
        assert api(base, 'telephone/contacts', body={'name': 'Synthetic recipient', 'lxmf_address': 'cd' * 16}, token=token)[0] == 200
        contact = api(base, 'telephone/contacts')[1]['contacts'][0]
        path = f'telephone/contacts/{contact["id"]}/mailbox-alert-route'
        assert api(base, path)[1] == {'route': None}
        assert api(base, path, body={'route': ROUTE})[0] == 403
        assert api(base, path, body={'route': ROUTE}, token=token)[1] == {'route': ROUTE}
        assert api(base, path, body={'route': {**ROUTE, 'token': 'never save this'}}, token=token)[0] == 400
        assert api(base, path)[1] == {'route': ROUTE}
        assert api(base, path, method='DELETE', token=token)[1] == {'route': None}
        assert api(base, path, body={'route': ROUTE}, token=token)[0] == 200
        assert api(base, f'telephone/contacts/{contact["id"]}', method='DELETE', token=token)[0] == 200
        assert mailbox_push.route_for(tmp_path, 'cd' * 16) is None
        assert api(base, path)[0] == 404
