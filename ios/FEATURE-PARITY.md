# Family iOS / Android parity audit

Audited 2026-11-18 against the Android assets and shared runtime in this checkout.
“Present” means native wiring exists, not that a physical-device end-to-end test passed.
Regular Family on the iPad is excluded from testing. Apple enrollment remains on hold.

| Area | iOS status | Remaining verification or work |
|---|---|---|
| Guardian setup, nickname, approved contacts | Present | Review guardian password visibility and policy coverage against Android |
| Contact QR camera and image import | Present for new contacts | Existing-contact import and preservation tests pushed in 37ca36b; native iPhone suite passed |
| Existing contact service discovery | Present for LXMF in 37ca36b | Native iPhone suite passed; MeshCore saved-contact picker still separate |
| Contact photos | Present; actual iPad save/relaunch passed | None identified in this audit |
| Multiple editable TCP peers | Present | Physical network-change/reconnect matrix needs repetition |
| Reticulum messages and signed identity | Present; simulator live suites passed | Repeat real-peer device tests with new build |
| Message connection selection and fallback | Native Automatic / Reticulum / MeshCore chooser implemented locally; shared Automatic fallback retained | Six native policy tests and a private chooser UI assertion await Xcode; 23 backend fallback/validation tests passed |
| Files and photos | Native picker, quality presets, receive/export exist | Physical Files/Photos permission and size-boundary checks |
| Reticulum calls | Present; native audio and call-state tests passed | Actual speaker/headset, interruptions, lock during active call |
| SIP calls | Present; native registration/signaling fixtures passed | Actual two-way audio, lock, account reconnect |
| Native iOS call controls and route chooser | Present in build 181.1; Automatic/manual chooser and seven system-call tests passed on both simulators | Real CallKit answer/mute/hangup, interruption and route-quality checks |
| RNode Bluetooth | Present | Physical pairing, LoRa traffic and reconnect; preserve known profile |
| MeshCore Bluetooth | Present | Physical pairing, private messages and reconnect |
| MeshCore adverts | Native controls implemented | Guardian-only local/flood controls pushed in 4674f0f; seven mock-radio authorization tests passed; physical RF check pending |
| Radio batteries | RNode and MeshCore home indicators present in build 181.1 | Native threshold/unknown-reading tests passed on both simulators; real readings still need hardware |
| Family location sharing | Guardian policy and durations present; optional locked-screen session implemented locally | 143 local tests passed; ten native session tests await Xcode; physical GPS/background/expiry checks remain |
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

## Next local work

1. Review/run Xcode for optional locked-screen location sharing, then verify actual permission, expiry and battery behavior on the separate app.
2. Test RNode/MeshCore pairing/reconnect, call interruptions/headsets and map downloads on actual hardware.
3. Bounded Bluetooth background inbox refresh passed eight native lifecycle tests on both simulators; paired-radio/locked-device notification verification remains pending.
4. Long text above MeshCore's byte budget is excluded from Automatic fallback and remains a known cross-platform limitation.
5. Real APNs verification still needs eventual enrollment and a deployed provider; offline mailbox background checks remain opportunistic.
