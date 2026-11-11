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
    monkeypatch.setitem(sys.modules, "LXST.Mixer", types.SimpleNamespace(Backend=None))
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

    frames.clear()
    source.filters = [types.SimpleNamespace(handle_frame=lambda samples, rate: np.zeros_like(samples))]
    source.push(pcm)
    source.push(pcm, native_processing=True)
    assert frames == [bytes(len(pcm)), pcm]


def test_late_hangup_is_harmless_and_cannot_end_a_new_call():
    voice = FamilyVoice(None, {}, threading.RLock(), lambda: None, autostart=False)
    voice.hangup("already-ended")
    voice.phase = "connected"
    voice.call_id = "new-call"
    voice.phone = types.SimpleNamespace(active_call=object())
    generation = voice.generation
    voice.hangup("already-ended")
    assert voice.phase == "connected"
    assert voice.call_id == "new-call" and voice.generation == generation


def test_capture_restores_gain_control_for_quiet_and_loud_speech():
    np = pytest.importorskip("numpy")
    from LXST.Codecs import Raw
    from LXST.Filters import AGC
    telephony = types.SimpleNamespace()
    voice = FamilyVoice(None, {}, threading.RLock(), lambda: None, autostart=False)
    voice._install_audio(telephony)
    results = []
    for amplitude in (0.03, 0.8):
        frames = []
        agc = AGC(target_level=-15)
        raw = Raw(channels=1, bitdepth=16)
        sink = types.SimpleNamespace(can_receive=lambda **kwargs: True,
                                     handle_frame=lambda frame, source: frames.append(raw.decode(frame)))
        source = telephony.LineSource(target_frame_ms=60, codec=raw, sink=sink, filters=[agc])
        source.start()
        assert agc.target_linear == pytest.approx(10 ** (-15 / 20))
        assert agc.max_gain_linear == pytest.approx(10 ** (12 / 20))
        wave = np.sin(np.arange(2880) * 2 * np.pi * 1000 / 48000) * amplitude
        pcm = (wave * 32767).astype("<i2").tobytes()
        for _ in range(120):
            source.push(pcm)
        assert len(frames) == 120
        output = np.concatenate(frames[-20:])
        assert np.isfinite(output).all() and np.max(np.abs(output)) <= 0.751
        rms = float(np.sqrt(np.mean(output ** 2)))
        results.append(rms)
        if amplitude == 0.03:
            assert rms > float(np.sqrt(np.mean(wave ** 2))) * 2
        else:
            assert rms < 0.25
    assert results[1] / results[0] < 4


def test_ios_software_gain_keeps_quiet_speech_and_peak_headroom():
    np = pytest.importorskip("numpy")
    from LXST.Filters import AGC
    from lxst_audio_processing import prepare_capture_filters

    signal = np.sin(np.arange(2880, dtype=np.float32) * 2 * np.pi * 1000 / 48000)
    standard, enhanced = AGC(target_level=-15), AGC(target_level=-15)
    prepare_capture_filters([standard])
    prepare_capture_filters([enhanced], default_max_gain_db=18)
    for _ in range(120):
        baseline = standard.handle_frame(signal * 0.01, 48000)
        boosted = enhanced.handle_frame(signal * 0.01, 48000)
    assert np.linalg.norm(boosted) > 1.7 * np.linalg.norm(baseline)
    assert np.max(np.abs(enhanced.handle_frame(signal * 0.95, 48000))) <= 0.751


def test_ios_extra_speech_gain_waits_for_the_speaker_echo_to_decay():
    from family_voice import ios_transmit_gain

    assert ios_transmit_gain(2.0, 2.0, 0.004, 0.01) == 1
    assert ios_transmit_gain(2.6, 2.0, 0.01, 0.01) == 1
    assert ios_transmit_gain(2.6, 2.0, 0.015, 0.006) == pytest.approx(10 ** (5 / 20))
    assert ios_transmit_gain(2.8, 2.0, 0.004, 0.01) == pytest.approx(10 ** (5 / 20))
