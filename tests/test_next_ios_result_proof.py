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


def phase_fixtures(tmp_path):
    summary,tree=fixtures(tmp_path)
    one=dict(summary,totalTestCount=1,passedTests=1)
    native={'testNodes':[tree['testNodes'][0]]}
    ui={'testNodes':[tree['testNodes'][1]]}
    return one,native,dict(one),ui


def test_separate_phases_require_each_real_source_case(tmp_path):
    native,ntree,ui,utree=phase_fixtures(tmp_path)
    summary,tree,result=proof.combine_phases(native,ntree,ui,utree,tmp_path)
    assert result['source_cases_verified']==2 and result['messages_ui_verified']
    assert result['separate_phases_verified']['native']['source_cases_verified']==1
    assert result['separate_phases_verified']['ui']['messages_ui_verified']
    assert proof.verify(summary,tree,tmp_path)['passed_test_count']==2
    with pytest.raises(ValueError,match='lack passing'):
        proof.combine_phases(native,ntree,ui,{},tmp_path)
    with pytest.raises(ValueError,match='lack passing'):
        proof.combine_phases(native,{},ui,utree,tmp_path)


@pytest.mark.parametrize('phase', ['native','ui'])
@pytest.mark.parametrize('field,value',[('failedTests',1),('skippedTests',1),('result','Failed'),('passedTests',0)])
def test_combined_proof_cannot_hide_a_failed_or_skipped_phase(tmp_path,phase,field,value):
    native,ntree,ui,utree=phase_fixtures(tmp_path)
    (native if phase=='native' else ui)[field]=value
    with pytest.raises(ValueError,match='summary'):
        proof.combine_phases(native,ntree,ui,utree,tmp_path)


def test_phase_cli_retains_real_inputs_and_emits_strict_aggregate(tmp_path):
    import json,subprocess,sys
    native,ntree,ui,utree=phase_fixtures(tmp_path)
    paths=[]
    for name,value in [('native-summary',native),('native-tree',ntree),('ui-summary',ui),('ui-tree',utree)]:
        path=tmp_path/(name+'.json');path.write_text(json.dumps(value));paths.append(path)
    prefix=tmp_path/'combined'
    command=[sys.executable,str(Path(proof.__file__)),str(paths[0]),str(paths[1]),str(tmp_path),
             '--ui-summary',str(paths[2]),'--ui-tree',str(paths[3]),'--write-prefix',str(prefix)]
    result=subprocess.run(command,text=True,capture_output=True,check=True)
    assert json.loads(result.stdout)['messages_ui_verified']
    summary=json.loads(Path(str(prefix)+'-summary.json').read_text())
    tree=json.loads(Path(str(prefix)+'-tests.json').read_text())
    assert proof.verify(summary,tree,tmp_path)['source_cases_verified']==2
    ui['skippedTests']=1;paths[2].write_text(json.dumps(ui))
    rejected_prefix=tmp_path/'rejected'
    command[-1]=str(rejected_prefix)
    rejected=subprocess.run(command,text=True,capture_output=True)
    assert rejected.returncode!=0
    assert not Path(str(rejected_prefix)+'-summary.json').exists()
