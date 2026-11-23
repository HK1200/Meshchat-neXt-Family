// SPDX-License-Identifier: 0BSD
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createNativeArchiveExport } from './native-archive-export.mjs';

function fixture(base = 'http://127.0.0.1:44444/?not-shared=secret#/archives') {
    const events = [];
    const anchor = { click() { events.push(['click', this.href, this.download]); }, remove() { events.push(['remove']); } };
    return { base, events, document: { createElement(kind) { assert.equal(kind, 'a'); return anchor; }, body: { appendChild() { events.push(['append']); } } } };
}

test('native export retains only the chosen encoded filters and own origin', () => {
    const owner = fixture();
    const address = 'a1'.repeat(16);
    const result = createNativeArchiveExport({ q: 'PNW 雪 & roads', destination_hash: address }, owner);
    const url = new URL(result);
    assert.equal(url.origin, 'http://127.0.0.1:44444');
    assert.equal(url.pathname, '/api/v1/nomadnet/archives/export');
    assert.equal(url.searchParams.get('q'), 'PNW 雪 & roads');
    assert.equal(url.searchParams.get('destination_hash'), address);
    assert.equal(url.searchParams.has('not-shared'), false);
    assert.equal(url.hash, '');
    assert.deepEqual(owner.events.map(row => row[0]), ['append', 'click', 'remove']);
    assert.equal(owner.events[1][2], 'meshchatnext-archives.zip');
});

test('external origins, credentials and invalid filters never create a download', () => {
    for (const base of ['https://example.invalid/', 'http://127.0.0.1/', 'http://user:password@127.0.0.1:44444/']) {
        const owner = fixture(base);
        assert.throws(() => createNativeArchiveExport({}, owner));
        assert.deepEqual(owner.events, []);
    }
    for (const filters of [null, [], { target: 'https://example.invalid' }, { q: 'x'.repeat(257) }, { destination_hash: '../private' }]) {
        const owner = fixture();
        assert.throws(() => createNativeArchiveExport(filters, owner));
        assert.deepEqual(owner.events, []);
    }
});
