"""A green Xcode build or a missing XCTest run cannot pass native verification."""
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('next_result_proof',Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe/verify-test-results.py')
proof=importlib.util.module_from_spec(spec);spec.loader.exec_module(proof)


def fixtures(tmp_path):
    (tmp_path/'UnitTests.swift').write_text('func testPrivateAccess() {}')
    (tmp_path/'ProbeUITests.swift').write_text('func testConversationSendsAndReceivesSignedLXMF() {}')
    summary=dict(totalTestCount=2,passedTests=2,failedTests=0,skippedTests=0,result='Passed')
    tree={'testNodes':[{'name':'PrivateTests','children':[{'name':'testPrivateAccess()','result':'Passed'}]},
                       {'name':'testConversationSendsAndReceivesSignedLXMF()','result':'Passed'}]}
    return summary,tree


def test_requires_each_source_case_and_the_actual_ui_reply_test(tmp_path):
    summary,tree=fixtures(tmp_path)
    result=proof.verify(summary,tree,tmp_path)
    assert result['source_cases_verified']==2 and result['messages_ui_verified']
    tree['testNodes'].pop()
    with pytest.raises(ValueError,match='lack passing'):proof.verify(summary,tree,tmp_path)


@pytest.mark.parametrize('field,value',[('totalTestCount',0),('passedTests',0),('failedTests',1),('skippedTests',1),('result','Failed'),('totalTestCount',None)])
def test_missing_empty_failed_or_skipped_run_cannot_be_green(tmp_path,field,value):
    summary,tree=fixtures(tmp_path);summary[field]=value
    with pytest.raises(ValueError,match='summary'):proof.verify(summary,tree,tmp_path)


def test_unit_only_is_explicit_and_still_requires_nonempty_passing_records(tmp_path):
    summary,tree=fixtures(tmp_path)
    summary.update(totalTestCount=1,passedTests=1);tree['testNodes'].pop()
    result=proof.verify(summary,tree,tmp_path,unit_only=True)
    assert result['source_cases_verified']==1 and not result['messages_ui_verified']
    with pytest.raises(ValueError):proof.verify(summary,{},tmp_path,unit_only=True)
