# neXt iOS completion status

neXt for iPhone and iPad is a development preview. Reticulum messaging works in
the released neXt interface, including signed replies and attachments. Native
SIP calling and optional mailbox receiving are integrated and under verification.
Reticulum voice, offline maps, location and Relay Chat are integrated and
undergoing native/device qualification. Remaining desktop services, suspended
alerts and release verification still need work before a complete neXt release. Family has its own [parity audit](FEATURE-PARITY.md).

This checkpoint is dated November 21, 2026. “Integrated” means the code is wired
into the app; physical verification is stated separately.

## Features and remaining work

| Feature | Current implementation and verification | Remaining work |
|---|---|---|
| Reticulum direct messages | Real signed exchanges on the iPad and both simulators; conversations survive closing and reopening | Network-loss, extended idle and physical iPhone matrix |
| Quoted replies | Signed replies preserve their referenced message; verified through the physical iPad backend | Repeat ordinary UI interaction on a physical iPhone |
| Files and photos | The physical iPad received and returned signed file/photo payloads with matching bytes; simulator file export passes | Real camera/Photos/Files picker and share-sheet checks; larger resource transfers |
| Contacts and conversation history | Saved contacts, rename/removal, local conversation labels, new incoming conversations and unread state are integrated; in-place iPad upgrade preserved existing data | Complete additional contact-import methods and physical editor/discovery checks |
| Conversation organization | Durable folders, pinning, moving, folder import/export, Unicode names and name/unread/failed/attachment filters are wired to the real interface in development source. Private HTTP tests prove restart and identity preservation, atomic failed imports and idempotent reimports. The archived interface passed create/pin/move/reload at desktop and phone browser sizes | Native iPhone/iPad interaction and physical-device qualification remain required |
| Local conversation deletion | Individual and selected-history removal now fence late delivery callbacks, clear pins/folder assignments atomically and preserve contacts and identity. A real private signed exchange passes before deletion and a new signed message reopens the chat afterward; browser confirmation/removal passes at both sizes | New native delete/restart/fresh signed-reply case awaits both simulators; physical-device checks remain required |
| Own contact QR | Native scannable LXMF card and sharing; simulator decodes the displayed QR | Physical sharing between apps |
| Client discovery | Signed messaging-client announces, name/address filtering and bounded local cache are integrated | Physical discovery picker and additional service identities |
| Individual TCP peers | Four editable peers, independent toggles and saved settings; native controls/restart tests and physical saved-state checks pass | Repeat real Wi-Fi changes, offline recovery and route failover; connected sockets alone do not prove message traffic |
| RNode | Native editor, shared Bluetooth transport, saved settings, batteries and bounded radio wake handling are integrated | Actual neXt pairing, LoRa exchange, locked delivery and radio power-cycle checks |
| MeshCore | Released service/fleet routes, Bluetooth bridge, own-app Keychain passwords and native DM alert routing are integrated | Physical neXt DMs, channels, rooms, node administration, reconnect and repeat reporting |
| Profile and appearance | Saved display name/theme, private web preferences and native theme propagation are implemented | Both simulator profile-edit/restart regressions pass; verify physical editing and all saved web choices |
| Message notifications | Generic private notifications and native permission controls are integrated | Physical neXt notification delivery/navigation; fully suspended internet delivery needs the mailbox/push integration |
| Permission checkup | Setup and Settings paths are implemented; iPhone full flow and iPad setup flow pass without requesting optional access | Continue coverage as calling/location are wired; physical OS permission prompts |
| SIP | Native Keychain accounts, registration, CallKit and audio controls are integrated. Both native simulator suites passed; physical iPad foreground calls, answering, test-tone output, bidirectional RTP and clean ending/logout passed | Locked incoming alert failed on the iPad. Complete VoIP push/wake integration and physical phone, speech, route and interruption tests |
| Reticulum voice | Native CallKit controls, AVAudioEngine PCM, existing neXt telephone actions, contact identities, profiles and duplex/PTT are integrated; codec round trips pass on both simulators | Both simulators and strict encrypted-media CI pass; physical speech, interruptions, echo and locked incoming calls remain unqualified |
| Maps | The released map backend is integrated: offline tiles, validated imports, selection/removal, drawings, overlays and map-data catalogs. Private HTTP tests prove signed discovery/catalog transfer, exact file hashes, imports above the message-size limit and preservation across invalid uploads and restarts | Native map rendering, download/share pickers and regional downloads need Xcode/device verification |
| Location and telemetry | Actual released telemetry routes, signed location exchange, Family frames, silent map updates, saved location-source settings and fresh outgoing fixes are integrated. Private tests prove both message directions, restart persistence, sender attribution and cancellation when sharing is disabled during pathfinding | Verify browser GPS and timed sharing in the native interface, expiry/stop controls and physical permission behavior; suspended location sharing remains unqualified |
| Relay Chat | Actual released RRC services, signed discovery, public/password rooms, hub receipts and automatic rejoining are integrated. Private real-link tests pass both directions against the unmodified desktop hub; keys remain encrypted and rooms/history survive restart | Native room UI, mentions, reconnect and physical device checks |
| Other Reticulum tools | Their frontend menus are bundled | Register the remaining real services and test their actions; a visible menu does not establish working functionality |
| Offline mailbox and push | Optional native relay-address editor and periodic receiving while running are integrated. Real encrypted relay tests prove failed writes retain messages and recovery saves once. Explicitly opted-in manual/Automatic outbound propagation now passes a real offline-recipient/file test; relay acceptance is shown as Sent | Verify the native editor; qualify opted-in outbound propagation, then qualify the new native recipient-route editor and signed sender hints. Native receiving-side enrollment, token rotation, explicit sender approvals and alert-tap retrieval are integrated in development source and await Xcode qualification. Personal-signed previews leave Apple enrollment disabled. Real suspended APNs delivery needs Apple signing entitlements, a deployed provider and device tests |
| Recovery and distribution | Unsigned arm64 device packages build; same-account personal upgrades preserve the separate preview | Finish identity/settings backup and restore paths, release configuration, signing, TestFlight and store listing/review |

## Verified checkpoints

On November 21, 2026, the separate physical neXt preview was running build
299.1. Its in-place upgrade preserved all 12 messages, both saved contacts,
the Reticulum identity, ratchet keys, native preferences and four TCP peers.
All non-cache support files were compared before the first launch. Physical
signed file/photo exchanges matched their original bytes and survived restart.
The real camera, Files/Photos pickers and share sheets still need device checks.

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
