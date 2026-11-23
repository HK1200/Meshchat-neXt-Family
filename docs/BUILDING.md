# Build Family for Android

The production Android app ID is `org.meshchat.family`. Updates signed with the production certificate can install over versions with that same ID. The current Android build targets ARM64, compiles with Android SDK 35, and uses Java 17 and Python 3.11 for Chaquopy.

1. Install JDK 17, Android SDK Platform 35 and the Android build tools. Configure `ANDROID_HOME` or create a local `local.properties` pointing to the SDK.
2. Use the pinned ARM64 Android wheels listed in `app/build.gradle`. Set `FAMILY_ANDROID_VENDOR_DIR` to the directory holding them. An adjoining Meshchat neXt checkout’s prepared `android/vendor` directory is the default. See neXt’s Android build instructions for its wheel preparation. [neXt Android build instructions](https://github.com/HK1200/Meshchat-neXt/blob/v0.1.8/android/README.md)
3. Set `FAMILY_ANDROID_PYTHON` to a Python 3.11 interpreter if `python3.11` is unavailable on your path.
4. On Linux, install Android NDK `27.3.13750724` and run `python3 scripts/android/provision-expat.py --abis arm64-v8a`. This verifies official inputs and rebuilds only Python’s XML parser with the pinned Expat 2.10.0 security backport; all other Python target bytes are checked unchanged. The generated Maven inputs and provenance stay under the ignored `.expat-runtime-maven/` directory.
5. Run `./gradlew :app:assembleRelease :app:lintRelease`. After dependencies are cached, use `--offline`. The unsigned APK is under `app/build/outputs/apk/release/`.

Production packages are signed outside Gradle. To install over an existing production release, Android requires the same app ID and compatible signing certificate. The release updater also verifies the downloaded APK’s size, SHA-256, version, app ID, and certificate before opening Android’s installer.

For Codec2, verify the Android wheel’s `pycodec2/pycodec2.so` exports `PyInit_pycodec2` with the Android NDK’s `llvm-readelf --dyn-syms`. A wheel can contain `libcodec2.so` and still fail to import if that export is missing. Before shipping, test an actual Codec2 encode/decode on the target device.

The reproducible repair tool accepts the pinned wheel, matching NumPy wheel, the per-ABI Chaquopy Python target ZIP, and the Android NDK LLVM toolchain. Run it for each needed ABI, preserve its provenance file, then build with the repaired private vendor directory.

[Codec2 repair tool](https://github.com/HK1200/Meshchat-neXt/blob/v0.1.11/scripts/android/rebuild-pycodec2-wheel.py)

## Transition from the original Android package

Family v0.6.19 and earlier used `org.meshchat.family.preview`. Android treats `org.meshchat.family` as a separate app and assigns it separate private storage. Installing the new package starts guardian setup. Keep the original app installed if you need its settings, messages, or Reticulum identity. An in-app transfer between the two packages requires a migration feature.

Publish the production APK to a versioned release and upload its `family-update.json` to the `family-stable` release. The manifest must declare `org.meshchat.family` and the versioned tag that hosts the APK. Include the original package's last compatible manifest as `family-update.json` on each release marked Latest during the transition. The new package reads its separate `family-stable` feed. The installer verifies that a downloaded APK matches the installed app ID, version, and signing certificate.

## Bundled Android binaries

Family keeps these inputs in the repository so its offline Android build can use them. Run `sha256sum --check gradle/android-binaries.sha256` from the repository root before building. CI also checks the Gradle wrapper against Gradle's published list. If a binary is updated, verify its source and update its checksum and corresponding notices together.

| File | Verified origin |
| --- | --- |
| `gradle-wrapper.jar` | Official Gradle 8.13 wrapper JAR. The JAR and distribution ZIP checksums match the [Gradle release checksums](https://gradle.org/release-checksums/). |
| `usb-serial-for-android-3.8.1.aar` | Byte-for-byte match to the [JitPack 3.8.1 artifact](https://jitpack.io/com/github/mik3y/usb-serial-for-android/3.8.1/usb-serial-for-android-3.8.1.aar), built from the [USB Serial for Android release](https://github.com/mik3y/usb-serial-for-android/releases/tag/v3.8.1). |
| `libffi.so` | Byte-for-byte match to `chaquopy/lib/libffi.so` in [Chaquopy's libffi 3.3 build 3 ARM64 wheel](https://chaquo.com/pypi-13.1/chaquopy-libffi/). |
| `libc++_shared.so` | Byte-for-byte match to the ARM64 shared C++ runtime in [Android NDK r27d](https://github.com/android/ndk/releases/tag/r27d), SDK revision `27.3.13750724`. |
| `libopus.so` | Byte-for-byte match to the neXt ARM64 Android build of Opus 1.5.2. The library identifies itself as `libopus 1.5.2`. See [neXt's Opus build script](https://github.com/HK1200/Meshchat-neXt/blob/de618055557c72bbea5a84ba34288252c43cc4a5/scripts/android/provision-opus.py). |
| `libnext_sip.so` | Byte-for-byte match to the neXt ARM64 Android build. The [neXt SIP build script](https://github.com/HK1200/Meshchat-neXt/blob/59ea9cd032596c249bd75f07cc47aa31c61ae442/scripts/android/build-sip.py) pins Baresip and re 4.12.0, Mbed TLS 3.6.7, Android NDK r27d and Opus 1.5.2. This build uses mono PCM for the Android audio adapter while retaining standard Opus RTP signaling. |

The source archive checksums for the SIP dependencies matched the neXt build script. Hash checks identify the input binaries. Build output can also be compared against a fresh reproduction from source.

The Android package bundles their notices under `assets/notices`. See [third-party notices](NOTICES.md).

Before signing, run `python3 scripts/android/verify-apk-expat.py --provenance .expat-runtime-maven/PROVENANCE.json --abis arm64-v8a app/build/outputs/apk/release/app-release-unsigned.apk` to verify the parser actually packaged in the APK.

## Release-feed checks

Keep the two package histories separate. Every release marked Latest must carry
`family-update.json` copied unchanged from the approved v0.6.21 transfer release
for `org.meshchat.family.preview`. Its `family-production-update.json` describes
the new regular APK. The `family-stable` release's `family-update.json` is a copy
of that production manifest for `org.meshchat.family`. Never replace the Latest
legacy manifest with the production manifest: older installed apps reject it.

Before publishing a draft, run
`python3 scripts/ci/family_release_feeds.py --tag v0.6.30 --preflight`.
Publish the versioned assets without marking the release Latest, update the
production `family-stable` manifest, then mark the new version Latest. Finally,
run `python3 scripts/ci/family_release_feeds.py` or dispatch **Published Family
updater verification**. The check validates both package IDs, frozen transfer
metadata, APK sizes and GitHub's available SHA-256 digests. It does not replace
APK certificate verification or an in-place installation test.


## Inspect the separate neXt iOS development preview

A Debug build of the separate neXt preview can expose its embedded web interface
through Apple's Web Inspector when launched with `--inspect-web-interface`.
The option is off by default and is not saved. Relaunch without the argument to
turn it off. It does not apply to regular Family or provide access to native
Guardian forms.

The iPad must permit Web Inspector in its Safari advanced settings, and the
computer must already be trusted. The launch option does not enable either of
those device settings. The device-tools Web Inspector commands can then inspect
the preview's web page for development checks. Keep inspector access limited to
the trusted development computer; the page can contain private conversations.

Release builds omit this launch option. The App Store archive gate rejects a
production executable containing it. Xcode and a live inspection check are
required before this developer capability is qualified.
