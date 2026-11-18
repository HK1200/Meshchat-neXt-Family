# Family iOS / Android parity audit

Audited 2026-11-18 against the Android assets and shared runtime in this checkout.
“Present” means native wiring exists, not that a physical-device end-to-end test passed.
Regular Family on the iPad is excluded from testing. Apple enrollment remains on hold.

| Area | iOS status | Remaining verification or work |
|---|---|---|
| Guardian setup, nickname, approved contacts | Present | Review guardian password visibility and policy coverage against Android |
| Contact QR camera and image import | Present for new contacts | Existing-contact import added locally; native build pending |
| Existing contact service discovery | Added locally for LXMF | Native build pending; MeshCore saved-contact picker still separate |
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
| MeshCore adverts | Native control not found | Verify shared transport command support before adding controls |
| Radio batteries | MeshCore voltage present; RNode status available | Audit home-screen parity and real readings |
| Family location sharing | Present; guardian policy, duration controls | Audit MeshCore recipient eligibility and background sampling parity |
| Last-updated map pin details | Present | Device visual check at multiple zoom levels |
| Offline maps | MBTiles import/remove and bundled PNW overview present | Android guided regional detail download is missing |
| Rooms and Relay Chat | Native Reticulum room editor/chat present | MeshCore room UI parity incomplete; App Store exclusion must remain |
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

1. Existing-contact QR/discovery import with merge-preservation regression tests.
2. Verified regional map downloader, matching Android’s source, size and SHA-256.
3. Audit location transport eligibility and automatic delivery fallback.
4. MeshCore adverts and room controls, gated by distribution policy.
5. Real hardware checks and eventual APNs verification remain explicitly separate.
