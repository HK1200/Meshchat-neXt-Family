"""Regression checks for Reticulum write failures and the Android PCM bridge."""
import socket
import sys
import threading
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/src/main/python"))
from family_voice import FamilyVoice, PLAYBACK_CHUNK, VoicePlaybackBuffer


def test_tcp_write_failure_reconnects_and_restores_sending(monkeypatch, tmp_path):
    pytest.importorskip("RNS")
    import RNS
    from family_tcp import FamilyTCPInterface, HDLC, TCPClientInterface

    (tmp_path / "config").write_text("[reticulum]\nshare_instance = No\n[interfaces]\n")
    RNS.Reticulum(configdir=str(tmp_path), loglevel=1)
    monkeypatch.setattr(TCPClientInterface, "RECONNECT_WAIT", 0.05)
    monkeypatch.setattr(RNS.Transport, "synthesize_tunnel", lambda interface: None)
    create_connection = socket.create_connection

    class FailedWrite:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def sendall(self, data):
            raise BrokenPipeError("simulated write failure with reader still blocked")

    def fail_first_connection(*args):
        connection = create_connection(*args)
        if not connections:
            connection = FailedWrite(connection)
        connections.append(connection)
        return connection

    connections = []
    monkeypatch.setattr(socket, "create_connection", fail_first_connection)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(5)
        client = FamilyTCPInterface(object(), {
            "name": "Family test", "target_host": "127.0.0.1",
            "target_port": listener.getsockname()[1], "connect_timeout": 1,
        })
        client.OUT = True
        try:
            peer, _ = listener.accept()
            with peer:
                assert client.online
                client.process_outgoing(b"simulated packet")
                peer.settimeout(2)
                assert peer.recv(1) == b""
            replacement, _ = listener.accept()
            with replacement:
                deadline = time.monotonic() + 2
                while not client.online and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert client.online and client.OUT and client.family_connection_epoch == 2
                payload = bytes([1, HDLC.FLAG, HDLC.ESC])
                client.process_outgoing(payload)
                replacement.settimeout(2)
                assert replacement.recv(32) == bytes([HDLC.FLAG]) + HDLC.escape(payload) + bytes([HDLC.FLAG])
        finally:
            client.detach()


def test_playback_waits_for_jitter_reserve_and_discards_stale_audio():
    buffer = VoicePlaybackBuffer()
    audio = b"\x12\x34" * (PLAYBACK_CHUNK // 2)
    buffer.append(audio * 5)
    assert buffer.pull() == b""
    buffer.append(audio)
    assert [buffer.pull() for _ in range(6)] == [audio] * 6
    assert buffer.pull() == b"" and buffer.underruns == 1
    buffer.append(audio)
    assert buffer.pull() == b""
    buffer.append(b"\x56\x78" * (PLAYBACK_CHUNK // 2) * 25)
    assert buffer.dropped_bytes == PLAYBACK_CHUNK
    assert buffer.pull() == b"\x56\x78" * (PLAYBACK_CHUNK // 2)
    buffer.clear()
    assert buffer.pull() == b"" and buffer.underruns == buffer.dropped_bytes == 0


def test_capture_splits_or_joins_chunks_at_negotiated_profile(monkeypatch):
    np = pytest.importorskip("numpy")
    base = type("AudioBase", (), {})
    monkeypatch.setitem(sys.modules, "LXST.Sources", types.SimpleNamespace(LocalSource=base))
    monkeypatch.setitem(sys.modules, "LXST.Sinks", types.SimpleNamespace(LocalSink=base))
    monkeypatch.setitem(sys.modules, "LXST.Codecs", types.SimpleNamespace(Raw=lambda **kwargs: None))
    telephony = types.SimpleNamespace()
    voice = FamilyVoice(None, {}, threading.RLock(), lambda: None, autostart=False)
    voice._install_audio(telephony)

    pcm = np.arange(2880, dtype="<i2").tobytes()
    for frame_ms, expected in ((60, 1), (20, 3), (10, 6)):
        frames = []
        codec = types.SimpleNamespace(encode=lambda samples: (samples * 32768).astype("<i2").tobytes())
        sink = types.SimpleNamespace(
            can_receive=lambda **kwargs: True,
            handle_frame=lambda frame, source: frames.append(frame),
        )
        source = telephony.LineSource(target_frame_ms=frame_ms, codec=codec, sink=sink)
        source.start()
        source.push(pcm[:500])
        source.push(pcm[500:2048])
        source.push(pcm[2048:])
        assert len(frames) == expected
        assert b"".join(frames) == pcm

    source = telephony.LineSource(target_frame_ms=60, codec=codec, sink=sink)
    source.start()
    assert source.push(pcm[:100]) == 0
    voice.set_muted(True)
    assert not source.pending
