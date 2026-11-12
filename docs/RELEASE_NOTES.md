# neXt Family v0.6.25

- Show each configured TCP peer once and keep offline peers visible.
- Changing between RMAP ports 4242 and 4343 keeps WashMesh and Chicago configured and preserves their live connections.

---

# neXt Family v0.6.24

- The default Reticulum TCP setup keeps connections to RMAP, WashMesh, and Chicago available in parallel.
- Existing RMAP profiles without a custom backup pick up the two additional peers automatically. Guardian settings shows each connection’s status and accepts a custom backup.

---

# neXt Family v0.6.23

- Keep MeshCore room posting available when the companion clock is far ahead or unreadable.
- Install over v0.6.22 to keep your existing setup.

---

# neXt Family v0.6.22

- Show **My contact QR** under **Guardian settings → Contacts**. Scan it on another device to review and approve the Family member's public contact details.
- Send local or flood MeshCore adverts from the companion settings.
- Review Android permissions during setup or under **Guardian settings → Security → Permission checkup**.
- Enable full-screen incoming call alerts to answer or decline approved SIP and Reticulum calls from the Android lock screen. Android's lock-screen notification settings also control when message alerts appear.
- The Android status bar follows Family’s day and night mode.
- The one-time guardian transfer remains available in v0.6.21.

---

# neXt Family v0.6.21

- Move your Family profile from the old Android package to the current one with guardian approval. The transfer preserves settings, approved contacts, messages, attachments, offline maps, and the Reticulum identity.
- Install the Transfer APK over v0.6.19 or earlier and install the regular v0.6.21 APK alongside it. Start the transfer in the old app under **Guardian settings → Security** before setting up the new app. See the [transfer instructions](INITIAL_SETUP.md#transfer-from-family-v0619-or-earlier).
- This is the one-time migration release. Current package users can install the regular APK as an in-place update.

---

# neXt Family v0.6.20

- The public Android package ID is now `org.meshchat.family`. Android installs it as a separate app alongside v0.6.19 and earlier. Complete guardian setup in the new app. Keep the previous app to retain access to its settings, contacts, messages, and Reticulum identity.
- Automatic connection recovery after a reboot or update defaults to off. Guardians can enable it under **Guardian settings → Security**.
- Future versions of the new package use the dedicated Family update feed.

---

# neXt Family v0.6.19

- Keep the Android message field visible above the docked keyboard and preserve the draft during live conversation updates.
- Send files and photos in approved Reticulum conversations. Select multiple attachments, preview photos, and save received attachments.
- Choose Low, Medium, High, or Original photo quality. Family previews incoming Reticulum photos inline.
- Guardian settings offer a 10 MB default direct receive limit, presets up to 1 GB, and a custom limit. Android sends up to 9.95 MB of attachments per direct message and asks for confirmation above 900 KB.

Use **Install now** in Family or install the ARM64 APK over the existing public version to retain your settings.

---

# neXt Family v0.6.18

- Restore the Reticulum microphone speech filters and automatic level control that the Android capture bridge previously bypassed.
- Correct LXST 0.5.4 amplitude gain targets and limits to use amplitude dB conversion.
- Route Android volume buttons to call volume during calls.
- Ignore delayed hang-up actions for ended calls while protecting a newer call.
- Add a speaker button to Reticulum calls. Answering from the Android call notification opens Family and handles microphone permission.

The speech-level changes pass quiet and loud signal regression checks. A live listening test on the two OnePlus 13 phones remains necessary.

# neXt Family v0.6.17

- Messaging, Reticulum calling, and SIP share one Android connection status card while idle. Incoming call controls and active location sharing keep their own notices.
- Repair the Android Codec2 extension required by Low Bandwidth and Ultra Low Bandwidth Reticulum calls.
- Automatically sign into approved MeshCore rooms with their saved passwords when the companion connects. Leaving a room screen keeps the session.

---

# neXt Family v0.6.16

- Day and Night mode respond during connection checks, use a larger button, and remember the selected appearance.
- Reticulum calls follow call-quality changes from neXt, including low-bandwidth Codec2 profiles.
- Reticulum messaging and voice announcements use the device name set in Guardian settings → Security.
- Tap a Family Map pin to see when that location was last updated.

Install this ARM64 APK over the previous public release to keep your settings and approved contacts. [Initial setup guide](https://github.com/HK1200/Meshchat-neXt-Family/blob/v0.6.16/docs/INITIAL_SETUP.md)

---

# neXt Family v0.6.15

- Reticulum TCP reconnects after a failed write and when Android switches networks.
- Reticulum calls match the negotiated microphone frame size and buffer incoming audio to reduce gaps.
- Guardian settings shows **Install now** when an update is available. Family resumes the Android install flow after the user enables install permission.

The ARM64 APK uses the same signing certificate as previous public Family releases for in-place upgrades. [Initial setup guide](https://github.com/HK1200/Meshchat-neXt-Family/blob/main/docs/INITIAL_SETUP.md)

---

# neXt Family v0.6.14

- Automatic texting retries over the other available approved service when Reticulum or MeshCore fails or the receipt window expires. One chat entry tracks the attempt. The receiving device may see two copies if the first receipt was lost. MeshCore accepts messages of up to 160 UTF-8 bytes.
- In an approved contact, attach a MeshCore key by scanning a companion QR code, choosing a QR image, or searching received MeshCore clients. Reticulum discovery includes unapproved messaging clients for guardian review and handles busier TCP peers.
- Set the Reticulum device name under **Guardian settings → Security**. Family announces its available Reticulum text and voice endpoints on startup, on reconnect, and hourly.
- New RNode profiles have editable starting values, and the frequency field accepts MHz, kHz, or Hz. New SIP accounts prefill the editable Hams Over IP server and port. A numeric SIP extension in a contact uses your configured SIP provider.
- Guardian settings can show the password while entering it and share the installed APK. The QR scanner keeps directions and results near the camera preview.

Download the ARM64 APK for Android 8.0 or later. Public v0.6.12 installations can upgrade in place with the production-signed APK. [Initial setup guide](https://github.com/HK1200/Meshchat-neXt-Family/blob/main/docs/INITIAL_SETUP.md)

---

# neXt Family v0.6.12

The first production-signed Android release of neXt Family.

- Guardian-approved contacts and rooms, with a password-protected setup area.
- Reticulum text, calls and Relay Chat, MeshCore private text and room servers, and SIP calls. Enable the services you use.
- Contact QR import, discovery, profile pictures, and automatic or manual connection selection.
- Android message and call notifications, day and night mode, radio battery indicators, and offline maps with approved location sharing.
- Updates offered on the home screen through this project’s GitHub Releases.

Download the ARM64 APK for Android 8.0 or later. Start with the setup guide to enable a service and approve a first contact. [Initial setup guide](https://github.com/HK1200/Meshchat-neXt-Family/blob/main/docs/INITIAL_SETUP.md)
