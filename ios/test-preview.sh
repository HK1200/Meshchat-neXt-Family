#!/usr/bin/env bash
set -euo pipefail

device_family="${1:-}"
case "$device_family" in
    iPhone|iPad) ;;
    *) echo "Usage: bash ios/test-preview.sh iPhone|iPad" >&2; exit 2 ;;
esac

scheme="${2:-FamilyPreview}"
case "$scheme" in
    FamilyPreview) specification=project.yml; signing=CODE_SIGNING_ALLOWED=NO ;;
    FamilyLive) specification=project-live.yml; signing=CODE_SIGN_IDENTITY=- ;;
    *) echo "Unknown test scheme" >&2; exit 2 ;;
esac

store_capture="${FAMILY_STORE_SCREENSHOTS:-0}"
build_overrides=()
if [[ "$store_capture" == 1 ]]; then
    [[ "$scheme" == FamilyLive ]] || exit 2
    build_overrides=("GCC_PREPROCESSOR_DEFINITIONS=FAMILY_APP_STORE=1"
                     "SWIFT_ACTIVE_COMPILATION_CONDITIONS=DEBUG FAMILY_STORE_SCREENSHOTS")
fi

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
destination="$(xcrun simctl list devices available --json | python3 -c '
import json
import re
import sys

family, store_capture = sys.argv[1:]
def matches(name):
    if not name.startswith(family + " "):
        return False
    if store_capture != "1":
        return True
    if family == "iPad":
        return name.startswith("iPad Pro 13-inch")
    return bool(re.fullmatch(r"iPhone (?:1[5-9]|2[0-9]) Pro", name))

candidates = []
for runtime, devices in json.load(sys.stdin)["devices"].items():
    match = re.fullmatch(r"com\.apple\.CoreSimulator\.SimRuntime\.iOS-(\d+(?:-\d+)*)", runtime)
    if match:
        version = tuple(map(int, match[1].split("-")))
        if version >= (17,):
            candidates.extend((version, device["udid"]) for device in devices
                              if device.get("isAvailable") and matches(device["name"]))
if not candidates:
    raise SystemExit(f"No iOS 17 or later {family} simulator is installed")
print(max(candidates)[1])
' "$device_family" "$store_capture")"

xcodegen generate --spec "$specification"
mkdir -p RuntimeBuild/results
result="$PWD/RuntimeBuild/results/$scheme-$device_family-$(uuidgen).xcresult"
xcodebuild test -project "$scheme.xcodeproj" -scheme "$scheme" \
    -destination "platform=iOS Simulator,id=$destination" \
    -derivedDataPath DerivedData -resultBundlePath "$result" -parallel-testing-enabled NO "$signing" "${build_overrides[@]}"

if [[ "$store_capture" == 1 ]]; then
    xcrun xcresulttool export attachments --path "$result" \
        --output-path "RuntimeBuild/store-screenshots/$device_family"
fi
