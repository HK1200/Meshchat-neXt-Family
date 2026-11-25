"""Exercise exact-case proof and early stop without a simulator or network."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ui_cases', HERE/'run-ui-cases.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
spec = importlib.util.spec_from_file_location('case_proof', HERE/'verify-test-results.py')
v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)


def summary(**overrides):
    value = dict(totalTestCount=1, passedTests=1, failedTests=0, skippedTests=0, result='Passed')
    value.update(overrides); return value


def tree(name):
    return {'children': [{'result': 'Passed', 'nodeIdentifier': 'ProbeUITests/'+name+'()'}]}


class UICaseRunnerTests(unittest.TestCase):
    def test_every_source_case_runs_once_and_combined_proof_remains_strict(self):
        with tempfile.TemporaryDirectory(dir=HERE) as d:
            root=Path(d); source=root/'ProbeUITests.swift'
            source.write_text('class ProbeUITests: XCTestCase { func testB() {} func testA() {} }')
            commands=[]
            def run(args, **kwargs):
                commands.append(args); return SimpleNamespace(returncode=0)
            def read(args):
                name='testA' if 'testA' in args[-1] else 'testB'
                return json.dumps(summary() if 'summary' in args else tree(name)).encode()
            prefix=root/'ui'
            self.assertEqual(m.run_cases(source, root/'test.xctestrun', 'disposable', prefix, run=run, read=read),0)
            self.assertEqual([next(a for a in c if a.startswith('-only-testing:')) for c in commands],
                             ['-only-testing:NextRuntimeProbeUITests/ProbeUITests/testA','-only-testing:NextRuntimeProbeUITests/ProbeUITests/testB'])
            for c in commands:
                self.assertEqual(c[c.index('-xctestrun')+1], str(root/'test.xctestrun'))
                self.assertEqual(c[c.index('-destination')+1], 'disposable')
                self.assertEqual(c[c.index('-maximum-test-execution-time-allowance')+1],'900')
                self.assertEqual(c[c.index('-parallel-testing-enabled')+1],'NO')
            combined=json.loads(Path(str(prefix)+'-summary.json').read_text())
            results=json.loads(Path(str(prefix)+'-tests.json').read_text())
            self.assertEqual(v.verify(combined, results, root, ui_only=True)['source_cases_verified'],2)
            self.assertFalse(Path(str(prefix)+'-failed-path.txt').exists())

    def test_first_failure_stops_remaining_cases_and_retains_exact_bundle(self):
        with tempfile.TemporaryDirectory(dir=HERE) as d:
            root=Path(d); source=root/'ProbeUITests.swift'
            source.write_text('func testA() {} func testB() {}')
            calls=[]
            def fail(args, **kwargs):calls.append(args); return SimpleNamespace(returncode=65)
            def forbidden(args):raise AssertionError('Failed execution must not produce a passing proof')
            prefix=root/'ui'
            self.assertEqual(m.run_cases(source,root/'test.xctestrun','disposable',prefix,run=fail,read=forbidden),65)
            self.assertEqual(len(calls),1)
            self.assertIn('testA.xcresult',Path(str(prefix)+'-failed-path.txt').read_text())
            self.assertFalse(Path(str(prefix)+'-summary.json').exists())

    def test_reject_wrong_case_skips_failures_and_invalid_counts(self):
        for bad in [summary(skippedTests=1),summary(failedTests=1),summary(totalTestCount=2,passedTests=2),summary(totalTestCount=True),summary(result='Failed')]:
            with self.subTest(summary=bad),self.assertRaises(ValueError):m.passed_case(bad,tree('testA'),'testA',['testA','testB'])
        with self.assertRaises(ValueError):m.passed_case(summary(),tree('testB'),'testA',['testA','testB'])
        with self.assertRaises(ValueError):m.passed_case(summary(),{},'testA',['testA'])

    def test_actual_ui_inventory_and_duplicate_source_rejection(self):
        names=m.case_names(HERE/'Tests/ProbeUITests.swift')
        self.assertEqual(len(names),12)
        self.assertIn('testConversationSendsAndReceivesSignedLXMF',names)
        with tempfile.TemporaryDirectory(dir=HERE) as d:
            source=Path(d)/'ProbeUITests.swift';source.write_text('func testA() {} func testA() {}')
            with self.assertRaises(ValueError):m.case_names(source)


if __name__=='__main__':unittest.main()
