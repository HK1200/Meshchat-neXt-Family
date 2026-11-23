# Family privacy and reporting

Guardians choose the approved people, addresses, rooms and services. Approved rooms are shared spaces. Room participants can see room posts even when they are not private contacts.

Family stores its contacts, configuration and message history on the device. SIP and room credentials use the device’s protected storage. The configured networks and providers handle the traffic you choose to send. Private location sharing is optional and sends updates to approved contacts over the selected compatible service. Check who is approved before enabling it. On iOS, locked-screen location sharing is off by default and can be enabled only in Guardian settings. An active session starts while Family is open and displays the system location indicator. Saving the preference alone does not start location collection.

An internet connection may be used for Reticulum TCP, SIP, map downloads, and update checks. Update checks use this project’s GitHub Releases repository. An offline map stays on the device after it is downloaded or imported.

Report a reproducible problem with the Family version, operating system version and affected service. Remove passwords, private keys, contact addresses, message contents and personal locations from logs or screenshots before attaching them. Use [private vulnerability reporting](../SECURITY.md) for a security issue. [Issue tracker](https://github.com/HK1200/Meshchat-neXt-Family/issues)

## Optional mailbox alerts

Family does not choose or enable an alert provider automatically. In a compatible
push-enabled iOS build, a guardian can choose an HTTPS provider and explicitly
enable mailbox alerts. Personal-signed development previews cannot receive live
Apple push alerts. Ordinary radio notifications and mailbox retrieval are
separate features.

The chosen provider receives the device's Apple push token, public Reticulum
address and approved senders' public keys. An enrollment code authenticates
updates to that registration. A configured sender sends a signed alert hint
after the selected relay accepts encrypted mail. The hint contains public
routing addresses, an encrypted-message identifier, a timestamp and signature.
It contains no message text, file/photo contents or location coordinates. Apple
receives the push token and a generic alert, without a contact name or message
content. Network operators may also see connection metadata.

Turning alerts off completes after the provider acknowledges removal; offline
removal remains pending until it can be retried. The current reference provider
removes the active token and approved-sender record on acknowledgment and
automatically expires delivery metadata after about one hour while running.
Other providers and operator-managed logs, configuration and backups may have
different retention. Turning alerts off does not delete mail already held by a
relay or copies already received by another person.

Rooms and Relay Chat are excluded from Google Play and planned App Store
editions. GitHub editions can retain those guardian-controlled features.

## Optional incoming Reticulum call alerts

Call alerts are separate from mailbox alerts and are off until a guardian
explicitly enrolls a compatible push-enabled iOS build with a chosen HTTPS
provider. The guardian selects individual approved, identity-verified voice
contacts. The app pauses alerts if those approvals, the device identity or
calling permissions change. A guardian must review the selection to resume.
Personal-signed previews cannot receive live Apple call pushes.

The provider receives an Apple call push token, the recipient's public identity
key, selected callers' public voice addresses and an enrollment credential
used to authenticate registration and removal. The installation marker stays
on the device. It does
not receive the private identity key, guardian password, contact names, message
contents, audio, photos or location coordinates. A sender explicitly configured
for this route sends a signed, short-lived call intent. The provider forwards
an encrypted call hint through Apple. The receiving device verifies the sender,
current guardian approval, expiration and replay history before starting call
signaling. The existing Reticulum connection carries the call's audio.

Turning call alerts off stops local call-wake admission immediately. If the
provider cannot be reached, removal remains pending and can be retried from
Guardian settings. The reference provider expires call intents after their
short validity window; provider logs and backups may retain connection or
registration metadata according to the operator's policy. This feature does
not provide suspended SIP calling or guarantee delivery without network access.
