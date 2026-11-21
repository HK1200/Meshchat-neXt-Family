function (configuration) {
    "use strict";
    if (location.origin !== configuration.origin) return;
    const keys = new Set(configuration.keys);
    const storage = window.localStorage;
    const original = { set: Storage.prototype.setItem, remove: Storage.prototype.removeItem, clear: Storage.prototype.clear };
    const committed = new Map();
    for (const key of keys) {
        const value = configuration.values[key];
        if (typeof value === "string") original.set.call(storage, key, value);
        committed.set(key, storage.getItem(key));
    }
    let sequence = 0;
    let queue = Promise.resolve();
    const generations = new Map();
    function stamp(key) { const next = ++sequence; generations.set(key, next); return next; }
    function restore(key) {
        const before = committed.get(key), after = storage.getItem(key);
        if (before === null) original.remove.call(storage, key);
        else original.set.call(storage, key, before);
        window.dispatchEvent(new StorageEvent("storage", { key, oldValue: after, newValue: before, storageArea: storage }));
    }
    function save(request, changed) {
        // Preserve native write order and roll back to the last acknowledged
        // snapshot, including when several consecutive writes are rejected.
        queue = queue.then(async () => {
            try {
                const result = await window.webkit.messageHandlers.nextPreferences.postMessage(request);
                if (result !== true) throw new Error("Not saved");
                if (request.op === "clear") for (const key of keys) committed.set(key, null);
                else committed.set(request.key, request.op === "set" ? request.value : null);
            } catch {
                for (const [key, generation] of changed) {
                    if (generations.get(key) === generation) restore(key);
                }
            }
        });
    }
    Object.defineProperty(Storage.prototype, "setItem", { configurable: true, writable: true, value: function (key, value) {
        const name = String(key), text = String(value), managed = this === storage && keys.has(name);
        const result = original.set.call(this, name, text);
        if (managed) save({ op: "set", key: name, value: text }, [[name, stamp(name)]]);
        return result;
    }});
    Object.defineProperty(Storage.prototype, "removeItem", { configurable: true, writable: true, value: function (key) {
        const name = String(key), managed = this === storage && keys.has(name);
        const result = original.remove.call(this, name);
        if (managed) save({ op: "remove", key: name }, [[name, stamp(name)]]);
        return result;
    }});
    Object.defineProperty(Storage.prototype, "clear", { configurable: true, writable: true, value: function () {
        const changed = this === storage ? [...keys].map(key => [key, stamp(key)]) : [];
        const result = original.clear.call(this);
        if (this === storage) save({ op: "clear" }, changed);
        return result;
    }});
}
