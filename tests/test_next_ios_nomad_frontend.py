"""Native archive downloads fail closed when the pinned interface changes."""
import hashlib
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe'))
import nomad_frontend


def test_rewrite_keeps_other_frontend_code_and_uses_the_native_export():
    source = '/*before*/' + nomad_frontend.BEFORE + ';/*after*/'
    result = nomad_frontend.rewrite(source)
    assert result.startswith('/*before*/' + nomad_frontend.AFTER + ';/*after*/')
    assert 'function __nextExportArchives(filters,' in result
    assert 'export function' not in result
    assert result.count('/api/v1/nomadnet/archives/export') == 1
    assert nomad_frontend.BEFORE not in result


@pytest.mark.parametrize('source', ['', nomad_frontend.BEFORE * 2])
def test_unexpected_frontend_is_rejected(source):
    with pytest.raises(ValueError): nomad_frontend.rewrite(source)


def test_changed_checksum_leaves_the_frontend_untouched(tmp_path):
    target = tmp_path / nomad_frontend.CHUNK
    target.parent.mkdir()
    target.write_text(nomad_frontend.BEFORE)
    before = target.read_bytes()
    assert hashlib.sha256(before).hexdigest() != nomad_frontend.SHA256
    with pytest.raises(ValueError): nomad_frontend.stage(tmp_path)
    assert target.read_bytes() == before
