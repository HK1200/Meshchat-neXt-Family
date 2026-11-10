# neXt Family for iOS

The iOS target runs the Family v0.6.14 interface in a native WebKit view for iPhone and iPad. On narrow windows contacts stay in a single column. Wider windows show two contact columns and give the map more room. It uses sample contacts, conversations, rooms, and map positions. The banner identifies preview mode on every screen. The app serves its interface and tiles from the bundle and blocks external navigation and network requests.

## Run the preview on a Mac

1. Open Xcode and install an iOS 17 or newer Simulator runtime. Install [XcodeGen](https://github.com/yonaskolb/XcodeGen).
2. From this directory, run `xcodegen generate` and open `FamilyPreview.xcodeproj`.
3. Select the **FamilyPreview** scheme and run it on both an iPhone and an iPad Simulator.
4. Check the contacts, day and night themes, a sample conversation, a room, and the bundled map. Rotate the iPad and resize its window to verify that the layout returns to one column in a narrow window. Check that the preview banner stays visible. To run on a physical iPhone or iPad, select your development team in Signing & Capabilities.

The Xcode target references the shared Family web assets. The adaptive stylesheet is bundled only in the iPhone and iPad preview.

## First live milestone

Bundle a supported CPython runtime and the existing Family backend, then bring up first-run guardian setup and foreground Reticulum TCP messaging on iPhone and iPad. Keep approved-contact checks in the backend. After that, test BLE companion connections and background delivery on a physical device. SIP audio and incoming calls, notifications, location sharing, and signed distribution need iOS integrations.

[Python embedding on iOS](https://docs.python.org/3.14/using/ios.html) · [Apple distribution guide](https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases/)
