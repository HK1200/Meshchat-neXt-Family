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
| SIP | Native Keychain accounts, registration, CallKit and audio controls are integrated. Both native simulator suites passed; physical iPad foreground calls, answering, test-tone output, bidirectional RTP and clean ending/logout passed | Locked incoming alert failed on the iPad. Complete VoIP push/wake integration and physical phone, speech, route and interruption tests |
| Reticulum voice | Native CallKit controls, AVAudioEngine PCM, existing neXt telephone actions, contact identities, profiles and duplex/PTT are integrated; codec round trips pass on both simulators | New call integration still needs Xcode, actual encrypted media tests and physical calls both ways; it is not release-qualified yet |
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

The retained final iPad recording shows the complete “Simulator profile” name in
both the input and sidebar while XCTest reported a prefix. This confirms that
failure was an accessibility observation delay, rather than a truncated saved
name. A separate iPhone retry failed before entering any text because its software
keyboard never appeared after focusing a valid visible native field. Simulator
jobs now explicitly disable the runner's hardware-keyboard attachment and verify
that preference before boot/testing; all real keyboard assertions remain.

The following UI repair corrects two test-query problems without dropping checks:
the web profile's stable name is its placeholder, not its label once filled, and
native text replacement now matches identifier/value on the accessibility server
instead of repeatedly polling KVC through a complete WebKit hierarchy. Native
forms also explicitly hide their inactive web page from accessibility while
presented, so VoiceOver and UI automation do not traverse controls behind a modal.
A new UI assertion requires that inactive composer to be hidden and the existing
post-dismissal composer and messaging checks remain mandatory.

On physical build 291.1, the owner confirmed no SIP alert while locked; the private
peer likewise received no ringing response, including on the retransmitting
retry. With neXt open, the subsequent incoming SIP control authenticated, rang,
declined and logged out successfully. Temporary accounts were removed. The
locked-call/background wake path remains incomplete; a VoIP background declaration
alone is not proof that suspended calls are available. Real PushKit/APNs
qualification is still held with Apple enrollment.

The identical retransmitting SIP peer succeeded with neXt open on build 291.1.
The owner answered and heard its quiet tone; the peer observed ringing, exchanged
648 outgoing/623 incoming RTP packets and confirmed the remote ending. The
account and Keychain entry were removed and logout was observed. An administrator
subsequently verified both temporary firewall labels absent, removing the one
remaining test rule while preserving unrelated rules.

A further resume hardening checks call ownership in the native controller before
retiring an idle SIP transport: native iOS can receive a call before Python polls
its event. A conditional close refuses a native active call and leaves its event
pump running; the explicit end/disconnect path remains unchanged. All 239 backend
checks, 12 staged account/HTTP/lifecycle checks and 13 native-adapter Python checks
passed locally. The new app-hosted native ownership check still requires Xcode.
This addresses a resume race; it does not establish suspended call availability.


## Reticulum voice codec foundation

The neXt preview now packages the same pinned LXST, NumPy, Opus and Codec2
runtime used by Family. Packaging retains the upstream notices and verifies
native device architecture. A new native test runs actual synthetic
encode/decode round trips through the embedded interpreter for three Opus
voice profiles and three Codec2 modes; it uses no microphone or network.
The equivalent local checks passed with the exact iOS Codec2 adapter, including
failure checks for silence and invalid PCM. [Xcode run 44941736008](https://github.com/HK1200/Meshchat-neXt-Family/actions/runs/44941736008)
passed the device archive and all 66 source-verified native/UI cases on each
simulator. That includes actual bundled codec execution, DOM modal isolation
and restoration without losing a draft, radio lifecycle bounds, and signed
message replies after settings edits and restart.
This is a prerequisite for neXt Reticulum calls; call setup, native PCM exchange
and system call controls are not connected by this packaging change.


## Reticulum call integration under verification

The new integration uses neXt's existing identity and TelephoneManager, with
native permission checks and call controls. The sender's displayed call ID is
captured before any permission await; a delayed action cannot answer or end its
replacement. Microphone muting takes effect at the C audio boundary immediately.
Playback is bounded and stale call clients cannot deliver audio into a later
call. Voice announces use startup, reconnect and hourly scheduling.

The native Calls menu contains both Reticulum calling and SIP accounts. Existing
neXt telephone controls use the same protected backend. Voice quality can be set
before dialing, and existing contacts can be selected without retyping their
addresses. This implementation is being tested; the installed 299.1 preview does
not yet contain it. The earlier locked-screen SIP alert failure remains open.


## Real Reticulum voice transport checkpoint

The native integration now explicitly installs neXt's incoming-call policy;
TelephoneManager intentionally refuses callers until that policy is installed.
Do Not Disturb, contacts-only calls and blocked identities remain enforced before
ringing. The network callback reads an immutable contact snapshot, and contact
edits refresh that snapshot before the API returns. The native calling panel
exposes Do Not Disturb and contacts-only switches. Failed setup remains visible
after the telephone recovers instead of disappearing immediately.

The full neXt iOS backend suite passed 272 checks. The separate real-media proof
uses two disposable Reticulum processes, localhost TCP only, the checksum-pinned
0.1.21 backend with the existing hostless-audio backport, production LXST and the
iOS Codec2 adapter backed by host Codec2. Only the OS permission/answer boundary
is simulated. Twelve checks passed: decoded PCM in both directions at medium,
ultra-low, very-low and low bandwidth, switching back to medium, clean hangup,
and a new call initiated by the other peer. No microphone, speaker, public peer
or radio is used; this establishes encrypted transport and codec continuity,
not subjective speech quality or a physical locked-screen alert.

`test-voice-loopback.py` retains only numeric energy/sample results, never an
audio recording. The new CI job stages the same checksum-verified backend before
running that proof. The native device archive builds after the settings error
handler correction; both simulator suites and the policy follow-up still need
their final GitHub result before a new device install is qualified. Regular
Family remains unchanged. Apple enrollment remains on hold.


The calling follow-up implements durable Reticulum history, search/pagination,
missed-call counts, mark-viewed and clear-history actions through the released
telephone API. It deduplicates late end callbacks, resolves current contact
names from authenticated identities and keeps a failed history write from
leaving a call or microphone active. The full preceding suite passed 274 tests;
additional focused storage-failure and no-announce caller-name regressions pass.
The 12-check encrypted-media test also passes through the new hangup/history
path. These do not establish SIP history or locked-screen VoIP wake support.


The audio proof now compares two seconds of settled tone against a measured
silent baseline, requires at least 0.5 seconds of decoded samples and rejects
clipping. All 12 stronger checks passed. A silence-only negative run failed at
the intended energy assertion, proving comfort noise cannot pass the oracle;
CI runs that negative control before the positive proof.

Build 303.1's archive contains the exact reviewed runtime and no test peer or SIP
credential fixtures. Its first iPhone UI run failed to open native panels; the
recording remained on Apple's boot-progress overlay while accessibility exposed
the app underneath. All 66 unit checks passed, but the two UI checks failed.
The simulator harness now waits for OS boot completion before invoking XCTest.
The archive is not installed or release-qualified while this retry is pending.


The real-media fixture now also observes the actual LXST caller-policy callback:
a signed unknown caller reaches that policy and is rejected before any native
ring or missed-call entry. After local LXMF-contact approval, both endpoints
operate in contacts-only mode and complete all 12 settled-audio checks, including
authenticated remote-identity matching. The silence-only control still fails at
the intended energy assertion. This strengthens tests only; it does not change
the compiled app or widen incoming-call permissions.


The boot-readiness run then passed its native cases but hit an iPad UI launch
handoff timeout (`Failed to send signal 19 ... process does not exist`). No app
crash report was exported. This does not establish an application cause or a
successful fix. The next harness runs hosted native tests and UI tests in
separate XCTest invocations with a disposable simulator reboot between them.
It preserves both actual result bundles and validates each phase independently
before producing the full source-derived proof. Missing, failed or skipped
native/UI cases cannot be hidden in the aggregate. Original UI assertions are
unchanged; candidates remain uninstalled until both device-family jobs pass.


The next calling polish adds the missing iPhone loudspeaker action through the
existing native audio controller, with exact-call and connected-state checks.
iPad routing remains speaker/headset only; a connected headset is respected.
The native call form also displays capture progress. The active call's message
shortcut now uses the LXMF address derived from the authenticated link identity,
never its different telephony destination hash.

The codec diagnostic now covers all seven supported Codec2 modes, including
700/1600/3200 selected by neXt's actual mobile profiles, plus the three Opus
profiles. The real-media fixture additionally requires both peers to report each
negotiated profile (16/32/48/64) before measuring its tone. The local proof passed
all four remote-profile matches and all 12 settled-audio checks. Updated native
speaker assertions and the expanded iOS-framework checks still require Xcode.
