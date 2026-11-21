# neXt iOS completion status

neXt for iPhone and iPad is a development preview. Reticulum messaging works in
the released neXt interface, including signed replies and attachments. Native
SIP calling and optional mailbox receiving are integrated and under verification.
Reticulum voice, location and remaining desktop services still need integration
before this is a complete neXt release. Family has its own [parity audit](FEATURE-PARITY.md).

This checkpoint is dated November 21, 2026. “Integrated” means the code is wired
into the app; physical verification is stated separately.

## Features and remaining work

| Feature | Current implementation and verification | Remaining work |
|---|---|---|
| Reticulum direct messages | Real signed exchanges on the iPad and both simulators; conversations survive closing and reopening | Network-loss, extended idle and physical iPhone matrix |
| Quoted replies | Signed replies preserve their referenced message; verified through the physical iPad backend | Repeat ordinary UI interaction on a physical iPhone |
| Files and photos | The physical iPad received and returned signed file/photo payloads with matching bytes; simulator file export passes | Real camera/Photos/Files picker and share-sheet checks; larger resource transfers |
| Contacts and conversation history | Saved contacts, rename/removal, local conversation labels, new incoming conversations and unread state are integrated; in-place iPad upgrade preserved existing data | Complete additional contact-import methods and physical editor/discovery checks |
| Own contact QR | Native scannable LXMF card and sharing; simulator decodes the displayed QR | Physical sharing between apps |
| Client discovery | Signed messaging-client announces, name/address filtering and bounded local cache are integrated | Physical discovery picker and additional service identities |
| Individual TCP peers | Four editable peers, independent toggles and saved settings; native controls/restart tests and physical saved-state checks pass | Repeat real Wi-Fi changes, offline recovery and route failover; connected sockets alone do not prove message traffic |
| RNode | Native editor, shared Bluetooth transport, saved settings, batteries and bounded radio wake handling are integrated | Actual neXt pairing, LoRa exchange, locked delivery and radio power-cycle checks |
| MeshCore | Released service/fleet routes, Bluetooth bridge, own-app Keychain passwords and native DM alert routing are integrated | Physical neXt DMs, channels, rooms, node administration, reconnect and repeat reporting |
| Profile and appearance | Saved display name/theme, private web preferences and native theme propagation are implemented | Both simulator profile-edit/restart regressions pass; verify physical editing and all saved web choices |
| Message notifications | Generic private notifications and native permission controls are integrated | Physical neXt notification delivery/navigation; fully suspended internet delivery needs the mailbox/push integration |
| Permission checkup | Setup and Settings paths are implemented; iPhone full flow and iPad setup flow pass without requesting optional access | Continue coverage as calling/location are wired; physical OS permission prompts |
| SIP | Native Keychain accounts, registration, CallKit, microphone/audio, answer/end/mute/speaker and interruption handling are integrated. Private app-hosted incoming/outgoing signaling checks pass on iPad; matching iPhone and current mailbox builds are running | Complete native screen coverage and real neXt iPad/Android calls, locked alerts and audio/routing checks |
| Reticulum voice | Family's shared native engine is available in the repository | Wire neXt call setup, caller identities, quality negotiation, audio and system controls; live tests both ways |
| Maps and location | The released frontend is bundled | Wire neXt's location/telemetry backend, native permission/session handling, offline maps and pin details; verify sharing expiry and stopping |
| Relay Chat and other Reticulum tools | Their frontend menus are bundled | Register the real services and test their actions; a visible menu does not establish working functionality |
| Offline mailbox and push | Optional native relay-address editor and periodic receiving while running are integrated. Real encrypted relay tests prove failed writes retain messages and recovery saves once | Verify the native editor; add outbound propagation, suspended scheduling and neXt push enrollment. Real APNs needs Apple signing entitlements and a deployed provider |
| Recovery and distribution | Unsigned arm64 device packages build; same-account personal upgrades preserve the separate preview | Finish identity/settings backup and restore paths, release configuration, signing, TestFlight and store listing/review |

## Physical iPad checkpoint

The separate neXt preview upgraded from 236.1 to 264.1. Its permanent identity and
message database were byte-identical immediately after installation, and saved
preferences matched. All eight original messages and both contacts remained.
Subsequent private test exchanges added two signed file messages and two signed
photo messages without creating or changing saved phonebook contacts.

The file exchange survived an actual app restart. Attachment downloads matched
exactly. The new process rejected its predecessor's session token, foreign
origins, incorrect Host headers and message submissions without a CSRF token.
These backend/device checks do not substitute for tapping each picker or call
control on a real device.

Regular Family 47.6 and Family Mailbox Test 218.1 were not replaced. Their earlier
radio, location and voice successes are Family results, not proof of neXt's new
service integrations.

## Native verification checkpoint

At `0870519` (run 44913566807), all 44 native cases and both UI cases
passed on each simulator, with source-case execution verified. The hostname test now waits for the exact settled accessibility
value. Profile editing, identity preservation and restart assertions passed on
both devices. The separate physical preview then upgraded to 276.1 with all
12 messages, both contacts, its identity and saved settings intact. Both Family
installs remained unchanged. Actual authenticated API checks also passed for
contact rename/removal/labels, manual announces and fresh rapid-announce times.

The backend passed all 193 neXt iOS Python checks, including authenticated
contact edits in both device and isolated simulator modes. Contact removal keeps
messages, read state and independent conversation labels. It never creates a
new contact or conversation from a label alone.

The announce controls are included in that suite. The existing Announce
button now invokes the real connected interfaces, reports failure when none can
send, and updates the displayed successful time. The interval selector persists
its supported values; startup/reconnect announces remain separate from the
periodic timer. A successful timestamp survives app restart, preventing rapid
replacement announces from reusing the same one-second protocol time. Failed or
merely queued requests do not overwrite the last successful time. These are
private loopback and mock-radio results, not new physical RF verification.

The real WebKit bridge test writes through JavaScript into the private native
preference file, restores it with a new loopback port and rejects a child-frame
write. Both simulators passed that case. A green build without executed test
records is never sufficient release proof.

## Next implementation sequence

1. Complete both native UI suites and upgrade the separate iPad preview with its
   data intact.
2. Finish SIP calls through the actual neXt interface and native system controls,
   then Reticulum voice. Test permission denial, locked answering, ending from
   either end, routing, interruptions and reconnect.
3. Complete location/maps, mailbox/background alerts and the remaining service
   routes. Verify physical radio traffic independently of TCP traffic.
4. Run the device reliability and upgrade matrix, including an actual iPhone,
   then finish distribution and recovery guides.

Apple enrollment remains on hold. Simulator success cannot establish real APNs
or physical iPhone behavior. Android/desktop public releases remain separate
from this unfinished iOS preview.


## Notification sequence repair

Deleting the newest unread message previously allowed its number to be reused,
which could hide a later notification after first enabling alerts. The new
regression fails on the old code. A persistent counter now survives deletion and
restart; the native app also carries its existing Reticulum baseline into the
backend when upgrading a preview. Existing messages, contacts and read state
remain intact. All 193 Python checks and all 46 native/UI cases per simulator passed. The
separate physical preview upgraded to 277.1 with its identity, message database
and native preferences byte-identical before launch. All 12 messages and both
contacts remain; regular Family 47.6 and Family Mailbox Test 218.1 are unchanged.

A separate read-only physical-device test runner builds successfully. It permits
only the separate neXt preview and Family Mailbox Test, and never accepts regular
Family as a target. Actual device execution is not yet proven. It is not a store
build and does not replace any existing install during compilation.


## SIP account integration checkpoint

The preview now has native SIP account management backed by the released neXt
account service, its own iOS Keychain and the current OS route. Saving alone does
not register; connecting is explicit, and saved enabled accounts can recover
when an allowed connection returns. The native screen preserves unsaved edits
and supports secure password replacement, removal and per-network choices.
The released web dialer remains unavailable until calling is integrated.

All six staged-runtime checks pass, including actual protected HTTP routes,
credential omission from metadata/status, logout, corruption preservation and
route changes. These checks use synthetic accounts and no external registrar.
The 193 backend checks pass; the new native account form cases await Xcode.

The read-only physical UI runner still fails before executing its test. The
normal neXt preview and original saved-window state were restored afterward.
It has not established physical UI automation.


## Native SIP calling integration

The next preview links the CallKit/audio controller to exact native SIP call
IDs. The native account screen and released web telephone can call, answer,
end, mute and route audio through the shared engine. The iPad defaults to its
speaker and keeps external headset routing. Microphone permission is explained
in the seven-step checkup and requested only through an explicit action.

The backport recognizes iOS without pretending it is Linux or Android. Its
input chunk checksum and four policy expressions are verified before changing
the pinned frontend. Both native and web call controls carry the displayed
call ID; a late request cannot target the next call. The matching source change
is on neXt main. Future frontend updates must review/remove this pinned backport
when their source includes it.

All seven staged-runtime checks and 198 backend tests pass locally. Six new
call-controller cases and a linked-session case await native Xcode execution.
Live calls, speaker/headset routing, interruptions and locked answering still
need verification on this neXt build. These implementations do not establish
fully suspended internet delivery or APNs, and Apple enrollment remains on hold.


The SIP account build at `989d326` passed all 50 executed native/UI cases on
each simulator (run 44917304591). Its device build passed as well. The native
calling build compiled for arm64; its expanded tests are running. Two additional
app-hosted wire tests now use private loopback peers to verify an outgoing
INVITE/rejection and incoming decline without microphone capture. The fixture
requires a fresh authenticated registration, completed call and logout for each
simulator, including when both run sequentially. Its four local wire checks pass.


## Follow-up verification repairs

The `35c4020` iPad run executed all 57 native cases successfully and confirmed
the incoming SIP decline on the private peer. The outgoing wire check correctly
refused qualification: its SIP destination was loopback, which Baresip excludes
when selecting that outgoing media route. The retry uses only the runner's own
bound interface and the native test verifies that address against `getifaddrs`;
it also explicitly rejects audio and command errors. Reticulum simulator peers
remain restricted to loopback. The strict completed-call proof is retained.

The `4efed20` iPad calling/UI suite passed; iPhone passed both UI cases but its
offscreen WebKit preference test timed out. That test now hosts the real web
view in a temporary visible test window, retains its delegate, reports process
termination and always cleans up on failure. Its persistence, cross-port restore
and child-frame denial assertions remain unchanged. The normal app window is
restored afterward. This helper is simulator-test code, not a device-app change.

The `1a35d04` device app compiled successfully, but macOS Bash failed during
cleanup because the device build had no fixture PIDs. Cleanup now uses two
explicit optional process IDs. All five focused wire-fixture tests and the
related preference/proof checks pass locally. The full native retry is required
before installing the calling candidate or claiming it verified.


## Durable inbox prerequisite for offline messages

The old neXt transport callback returned no result even when the inbox declined
a message. The new regression fails on that code. A bounded thread-safe handoff
now returns success only after the owning loop commits the SQLite transaction;
slow web views do not delay that commit. Failed, timed-out or shutdown writes are
not acknowledged. The staged LXMF fork's strict propagation-delivery callback is
enabled. Invalid signatures remain rejected.

All 213 existing/new neXt backend checks pass. A real encrypted relay test also
passes: a simulated failed inbox write leaves the verified message available,
then a later successful write saves it once. Repeated sync does not duplicate
it. The sender is not in the phonebook; its public identity is supplied by the
private fixture so signature verification is genuinely exercised. This is a
prerequisite, not a claim that neXt's mailbox settings, background scheduling or
real APNs are finished.

At `755cc00`, iPhone passed the full native/UI and strict SIP peer checks. iPad
passed all 57 native cases; its new blank peer-host field timed out in an extra
placeholder-clearing poll before typing. The helper now polls for clearing only
after actually deleting existing text, using the built-in value predicate. It
still requires the exact replacement, saved peer values, restart preservation
and signed replies. The combined retry must pass before qualification.


## Optional offline mailbox controls

neXt now has a native Offline mailbox editor beside its contact QR controls.
It accepts a propagation-node address, offers explicit Check now, shows progress
and the last completed check, and allows blank-and-save to turn receiving off.
The setting defaults off, is stored in the existing private SQLite database,
and does not change contacts, identity, TCP peers or outbound message routing.

While the runtime executes, it checks an enabled mailbox every five minutes,
cancels stale downloads when live transport sessions change, limits each request
to 50 messages and retries failed/timed-out checks with a bounded delay. The
real encrypted relay regression now exercises this controller as well as the
durable inbox. All 227 backend checks passed before the additional retry-error
case, which also passes. Native address validation and real editor tests are
prepared for Xcode.

This is receiving support while the runtime runs. It does not make iOS wake
neXt while fully suspended; background scheduling, push enrollment and sending
offline still require integration. The screen explains these limits explicitly.


## Qualified native mailbox and protected physical upgrade

At `fd3969d` (run 44924314202), both iPhone and iPad passed all 60 required
source-matched native/UI cases, including actual signed replies, peer persistence,
private native SIP signaling, and the mailbox editor. All 231 backend cases
passed on the exact source. Main CI, Security and Scorecard are green.

The actual iPad preview upgraded from 277.1 to 285.1. A complete 10,800-file
support backup was retained. Immediately before and after upgrading, all 755
current non-cache support files—including identity, message history, web choices,
radio data and every current ratchet key—matched byte for byte. Native preferences
matched too. The running authenticated API confirms all 12 messages, both contacts,
the existing notification counter and all four peers. The mailbox defaults off;
native SIP is available. Regular Family 47.6 and Family Mailbox Test 218.1 remain
untouched.

Apple rejected iLoader's initial login with error -22410. The local upgrade instead
used the existing vault signing key and an already valid same-app, same-team,
same-device profile expiring November 28. The key was matched to the profile's
certificate; all 69 signed native binaries and 4,333 ordinary sealed-resource
digests passed verification before installation. The temporary key file was
removed, and the Apple password was not read. This did not enroll a developer
account, renew a profile or create an App Store signing identity.

The first private physical SIP attempt was blocked by iOS's visible Local Network
permission dialog. Its temporary account was removed. Microphone permission is
also still undetermined. Those OS prompts need the device owner's taps before
live incoming/audio verification; they are not evidence of an audio-engine
failure. The usage explanation and voluntary permission checkup now cover local
SIP providers and radios as well as TCP peers. No physical neXt speech result is
claimed yet.


The continued voice audit reproduced `NoneType ... SAMPLERATE` in neXt's real
LXST Null mixer with its host backend absent. The shared repair at `a714c4d`
supplies only 48 kHz metadata when that backend is missing, preserves any real
backend and restores only its own fallback in test cleanup. All 96 related neXt
audio checks passed. The iOS stager carries the same repair into the pinned
0.1.21 wheel; its actual packaged payload matches the reviewed shared source
structurally. All 235 iOS backend checks pass, including a regression using the
real Null mixer before and after the backport. Native packing is being rerun.
This does not claim that neXt's Reticulum call screen or native PCM bridge is
already integrated.

## Physical SIP registration and incoming-call repair

The separate physical preview 285.1 completed signed exchanges in both directions
against private Mint test peers attached individually to RMAP 4343, RMAP 4242,
WashMesh 7242 and Chicago 4242. The iPad retained its four enabled peers; this does
not prove that each iPad connection was forced independently. Synthetic messages
were removed afterward, preserving the original twelve messages and two contacts.

Actual SIP testing identified two independent restrictions: the iPad's Local
Network permission and Mint's inbound firewall. With owner-approved temporary
access limited to the iPad and private SIP port, authenticated registration worked.
The incoming call was immediately declined until the neXt package included the
VoIP background declaration already present in Family. A controlled 285.2 personal
test changed only that package declaration and the build number, retaining the
qualified 285.1 compiled code. It then passed authenticated registration, incoming
call state, explicit decline and clean logout. Its temporary account and Keychain
secret were removed. This verifies signaling, not speech, locked-screen alerts or
fully suspended internet availability. Regular Family remains unchanged.

The source now verifies the packaged audio/VoIP declarations in native tests and
reports native system-call failures through SIP status. The iPad profile test also
uses the displayed Select All menu's current frame after recordings showed the
menu present while XCTest stalled resolving its tap. All text replacement,
profile persistence, restart and signed-message assertions remain required.

The controlled 285.2 preview also completed actual private incoming and outgoing
SIP media sessions. Mint sent 1,250 PCMU RTP packets in each direction test and
received 1,319 and 1,751 packets from the iPad respectively. The owner heard both
quiet test tones and spoke during the outgoing test; aggregate microphone levels
changed. No speech recordings were retained. These tests establish bidirectional
media transport and iPad speaker output, not a full Android/iPad conversation or
Opus quality qualification.

The subsequent locked-screen check did not pass. After suspension the local HTTP
listener stopped accepting requests while the app process remained alive, and
the owner reported a black/disconnected interface. The interrupted temporary SIP
account was subsequently removed, and all twelve messages, two contacts, saved
identity and four peer rows remained intact. The follow-up now reopens the local
listener on resume on the same port, without recreating messaging services or
changing access credentials; renderer termination also reloads the local view.
Real socket-loss/rebind tests cover access preservation, transient bind failure
and 25 recovery cycles without descriptor growth. Physical lock/unlock recovery
and locked calls still require retesting after Xcode qualification.

Run 44931472088 passed all 61 checks on iPad. Its iPhone native checks passed,
but the UI runner timed out querying keyboard absence. The recording shows the
keyboard already hidden and an Apple Intelligence system banner remaining over
the TCP form. The follow-up test dismisses only that positively identified
simulator notice and retains the keyboard-absence, saved-peer, profile and signed
reply assertions. A passing rerun is still required.

The same-key personal upgrade from 285.2 to compiled recovery build 289.1 preserved
all 851 current non-cache support files and native preferences byte for byte,
including twelve messages, two contacts, identity and four peers. The owner then
locked the iPad for approximately twenty seconds and reopened neXt: the
conversation returned normally. An authenticated check confirmed the same runtime
instance and local port responded after the cycle; a fresh data check passed.
This is one successful physical resume, not proof of sustained suspended delivery.

The SIP follow-up also refreshes an enabled, idle registration after resume,
because its UDP socket may have been reclaimed independently of the UI listener.
The decision is checked again under the existing service lock, preserving an
incoming call that arrives during recovery. Active calls and disabled accounts
are untouched; repeated restarts retain the existing five-second bound. Eleven
staged account/HTTP/lifecycle checks passed, including that race and a fresh
registration after an idle resume. Live post-lock SIP alerts still need testing.

Run 44932961783 passed all 62 checks on iPhone. Its iPad UI run reached profile
replacement but read a partial accessibility value immediately after typing.
The overlapping-save regression against the actual shared Settings component
passed without any application change, so an application save race has not been
established. The follow-up targets the now-empty input explicitly and waits for
the exact complete WebKit value before retaining the equality, save/restart and
signed-reply checks. Its recording is retained for further diagnosis; a passing
rerun is still required.
