"""Standard RNSh listener vs the iOS client, over private loopback TCP only."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ['NEXT_TEST_BACKEND_SOURCE']).resolve()
sys.path[:0] = [str(ROOT / 'ios/NextRuntimeProbe'), str(BACKEND)]
import RNS


def network(folder, server, port):
    folder.mkdir(parents=True, exist_ok=False)
    kind = 'TCPServerInterface' if server else 'TCPClientInterface'
    address = 'listen_ip = 127.0.0.1\nlisten_port = ' if server else 'target_host = 127.0.0.1\ntarget_port = '
    (folder / 'config').write_text('[reticulum]\nshare_instance = No\nenable_transport = No\n[interfaces]\n[[Private terminal proof]]\ntype = '+kind+'\nenabled = Yes\n'+address+str(port)+'\n')
    reticulum = RNS.Reticulum(configdir=str(folder), loglevel=1)
    for interface in tuple(RNS.Transport.interfaces): interface.ingress_control = False
    return reticulum


async def peer(folder, port, allowed):
    from RNS.Utilities.rnsh.session import ListenerSession, RNSOutlet
    network(folder / 'rns', True, port)
    identity = RNS.Identity()
    worker = folder / 'fixed-echo-worker.py'
    worker.write_text("import sys\nprint('Private RNSh ready',flush=True)\nfor line in sys.stdin:\n text=line.rstrip('\\r\\n')\n if text=='quit': raise SystemExit(7)\n print('Echo: '+text,flush=True)\n")
    ListenerSession.allowed_identity_hashes = [bytes.fromhex(allowed)]
    ListenerSession.allowed_file_identity_hashes = []
    ListenerSession.allow_all = False
    ListenerSession.allow_remote_command = False
    ListenerSession.default_command = [sys.executable, '-u', str(worker)]
    ListenerSession.remote_cmd_as_args = False
    destination = RNS.Destination(identity, RNS.Destination.IN, RNS.Destination.SINGLE, 'rnsh')
    loop = asyncio.get_running_loop(); sessions = []
    def established(link):
        sessions.append(ListenerSession(RNSOutlet.get_outlet(link), link.get_channel(), loop))
    destination.set_link_established_callback(established)
    (folder / 'ready.json').write_text(json.dumps(dict(destination=destination.hash.hex())))
    stop = asyncio.Event(); loop.add_signal_handler(signal.SIGTERM, stop.set)
    announced = set()
    try:
        while not stop.is_set():
            for interface in tuple(RNS.Transport.interfaces):
                if getattr(interface, 'online', False) and getattr(interface, 'OUT', False) and id(interface) not in announced:
                    interface.ingress_control = False
                    destination.announce(attached_interface=interface); announced.add(id(interface))
            if ListenerSession.sessions: await ListenerSession.pump_all()
            observed_tmp = folder / 'observed.tmp'
            observed_tmp.write_text(json.dumps(dict(accepted=sum(s.authenticated for s in sessions),
                only_approved_identity=all(s.remote_identity is None or s.remote_identity.hash.hex()==allowed for s in sessions),return_codes=[s.return_code for s in sessions])))
            observed_tmp.replace(folder / 'observed.json')
            await asyncio.sleep(.01)
    finally:
        await ListenerSession.terminate_all('Private test finished')


async def client(folder, port, identity, target):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from terminal_runtime import TerminalRuntime
    reticulum = network(folder / 'client-rns', False, port)
    events = []
    async def publish(event): events.append(event)
    runtime = TerminalRuntime(SimpleNamespace(reticulum=reticulum, source=SimpleNamespace(identity=identity)), folder / 'client-terminal', lambda address: False, publish)
    app = web.Application(); runtime.register(app.router)
    async def wait(check, seconds=20):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = check()
            if value: return value
            await asyncio.sleep(.05)
        raise RuntimeError('Private terminal condition timed out')
    async with TestClient(TestServer(app)) as http:
        try:
            response = await http.post('/api/v1/rnsh/sessions', json={**target, 'name': 'Private standard host', 'mirror': True})
            result = await response.json(); assert response.status==200,result
            identifier = result['session']['id']; session=runtime.sessions[identifier]
            def ready():
                if session.status=='failed': raise AssertionError(session.last_error)
                return 'Private RNSh ready' in session.record()['output_text']
            await wait(ready,30)
            text = 'unicode:' + ''.join(chr(0x400 + (i * 37) % 768) for i in range(300))
            response = await http.post('/api/v1/rnsh/sessions/'+identifier+'/input', json={'text': text, 'newline': True})
            assert response.status==200,await response.text()
            await wait(lambda:'Echo: '+text in session.record()['output_text'],30)
            response = await http.post('/api/v1/rnsh/sessions/'+identifier+'/resize', json={'rows':31,'cols':89})
            assert response.status==200
            response = await http.post('/api/v1/rnsh/sessions/'+identifier+'/input', json={'text':'quit','newline':True})
            assert response.status==200
            await wait(lambda:session.worker.done(),30)
            observed=json.loads((folder/'peer/observed.json').read_text())
            reported=observed['return_codes'][-1]
            assert type(reported) is int and session.remote_exit_code==session.last_exit_code==reported
            assert session.status==('failed' if reported else 'stopped')
            await runtime.tick()
            saved=runtime.state.read_bytes()
            observed=json.loads((folder/'peer/observed.json').read_text())
            assert observed['accepted']==1 and observed['only_approved_identity']
            await runtime.close()
            reopened=TerminalRuntime(SimpleNamespace(reticulum=reticulum, source=SimpleNamespace(identity=identity)), folder/'client-terminal', lambda address:False, publish)
            assert not reopened.error and reopened.sessions[identifier].worker is None
            assert 'Echo: '+text in reopened.sessions[identifier].record()['output_text']
            assert reopened.state.read_bytes()==saved
            await reopened.close()
            proof=dict(private_loopback_only=True,public_packets_sent=False,standard_rnsh_listener=True,
                approved_identity_authenticated=True,unicode_input_bytes=len(text.encode()),
                split_input_and_ordered_output_match=True,remote_worker_requested_exit=7,standard_peer_reported_exit=reported,mirror_matches_received_status=True,upstream_wait_status_limitation=reported!=7,
                history_and_settings_survive_restart=True,remote_command_not_repeated_after_restart=True,
                local_shell_execution_on_client=False,actual_ipad=False)
            (folder/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof))
        finally: await runtime.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--port',type=int);parser.add_argument('--allowed')
    args=parser.parse_args();folder=args.folder.resolve()
    if args.port is not None:
        asyncio.run(peer(folder,args.port,args.allowed));return
    folder.mkdir(parents=True,exist_ok=False)
    identity=RNS.Identity()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with (folder/'peer.log').open('w') as log:
        process=subprocess.Popen([sys.executable,__file__,'--folder',str(folder/'peer'),'--port',str(port),'--allowed',identity.hash.hex()],stdout=log,stderr=subprocess.STDOUT)
        try:
            end=time.monotonic()+20
            while not (folder/'peer/ready.json').exists():
                assert process.poll() is None,'Private standard listener failed'
                assert time.monotonic()<end
                time.sleep(.05)
            target=json.loads((folder/'peer/ready.json').read_text())
            asyncio.run(asyncio.wait_for(client(folder,port,identity,target),100))
        finally:
            process.terminate()
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
