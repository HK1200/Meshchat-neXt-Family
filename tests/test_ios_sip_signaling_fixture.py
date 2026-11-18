"""Exercise the private SIP wire fixture before running the native Apple client."""
import hashlib
import importlib.util
from pathlib import Path
import socket
import time

SOURCE = Path(__file__).resolve().parents[1] / 'ios/test-sip-signaling.py'
spec = importlib.util.spec_from_file_location('family_sip_signaling_fixture', SOURCE)
sip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sip)


def register(peer, client, *, expires=3600):
    uri = f'sip:127.0.0.1:{peer.port}'
    digest = lambda value: hashlib.md5(value.encode()).hexdigest()
    first = digest(f'{peer.user}:{peer.realm}:{peer.password}')
    final = digest(f'{first}:{peer.nonce}:{digest("REGISTER:" + uri)}')
    auth = (f'Digest username="{peer.user}", realm="{peer.realm}", nonce="{peer.nonce}", '
            f'uri="{uri}", response="{final}"')
    packet = [f'REGISTER {uri} SIP/2.0', 'Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bKreg',
              f'From: <sip:{peer.user}@127.0.0.1>;tag=client', f'To: <sip:{peer.user}@127.0.0.1>',
              'Call-ID: private-registration', 'CSeq: 1 REGISTER',
              f'Contact: <sip:{peer.user}@127.0.0.1:{client.getsockname()[1]}>;expires={expires}',
              f'Expires: {expires}', 'Authorization: ' + auth, 'Content-Length: 0', '', '']
    client.sendto('\r\n'.join(packet).encode(), ('127.0.0.1', peer.port))
    response, _ = client.recvfrom(65535)
    assert response.startswith(b'SIP/2.0 200 OK')


def wait_complete(peer):
    deadline = time.monotonic() + 2
    while not peer.call_complete and time.monotonic() < deadline:
        time.sleep(0.01)
    assert peer.call_complete


def test_private_incoming_invite_decline_and_ack():
    peer = sip.CallPeer('incoming')
    peer.media_host = '192.0.2.20'
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.bind(('127.0.0.1', 0))
            client.settimeout(2)
            register(peer, client)
            raw, address = client.recvfrom(65535)
            first, values = sip.parse(raw)
            assert first.startswith('INVITE sip:family-test@127.0.0.1:')
            body = raw.split(b'\r\n\r\n', 1)[1]
            assert int(values['content-length']) == len(body)
            assert b'a=rtpmap:0 PCMU/8000' in body
            assert b'c=IN IP4 192.0.2.20\r\n' in body
            response = ['SIP/2.0 486 Busy Here']
            for name in ['via', 'from', 'to', 'call-id', 'cseq']:
                response.append(name + ': ' + values[name] + (';tag=native-client' if name == 'to' else ''))
            client.sendto(('\r\n'.join(response) + '\r\nContent-Length: 0\r\n\r\n').encode(), address)
            ack, _ = client.recvfrom(65535)
            assert sip.parse(ack)[1]['cseq'] == '1 ACK'
            wait_complete(peer)
            register(peer, client, expires=0)
            assert peer.unregistered
    finally:
        peer.close()


def test_private_outgoing_rejection_waits_for_ack():
    peer = sip.CallPeer('outgoing')
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.bind(('127.0.0.1', 0))
            client.settimeout(2)
            register(peer, client)
            packet = ['INVITE sip:private-peer@127.0.0.1 SIP/2.0',
                      'Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bKcall',
                      'From: <sip:family-test@127.0.0.1>;tag=client', 'To: <sip:private-peer@127.0.0.1>',
                      'Call-ID: private-outgoing', 'CSeq: 1 INVITE', 'Content-Length: 0', '', '']
            client.sendto('\r\n'.join(packet).encode(), ('127.0.0.1', peer.port))
            response, _ = client.recvfrom(65535)
            first, values = sip.parse(response)
            assert first == 'SIP/2.0 486 Busy Here'
            assert values['call-id'] == 'private-outgoing'
            assert not peer.call_complete
            packet[0] = packet[0].replace('INVITE ', 'ACK ', 1)
            packet[5] = 'CSeq: 1 ACK'
            client.sendto('\r\n'.join(packet).encode(), ('127.0.0.1', peer.port))
            wait_complete(peer)
            register(peer, client, expires=0)
            assert peer.unregistered
    finally:
        peer.close()


def test_unauthenticated_registration_does_not_trigger_incoming_call():
    peer = sip.CallPeer('incoming')
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.bind(('127.0.0.1', 0))
            client.settimeout(2)
            packet = [f'REGISTER sip:127.0.0.1:{peer.port} SIP/2.0',
                      'Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bKunauthorized',
                      'From: <sip:family-test@127.0.0.1>;tag=client', 'To: <sip:family-test@127.0.0.1>',
                      'Call-ID: no-auth', 'CSeq: 1 REGISTER', 'Content-Length: 0', '', '']
            client.sendto('\r\n'.join(packet).encode(), ('127.0.0.1', peer.port))
            response, _ = client.recvfrom(65535)
            assert response.startswith(b'SIP/2.0 401 Unauthorized')
            assert not peer.authenticated
            assert not peer.invited
            assert peer.timer is None
    finally:
        peer.close()
