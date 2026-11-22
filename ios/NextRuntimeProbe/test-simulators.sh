#!/usr/bin/env bash
set -euo pipefail

family_ios="$(cd -- "${1:?Pass the Family checkout ios directory}" && pwd)"
mode="${2:-simulators}"
case "$mode" in simulators|device) ;; *) exit 2 ;; esac
push_settings=()
if [[ -n "${NEXT_APNS_ENVIRONMENT:-}" ]]; then
    case "$NEXT_APNS_ENVIRONMENT" in development|production) ;;
        *) echo "NEXT_APNS_ENVIRONMENT must be development or production" >&2; exit 2 ;;
    esac
    if [[ "$mode" != device ]]; then
        echo "APNs entitlements require a device build and matching Apple profile" >&2; exit 2
    fi
    push_settings=("NEXT_APNS_ENVIRONMENT=$NEXT_APNS_ENVIRONMENT" "CODE_SIGN_ENTITLEMENTS=AppPush.entitlements")
fi
simulator_families=(iPhone iPad)
if [[ -n "${NEXT_PROBE_DEVICE:-}" ]]; then
    case "$NEXT_PROBE_DEVICE" in iPhone|iPad) simulator_families=("$NEXT_PROBE_DEVICE") ;;
        *) echo "Choose iPhone or iPad for NEXT_PROBE_DEVICE" >&2; exit 2 ;; esac
fi
probe="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
scratch="$(mktemp -d "${TMPDIR:-/tmp}/next-runtime-probe.XXXXXXXX")"
peer_pid=
sip_pid=
sip_incoming_pid=
sip_outgoing_pid=
owned_ui_simulators=("")
cleanup() {
    for call_pid in "$sip_incoming_pid" "$sip_outgoing_pid"; do
        if [[ -n "$call_pid" ]]; then
            kill "$call_pid" 2>/dev/null || true; wait "$call_pid" 2>/dev/null || true
        fi
    done
    if [[ -n "$peer_pid" ]]; then kill "$peer_pid" 2>/dev/null || true; wait "$peer_pid" 2>/dev/null || true; fi
    if [[ -n "$sip_pid" ]]; then kill "$sip_pid" 2>/dev/null || true; wait "$sip_pid" 2>/dev/null || true; fi
    for simulator in "${owned_ui_simulators[@]}"; do
        [[ -n "$simulator" ]] || continue
        xcrun simctl shutdown "$simulator" 2>/dev/null || true
        xcrun simctl delete "$simulator" 2>/dev/null || true
    done
    rm -rf -- "$scratch"
}
trap cleanup EXIT

bash "$family_ios/prepare-live.sh"
cd -- "$scratch"
cp -R "$probe/App" "$probe/project.yml" .
cp "$family_ios/SIP-NOTICES.txt" "$probe/PrivacyInfo.xcprivacy" .
cp "$probe/AppSimulator.entitlements" "$probe/TestsSimulator.entitlements" "$probe/AppPush.entitlements" .
ln -s "$family_ios/RuntimeBuild/sip" SIPBuild
cp "$family_ios/LiveRuntime/FamilySIP.c" "$family_ios/LiveRuntime/FamilySIP.h" "$family_ios/LiveRuntime/FamilySIPIdentity.c" "$family_ios/LiveRuntime/mobile_sip_audio.h" App/
cp "$family_ios/FamilyLive/FamilySIPPolicy.swift" "$family_ios/FamilyLive/FamilyKeyboard.swift" App/
cp "$family_ios/FamilyLive/FamilyVoiceAudio.swift" App/
cp "$family_ios/FamilyLive/FamilyNativeHTTPS.swift" App/
cp "$family_ios/FamilyLive/FamilySystemCalls.swift" "$family_ios/FamilyLive/FamilyCallKitDriver.swift" "$family_ios/FamilyLive/FamilyCallAudioSession.swift" App/
cp "$family_ios/FamilyLive/FamilyBluetooth.swift" "$family_ios/FamilyLive/FamilyBluetoothPicker.swift" "$family_ios/FamilyLive/FamilyRadioWake.swift" App/
ln -s "$family_ios/RuntimeBuild/Python.xcframework" Python.xcframework
ln -s "$family_ios" VoiceBuild
mkdir staged
curl --fail --silent --show-error --location --retry 3 \
    https://github.com/HK1200/Meshchat-neXt/releases/download/v0.1.21/meshchatnext-frontend.zip \
    --output frontend.zip
printf '%s\n' '1b1e8a9b77c64c780bc748167f22d879e739de58f861994612826612d92a950d  frontend.zip' \
    | shasum -a 256 -c -
unzip -q frontend.zip -d staged/frontend
python3 "$probe/sip_frontend.py" staged/frontend
python3 "$probe/voice_frontend.py" staged/frontend
curl --fail --silent --show-error --location --retry 3 \
    https://github.com/HK1200/Meshchat-neXt/releases/download/v0.1.21/meshchat_next-0.1.21-py3-none-any.whl \
    --output next-backend.whl
python3 "$probe/stage-backend.py" next-backend.whl staged "$family_ios"
python3 -m venv wheels-env
wheels-env/bin/python -m pip install --disable-pip-version-check --target staged \
    --only-binary=:all: --platform any --python-version 3.14 \
    --require-hashes --requirement "$probe/requirements.lock"
cp -R "$family_ios/RuntimeBuild/staged/RNS" "$family_ios/RuntimeBuild/staged/LXMF" staged/
cp "$probe/loopback_probe.py" "$probe/messaging_probe.py" "$probe/tcp_peers.py" "$probe/attachment_fields.py" "$probe/discovery.py" staged/
cp "$probe/meshcore_runtime.py" "$probe/meshcore_keychain.py" "$probe/meshcore_notices.py" "$probe/meshcore_repeat_crypto.py" "$probe/sip_native.py" "$probe/sip_runtime.py" "$probe/runtime_access.py" "$probe/durable_inbox.py" "$probe/offline_mailbox.py" "$probe/loopback_listener.py" staged/
cp "$probe/rnode_settings.py" "$family_ios/../app/src/main/python/family_radios.py" "$family_ios/../app/src/main/python/family_ios_bluetooth.py" staged/
cp "$family_ios/../app/src/main/python/family_tcp.py" staged/
cp "$family_ios/../app/src/main/python/mailbox_push.py" staged/mailbox_push.py
cp "$probe/voice_codec_probe.py" staged/voice_codec_probe.py
cp "$probe/voice_runtime.py" staged/voice_runtime.py
cp "$probe/map_runtime.py" staged/map_runtime.py
cp "$probe/relay_runtime.py" staged/relay_runtime.py
cp "$probe/outbound_mailbox.py" staged/outbound_mailbox.py
cp "$probe/push_receiving.py" staged/push_receiving.py
cp "$probe/telemetry_runtime.py" staged/telemetry_runtime.py
cp "$family_ios/../app/src/main/python/family_location.py" "$family_ios/../app/src/main/python/family_meshcore_location.py" staged/
cp "$family_ios/../app/src/main/python/family_maps.py" staged/family_maps.py
cp "$family_ios/../app/src/main/python/lxst_pyogg_ctypes_compat.py" staged/lxst_pyogg_ctypes_compat.py
cp -R "$family_ios/RuntimeBuild/staged/pycparser" staged/pycparser
PYTHONPATH="$scratch/staged" python3 "$probe/test-sip-accounts.py"
PYTHONPATH="$scratch/staged" python3 "$probe/test-sip-runtime.py"
if [[ "$mode" == device ]]; then
    # The device project excludes the simulator test target and its echo fixture.
    awk '/^  NextRuntimeProbeUnitTests:/ {exit} {print}' project.yml > device.yml
    cat >> device.yml <<'YAML'
schemes:
  NextRuntimeProbe:
    build:
      targets:
        NextRuntimeProbe: all
YAML
    python3 "$family_ios/build-sip.py" iphoneos arm64
    xcodegen generate --spec device.yml
    xcodebuild build -project NextRuntimeProbe.xcodeproj -scheme NextRuntimeProbe \
        -configuration Release -destination 'generic/platform=iOS' -derivedDataPath DerivedData \
        CODE_SIGNING_ALLOWED=NO "CURRENT_PROJECT_VERSION=${GITHUB_RUN_NUMBER:-1}.${GITHUB_RUN_ATTEMPT:-1}" "${push_settings[@]}"
    app=DerivedData/Build/Products/Release-iphoneos/NextRuntimeProbe.app
    lipo "$app/NextRuntimeProbe" -verify_arch arm64
    test -f "$app/Frameworks/Python.framework/Python"
    test -f "$app/staged/frontend/index.html"
    test -s "$app/SIP-NOTICES.txt"
    lipo "$app/Frameworks/FamilyVoiceCodecs.framework/FamilyVoiceCodecs" -verify_arch arm64
    test -s "$app/staged/LXST/Codecs/Opus.py"
    test -s "$app/staged/LXST/Codecs/Codec2.py"
    for notice in Opus-COPYING Codec2-COPYING audioop-LICENSE; do
        test -s "$app/staged/voice-notices/$notice"
    done
    test -s "$app/PrivacyInfo.xcprivacy"
    plutil -lint "$app/PrivacyInfo.xcprivacy"
    test ! -e "$app/staged/peer.json"
    test ! -e "$app/sip-account.json"
    /usr/libexec/PlistBuddy -c 'Print :UILaunchScreen' "$app/Info.plist" >/dev/null
    /usr/libexec/PlistBuddy -c 'Print :NSMicrophoneUsageDescription' "$app/Info.plist" >/dev/null
    python3 - "$app/Info.plist" <<'PYTHON'
import plistlib, sys
with open(sys.argv[1], 'rb') as stream:
    value = plistlib.load(stream)
assert {'audio', 'voip'}.issubset(value.get('UIBackgroundModes', [])), 'CallKit requires the VoIP mode in the actual device app'
PYTHON
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

# These UI checks require an actual software keyboard. A hosted runner's
# hardware-keyboard attachment can suppress it even when the field is focused.
# Set and verify this only on disposable simulator jobs, never a device build.
defaults write com.apple.iphonesimulator ConnectHardwareKeyboard -bool NO
test "$(defaults read com.apple.iphonesimulator ConnectHardwareKeyboard)" = 0

cp -R "$probe/Tests" .
# The shared wake type is compiled into this test target; do not import the Family app.
sed '/^@testable import FamilyLive$/d' "$family_ios/ContactPhotoTests/FamilyRadioWakeTests.swift" > Tests/FamilyRadioWakeTests.swift
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
python3 "$family_ios/sip-simulator-registrar.py" "$scratch/sip" > "$scratch/sip.log" 2>&1 &
sip_pid=$!
for ((i=0; i<100; i++)); do
    [[ ! -f "$scratch/sip/account.json" ]] || break
    kill -0 "$sip_pid" 2>/dev/null || { cat "$scratch/sip.log"; exit 1; }
    sleep 0.1
done
[[ -f "$scratch/sip/account.json" ]] || { cat "$scratch/sip.log"; exit 1; }
cp "$scratch/sip/account.json" Tests/sip-account.json
for direction in incoming outgoing; do
    python3 "$probe/sip_call_fixture.py" "$scratch/sip-$direction" "$direction" > "$scratch/sip-$direction.log" 2>&1 &
    call_pid=$!
    if [[ "$direction" == incoming ]]; then sip_incoming_pid=$call_pid; else sip_outgoing_pid=$call_pid; fi
    for ((i=0; i<100; i++)); do
        [[ ! -f "$scratch/sip-$direction/account.json" ]] || break
        kill -0 "$call_pid" 2>/dev/null || { cat "$scratch/sip-$direction.log"; exit 1; }
        sleep 0.1
    done
    [[ -f "$scratch/sip-$direction/account.json" ]] || { cat "$scratch/sip-$direction.log"; exit 1; }
    cp "$scratch/sip-$direction/account.json" "Tests/sip-$direction.json"
done


xcodegen generate
mkdir -p "$family_ios/RuntimeBuild/next-results"
result_set="$(mktemp -d "$family_ios/RuntimeBuild/next-results/run.XXXXXXXX")"
# The embedded Python packager selects lib-$ARCHS. Build the host slice only;
# generic simulator destinations otherwise request "arm64 x86_64" as one path.
simulator_arch="$(uname -m)"
case "$simulator_arch" in arm64|x86_64) ;; *) echo "Unsupported simulator host architecture" >&2; exit 1 ;; esac
python3 "$family_ios/build-sip.py" iphonesimulator "$simulator_arch"
xcodebuild build-for-testing -project NextRuntimeProbe.xcodeproj -scheme NextRuntimeProbe \
    -destination 'generic/platform=iOS Simulator' -derivedDataPath DerivedData \
    -parallel-testing-enabled NO \
        -test-timeouts-enabled YES -default-test-execution-time-allowance 600 \
        -maximum-test-execution-time-allowance 900 CODE_SIGN_IDENTITY=- "ARCHS=$simulator_arch" ONLY_ACTIVE_ARCH=YES
python3 "$probe/inspect-simulator-apps.py" DerivedData/Build/Products/Debug-iphonesimulator "$result_set"
test_runs=(DerivedData/Build/Products/*.xctestrun)
[[ ${#test_runs[@]} == 1 && -f "${test_runs[0]}" ]]
test_arguments=(-xctestrun "${test_runs[0]}")
case "${NEXT_PROBE_UNIT_ONLY:-false}" in
    true) ;;
    false) ;;
    *) echo "NEXT_PROBE_UNIT_ONLY must be true or false" >&2; exit 2 ;;
esac
# Hosted native tests initialize CPython, WebKit and audio. XCTest must not
# reuse that host during its UI launch handoff. Keep independent real results
# and require both phases. Native and UI hosts use distinct disposable
# containers; UI restart/data-preservation assertions still run unchanged.
run_device_tests() {
    local unit_result="$result_set/$device-native.xcresult"
    local ui_result="$result_set/$device-ui.xcresult"
    failed_result_bundle="$unit_result"
    if xcodebuild test-without-building "${test_arguments[@]}" \
        -only-testing:NextRuntimeProbeUnitTests \
        -destination "platform=iOS Simulator,arch=$simulator_arch,id=$destination" \
        -resultBundlePath "$unit_result" -parallel-testing-enabled NO \
        -test-timeouts-enabled YES -default-test-execution-time-allowance 600 \
        -maximum-test-execution-time-allowance 900; then
        xcrun xcresulttool get test-results summary --path "$unit_result" > "$result_set/$device-native-summary.json" || return $?
        xcrun xcresulttool get test-results tests --path "$unit_result" > "$result_set/$device-native-tests.json" || return $?
    else return $?; fi
    if [[ "${NEXT_PROBE_UNIT_ONLY:-false}" == true ]]; then
        cp "$result_set/$device-native-summary.json" "$result_set/$device-summary.json" || return $?
        cp "$result_set/$device-native-tests.json" "$result_set/$device-tests.json" || return $?
        return 0
    fi
    # A reboot alone still left Xcode attaching to a terminated unit-test
    # host on iPad. Use a clean simulator of the same runtime and device type.
    # This never clones/erases app data and never targets a USB device.
    local ui_destination
    ui_destination="$(python3 "$probe/fresh-simulator.py" "$destination" "$device")" || return $?
    owned_ui_simulators+=("$ui_destination")
    xcrun simctl shutdown "$destination" || return $?
    destination="$ui_destination"
    xcrun simctl bootstatus "$destination" -b || return $?
    failed_result_bundle="$ui_result"
    if xcodebuild test-without-building "${test_arguments[@]}" \
        -only-testing:NextRuntimeProbeUITests \
        -destination "platform=iOS Simulator,arch=$simulator_arch,id=$destination" \
        -resultBundlePath "$ui_result" -parallel-testing-enabled NO \
        -test-timeouts-enabled YES -default-test-execution-time-allowance 600 \
        -maximum-test-execution-time-allowance 900; then
        xcrun xcresulttool get test-results summary --path "$ui_result" > "$result_set/$device-ui-summary.json" || return $?
        xcrun xcresulttool get test-results tests --path "$ui_result" > "$result_set/$device-ui-tests.json" || return $?
    else return $?; fi
    python3 "$probe/verify-test-results.py" \
        "$result_set/$device-native-summary.json" "$result_set/$device-native-tests.json" "$scratch/Tests" \
        --ui-summary "$result_set/$device-ui-summary.json" --ui-tree "$result_set/$device-ui-tests.json" \
        --write-prefix "$result_set/$device" > "$result_set/$device-phase-proof.json" || return $?
}

sip_expected=0
for device in "${simulator_families[@]}"; do
    sip_expected=$((sip_expected + 1))
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
    # A simulator can expose the app's accessibility tree while its boot
    # overlay still intercepts touches. Complete OS boot before XCTest starts;
    # the failed recording and all original assertions remain retained.
    xcrun simctl bootstatus "$destination" -b
    if run_device_tests; then
        if [[ -f "$scratch/sip/observed.json" ]]; then cp "$scratch/sip/observed.json" "$result_set/$device-sip-observed.json"; fi
        proof_arguments=("$result_set/$device-summary.json" "$result_set/$device-tests.json" "$scratch/Tests")
        if [[ "${NEXT_PROBE_UNIT_ONLY:-false}" == true ]]; then proof_arguments+=(--unit-only); fi
        python3 "$probe/verify-test-results.py" "${proof_arguments[@]}" > "$result_set/$device-proof.json"
        cat "$result_set/$device-proof.json"
        python3 - "$scratch/sip/observed.json" "$result_set/$device-sip-proof.json" "$sip_expected" <<'PYTHON'
import json, sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text())
assert value.get("authenticated") is True and value.get("unregistered") is True and value.get("host")=="127.0.0.1", "The native app did not authenticate and unregister"
assert value.get("registrations",0)>=int(sys.argv[3]) and value.get("unregistrations",0)>=int(sys.argv[3]), "A simulator reused a previous account proof"
Path(sys.argv[2]).write_text(json.dumps(value,sort_keys=True)+"\n")
PYTHON
        for direction in incoming outgoing; do
            cp "$scratch/sip-$direction/observed.json" "$result_set/$device-sip-$direction-observed.json"
            python3 - "$result_set/$device-sip-$direction-observed.json" "$result_set/$device-sip-$direction-proof.json" "$sip_expected" <<'PYTHON'
import json,sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text())
assert value.get("authenticated") is True and value.get("bound_local_interface") is True
if value.get("mode")=="incoming":
    assert value.get("host")=="127.0.0.1" and value.get("scope")=="loopback"
else:
    assert value.get("scope")=="local-interface" and value.get("host")!="127.0.0.1"
for field in ("registrations","unregistrations","completed_calls"):
    assert value.get(field,0)>=int(sys.argv[3]), "Native SIP direction lacks fresh wire proof: "+field
Path(sys.argv[2]).write_text(json.dumps(value,sort_keys=True)+"\n")
PYTHON
        done
        # Release the previous simulator before testing the other device family.
        xcrun simctl shutdown "$destination" || true
    else
        next_probe_exit=$?
        # These bundles use only fresh synthetic simulator profiles. Export
        # this failed test's recording as well as its issue text, preserving
        # the actual test exit code even if diagnostic extraction fails.
        if [[ -d "$failed_result_bundle" ]]; then
            xcrun xcresulttool export attachments --path "$failed_result_bundle" \
                --output-path "$result_set/activity-$device" \
                --test-id 'ProbeUITests/testConversationSendsAndReceivesSignedLXMF()' \
                || echo "Synthetic activity export unavailable; the original test failure is retained"
        fi
        xcrun simctl spawn "$destination" log show --style compact --last 5m \
            --predicate 'process == "NextRuntimeProbe" OR process == "SpringBoard" OR process == "runningboardd"' \
            > "$result_set/$device-launch-system.log" 2>&1 || true
        mkdir -p "$result_set/crashes-$device"
        for report in "$HOME/Library/Logs/DiagnosticReports/"NextRuntimeProbe*.ips \
                      "$HOME/Library/Logs/DiagnosticReports/"NextRuntimeProbe*.crash; do
            if [[ -f "$report" ]]; then cp "$report" "$result_set/crashes-$device/"; fi
        done
        for app_name in NextRuntimeProbe NextRuntimeProbeUITests-Runner; do
            bundle="DerivedData/Build/Products/Debug-iphonesimulator/$app_name.app"
            if [[ -d "$bundle" ]]; then
                codesign -d --entitlements :- "$bundle" > "$result_set/$app_name-entitlements.plist" 2> "$result_set/$app_name-codesign.log" || true
            fi
        done
        if [[ -f "$scratch/sip/observed.json" ]]; then cp "$scratch/sip/observed.json" "$result_set/$device-sip-observed.json"; fi
        for direction in incoming outgoing; do
            if [[ -f "$scratch/sip-$direction/observed.json" ]]; then
                cp "$scratch/sip-$direction/observed.json" "$result_set/$device-sip-$direction-observed.json"
            fi
        done
        cp "$scratch/echo.log" "$result_set/echo.log"
        cat "$scratch/echo.log"
        exit "$next_probe_exit"
    fi
done

for device in "${simulator_families[@]}"; do test -s "$result_set/$device-proof.json"; done
