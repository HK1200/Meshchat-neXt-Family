# Private Android call-route verification

This test runs the actual packaged Python backend and native signing library on an
Android device without opening an Activity or initializing a user's profile. It
requires a fresh, disposable `org.meshchat.family.setuptest` installation and
refuses regular application IDs and non-debuggable builds. The test APK cannot
ship in a release APK.

Build both packages from the workspace's media-aware environment:

```sh
./gradlew --no-daemon -PisolatedSetupTest :app:assembleDebug :app:assembleDebugAndroidTest
```

Before installation, verify that neither `org.meshchat.family.setuptest` nor
`org.meshchat.family.setuptest.test` already exists. Preserve an existing test
installation rather than overwriting it. Use an explicit device serial for every
ADB command. Install the debug target and test APK, then run:

```sh
adb -s DEVICE_SERIAL shell am instrument -w \
  org.meshchat.family.setuptest.test/org.meshchat.family.preview.FamilyTestInstrumentation
```

Success requires `INSTRUMENTATION_CODE: -1`, no `failure` result, and every boolean
in `family_call_route_proof` to be true. An ADB exit status alone is insufficient.
The fixture verifies Guardian authentication, private route save/read/removal,
atomic rejection of invalid providers, actual Android signatures, ordered wake
and cancellation, and no hint after route removal. Socket creation is forbidden;
no provider, Reticulum peer or radio is contacted. Only temporary in-memory
identities and app-cache fixture files are used, and fixture files are removed.

Uninstall only the two disposable packages created for this test, even if the
test fails. Compare regular-app version, signature and installation metadata
before and after. This comparison does not constitute a byte-for-byte audit of
regular app data, which this harness never opens.
