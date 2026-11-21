"""Private on-runner SIP call peer with per-simulator signaling proof.

No call is answered, no microphone is read and no RTP is sent. Incoming tests
explicitly decline; outgoing tests receive Busy. Temporary account files are
included only in simulator test bundles, never in the device application.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import secrets
import signal
import socket
import threading

spec = importlib.util.spec_from_file_location('next_private_sip_signaling', Path(__file__).resolve().parents[1] / 'test-sip-signaling.py')
signaling = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signaling)


class RecordedCallPeer(signaling.CallPeer):
    def __init__(self, folder, mode, *, media_host):
        if mode not in ('incoming', 'outgoing'):
            raise ValueError('Choose a private call signaling direction')
        self.folder = Path(folder)
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.registrations = set()
        self.unregistrations = set()
        self.completed_calls = set()
        self.outgoing_invites = set()
        # Incoming signaling can use loopback with a real SDP interface.
        # For outgoing INVITEs, Baresip chooses its media interface from the SIP
        # destination itself. Bind that peer to this runner's own local address.
        signaling_host = '127.0.0.1' if mode == 'incoming' else media_host
        super().__init__(mode, media_host=signaling_host)
        self.media_host = media_host
        self.bound_local_interface = self.socket.getsockname()[0] == self.host

    def record(self):
        value = dict(host=self.host, mode=self.mode, authenticated=self.authenticated,
                     registrations=len(self.registrations), unregistrations=len(self.unregistrations),
                     completed_calls=len(self.completed_calls),
                     scope='loopback' if self.host == '127.0.0.1' else 'local-interface',
                     bound_local_interface=self.bound_local_interface,
                     last_messages=[' '.join(line.split()[:2]) if line.startswith('SIP/2.0 ') else line.split()[0]
                                    for line in self.packet_summaries])
        temporary = self.folder / 'observed.tmp'
        temporary.write_text(json.dumps(value)); temporary.chmod(0o600)
        temporary.replace(self.folder / 'observed.json')

    def handle(self, raw, address):
        first, headers = signaling.parse(raw)
        identifier = headers.get('call-id', '')
        if first.startswith('REGISTER ') and self.authorized(headers.get('authorization', '')) and identifier:
            expires = headers.get('expires') == '0' or 'expires=0' in headers.get('contact', '')
            if expires:
                self.unregistrations.add(identifier)
            elif identifier not in self.registrations:
                self.registrations.add(identifier)
                self.unregistered = False
                self.invited = False
                self.call_complete = False
                self.call_id = secrets.token_hex(12)
                self.branch = 'z9hG4bK' + secrets.token_hex(8)
        if first.startswith('INVITE ') and self.mode == 'outgoing' and identifier:
            self.outgoing_invites.add(identifier)
        super().handle(raw, address)
        if self.call_complete:
            if self.mode == 'incoming' and identifier == self.call_id:
                self.completed_calls.add(identifier)
            elif self.mode == 'outgoing' and first.startswith('ACK ') and identifier in self.outgoing_invites:
                self.completed_calls.add(identifier)
        self.record()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('mode', choices=['incoming', 'outgoing'])
    args = parser.parse_args()
    # Kernel route lookup only; UDP connect sends no packet.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect(('192.0.2.1', 9))
        media_host = route.getsockname()[0]
    peer = RecordedCallPeer(args.folder, args.mode, media_host=media_host)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: stopped.set())
    try:
        account = args.folder / 'account.json'
        account.write_text(json.dumps(dict(user=peer.user, host=peer.host, port=peer.port, password=peer.password)))
        account.chmod(0o600)
        print('Private on-runner native call peer ready', flush=True)
        stopped.wait()
    finally:
        peer.close(); peer.record()


if __name__ == '__main__': main()
