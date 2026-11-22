"""Real upstream Ogg/Opus encode/decode and bounded private voice attachments."""

import base64
import io
from pathlib import Path
import struct
import sys
import wave

import LXMF
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ios/NextRuntimeProbe"), str(ROOT / "app/src/main/python")]
import attachment_fields  # noqa: E402 - runtime wrappers are outside the test package
import voice_notes  # noqa: E402 - runtime wrappers are outside the test package


def recording(rate=48000):
    samples = (0.25 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate) * 32767).astype(
        "<i2"
    )
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())
    return target.getvalue()


@pytest.mark.parametrize("rate", [16000, 44100, 48000])
def test_recorded_pcm_becomes_real_opus_and_playable_wav(rate):
    mode, encoded = voice_notes.encode(0x10, recording(rate))
    assert mode == 0x10 and encoded.startswith(b"OggS") and b"OpusHead" in encoded[:128]
    assert len(encoded) < 12000
    with wave.open(io.BytesIO(voice_notes.playable_wav(encoded)), "rb") as decoded:
        assert (
            decoded.getnchannels(),
            decoded.getsampwidth(),
            decoded.getframerate(),
        ) == (1, 2, 16000)
        assert abs(decoded.getnframes() - 16000) < 320
        pcm = np.frombuffer(
            decoded.readframes(decoded.getnframes()), dtype="<i2"
        ).astype(float)
        assert np.sqrt(np.mean(pcm * pcm)) > 1000
        spectrum = abs(np.fft.rfft(pcm))
        frequency = np.argmax(spectrum) * 16000 / len(pcm)
        assert abs(frequency - 440) < 5


def test_voice_fields_survive_roundtrip_and_history_stays_slim(tmp_path):
    from conversation_organization import ConversationOrganization
    from loopback_probe import ConversationHistory

    raw = attachment_fields.outgoing(
        {
            "audio": dict(
                audio_mode=0x10, audio_bytes=base64.b64encode(recording()).decode()
            )
        }
    )
    assert raw[LXMF.FIELD_AUDIO][1].startswith(b"OggS")
    received = attachment_fields.incoming(raw)
    assert (
        base64.b64decode(received["audio"]["audio_bytes"]) == raw[LXMF.FIELD_AUDIO][1]
    )
    assert (
        attachment_fields.slim({"fields": received})["fields"]["audio"]["audio_bytes"]
        is None
    )
    history = ConversationHistory(tmp_path / "history.sqlite3")
    try:
        peer = "ab" * 16
        history.ensure_contact(peer, "Private Audio")
        history.save(
            peer, dict(hash="cd" * 32, state="received", content="", fields=received)
        )
        assert history.summary(peer)["latest_message_preview"] == "Voice message"
        assert history.summary(peer)["has_attachments"]
        assert (
            ConversationOrganization(history).conversations(
                {"has_attachments": "true"}
            )["conversations"][0]["destination_hash"]
            == peer
        )
    finally:
        history.close()


@pytest.mark.parametrize("mode", range(1, 10))
def test_existing_codec2_fields_preserve_exact_wire_bytes(mode):
    data = b"\x01\x02\x03\x04"
    raw = attachment_fields.outgoing(
        {"audio": dict(audio_mode=mode, audio_bytes=base64.b64encode(data).decode())}
    )
    assert raw[LXMF.FIELD_AUDIO] == [mode, data]
    assert attachment_fields.incoming(raw)["audio"]["audio_mode"] == mode


@pytest.mark.parametrize(
    "mode,data",
    [
        (True, b"x"),
        (17, b"x"),
        (0x10, b"not audio"),
        (1, b""),
        (1, b"x" * (512 * 1024 + 1)),
    ],
)
def test_invalid_recordings_fail_before_transmission(mode, data):
    with pytest.raises(ValueError):
        voice_notes.encode(mode, data)
    assert attachment_fields.incoming({LXMF.FIELD_AUDIO: [mode, data]}) == {}


def test_declared_wav_length_does_not_allocate_from_untrusted_header():
    data = bytearray(recording())
    data[40:44] = struct.pack("<I", 0x7FFFFFF0)
    with pytest.raises(ValueError):
        voice_notes.encode(0x10, bytes(data))


def test_decoded_audio_has_a_hard_budget_and_releases_native_handle(monkeypatch):
    from LXST.Codecs.libs.pyogg import opus

    _, encoded = voice_notes.encode(0x10, recording())
    original = opus.op_free
    freed = []

    def release(handle):
        freed.append(True)
        original(handle)

    monkeypatch.setattr(opus, "op_free", release)
    monkeypatch.setattr(voice_notes, "MAX_PCM_BYTES", 128)
    with pytest.raises(ValueError, match="too long"):
        voice_notes.playable_wav(encoded)
    assert freed == [True]


def test_bad_ogg_does_not_crash_the_player():
    with pytest.raises(ValueError):
        voice_notes.playable_wav(b"OggS" + b"OpusHead" + b"\x00" * 32)


def audio_only_hub(folder, ports, pipe):
    import LXMF
    import RNS

    folder.mkdir()
    assert len(ports) == 1
    (folder / "config").write_text(
        "[reticulum]\nshare_instance = No\nenable_transport = Yes\n"
        "[interfaces]\n[[Private audio]]\ntype = TCPServerInterface\nenabled = Yes\n"
        f"listen_ip = 127.0.0.1\nlisten_port = {ports[0]}\n"
    )
    RNS.Reticulum(configdir=str(folder), loglevel=1)
    identity = RNS.Identity()
    router = LXMF.LXMRouter(
        identity=identity, storagepath=str(folder / "lxmf"), autopeer=False
    )
    source = router.register_delivery_identity(
        identity, display_name="Private audio-only test", stamp_cost=0
    )

    def reply(message):
        if not message.signature_validated:
            return
        recalled = RNS.Identity.recall(message.source_hash)
        target = RNS.Destination(
            recalled, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery"
        )
        router.handle_outbound(
            LXMF.LXMessage(
                target,
                source,
                "",
                fields=message.fields,
                desired_method=LXMF.LXMessage.DIRECT,
            )
        )

    router.register_delivery_callback(reply)
    source.announce()
    pipe.send(source.hash.hex())
    pipe.recv()


def test_audio_only_signed_exchange_and_wav_http_playback(tmp_path):
    from contextlib import ExitStack
    import json
    import socket
    from urllib.request import urlopen
    from test_next_ios_tcp_integration import (
        api,
        backend,
        private_request,
        run_server,
        start,
        wait,
    )

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with ExitStack() as stack:
        _, pipe = start(stack, audio_only_hub, tmp_path / "hub", [port])
        assert pipe.poll(20)
        address = pipe.recv()
        app = tmp_path / "app"
        app.mkdir()
        ready = app / "backend.url"
        settings = app / "peers.json"
        settings.write_text(
            json.dumps(
                dict(
                    address=address,
                    peers=[
                        dict(id="private", host="127.0.0.1", port=port, enabled=True)
                    ],
                )
            )
        )
        start(stack, run_server, app, ready, settings)
        wait(ready.is_file)
        base = backend(ready)
        token = api(base, "auth/csrf")[1]["csrf_token"]
        fields = {
            "audio": dict(
                audio_mode=0x10, audio_bytes=base64.b64encode(recording()).decode()
            )
        }
        assert (
            api(
                base,
                "lxmf-messages/send",
                body={
                    "lxmf_message": dict(
                        destination_hash=address, content="", fields=fields
                    )
                },
                token=token,
            )[0]
            == 200
        )

        def incoming():
            rows = api(base, "lxmf-messages/conversation/" + address)[1][
                "lxmf_messages"
            ]
            return next(
                (
                    row
                    for row in rows
                    if row["state"] == "received" and row["source_hash"] == address
                ),
                None,
            )

        echoed = wait(incoming, timeout=45)
        assert echoed["fields"]["audio"]["audio_bytes"] is None
        assert echoed["content"] == "" and not echoed["is_private_telemetry"]
        assert any(
            row["peer"] == address and row["hash"] == echoed["hash"]
            for row in api(base, "preview/unread-messages")[1]["messages"]
        )
        with urlopen(
            private_request(
                base, "/api/v1/lxmf-messages/attachment/" + echoed["hash"] + "/audio"
            ),
            timeout=10,
        ) as response:
            assert response.headers["Content-Type"].startswith("audio/wav")
            wav = response.read()
        with wave.open(io.BytesIO(wav), "rb") as decoded:
            assert decoded.getframerate() == 16000
            assert decoded.getnframes() > 15000
        with urlopen(
            private_request(
                base,
                "/api/v1/lxmf-messages/attachment/" + echoed["hash"] + "/audio?raw=1",
            ),
            timeout=10,
        ) as response:
            assert response.read().startswith(b"OggS")
        assert (
            api(base, "lxmf/conversations?has_attachments=true")[1]["conversations"][0][
                "destination_hash"
            ]
            == address
        )
