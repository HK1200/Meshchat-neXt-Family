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
