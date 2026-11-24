"""Execute production boot scripts and ensure private error contents never escape."""
import json
from pathlib import Path
import re
import subprocess


def test_boot_diagnostics_are_bounded_and_omit_private_event_and_dom_data(tmp_path):
    source = (Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe/App/NextWebLoadState.swift').read_text()
    def script(name):
        return re.search(r'static let ' + name + r' = """\n(.*?)\n        """', source, re.S)[1]
    test = tmp_path / 'boot-diagnostics.cjs'
    test.write_text('''const vm=require('node:vm'),assert=require('node:assert/strict');
let errorHandler;
const context=vm.createContext({document:{readyState:'complete',getElementById:()=>({childElementCount:3,textContent:'private chat'})},
addEventListener:(type,fn)=>{assert.equal(type,'error');errorHandler=fn}});
vm.runInContext(''' + json.dumps(script('diagnosticsInstallScript')) + ''',context);
const global=vm.runInContext('globalThis',context);
for(let i=0;i<120;i++){
 errorHandler({target:{src:'https://private.invalid/?token=private-token'},message:'private chat'});
 errorHandler({target:global,error:{name:'TypeError',message:'private chat',stack:'private stack'},filename:'private file'});
}
const snapshot=()=>vm.runInContext('(function(){'+''' + json.dumps(script('diagnosticsSnapshotScript')) + '''+'})()',context);
let raw=snapshot();let value=JSON.parse(raw);
assert.deepEqual(value,{ready:'complete',appChildren:3,resources:99,errors:Array(4).fill('TypeError')});
assert.equal(raw.includes('private'),false);
vm.runInContext("globalThis.__nextBootDiagnostics={resources:'private token',errors:['private chat','RangeError']}",context);
raw=snapshot();value=JSON.parse(raw);
assert.equal(value.resources,0);assert.deepEqual(value.errors,['RangeError']);assert.equal(raw.includes('private'),false);
console.log('Bounded boot diagnostics retained no private error, URL, stack or DOM contents');
''')
    result = subprocess.run(['node', str(test)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
