# Family on iPhone and iPad: setup and recovery

This guide describes the native live Family app. The sample **FamilyPreview**
app is a separate interface demonstration. The separate **Family Mailbox Test**
install is for testing; keep an existing regular Family install intact when
trying it. The separate neXt iOS preview includes Reticulum messaging and development
integrations for calling, radios, maps and mailbox delivery. It does not yet
qualify every desktop/Android neXt feature.

The iOS app is still under verification. It is not yet an App Store release.
See [the feature and device verification audit](../ios/FEATURE-PARITY.md) for the
remaining checks. Incoming calls while fully suspended and real Apple push
alerts are not yet verified release capabilities.

## Install or update without starting over

Use the same app identifier and signing team as the existing installation.
Install an update over that app; do not delete it first. A separate test app has
its own contacts, guardian password and Reticulum identity. It does not update
or inherit the regular app's setup.

For a personal-signed test build, use the existing signing account in iLoader.
If sign-in fails, check the official iLoader release notes and update from its
official source before retrying. Enter account credentials and verification
codes in iLoader, not in a chat. If the device reports a trust or Developer Mode
requirement, complete it on the unlocked device. A stock iPad does not need to
be jailbroken for these test installations.

If signing expires, renew signing and reinstall over the same app. Do not
uninstall as a troubleshooting step: that can remove its locally stored data.
Before updating, check the contact list, a recent conversation and **My contact
QR**; check the same items afterward. The public Reticulum addresses should
remain the same. Keep a private backup before a development upgrade.

## First setup and approved contacts

1. Create and confirm a guardian password. A fresh install has no preset password.
2. Open the shield button for **Guardian settings**. Run **Permission checkup**.
   Grant permissions for the features you intend to use. Bluetooth is needed for
   radios, microphone for calls, camera for live QR scanning and location for GPS.
3. Set a nickname under **Device name** and tap **Save device name**.
4. Use **Add approved contact**. Scan a contact card, select a QR image or use
   discovery, then review the addresses and save. To share this device's public
   addresses, use **My contact QR**. Each device must approve the other for private
   conversations and calls to work in both directions.

Use **Day mode** or **Night mode** without unlocking Guardian settings.

## Connect only the services you use

Under **Reticulum TCP peers**, each endpoint has its own status and saved settings:

| Peer | Port |
| --- | --- |
| `rmap.world` | `4343` |
| `rmap.world` | `4242` |
| `reticulum.washmesh.net` | `7242` |
| `rns.chimesh.org` | `4242` |

Select a row to edit it, change its enabled state and tap **Save peer**. Use
**Add TCP peer** for a private or additional server. Existing custom profiles
can leave the public peers disabled; inspect each row rather than assuming
that saving one enables every connection.

A connected socket does not guarantee that a destination has announced or that
a route is available. If a message cannot find a path, check the full contact
address, the other device's connection and its announce. Try another enabled
peer before changing radio settings or deleting a contact. An internet peer
outage does not require removing the app or resetting its identity.

For an **RNode**, select **Bluetooth LE**, tap **Find Bluetooth radios**, choose
the radio and save its profile. For the first connection, put the radio itself
in pairing mode and enter its current PIN when iPadOS asks. Merely enabling
Bluetooth on the radio may not allow a new pairing. Keep other apps and phones
disconnected from that radio. If a pairing prompt disappears repeatedly, stop
retrying, check the radio's pairing mode and check for another connected phone.
Preserve the known working frequency, bandwidth, spreading factor, coding rate
and transmit power; network profiles must match.

For **MeshCore companion**, enable the service, choose the intended Bluetooth
radio and save. Keep approved private-message reception enabled if needed.
Radio acknowledgement confirms delivery to a companion; the recipient's Family
app still needs the sender approved before it admits the private message.

## Calls and alerts

For Reticulum, enable **Reticulum calling** and approve the contact's voice
address. For SIP, open **SIP calling**, enter the provider account and password,
save and wait for registration. Add the contact's SIP address or extension.
The iPad uses its speaker unless a headset is connected.

**Use iOS call screen** enables system Answer, Decline, End and Mute controls.
It does not make a suspended Family app continuously reachable. Keep Family
open to receive new calls in the current test builds. Calls already answered
can continue when the screen locks. **Keep screen awake for calls** is optional
and applies while Family is open.

For message alerts, enable notifications in Family and check the device's
notification settings. Bluetooth can wake the app for radio traffic, but this
depends on a connected/restorable radio and iOS scheduling. A TCP connection
alone does not keep iOS running indefinitely in the background.

An **Offline message mailbox** stores encrypted mail for later retrieval.
Configure a trusted LXMF propagation node and exchange the approved contact's
verified identity first. The sender must use that mailbox for offline delivery.
Family checks on return to the app and requests background checks; iOS controls
when those checks run. Optional **Mailbox push alerts** need a compatible
provider and a push-enabled signed build. Free personal signing and mock-provider
checks do not prove real Apple push delivery.

## Share and stop location

Location policy is on **Guardian settings → Location sharing**, not in the
contact editor.

1. Under **Approved location contacts**, select only the intended recipients,
   enable the Family map and tap **Save location policy**.
2. If needed, turn on **Continue sharing with the screen locked** and tap
   **Save background sharing**. It starts off.
3. Choose a duration and tap **Start sharing** while Family is open. Allow
   location access and Precise Location when requested.
4. To end the session, tap **Stop sharing**. If locked-screen sharing is no
   longer wanted, switch it off and save that setting too.

Locked-screen location sharing uses iOS's location indicator and more battery.
Force-quitting the app ends its location session. The map shows the time of the
last received update; a pin is not proof that the person is still there.

## Recover without losing setup

- **No radio connection:** check radio power, battery, Bluetooth permission and
  competing connections before changing the saved pairing or RF profile.
- **No new TCP messages while locked:** reopen Family and let its mailbox check
  finish. Review the background-delivery limitations above.
- **Calls silent:** check microphone permission, call registration/path, output
  volume and any headset. Test with the devices apart to avoid speaker feedback.
- **Map unavailable offline:** download or import a supported map under
  **Offline maps** before going offline. Do not remove the only regional map
  while testing another download.
- **Update or launch failure:** keep the app installed and preserve its backup.
  Confirm the bundle/signing identity before retrying an in-place installation.

For a bug report, include the app/build version, connection method, whether the
screen was locked and the visible error. Do not send guardian passwords, SIP
passwords, Apple credentials or private location history.

### neXt preview: sending through a mailbox

In the separate neXt iOS preview, open **Offline mailbox** and save the relay's
propagation address. Receiving checks do not automatically enable sending.
**Use mailbox when a direct message fails** is off by default. If you enable it
and save, Automatic delivery can use that relay when a known recipient is
offline; the Propagated delivery choice uses the same saved opt-in. The relay
holds encrypted content and can observe delivery metadata. A verified contact
identity must already be known, so an address alone is insufficient for an
offline first message.

**Sent** means the relay accepted the message. It does not prove the recipient
received or read it. **Delivered** is reserved for a recipient delivery proof.
Turning this option off prevents new fallback attempts; it cannot recall a
message already accepted by a relay. Development builds keep a private signed restart record for an ordinary
message once it has entered Sending. When neXt runs again with a connected
interface, it can retry that original message identifier, including its files
and photos. Deleting the conversation cancels its saved send. Blocking is checked
again, a changed or disabled mailbox cannot receive a pending propagated send,
and location updates are never replayed. Old unsent messages created before
this journal existed remain failed; they cannot be safely reconstructed from
preview text alone. This recovery runs while the app executes and does not
wake a fully suspended device.

### neXt preview: location and map updates

Location sharing starts **Disabled**. In neXt Settings, choose Browser GPS for
an explicit device fix, or Manual for coordinates you enter yourself. Reviewing
the permission guide or opening the map does not send your position. To send it,
open a conversation and choose the location action, then confirm the recipient.
The native **Location sharing** panel lets you select Reticulum recipients and
choose 15 minutes, one hour, or until stopped. **Continue with the screen locked**
is off by default and is saved separately for each started session. Start while
neXt is open and accept While Using the App location permission if requested.
iOS displays its location indicator during background sharing. Foreground-only
sessions pause when locked; cold starts do not resume GPS without your action.

Use **Stop sharing** in the conversation, **Stop all sharing**, or the native
panel to end a session. Expiry keeps the original deadline even if sending is
waiting for a route. Updates are limited to once a minute while moving and every
five minutes when stationary. Both simulators have proved the actual native GPS
update, signed Reticulum receipt and chat Stop path. Actual neXt iPad locked
sharing still needs qualification; Family's separate device result does not
establish neXt's result. Existing Manual and MeshCore foreground controls remain available.
Development builds also list saved MeshCore users whose private location sharing
permission is already enabled in the MeshCore contact controls. Starting a native
session does not enable that underlying permission. Each target uses its full
radio identity, private user key and current sharing-permission revision. Turning
that permission off and on requires selecting and starting the recipient again.
These sessions use encrypted direct messages, never a room or channel. The
existing chat/global Stop buttons also stop native MeshCore sharing. Real-radio
locked sharing in neXt still needs verification before public release.

Received signed location updates appear on the map with their timestamp. They
do not create message alerts, unread chats or empty chat bubbles. Location data
is not sent through mailbox fallback, where delayed coordinates could become
misleading. Disabling location sharing while a fix is waiting for a route
cancels that pending submission.

### neXt recipient mailbox alerts (development preview)

In neXt, open **Offline mailbox → Recipient mailbox alerts**. Choose a saved
Reticulum contact, then enter the HTTPS alert provider, audience and propagation
address supplied by that recipient. Save explicitly; leaving this form does not
enable a draft route. **Remove recipient alerts**, or deleting the contact,
revokes the route. Unsaved drafts stay separate for each contact while the
editor is open. No provider request is made by opening or saving this form.

Use the same propagation relay for sending and for the recipient's mailbox. A
signed hint is sent only after that exact relay accepts an encrypted message.
Direct delivery sends no hint. The hint contains public routing metadata and an
encrypted packet identifier, without text or attachments. Enrollment secrets
and Apple device tokens are receiving-side credentials; never enter or share
them in this sender form.

This sender integration does not make the current personal-signed neXt preview
receive Apple push alerts. Receiving-side enrollment, Apple push entitlements
and a functioning provider remain separate requirements. Ordinary TCP or SIP
traffic cannot guarantee that a fully suspended iPhone or iPad wakes.

### neXt receiving mailbox alerts (development source)

After saving an offline mailbox, open **Offline mailbox → Mailbox push alerts**.
The chosen provider supplies its HTTPS address and private enrollment code.
Select which verified saved Reticulum contacts may send alerts, then explicitly
enable the service. The code is stored only in neXt’s private Keychain. New
phonebook contacts do not automatically receive push permission. Saved contact
removals and Apple token changes are synced while neXt runs.

Personal-signed previews cannot enable Apple push alerts. Their radio
notifications and ordinary mailbox retrieval remain available. A future
push-enabled signed build must use a matching Apple profile, provider topic and
APNs environment. Apple enrollment remains on hold; real APNs delivery has not
been qualified. Opening the settings does not request permission or upload data.

The provider and Apple receive a generic alert rather than message text. Tap it
to open Messages and retrieve encrypted mail. This does not guarantee silent
retrieval while fully suspended or wake incoming calls. **Turn off push alerts**
stays pending until the provider confirms removal; reopen neXt online or use
Retry if needed. Family’s enrollment, account and settings remain separate.

### neXt conversation folders and pins (development source)

Open **Messages → Conversations**. Use **Create folder** beside Folders to
organize conversations. A conversation’s context menu lets you pin it or move
it into a folder. Select **All messages**, **Uncategorized**, or a named folder
to change the view. Search and the Unread, Failed and Attachments filters apply
to the conversation list. Pins appear before ordinary conversations, including
when the list spans multiple pages.

The folders menu exports and imports folder names and assignments in neXt’s
JSON format. Imported folder identifiers are matched by name rather than
replacing unrelated existing folders. A rejected import preserves the previous
state. Reimporting an unchanged assignment preserves its timestamps. Removing
a folder moves its assignments to Uncategorized and does not delete contacts,
messages or pins. These local labels never approve calls, add contacts, enable
location sharing or authorize mailbox push senders.

The private backend and archived-interface browser checks have passed. Native
folder interaction and real-device sharing/pickers still need qualification.

### neXt local history deletion (development source)

In Conversations, use selection mode to select chats, choose **Delete**, then
confirm. Contacts remain available, and a fresh signed message creates a new
conversation. Folder assignments and pins for the deleted chats are cleared;
the folders themselves remain. Deleting history is a local action: copies
already received by another device and files exported to Files remain there.

The app retains only local deleted-packet identifiers to ignore late delivery
callbacks and repeated copies of those packets. Deleted content is removed
from the message history and attachment endpoints. A failed database write
preserves the previous chats, notification state and folder assignments.

### neXt voice notes and contact sharing

The development preview converts a recorded voice note to standard Opus/Ogg for
LXMF delivery. Incoming Opus notes use a bounded WAV playback preview on iOS;
the original encoded data is kept. Maximum encoded size and playback length are
separate limits: the WAV preview is limited to 8 MB of decoded PCM. A message
can be saved even when its recording is too long for inline playback. Native
microphone recording and playback controls still need physical UI verification.

**My contact QR** normally shares the plain Reticulum messaging address. In
builds with **Family contact**, choose that format to include your saved
nickname, public identity and voice address when Reticulum calling is enabled.
A Family guardian still reviews and approves the imported contact. Neither card
contains a private identity key, SIP password or Apple credentials.

### neXt contact codes and local blocking (development preview)

Open **My contact QR → Add contact** to scan a QR, choose a QR image, or paste a
Reticulum contact code. Review the name and address, then tap **Save contact**.
Scanning and reviewing do not approve or save a contact. Existing contacts are
shown for review without being renamed or added twice. Public identity keys
must match the supplied address. MeshCore and SIP details are handled in their
own service menus; this Reticulum importer does not silently approve them.

**Blocked destinations** applies to private messages and calls. Blocking removes
that contact's local history and cancels its location sessions and mailbox-alert
route. New blocked traffic is rejected before inbox records or notifications.
Unblocking allows future traffic; it does not restore removed history or restart
sharing. This is a local communication block, not a Reticulum transport
blackhole announcement.

### Recovering a stalled Reticulum send after reconnect (development source)

A live connection change can leave an LXMF direct message marked Sending after
its old delivery link has gone away. The development recovery waits for an
active replacement link, then lets LXMF continue the same queued packet. It
preserves the packet's identity, original retry budget and delivery callbacks.
It does not revive cancelled or completed messages, enable mailbox fallback or
requeue live location telemetry. Closing the app still does not create a
persistent outbound queue; the restart limitation above remains.

The separate iPad test completed signed messages and replies before and after
two full TCP retirements with the receiving peer using this recovery. The
unmodified receiver's stalled state was retained as the negative reference.
This is a private reconnect check, not a completed Wi-Fi/cellular or independent
public-provider failover test. No firewall settings were changed.

### Pending messages and offline recipients

The development neXt restart journal retains the recipient's public key beside
the original signed packet, so a recipient who is offline does not have to
announce again before an opted-in mailbox send can resume. neXt checks that
the public key belongs to the saved LXMF address before using it. This retains
no recipient private key and sends no additional identity data. Older pending
records without that public key remain readable and may still need a verified
announce. Exact source `e048311` passed both full simulator suites and the physical iPad restart test with the original signed message, attachment and photo. This does not qualify fully suspended delivery.


### neXt RNCP files (development preview)

RNCP is separate from ordinary chat attachments. Open **More → Tools → RNCP**.
The receiver must start its RNCP listener, approve the sending Reticulum
identity and supply the RNCP receive address. A contact's LXMF messaging
address is not an RNCP receive address.

Use **Browse** to select a file from Files, then send it to that receive
address. The iOS preview imports a copy into its own storage; it does not
request access to the device's whole filesystem. Fetching a remote file also
requires the other side to enable fetching and share that file explicitly.
Disabling the listener does not delete files already received.

Open **Received files** to share or save a received copy. Development source
also provides **Remove → Remove file** with confirmation; **Keep file** cancels.
Removal affects only that copy inside neXt. A copy saved to Files or another
app remains. A file cannot be removed while it is being sent, waiting for a
send slot or streaming to the save/share action. Use **Refresh** after the
transfer finishes.

Keep neXt visible during large transfers. iOS may pause it when locked or in
the background. If an interrupted transfer fails, reopen the app and retry;
this preview does not promise resumable RNCP transfers after termination.
These tools do not change chat attachment limits or enable mailbox delivery.
