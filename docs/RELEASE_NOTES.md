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
