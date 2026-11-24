#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mode="${2:-local}"
case "$mode" in
    local|rmap) ;;
    *) echo "Usage: bash ios/test-live.sh iPhone|iPad [local|rmap]" >&2; exit 2 ;;
esac
bash prepare-live.sh

run="$(mktemp -d "$PWD/RuntimeBuild/simulator-test.XXXXXXXX")"
peer_pid=
device_family="${1:-unknown}"
cleanup() {
    if [[ -n "$peer_pid" ]]; then kill "$peer_pid" 2>/dev/null || true; wait "$peer_pid" 2>/dev/null || true; fi
    # Retain synthetic-only peer events beside XCTest results so an inbox/UI
    # failure can be distinguished from a missing network delivery.
    mkdir -p "$PWD/RuntimeBuild/results"
    if [[ -f "$run/peer.log" && ! -L "$run/peer.log" ]]; then
        cp -- "$run/peer.log" "$PWD/RuntimeBuild/results/peer-${device_family}.log"
    fi
    rm -f -- "$PWD/RuntimeBuild/test-peer.json"
    rm -rf -- "$run"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
# Keep synthetic peer events outside the temporary run even if the CI job is
# cancelled before its EXIT trap can finish.
mkdir -p "$PWD/RuntimeBuild/results"
peer_log="$PWD/RuntimeBuild/results/peer-${device_family}.log"
PYTHONPATH="$PWD/RuntimeBuild/staged" python3 -u -S simulator-peer.py "$run/hub" "$mode" > "$peer_log" 2>&1 &
ln -s -- "$peer_log" "$run/peer.log"
peer_pid=$!
for ((i=0; i<300; i++)); do
    if [[ -f "$run/hub/peer.json" ]]; then break; fi
    if ! kill -0 "$peer_pid" 2>/dev/null; then cat "$run/peer.log"; exit 1; fi
    sleep 0.1
done
test -f "$run/hub/peer.json" || { cat "$run/peer.log"; exit 1; }
cp -- "$run/hub/peer.json" RuntimeBuild/test-peer.json
bash test-preview.sh "${1:-}" FamilyLive || { cat "$run/peer.log"; exit 1; }
