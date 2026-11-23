#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
xcodegen generate --spec project.yml
xcodebuild build-for-testing -project NextDeviceChecks.xcodeproj -scheme NextDeviceChecks \
  -destination 'generic/platform=iOS' -derivedDataPath DerivedData CODE_SIGNING_ALLOWED=NO
runner=DerivedData/Build/Products/Debug-iphoneos/NextDeviceChecks-Runner.app
test -d "$runner/PlugIns/NextDeviceChecks.xctest"
test -s "$runner/Frameworks/XCTest.framework/XCTest"
lipo "$runner/NextDeviceChecks-Runner" -verify_arch arm64
python3 - "$runner" <<'PY'
import plistlib, sys
from pathlib import Path
root = Path(sys.argv[1])
info = plistlib.loads((root / 'Info.plist').read_bytes())
assert info['CFBundleIdentifier'] == 'org.meshchat.next.ios.devicechecks.tests.xctrunner'
assert info['CFBundlePackageType'] == 'APPL'
# Build output must contain code/resources only, never an app's saved data.
for name in ('reticulum', 'identity', 'next-runtime-info.json', 'sip-account.json', 'peer.json'):
    assert not list(root.rglob(name)), 'Unexpected private runtime input in runner'
PY
mkdir -p Package/Payload
# Xcode can place debug-symbol companions beside the test plug-in. Those
# are retained in DerivedData for diagnostics, not shipped as app code.
python3 - "$runner" <<'PYTHON'
import shutil, sys
from pathlib import Path
source = Path(sys.argv[1])
target = Path("Package/Payload") / source.name
shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns("*.dSYM"))
assert not list(target.rglob("*.dSYM")), "Debug symbols must not be embedded in the device IPA"
assert (target / "PlugIns/NextDeviceChecks.xctest/NextDeviceChecks").is_file()
PYTHON
(cd Package && zip -qry ../neXt-Device-Checks-unsigned.ipa Payload)
shasum -a 256 neXt-Device-Checks-unsigned.ipa > neXt-Device-Checks-unsigned.ipa.sha256
