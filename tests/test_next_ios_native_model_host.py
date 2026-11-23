"""The model phase cannot silently change UI test execution or app permissions."""
import copy
import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('native_model_host',Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe/isolate-native-model-host.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def targets():
    return [{"BlueprintName": name, "EnvironmentVariables": {"fixture": "127.0.0.1"},
             "OnlyTestIdentifiers": ["actual_behavior"], "TestHostPath": "original-path"}
            for name in (module.UNIT, module.UI)]


@pytest.mark.parametrize('modern',[True,False])
def test_only_native_environment_changes_without_skipping_any_behavior(modern):
    rows=targets()
    value={'TestConfigurations':[{'TestTargets':rows}]} if modern else {row['BlueprintName']:row for row in rows}
    before=copy.deepcopy(value)
    actual=module.isolate(value)
    assert actual is value
    assert rows[0]['EnvironmentVariables'][module.FLAG]=='1'
    assert rows[1]==(before['TestConfigurations'][0]['TestTargets'][1] if modern else before[module.UI])
    assert rows[0]['OnlyTestIdentifiers']==['actual_behavior']
    assert rows[0]['TestHostPath']=='original-path'


@pytest.mark.parametrize('change',['missing','duplicate','foreign','preenabled','bad_environment'])
def test_rejects_ambiguous_or_pre_overridden_test_targets(change):
    rows=targets()
    if change=='missing':rows.pop()
    elif change=='duplicate':rows[1]['BlueprintName']=module.UNIT
    elif change=='foreign':rows[0]['BlueprintName']='RegularFamily'
    elif change=='preenabled':rows[1]['EnvironmentVariables'][module.FLAG]='1'
    elif change=='bad_environment':rows[0]['EnvironmentVariables']=[]
    with pytest.raises(ValueError):module.isolate({'TestConfigurations':[{'TestTargets':rows}]})


def test_integration_leaves_ui_launch_on_the_original_run_file():
    script=(Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe/test-simulators.sh').read_text()
    assert '"${native_test_arguments[@]}" \\\n        -only-testing:NextRuntimeProbeUnitTests' in script
    assert '"${test_arguments[@]}" \\\n        -only-testing:NextRuntimeProbeUITests' in script


def test_actual_cli_round_trip_retains_original_and_all_ui_configuration(tmp_path):
    import json, plistlib, subprocess, sys
    source=tmp_path/'original.xctestrun';output=tmp_path/'native.xctestrun';proof=tmp_path/'proof.json'
    value={'TestConfigurations':[{'TestTargets':targets()}], '__xctestrun_metadata__':{'FormatVersion':2}}
    raw=plistlib.dumps(value);source.write_bytes(raw)
    subprocess.run([sys.executable,spec.origin,str(source),str(output),str(proof)],check=True,timeout=15)
    assert source.read_bytes()==raw
    result=plistlib.loads(output.read_bytes())
    assert result['TestConfigurations'][0]['TestTargets'][1]==value['TestConfigurations'][0]['TestTargets'][1]
    assert json.loads(proof.read_text())['all_tests_retained'] is True


def test_cli_refuses_to_overwrite_the_original_run_file(tmp_path):
    import plistlib, subprocess, sys
    source=tmp_path/'original.xctestrun';raw=plistlib.dumps({row['BlueprintName']:row for row in targets()});source.write_bytes(raw)
    result=subprocess.run([sys.executable,spec.origin,str(source),str(source),str(tmp_path/'proof.json')],capture_output=True,timeout=15)
    assert result.returncode!=0 and source.read_bytes()==raw


def test_cli_rejects_relocation_that_would_break_xcode_testroot(tmp_path):
    import plistlib, subprocess, sys
    products=tmp_path/'DerivedData/Build/Products'; products.mkdir(parents=True)
    source=products/'original.xctestrun'
    rows=targets()
    rows[0]['TestHostPath']='__TESTROOT__/Debug-iphonesimulator/NextRuntimeProbe.app'
    raw=plistlib.dumps({'TestConfigurations':[{'TestTargets':rows}]});source.write_bytes(raw)
    output=tmp_path/'native.xctestrun'
    result=subprocess.run([sys.executable,spec.origin,str(source),str(output),str(tmp_path/'proof.json')],capture_output=True,timeout=15)
    assert result.returncode!=0 and not output.exists() and source.read_bytes()==raw
    assert b'beside its original built products' in result.stderr


def test_integration_keeps_native_testroot_beside_built_products():
    script=(Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe/test-simulators.sh').read_text()
    assert 'native_test_run="$(dirname -- "${test_runs[0]}")/native-models.xctestrun"' in script
    assert 'native_test_arguments=(-xctestrun "$native_test_run")' in script
