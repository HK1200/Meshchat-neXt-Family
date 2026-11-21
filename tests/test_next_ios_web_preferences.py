"""Execute the browser storage adapter without devices or network traffic."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_browser_preference_bridge_orders_writes_and_preserves_acknowledged_state():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the browser adapter test")
    script = Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe/App/next-web-preferences.js"
    subprocess.run([node, "-", str(script)], input=r'''
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
function environment(origin = 'http://127.0.0.1:12345') {
    const calls = [], events = [], pending = [];
    const context = vm.createContext({calls, events, pending});
    vm.runInContext(`
        class Storage {
            constructor() { this.values = new Map(); }
            getItem(k) { return this.values.has(String(k)) ? this.values.get(String(k)) : null; }
            setItem(k,v) { this.values.set(String(k), String(v)); }
            removeItem(k) { this.values.delete(String(k)); }
            clear() { this.values.clear(); }
        }
        this.Storage = Storage;
        this.StorageEvent = class { constructor(name, values) { Object.assign(this, values); } };
        this.window = this;
        this.localStorage = new Storage();
        this.sessionStorage = new Storage();
        this.dispatchEvent = e => events.push(e);
        this.webkit = {messageHandlers: {nextPreferences: {postMessage: value => {
            calls.push(value);
            return new Promise((resolve,reject) => pending.push({resolve,reject}));
        }}}};
    `, context);
    context.location = {origin};
    vm.runInContext(`(${source})(${JSON.stringify({origin:'http://127.0.0.1:12345',keys:['saved'],values:{saved:'original'}})})`, context);
    return {context, calls, events, pending, run: s => vm.runInContext(s,context)};
}
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
    const e = environment();
    assert.equal(e.run("localStorage.getItem('saved')"), 'original');
    e.run("localStorage.setItem('secret','never bridged'); sessionStorage.setItem('saved','session only')");
    await tick(); assert.equal(e.calls.length,0);
    e.run("localStorage.setItem('saved','first'); localStorage.setItem('saved','second')");
    await tick(); assert.equal(e.calls.length,1);
    e.pending.shift().resolve(true); await tick(); assert.equal(e.calls.length,2);
    e.pending.shift().reject(new Error('disk error')); await tick();
    assert.equal(e.run("localStorage.getItem('saved')"),'first');
    e.run("localStorage.setItem('saved','bad1'); localStorage.setItem('saved','bad2')");
    await tick(); e.pending.shift().reject(new Error()); await tick();
    e.pending.shift().reject(new Error()); await tick();
    assert.equal(e.run("localStorage.getItem('saved')"),'first');
    e.run("localStorage.clear()"); await tick(); e.pending.shift().reject(new Error()); await tick();
    assert.equal(e.run("localStorage.getItem('saved')"),'first');
    e.run("localStorage.removeItem('saved')"); await tick(); e.pending.shift().resolve(true); await tick();
    assert.equal(e.run("localStorage.getItem('saved')"),null);
    const external = environment('http://127.0.0.1:54321');
    external.run("localStorage.setItem('saved','external')"); await tick();
    assert.equal(external.calls.length,0);
    assert.ok(e.events.length >= 3);
    console.log('Browser persistence, ordering, rollback and origin isolation passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
''', text=True, check=True, timeout=20)
