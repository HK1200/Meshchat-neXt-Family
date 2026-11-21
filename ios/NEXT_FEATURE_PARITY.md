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
| Contacts and conversation history | Saved contact/history database, new incoming conversations and unread state are integrated; in-place iPad upgrade preserved existing data | Complete additional contact-import methods and physical editor/discovery checks |
| Own contact QR | Native scannable LXMF card and sharing; simulator decodes the displayed QR | Physical sharing between apps |
| Client discovery | Signed messaging-client announces, name/address filtering and bounded local cache are integrated | Physical discovery picker and additional service identities |
| Individual TCP peers | Four editable peers, independent toggles and saved settings; native controls/restart tests and physical saved-state checks pass | Repeat real Wi-Fi changes, offline recovery and route failover; connected sockets alone do not prove message traffic |
| RNode | Native editor, shared Bluetooth transport, saved settings, batteries and bounded radio wake handling are integrated | Actual neXt pairing, LoRa exchange, locked delivery and radio power-cycle checks |
| MeshCore | Released service/fleet routes, Bluetooth bridge, own-app Keychain passwords and native DM alert routing are integrated | Physical neXt DMs, channels, rooms, node administration, reconnect and repeat reporting |
| Profile and appearance | Saved display name/theme, private web preferences and native theme propagation are implemented | Finish the iPad profile-edit UI regression; verify physical editing and all saved web choices |
| Message notifications | Generic private notifications and native permission controls are integrated | Physical neXt notification delivery/navigation; fully suspended internet delivery needs the mailbox/push integration |
| Permission checkup | Setup and Settings paths are implemented; iPhone full flow and iPad setup flow pass without requesting optional access | Continue coverage as calling/location are wired; physical OS permission prompts |
| SIP | Compiled native engine, IPv4/IPv6 fixtures, isolated Keychain adapter and actual app-hosted registration/logout pass | Connect the account/command HTTP routes and interface; add CallKit, microphone/audio, answer/end/mute/speaker and interruption handling; then live calls |
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

The current permission implementation passed 40 native cases and both UI cases
on the iPhone simulator. The iPad passed all 40 native cases and the setup
permission checkup. Its remaining UI failure is the profile-name replacement:
the recording shows the simulated hardware Select All shortcut leaving the
caret at the beginning. The next test uses the visible iOS edit menu while
retaining cleared-field, exact-name and restart assertions.

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
