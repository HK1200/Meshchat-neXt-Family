"""Ephemeral IPv4 loopback SIP registrar for app-hosted native tests only."""
import argparse
import importlib.util
import json
from pathlib import Path
import signal
import threading

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('private_sip_registrar',root/'test-sip-registration.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


class RecordedRegistrar(fixture.Registrar):
    def __init__(self, folder):
        self.folder=folder
        self.registrations=set()
        self.unregistrations=set()
        super().__init__('127.0.0.1')
    def record(self):
        temporary=self.folder/'observed.tmp'
        temporary.write_text(json.dumps({'authenticated':self.authenticated,'unregistered':self.unregistered,'host':self.host,'registrations':len(self.registrations),'unregistrations':len(self.unregistrations)}))
        temporary.chmod(0o600)
        temporary.replace(self.folder/'observed.json')
    def handle(self, raw, address):
        lines=raw.decode('utf-8','replace').split('\r\n')
        headers={line.split(':',1)[0].lower():line.split(':',1)[1].strip() for line in lines[1:] if ':' in line}
        if lines[0].startswith('REGISTER ') and self.authorized(headers.get('authorization','')):
            identifier=headers.get('call-id','')
            if identifier:
                target=self.unregistrations if headers.get('expires')=='0' or 'expires=0' in headers.get('contact','') else self.registrations
                target.add(identifier)
        super().handle(raw,address)
        self.record()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path);args=parser.parse_args()
    args.folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    peer=RecordedRegistrar(args.folder)
    stopped=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stopped.set())
    try:
        account=args.folder/'account.json'
        account.write_text(json.dumps({'user':peer.user,'host':peer.host,'port':peer.port,'password':peer.password}))
        account.chmod(0o600)
        print('Private loopback SIP registrar ready',flush=True)
        stopped.wait()
    finally:
        peer.close();peer.record()


if __name__=='__main__':main()
