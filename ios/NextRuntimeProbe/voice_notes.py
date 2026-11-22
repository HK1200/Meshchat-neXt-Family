"""Bounded LXMF voice notes using the bundled upstream Opus/Ogg codecs."""

import io
import wave

OPUS = 0x10
CODEC2_MODES = frozenset(range(1, 10))
MAX_OPUS_BYTES = 2 * 1024 * 1024
MAX_CODEC2_BYTES = 512 * 1024
MAX_PCM_BYTES = 8 * 1024 * 1024
MAX_RECORDING_BYTES = 9_950_000


def valid(mode, data):
    return (
        type(mode) is int
        and isinstance(data, bytes)
        and bool(data)
        and (
            (
                mode == OPUS
                and len(data) <= MAX_OPUS_BYTES
                and data.startswith(b"OggS")
                and b"OpusHead" in data[:128]
            )
            or (mode in CODEC2_MODES and len(data) <= MAX_CODEC2_BYTES)
        )
    )


def encode(mode, data):
    if type(mode) is not int or not isinstance(data, bytes) or not data:
        raise ValueError("Invalid voice recording")
    if mode == OPUS and not data.startswith(b"OggS"):
        data = _encode_recording(data)
    if not valid(mode, data):
        raise ValueError(
            "Use a valid Opus recording up to 2 MB or Codec2 recording up to 512 KB"
        )
    return mode, data


def _encode_recording(data):
    """Feed bounded PCM chunks to the same upstream Ogg writer as desktop."""
    if len(data) > MAX_RECORDING_BYTES:
        raise ValueError("Voice recording exceeds the 10 MB recording limit")
    import audioop
    from LXST.Codecs import Opus
    from LXST.Codecs.libs.pyogg import OggOpusWriter, OpusBufferedEncoder, ogg
    from lxst_pyogg_ctypes_compat import repair_ogg_stream_state

    repair_ogg_stream_state(ogg)
    try:
        with wave.open(io.BytesIO(data), "rb") as recording:
            channels, width, rate = (
                recording.getnchannels(),
                recording.getsampwidth(),
                recording.getframerate(),
            )
            size = recording.getnframes() * channels * width
            if (
                channels not in (1, 2)
                or width != 2
                or not 8000 <= rate <= 192000
                or not 0 < size <= MAX_RECORDING_BYTES
            ):
                raise ValueError("Use a bounded 16-bit mono or stereo voice recording")
            profile = Opus.PROFILE_VOICE_HIGH
            encoder = OpusBufferedEncoder()
            encoder.set_application(Opus.profile_application(profile))
            encoder.set_sampling_frequency(48000)
            encoder.set_channels(1)
            encoder.set_frame_size(60)
            encoder.set_max_bytes_per_frame(
                Opus.max_bytes_per_frame(Opus.profile_bitrate_ceiling(profile), 60)
            )
            target = io.BytesIO()
            writer = OggOpusWriter(target, encoder)
            read, state = 0, None
            try:
                while chunk := recording.readframes(4096):
                    read += len(chunk)
                    if channels == 2:
                        chunk = audioop.tomono(chunk, 2, 0.5, 0.5)
                    if rate != 48000:
                        chunk, state = audioop.ratecv(chunk, 2, 1, rate, 48000, state)
                    writer.write(memoryview(bytearray(chunk)))
                    if target.tell() > MAX_OPUS_BYTES:
                        raise ValueError("Voice recording exceeds the 2 MB Opus limit")
            finally:
                writer.close()
            if read != size:
                raise ValueError("Incomplete voice recording")
            return target.getvalue()
    except (wave.Error, EOFError, TypeError) as error:
        raise ValueError("Could not read the voice recording") from error


def playable_wav(data):
    """Stream Opus into capped mono WAV; works before iOS gained Ogg playback.

    libopusfile handles framing, preskip, output gain and chained streams. Its
    URL/HTTP helper is not included. Never allocate from untrusted duration tags.
    """
    if not valid(OPUS, data):
        raise ValueError("Invalid Opus voice recording")
    import audioop
    import ctypes
    from LXST.Codecs.libs.pyogg import opus

    encoded = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    error = ctypes.c_int()
    handle = opus.op_open_memory(encoded, len(data), ctypes.byref(error))
    if not handle or error.value:
        if handle:
            opus.op_free(handle)
        raise ValueError("Could not open the Opus voice recording")
    target = io.BytesIO()
    pcm = (ctypes.c_int16 * (5760 * 2))()
    size, state, holes = 0, None, 0
    try:
        with wave.open(target, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            while True:
                samples = opus.op_read_stereo(handle, pcm, len(pcm))
                if samples == 0:
                    break
                if samples < 0:
                    # OP_HOLE can be a recoverable discontinuity; bound retries.
                    if samples == -3 and holes < 8:
                        holes += 1
                        continue
                    raise ValueError("Could not decode the Opus voice recording")
                chunk = ctypes.string_at(pcm, samples * 4)
                mono = audioop.tomono(chunk, 2, 0.5, 0.5)
                converted, state = audioop.ratecv(mono, 2, 1, 48000, 16000, state)
                size += len(converted)
                if size > MAX_PCM_BYTES:
                    raise ValueError(
                        "This recording is too long for the inline player; save the original recording instead"
                    )
                output.writeframesraw(converted)
        if size == 0:
            raise ValueError("The voice recording contains no audio")
        return target.getvalue()
    finally:
        opus.op_free(handle)


def diagnostic():
    """Synthetic round trip required by the native bundled-runtime test."""
    import numpy as np

    rate = 48000
    samples = (0.2 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate) * 32767).astype(
        "<i2"
    )
    recording = io.BytesIO()
    with wave.open(recording, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())
    mode, encoded = encode(OPUS, recording.getvalue())
    decoded = playable_wav(encoded)
    with wave.open(io.BytesIO(decoded), "rb") as source:
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(
            float
        )
        if (
            source.getnchannels() != 1
            or source.getframerate() != 16000
            or abs(len(pcm) - 16000) > 320
        ):
            raise ValueError("Voice note duration or format changed")
    rms = float(np.sqrt(np.mean(pcm * pcm)))
    frequency = float(np.argmax(abs(np.fft.rfft(pcm))) * 16000 / len(pcm))
    if rms < 1000 or abs(frequency - 440) > 5:
        raise ValueError("Voice note round trip lost the synthetic audio")
    return dict(
        ok=True,
        mode=mode,
        encoded_bytes=len(encoded),
        decoded_bytes=len(decoded),
        rms=rms,
        frequency=frequency,
        network_used=False,
        microphone_used=False,
    )
