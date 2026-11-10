# neXt Family for iOS

This first iOS target runs the shared Family interface in a native WebKit view. It uses sample contacts, conversations, rooms, and map positions. The banner identifies preview mode on every screen. The app serves its interface and tiles from the bundle and blocks external navigation and network requests.

## Run the preview on a Mac

1. Open Xcode and install an iOS 17 or newer Simulator runtime. Install [XcodeGen](https://github.com/yonaskolb/XcodeGen).
2. From this directory, run `xcodegen generate` and open `FamilyPreview.xcodeproj`.
3. Select the **FamilyPreview** scheme and an iPhone Simulator, then run.
4. Check the contacts, day and night themes, a sample room, and the bundled map. Check that the preview banner stays visible. To test on an iPhone, select your development team in Signing & Capabilities first.

The Xcode target references the existing Family web assets. Changes to those assets are shared with Android.

## First live milestone

Bundle a supported CPython runtime and the existing Family backend, then bring up first-run guardian setup and foreground Reticulum TCP messaging on an iPhone. Keep approved-contact checks in the backend. After that, test BLE companion connections and background delivery on a physical device. SIP audio and incoming calls, notifications, location sharing, and signed distribution need iOS integrations.

[Python embedding on iOS](https://docs.python.org/3.14/using/ios.html) · [Apple distribution guide](https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases/)
