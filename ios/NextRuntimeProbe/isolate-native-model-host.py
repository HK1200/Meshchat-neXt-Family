"""Change only the native XCTest target's environment in a separate run file."""
import argparse
import copy
import json
from pathlib import Path
import plistlib

FLAG = 'NEXT_NATIVE_MODEL_HOST'
UNIT = 'NextRuntimeProbeUnitTests'
UI = 'NextRuntimeProbeUITests'


def isolate(value):
    original = copy.deepcopy(value)
    if type(value) is not dict:
        raise ValueError('Expected an Xcode test-run object')
    if 'TestConfigurations' in value:
        configs = value['TestConfigurations']
        if type(configs) is not list or len(configs) != 1 or type(configs[0]) is not dict:
            raise ValueError('Expected one explicit test configuration')
        targets = configs[0].get('TestTargets')
        if type(targets) is not list or any(type(t) is not dict for t in targets):
            raise ValueError('Expected explicit test targets')
        pairs = [(t.get('BlueprintName') or Path(t.get('TestBundlePath', '')).stem, t) for t in targets]
    else:
        pairs = [(name, target) for name, target in value.items() if not name.startswith('__')]
    if any(type(name) is not str or type(target) is not dict for name, target in pairs) or sorted(name for name, _ in pairs) != sorted((UNIT, UI)):
        raise ValueError('Native and UI target identities must be exact and distinct')
    unit = next(target for name, target in pairs if name == UNIT)
    ui = next(target for name, target in pairs if name == UI)
    for target in (unit, ui):
        env = target.get('EnvironmentVariables', {})
        if type(env) is not dict or FLAG in env:
            raise ValueError('The original test environment must not contain a model-host override')
    # Do not modify the UI entry, target selection, test identifiers, signing,
    # entitlement or launch options; all behavioral assertions still run.
    unit['EnvironmentVariables'] = {**unit.get('EnvironmentVariables', {}), FLAG: '1'}
    expected = copy.deepcopy(value)
    expected_unit = (expected['TestConfigurations'][0]['TestTargets'][pairs.index((UNIT, unit))]
                     if 'TestConfigurations' in expected else expected[UNIT])
    expected_unit['EnvironmentVariables'].pop(FLAG)
    original_unit = (original['TestConfigurations'][0]['TestTargets'][pairs.index((UNIT, unit))]
                     if 'TestConfigurations' in original else original[UNIT])
    if 'EnvironmentVariables' not in original_unit:
        del expected_unit['EnvironmentVariables']
    if expected != original:
        raise ValueError('Only the native model-host flag may change')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('proof', type=Path)
    args = parser.parse_args()
    if args.source.resolve() in (args.output.resolve(), args.proof.resolve()) or args.output.resolve() == args.proof.resolve():
        raise ValueError('Input, isolated run and proof must have distinct paths')
    raw = args.source.read_bytes()
    if len(raw) > 4_194_304:
        raise ValueError('Unexpected test-run metadata size')
    result = isolate(plistlib.loads(raw))
    args.output.write_bytes(plistlib.dumps(result, fmt=plistlib.FMT_BINARY))
    assert args.source.read_bytes() == raw
    args.proof.write_text(json.dumps(dict(native_target=UNIT, ui_target=UI,
        only_native_environment_changed=True, original_run_file_unchanged=True,
        all_tests_retained=True)) + '\n')
