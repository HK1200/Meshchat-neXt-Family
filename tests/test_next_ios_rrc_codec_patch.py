from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe'))
from mobile_rrc_codec import portable_rrc

SOURCE=b'''import cborx
_STREAM_DECODER = cborx.CBORDecoder()
def encode(obj): return cborx.dumps(obj, canonical=True)
def decode(data): return cborx.loads(data)
def decode_item(data, pos=0):
    return _STREAM_DECODER.decode_item(data, pos)
'''

def test_preserves_wire_canonical_encoding_and_stream_offsets_without_native_extension():
    result=portable_rrc(SOURCE)
    assert b'import cbor2 as cborx' in result
    assert b'canonical=True' in result and b'stream.seek(pos)' in result and b'stream.tell()' in result


@pytest.mark.parametrize('source',[b'',SOURCE+SOURCE,SOURCE.replace(b'import cborx',b'import changed')])
def test_requires_the_exact_pinned_protocol_boundary(source):
    with pytest.raises(ValueError):portable_rrc(source)
