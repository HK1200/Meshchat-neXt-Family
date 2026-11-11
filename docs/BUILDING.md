# Build Family for Android

The production Android app ID is `org.meshchat.family`. Updates signed with the production certificate can install over versions with that same ID. The current Android build targets ARM64, compiles with Android SDK 35, and uses Java 17 and Python 3.11 for Chaquopy.

1. Install JDK 17, Android SDK Platform 35 and the Android build tools. Configure `ANDROID_HOME` or create a local `local.properties` pointing to the SDK.
2. Use the pinned ARM64 Android wheels listed in `app/build.gradle`. Set `FAMILY_ANDROID_VENDOR_DIR` to the directory holding them. An adjoining Meshchat neXt checkout’s prepared `android/vendor` directory is the default. See neXt’s Android build instructions for its wheel preparation. [neXt Android build instructions](https://github.com/HK1200/Meshchat-neXt/blob/v0.1.8/android/README.md)
3. Set `FAMILY_ANDROID_PYTHON` to a Python 3.11 interpreter if `python3.11` is unavailable on your path.
4. Run `./gradlew :app:assembleRelease :app:lintRelease`. After dependencies are cached, use `--offline`. The unsigned APK is under `app/build/outputs/apk/release/`.

Production packages are signed outside Gradle. To install over an existing production release, Android requires the same app ID and compatible signing certificate. The release updater also verifies the downloaded APK’s size, SHA-256, version, app ID, and certificate before opening Android’s installer.

For Codec2, verify the Android wheel’s `pycodec2/pycodec2.so` exports `PyInit_pycodec2` with the Android NDK’s `llvm-readelf --dyn-syms`. A wheel can contain `libcodec2.so` and still fail to import if that export is missing. Before shipping, test an actual Codec2 encode/decode on the target device.

The reproducible repair tool accepts the pinned wheel, matching NumPy wheel, the per-ABI Chaquopy Python target ZIP, and the Android NDK LLVM toolchain. Run it for each needed ABI, preserve its provenance file, then build with the repaired private vendor directory.

[Codec2 repair tool](https://github.com/HK1200/Meshchat-neXt/blob/v0.1.11/scripts/android/rebuild-pycodec2-wheel.py)

## Transition from the original Android package

Family v0.6.19 and earlier used `org.meshchat.family.preview`. Android treats `org.meshchat.family` as a separate app and assigns it separate private storage. Installing the new package starts guardian setup. Keep the original app installed if you need its settings, messages, or Reticulum identity. An in-app transfer between the two packages requires a migration feature.

Publish the production APK to a versioned release and upload its `family-update.json` to the `family-stable` release. The manifest must declare `org.meshchat.family` and the versioned tag that hosts the APK. Include the original package's last compatible manifest as `family-update.json` on each release marked Latest during the transition. The new package reads its separate `family-stable` feed. The installer verifies that a downloaded APK matches the installed app ID, version, and signing certificate.
