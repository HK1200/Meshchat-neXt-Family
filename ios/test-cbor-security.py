"""Verify the bundled mobile decoder's depth bound and trust-state reset."""
import argparse,importlib.abc,importlib.util,json,sys
from io import BytesIO
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def check(protocol,codec):
    nested=b'\x81'*1000+b'\x00'
    for decode in (protocol.decode,lambda data:protocol.decode_item(data)[0]):
        try:decode(nested)
        except codec.CBORDecodeError:pass
        except RecursionError:raise AssertionError('Nested input must hit the decoder depth guard, not interpreter recursion') from None
        else:raise AssertionError('Nested input exceeded the supported RRC envelope depth')
        assert decode(protocol.encode({0:1,1:'still working'}))=={0:1,1:'still working'}
    return True

def main(stage,report):
    sys.path.insert(0,str(stage.resolve()))
    import cbor2
    from meshchatnext.src.backend.rrc import protocol as next_protocol
    assert next_protocol.cborx.__name__=='cbor2'
    check(next_protocol,cbor2)
    # A reused decoder may not expose a prior message's shareable values.
    decoder=cbor2.CBORDecoder(BytesIO(b''),max_depth=64)
    decoder.decode_from_bytes(cbor2.dumps(cbor2.CBORTag(28,'synthetic private value')))
    try:decoder.decode_from_bytes(cbor2.dumps(cbor2.CBORTag(29,0)))
    except cbor2.CBORDecodeError:pass
    else:raise AssertionError('Shared references must not cross independent decode calls')
    class NoCBORx(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname=='cborx':raise ModuleNotFoundError('Use the actual iOS fallback',name='cborx')
            return None
    assert 'cborx' not in sys.modules
    guard=NoCBORx();sys.meta_path.insert(0,guard)
    try:
        spec=importlib.util.spec_from_file_location('family_mobile_cbor_security',ROOT/'app/src/main/python/meshchatnext/src/backend/rrc/protocol.py')
        family=importlib.util.module_from_spec(spec);spec.loader.exec_module(family)
    finally:sys.meta_path.remove(guard)
    assert family.cbor.__name__=='cbor2';check(family,cbor2)
    values=[{0:1,2:b'\x00\xff'},['canonical',True,None,-1,1.5]]
    for protocol in (next_protocol,family):
        wire=b''.join(protocol.encode(v) for v in values)
        a,pos=protocol.decode_item(wire);b,end=protocol.decode_item(wire,pos)
        assert [a,b]==values and end==len(wire)
    result={'ok':True,'next_and_family_depth_bounded':True,'valid_frames_after_rejection':True,
            'independent_decodes_do_not_share_values':True,'canonical_frames_and_offsets':True,'native_extension_required':False}
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--staged',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();main(args.staged,args.report)
