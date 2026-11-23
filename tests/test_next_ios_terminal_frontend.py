"""The exact released terminal page retains its controls and explains iOS limits."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('terminal_frontend', ROOT / 'ios/NextRuntimeProbe/terminal_frontend.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
SOURCE = (ROOT / 'tests/fixtures/next-027-rnsh-page.js.txt').read_text()


def test_exact_released_terminal_page_keeps_controls_with_visible_mobile_guidance(tmp_path):
    assert hashlib.sha256(SOURCE.encode()).hexdigest() == module.SHA256
    path = tmp_path / module.CHUNK; path.parent.mkdir(parents=True); path.write_text(SOURCE)
    module.stage(tmp_path)
    patched = path.read_text()
    assert patched.count('role:"note"') == 1
    assert 'Hosting a local shell requires desktop neXt.' in patched
    for method in ('async createConnectSession()', 'async createListenSession()', 'async sendCommand()', 'async loadSessions()'):
        assert patched.count(method) == SOURCE.count(method) == 1
    check = tmp_path / 'terminal.mjs'; check.write_text(patched)
    subprocess.run(['node', '--check', str(check)], check=True, capture_output=True, timeout=10)


def test_changed_page_is_preserved_instead_of_silently_patched(tmp_path):
    for source in ('changed', SOURCE + SOURCE):
        with pytest.raises(ValueError): module.rewrite(source)
    path = tmp_path / module.CHUNK; path.parent.mkdir(parents=True); path.write_text('changed')
    with pytest.raises(ValueError): module.stage(tmp_path)
    assert path.read_text() == 'changed'
