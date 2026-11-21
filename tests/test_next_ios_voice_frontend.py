"""Execute the actual released call handlers across a permission/identity race."""
from pathlib import Path
import subprocess
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe'))
import voice_frontend
ROOT=Path(__file__).resolve().parent


@pytest.mark.parametrize('page',[False,True])
def test_answer_keeps_the_displayed_call_id_across_the_real_async_permission_handler(page,tmp_path):
    source=(ROOT/'fixtures'/('next-021-voice-'+('page' if page else 'bar')+'.js.txt')).read_text()
    rewritten=voice_frontend.rewrite(source,page=page)
    script=tmp_path/'handler.js'
    script.write_text('''const assert=require('node:assert/strict');
let release,ready;const permission=new Promise(resolve=>release=resolve);const permissionReady=new Promise(resolve=>ready=resolve);const posts=[];
const window={api:{post:async(path,body)=>{posts.push({path,body});return {data:{}}}}};
const qe=x=>x,R=x=>x,g=()=>{ready();return permission};
const xe={error:message=>{throw Error(message)}},k=xe;
const controls='''+rewritten+''';
const context={activeCall:{call_id:'original-call',hash:'original-link',status:4,is_incoming:true},
 webAudioBridgeEnabled:true,requestAudioPermission:g,
 getStatus:async function(){return this.activeCall},
 $route:{name:'call',query:{tab:'phone'}},$router:{push:async()=>{}},$t:x=>x};
(async()=>{
 const pending=controls.answerCall.call(context);
 await permissionReady;context.activeCall={call_id:'replacement-call',hash:'replacement-link',status:4,is_incoming:true};
 release();await pending;
 assert.equal(posts.length,1);assert.equal(posts[0].path,'/telephone/answer');
 assert.equal(posts[0].body?.call_id,'original-call');
})().catch(error=>{console.error(error);process.exitCode=1});
''')
    subprocess.run(['node',str(script)],check=True,timeout=15)


@pytest.mark.parametrize('page',[False,True])
def test_handler_boundary_changes_fail_closed(page):
    source=(ROOT/'fixtures'/('next-021-voice-'+('page' if page else 'bar')+'.js.txt')).read_text()
    with pytest.raises(ValueError):voice_frontend.rewrite(source.replace('async answerCall(){','async changedAnswer(){'),page=page)


def test_bad_bundle_is_not_overwritten(tmp_path):
    for name in voice_frontend.CHUNKS:
        p=tmp_path/'assets'/name;p.parent.mkdir(exist_ok=True);p.write_text('not verified source')
    before={p.name:p.read_bytes() for p in (tmp_path/'assets').iterdir()}
    with pytest.raises(ValueError,match='checksum'):voice_frontend.stage(tmp_path)
    assert before=={p.name:p.read_bytes() for p in (tmp_path/'assets').iterdir()}
