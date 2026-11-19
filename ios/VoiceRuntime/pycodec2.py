"""Codec2 API for LXST using Family’s signed iOS codec framework."""
import array
import ctypes
import weakref

from family_ios_codecs import library

MODES = {3200: 0, 2400: 1, 1600: 2, 1400: 3, 1300: 4, 1200: 5, 700: 8}
LIB = library()
for name, args, result in (
    ("codec2_create", [ctypes.c_int], ctypes.c_void_p),
    ("codec2_destroy", [ctypes.c_void_p], None),
    ("codec2_samples_per_frame", [ctypes.c_void_p], ctypes.c_int),
    ("codec2_bytes_per_frame", [ctypes.c_void_p], ctypes.c_int),
    ("codec2_encode", [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], None),
    ("codec2_decode", [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], None),
):
    function = getattr(LIB, name)
    function.argtypes = args
    function.restype = result


class Codec2:
    def __init__(self, mode):
        self._codec = LIB.codec2_create(MODES[mode])
        if not self._codec:
            raise ValueError(f"Unsupported Codec2 mode: {mode}")
        self._cleanup = weakref.finalize(self, LIB.codec2_destroy, self._codec)
        self._samples = LIB.codec2_samples_per_frame(self._codec)
        self._bytes = LIB.codec2_bytes_per_frame(self._codec)

    def samples_per_frame(self):
        return self._samples

    def bytes_per_frame(self):
        return self._bytes

    def encode(self, samples):
        pcm = array.array("h")
        pcm.frombytes(memoryview(samples).cast("B"))
        if len(pcm) != self._samples:
            raise ValueError("Invalid Codec2 PCM frame size")
        encoded = ctypes.create_string_buffer(self._bytes)
        LIB.codec2_encode(self._codec, encoded, pcm.buffer_info()[0])
        return encoded.raw

    def decode(self, encoded):
        if len(encoded) != self._bytes:
            raise ValueError("Invalid Codec2 packet size")
        pcm = (ctypes.c_short * self._samples)()
        LIB.codec2_decode(self._codec, pcm, encoded)
        return pcm
