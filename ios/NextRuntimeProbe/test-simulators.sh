#!/usr/bin/env bash
set -euo pipefail

family_ios="$(cd -- "${1:?Pass the Family checkout ios directory}" && pwd)"
mode="${2:-simulators}"
case "$mode" in simulators|device) ;; *) exit 2 ;; esac
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
cp -R "$probe/App" "$probe/project.yml" .
cp "$family_ios/FamilyLive/FamilyBluetooth.swift" "$family_ios/FamilyLive/FamilyBluetoothPicker.swift" "$family_ios/FamilyLive/FamilyRadioWake.swift" App/
ln -s "$family_ios/RuntimeBuild/Python.xcframework" Python.xcframework
mkdir staged
curl --fail --silent --show-error --location --retry 3 \
    https://github.com/HK1200/Meshchat-neXt/releases/download/v0.1.20/meshchatnext-frontend.zip \
    --output frontend.zip
printf '%s\n' '14814af6c6fb5a50236e8ad8420917bcdf51e5142818baa0419a6ca4522a6749  frontend.zip' \
    | shasum -a 256 -c -
unzip -q frontend.zip -d staged/frontend
python3 -m venv wheels-env
wheels-env/bin/python -m pip install --disable-pip-version-check --target staged \
    --only-binary=:all: --platform any --python-version 3.14 \
    --require-hashes --requirement "$probe/requirements.lock"
cp -R "$family_ios/RuntimeBuild/staged/RNS" "$family_ios/RuntimeBuild/staged/LXMF" staged/
cp "$probe/loopback_probe.py" "$probe/messaging_probe.py" "$probe/tcp_peers.py" "$probe/attachment_fields.py" "$probe/discovery.py" staged/
cp "$probe/rnode_settings.py" "$family_ios/../app/src/main/python/family_radios.py" "$family_ios/../app/src/main/python/family_ios_bluetooth.py" staged/
cp "$family_ios/../app/src/main/python/family_tcp.py" staged/
if [[ "$mode" == device ]]; then
    # The device project excludes the simulator test target and its echo fixture.
    awk '/^  NextRuntimeProbeUITests:/ {exit} {print}' project.yml > device.yml
    cat >> device.yml <<'YAML'
schemes:
  NextRuntimeProbe:
    build:
      targets:
        NextRuntimeProbe: all
YAML
    xcodegen generate --spec device.yml
    xcodebuild build -project NextRuntimeProbe.xcodeproj -scheme NextRuntimeProbe \
        -configuration Release -destination 'generic/platform=iOS' -derivedDataPath DerivedData \
        CODE_SIGNING_ALLOWED=NO "CURRENT_PROJECT_VERSION=${GITHUB_RUN_NUMBER:-1}.${GITHUB_RUN_ATTEMPT:-1}"
    app=DerivedData/Build/Products/Release-iphoneos/NextRuntimeProbe.app
    lipo "$app/NextRuntimeProbe" -verify_arch arm64
    test -f "$app/Frameworks/Python.framework/Python"
    test -f "$app/staged/frontend/index.html"
    test ! -e "$app/staged/peer.json"
    /usr/libexec/PlistBuddy -c 'Print :UILaunchScreen' "$app/Info.plist" >/dev/null
    test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Info.plist")" = org.meshchat.next.ios.runtimeprobe
    mkdir Payload
    ditto "$app" Payload/NextRuntimeProbe.app
    ipa="$family_ios/RuntimeBuild/neXt-iOS-unsigned.ipa"
    rm -f -- "$ipa"
    ditto -c -k --keepParent Payload "$ipa"
    unzip -tq "$ipa"
    shasum -a 256 "$ipa"
    exit
fi

cp -R "$probe/Tests" .
cp "$family_ios/ContactPhotoTests/FamilyRadioWakeTests.swift" Tests/
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$scratch/staged" python3 "$family_ios/simulator-peer.py" "$scratch/echo" local-no-drop attachment-echo > "$scratch/echo.log" 2>&1 &
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
mkdir -p "$family_ios/RuntimeBuild/next-results"
result_set="$(mktemp -d "$family_ios/RuntimeBuild/next-results/run.XXXXXXXX")"
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
    if xcodebuild test -project NextRuntimeProbe.xcodeproj -scheme NextRuntimeProbe \
        -destination "platform=iOS Simulator,id=$destination" -derivedDataPath DerivedData \
        -resultBundlePath "$result_set/$device.xcresult" \
        -parallel-testing-enabled NO CODE_SIGN_IDENTITY=-; then
        # Release the previous simulator before testing the other device family.
        xcrun simctl shutdown "$destination" || true
    else
        next_probe_exit=$?
        mkdir -p "$result_set/crashes-$device"
        for report in "$HOME/Library/Logs/DiagnosticReports/"NextRuntimeProbe*.ips \
                      "$HOME/Library/Logs/DiagnosticReports/"NextRuntimeProbe*.crash; do
            if [[ -f "$report" ]]; then cp "$report" "$result_set/crashes-$device/"; fi
        done
        cp "$scratch/echo.log" "$result_set/echo.log"
        cat "$scratch/echo.log"
        exit "$next_probe_exit"
    fi
done
