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
| Delivery fallback across services | Shared runtime exists | Audit native send selection and automatic fallback coverage |
| Files and photos | Native picker, quality presets, receive/export exist | Physical Files/Photos permission and size-boundary checks |
| Reticulum calls | Present; native audio and call-state tests passed | Actual speaker/headset, interruptions, lock during active call |
| SIP calls | Present; native registration/signaling fixtures passed | Actual two-way audio, lock, account reconnect |
| Native iOS call controls | Present in build 150.1; seven tests per simulator passed | Real CallKit answer/mute/hangup and interruption checks |
| RNode Bluetooth | Present | Physical pairing, LoRa traffic and reconnect; preserve known profile |
| MeshCore Bluetooth | Present | Physical pairing, private messages and reconnect |
| MeshCore adverts | Native controls implemented | Guardian-only local/flood controls pushed in 4674f0f; seven mock-radio authorization tests passed; physical RF check pending |
| Radio batteries | RNode home indicator present; MeshCore home indicator added locally | Native threshold/unknown-reading tests added locally; real readings still need hardware |
| Family location sharing | Present; guardian policy, duration controls | MeshCore recipient-picker fix pushed in 37ca36b; native tests added; background sampling remains platform-limited |
| Last-updated map pin details | Present | Device visual check at multiple zoom levels |
| Offline maps | Verified regional download and automatic selection pushed through d383b21; MBTiles import/remove present | Published pack hash/size/database and disposable import/read/remove passed; automatic multi-pack fallback added locally; physical GPS/download UI pending |
| Rooms and Relay Chat | Reticulum and MeshCore room QR/editor/discovery wired in 58fc411 | Native service/byte-limit tests added; real MeshCore room check pending; App Store exclusion remains |
| Day/night theme | Present | Check keyboard contrast and system bars on phone/tablet |
| Permission checkup | Present | Recheck new call controls and platform-specific explanations |
| Offline mailbox | Present; reconnect tests implemented | iPadOS schedules checks opportunistically, not immediate delivery |
| Push alerts | Opt-in, routes and signed mock-provider tests present | Real APNs needs enrollment, entitlement and deployed provider |
| Updates | Platform-specific distribution | App Store updates ultimately managed by Apple; no Android APK updater on iOS |

## Verification baseline

Source ab234d9: unsigned archive 44341891121 passed; four simulator suites
44341897414 passed after infrastructure retries; both native SIP suites
44341904130 passed. Separate iPad Family Mailbox Test upgraded to 150.1 with
saved state preserved exactly. Regular Family 47.6 remained unchanged.

## Next local work

1. Finish native runs for d383b21 (contact/location, verified downloads, both room services and adverts).
2. Review/test local home battery and automatic multi-region tile fallback patch.
3. Test RNode/MeshCore pairing/reconnect, call interruptions/headsets and map downloads on actual hardware.
4. Automatic fallback is shared with Android; long text above MeshCore's byte budget is excluded and remains a known cross-platform limitation.
5. Real APNs verification still needs eventual enrollment and a deployed provider; no enrollment has been performed.
