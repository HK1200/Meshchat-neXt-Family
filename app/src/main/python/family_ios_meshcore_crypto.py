"""MeshCore packet primitives using the bundled Reticulum and Python providers."""
import hashlib
import hmac


class SHA256:
    digest_size = 32
    block_size = 64
    new = staticmethod(hashlib.sha256)


class HMAC:
    @staticmethod
    def new(key, msg=b"", digestmod=SHA256):
        if digestmod is not SHA256:
            raise ValueError("Only SHA-256 is supported")
        return hmac.new(key, msg, hashlib.sha256)


class AES:
    MODE_ECB = 1

    @staticmethod
    def new(key, mode):
        if mode != AES.MODE_ECB or len(key) not in (16, 32):
            raise ValueError("MeshCore decoding requires AES-128 or AES-256 ECB")
        return _ECB(key)


class _ECB:
    def __init__(self, key):
        from RNS.Cryptography.aes import AES128, AES256
        self.cipher = AES128(key) if len(key) == 16 else AES256(key)
        self.bits = len(key) * 8

    def decrypt(self, data):
        if len(data) % 16:
            raise ValueError("AES ciphertext must contain complete blocks")
        # CBC of a single block with a zero IV is ECB. No padding is removed.
        blocks = [data[offset:offset + 16] for offset in range(0, len(data), 16)]
        if self.bits == 128:
            return b"".join(self.cipher.decrypt(block, bytes(16)) for block in blocks)
        return b"".join(self.cipher.decrypt_block(block) for block in blocks)

    def encrypt(self, data):
        if len(data) % 16:
            raise ValueError("AES plaintext must contain complete blocks")
        # CBC of each independent block with a zero IV is ECB, without padding.
        blocks = [data[offset:offset + 16] for offset in range(0, len(data), 16)]
        if self.bits == 128:
            return b"".join(self.cipher.encrypt(block, bytes(16)) for block in blocks)
        return b"".join(self.cipher.encrypt_block(block) for block in blocks)
