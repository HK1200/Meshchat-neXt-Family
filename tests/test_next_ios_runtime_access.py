"""App-only local access, atomic metadata permissions and stale-instance safety."""
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe'))
from runtime_access import RuntimeAccess, HEADER, COOKIE, CSP


def test_header_and_http_only_cookie_access_never_accept_guess_or_bad_header(tmp_path):
    access=RuntimeAccess(tmp_path)
    request=lambda headers={},cookies={}: SimpleNamespace(headers=headers,cookies=cookies)
    assert not access.allowed(request())
    assert not access.allowed(request({HEADER:'not the session'}))
    assert access.allowed(request({HEADER:access.capability}))
    assert access.allowed(request(cookies={COOKIE:access.capability}))
    assert not access.allowed(request({HEADER:'wrong'},{COOKIE:access.capability}))
    assert not access.allowed(request({HEADER:'\udcff'}))


def test_metadata_is_private_and_an_old_instance_cannot_remove_a_new_one(tmp_path):
    old=RuntimeAccess(tmp_path);old.write_info('http://127.0.0.1:12345')
    value=json.loads(old.path.read_text())
    assert value==dict(version=1,pid=os.getpid(),origin='http://127.0.0.1:12345',instance=old.instance,capability=old.capability)
    assert stat.S_IMODE(old.path.stat().st_mode)==0o600
    new=RuntimeAccess(tmp_path);new.write_info('http://127.0.0.1:54321')
    old.clear_info();assert new.path.exists()
    new.clear_info();assert not new.path.exists()
    assert not list(tmp_path.glob('.next-runtime-*'))


@pytest.mark.parametrize('origin',['http://localhost:1234','http://192.168.0.2:1234','https://127.0.0.1:1234','http://user@127.0.0.1:1234','http://127.0.0.1:1234/path'])
def test_metadata_refuses_non_loopback_or_ambiguous_origins(tmp_path,origin):
    with pytest.raises(ValueError): RuntimeAccess(tmp_path).write_info(origin)
    assert not list(tmp_path.iterdir())


def test_renderer_policy_allows_own_attachments_but_no_other_http_ports():
    directives={part.split()[0]:part.split()[1:] for part in CSP.split(';') if part.strip()}
    for kind in ['connect-src','img-src','media-src','frame-src']:
        assert "'self'" in directives[kind]
        assert 'http:' not in directives[kind] and '*' not in directives[kind]
    assert 'blob:' in directives['worker-src']
    assert 'blob:' in directives['script-src']
