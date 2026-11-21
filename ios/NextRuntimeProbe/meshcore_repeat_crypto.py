"""Repeat-fingerprint key agreement using the already bundled Reticulum provider.

This matches MeshCore's expanded Ed25519 scalar conversion. It neither changes
radio messages nor transmits anything; the result fingerprints overheard packets.
"""
import hmac


def shared_secret(private, montgomery_u):
    from RNS.Cryptography.X25519 import X25519PrivateKey
    p = (1 << 255) - 19
    if (not isinstance(private, bytes) or len(private) != 32
            or type(montgomery_u) is not int or not 0 <= montgomery_u < p):
        raise ValueError("Invalid repeat-fingerprint key")
    secret = X25519PrivateKey.from_private_bytes(private).exchange(montgomery_u.to_bytes(32, "little"))
    if hmac.compare_digest(secret, bytes(32)):
        raise ValueError("Invalid low-order peer public key")
    return secret
