"""Require actual passing device cases; pymobiledevice3 exit zero is insufficient."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def verify(text, control, expected, exit_code):
    if exit_code != 0 or not expected or len(expected) != len(set(expected)):
        raise ValueError('Device test transport or source inventory is incomplete')
    cases = re.findall(r'^\[case\]\s+finish\s+PreviewChecks/(test\w+)\s+status=(\w+)\b', text, re.M)
    if Counter(name for name, _ in cases) != Counter(expected) or any(status != 'passed' for _, status in cases):
        raise ValueError('Every expected device case must have exactly one actual passed result')
    suites = re.findall(r'^\[suite\]\s+finish\s+PreviewChecks\s+(.+)$', text, re.M)
    if len(suites) != 1:
        raise ValueError('A single completed device suite is required')
    fields = re.findall(r'\b(run|fail|une|skip|exp_fail|unc)=(\d+)\b', suites[0])
    counts = {key: int(value) for key, value in fields}
    if len(fields) != 6 or counts != dict(run=len(expected), fail=0, une=0, skip=0, exp_fail=0, unc=0):
        raise ValueError('The completed device suite must contain no missing, skipped or failed cases')
    if not re.search(r'^\[plan\] finish\s*$', text, re.M) or not re.search(r'\[IDE\]\s+didFinishExecutingTestPlan\b', control):
        raise ValueError('The paired test service did not confirm plan completion')
    return dict(passed=True, source_cases_verified=len(expected), passed_test_count=len(cases),
                actual_device_results=True, regular_family_targeted=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('control_log', type=Path)
    parser.add_argument('--exit-code', type=int, required=True)
    args = parser.parse_args()
    source = Path(__file__).parent/'Tests/PreviewChecks.swift'
    expected = re.findall(r'\bfunc\s+(test\w+)\s*\(', source.read_text())
    print(json.dumps(verify(args.log.read_text(), args.control_log.read_text(), expected, args.exit_code)))
