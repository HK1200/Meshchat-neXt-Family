# neXt iOS completion status

neXt for iPhone and iPad is a development preview. Reticulum messaging works in
the released neXt interface, including signed replies and attachments. Calling,
location and the remaining desktop services still need integration before this
is a complete neXt release. Family has its own [parity audit](FEATURE-PARITY.md).

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
| SIP | Compiled native engine, IPv4/IPv6 fixtures, isolated Keychain adapter and actual app-hosted registration/logout pass. Native account management and protected HTTP lifecycle routes are now integrated | Verify the account screen on Xcode; add CallKit, microphone/audio, answer/end/mute/speaker and interruption handling; then live calls |
| Reticulum voice | Family's shared native engine is available in the repository | Wire neXt call setup, caller identities, quality negotiation, audio and system controls; live tests both ways |
| Maps and location | The released frontend is bundled | Wire neXt's location/telemetry backend, native permission/session handling, offline maps and pin details; verify sharing expiry and stopping |
| Relay Chat and other Reticulum tools | Their frontend menus are bundled | Register the real services and test their actions; a visible menu does not establish working functionality |
| Offline mailbox and push | Shared project components and signed-hint infrastructure exist | Add neXt iOS enrollment, mailbox/session lifecycle and notification routing; real APNs verification needs Apple signing entitlements and a deployed provider |
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
