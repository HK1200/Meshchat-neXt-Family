"""The pinned accessibility adapter fails closed when its input changes."""
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"))
import nomad_accessibility


def test_the_real_helper_is_injected_once_without_changing_other_parser_code(tmp_path, monkeypatch):
    source = "class Renderer {" + nomad_accessibility.BEFORE + "return t;}}\nexport {Renderer};"
    target = tmp_path / nomad_accessibility.CHUNK
    target.parent.mkdir()
    target.write_text(source)
    monkeypatch.setattr(nomad_accessibility, "SHA256", hashlib.sha256(source.encode()).hexdigest())
    nomad_accessibility.stage(tmp_path)
    result = target.read_text()
    assert result.startswith(source.replace(nomad_accessibility.BEFORE, nomad_accessibility.BEFORE + "__nextLabelNomadLinks(t);"))
    assert result.count("function __nextLabelNomadLinks(root)") == 1
    assert "export function labelNomadLinks" not in result
    module = tmp_path / "checked.mjs"
    module.write_text(result)
    subprocess.run(["node", "--check", str(module)], check=True, capture_output=True)


def test_unreviewed_checksum_keeps_the_original_bundle_untouched(tmp_path):
    target = tmp_path / nomad_accessibility.CHUNK
    target.parent.mkdir()
    target.write_text("changed upstream parser")
    with pytest.raises(ValueError, match="pinned Micron parser changed"):
        nomad_accessibility.stage(tmp_path)
    assert target.read_text() == "changed upstream parser"


@pytest.mark.parametrize("source", ["", nomad_accessibility.BEFORE * 2])
def test_missing_or_ambiguous_accessibility_entrypoint_is_rejected(source):
    with pytest.raises(ValueError, match="entry point changed"):
        nomad_accessibility.rewrite(source)
