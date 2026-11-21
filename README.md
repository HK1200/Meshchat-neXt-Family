# neXt Family

**[Download Family v0.6.29 for Android (ARM64)](https://github.com/HK1200/Meshchat-neXt-Family/releases/download/v0.6.29/MeshchatNextFamily-v0.6.29-android-arm64.apk)**

neXt Family is an Android companion to Meshchat neXt. A guardian approves the people and rooms the device can reach, then locks those settings. Family members can call or text an approved person from a simple contact list.

- **Reticulum** provides LXMF text, LXST calling on suitable links, and approved Relay Chat rooms. Use an internet TCP peer, an RNode, or both.
- **MeshCore** provides private text and approved room servers through a separate companion radio.
- **SIP** provides extension calls with your own SIP provider account.

You can enable any combination. Family keeps these services separate and uses an available route supported by the contact and the action. Automatic texting can retry over another approved service after a failed or unconfirmed attempt. A person can also choose a service manually.

## Install and set up

Use an ARM64 phone or tablet running Android 8.0 or later. If you are moving from v0.6.19 or earlier, use the one-time guardian profile transfer before setting up the new app. [Transfer instructions](docs/INITIAL_SETUP.md#transfer-from-family-v0619-or-earlier). [v0.6.29 release notes](https://github.com/HK1200/Meshchat-neXt-Family/releases/tag/v0.6.29) · [Initial setup](docs/INITIAL_SETUP.md)

The GitHub edition includes guardian-approved rooms and Relay Chat. The Google Play edition omits those features and receives updates through Google Play. Both editions use the same app ID, release version and signing identity.

The GitHub edition can show updates on its home screen. **Install now** downloads the APK from this repository, verifies it, and opens Android’s installer. Android handles the installation approval.

## Project information

- [Build instructions](docs/BUILDING.md)
- [Privacy and reporting](docs/PRIVACY.md)
- [Report a security vulnerability](SECURITY.md)
- [Third-party software and map credits](docs/NOTICES.md)
- [Meshchat neXt](https://github.com/HK1200/Meshchat-neXt)

## iPhone and iPad development

The `ios/` directory contains the native iPhone and iPad port and simulator checks. Unsigned archives and separate personal test installs are available during development; this is not an App Store release.
