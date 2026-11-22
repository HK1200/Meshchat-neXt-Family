# neXt iOS completion status

neXt for iPhone and iPad is a development preview. Reticulum messaging works in
the released neXt interface, including signed replies and attachments. Native
SIP calling and optional mailbox receiving are integrated and under verification.
Reticulum voice, offline maps, location and Relay Chat are integrated and
undergoing native/device qualification. Remaining desktop services, suspended
alerts and release verification still need work before a complete neXt release. Family has its own [parity audit](FEATURE-PARITY.md).

This checkpoint is dated November 22, 2026. “Integrated” means the code is wired
into the app; physical verification is stated separately.

## Features and remaining work

| Feature | Current implementation and verification | Remaining work |
|---|---|---|
| Reticulum direct messages | Real signed exchanges on the iPad and both simulators; conversations survive closing and reopening | Network-loss, extended idle and physical iPhone matrix |
| Quoted replies | Signed replies preserve their referenced message; verified through the physical iPad backend | Repeat ordinary UI interaction on a physical iPhone |
| Files and photos | The physical iPad received and returned signed file/photo payloads with matching bytes; simulator file export passes | Real camera/Photos/Files picker and share-sheet checks; larger resource transfers |
| Voice notes | Development source now streams recorded PCM through the upstream Opus/Ogg writer, preserves standard Codec2/Opus LXMF fields, and serves bounded WAV previews for iOS versions without Ogg playback. Private host tests verify signed audio-only delivery, playback, byte limits, duration, tone energy and corrupt-input handling. Inline WAV previews have an 8 MB decoded-PCM bound; original encoded bytes remain available from the authenticated raw attachment endpoint | Bundled Ogg/Opus encode/decode assertions passed in 83 native tests on both simulators. The actual iPad encoded and decoded a signed synthetic tone; physical microphone recording, audible playback controls and export remain required |
| Contacts and conversation history | Saved contacts, rename/removal, local conversation labels, new incoming conversations and unread state are integrated; in-place iPad upgrade preserved existing data | Development source adds native camera/QR-image/paste review and explicit Reticulum contact saving. Key-binding, atomic-failure, duplicate, blocked-identity and real private HTTP tests pass; native paste/review passed on both simulators; physical camera/editor/discovery checks remain |
| Local Reticulum peer bans | Development source wires the released Blocked destinations API to durable verified-identity aliases, clears only the banished contact/history, rejects messages before alerts, cancels private sharing and blocks calls. Private signed-packet tests prove blocking, cold restart and unblocking; a pathfinding race test proves a pending message cannot escape after the ban | Both complete simulator runs passed, including signed receive/reply after the integration. Physical block/unblock interaction remains pending. Optional transport-level blackhole management is a separate unfinished Reticulum tool |
| Conversation organization | Durable folders, pinning, moving, folder import/export, Unicode names and name/unread/failed/attachment filters are wired to the real interface in development source. Private HTTP tests prove restart and identity preservation, atomic failed imports and idempotent reimports. The archived interface passed create/pin/move/reload at desktop and phone browser sizes | Both full simulator UI runs passed; the actual iPad backend passed pin/move/export/import and process restart. Physical editor gestures still need review |
| Local conversation deletion | Individual and selected-history removal now fence late delivery callbacks, clear pins/folder assignments atomically and preserve contacts and identity. A real private signed exchange passes before deletion and a new signed message reopens the chat afterward; browser confirmation/removal passes at both sizes | Both full simulator deletion/reply cases passed. Actual iPad backend deletion preserved the contact, fenced old messages and received a fresh signed reply; physical confirmation gestures still need review |
| Own contact QR | Native scannable LXMF card and sharing; simulator decodes the displayed QR. Development source also adds a Family-compatible public card with nickname and optional voice address | Both simulator QR checks pass. Actual iPad build 337.1 card was parsed with Family's importer and its identity/LXMF bindings verified; physical camera sharing between apps remains |
| Client discovery | Signed messaging-client announces, name/address filtering and bounded local cache are integrated | Physical discovery picker and additional service identities |
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
| Other Reticulum tools | Their frontend menus are bundled | Register the remaining real services and test their actions; a visible menu does not establish working functionality |
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
