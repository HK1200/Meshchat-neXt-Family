// SPDX-License-Identifier: 0BSD
export function createNativeArchiveExport(filters, { base = globalThis.location?.href, document = globalThis.document } = {}) {
    const origin = new URL(base);
    if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port || origin.username || origin.password) {
        throw new Error('The local app session is unavailable.');
    }
    if (!filters || typeof filters !== 'object' || Array.isArray(filters)) throw new Error('Choose valid export filters.');
    const target = new URL('/api/v1/nomadnet/archives/export', origin);
    for (const key of Object.keys(filters)) {
        if (!['q', 'destination_hash'].includes(key) || typeof filters[key] !== 'string') throw new Error('Choose valid export filters.');
        if (key === 'q' && filters[key].length > 256) throw new Error('Enter a shorter archive search.');
        if (key === 'destination_hash' && !/^[a-fA-F0-9]{32}$/.test(filters[key])) throw new Error('Choose a valid node.');
        target.searchParams.set(key, filters[key]);
    }
    const link = document.createElement('a');
    link.href = target.href;
    link.download = 'meshchatnext-archives.zip';
    link.hidden = true;
    document.body.appendChild(link);
    try { link.click(); } finally { link.remove(); }
    return target.href;
}
