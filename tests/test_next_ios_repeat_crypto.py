"""Published AES/X25519 vectors; no radio access or RF transmissions."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ios/NextRuntimeProbe'))
sys.path.insert(0, str(ROOT / 'app/src/main/python'))
from family_ios_meshcore_crypto import AES
from meshcore_repeat_crypto import shared_secret


@pytest.mark.parametrize('key,ciphertext', [
    ('000102030405060708090a0b0c0d0e0f', '69c4e0d86a7b0430d8cdb78070b4c55a'),
    ('000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f', '8ea2b7ca516745bfeafc49904b496089'),
])
def test_nist_aes_ecb_vectors_and_independent_blocks(key, ciphertext):
    cipher = AES.new(bytes.fromhex(key), AES.MODE_ECB)
    plaintext = bytes.fromhex('00112233445566778899aabbccddeeff')
    encrypted = bytes.fromhex(ciphertext)
    assert cipher.encrypt(plaintext * 3) == encrypted * 3
    assert cipher.decrypt(encrypted * 3) == plaintext * 3
    assert cipher.encrypt(b'') == cipher.decrypt(b'') == b''
    with pytest.raises(ValueError): cipher.encrypt(plaintext[:-1])
    with pytest.raises(ValueError): cipher.decrypt(encrypted[:-1])


def test_rfc7748_x25519_shared_secret():
    private = bytes.fromhex('77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a')
    peer = bytes.fromhex('de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f')
    expected = bytes.fromhex('4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742')
    assert shared_secret(private, int.from_bytes(peer, 'little')) == expected


@pytest.mark.parametrize('private,u', [(b'',9), (b'x'*31,9), (b'x'*33,9), ('x'*32,9), (b'x'*32,True), (b'x'*32,-1), (b'x'*32,(1<<255)-19)])
def test_malformed_keys_are_rejected(private,u):
    with pytest.raises(ValueError): shared_secret(private,u)


@pytest.mark.parametrize('u',[0,1])
def test_low_order_peers_are_rejected(u):
    with pytest.raises(ValueError): shared_secret(bytes(range(32)),u)
