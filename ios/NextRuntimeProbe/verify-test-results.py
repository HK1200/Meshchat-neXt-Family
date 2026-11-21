"""Require actual passed XCTest cases, not merely a successful build/job exit."""
import argparse
import json
from pathlib import Path
import re


def verify(summary, tree, sources, *, unit_only=False):
    expected = set()
    for source in sources.glob('*.swift'):
        if unit_only and source.name == 'ProbeUITests.swift':
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('summary', type=Path)
    parser.add_argument('tree', type=Path)
    parser.add_argument('sources', type=Path)
    parser.add_argument('--unit-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.summary.read_text()), json.loads(args.tree.read_text()),
                            args.sources, unit_only=args.unit_only), sort_keys=True))
