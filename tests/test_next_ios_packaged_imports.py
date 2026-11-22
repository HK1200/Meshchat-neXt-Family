"""Detect deferred feature dependencies missing from the deployed app."""
import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('packaged_imports',Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe/verify-runtime-imports.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

@pytest.mark.parametrize('body',[
 'def contact_card():\n from family_cards import export_contact\n',
 'import family_cards\n',
 'import importlib\ndef load():\n return importlib.import_module("family_cards")\n',
 'def load():\n return __import__("family_cards")\n',
])
def test_missing_deferred_local_helper_is_rejected_and_packaging_it_resolves_failure(tmp_path,body):
    source=tmp_path/'source';source.mkdir();(source/'family_cards.py').write_text('')
    staged=tmp_path/'staged';staged.mkdir();(staged/'runtime.py').write_text(body)
    with pytest.raises(ValueError,match='family_cards.py'):module.verify(staged,[source])
    (staged/'family_cards.py').write_text('')
    assert module.verify(staged,[source])==2


def test_external_and_embedded_modules_are_not_invented_as_local_dependencies(tmp_path):
    source=tmp_path/'source';source.mkdir();staged=tmp_path/'staged';staged.mkdir()
    (staged/'runtime.py').write_text('import _next_sip\nimport RNS\n')
    assert module.verify(staged,[source])==1


def test_android_exception_is_limited_to_its_actual_worker(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'family_radio_pacing.py').write_text('')
    staged=tmp_path/'staged';staged.mkdir();(staged/'family_radios.py').write_text('from family_radio_pacing import install\n')
    assert module.verify(staged,[source])==1
    (staged/'other.py').write_text('from family_radio_pacing import install\n')
    with pytest.raises(ValueError,match='other.py'):module.verify(staged,[source])
