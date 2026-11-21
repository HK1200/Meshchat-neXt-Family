"""Fail-closed iOS SIP compatibility changes to the pinned frontend."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe'))
import sip_frontend


def synthetic_source():
    return ('/* unrelated Android/Linux code stays intact */'
            + ';'.join('["linux","windows"].includes(ws.platform)' for _ in range(3))
            + ';["linux","windows"].includes(e.platform);'
            + sip_frontend.COMMAND + ';'
            + 'Could not update SIP feature settings;/sip/status;SIP calling is unavailable in this build')


def test_backport_adds_only_ios_policy_and_exact_call_context():
    source = synthetic_source()
    changed = sip_frontend.rewrite(source)
    assert changed.count('["linux","windows","ios"]') == 4
    assert sip_frontend.COMMAND_IOS in changed
    assert '"ios"===ws.platform' in changed and '{call_id:ws.call_id}' in changed
    restored = changed.replace('["linux","windows","ios"]', '["linux","windows"]')
    assert restored.replace(sip_frontend.COMMAND_IOS, sip_frontend.COMMAND) == source


@pytest.mark.parametrize('source', [synthetic_source().replace('/sip/status', '/changed'),
                                   synthetic_source() + sip_frontend.COMMAND,
                                   synthetic_source().replace('includes(e.platform)', 'includes(other.platform)')])
def test_changed_bundle_boundaries_require_explicit_review(source):
    with pytest.raises(ValueError): sip_frontend.rewrite(source)


def test_unverified_source_cannot_be_overwritten(tmp_path):
    path = tmp_path / sip_frontend.CHUNK; path.parent.mkdir(); path.write_text(synthetic_source())
    before = path.read_bytes()
    with pytest.raises(ValueError, match='checksum'): sip_frontend.stage(tmp_path)
    assert path.read_bytes() == before
