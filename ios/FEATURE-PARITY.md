# Family iOS / Android parity audit

Audited 2026-11-20 against the Android assets and shared runtime in this checkout.
“Present” means native wiring exists, not that a physical-device end-to-end test passed.
Regular Family on the iPad is excluded from testing. Apple enrollment remains on hold.

For the separate neXt port, see [neXt iOS completion status](NEXT_FEATURE_PARITY.md).

## Cross-app qualification — November 23, 2026

Family runtime at source `e82803cfa820f90d30b1fce2bf7226b8ec311255`
passed all four iPhone/iPad live and sample-preview jobs in `45127212986`.
The live jobs executed all 48 native cases and the actual guardian/contact,
notification permission, private signed message/background round-trip and
reconnect UI checks. Both iPhone jobs passed on their first attempt. The iPad
live permission check and sample preview startup check needed one unchanged
failed-only retry. Original failure logs and the iPad live recording are
retained; the passing retry does not establish the initial failures' causes.

Both unsigned Family device and App Store archives passed in `45127216492`.
The App Store configuration continues to exclude rooms and Relay Chat; the
GitHub configuration retains them. These simulator/archive checks did not
install either Family package on the physical iPad. Regular Family **47.6**
and separate Family Mailbox Test **353.1** retain their existing setup.
Real suspended internet call/push verification, the physical iPhone matrix,
Apple distribution signing and submission remain pending. Apple enrollment
has not been performed.

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


## neXt iOS messaging follow-up

The reviewed TCP-controls baseline passed both simulators in `44793739771`.
The contact QR change `91937df` passed both native tests, including decoding the
actual displayed code, in `44799411385`. The separate neXt iPad preview upgraded
to 223.1 with identical identity/history and unchanged saved preferences; all
four TCP rows remained saved. Modern CoreDevice restarts reopened the stored
conversation successfully. The older developer-launcher black screen has no
proven product-level cause.

Unread-state change `a647956` passed CI, Security, Scorecard and both native
simulators in `44807183946`. Its private signed-message test also verifies
unread state after restart, mark-read authorization and message previews.
Regular Family is still 47.6 and the separate Family test app is 218.1.

The profile/theme changes are now uploaded and verified by the final native
baseline below. They save the existing Settings controls and display name while
preserving identity/history across genuine simulator restarts. Earlier local
browser checks were preparation, not substitutes for the native results.

## neXt passive client discovery (local verification)

The next local patch connects the released Contacts → Add Contact → Discover
contacts picker to signed Reticulum LXMF client announces. It supports name and
address search, bounded pagination, and a private on-device cache capped at 1,000
clients with 30-day expiry. It excludes the local identity, rejects a destination
that does not match the announcing identity, and does not create contacts or
change saved nicknames when an announce arrives. Only LXMF messaging clients are
included; this does not implement voice, relay, or radio discovery.

The private integration test received a real signed path-response announce over
loopback, while unit checks covered malformed names, identity mismatch, expiry,
restart and bounded queries. The actual released 0.1.20 frontend also searched a
private peer by name, filled the matching address and saved it through an explicit
Add Contact action, with no page errors. No regular device app was involved.
The discovery patch was subsequently uploaded and included in the final native
baseline below; it does not establish physical-radio discovery verification.

## neXt native message alerts

The native preview now has a Message alerts control with an explicit permission
request, a link back to the app's system notification settings, and an explanation
of iOS suspension. It posts a generic notification for unread saved conversations
when the app is not active and iOS still permits it to run. No sender name or
message content is copied into the notification. Tapping the alert routes to its
validated contact address; ordinary web navigation is not replaced by redraws.

Notification eligibility is stored separately from message payloads, so polling
never decodes attachment bytes. Location-only telemetry is silent. Migration
preserves existing unread state without replaying old messages, and permission
setup records a baseline before posting any new alerts. The native policy tests
cover denial, foreground suppression, restart/deduplication, OS failure/retry,
concurrent refreshes, permission races and validated routing.

This is local notification wiring, not APNs or a keep-alive service. It does not
wake a fully suspended process. Production push delivery and physical lock-screen
notification checks remain release gates; no background entitlement or Apple
enrollment is added by this change.


## Completion verification update — 2026-11-20

The combined neXt preview changes passed the iPhone and iPad native messaging
suites in run `44865544249`, including TCP peer edits and restart, signed replies,
contact QR decoding, native attachment export and profile/theme persistence.
Family's unsigned device and App Store archive jobs passed in that run too.

Native neXt message-alert wiring was added in `427f45d`; `cc93547` corrects a
Swift error-state name collision found by Xcode. The corrected device archive
passed and installed as the separate neXt preview build 230.1 on the real iPad.
Before launch, its identity, message database and preferences were byte-identical
to the backup. After the new notification-table migration, both contact records
and all seven saved messages were unchanged. The preview opened with its saved
conversation, visible composer and connected TCP status. Regular Family 47.6
and Family Mailbox Test 218.1 were not modified.

The local suite passed 240 tests with seven optional skips and three subtests.
The new message-alert simulator run `44868343163` is still in progress at this
checkpoint. These local alerts do not wake a fully suspended app. Physical
notification permission/delivery and production APNs remain separate verification
gates, and Apple enrollment remains on hold.

Family Android 0.6.29 is published with signed upgrades and both updater-feed
checks passing. Its Play code 43 was submitted to closed testing; Google quick
checks precede review. This does not make either iOS app an App Store release.


### neXt native RNode work

The next source change adds opt-in Bluetooth LE and Wi-Fi RNode configuration to
neXt's native header, reusing Family's tested transport. It retains the agreed
914.875 MHz / 125 kHz / SF8 / CR4/7 / 17 dBm defaults, saves profiles privately,
keeps radio data alongside the existing identity, and scopes startup/reconnect
and hourly announces to the selected radio. Unconfigured profiles never request
Bluetooth access. Simulator tests reject enabled radio profiles.

It also reuses Family's bounded Bluetooth-wake inbox checks; this is not an
always-running service. A shared lifecycle repair rejects a radio session that
finishes opening after its profile was disabled or replaced. That regression
fails against the previous implementation and passes with the repair. The
previous full local suite passed 252 tests; additional focused checks cover
unchanged-profile saves without restarting pairing. Native compilation, editor
persistence and the real iPad radio test are still required at this checkpoint.
Regular Family remains untouched, and Apple enrollment remains on hold.


### neXt RNode and inbox checkpoint (2026-11-20)

The separate neXt iPad preview now includes RNode Bluetooth LE/Wi-Fi configuration, saved radio settings, radio status/battery, startup/reconnect/hourly radio announces and bounded Bluetooth inbox wake handling. The iPhone and iPad simulator runs each passed 18 native checks, and the device archive passed. Build 235.1 was installed over the separate neXt preview on the stock iPad: its identity, seven messages, two contacts and preferences remained byte-identical; regular Family 47.6 and Family Mailbox Test 218.1 were unchanged. The real-device interface started and retained its saved conversation and TCP connection. Physical RNode transmission from neXt itself still needs verification; Family radio tests are not proof for neXt.

neXt's incoming signed private messages may begin a conversation without automatically adding the sender to its phonebook. Existing conversations can receive replies and unread alerts and survive a restart. Family's guardian-approved contact restrictions are unchanged. A new sender must have a verified LXMF identity; unsigned messages are rejected and telemetry alone does not create a new conversation.

## neXt 0.1.21 integration and remaining native checks

The public neXt release is now **0.1.21 across platforms**, source `21f977d`.
Its publication verification passed in `44881960193`. The signed updater feeds
were fetched and verified for Android, Linux x64/arm64, Windows x64 and macOS
x64/arm64. Play code 26 was submitted for closed-test review; submission does
not mean Google has approved it.

The iOS Messages app now pins that release's frontend and backend wheel by
checksum. Baseline `73e3f8f` passed both native simulator suites and its unsigned
device build in `44881981054`. Subsequent MeshCore integration adds explicit
Bluetooth companion selection, the existing neXt service/settings interface,
own-app Keychain node-password storage and metadata-only native private-message
alerts. Removed radios and already-read messages are excluded from alerts.
These additions still need their final native and physical-radio checks; the
successful earlier Family radio tests do not verify the separate neXt app.

Repeat-fingerprint repair `3ec43a2` uses the bundled Reticulum AES/X25519
providers instead of unavailable iOS Crypto imports. Twelve AES/RFC7748 and
input-rejection tests passed. A separate staged-runtime comparison matched all
26 reference packet payloads, with Crypto/cryptography imports blocked and no
radio transmissions. This verifies fingerprint compatibility, not RF repeat
reception. Encrypted radio identity backup and the remaining cryptography
consumers require separate iOS integration; they are not covered by this repair.

Native run `44887514505` verifies the actual simulator executable signatures
before running real Keychain tests. It builds the host simulator architecture
explicitly because the Python packager cannot consume a combined architecture
name. Run `44888091878` includes the repeat repair. At the time of this entry,
both simulator results are pending; the earlier `3f2a991` unsigned device build
has passed. No check has been skipped to obtain a passing result.

The physical iPad's separate neXt preview remains build **236.1**, with its
identity, two contacts, eight messages and saved peers preserved. Regular
Family **47.6** and Family Mailbox Test **218.1** have not been updated. neXt SIP
calling, Reticulum voice, maps/location, complete native permissions/background
behavior and a physical iPhone verification matrix remain unfinished. Apple
enrollment and real APNs verification remain on hold.


## Verified checkpoint — 2026-11-21

neXt source `cefa5c7` passed **34 actual source test cases on each simulator** in
`44899096919`. This includes the complete released Messages interface, signed
replies, attachments, saved profile/theme and restart assertions. Native SIP
registration and authenticated logout run through the actual compiled app
adapter against a temporary private registrar. This is registration verification,
not a claim that neXt's user-facing SIP calls or CallKit/audio are complete.

The result verifier checks Apple's actual `result` field and requires every
source test case to have a passing record. Run `44896028153` is invalid as test
proof: an empty-array shell error skipped the test invocation despite a green
workflow. Its package was held back and never installed. Later genuine native
results supersede it; no assertion was removed to obtain those results.

Privacy-only source `525aaa0` passed the neXt device build and both Family device
and App Store archives in `44900079229`. Downloaded archives contain the exact
privacy manifests and upstream SIP notices. neXt app code at that source is
identical to the fully tested `cefa5c7` baseline. The Family App Store archive
continues to compile with rooms and Relay Chat excluded. No Apple enrollment or
App Store submission has occurred.

Subsequent neXt interface-preference source `fb281f9` passed the full local suite
(330 passed, seven optional skips, three subtests) and its unsigned device build.
Five new native tests cover private preference-file persistence, multi-window
merging, invalid/secret-key rejection, identity isolation and corrupt-file
preservation. A browser execution test additionally checks origin isolation,
ordered acknowledgements and rollback after consecutive failed writes. Its
both-simulator run `44901168607` passed all 38 native cases on each device
and the complete iPhone UI flow. The iPad UI failed because the test's trailing-edge
caret tap left the original display name unchanged. The native Select All repair
keeps the cleared-field, exact replacement, saved-name, theme and restart assertions.
The next run also includes the actual WebKit persistence/child-frame isolation case.

The physical iPad upgraded only the separate neXt preview from **236.1** to
**264.1**. Regular Family **47.6** and Family Mailbox Test **218.1** stayed unchanged. The new consistent backup
contains 10,549 files, a verified identity, eight messages and two contacts. A
live-cache copy failed on an expired announce and was replaced by a complete
copy after stopping only the separate neXt preview. No regular Family data has
been changed. Identity/history bytes and saved preferences matched exactly after
installation. A real signed TCP message with a file arrived; the iPad returned a
signed quoted reply with byte-identical file contents. Both messages survived an
actual app restart, all original message/contact rows remained, and the private
runtime capability rotated. The physical test used Chicago and a temporary
private counterpart; it does not prove physical RMAP availability or observed OS
notifications.


## Native permission and WebKit checkpoint — 2026-11-21

Source `4a24b00` compiled its unsigned device package and passed the complete
iPhone run in `44903565571`: 40 native cases plus two UI cases. The iPad passed
all 40 native cases, including the actual WebKit/native-file round trip on a new
loopback port and rejection of a child-frame write. Its setup permission-checkup
UI case also passed. The complete iPad Messages UI flow still fails at the test's
profile-name replacement; the exact replacement and restart checks remain
required before that candidate replaces the working physical preview.

The permission checkup is available from the setup form and native Message
alerts. It shows one explanation at a time, separates authorization from the
actual lock-screen notification setting, and makes optional requests explicit.
The Bluetooth permission request never scans or connects. The guide does not
request entire-photo-library access and does not promise an always-running iOS
service. Native SIP calling and fully suspended internet delivery remain separate
unfinished work, regardless of permission status.

The initial WebKit integration test incorrectly selected the Void overload of
`callAsyncJavaScript`; `717164c` explicitly waits for its completion result. The
corrected native round trip and child-frame isolation passed on both simulators.
The iPad's profile-test caret/selection failure is distinct from that repaired
harness issue. Its existing synthetic result is being inspected using a workflow
restricted to run `44902819390` and immutable source `d970a40`; no physical-device
recording or regular Family data is part of that diagnostic upload.

A fresh Play Console check showed Family **0.6.29 / code 43 serving** on the
closed track, and neXt **0.1.21 / code 26 in review**. Each app had ten opted-in
testers, below the twelve required continuously for fourteen days before
production access. These are point-in-time observations, not an approved
production release. Apple enrollment remains on hold.


## Family call-wake admission foundation — November 23, 2026

The separate native approval reader and encrypted-intent admission passed all
89 focused native cases on each simulator at `57b0689`. Those results include
current individual contact permissions, public messaging/voice key binding,
identity-file restrictions, signed provider fixtures, expiry and revocation.
Both unsigned Family archives passed. These are prerequisites, not a claim
that Family currently receives suspended calls through Apple.

The next integration adds a native-only, one-use incoming window, limited to
one selected voice address for at most 30 seconds. It can be armed before
CPython starts, avoiding a cold-start signaling race. The embedded Python
module can consume that window, but exposes no way to arm it. JSON actions
cannot enable it. Contact approval is still checked before consumption, and
outgoing background calling remains blocked. Foreground calls and Android's
existing call gate keep their previous behavior.

The clock includes device sleep on Apple platforms, following Apple's
[continuous-clock documentation](https://developer.apple.com/documentation/kernel/1646199-mach_continuous_time).
Native host tests cover expiry, stale cancellation, wrong caller, parallel
consumption, clock failure and the real embedded-Python boundary. The test clock
override is absent from production objects. The guardian opt-in, PushKit owner
and CallKit transport handoff still need to be wired before this window is
armed by an actual app. No installed personal preview has enabled Apple push.
