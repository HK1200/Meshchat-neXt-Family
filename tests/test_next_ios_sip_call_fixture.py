"""Fresh loopback SIP signaling proofs for consecutive simulator processes."""
import importlib.util
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('next_call_fixture', ROOT/'ios/NextRuntimeProbe/sip_call_fixture.py')
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
spec = importlib.util.spec_from_file_location('next_call_wire_helpers', ROOT/'tests/test_ios_sip_signaling_fixture.py')
wire = importlib.util.module_from_spec(spec); spec.loader.exec_module(wire)


class Client:
    def __init__(self, sock, registration): self.sock = sock; self.registration = registration
    def __getattr__(self, key): return getattr(self.sock, key)
    def sendto(self, data, address):
        return self.sock.sendto(data.replace(b'private-registration', self.registration.encode()), address)


def test_consecutive_private_incoming_clients_each_need_a_new_completed_call(tmp_path):
    peer = fixture.RecordedCallPeer(tmp_path, 'incoming', media_host='192.0.2.20')
    try:
        for number in (1, 2):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.bind(('127.0.0.1', 0)); sock.settimeout(3)
                client = Client(sock, 'registration-' + str(number))
                wire.register(peer, client)
                raw, address = sock.recvfrom(65535)
                first, headers = fixture.signaling.parse(raw)
                assert first.startswith('INVITE ') and peer.host == '127.0.0.1'
                response = ['SIP/2.0 603 Decline']
                for name in ['via','from','to','call-id','cseq']:
                    response.append(name + ': ' + headers[name] + (';tag=test-client' if name == 'to' else ''))
                sock.sendto(('\r\n'.join(response)+'\r\nContent-Length: 0\r\n\r\n').encode(), address)
                assert fixture.signaling.parse(sock.recvfrom(65535)[0])[1]['cseq'] == '1 ACK'
                wire.wait_complete(peer)
                wire.register(peer, client, expires=0)
                assert len(peer.completed_calls) == number
                assert len(peer.registrations) == number and len(peer.unregistrations) == number
        import json
        value = json.loads((tmp_path/'observed.json').read_text())
        assert value['completed_calls'] == 2 and value['host'] == '127.0.0.1'
        assert peer.password not in json.dumps(value)
    finally: peer.close()


def test_outgoing_wire_proof_requires_an_invite_and_its_matching_ack(tmp_path):
    peer = fixture.RecordedCallPeer(tmp_path, 'outgoing', media_host='127.0.0.1')
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.bind(('127.0.0.1', 0)); client.settimeout(3)
            wire.register(peer, client)
            packet = ['INVITE sip:private-peer@127.0.0.1 SIP/2.0',
                      'Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bKcall',
                      'From: <sip:family-test@127.0.0.1>;tag=client', 'To: <sip:private-peer@127.0.0.1>',
                      'Call-ID: private-outgoing', 'CSeq: 1 INVITE', 'Content-Length: 0', '', '']
            client.sendto('\r\n'.join(packet).encode(), ('127.0.0.1',peer.port))
            first, values = fixture.signaling.parse(client.recvfrom(65535)[0])
            assert first == 'SIP/2.0 486 Busy Here'
            assert not peer.completed_calls
            packet[0] = packet[0].replace('INVITE ', 'ACK ', 1); packet[5] = 'CSeq: 1 ACK'
            client.sendto('\r\n'.join(packet).encode(), ('127.0.0.1',peer.port))
            wire.wait_complete(peer)
            wire.register(peer, client, expires=0)
            assert peer.completed_calls == {'private-outgoing'}
    finally: peer.close()
    peer.record()  # Final cleanup proof must remain writable after socket close.
    import json
    value = json.loads((tmp_path/'observed.json').read_text())
    assert value['bound_local_interface'] and value['completed_calls'] == 1
    assert all('@' not in row for row in value['last_messages'])
