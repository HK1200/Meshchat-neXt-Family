#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
bash prepare-live.sh

run="$(mktemp -d "$PWD/RuntimeBuild/simulator-test.XXXXXXXX")"
peer_pid=
cleanup() {
    if [[ -n "$peer_pid" ]]; then kill "$peer_pid" 2>/dev/null || true; wait "$peer_pid" 2>/dev/null || true; fi
    rm -f -- "$PWD/RuntimeBuild/test-peer.json"
    rm -rf -- "$run"
}
trap cleanup EXIT
PYTHONPATH="$PWD/RuntimeBuild/staged" python3 -S simulator-peer.py "$run/hub" > "$run/peer.log" 2>&1 &
peer_pid=$!
for ((i=0; i<100; i++)); do
    if [[ -f "$run/hub/peer.json" ]]; then break; fi
    if ! kill -0 "$peer_pid" 2>/dev/null; then cat "$run/peer.log"; exit 1; fi
    sleep 0.1
done
test -f "$run/hub/peer.json" || { cat "$run/peer.log"; exit 1; }
cp -- "$run/hub/peer.json" RuntimeBuild/test-peer.json
bash test-preview.sh "${1:-}" FamilyLive
