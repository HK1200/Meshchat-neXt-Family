"""Real IPv4/IPv6 loopback digest exchanges; no public SIP service is contacted."""
import hashlib
import importlib.util
from pathlib import Path
import socket

import pytest

path = Path(__file__).resolve().parents[1] / 'ios/test-sip-registration.py'
spec = importlib.util.spec_from_file_location('sip_dual_stack_fixture', path)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.mark.parametrize('host,family', [('127.0.0.1',socket.AF_INET),('::1',socket.AF_INET6)])
def test_actual_registrar_challenges_authenticates_and_unregisters(host,family):
    registrar = fixture.Registrar(host)
    peer = socket.socket(family,socket.SOCK_DGRAM)
    peer.settimeout(2)
    uri = f"sip:{'['+host+']' if family==socket.AF_INET6 else host}:{registrar.port}"
    def register(auth='', expires=3600):
        request = (f'REGISTER {uri} SIP/2.0\r\nVia: SIP/2.0/UDP localhost\r\n'
                   f'From: <sip:{registrar.user}@localhost>\r\nTo: <sip:{registrar.user}@localhost>\r\n'
                   f'Call-ID: private-test\r\nCSeq: 1 REGISTER\r\nExpires: {expires}\r\n'
                   f'{auth}Content-Length: 0\r\n\r\n')
        peer.sendto(request.encode(),(host,registrar.port))
        return peer.recvfrom(65535)[0].decode()
    try:
        assert register().startswith('SIP/2.0 401')
        # This ephemeral loopback fixture implements SIP's legacy MD5 digest.
        digest=lambda text: hashlib.md5(text.encode()).hexdigest()
        first=digest(f'{registrar.user}:{registrar.realm}:{registrar.password}')
        response=digest(f'{first}:{registrar.nonce}:{digest("REGISTER:"+uri)}')
        auth=(f'Authorization: Digest username="{registrar.user}",realm="{registrar.realm}",'
              f'nonce="{registrar.nonce}",uri="{uri}",response="{response}"\r\n')
        assert register(auth).startswith('SIP/2.0 200')
        assert registrar.authenticated and not registrar.unregistered
        assert register(auth,0).startswith('SIP/2.0 200')
        assert registrar.unregistered
    finally:
        peer.close();registrar.close()


def test_native_registration_fixture_rejects_public_target():
    with pytest.raises(ValueError,match='loopback'): fixture.verify_registration('sim','fixture','example.org')
