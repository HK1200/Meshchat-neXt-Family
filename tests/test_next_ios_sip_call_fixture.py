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
