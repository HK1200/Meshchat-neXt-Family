import test from "node:test";
import assert from "node:assert/strict";
import {createNativeLocationClient} from "./native-location-client.mjs";
const key = `reticulum:${"1".repeat(32)}:${"2".repeat(32)}`;
const nonce = "a".repeat(32);
const flush = async () => { for (let i=0;i<4;i++) await new Promise(setImmediate); };
function fixture() {
    const f = {sessions:new Map(), calls:[], reports:[], time:1000000, hidden:false,
        state:{consent_epoch:0,active:false,sessions:[]}, failStop:false};
    f.request=async (method,body) => {
        f.calls.push({method,body:structuredClone(body)});
        if (method==="GET") {
            if (f.holdGet) {const hold=f.holdGet;f.holdGet=null;return hold;}
            return structuredClone(f.state);
        }
        if (body.action==="start") {
            assert.equal(body.consent_epoch,f.state.consent_epoch);
            f.state={consent_epoch:f.state.consent_epoch+1,active:true,sessions:[{
                target:key,name:"One",request_id:body.request_id,until:body.deadline,background:body.background,
            }]};
        } else {
            assert.equal(body.action,"stop");
            if (f.pauseStop) await f.pauseStop;
            if(f.failStop)throw Error("private fixture offline");
            f.state.sessions=f.state.sessions.filter(r=>r.target!==body.target||r.request_id!==body.request_id);
            f.state.active=f.state.sessions.length>0;f.state.consent_epoch++;
        }
        return structuredClone(f.state);
    };
    f.client=createNativeLocationClient({sessions:f.sessions,request:f.request,
        report:(...value)=>f.reports.push(value),now:()=>f.time,identifier:()=>nonce,hidden:()=>f.hidden,
        subscribe:(callback)=>{f.visible=callback;return()=>{f.unsubscribed=true;};},
        every:(callback)=>{f.poll=callback;return()=>{f.timerCancelled=true;};}});
    f.options=()=>({firstFix:{time:f.time,latitude:48.75,longitude:-122.48},deadline:f.time+900000,isCurrent:()=>true});
    return f;
}
test("chat start delegates only consent and retains a real backend Stop",async()=>{
    const f=fixture();await flush();f.calls=[];f.state.background=true;
    assert(f.client.start(key,"One",f.options()));await flush();
    const sent=f.calls.find(c=>c.body?.action==="start").body;
    assert.deepEqual(sent,{action:"start",targets:[key],duration:"15",background:false,
        deadline:1900,request_id:nonce,consent_epoch:0});
    assert(!JSON.stringify(f.calls).includes("latitude"));
    assert(f.sessions.has(key));assert(await f.sessions.get(key).stop());
    assert(!f.sessions.has(key));assert.equal(f.state.sessions.length,0);assert.deepEqual(f.reports,[]);
    f.client.dispose();
});
test("Stop before a delayed initial read prevents the pending Start",async()=>{
    const f=fixture();await flush();f.calls=[];
    let release;f.holdGet=new Promise(resolve=>{release=resolve;});
    f.client.start(key,"One",f.options());
    assert(await f.sessions.get(key).stop());
    release({consent_epoch:0,active:false,sessions:[]});await flush();
    assert.deepEqual(f.calls.filter(c=>c.method==="POST").map(c=>c.body.action),["stop"]);
    assert(!f.sessions.has(key));f.client.dispose();
});
test("failed Stop stays visible and retryable until the server confirms it",async()=>{
    const f=fixture();await flush();let stopped=0;
    f.client.start(key,"One",{...f.options(),onStop:()=>stopped++});await flush();
    f.failStop=true;assert.equal(await f.sessions.get(key).stop(),false);
    assert(f.sessions.has(key));assert.equal(stopped,0);assert.equal(f.reports.length,1);
    f.failStop=false;assert(await f.sessions.get(key).stop());
    assert(!f.sessions.has(key));assert.equal(stopped,1);f.client.dispose();
});
test("visibility and page disposal do not stop native background sharing",async()=>{
    const f=fixture();await flush();f.client.start(key,"One",f.options());await flush();
    f.calls=[];f.hidden=true;f.visible();f.poll();await flush();
    assert(f.sessions.has(key));assert.equal(f.calls.length,0);
    f.client.dispose();assert(f.unsubscribed&&f.timerCancelled);
    assert.equal(f.calls.length,0);
});
test("native panel sessions restore into chat controls without changing their permission",async()=>{
    const f=fixture();await flush();
    f.state={consent_epoch:3,active:true,sessions:[{target:key,name:"Native",request_id:"b".repeat(32),until:1900,background:true}]};
    await f.client.sync();assert.equal(f.sessions.get(key).name,"Native");
    f.state.sessions[0].name="Renamed";await f.client.sync();assert.equal(f.sessions.get(key).name,"Renamed");
    assert(await f.sessions.get(key).stop());
    assert(!f.sessions.has(key));f.client.dispose();
});
test("manual and MeshCore timers are preserved and never delegated",async()=>{
    const f=fixture();await flush();
    let stopped=0;const meshKey=`meshcore:${"3".repeat(64)}:${"4".repeat(64)}`;
    const manual={firstFix:{latitude:48.75,longitude:-122.48},deadline:1900000};
    assert.equal(f.client.handles(key,manual),false);
    assert.equal(f.client.handles(meshKey,f.options()),false);
    f.sessions.set(meshKey,{name:"Other radio",stop:()=>stopped++});
    await f.client.sync();assert(f.sessions.has(meshKey));assert.equal(stopped,0);
    f.client.dispose();
});
test("a stale reply cannot bring back a session after confirmed Stop",async()=>{
    const f=fixture();await flush();f.client.start(key,"One",f.options());await flush();
    const stale=structuredClone(f.state);assert(await f.sessions.get(key).stop());
    f.holdGet=Promise.resolve(stale);await f.client.sync();
    assert(!f.sessions.has(key));f.client.dispose();
});
test("a throwing chat consent check stops its native session",async()=>{
    const f=fixture();await flush();let allowed=true;
    f.client.start(key,"One",{...f.options(),isCurrent:()=>{if(!allowed)throw Error("changed");return true;}});
    await flush();allowed=false;await f.client.sync();await flush();
    assert.equal(f.state.sessions.length,0);assert(!f.sessions.has(key));f.client.dispose();
});

test("a native-panel start race is adopted without downgrading its locked permission",async()=>{
    const f=fixture();await flush();f.calls=[];
    f.state={consent_epoch:2,active:true,sessions:[{target:key,name:"Native",request_id:"b".repeat(32),until:1900,background:true}]};
    f.client.start(key,"One",f.options());await flush();
    assert(f.sessions.has(key));assert.equal(f.sessions.get(key).name,"Native");
    assert.equal(f.calls.filter(c=>c.method==="POST").length,0);
    assert.equal(f.state.sessions[0].background,true);f.client.dispose();
});
test("the chat keeps its Stop control until backend acknowledgement",async()=>{
    const f=fixture();await flush();f.client.start(key,"One",f.options());await flush();
    let release;f.pauseStop=new Promise(resolve=>{release=resolve;});
    const stopping=f.sessions.get(key).stop();await flush();
    assert(f.sessions.has(key));release();assert(await stopping);
    assert(!f.sessions.has(key));f.client.dispose();
});
