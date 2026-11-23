# Read-only physical iPad checks

This development runner inspects a separately installed preview through Apple's
paired XCTest service. It is not included in either public app. It never targets
regular Family, resets a profile, installs a contact, sends a message, changes a
peer, or taps Save.

The two current checks wait for neXt's native header, inspect its controls, open
TCP connections and close the sheet with Done. They run against the separate
neXt preview identified in `Tests/PreviewChecks.swift`; another bundle identifier
must not be substituted for convenience. A passed menu test does not qualify
radio delivery, calls, notifications or suspended execution.

The workflow's `check_app` selection also offers `family`. That separate variant
inspects only Family Mailbox Test, opens the Guardian password gate and closes
it with Done. It does not enter a password or unlock settings. Its runner must
occupy a different disposable slot from the app being tested. Pass
`--check-app family` to the verifier for those logs; the default inventory is
neXt's two cases. The authenticated artifact includes `device-check-kind.txt`
so the selected variant can be checked before installation. Never interchange
these inventories to make an unrelated result pass.

## Build and sign

Use `build.sh` on a Mac with Xcode and XcodeGen, or dispatch the **Build isolated
iPad device checks** workflow. Confirm the successful run's exact commit and
GitHub artifact digest, then verify the included IPA checksum before signing.
The package deliberately excludes saved data, runtime identities and debug-symbol
bundles. Do not add production credentials or private entitlements to it.

Device installation needs an appropriate existing personal or developer signing
profile. Match its app identifier and team, verify every embedded native binary
and resource seal after signing, and keep the original unsigned artifact.
Never remove a regular app to make a free-signing slot available. If an existing
disposable test slot must be used, take a complete private data backup, retain
its verified original signed package, serialize device operations and restore
that package in a finally path. Stop other device work if restoration fails.

## Run and verify

Pair and trust the device, enable Developer Mode and approve UI Automation on
the device when required. Keep its passcode enabled. Mount Apple's compatible
signed developer image using the paired-device tooling if the test service is
unavailable after a reboot. Do not bypass device authorization.

With the appropriately signed runner installed, use the paired XCTest tool's
`--output-log` option and retain its separate control log. After execution, run:

```sh
python3 ios/DeviceChecks/verify-result.py xctest.log control.log --exit-code 0
```

Pass the tool's actual exit status; `0` above is only an example. A zero tool
exit by itself does not mean that any test passed. The verifier requires one
actual passing record for each source test, a complete suite with no failures,
unexpected failures, skips or uncaught errors, and completion from both the
listener and paired control service. Missing or repeated result counts fail.

Restore any temporarily used test slot before declaring success. Verify the
original saved files, contacts, identity and preferences against the private
backup, and confirm that regular Family and neXt settings are unchanged.
Keep logs, screenshots, backups, certificates and signing material private;
accessibility and device logs can contain conversation or account metadata.

## Verified physical checkpoint

On November 23, 2026, runner source `898a0e2` executed both cases successfully
on the stock iPad. The original Family Mailbox Test package was restored;
regular Family and neXt identity/settings fingerprints matched, every original
test-app saved file matched and no additional saved test files remained.
The stricter result verifier in the following commit also accepted these actual
logs. This establishes read-only UI control on that paired device, not a promise
that future authorization prompts or device services need no owner action.
