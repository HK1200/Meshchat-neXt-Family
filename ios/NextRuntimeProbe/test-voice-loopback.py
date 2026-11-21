"""Private real-RNS/LXST media proof. No microphone, speaker or public peer.

Run with --backend-source pointing to the checksum-verified staged neXt bundle
and --work-dir inside an ignored media-volume test directory. Only CallKit's
permission/answer boundary is simulated; links, codecs and PCM are production.
"""
import argparse
import asyncio
from collections import deque
from contextlib import ExitStack
import ctypes
import ctypes.util
import importlib.util
import json
import multiprocessing
from pathlib import Path
import socket
import sqlite3
import sys
import time
from types import SimpleNamespace


def worker(source, folder, port, server, pipe, silent_control=False):
    folder = Path(folder)
    folder.mkdir(parents=True)
    # Isolate backend code from the staged iOS-only NumPy binaries.
    (folder / 'meshchatnext').symlink_to(Path(source) / 'meshchatnext', target_is_directory=True)
    sys.path.insert(0, str(folder))
    adapter_path = Path(__file__).resolve().parents[1] / 'VoiceRuntime/pycodec2.py'
    library = ctypes.CDLL(ctypes.util.find_library('codec2'))
    sys.modules['family_ios_codecs'] = SimpleNamespace(library=lambda: library)
    spec = importlib.util.spec_from_file_location('pycodec2', adapter_path)
    adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    sys.modules['pycodec2'] = adapter
    import numpy as np
    import RNS
    from voice_runtime import ReticulumVoice
    config = folder / 'rns'; config.mkdir()
    interface = ('type = TCPServerInterface\nlisten_ip = 127.0.0.1\nlisten_port' if server else
                 'type = TCPClientInterface\ntarget_host = 127.0.0.1\ntarget_port')
    (config / 'config').write_text('[reticulum]\nshare_instance = No\nenable_transport = No\n'
                                  '[interfaces]\n[[Private voice]]\nenabled = Yes\n' + interface + f' = {port}\n')
    RNS.Reticulum(configdir=str(config), loglevel=1)

    async def run():
        events = deque(); contacts = {}; incoming_events = 0; policy_denials = 0
        def native(value):
            nonlocal incoming_events
            if value['op'] == 'dial': events.append(dict(operation='dial', call_id=value['call_id']))
            if value['op'] == 'state' and value.get('state') == 'incoming':
                incoming_events += 1
                events.append(dict(operation='answer', call_id=value['call_id']))
            if value['op'] == 'poll':
                result = list(events); events.clear(); return dict(ok=True, events=result)
            return dict(ok=True)
        db = sqlite3.connect(folder / 'voice.sqlite3')
        identity = RNS.Identity()
        voice = ReticulumVoice(db, identity, lambda: contacts, lambda: RNS.Transport.interfaces,
                               lambda: 'Private synthetic voice', native=native)
        original_allowed = voice.caller_allowed
        def observed_allowed(identity_hash):
            nonlocal policy_denials
            allowed = original_allowed(identity_hash)
            if not allowed: policy_denials += 1
            return allowed
        voice.caller_allowed = observed_allowed
        await voice.configure(True); await voice.start()
        phase = 0
        tone_until = 0.
        samples = energy = peak = 0
        async def media():
            nonlocal phase, samples, energy, peak
            while True:
                call = voice.call
                if call and call.phase == 'connected':
                    if time.monotonic() < tone_until and not silent_control:
                        frame = (.07 * np.sin(2 * np.pi * 440 * (np.arange(960) + phase) / 48000) * 32767).astype('<i2')
                        phase += 960; voice.push(call.id, frame.tobytes(), True)
                    else: voice.push(call.id, bytes(1920), True)
                    data = voice.pull(call.id)
                    if data:
                        pcm = np.frombuffer(data, dtype='<i2').astype(np.float64) / 32768
                        samples += len(pcm); energy += float(np.sum(pcm ** 2)); peak = max(peak, float(np.max(np.abs(pcm))))
                await asyncio.sleep(.02)
        media_task = asyncio.create_task(media())
        pipe.send(dict(address=voice.snapshot()['address'], identity=identity.hash.hex(),
                       lxmf=RNS.Destination.hash_from_name_and_identity('lxmf.delivery',identity.hash).hex()))
        try:
            while True:
                command = await asyncio.to_thread(pipe.recv)
                op = command['op']
                try:
                    if op == 'dial': await voice.dial(command['peer'])
                    elif op == 'tone':
                        samples = energy = peak = 0; tone_until = time.monotonic() + command.get('seconds', 3)
                    elif op == 'reset': samples = energy = peak = 0
                    elif op == 'announce': await voice.announce_due(force=True)
                    elif op == 'contacts-only':voice.set_call_policy({'telephone_allow_calls_from_contacts_only':True})
                    elif op == 'approve':
                        from voice_runtime import address
                        contacts[address(command['address'])]={'name':'Approved private peer'}
                        voice.refresh_call_contacts()
                    elif op == 'hangup': await voice.end()
                    elif op == 'profile':
                        await voice.set_profile(command['value'], dict(call_id=voice.call.id))
                    elif op == 'stop': pipe.send(dict(ok=True)); break
                    elif op != 'status': raise ValueError('Unknown private test command')
                    state = voice.snapshot()
                    pipe.send(dict(ok=True, state=state, samples=samples, incoming_events=incoming_events, policy_denials=policy_denials,
                                   rms=(energy / samples) ** .5 if samples else 0, peak=peak,
                                   profiles=voice.profile_choices() if op == 'status' else None))
                except Exception as error: pipe.send(dict(ok=False, error=str(error)))
        finally:
            media_task.cancel(); await asyncio.gather(media_task, return_exceptions=True)
            await voice.close(); db.close()
    asyncio.run(run())


def rpc(pipe, op, **values):
    pipe.send(dict(op=op, **values)); assert pipe.poll(40), f'{op} worker timed out'
    value = pipe.recv(); assert value.get('ok'), value
    return value


def wait(pipes, predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        values = [rpc(pipe, 'status') for pipe in pipes]
        if predicate(values): return values
        time.sleep(.1)
    raise AssertionError('Private voice condition timed out: ' + json.dumps(values))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-source', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument("--silent-negative-control", action="store_true", help="Inject silence; this command must fail its settled-tone assertion")
    args = parser.parse_args()
    assert (args.backend_source / 'meshchatnext/src/backend/telephone_manager.py').is_file()
    args.work_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    with socket.socket() as socket_:
        socket_.bind(('127.0.0.1', 0)); port = socket_.getsockname()[1]
    proof = dict(public_network=False, microphone=False, speaker=False, checks=[], negotiated_profiles=[])
    with ExitStack() as stack:
        pipes = []
        addresses = []; identities = []; lxmf_addresses = []
        for index in range(2):
            pipe, child = multiprocessing.get_context('spawn').Pipe()
            process = multiprocessing.get_context('spawn').Process(target=worker, args=(
                str(args.backend_source.resolve()), str(args.work_dir / str(index)), port, index == 0, child, args.silent_negative_control))
            process.start(); child.close()
            def cleanup(process=process, pipe=pipe):
                pipe.close()
                if process.is_alive(): process.terminate()
                process.join(5)
                if process.is_alive(): process.kill(); process.join()
                process.close()
            stack.callback(cleanup)
            assert pipe.poll(30), 'Voice worker did not start'
            ready=pipe.recv();addresses.append(ready['address']);identities.append(ready['identity']);lxmf_addresses.append(ready['lxmf']);pipes.append(pipe)
        assert addresses[0] != addresses[1]
        time.sleep(1)
        for pipe in pipes: rpc(pipe, 'announce')
        # Verify a real signed caller is refused before ringing when absent
        # from contacts, then admitted immediately after the local approval.
        rpc(pipes[1], 'contacts-only')
        rpc(pipes[0], 'dial', peer=addresses[1])
        refused=wait(pipes, lambda rows: all(not r['state']['is_busy'] for r in rows))
        assert refused[1]['policy_denials']>0, 'The signed caller did not reach the real incoming policy'
        assert refused[1]['incoming_events']==0
        assert refused[1]['state']['missed_calls_unread_count']==0
        for index in range(2):
            rpc(pipes[index], 'approve', address=lxmf_addresses[1-index])
            rpc(pipes[index], 'contacts-only')
        proof['unapproved_call_rejected_before_ringing']=True
        for caller in (0, 1):
            rpc(pipes[caller], 'dial', peer=addresses[1-caller])
            states = wait(pipes, lambda rows: all(r['state']['active_call'] and r['state']['active_call']['status'] == 6 for r in rows))
            assert all(row['state']['active_call']['remote_telephony_hash'] == addresses[1-i] for i, row in enumerate(states))
            assert all(row['state']['active_call']['remote_identity_hash'] == identities[1-i] for i, row in enumerate(states))
            profiles = [None]
            if caller == 0:
                available = states[0]['profiles']['audio_profiles']
                assert {16, 32, 48, 64}.issubset({row['id'] for row in available if row['available']}), 'Required Opus/Codec2 profiles are unavailable'
                profiles += [16, 32, 48, 64]
            for profile in profiles:
                if profile is not None:
                    rpc(pipes[caller], 'profile', value=profile)
                    negotiated=wait(pipes, lambda rows: all(r['state']['active_call'] and r['state']['active_call']['audio_profile_id']==profile for r in rows), timeout=12)
                    proof['negotiated_profiles'].append({'requested':profile,'actual':[row['state']['active_call']['audio_profile_id'] for row in negotiated]})
                    time.sleep(2)
                for sender in range(2):
                    receiver = 1 - sender
                    # Codec2 can emit low-level comfort noise while the
                    # sender is silent. Settled tone energy must exceed that
                    # baseline; nonempty decoded frames alone are not proof.
                    rpc(pipes[receiver], 'reset'); time.sleep(1)
                    baseline = rpc(pipes[receiver], 'status')['rms']
                    rpc(pipes[sender], 'tone', seconds=5)
                    time.sleep(1); rpc(pipes[receiver], 'reset'); time.sleep(2)
                    measured = rpc(pipes[receiver], 'status')
                    assert measured['samples'] >= 24000, measured
                    assert measured['rms'] > max(.001, baseline * 3), ('Silent/comfort-only audio cannot pass settled-tone proof', dict(baseline=baseline, measured=measured))
                    assert measured['peak'] < .99, measured
                    proof['checks'].append(dict(caller=caller, sender=sender, profile=profile,
                                                 samples=measured['samples'], rms=measured['rms'], peak=measured['peak'],
                                                 silent_baseline_rms=baseline, settled_tone_verified=True))
                    time.sleep(3)
            rpc(pipes[caller], 'hangup')
            wait(pipes, lambda rows: all(not r['state']['is_busy'] for r in rows))
        for pipe in pipes: rpc(pipe, 'stop')
    proof['ok'] = True
    (args.work_dir / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))


if __name__ == '__main__': main()
