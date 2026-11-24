"""Run every UI case serially and stop before a failed app poisons later cases."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def case_names(source):
    names = re.findall(r'\bfunc\s+(test\w+)\s*\(', source.read_text())
    if not names or len(set(names)) != len(names):
        raise ValueError('UI source must contain unique test cases')
    return sorted(names)


def passed_case(summary, tree, expected, all_names):
    if (any(type(summary.get(key)) is not int for key in
            ('totalTestCount', 'passedTests', 'failedTests', 'skippedTests'))
            or summary.get('totalTestCount') != 1 or summary.get('passedTests') != 1
            or summary.get('failedTests') != 0 or summary.get('skippedTests') != 0
            or summary.get('result') != 'Passed'):
        raise ValueError('The selected UI case did not pass exactly once')
    found = set()

    def walk(value):
        if isinstance(value, dict):
            if value.get('result') == 'Passed':
                for field in ('name', 'nodeIdentifier', 'testIdentifier', 'testIdentifierURL'):
                    label = value.get(field)
                    if isinstance(label, str):
                        found.update(name for name in all_names if re.search(
                            r'(?:^|[/ .])' + re.escape(name) + r'(?:\(|$)', label))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(tree)
    if found != {expected}:
        raise ValueError('The result does not prove the exact selected UI case')


def run_cases(source, test_run, destination, prefix, *, run=subprocess.run,
              read=subprocess.check_output):
    names = case_names(source)
    plan = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'cases': names, 'verified': []}
    plan_path = Path(str(prefix) + '-plan.json')
    plan_path.write_text(json.dumps(plan, indent=2) + '\n')
    trees = []
    for index, name in enumerate(names):
        result = Path(str(prefix) + f'-{index:02d}-{name}.xcresult')
        # Preserve the actual failed bundle for the existing diagnostic export.
        Path(str(prefix) + '-failed-path.txt').write_text(str(result) + '\n')
        command = ['xcodebuild', 'test-without-building', '-xctestrun', str(test_run),
                   '-only-testing:NextRuntimeProbeUITests/ProbeUITests/' + name,
                   '-destination', destination, '-resultBundlePath', str(result),
                   '-parallel-testing-enabled', 'NO', '-test-timeouts-enabled', 'YES',
                   '-default-test-execution-time-allowance', '600',
                   '-maximum-test-execution-time-allowance', '900']
        completed = run(command, check=False)
        if completed.returncode:
            return completed.returncode if completed.returncode > 0 else 1
        summary = json.loads(read(['xcrun', 'xcresulttool', 'get', 'test-results',
                                   'summary', '--path', str(result)]))
        tree = json.loads(read(['xcrun', 'xcresulttool', 'get', 'test-results',
                                'tests', '--path', str(result)]))
        Path(str(result) + '-summary.json').write_text(json.dumps(summary) + '\n')
        Path(str(result) + '-tests.json').write_text(json.dumps(tree) + '\n')
        passed_case(summary, tree, name, names)
        trees.append(tree)
        plan['verified'].append(name)
        plan_path.write_text(json.dumps(plan, indent=2) + '\n')
    assert plan['verified'] == names
    summary = dict(totalTestCount=len(names), passedTests=len(names), failedTests=0,
                   skippedTests=0, result='Passed')
    Path(str(prefix) + '-summary.json').write_text(json.dumps(summary) + '\n')
    Path(str(prefix) + '-tests.json').write_text(json.dumps({'cases': trees}) + '\n')
    Path(str(prefix) + '-failed-path.txt').unlink()
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--xctestrun', required=True, type=Path)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--prefix', required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(run_cases(args.source, args.xctestrun, args.destination, args.prefix))
