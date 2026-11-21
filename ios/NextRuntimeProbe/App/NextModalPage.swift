import Foundation

/// WebKit owns a remote accessibility tree. A native modal must also suspend
/// interaction in the DOM, without unloading the conversation or its draft.
enum NextModalPage {
    static let script = """
        const root = document.documentElement;
        if (!root) return false;
        const states = globalThis.__nextNativeModalRoots ??= new WeakMap();
        if (active) {
            if (!states.has(root)) {
                states.set(root, { aria: root.getAttribute("aria-hidden"), inert: root.inert });
            }
            document.activeElement?.blur();
            root.setAttribute("aria-hidden", "true");
            root.inert = true;
        } else if (states.has(root)) {
            const previous = states.get(root);
            if (previous.aria === null) root.removeAttribute("aria-hidden");
            else root.setAttribute("aria-hidden", previous.aria);
            root.inert = previous.inert;
            states.delete(root);
        }
        return true;
        """
}
