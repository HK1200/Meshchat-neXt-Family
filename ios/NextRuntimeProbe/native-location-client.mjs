/** Keep the released chat controls in sync with native sharing consent.
 * This module never reads or sends coordinates. Native sampling owns the fix.
 */
export function createNativeLocationClient({sessions, request, report = () => {},
    now = () => Date.now(),
    identifier = () => crypto.randomUUID().replaceAll("-", "").toLowerCase(),
    hidden = () => document.hidden,
    subscribe = (callback) => {
        document.addEventListener("visibilitychange", callback);
        return () => document.removeEventListener("visibilitychange", callback);
    },
    every = (callback) => {
        const timer = setInterval(callback, 3000);
        return () => clearInterval(timer);
    }}) {
    const entries = new Map(), pending = new Map();
    let disposed = false, syncing = false, epoch = -1;
    const validKey = (key) => typeof key === "string" && /^reticulum:[a-f0-9]{32}:[a-f0-9]{32}$/.test(key);
    const validID = (id) => typeof id === "string" && /^[a-f0-9]{32}$/.test(id);

    function finish(key, entry, reason = "stopped") {
        if (entries.get(key) === entry) entries.delete(key);
        if (sessions.get(key) === entry.value) sessions.delete(key);
        if (!entry.finished) {
            entry.finished = true;
            try { entry.onStop?.(reason); } catch { /* UI cleanup cannot undo revocation. */ }
        }
    }
    function makeEntry(key, name, id, options = {}) {
        const entry = {id, name, onStop: options.onStop, check: options.isCurrent,
            cancelled: false, finished: false, stopping: null};
        entry.value = {name, __nextNativeLocation: true,
            stop: (reason = "stopped") => stop(key, entry, typeof reason === "string" ? reason : "stopped")};
        entries.set(key, entry); sessions.set(key, entry.value);
        return entry;
    }
    function validate(state) {
        if (!state || !Number.isSafeInteger(state.consent_epoch) || state.consent_epoch < 0 ||
            typeof state.active !== "boolean" || !Array.isArray(state.sessions) || state.sessions.length > 16) {
            throw new Error("Invalid location state");
        }
        for (const row of state.sessions) {
            if (!row || !validKey(row.target) || !validID(row.request_id) ||
                typeof row.name !== "string" || row.name.length > 256 ||
                typeof row.background !== "boolean" || !Number.isFinite(row.until)) {
                throw new Error("Invalid sharing session");
            }
        }
        return state;
    }
    function reconcile(raw) {
        const state = validate(raw);
        if (disposed || state.consent_epoch < epoch) return;
        epoch = state.consent_epoch;
        const rows = state.active ? state.sessions.filter((row) => row.until === -1 || row.until * 1000 > now()) : [];
        const present = new Set(rows.map((row) => row.target));
        for (const [key, entry] of entries) {
            if (!present.has(key) && !pending.has(key)) finish(key, entry);
        }
        for (const row of rows) {
            if (pending.has(row.target)) continue;
            const current = entries.get(row.target);
            if (current?.id === row.request_id) {
                if (current.value.name !== row.name) {
                    current.name = row.name; current.value = {...current.value, name: row.name};
                    sessions.set(row.target, current.value);
                }
                continue;
            }
            if (current) finish(row.target, current, "superseded");
            const previous = sessions.get(row.target);
            // A new explicit native session supersedes a legacy manual timer
            // for that same contact; unrelated MeshCore/manual sessions remain.
            if (previous && !previous.__nextNativeLocation) previous.stop("superseded");
            makeEntry(row.target, row.name, row.request_id);
        }
    }
    async function stop(key, entry, reason) {
        if (entry.finished) return true;
        entry.cancelled = true;
        if (entry.stopping) return entry.stopping;
        entry.stopping = (async () => {
            try {
                const state = validate(await request("POST", {
                    action: "stop", target: key, request_id: entry.id,
                }));
                if (state.sessions.some((row) => row.target === key && row.request_id === entry.id)) {
                    throw new Error("Stop not confirmed");
                }
                finish(key, entry, reason);
                reconcile(state);
                return true;
            } catch {
                if (entry.finished) return true;
                report("Could not confirm Stop. Open Location sharing and try Stop all.", "error");
                return false;
            } finally { entry.stopping = null; }
        })();
        return entry.stopping;
    }
    function handles(key, options) {
        return validKey(key) && options && Number.isFinite(options.firstFix?.time);
    }
    function start(key, name, options) {
        if (!handles(key, options) || sessions.has(key)) return false;
        const entry = makeEntry(key, name, identifier(), options);
        pending.set(key, entry);
        void (async () => {
            let result;
            try {
                const state = validate(await request("GET"));
                if (entry.cancelled || disposed) return;
                if (entry.check && !entry.check()) { finish(key, entry); return; }
                if (state.active && state.sessions.some((row) => row.target === key)) {
                    // The native settings panel may have started this contact
                    // before its last UI refresh. Adopt it without changing it.
                    result = state; return;
                }
                const remaining = options.deadline - now();
                if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 3600000) {
                    finish(key, entry, "expired"); return;
                }
                result = validate(await request("POST", {
                    action: "start", targets: [key], duration: remaining <= 900000 ? "15" : "60",
                    // The normal chat confirmation authorizes foreground sharing.
                    // Locked sharing needs its explicit native setting per recipient.
                    background: false, deadline: options.deadline / 1000,
                    request_id: entry.id, consent_epoch: state.consent_epoch,
                }));
            } catch {
                if (!entry.cancelled) {
                    finish(key, entry, "error");
                    report("Timed sharing could not start. Your first update may already be queued.", "error");
                }
            } finally {
                if (pending.get(key) === entry) pending.delete(key);
                if (result && !entry.cancelled && !disposed) {
                    // Rebind the existing entry only after server acceptance.
                    // Preserve its chat-level checks and Stop callback.
                    const row = result.sessions.find((row) => row.target === key);
                    if (row && row.request_id !== entry.id) finish(key, entry, "superseded");
                    reconcile(result);
                }
                if (entry.cancelled && !entry.stopping) void sync();
            }
        })();
        return true;
    }
    async function sync() {
        if (disposed || syncing || hidden()) return;
        syncing = true;
        try {
            for (const [key, entry] of entries) {
                let allowed = true;
                try { if (entry.check) allowed = entry.check(); } catch { allowed = false; }
                if (!allowed && !entry.cancelled) void stop(key, entry, "stopped");
            }
            const revision = epoch;
            const state = await request("GET");
            if (!disposed && epoch === revision) reconcile(state);
        } catch { /* Backend recovery retries quietly; never declare Stop without proof. */ }
        finally { syncing = false; }
    }
    const unsubscribe = subscribe(() => { if (!hidden()) void sync(); });
    const cancelTimer = every(() => { void sync(); });
    // Wait until the module has finished loading; API initialization can follow.
    void Promise.resolve().then(sync);
    return {handles, start, sync, dispose() { disposed = true; unsubscribe(); cancelTimer(); }};
}
