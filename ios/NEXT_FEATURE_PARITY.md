# neXt iOS completion status

neXt for iPhone and iPad is a development preview. Reticulum messaging works in
the released neXt interface, including signed replies and attachments. Native
SIP calling and optional mailbox receiving are integrated and under verification.
Reticulum voice, offline maps, location and Relay Chat are integrated and
undergoing native/device qualification. Remaining desktop services, suspended
alerts and release verification still need work before a complete neXt release. Family has its own [parity audit](FEATURE-PARITY.md).

The latest fully verified separate iPad build is **390.1**, exact source
`33096576029c398068cf562babd9b35f30afcdff`, pinned to public **0.1.27**.
GitHub run `45148207507` passed all **115 required checks per simulator**
(109 native and six UI cases) on their first attempts, plus both unsigned
archives. The earlier compact-header candidate's iPhone contact-QR navigation
failure was retained and that package was never installed. The same QR flow
passed in the final both-device run without weakening its assertions.

The same-key physical upgrade from 389.1 preserved all **1,511 current
non-cache support files**, twelve messages, two contacts, identity, native
preferences and four peers before first launch. Counts reflect the files
present at this upgrade, not expired runtime caches from earlier builds.

On the actual iPad's build 390.1, an original signed message with a
**75,000-byte attachment** and photo survived a distinct process restart and
arrived once with exact bytes. The previous build 389.1 also passed standard
RNCP send, fetch and approved reverse reception with **2 MiB** files and
byte-identical downloads. Explicit removal affected only the synthetic received
files. Its clean private TCP test queued messages during **twelve connection
outages**: every original identifier was delivered once, every signed
echo returned, and no message was manually submitted again. The counterpart used
the byte-verified recovery already in public neXt 0.1.27 from startup.

An initial bare-SDK receiver stalled in its own known Sending/no-destination
state despite an active link. Receiver-side tracing captured that state;
enabling the existing released recovery only in that disposable receiver
unblocked its reply without changing the iPad. That diagnostic run and its
original failures are retained separately from the clean twelve-outage result.
The permanent regression now tests a raw-SDK first-link exchange and three
repeated outages with the released counterpart's recovery; ordinary protocol
interoperability coverage remains in place.

Original contacts and peers were restored. A screenshot confirmed the ordinary
conversation, composer and compact native header rendered after all tests.
Both Family apps retained byte-identical state, identity and native preferences.
These are authenticated private LAN/API tests, not physical Wi-Fi switching,
public-provider reliability, picker/share-sheet gestures or locked-screen proof.
Fully suspended internet alerts, physical iPhone behavior and the remaining
desktop services are still not qualified by these results.

This checkpoint is dated November 23, 2026. “Integrated” means the code is wired
into the app; physical verification is stated separately.

The next call-wake development step now has a native admission router: it
validates the provider's encrypted, signed payload, persists a bounded replay
journal in the app's own Keychain, rejects expired or revoked callers, and
matches only that approved voice identity to the pending CallKit UUID. All
140 native checks passed on each simulator in run `45175698519` (UI was
intentionally excluded). This does not register PushKit or deploy a provider;
explicit enrollment, sender integration, cancellation lookup and genuine APNs
and physical-device qualification remain required before suspended call alerts
can be described as reliable. The shared-runtime coordinator now also offers a
15-second call-wake wait that releases a cancelled or timed-out caller without
cancelling or reinitializing CPython. Five added native checks cover pending, ready, failed and pre-cancelled
startup; all 145 native cases passed on each simulator in run `45177832745`
(UI was intentionally excluded). This method is a dispatcher prerequisite;
it does not register PushKit or make a suspended-call delivery claim.

## Features and remaining work

| Feature | Current implementation and verification | Remaining work |
|---|---|---|
| Reticulum direct messages | Real signed exchanges on the iPad and both simulators; conversations survive closing and reopening | Network-loss, extended idle and physical iPhone matrix |
| Quoted replies | Signed replies preserve their referenced message; verified through the physical iPad backend | Repeat ordinary UI interaction on a physical iPhone |
| Files and photos | The physical iPad received and returned signed file/photo payloads with matching bytes; simulator file export passes | Actual iPad signed near-budget 9.9 MB round trip passed with exact bytes; byte-budget and 32-item limits were rejected before queuing. Real camera/Photos/Files picker and share-sheet checks, interrupted transfers and long-radio delivery remain |
| Voice notes | Development source now streams recorded PCM through the upstream Opus/Ogg writer, preserves standard Codec2/Opus LXMF fields, and serves bounded WAV previews for iOS versions without Ogg playback. Private host tests verify signed audio-only delivery, playback, byte limits, duration, tone energy and corrupt-input handling. Inline WAV previews have an 8 MB decoded-PCM bound; original encoded bytes remain available from the authenticated raw attachment endpoint | Bundled Ogg/Opus encode/decode assertions passed in 83 native tests on both simulators. The actual iPad encoded and decoded a signed synthetic tone; physical microphone recording, audible playback controls and export remain required |
| Contacts and conversation history | Saved contacts, rename/removal, local conversation labels, new incoming conversations and unread state are integrated; in-place iPad upgrade preserved existing data | Development source adds native camera/QR-image/paste review and explicit Reticulum contact saving. Key-binding, atomic-failure, duplicate, blocked-identity and real private HTTP tests pass; native paste/review passed on both simulators; physical camera/editor/discovery checks remain |
| Local Reticulum peer bans | Development source wires the released Blocked destinations API to durable verified-identity aliases, clears only the banished contact/history, rejects messages before alerts, cancels private sharing and blocks calls. Private signed-packet tests prove blocking, cold restart and unblocking; a pathfinding race test proves a pending message cannot escape after the ban | Both complete simulator runs passed. On the actual iPad, a private signed packet received a transport receipt while blocked but never entered the inbox; after unblocking, a fresh signed message arrived without replaying the blocked packet. The original contacts, peer settings and block list were restored. Physical button interaction and optional transport-level blackhole management remain |
| Conversation organization | Durable folders, pinning, moving, folder import/export, Unicode names and name/unread/failed/attachment filters are wired to the real interface in development source. Private HTTP tests prove restart and identity preservation, atomic failed imports and idempotent reimports. The archived interface passed create/pin/move/reload at desktop and phone browser sizes | Both full simulator UI runs passed; the actual iPad backend passed pin/move/export/import and process restart. Physical editor gestures still need review |
| Local conversation deletion | Individual and selected-history removal now fence late delivery callbacks, clear pins/folder assignments atomically and preserve contacts and identity. A real private signed exchange passes before deletion and a new signed message reopens the chat afterward; browser confirmation/removal passes at both sizes | Both full simulator deletion/reply cases passed. Actual iPad backend deletion preserved the contact, fenced old messages and received a fresh signed reply; physical confirmation gestures still need review |
| Own contact QR | Native scannable LXMF card and sharing; simulator decodes the displayed QR. Development source also adds a Family-compatible public card with nickname and optional voice address | Both simulator QR checks pass. Actual iPad build 337.1 card was parsed with Family's importer and its identity/LXMF bindings verified; physical camera sharing between apps remains |
| Client discovery | Signed messaging-client announces, name/address filtering and bounded local cache are integrated | Physical discovery picker and additional service identities |
| Nomad browser | Development source uses the released NomadNet request handlers over the existing Reticulum identity and connections, with signed discovery, bookmarks, manual/private browsing and bounded local page archives. Private real-link tests verify page and 1 MiB file reception, explicit identification consent and private browsing without identification or automatic archiving. Archive exports preserve selected pages, cancel cleanly and do not accumulate file descriptors | The native frame allow rule and public-static CORS/CSP repair retain private API isolation. Full simulator qualification exposed a second WebKit cache bug: shared modules loaded by the shell were reused without opaque-origin CORS headers. Public static responses now vary by Origin, including initial and cache-validated 304 responses. A local WebKit run reproduces the failure before the fix and passes visible signed page loading, exact file download and warm reload afterward; both full simulator reruns are still required. Real private peer disable/re-enable also passes after retiring only that interface’s service links and paths. Physical browser, picker/export gestures, interruptions and long-radio transfers remain; local page hosting and crawling are not yet implemented |
| Individual TCP peers | Four editable peers, independent toggles and saved settings; native controls/restart tests and physical saved-state checks pass | Repeat real Wi-Fi changes, offline recovery and route failover; connected sockets alone do not prove message traffic |
| RNode | Native editor, shared Bluetooth transport, saved settings, batteries and bounded radio wake handling are integrated | Actual neXt pairing, LoRa exchange, locked delivery and radio power-cycle checks |
| MeshCore | Released service/fleet routes, Bluetooth bridge, own-app Keychain passwords and native DM alert routing are integrated | Physical neXt DMs, channels, rooms, node administration, reconnect and repeat reporting |
| Profile and appearance | Saved display name/theme, private web preferences and native theme propagation are implemented | Both simulator profile-edit/restart regressions pass; verify physical editing and all saved web choices |
| Message notifications | Generic private notifications and native permission controls are integrated | Physical neXt notification delivery/navigation; fully suspended internet delivery needs the mailbox/push integration |
| Permission checkup | Setup and Settings paths are implemented; iPhone full flow and iPad setup flow pass without requesting optional access | Continue coverage as calling/location are wired; physical OS permission prompts |
| SIP | Native Keychain accounts, registration, CallKit and audio controls are integrated. Both native simulator suites passed; physical iPad foreground calls, answering, test-tone output, bidirectional RTP and clean ending/logout passed | Actual iPad authenticated registration, clean logout and reconnect from Keychain passed on the new build. Locked incoming alert previously failed. Complete VoIP push/wake integration and physical phone, speech, route and interruption tests |
| Reticulum voice | Native CallKit controls, AVAudioEngine PCM, existing neXt telephone actions, contact identities, profiles and duplex/PTT are integrated; codec round trips pass on both simulators | Both simulators and strict encrypted-media tests pass. On the actual iPad, both call directions connect, native capture/receive frames flow and remote profile changes negotiate 16/32/48/64 without stopping frame flow. Physical speech quality, interruptions, echo and locked incoming calls remain unqualified |
| Maps | The released map backend is integrated: offline tiles, validated imports, selection/removal, drawings, overlays and map-data catalogs. Private HTTP tests prove signed discovery/catalog transfer, exact file hashes, imports above the message-size limit and preservation across invalid uploads and restarts | Actual iPad backend import, 50 exact tile reads, malformed-input rejection and restoration passed. Visual rendering, download/share pickers and regional downloads remain unqualified |
| Location and telemetry | Actual released telemetry routes, signed location exchange, Family frames, silent map updates, saved location-source settings and fresh outgoing fixes are integrated. Private tests prove both message directions, restart persistence, sender attribution and cancellation when sharing is disabled during pathfinding | Both simulators passed actual native GPS → signed private LXMF → verified receipt → chat Stop. Physical permission, lock/expiry and MeshCore background sharing remain unqualified |
| Relay Chat | Actual released RRC services, signed discovery, public/password rooms, hub receipts and automatic rejoining are integrated. Private real-link tests pass both directions against the unmodified desktop hub; keys remain encrypted and rooms/history survive restart | Actual iPad backend passed bidirectional open/password-room messages, hub receipts and saved-key rejoin against the standard desktop hub. Native room UI, mentions and prolonged network-loss recovery remain |
| RNCP file transfers | Development source connects the released RNCP send/fetch/listener contracts, streaming Files imports and native Share/Save exports. Private standard-engine tests prove send, fetch and approved reverse receive with exact bytes. Sender identities, path confinement, size/disk bounds, cancellation before saving and shutdown are tested. Chat attachment limits are unchanged | A physical 2 MiB send exposed premature completion after the first resource segment. The development repair now waits for the standard final callback, passes a paced real three-segment exchange and preserves cancellation. The pinned iOS backport passed actual iPad send/fetch/approved reverse-receive checks with 2 MiB files and exact-byte downloads on builds 383.1 and 384.1. The separate receiver repair also prevents later segments from reserving the same file repeatedly; cancellation and link closure release the reservation. Native export-policy checks, picker/share gestures, long-radio transfers and suspension/reconnect remain unqualified. The listener is off at startup and remote fetching exposes only explicitly imported shared files |
| RNSh remote terminals | Development source connects the released session controls to the standard encrypted RNSh protocol, using the app identity and interfaces. Private standard-listener tests prove authentication, ordered multi-packet Unicode input/output, resize, received exit status, cancellation and history preservation without replaying commands. Local subprocesses and command listeners are not available on iOS; the page explains this | Native page and actual iPad qualification remain required. Fully suspended terminal sessions are not qualified. The unmodified upstream test listener currently reports raw process exit status incorrectly; the client preserves the status actually received |
| Reticulum diagnostics | Local RNStatus, RNPath tables/rates, interface statistics and saved interface metadata are wired to the actual desktop handlers. Conversation path snapshots and explicit path request/drop controls use the released HTTP contracts. Fifty-three tests against the checksum-pinned iOS backend verify filtering, bounds, blocked requests, read-only GETs, cancellation, truthful radio battery state and the conversation header’s explicit path request/drop/wait actions | Both simulators passed all 98 native/UI checks. Actual iPad build 358.1 passed read-only status/path/interface checks, local zero-hop lookup and rejection of five invalid or transmitting GETs. Development source now also returns read-only route traces with unknown intermediate hops explicitly labelled; it does not broadcast when the page refreshes. Development source also connects RNProbe to standard bounded encrypted packets and receipt proofs, with Stop cancellation and contact-block checks; two private loopback probes passed real standard-RNS delivery proofs. The local transport-blackhole snapshot now uses the standard Reticulum getter through the released read-only endpoint; the diagnostics suite passed 54 private HTTP checks, including this snapshot without transmissions, list fetching or settings changes. Remote management and the remaining tool services still need integration; bundled menus do not qualify them |
| Offline mailbox and push | Optional native relay-address editor and periodic receiving while running are integrated. Real encrypted relay tests prove failed writes retain messages and recovery saves once. Explicitly opted-in manual/Automatic outbound propagation now passes a real offline-recipient/file test; relay acceptance is shown as Sent | Verify the native editor; qualify opted-in outbound propagation, then qualify the new native recipient-route editor and signed sender hints. Native receiving-side enrollment, token rotation, explicit sender approvals and alert-tap retrieval are integrated in development source and await Xcode qualification. Personal-signed previews leave Apple enrollment disabled. Real suspended APNs delivery needs Apple signing entitlements, a deployed provider and device tests |
| Recovery and distribution | Unsigned arm64 device packages build; same-account personal upgrades preserve the separate preview | Finish identity/settings backup and restore paths, release configuration, signing, TestFlight and store listing/review |

## Native location follow-up under qualification

The separate native Location sharing panel adds explicit Reticulum recipients,
15-minute/one-hour/until-stopped sessions, and a locked-screen option off by
default. It uses When In Use permission and the visible iOS location indicator;
no Always permission is requested. Foreground-only sessions pause when locked.
Fixed-duration sessions retain their original deadline through delayed requests
and restarts. Cold starts do not activate GPS; Resume must occur in the foreground.
Independent native consent revisions prevent a failed backend settings write
from restoring a stopped session. Removing a recipient or disabling Browser GPS
revokes its session, including a send still finding a path. Live updates use
standard private LXMF telemetry without an offline-mailbox copy. They send no
more often than once a minute while moving and every five minutes when still.
The released chat controls now follow the native Reticulum sessions, including
Stop all and reopening the page. Ordinary chat starts remain foreground-only;
locked-screen sharing needs an explicit setting for that recipient. Manual coordinates and the existing MeshCore foreground controls remain intact.
Development source also offers saved MeshCore users with existing private-share
permission in the native panel. Each session binds the full companion identity,
full user key and current policy revision. Original SDK policy checks remain,
with additional native consent checks after the Bluetooth write lock and in
its final native-send thread. Stops, expiry, native permission loss and changed
radio identity cannot be bypassed by a delayed write. Turning private sharing
off and back on requires a fresh native Start. The existing chat/global Stop
controls follow these native sessions. Xcode and real-radio locked sharing for
this extension remain required; these are not yet completed device results.
Host regressions and both full simulator runs pass. Each simulator executed all
98 required cases (92 native and six interface tests), including real native GPS,
signed telemetry receipt, chat Stop and contact-code paste/review. The unsigned
device archive passed in the same exact-source run, `45006778485`, at `33f1e81`.
Physical GPS/lock/expiry verification remains required; this is not a public
release or a completed physical location test.

## Verified checkpoints

On November 21, 2026, the separate physical neXt preview upgraded from build
299.1 to diagnostic build **331.1**, using its existing signing key and device
profile. Before first launch, all **2,861 non-cache support files**, native
preferences, all 12 messages, both contacts and the Reticulum identity were
byte-identical. The four saved TCP peers were retained.

The actual iPad then exchanged signed text, file, photo and synthetic Opus voice
content with a private LAN receiver. File and photo bytes matched exactly; the
native codec produced standard Ogg/Opus and decoded it to the expected waveform.
After terminating and relaunching the app, the records and attachment bytes
remained intact. Folder creation, pin/move, export/import and deletion were
exercised through the authenticated backend. Deleting only the synthetic chat
preserved its contact, rejected its old records and allowed a fresh signed reply.
Temporary contacts, folders and peers were removed afterward. These are actual
device/backend checks, not manual camera, microphone or share-sheet UI checks.

An early test retry timed out because its API-added LAN peer was temporary;
relaunch correctly restored the four native saved peers. Reattaching the private
fixture allowed the complete test to pass. No app routing change was made for
that fixture issue.

Build 331.1 is **not public-release qualified**. Its runtime-identical test source initially
encountered an XCTest iPad relaunch failure without a retained app crash report. An unchanged fresh-runner retry passed all 86 required cases on both
simulators in run `44986353408`. The Family-compatible contact-card follow-up is undergoing its own
native checks and is not installed on the iPad yet.

Regular Family 47.6 and Family Mailbox Test 218.1 were not replaced. Family's
successful locked-screen radio and location tests do not qualify neXt's separate
service integrations.

The [743e8aa native run](https://github.com/HK1200/Meshchat-neXt-Family/actions/runs/44954351406)
passed on both iPhone and iPad: 66 native cases and two real Messages UI cases
per simulator. The unsigned device archive also passed. The harness checks
executed cases against the current source and rejects missing, failed or skipped
required tests. Native and UI phases run separately with a clean simulator
restart between them; the signed-reply, peer-edit and persistence assertions
remain required. This archive has not yet replaced the physical preview.

The Reticulum voice integration uses the existing app identity, real LXST links,
CallKit and AVAudioEngine. Its private CI fixture rejects an unapproved caller,
then completes calls in both directions after explicit approval. It checks
settled audio through medium, ultra-low, very-low and low profiles, confirms the
actual negotiated profile at both ends, changes quality during the call and
hangs up cleanly. Twelve bidirectional media checks pass. A silent negative
control must fail the same proof, so comfort noise cannot qualify audio.

The native codec test covers three Opus profiles and all seven bundled Codec2
modes. The bridge includes echo-processing status, bounded audio queues, immediate
mute, call ownership and speaker/headset routing. These automated results do
not establish real microphone quality, delay, echo or locked-screen call alerts;
those require device tests.

## Known limitations before public release

* Fully suspended internet delivery is not reliable yet. A connected socket or
  declared background mode does not make ordinary TCP/SIP traffic wake iPadOS.
  The physical incoming SIP test produced no locked-screen alert; the same
  private peer rang and passed audio while neXt was open. Genuine push wake and
  its signing/provider configuration remain work, not a passing result.
* Native Reticulum calls need actual iPad/phone speech tests in both directions,
  including headset changes, interruptions, quality switching and locked alerts.
* neXt radio tests must cover both Bluetooth radios, approved incoming messages,
  power cycles and network transitions. Existing Family results remain separate.
* The map backend is wired and privately tested; its native UI/download checks
  remain pending. Location sharing and Relay Chat
  now have real backend integrations but need native/device qualification. Other
  Reticulum tools still need integration. Bundled menus do not qualify those services.
* Native recipient alert routes and signed hints are integrated with explicit consent, atomic private storage and revocation; their new native UI tests still need to pass on both simulators. Real suspended mailbox alerts and complete
  identity/settings recovery need integration and device verification.
* A physical iPhone is still needed for the final phone-specific reliability
  matrix. Simulator success does not replace this.
* Release signing, TestFlight, listing/review and production qualification remain
  distribution gates. Development personal signing is not App Store signing.

Use the [iOS setup and recovery guide](../docs/IOS_SETUP_AND_RECOVERY.md) for
current setup and troubleshooting. The Family-specific audit is
[FEATURE-PARITY.md](FEATURE-PARITY.md).

The mobile runtimes use checksum-pinned pure-Python CBOR2 5.9.0. RRC decoding
has an explicit nesting bound and independent-message state; required tests
reject pathological nesting and cross-message shared references while preserving
canonical desktop interoperability. This replaces the older iOS-only dependency
affected by GHSA-3c37-wwvx-h642 and GHSA-wcj4-jw5j-44wh. Android retains its
existing pinned CBORx implementation.

## Verified separate iPad preview: 337.1

The same-key upgrade from 331.1 preserved all 1,840 current non-cache support
files, twelve messages, two contacts, identity and preferences before first
launch. Regular Family 47.6 and Family Mailbox Test 218.1 remained byte-identical.
The matching runtime passed both full simulator runs (89 required checks each,
GitHub run 44996038061; subsequent differences were validation, test and provider
changes). The actual iPad's Family-compatible contact card passed public-key and
address validation. Two private Reticulum calls, one in each direction, passed
native capture/receive frame checks and reported current microphone flow
correctly. These checks did not record speech or establish subjective audio
quality, locked internet ringing, or physical iPhone compatibility.


## Verified separate iPad preview: 348.1

Exact source `33f1e81` passed all 98 required checks on each simulator (92
native and six Messages UI cases) in run `45006778485`. The same-key upgrade
from 337.1 preserved all 2,355 current non-cache support files, twelve messages,
two contacts, the Reticulum identity and native preferences before first launch.
Regular Family 47.6 and Family Mailbox Test 218.1 remained byte-identical.

The actual iPad backend passed a private signed exchange with exact file/photo
bytes and synthetic native Opus encode/decode, a cold process restart,
conversation pin/move/export/import, and deletion followed by a fresh signed
reply. Contact import preview did not save or approve the contact; explicit
saving, blocking, rejection of a blocked code and cleanup were verified. The
visible conversation and composer rendered normally after the upgrade. These
checks do not qualify physical camera/picker gestures or recorded speech.

A private reconnect experiment captured an upstream LXMF direct message stuck
in Sending after losing its assigned link, despite a fresh active replacement.
The recovery passed three signed round trips across two connection retirements
on the receiving test peer. Both negative and positive local TCP regressions
passed in neXt CI. This is not proof of independent public-provider failover,
Wi-Fi/cellular transitions, persistence of an unsent queue across termination,
or fully suspended iPad delivery. The following app archives remain separately
subject to their complete native test gates before installation.


## Verified separate iPad preview: 358.1

Exact source `cae043c` passed all 98 required checks on each simulator (92
native and six Messages UI cases) in run `45027761400`. The bundled desktop
backend and frontend are checksum-pinned to the public neXt 0.1.23 release.
The same-key upgrade from 350.1 preserved all 3,261 current non-cache support
files, twelve messages, two contacts, Reticulum identity and native preferences
before first launch. Regular Family 47.6 and Family Mailbox Test 353.1 remained
byte-identical in their state, identity and preferences.

On the actual iPad, three private signed message/echo round trips passed,
including exchanges after two complete TCP connection retirements. The test
restored the four original peers and both contacts and removed its synthetic
history. This was a private LAN reconnect test, not an independent public
provider, operating-system Wi-Fi change or prolonged suspension test.

The running app's RNStatus, RNPath tables/rates, interface statistics and saved
peer metadata returned the expected released contracts. Its local destination
reported zero hops, and five malformed, remote or transmitting GET requests
were rejected. These backend checks do not qualify radio reception, physical
camera/picker gestures, subjective call quality or suspended internet alerts.

The same 358.1 device build also passed two private Reticulum calls, one in
each direction, through the real native capture/playback bridge. Both calls
reported live microphone capture and increasing sent/received frame counts.
The test retained no recording and restored its temporary contact, peer and
call policy. This verifies native frame flow, not subjective speech quality,
locked-screen internet ringing or physical iPhone behavior.


## iOS 0.1.25 host qualification

The exact public 0.1.25 wheel and frontend archives are checksum-pinned. All
308 backend Python modules are byte-identical to the qualified 0.1.23 runtime;
the displayed version, build metadata and frontend security fixes advance.
Twenty frontend-binding checks passed, including negative controls against the
actual unpatched call handlers. The call-race checks now require a valid ringing
state, a completion marker and a deadline, preventing an unfinished Node promise
from being mistaken for a passing assertion.

All 69 network and MeshCore location checks passed together in five bounded
repeat runs, and two real private loopback probes received standard Reticulum
receipt proofs. The separate native and actual-device gates below also passed. These host
checks alone do not qualify suspended alerts.


## Verified separate iPad preview: 360.1

Exact source `2cce2d9641e326904d57e150698ccc44c30958c6` passed all 98
checks on each simulator (92 native and six Messages UI cases) in GitHub run
`45037586063`. The personal-signed upgrade from 358.1 preserved all 2,212
current non-cache support files byte for byte, twelve messages, two contacts,
identity, preferences and four saved TCP peers before first launch. Every
original native binary (92) and all 5,632 ordinary sealed resources were
verified. Both regular Family 47.6 and Family Mailbox Test 353.1 retained
byte-identical state, identity and preferences, including a check after the
functional tests.

The actual iPad passed read-only status, interface, path and local route-trace
checks, rejecting five invalid or transmitting GET requests. Two standard
encrypted RNProbe packets reached a private Mint peer and received valid
Reticulum proofs. Three private signed message/echo exchanges passed across
two full TCP connection retirements. Both Reticulum call directions passed
native microphone and increasing sent/received frame checks without saving a
recording. A cold process restart retained the conversations and rendered the
normal interface and composer. Every temporary peer, contact and call policy
was restored, and synthetic message history was removed.

These are private LAN/backend and native bridge checks. They do not establish
subjective speech quality, public-provider failover, Wi-Fi/cellular switching,
locked-screen internet ringing, physical iPhone behavior or camera/picker
interaction.

## Unsigned neXt production archive

Source `2068078c2a84e69aa9b8897f94d1ebc9eafef40a` passed the unsigned
production archive job `45039403018` (build 361.1). The retained archive was
independently digest-verified. It uses `org.meshchat.next.ios`, version 0.1.25,
with iPhone/iPad support, native Python/audio libraries, privacy and permission
declarations and upstream notices. It contains no simulator contact/account
fixtures, personal provisioning profile or main-app signature. The personal
preview identifier is unchanged. This is packaging verification only; Apple
enrollment, distribution signing, APNs/VoIP delivery qualification, TestFlight
and submission remain pending and were not performed.


## Slow transfer and pending-message recovery follow-up

The separate physical iPad build 367.1 fetched an exact 60,000-byte fixture
through a standard RNCP peer paced at 400 bytes per second over private TCP.
The transfer was still active after 125 seconds and completed after 154.8
seconds with a matching SHA-256. The received synthetic file was removed after
verification, and the original peers were restored. This proves the active
transfer is no longer stopped by the former two-minute request timer; it is
not a LoRa file-transfer or physical Files/share-sheet result.

Development source adds a bounded SQLite restart journal for ordinary outgoing
Reticulum messages. Its write commits with the visible Sending record. Cold
recovery verifies the original signature and preserves the message identifier,
timestamp, file/photo bytes and delivery choice. Current block and mailbox
policy are checked again before handing anything to LXMF. Deleted conversations
remove their restart packets; old legacy sends without a packet stay failed.
Location and telemetry are never replayed. Recovery handles one packet per
recipient at a time while neXt executes; it does not wake a suspended device.

Private real-network tests passed after a forced process exit before transport
handoff and after the recipient's delivery proof but before the local Delivered
commit. The original signed resource and echo arrived with matching bytes.
Deletion, corrupted signatures and disabled-mailbox recovery transmitted no
pending message. All five cases passed on Python 3.11 and 3.14. Seventeen
focused checks also cover signature/identity changes, queue bounds, rollback
and history migration. Source `472f5be` subsequently passed both full simulator suites and both
unsigned archive jobs in run `45066859273`. On the actual iPad, a one-shot test
peer did not reestablish the recovery route within the deadline. With periodic
private peer announces, the same build recovered the original signed message,
a 75,000-byte attachment and exact photo bytes after termination; the receiver
had no copy before restart and recorded the original hash once. Original
contacts and peers were restored. This does not qualify provider-independent
route recovery.

A follow-up real relay regression found that a recipient's public key could
remain only in volatile Reticulum state when a pending packet was saved. After
cold restart, a fully offline recipient could not supply another announce, so
its pending propagated message did not reach the relay. The repair journals
only the recipient's public key, validates its LXMF address binding on enqueue
and recovery, and preserves legacy journals. No recipient private key is saved
and no additional identity data is transmitted. The regression fails before
the repair; afterward the relay accepts the original signed packet while the
recipient remains offline, then delivers its exact attachment when the
recipient reconnects. All 741 available root tests and 42 focused Python 3.11
checks passed. Exact source `e048311` subsequently passed CI, both full simulator suites
and both archives. On the physical iPad, a private receiver provisioned with
only the sender's public key received the original signed message once after
process termination, with its exact 75,000-byte attachment and photo. The
recipient's public key was present in the stopped process's committed journal.
The reply and attachment/photo bytes returned correctly. Contacts and peers
were restored. This was an authenticated backend test, not a physical picker
or suspended-delivery qualification.


## Verified separate iPad preview: 369.1

Exact source `7d110412dee818b4de6c587a81fd564e85f23bb2` passed all 103
required checks on each simulator (97 native and six Messages UI cases) in run
`45063671633`. Its unsigned device and production archives also passed. The
same-key upgrade from 367.1 preserved all 2,565 current non-cache support files,
twelve messages, two contacts, identity, native preferences and four saved TCP
peers before first launch. Regular Family 47.6 and Family Mailbox Test 353.1
retained byte-identical state, identity and native preferences.

The actual iPad restored the synthetic RNSh session configuration and all
Unicode terminal output without executing its command again. The stopped test
session was then removed. Private signed text, file and photo exchanges and
synthetic native Opus encode/decode passed, including exact attachment bytes
after a cold process restart. Folder organization, deletion followed by a fresh
signed reply, and restoration of the original peers and contacts also passed.
The normal conversation and composer rendered on the physical iPad.

This build adds a native loading/error/retry surface and bounded recovery for
a terminated WebKit renderer. A successful launch and cold restart do not prove
every suspension or OS resource-pressure failure is resolved. These private
backend/device checks do not qualify human speech quality, picker gestures,
fully suspended internet alerts or physical iPhone behavior. The newer durable
outbox and 0.1.26 source pins remain subject to their own qualification.

## Private call-wake foundation — November 22, 2026

Development source now adds a separate opt-in Reticulum call-wake provider, not
a replacement for mailbox alerts. Its private HTTP tests cover enrollment,
approved voice addresses, signed intents, opaque recipient-encrypted payloads,
cancellation without another VoIP push, replay suppression, short retention and
revocation. Existing message-alert behavior remains covered. The native decoder
uses deterministic Python-provider vectors to test address/key/signature binding
and rejection of forged, stale, cancelled or unapproved wakes on both simulators.
Those new native cases still require Xcode qualification.

This is unfinished infrastructure, not a working suspended-call capability. No
installed app registers PushKit or sends call hints through this new path. Native
call ownership/handoff, explicit opt-in, token registration, sender integration,
APNs provisioning and locked-device tests remain. SIP needs a compatible proxy
that holds its incoming call while waking the client; this Reticulum foundation
does not provide SIP wakeup. Apple enrollment remains on hold.


## Segmented receive capacity follow-up

Physical build 382.1 sent an exact 2 MiB file, but fetching a three-segment
file exposed a separate receiver bug: the mobile capacity guard reserved the
whole file again for each segment and exhausted its two-file allowance.
Interrupted reservations also survived a closed link. The regression rejects
the third segment before the repair. Development source now counts a logical
file once, binds continuations to the same link, original hash, sequence,
size and segment count, and releases capacity after completion, cancellation
or link closure. Duplicate and inconsistent continuations remain rejected.

All 45 focused checks passed against both the pinned 0.1.26 and prepared
0.1.27 runtimes. Private real TCP tests now send, fetch and reverse-receive
files above 2 MiB with exact bytes and no retained capacity. The reverse
fixture uses the standard RNS resource primitive with a final conclusion
callback so the already documented 0.1.26 peer sender bug cannot hide a
receiver failure. The iPad repair still needs Xcode and physical retesting.


## Received-file removal follow-up

Development source adds explicit, confirmed removal in neXt's **Received
files** dialog. The server confines removal to actual received files, rejects
symlinks and preserves other local data. A selected file is protected from
removal while awaiting a send slot, finding a route, sending or streaming an
export. The dialog retains failed rows and displays the server's reason.
Sixty related backend/frontend checks passed, including a real blocked HTTP
stream and disconnect cleanup. The standard three-segment send, fetch and
reverse-receive fixture passed exact bytes, exports and explicit removal.
Both full simulator suites and unsigned archives subsequently passed on source
`9e81f45` in run `45120353574`. The actual iPad's separate build 384.1 passed
send, fetch, reverse reception, byte-identical downloads and explicit removal
of the synthetic received files. Native picker/share-sheet gestures and
suspended transfers remain unverified; regular Family was untouched.


## Ordinary submission during an outage

The physical build 384.1 private TCP outage check exposed a gap before the
restart journal: a new ordinary send waited for a route for 35 seconds and
returned HTTP 504 without saving a pending message. The fixture restored its
original peers and contacts; neither Family app was changed. The same failure
was reproduced in a real loopback TCP regression.

Development source now lets ordinary messages to an already verified identity
be signed and saved atomically before LXMF performs path requests and retries.
Unknown recipient keys are not invented. Explicit mailbox permission, block
checks, attachment bounds and the existing restart journal still apply.
Location and telemetry retain live-path checks and cannot enter this offline
queue. The regression verifies prompt durable submission while disconnected,
automatic reconnection, the original delivered hash and a signed echo without
resubmission. Exact source `852b6f4` subsequently passed both full 111-case simulator suites
and both unsigned archives. The actual iPad's build 389.1 passed the twelve
private outage checks described above, preserving the original packet hashes
and restoring its saved contacts and peers. Location/privacy checks also
passed; this is not a claim of suspended delivery or public-peer availability.


## One runtime for the screen and call wakeups

Development source extracts neXt's actual native runtime startup into a
process-wide coordinator. Concurrent callers share the same pending startup,
loopback origin and identity. Leaving a screen does not cancel initialization,
and a failed initialization cannot re-enter partially initialized CPython.
Peer changes continue through the running settings API rather than replacing
configuration from a second caller's snapshot. The native C entry also has
a process-lifetime atomic guard against duplicate Python initialization.

The host regression races 32 threads against the production C guard and checks
a negative control. Four native tests cover concurrent callers, retained
sessions, caller cancellation and retained failures. All four passed on both
simulators in run `45148207507`; both complete 115-case suites and unsigned
archives passed too. The separate iPad's same-key build 390.1 preserved its
state, delivered the original signed packet after a process restart and
rendered its ordinary conversation and composer afterward. Both Family apps'
state, identity and native preferences remained byte-identical. Main CI,
Security and Scorecard passed. This is a prerequisite for call wakeups, not
PushKit registration or a claim that suspended calls can already ring.


## Call alert enrollment boundary

Development source adds a separate authenticated call-enrollment snapshot.
It returns only the local identity's public key, its bound messaging/voice
addresses and saved contacts accepted by the existing incoming-call policy.
Recalled keys with mismatched destinations are rejected. Calling off, Do Not
Disturb, caller removal and bans cannot grant provider eligibility. No private
key, enrollment secret, device token or message content is returned.
This is metadata for the forthcoming explicit call-alert enrollment; it does
not itself register PushKit, transmit enrollment or enable suspended calls.


## Call wake dispatch and report completion

Development source connects signed wake admission to the bounded shared-runtime
starter and actual CallKit report receipts. Starting signaling does not keep the
push completion open while CPython starts. Cancellation, consent changes and
startup failure cannot release a required push before the OS report callback;
even cancellation before the report task starts still invokes the report.
Unusable OS-required pushes report and end a fresh generic UUID without
replacing or ending an existing approved call. Optional unusable pushes do not
start the runtime or report a call. Nine new native lifecycle checks are prepared.

This remains an opt-in integration prerequisite. No PushKit registry or real
provider enrollment is enabled by this change, and no APNs or locked-device
qualification is claimed. Apple enrollment remains on hold.


The concrete VoIP registration adapter is now prepared behind the push-enabled
build flag and an explicit start. Personal-signing previews cannot create an
APNs registry. It owns a separate PushKit token and does not unregister ordinary
message alerts. Stopping keeps already queued deliveries routable through the
consent-checking dispatcher, while stale token callbacks are rejected. Five
fake-registry tests cover these paths without contacting Apple.

The adapter uses Apple's [OS-supplied reporting metadata on iOS 26.4 and later](https://developer.apple.com/documentation/pushkit/pkpushregistrydelegate/pushregistry(_:didreceiveincomingvoippushwith:metadata:withcompletionhandler:))
and the [required-report legacy callback](https://developer.apple.com/documentation/pushkit/pkpushregistrydelegate/pushregistry(_:didreceiveincomingpushwith:for:completion:))
on earlier supported versions. Explicit enrollment, native key caching, token
upload, sender routes and real APNs/device qualification still need completing;
this adapter is not started by the current app interface.
