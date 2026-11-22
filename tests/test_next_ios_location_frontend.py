"""The shipped chat timer delegates GPS without losing its existing Stop controls."""
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
PROBE=ROOT/'ios/NextRuntimeProbe'
sys.path.insert(0,str(PROBE))
import location_frontend


def sample():
    return ('const unaffected="manual-and-MeshCore";'
            'function uo(e,t,a){if(co.has(e))return;co.set(e,{name:t,stop:()=>a.onStop?.("stopped")})}'
            'function mo(){for(const{stop:e}of co.values())e()}')


def test_rewrite_preserves_manual_timer_and_global_stop_and_adds_no_coordinate_bridge():
    source=sample();client=(PROBE/'native-location-client.mjs').read_text()
    changed=location_frontend.rewrite(source,client)
    old=source[source.index('function uo('):source.index('function mo(')]
    assert old.replace('function uo(', 'function __nextLegacyLocation(',1) in changed
    assert changed.startswith('const unaffected="manual-and-MeshCore";')
    assert changed.endswith('function mo(){for(const{stop:e}of co.values())e()}')
    assert changed.count('function uo(e,t,a){')==1
    assert '__nextNativeLocations.handles(e,a)' in changed
    assert 'native-location-client.mjs' not in changed
    assert 'navigator.geolocation' not in client


@pytest.mark.parametrize('source',[sample().replace('function uo(', 'function changed('),sample()+sample()])
def test_rewrite_rejects_changed_boundaries(source):
    with pytest.raises(ValueError):location_frontend.rewrite(source,(PROBE/'native-location-client.mjs').read_text())


def test_unverified_frontend_is_never_overwritten(tmp_path):
    file=tmp_path/location_frontend.CHUNK;file.parent.mkdir();file.write_text(sample())
    before=file.read_bytes()
    with pytest.raises(ValueError,match='checksum'):location_frontend.stage(tmp_path)
    assert file.read_bytes()==before


def test_real_javascript_client_lifecycle_and_cancellation():
    node=shutil.which('node')
    assert node,'Node is required to verify the bundled native location client'
    result=subprocess.run([node,'--test','--test-reporter=tap',str(PROBE/'test-native-location-client.mjs')],
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert '# tests 13\n' in result.stdout and '# pass 13\n' in result.stdout and '# fail 0\n' in result.stdout
