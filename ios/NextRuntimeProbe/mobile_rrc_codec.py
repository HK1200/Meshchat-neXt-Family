"""Backport the existing Family pure-Python CBOR support to pinned neXt RRC."""


def portable_rrc(source):
    changes=(
        (b'import cborx\n',b'import cbor2 as cborx\n'),
        (b'_STREAM_DECODER = cborx.CBORDecoder()',b'_STREAM_DECODER = None'),
        (b'return cborx.loads(data)', b'return cborx.loads(data, max_depth=64)'),
        (b'    return _STREAM_DECODER.decode_item(data, pos)',
         b'    from io import BytesIO\n    stream = BytesIO(data)\n    stream.seek(pos)\n    return cborx.CBORDecoder(stream, max_depth=64).decode(), stream.tell()'),
    )
    for before,after in changes:
        if source.count(before)!=1:raise ValueError('The pinned RRC codec boundary changed')
        source=source.replace(before,after)
    compile(source,'mobile-rrc-protocol','exec')
    return source
