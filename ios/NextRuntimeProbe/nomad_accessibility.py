# SPDX-License-Identifier: 0BSD
"""Carry the reviewed link-label repair into the pinned mobile frontend."""
import hashlib
from pathlib import Path

CHUNK = "assets/vendor-micron-D8bfT5oc.js"
SHA256 = "27ed26bd6300159afaa9817552562927673ce4376b18e583f1469396ad73fc06"
BEFORE = "static enhanceA11y(t,e={}){"


def rewrite(source):
    if source.count(BEFORE) != 1:
        raise ValueError("The Micron accessibility entry point changed")
    helper = Path(__file__).with_name("nomad-link-labels.mjs").read_text()
    declaration = "export function labelNomadLinks"
    if helper.count(declaration) != 1:
        raise ValueError("The reviewed link label helper changed")
    helper = helper.replace(declaration, "function __nextLabelNomadLinks", 1)
    return source.replace(BEFORE, BEFORE + "__nextLabelNomadLinks(t);") + "\n" + helper


def stage(folder):
    path = Path(folder) / CHUNK
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise ValueError("The pinned Micron parser changed; review accessible link labels")
    path.write_text(rewrite(payload.decode()))



if __name__ == "__main__":
    import sys
    stage(Path(sys.argv[1]))
