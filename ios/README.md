# neXt Family for iOS

The iOS target runs the Family v0.6.14 interface in a native WebKit view for iPhone and iPad. On narrow windows contacts stay in a single column. Wider windows show two contact columns and give the map more room. It uses sample contacts, conversations, rooms, and map positions. The banner identifies preview mode on every screen. The app serves its interface and tiles from the bundle and blocks external navigation and network requests.

## Run the preview on a Mac

1. Open Xcode and install an iOS 17 or newer Simulator runtime. Install [XcodeGen](https://github.com/yonaskolb/XcodeGen).
2. From this directory, run `xcodegen generate` and open `FamilyPreview.xcodeproj`.
3. Select the **FamilyPreview** scheme and run it on both an iPhone and an iPad Simulator.
4. Check the contacts, day and night themes, a sample conversation, a room, and the bundled map. Rotate the iPad and resize its window to verify that the layout returns to one column in a narrow window. Check that the preview banner stays visible. To run on a physical iPhone or iPad, select your development team in Signing & Capabilities.

The Xcode target references the shared Family web assets. The adaptive stylesheet is bundled only in the iPhone and iPad preview.

## Simulator smoke checks

On a Mac with Xcode, XcodeGen, and simulator runtimes installed, run `bash ios/test-preview.sh iPhone` and `bash ios/test-preview.sh iPad` from the repository root. Each opens the bundled preview and starts a sample conversation. The **Family iOS simulator** GitHub Actions workflow defines these two jobs and requires no signing credentials.

## Reticulum TCP runtime

The shared Python backend supports a standalone TCP-only mode through `initialize(folder, tcp_only=True)`. It keeps the first-run guardian password, approved contacts, discovery, and signed LXMF delivery in the same backend as Android. The preview's WebKit window still uses sample data.

With Python 3.11 or later, stage the runtime from the pinned `rns-1.5.7-py3-none-any.whl` using:

```sh
python3 ios/stage-runtime.py /path/to/rns-1.5.7-py3-none-any.whl ios/RuntimeBuild/staged
```

The staging script verifies the wheel hash and includes Family's bundled LXMF sources. It keeps Reticulum standalone, delays importing shared-instance IPC, and uses the internal crypto provider when external crypto is unavailable. On iOS, LXMF stamp generation runs in one process.

The loopback test in `tests/test_ios_tcp_runtime.py` starts two Family instances on a local Reticulum hub. Set `FAMILY_IOS_TCP_TEST_RUNTIME` to the absolute staged directory to exercise the staged clients with the iOS platform identifier and without optional Android and crypto modules.

## Next native milestone

Embed a CPython XCFramework in an Xcode target and bundle the staged modules. The C bridge in `ios/LiveRuntime` starts the backend in an isolated interpreter and exchanges UTF-8 JSON. It has been compiled and exercised on Linux. Link it to the iOS framework and use the app’s private Application Support directory for the state before connecting the native UI. Build and exercise foreground messaging on both simulators first. Physical-device tests come later for Bluetooth, camera, location, and app lifecycle. SIP audio, incoming calls, background delivery, and distribution need iOS integrations.

[Python embedding on iOS](https://docs.python.org/3.14/using/ios.html) · [Apple device and simulator testing](https://developer.apple.com/documentation/xcode/building-and-running-an-app)
