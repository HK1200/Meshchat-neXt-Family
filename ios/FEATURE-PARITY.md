# Family iOS / Android parity audit

Audited 2026-11-20 against the Android assets and shared runtime in this checkout.
“Present” means native wiring exists, not that a physical-device end-to-end test passed.
Regular Family on the iPad is excluded from testing. Apple enrollment remains on hold.

| Area | iOS status | Remaining verification or work |
|---|---|---|
| Guardian setup, nickname, approved contacts | Present | Setup/unlock visibility checks passed on both native simulators |
| Contact QR camera and image import | Present for new contacts | Existing-contact import and preservation tests pushed in 37ca36b; native iPhone suite passed |
| Existing contact service discovery | Present for LXMF in 37ca36b | LXMF and MeshCore editor pickers passed both native simulators, including unsaved-draft preservation |
| Contact photos | Present; actual iPad save/relaunch passed | None identified in this audit |
| Multiple editable TCP peers | Present | Physical network-change/reconnect matrix needs repetition |
| Reticulum messages and signed identity | Present; simulator live suites passed | Repeat real-peer device tests with new build |
| Message connection selection and fallback | Native Automatic / Reticulum / MeshCore chooser present; shared Automatic fallback retained | Integrated simulator suites passed in 44631048898; physical manual/fallback matrix remains |
| Files and photos | Native picker, quality presets, receive/export exist | Physical Files/Photos permission and size-boundary checks |
| Reticulum calls | Present; native audio and call-state tests passed | Actual speaker/headset, interruptions, lock during active call |
| SIP calls | Present; native registration/signaling fixtures passed | Separate iPad ↔ 9 two-way speech passed, including calling the locked 9; iPad locked incoming, headset/interruption and reconnect matrix remain |
| Native iOS call controls and route chooser | Present in build 181.1; Automatic/manual chooser and seven system-call tests passed on both simulators | Real CallKit answer/mute/hangup, interruption and route-quality checks |
| RNode Bluetooth | Present | Separate iPad pairing and bidirectional LoRa passed, including locked-screen notification; preserve known profile |
| MeshCore Bluetooth | Present | Fairside J connected; outgoing receipt and incoming locked-screen notification passed; reconnect observed |
| MeshCore adverts | Native controls implemented | Guardian-only local/flood controls pushed in 4674f0f; seven mock-radio authorization tests passed; physical RF check pending |
| Radio batteries | RNode and MeshCore home indicators present in build 181.1 | Native threshold/unknown-reading tests passed on both simulators; real readings still need hardware |
| Family location sharing | Guardian policy and durations present; optional locked-screen session implemented | Integrated native tests passed; fresh locked-screen updates and Stop sharing verified on the separate iPad; physical expiry/movement matrix remains |
| Last-updated map pin details | Present | Device visual check at multiple zoom levels |
| Offline maps | Verified regional download and automatic selection pushed through d383b21; MBTiles import/remove present | Published pack hash/size/database and disposable import/read/remove passed; automatic multi-pack fallback passed local/native checks and is in build 181.1; physical GPS/download UI pending |
| Rooms and Relay Chat | Reticulum and MeshCore room QR/editor/discovery wired in 58fc411 | Native service/byte-limit tests added; real MeshCore room check pending; App Store exclusion remains |
| Day/night theme | Present | Check keyboard contrast and system bars on phone/tablet |
| Permission checkup | Present | Recheck new call controls and platform-specific explanations |
| Offline mailbox | Present; reconnect tests implemented | iPadOS schedules checks opportunistically, not immediate delivery |
| Push alerts | Opt-in, routes and signed mock-provider tests present | Real APNs needs enrollment, entitlement and deployed provider |
| Updates | Platform-specific distribution | App Store updates ultimately managed by Apple; no Android APK updater on iOS |

## Verification baseline

Runtime source bec9ebf passed all four simulator jobs in 44458839083, including
explicit contact keyboard dismissal, message round trips, 35 native tests per live
simulator (eight Bluetooth wake lifecycle cases), and private SIP signaling.
Final archive source 84b4564 differs only in the required local timer privacy
manifest entry. Its device archive 44459103558 and App Store archive 44459108090
passed; the final packaged manifest was inspected.

Separate iPad Family Mailbox Test upgraded to 195.1 with four contacts, eight
messages, settings and permanent Reticulum identity files unchanged. Launch and
process-relaunch checks passed. Regular Family 47.6 and neXt preview 82.1 stayed
unchanged. No Apple enrollment has been performed.

The subsequent local background-location work passed 143 local tests with four
skips; its ten new native session tests still require Xcode. The feature is off by
default, guardian-controlled, and uses a foreground-started When In Use session
with the system location indicator, rather than Always-location authorization.

## Latest verified baseline

Family 0.6.28 integration source `675f166` passed all four iPhone/iPad live and
preview jobs in `44631048898`; the isolated iPhone preview passed on an unchanged
retry. The device archive `44631059571` and unsigned App Store archive
`44631054550` passed. Main `279ad34` adds only the host-codec CI setup repair;
CI, CodeQL and Scorecard passed. Regular Family on the physical iPad was not
updated or cleared. Apple enrollment remains on hold.

The contact-editor follow-up and two test repairs passed all four simulator jobs in
`44714253572`. The subsequent real TCP reconnect repair `46a7b1b` removes retired
LXMF links from both caches while preserving other routes and callback-created
replacements. Its regression fails before the repair and passes afterward. CI
`44716801847` passed 159 tests with eight skips and three subtests. Security and
Scorecard passed. Unsigned device and App Store archives `44716802255` passed;
both downloaded build 213.1 archives contain the exact repaired runtime.

Final simulator run `44716835633` passed both live suites with the full approved
message UI round trip and 48 native tests on each device. The iPhone preview
startup check passed on one unchanged fresh-runner retry; all four jobs are now
green. Regular Family was not updated or cleared, and Apple enrollment remains
on hold. neXt’s 0.1.20 frontend passed signed-reply UI tests on iPhone and iPad in
`44710941151`.

The neXt TCP peer/settings work was reviewed and pushed as `e8018e0`. Its
initial iPhone control/restart/signed-reply test passed and the unsigned device
build passed. The iPad failure led to retained result/video diagnostics in
`7313aaa`; `4954d98` changes the test's full-height form swipes to short in-form
gestures after a recording showed the sheet being pulled downward. The final
both-device native result remains pending. These checks do not establish parity
for neXt calling, radios, maps or attachments.

Family's independent TCP connection attempts were reviewed and pushed as
`00470f6`. The two new regressions fail before and pass after the repair; the
full pinned suite passed 180 tests, with eight optional skips and three subtests.
CI, Security and Scorecard passed. Both unsigned archives in `44785472955`
passed; build 218.1 contains the exact reviewed backend. All four Family
simulator jobs in `44785477485` passed, including message UI round trips and 48
native checks on each live simulator. The GitHub and Play Android variants
compiled, and both APKs contain backend bytecode matching the reviewed source.

The separate iPad test app upgraded in place from 213.1 to 218.1. Its seven
contacts, fifteen messages, full saved state and permanent identity were
byte-identical immediately after installation; all preferences were unchanged.
It launched successfully and its signed startup announce reached a temporary
listener at its unchanged saved private TCP endpoint. The listener was then
stopped. Regular Family remains 47.6; no Apple enrollment has been performed.

## Next local work

1. Complete neXt peer-control and persistence checks on both simulators and the separate iPad preview; then continue the remaining service integrations and physical location expiry/movement and battery checks.
2. Test RNode/MeshCore pairing/reconnect, call interruptions/headsets and map downloads on actual hardware.
3. Bounded Bluetooth wake lifecycle checks passed, and actual RNode/MeshCore locked notifications appeared. Repeat with long idle intervals and connection loss when hardware is free.
4. Long text above MeshCore's byte budget is excluded from Automatic fallback and remains a known cross-platform limitation.
5. Real APNs verification still needs eventual enrollment and a deployed provider; offline mailbox background checks remain opportunistic.
