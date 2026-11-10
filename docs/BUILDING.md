# Build Family for Android

The app ID is `org.meshchat.family.preview`. Keeping it stable lets production-signed updates preserve data. The current Android build targets ARM64, compiles with Android SDK 35, and uses Java 17 and Python 3.11 for Chaquopy.

1. Install JDK 17, Android SDK Platform 35 and the Android build tools. Configure `ANDROID_HOME` or create a local `local.properties` pointing to the SDK.
2. Use the pinned ARM64 Android wheels listed in `app/build.gradle`. Set `FAMILY_ANDROID_VENDOR_DIR` to the directory holding them. An adjoining Meshchat neXt checkout’s prepared `android/vendor` directory is the default. See neXt’s Android build instructions for its wheel preparation. [neXt Android build instructions](https://github.com/HK1200/Meshchat-neXt/blob/v0.1.8/android/README.md)
3. Set `FAMILY_ANDROID_PYTHON` to a Python 3.11 interpreter if `python3.11` is unavailable on your path.
4. Run `./gradlew :app:assembleRelease :app:lintRelease`. After dependencies are cached, use `--offline`. The unsigned APK is under `app/build/outputs/apk/release/`.

Production packages are signed outside Gradle. To install over an existing production release, Android requires the same app ID and compatible signing certificate. The release updater also verifies the downloaded APK’s size, SHA-256, version, app ID, and certificate before opening Android’s installer.

For Codec2, verify the Android wheel’s `pycodec2/pycodec2.so` exports `PyInit_pycodec2` with the Android NDK’s `llvm-readelf --dyn-syms`. A wheel can contain `libcodec2.so` and still fail to import if that export is missing. Before shipping, test an actual Codec2 encode/decode on the target device.
