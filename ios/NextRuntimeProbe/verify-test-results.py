"""Require actual passed XCTest cases, not merely a successful build/job exit."""
import argparse
import json
from pathlib import Path
import re


def verify(summary, tree, sources, *, unit_only=False, ui_only=False):
    if unit_only and ui_only: raise ValueError("Choose one test phase")
    expected = set()
    for source in sources.glob('*.swift'):
        if unit_only and source.name == 'ProbeUITests.swift':
            continue
        if ui_only and source.name != 'ProbeUITests.swift':
            continue
        expected.update(re.findall(r'\bfunc\s+(test\w+)\s*\(', source.read_text()))
    if not expected:
        raise ValueError('No source test cases found')
    total, passed = summary.get('totalTestCount'), summary.get('passedTests')
    if (type(total) is not int or type(passed) is not int or total < len(expected)
            or passed != total or summary.get('failedTests') != 0
            or summary.get('skippedTests') != 0 or summary.get('result') != 'Passed'):
        raise ValueError('XCTest summary is missing, incomplete or unsuccessful')
    observed = set()
    def walk(value):
        if isinstance(value, dict):
            if value.get('result') == 'Passed':
                for field in ('name', 'nodeIdentifier', 'testIdentifier', 'testIdentifierURL'):
                    label = value.get(field)
                    if isinstance(label, str):
                        for name in expected:
                            if re.search(r'(?:^|[/ .])' + re.escape(name) + r'(?:\(|$)', label):
                                observed.add(name)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(tree)
    missing = expected - observed
    if missing:
        raise ValueError('XCTest cases lack passing result records: ' + ', '.join(sorted(missing)))
    return {'source_cases_verified': len(expected), 'passed_test_count': passed,
            'messages_ui_verified': 'testConversationSendsAndReceivesSignedLXMF' in observed}


def combine_phases(unit_summary, unit_tree, ui_summary, ui_tree, sources):
    unit = verify(unit_summary, unit_tree, sources, unit_only=True)
    ui = verify(ui_summary, ui_tree, sources, ui_only=True)
    total = unit_summary['totalTestCount'] + ui_summary['totalTestCount']
    summary = dict(totalTestCount=total, passedTests=total, failedTests=0,
                   skippedTests=0, result='Passed')
    tree = {'native_phase': unit_tree, 'ui_phase': ui_tree}
    result = verify(summary, tree, sources)
    result['separate_phases_verified'] = {'native': unit, 'ui': ui}
    return summary, tree, result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('summary', type=Path)
    parser.add_argument('tree', type=Path)
    parser.add_argument('sources', type=Path)
    parser.add_argument('--unit-only', action='store_true')
    parser.add_argument('--ui-summary', type=Path)
    parser.add_argument('--ui-tree', type=Path)
    parser.add_argument('--write-prefix', type=Path)
    args = parser.parse_args()
    summary, tree = json.loads(args.summary.read_text()), json.loads(args.tree.read_text())
    if args.ui_summary or args.ui_tree or args.write_prefix:
        if not args.ui_summary or not args.ui_tree or args.unit_only:
            parser.error('Combining phases requires both UI files and cannot use --unit-only')
        summary, tree, result = combine_phases(summary, tree,
            json.loads(args.ui_summary.read_text()), json.loads(args.ui_tree.read_text()), args.sources)
        if args.write_prefix:
            Path(str(args.write_prefix)+'-summary.json').write_text(json.dumps(summary)+'\n')
            Path(str(args.write_prefix)+'-tests.json').write_text(json.dumps(tree)+'\n')
    else: result = verify(summary, tree, args.sources, unit_only=args.unit_only)
    print(json.dumps(result, sort_keys=True))
