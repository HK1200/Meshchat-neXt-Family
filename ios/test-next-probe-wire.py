"""Private loopback proof of the iOS RNProbe HTTP contract with standard RNS."""
import argparse, asyncio, hashlib, json, os, socket, subprocess, sys, time
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
BACKEND=Path(os.environ['NEXT_TEST_BACKEND_SOURCE']).resolve()
sys.path[:0]=[str(ROOT/'ios/NextRuntimeProbe'),str(BACKEND)]
import RNS


def peer(folder,port):
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'config').write_text('[reticulum]\nshare_instance = No\nenable_transport = No\n[interfaces]\n[[Private proof server]]\ntype = TCPServerInterface\nenabled = Yes\nlisten_ip = 127.0.0.1\nlisten_port = '+str(port)+'\n')
    RNS.Reticulum(configdir=str(folder),loglevel=1)
    identity=RNS.Identity()
    destination=RNS.Destination(identity,RNS.Destination.IN,RNS.Destination.SINGLE,'test','echo','request')
    destination.set_proof_strategy(RNS.Destination.PROVE_ALL)
    received=[]
    def record(data,packet):
        received.append(dict(size=len(data),sha256=hashlib.sha256(data).hexdigest()))
        pending=folder/'received.pending';pending.write_text(json.dumps(received));pending.replace(folder/'received.json')
    destination.set_packet_callback(record)
    (folder/'ready.json').write_text(json.dumps(dict(destination_hash=destination.hash.hex(),full_name='test.echo.request')))
    announced=set();deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        for interface in tuple(RNS.Transport.interfaces):
            if getattr(interface,'online',False) and getattr(interface,'OUT',False) and id(interface) not in announced:
                interface.ingress_control=False
                destination.announce(attached_interface=interface);announced.add(id(interface))
        time.sleep(.05)


async def client(folder,port):
    from aiohttp import web
    from aiohttp.test_utils import TestClient,TestServer
    from network_runtime import NetworkRuntime
    target=folder/'client';target.mkdir()
    (target/'config').write_text('[reticulum]\nshare_instance = No\nenable_transport = No\n[interfaces]\n[[Private proof client]]\ntype = TCPClientInterface\nenabled = Yes\ntarget_host = 127.0.0.1\ntarget_port = '+str(port)+'\n')
    reticulum=RNS.Reticulum(configdir=str(target),loglevel=1)
    for interface in tuple(RNS.Transport.interfaces):interface.ingress_control=False
    ready=json.loads((folder/'peer/ready.json').read_text())
    destination=bytes.fromhex(ready['destination_hash'])
    deadline=time.monotonic()+15
    while not RNS.Transport.has_path(destination):
        assert time.monotonic()<deadline,'No path over private loopback TCP'
        await asyncio.sleep(.05)
    runtime=NetworkRuntime(SimpleNamespace(reticulum=reticulum,identity=RNS.Identity(),connections=SimpleNamespace(snapshot=lambda:[])),lambda address:False)
    app=web.Application();runtime.register(app.router)
    async with TestClient(TestServer(app)) as http:
        response=await http.post('/api/v1/rnprobe',json={**ready,'size':24,'probes':2,'wait':.05,'timeout':3})
        value=await response.json()
        assert response.status==200,value
        assert value['sent']==value['delivered']==2 and value['timeouts']==value['failed']==0,value
        assert all(row['rtt']>0 and row['size']==24 for row in value['results'])
        received=json.loads((folder/'peer/received.json').read_text())
        assert len(received)==2 and all(row['size']==24 for row in received)
        assert len({row['sha256'] for row in received})==2
        assert runtime.probe_slots._value==1
        report=dict(real_standard_reticulum_packets=True,private_loopback_only=True,public_packets_sent=False,delivered=2,valid_receipt_proofs=2,unique_random_payloads=True,source='iOS NetworkRuntime',rtts=[row['rtt'] for row in value['results']])
        (folder/'proof.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--peer',type=int)
    args=parser.parse_args();folder=args.folder.resolve()
    if args.peer is not None:
        assert 1024<=args.peer<=65535;peer(folder,args.peer);return
    folder.mkdir(parents=True,exist_ok=False)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with (folder/'peer.log').open('w') as log:
        process=subprocess.Popen([sys.executable,__file__,'--folder',str(folder/'peer'),'--peer',str(port)],stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+15
            while not (folder/'peer/ready.json').exists():
                assert process.poll() is None,'Private peer exited'
                assert time.monotonic()<deadline,'Private peer did not start'
                time.sleep(.05)
            asyncio.run(asyncio.wait_for(client(folder,port),30))
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':main()
