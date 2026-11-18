"""Only a pre-entry simulator launch stall may retry the private SIP fixture."""
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest

source = Path(__file__).resolve().parents[1] / 'ios/test-sip-registration.py'
spec = importlib.util.spec_from_file_location('family_sip_startup_fixture', source)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def install(monkeypatch, diagnostics, *, authenticated=False):
    peers = []
    calls = []
    def registrar():
        peer = SimpleNamespace(user='private-test', password='temporary', port=12345,
                               authenticated=False, unregistered=False, closed=False)
        peer.close = lambda: setattr(peer, 'closed', True)
        peers.append(peer)
        return peer
    def run(command, **kwargs):
        calls.append(command)
        if 'launchctl' in command:
            return subprocess.CompletedProcess(command, 0)
        if len(peers) == 1:
            peers[-1].authenticated = authenticated
            raise subprocess.TimeoutExpired(['redacted'], 70, stderr=diagnostics)
        peers[-1].authenticated = peers[-1].unregistered = True
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(fixture, 'Registrar', registrar)
    monkeypatch.setattr(fixture.subprocess, 'run', run)
    return peers, calls


def test_pre_entry_launch_stall_gets_one_retry(monkeypatch):
    peers, calls = install(monkeypatch, b'')
    fixture.verify_registration('simulator', 'fixture')
    assert len(peers) == 2 and all(p.closed for p in peers)
    assert sum('launchctl' in c for c in calls) == 1


@pytest.mark.parametrize('diagnostic,authenticated', [
    (b'Private SIP registration fixture entered\n', False), (b'', True),
])
def test_entered_or_authenticated_fixture_cannot_retry(monkeypatch, diagnostic, authenticated):
    peers, calls = install(monkeypatch, diagnostic, authenticated=authenticated)
    with pytest.raises(RuntimeError, match='startup timed out'):
        fixture.verify_registration('simulator', 'fixture')
    assert len(peers) == 1 and peers[0].closed
    assert all('launchctl' not in c for c in calls)
