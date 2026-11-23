"""Never equate a paired test-driver exit with successful physical behavior."""
import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('device_results',Path(__file__).resolve().parents[1]/'ios/DeviceChecks/verify-result.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
CASES=['testReady','testReadOnlyMenu']
LOG='\n'.join(f'[case] finish PreviewChecks/{name} status=passed dur=1s' for name in CASES)+'\n[suite] finish PreviewChecks at=date run=2 fail=0 une=0 skip=0 exp_fail=0 unc=0\n[plan] finish\n'
CONTROL='INFO [IDE] didFinishExecutingTestPlan\n'


def test_requires_real_case_and_suite_results_not_only_cli_success():
    assert module.verify(LOG,CONTROL,CASES,0)['source_cases_verified']==2


@pytest.mark.parametrize('change',['missing','failed','duplicate','extra','skipped','expected_failure','uncaught','unexpected','missing_unexpected','duplicate_count','no_listener_finish','no_suite','transport','no_plan'])
def test_rejects_partial_failed_or_nonbehavioral_results(change):
    text=LOG;control=CONTROL;code=0
    if change=='missing':text=text.replace('[case] finish PreviewChecks/testReady status=passed dur=1s\n','')
    elif change=='failed':text=text.replace('status=passed','status=failed',1)
    elif change=='duplicate':text+='[case] finish PreviewChecks/testReady status=passed\n'
    elif change=='extra':text+='[case] finish PreviewChecks/testUnexpected status=passed\n'
    elif change=='skipped':text=text.replace('skip=0','skip=1')
    elif change=='expected_failure':text=text.replace('exp_fail=0','exp_fail=1')
    elif change=='uncaught':text=text.replace('unc=0','unc=1')
    elif change=='unexpected':text=text.replace('une=0','une=1')
    elif change=='missing_unexpected':text=text.replace('une=0 ','')
    elif change=='duplicate_count':text=text.replace('fail=0','fail=1 fail=0',1)
    elif change=='no_listener_finish':text=text.replace('[plan] finish','')
    elif change=='no_suite':text=text.split('[suite]')[0]
    elif change=='transport':code=1
    elif change=='no_plan':control=''
    with pytest.raises(ValueError):module.verify(text,control,CASES,code)
