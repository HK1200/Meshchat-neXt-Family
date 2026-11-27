"""Stage the actual pinned release through every mobile frontend adapter."""
import hashlib
import os
from pathlib import Path
import re
import runpy
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[1]
PROBE=ROOT/'ios/NextRuntimeProbe'
ADAPTERS=('sip_frontend.py','voice_frontend.py','audio_frontend.py','location_frontend.py',
          'rncp_frontend.py','terminal_frontend.py','nomad_frontend.py','nomad_accessibility.py')


def test_actual_released_frontend_stages_all_native_adapters(tmp_path):
    configured=os.environ.get('NEXT_IOS_FRONTEND_ZIP')
    if not configured:
        pytest.skip('Release artifact supplied by the encrypted-media CI job')
    archive=Path(configured)
    script=(PROBE/'test-simulators.sh').read_text()
    pins=re.findall(r"'([0-9a-f]{64})  frontend.zip'",script)
    assert len(pins)==1
    with archive.open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest()==pins[0]
    frontend=tmp_path/'frontend';frontend.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
        bundle.extractall(frontend)
    for name in ADAPTERS:
        module=runpy.run_path(str(PROBE/name))
        module['stage'](frontend)
    shared=list((frontend/'assets').glob('shared-async-*.js'))
    assert len(shared)==1
    assert '__nextCreateNativeLocationClient' in shared[0].read_text()
    app=list((frontend/'assets').glob('app-*.js'))
    calls=list((frontend/'assets').glob('CallPage-*.js'))
    assert len(app)==len(calls)==1
    for file in app+calls:
        assert 'const __nextVoiceCall=this.activeCall?.call_id;' in file.read_text()
    assert (frontend/'index.html').is_file()
