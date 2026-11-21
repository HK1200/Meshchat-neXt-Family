"""Only a matching disposable iOS simulator can host the clean UI phase."""
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('next_fresh_simulator',Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe/fresh-simulator.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
TARGET='2A020491-3EBC-4783-8622-F8314CC00294'
RUNTIME='com.apple.CoreSimulator.SimRuntime.iOS-26-5'
TYPE='com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M4-8GB'


def inventory(**overrides):
    return {'devices':{RUNTIME:[dict(udid=TARGET,name='iPad Pro 13-inch',isAvailable=True,deviceTypeIdentifier=TYPE,**overrides)]}}


def test_uses_the_selected_runtime_and_type_without_copying_its_app_container():
    assert module.descriptor(inventory(),TARGET,'iPad')==(TYPE,RUNTIME)


@pytest.mark.parametrize('field,value',[('isAvailable',False),('deviceTypeIdentifier',''),('deviceTypeIdentifier','../../device'),('name','iPhone 17')])
def test_rejects_unavailable_or_mismatched_targets(field,value):
    value_inventory=inventory();value_inventory['devices'][RUNTIME][0][field]=value
    with pytest.raises(ValueError):module.descriptor(value_inventory,TARGET,'iPad')


def test_rejects_missing_duplicate_non_ios_and_old_runtime_targets():
    for value in ({'devices':{}}, {'devices':{RUNTIME:inventory()['devices'][RUNTIME]*2}},
                  {'devices':{'com.apple.CoreSimulator.SimRuntime.tvOS-26-0':inventory()['devices'][RUNTIME]}},
                  {'devices':{'com.apple.CoreSimulator.SimRuntime.iOS-16-0':inventory()['devices'][RUNTIME]}}):
        with pytest.raises(ValueError):module.descriptor(value,TARGET,'iPad')
    with pytest.raises(ValueError):module.descriptor(inventory(),TARGET,'Mac')
    with pytest.raises(ValueError):module.descriptor(inventory(),'not-a-simulator','iPad')
