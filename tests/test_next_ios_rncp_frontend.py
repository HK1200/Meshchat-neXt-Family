"""Run the actual released RNCP controls after their bounded iOS adaptation."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rncp_frontend', ROOT / 'ios/NextRuntimeProbe/rncp_frontend.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
FIXTURE = ROOT / 'tests/fixtures/next-026-rncp-methods.js.txt'


def execute(tmp_path, body, *, patched=True):
    source = FIXTURE.read_text()
    if patched: source = module.rewrite(source)
    script = tmp_path / 'rncp-controls.cjs'
    script.write_text("const assert=require('node:assert/strict');const alerts=[];const s={alert:async value=>alerts.push(value)};const o=value=>'/api/v1'+value;const methods=" + source + '\n(async()=>{' + body + "\nconsole.log('RNCP controls completed');})().catch(e=>{console.error(e);process.exitCode=1;});")
    result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'RNCP controls completed' in result.stdout


def test_selected_file_is_imported_with_actual_bytes_and_cancel_keeps_selection(tmp_path):
    execute(tmp_path, '''
const file=new File([Buffer.from('chosen bytes')],'chosen.bin');
const state={sendFilePath:'previous',sendInProgress:false};
let posted=0;
global.window={api:{post:async(path,form,options)=>{
 assert.equal(path,'/api/v1/preview/rncp/upload');assert.equal(await form.get('file').text(),'chosen bytes');
 assert.equal(form.get('file').name,'chosen.bin');assert.equal(options.headers['Content-Type'],undefined);assert.equal(options.timeout,0);
 assert.equal(state.sendInProgress,true);posted++;return{data:{file_path:'selected/path/chosen.bin'}};
}}};
const event={target:{files:[file],value:'chosen'}};
await methods.onWebSendFilePicked.call(state,event);
assert.equal(posted,1);assert.equal(state.sendFilePath,'selected/path/chosen.bin');assert.equal(state.sendInProgress,false);assert.equal(event.target.value,'');
await methods.onWebSendFilePicked.call(state,{target:{files:[],value:''}});
assert.equal(posted,1);assert.equal(state.sendFilePath,'selected/path/chosen.bin');assert.deepEqual(alerts,[]);
''')


def test_import_failure_is_visible_and_never_sends_the_previous_file(tmp_path):
    execute(tmp_path, '''
global.window={api:{post:async()=>{throw{response:{data:{message:'No storage available'}}}}}};
const state={sendFilePath:'previous',sendInProgress:false};
await methods.onWebSendFilePicked.call(state,{target:{files:[new File(['data'],'a.bin')],value:'chosen'}});
assert.equal(state.sendFilePath,'');assert.equal(state.sendInProgress,false);assert.deepEqual(alerts,['No storage available']);
''')


def test_received_names_are_text_and_only_exact_local_download_routes_are_created(tmp_path):
    execute(tmp_path, '''
const nodes=[];
class Element{
 constructor(tag){this.tag=tag;this.style={};this.children=[];this.events={};nodes.push(this)}
 set innerHTML(value){throw Error('Unsafe markup parsing')}
 setAttribute(key,value){this[key]=value} append(...items){this.children.push(...items)}
 addEventListener(name,fn){this.events[name]=fn} focus(){this.focused=true} remove(){this.removed=true}
}
const previous={focus(){this.focused=true}};
global.document={activeElement:previous,body:new Element('body'),getElementById:()=>null,createElement:tag=>new Element(tag)};
global.window={api:{get:async path=>{assert.equal(path,'/api/v1/preview/rncp/files');return{data:{files:[
 {id:'a'.repeat(32),name:'<img src=x onerror=alert(1)>',size:7},{id:'../private',name:'must not appear'}]}}}}};
await methods.openReceiveDirectory.call({});
const links=nodes.filter(n=>n.tag==='a');assert.equal(links.length,1);
assert.equal(links[0].textContent,'<img src=x onerror=alert(1)>');
assert.equal(links[0].href,'/api/v1/preview/rncp/files/'+'a'.repeat(32)+'/download');
assert.equal(nodes.filter(n=>n.tag==='img').length,0);
const button=nodes.find(n=>n.tag==='button');assert.equal(button.focused,true);button.events.click();
assert.equal(nodes.find(n=>n.id==='next-rncp-files').removed,true);assert.equal(previous.focused,true);
''')


def test_unmodified_browser_handler_cannot_pass_the_native_import_assertion(tmp_path):
    with pytest.raises(AssertionError):
        execute(tmp_path, '''
let posted=0;global.window={api:{post:async()=>{posted++;return{data:{file_path:'chosen'}}}}};
const state={sendFilePath:'previous',$t:value=>value};
await methods.onWebSendFilePicked.call(state,{target:{files:[new File(['data'],'a.bin')],value:'chosen'}});
assert.equal(posted,1);
''', patched=False)


def test_changed_or_duplicate_frontend_controls_are_rejected(tmp_path):
    source = FIXTURE.read_text()
    for text in ('changed', source + source):
        with pytest.raises(ValueError): module.rewrite(text)
    path = tmp_path / module.CHUNK; path.parent.mkdir(parents=True); path.write_text(source)
    with pytest.raises(ValueError): module.stage(tmp_path)
    assert path.read_text() == source


def test_real_file_operations_leave_healthy_transfer_timeouts_to_the_protocol(tmp_path):
    execute(tmp_path, '''
const calls=[];
global.window={api:{post:async(path,body,options)=>{
 calls.push({path,body,options});return {data:{transfer_id:'a'.repeat(64),file_path:'private/fixture.bin'}};
}}};
const state={sendDestinationHash:'a'.repeat(32),sendFilePath:'private/input.bin',sendTimeout:30,sendNoCompress:false,
 fetchDestinationHash:'a'.repeat(32),fetchFilePath:'fixture.bin',fetchTimeout:30,fetchSavePath:null,fetchAllowOverwrite:false,
 $t:value=>value,notifyRncp:()=>{}};
await methods.sendFile.call(state);await methods.fetchFile.call(state);
assert.equal(calls.length,2);assert.equal(calls[0].path,'/api/v1/rncp/send');assert.equal(calls[1].path,'/api/v1/rncp/fetch');
for(const call of calls){assert.equal(call.options.timeout,0);assert.equal(call.body.timeout,30)}
assert.equal(state.sendResult.success,true);assert.equal(state.fetchResult.success,true);
assert.equal(state.sendInProgress,false);assert.equal(state.fetchInProgress,false);
''')


def test_upstream_transfer_lifetime_guards_must_remain_present():
    source = FIXTURE.read_text()
    for marker in (module.SEND_AFTER, module.FETCH_AFTER):
        assert source.count(marker) == 1
        with pytest.raises(ValueError, match="transfer-lifetime protection"):
            module.rewrite(source.replace(marker, marker.replace("timeout:0", "timeout:120000")))


@pytest.mark.parametrize('conflict',[False,True])
def test_received_file_removal_needs_confirmation_and_keeps_a_failed_row(tmp_path,conflict):
    execute(tmp_path, '''
const nodes=[];
class Element{
 constructor(tag){this.tag=tag;this.style={};this.children=[];this.events={};nodes.push(this)}
 set innerHTML(value){throw Error('Unsafe markup parsing')}
 setAttribute(key,value){this[key]=value} append(...items){this.children.push(...items)}
 addEventListener(name,fn){this.events[name]=fn} focus(){this.focused=true} remove(){this.removed=true}
}
global.document={activeElement:null,body:new Element('body'),getElementById:()=>null,createElement:tag=>new Element(tag)};
let deleted=0;const conflict=CONFLICT;
global.window={api:{get:async()=>({data:{files:[{id:'a'.repeat(32),name:'chosen.bin',size:7}]}}),delete:async path=>{
 assert.equal(path,'/api/v1/preview/rncp/files/'+'a'.repeat(32));deleted++;
 if(conflict)throw{response:{data:{message:'File in use'}}};return{status:204};
}}};
await methods.openReceiveDirectory.call({});
const remove=nodes.find(n=>n.textContent==='Remove');remove.events.click();
assert.equal(deleted,0);
nodes.find(n=>n.textContent==='Keep file').events.click();assert.equal(deleted,0);assert.equal(remove.disabled,false);
remove.events.click();
const confirm=nodes.filter(n=>n.textContent==='Remove file').at(-1);await confirm.events.click();
assert.equal(deleted,1);
const row=nodes.find(n=>n.children.includes(remove));
if(conflict){assert.notEqual(row.removed,true);assert.equal(confirm.disabled,false);assert(nodes.some(n=>n.textContent==='File in use'))}
else{assert.equal(row.removed,true);assert(nodes.some(n=>n.textContent==='File removed.'))}
'''.replace('CONFLICT','true' if conflict else 'false'))
