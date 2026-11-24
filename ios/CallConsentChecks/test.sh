#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
case "${DEVICE_FAMILY:?}" in iPhone|iPad) ;; *) exit 2 ;; esac
xcodegen generate --spec project.yml
mkdir -p Results
python3 - "$DEVICE_FAMILY" > Results/device <<'PY'
import json, re, subprocess, sys
inventory = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devices", "available", "--json"]))
candidates=[]
for runtime, rows in inventory["devices"].items():
    match=re.fullmatch(r"com\.apple\.CoreSimulator\.SimRuntime\.iOS-(\d+(?:-\d+)*)", runtime)
    if match:
        version=tuple(map(int,match[1].split("-")))
        for row in rows:
            if row["name"].startswith(sys.argv[1]) and row.get("isAvailable"):
                candidates.append((version,row["name"],row["udid"]))
assert candidates, "A supported simulator is required"
print(max(candidates)[2])
PY
simulator="$(cat Results/device)"
# Never address a USB device. This job owns a fresh ephemeral hosted runner.
# Complete the cold simulator boot before XCTest asks its service to launch.
xcrun simctl boot "$simulator" || [[ "$(xcrun simctl list devices booted --json)" == *"$simulator"* ]]
xcrun simctl bootstatus "$simulator" -b
xcodebuild test -project CallConsentChecks.xcodeproj -scheme CallConsentChecks \
  -destination "platform=iOS Simulator,id=$simulator" \
  -derivedDataPath DerivedData -resultBundlePath Results/consent.xcresult \
  -parallel-testing-enabled NO -test-timeouts-enabled YES \
  -default-test-execution-time-allowance 30 -maximum-test-execution-time-allowance 120 \
  CODE_SIGN_IDENTITY=-
xcrun xcresulttool get test-results summary --path Results/consent.xcresult > Results/summary.json
xcrun xcresulttool get test-results tests --path Results/consent.xcresult > Results/tests.json
python3 - <<'PY'
import hashlib, importlib.util, json
from pathlib import Path
spec=importlib.util.spec_from_file_location("verify", "../NextRuntimeProbe/verify-test-results.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
# Build a source inventory containing only the real tests included above.
source=Path("Results/source-inventory");source.mkdir()
for name in ("ReticulumWakeRouterTests","NativeModelHostTests","CallWakeEnrollmentTests","CallWakeInstallationTests","CallWakeIdentityTests","CallWakeRegistrationTests","CallWakePolicyTests","CallWakeCancellationTests","ModalPageTests","CallWakeTests","VoIPPushDeviceTests"):
    original=Path("../NextRuntimeProbe/Tests")/(name+".swift")
    (source/original.name).write_bytes(original.read_bytes())
for name in ("FamilyCallWakePolicyTests", "FamilyCallWakeOwnerTests"):
    (source/(name+".swift")).write_bytes(Path(name+".swift").read_bytes())
proof=module.verify(json.loads(Path("Results/summary.json").read_text()), json.loads(Path("Results/tests.json").read_text()), source, unit_only=True)
production = [Path("../NextRuntimeProbe/App")/(name+".swift") for name in
    ("NextIncomingCallWakeRouting","NextReticulumWakeRouter","NextCallWakeDispatcher","NextCallWakeQuery","NextNativeModelHost","NextCallWakeContext","NextCallWakeEnrollment","NextCallWakeInstallation","NextCallWakeIdentity","NextCallWakeRegistration","NextCallWakePolicy","NextCallWakeCancellation","NextModalPage","NextWebLoadState","NextVoIPPushDevice","NextPushServices")]
production.extend(Path("../FamilyLive")/(name+".swift") for name in ("FamilyCallWake", "FamilyCallWakePolicy", "FamilyCallWakeOwner", "FamilySystemCalls", "FamilyCallKitDriver", "FamilyCallAudioSession"))
proof["production_sources"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in production}
proof["real_push_registration_performed"]=False
Path("Results/proof.json").write_text(json.dumps(proof,indent=2)+"\n")
print(json.dumps(proof))
PY
