#!/usr/bin/env bash
set -euo pipefail

family_ios="$(cd -- "${1:?Pass the Family checkout ios directory}" && pwd)"
probe="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
scratch="$(mktemp -d "${TMPDIR:-/tmp}/next-runtime-probe.XXXXXXXX")"
peer_pid=
cleanup() {
    if [[ -n "$peer_pid" ]]; then kill "$peer_pid" 2>/dev/null || true; wait "$peer_pid" 2>/dev/null || true; fi
    rm -rf -- "$scratch"
}
trap cleanup EXIT

bash "$family_ios/prepare-live.sh"
cd -- "$scratch"
cp -R "$probe/App" "$probe/Tests" "$probe/project.yml" .
ln -s "$family_ios/RuntimeBuild/Python.xcframework" Python.xcframework
mkdir staged
curl --fail --silent --show-error --location --retry 3 \
    https://github.com/HK1200/Meshchat-neXt/releases/download/v0.1.19/meshchatnext-frontend.zip \
    --output frontend.zip
printf '%s\n' 'c5144f886cf79e5b44a8f68b5edf590df1109a5f06131c76bc01fb720ceee6a2  frontend.zip' \
    | shasum -a 256 -c -
unzip -q frontend.zip -d staged/frontend
python3 -m venv wheels-env
wheels-env/bin/python -m pip install --disable-pip-version-check --target staged \
    --only-binary=:all: --platform any --python-version 3.14 'aiohttp==3.14.5'
cp -R "$family_ios/RuntimeBuild/staged/RNS" "$family_ios/RuntimeBuild/staged/LXMF" staged/
cp "$probe/loopback_probe.py" "$probe/messaging_probe.py" staged/
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$scratch/staged" python3 "$family_ios/simulator-peer.py" "$scratch/echo" local-no-drop > "$scratch/echo.log" 2>&1 &
peer_pid=$!
for ((i=0; i<200; i++)); do
    [[ ! -f "$scratch/echo/peer.json" ]] || break
    kill -0 "$peer_pid" 2>/dev/null || { cat "$scratch/echo.log"; exit 1; }
    sleep 0.1
done
[[ -f "$scratch/echo/peer.json" ]] || { cat "$scratch/echo.log"; exit 1; }
cp "$scratch/echo/peer.json" staged/
cp "$scratch/echo/peer.json" Tests/peer.json

xcodegen generate
for device in iPhone iPad; do
    destination="$(xcrun simctl list devices available --json | python3 -c '
import json, sys
family = sys.argv[1] + " "
devices = json.load(sys.stdin)["devices"]
for runtime in sorted(devices, key=lambda k: tuple(int(v) for v in k.split("iOS-")[-1].split("-"))
                      if "iOS-" in k else (), reverse=True):
    matches = [row["udid"] for row in devices[runtime] if row["name"].startswith(family)]
    if matches:
        print(matches[0])
        break
else:
    raise SystemExit(f"No {family.strip()} simulator available")
' "$device")"
    xcodebuild test -project NextRuntimeProbe.xcodeproj -scheme NextRuntimeProbe \
        -destination "platform=iOS Simulator,id=$destination" -derivedDataPath DerivedData \
        -parallel-testing-enabled NO CODE_SIGN_IDENTITY=- || { cat "$scratch/echo.log"; exit 1; }
done
