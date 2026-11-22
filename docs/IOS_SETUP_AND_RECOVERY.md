# Family on iPhone and iPad: setup and recovery

This guide describes the native live Family app. The sample **FamilyPreview**
app is a separate interface demonstration. The separate **Family Mailbox Test**
install is for testing; keep an existing regular Family install intact when
trying it. The neXt iOS prototype is also separate and currently supports
Reticulum messaging, rather than every desktop/Android neXt feature.

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
message already accepted by a relay. An interrupted unsent message is still
shown as failed after an app restart; persistent outbound retry is not yet
implemented in this preview.

### neXt preview: location and map updates

Location sharing starts **Disabled**. In neXt Settings, choose Browser GPS for
an explicit device fix, or Manual for coordinates you enter yourself. Reviewing
the permission guide or opening the map does not send your position. To send it,
open a conversation and choose the location action, then confirm the recipient.
Current timed sessions run while the interface is active and stop when it is
hidden; do not rely on locked-screen sharing in the neXt preview yet.

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
