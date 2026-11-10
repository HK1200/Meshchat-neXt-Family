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

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
destination="$(xcrun simctl list devices available --json | python3 -c '
import json
import re
import sys

family = sys.argv[1]
candidates = []
for runtime, devices in json.load(sys.stdin)["devices"].items():
    match = re.fullmatch(r"com\.apple\.CoreSimulator\.SimRuntime\.iOS-(\d+(?:-\d+)*)", runtime)
    if match:
        version = tuple(map(int, match[1].split("-")))
        if version >= (17,):
            candidates.extend((version, device["udid"]) for device in devices
                              if device.get("isAvailable") and device["name"].startswith(family + " "))
if not candidates:
    raise SystemExit(f"No iOS 17 or later {family} simulator is installed")
print(max(candidates)[1])
' "$device_family")"

xcodegen generate --spec "$specification"
xcodebuild test -project "$scheme.xcodeproj" -scheme "$scheme" \
    -destination "platform=iOS Simulator,id=$destination" \
    -derivedDataPath DerivedData -parallel-testing-enabled NO "$signing"
