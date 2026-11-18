#!/usr/bin/env python3
"""Check native incoming decline and outgoing rejection on a private SIP peer.

Exercises signaling only. Speaker, microphone and two-way audio remain separate
physical-device checks. No public provider or personal account is used.
"""
import importlib.util
from pathlib import Path
import platform
import re
import secrets
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sip_registration_fixture', ROOT / 'test-sip-registration.py')
registration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registration)


def parse(raw):
    lines = raw.decode('utf-8', 'strict').split('\r\n')
    headers = {}
    for line in lines[1:]:
        if not line:
            break
        name, value = line.split(':', 1)
        headers[name.lower()] = value.strip()
    return lines[0], headers


class CallPeer(registration.Registrar):
    def __init__(self, mode):
        self.mode = mode
        self.invited = False
        self.call_complete = False
        self.call_id = secrets.token_hex(12)
        self.branch = 'z9hG4bK' + secrets.token_hex(8)
        self.timer = None
        self.packet_summaries = []
        super().__init__()

    def close(self):
        if self.timer:
            self.timer.cancel()
            self.timer.join(timeout=2)
        super().close()

    def handle(self, raw, address):
        first, values = parse(raw)
        self.packet_summaries = (self.packet_summaries + [first])[-8:]
        if first.startswith('REGISTER '):
            super().handle(raw, address)
            if self.mode == 'incoming' and self.authenticated and not self.unregistered and not self.invited:
                self.invited = True
                contact = re.search(r'<(sip:[^>]+)>', values['contact'])
                if not contact:
                    raise RuntimeError('Native SIP register omitted its contact URI')
                self.contact = contact[1]
                self.timer = threading.Timer(0.3, self.invite, args=(address,))
                self.timer.start()
        elif first.startswith('INVITE ') and self.mode == 'outgoing':
            self.invited = True
            headers = ['SIP/2.0 486 Busy Here']
            for name in ['via', 'from', 'to', 'call-id', 'cseq']:
                value = values[name]
                if name == 'to' and ';tag=' not in value:
                    value += ';tag=private-peer'
                headers.append(name + ': ' + value)
            self.socket.sendto(('\r\n'.join(headers) + '\r\nContent-Length: 0\r\n\r\n').encode(), address)
        elif first.startswith('ACK ') and self.mode == 'outgoing':
            self.call_complete = True
        elif first.startswith('SIP/2.0 ') and self.mode == 'incoming' and values.get('call-id') == self.call_id:
            if int(first.split()[1]) >= 300:
                packet = [f'ACK {self.contact} SIP/2.0',
                          f'Via: SIP/2.0/UDP 127.0.0.1:{self.port};branch={self.branch}',
                          'Max-Forwards: 70', 'From: ' + values['from'], 'To: ' + values['to'],
                          'Call-ID: ' + self.call_id, 'CSeq: 1 ACK', 'Content-Length: 0', '', '']
                self.socket.sendto('\r\n'.join(packet).encode(), address)
                self.call_complete = True

    def invite(self, address):
        body = ('v=0\r\no=private-peer 1 1 IN IP4 127.0.0.1\r\ns=Private signaling test\r\n'
                'c=IN IP4 127.0.0.1\r\nt=0 0\r\nm=audio 40000 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\na=sendrecv\r\n')
        packet = [f'INVITE {self.contact} SIP/2.0',
                  f'Via: SIP/2.0/UDP 127.0.0.1:{self.port};branch={self.branch}',
                  'Max-Forwards: 70', f'From: <sip:private-peer@127.0.0.1:{self.port}>;tag=private-peer',
                  f'To: <sip:{self.user}@127.0.0.1:{self.port}>', 'Call-ID: ' + self.call_id,
                  'CSeq: 1 INVITE', f'Contact: <sip:private-peer@127.0.0.1:{self.port}>',
                  'Content-Type: application/sdp', f'Content-Length: {len(body.encode())}', '', body]
        self.socket.sendto('\r\n'.join(packet).encode(), address)


def main(simulator):
    arch = platform.machine()
    directory = ROOT / 'RuntimeBuild/sip' / ('iphonesimulator-' + arch)
    executable = directory / 'sip-signaling-test'
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path'], text=True).strip()
    command = ['xcrun', '--sdk', 'iphonesimulator', 'clang', '-target', arch + '-apple-ios17.0-simulator', '-isysroot', sdk,
               '-I' + str(ROOT / 'LiveRuntime'), '-I' + str(ROOT / 'RuntimeBuild/sip/re-4.12.0/include'),
               '-I' + str(ROOT / 'RuntimeBuild/sip/baresip-4.12.0/include'),
               str(ROOT / 'SIPPolicyTests/signaling.c'), str(ROOT / 'LiveRuntime/FamilySIP.c'), str(directory / 'libFamilySIP.a'),
               '-framework', 'AudioToolbox', '-framework', 'CoreAudio', '-framework', 'CoreFoundation',
               '-framework', 'Security', '-framework', 'SystemConfiguration', '-lresolv', '-lz', '-o', str(executable)]
    subprocess.run(command, check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(executable)], check=True)
    for mode in ['incoming', 'outgoing']:
        peer = CallPeer(mode)
        try:
            result = subprocess.run(['xcrun', 'simctl', 'spawn', simulator, str(executable), peer.user,
                                     str(peer.port), peer.password, mode], capture_output=True, text=True, timeout=50)
            if result.returncode or not (peer.authenticated and peer.unregistered and peer.call_complete):
                raise RuntimeError(f'Native SIP {mode} signaling failed: ' + result.stdout + result.stderr +
                                   f' fixture authenticated={peer.authenticated}, invited={peer.invited}, '
                                   f'completed={peer.call_complete}, unregistered={peer.unregistered}, packets={peer.packet_summaries}')
            print(f'Native SIP {mode} signaling completed and unregistered cleanly')
        finally:
            peer.close()


if __name__ == '__main__':
    main(sys.argv[1])
