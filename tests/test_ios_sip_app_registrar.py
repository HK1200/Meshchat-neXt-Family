"""Actual private registrar observations prove each native app logout separately."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('recorded_app_sip_registrar',root/'ios/sip-simulator-registrar.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


def test_distinct_authenticated_sessions_and_logouts_are_recorded_without_credentials(tmp_path):
    registrar=fixture.RecordedRegistrar(tmp_path)
    peer=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);peer.settimeout(2)
    uri=f'sip:127.0.0.1:{registrar.port}'
    # SIP Digest requires MD5; all credentials and packets are ephemeral/loopback.
    digest=lambda value:hashlib.md5(value.encode()).hexdigest()
    first=digest(f'{registrar.user}:{registrar.realm}:{registrar.password}')
    response=digest(f'{first}:{registrar.nonce}:{digest("REGISTER:"+uri)}')
    auth=(f'Authorization: Digest username="{registrar.user}",realm="{registrar.realm}",'
          f'nonce="{registrar.nonce}",uri="{uri}",response="{response}"\r\n')
    try:
        for identifier in ['first-private-session','second-private-session']:
            for expires in [3600,0]:
                raw=(f'REGISTER {uri} SIP/2.0\r\nVia: SIP/2.0/UDP localhost\r\nFrom: <sip:test@localhost>\r\n'
                     f'To: <sip:test@localhost>\r\nCall-ID: {identifier}\r\nCSeq: 1 REGISTER\r\n'
                     f'Expires: {expires}\r\n{auth}Content-Length: 0\r\n\r\n')
                peer.sendto(raw.encode(),('127.0.0.1',registrar.port))
                assert peer.recvfrom(65535)[0].startswith(b'SIP/2.0 200')
    finally:
        peer.close();registrar.close()
    registrar.record()
    observed=(tmp_path/'observed.json').read_text()
    assert json.loads(observed)==dict(authenticated=True,unregistered=True,host='127.0.0.1',registrations=2,unregistrations=2)
    assert registrar.password not in observed and registrar.user not in observed
    assert 'private-session' not in observed
