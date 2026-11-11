# neXt Family for iOS

The iOS target runs the shared Family interface in a native WebKit view for iPhone and iPad. On narrow windows contacts stay in a single column. Wider windows show two contact columns and give the map more room. It uses sample contacts, conversations, rooms, and map positions. The banner identifies preview mode on every screen. The app serves its interface and tiles from the bundle and blocks external navigation and network requests.

## Run the preview on a Mac

1. Open Xcode and install an iOS 17 or newer Simulator runtime. Install [XcodeGen](https://github.com/yonaskolb/XcodeGen).
2. From this directory, run `xcodegen generate` and open `FamilyPreview.xcodeproj`.
3. Select the **FamilyPreview** scheme and run it on both an iPhone and an iPad Simulator.
4. Check the contacts, day and night themes, a sample conversation, a room, and the bundled map. Rotate the iPad and resize its window to verify that the layout returns to one column in a narrow window. Check that the preview banner stays visible. To run on a physical iPhone or iPad, select your development team in Signing & Capabilities.

The Xcode target references the shared Family web assets. The adaptive stylesheet is bundled only in the iPhone and iPad preview.

## Simulator smoke checks

On a Mac with Xcode, XcodeGen, and simulator runtimes installed, run `bash ios/test-preview.sh iPhone` and `bash ios/test-preview.sh iPad` from the repository root. Each opens the bundled preview and starts a sample conversation. The **Family iOS simulator** GitHub Actions workflow runs the preview on both devices and requires no signing credentials.

## Reticulum TCP runtime

The shared Python backend supports a standalone TCP-only mode through `initialize(folder, tcp_only=True)`. It keeps the first-run guardian password, approved contacts, discovery, and signed LXMF delivery in the same backend as Android. The preview's WebKit window still uses sample data.

With Python 3.11 or later, stage the runtime from the pinned `rns-1.5.7-py3-none-any.whl` using:

```sh
python3 ios/stage-runtime.py /path/to/rns-1.5.7-py3-none-any.whl ios/RuntimeBuild/staged
```

The staging script verifies the wheel hash and includes Family's bundled LXMF sources. It keeps Reticulum standalone, delays importing shared-instance IPC, and uses the internal crypto provider when external crypto is unavailable. On iOS, LXMF stamp generation runs in one process.

The loopback test in `tests/test_ios_tcp_runtime.py` starts two Family instances on a local Reticulum hub. Set `FAMILY_IOS_TCP_TEST_RUNTIME` to the absolute staged directory to exercise the staged clients with the iOS platform identifier and without optional Android and crypto modules. Set `FAMILY_TEST_RMAP=1` to also exercise public TCP and the simulator echo fixture on the host.

## Live iPhone and iPad development target

On a Mac with full Xcode, an iOS simulator runtime, XcodeGen, and Python 3.11 or newer, run:

```sh
bash ios/test-live.sh iPhone
bash ios/test-live.sh iPad
```

The script verifies and stages the pinned CPython XCFramework and Reticulum wheel. It starts a private loopback peer, generates the **FamilyLive** Xcode project, and launches a test that sets up guardian access, approves the peer, and verifies an outgoing delivery receipt and incoming echo. The GitHub workflow runs the preview and live checks on both simulator families. Both interfaces keep a manually selected day or night theme. The live target allows a guardian to change the advertised device name and verifies that the name, approved contact, and appearance survive an app relaunch. The local live test also enables iOS message alerts, moves the app to the Home Screen and back during the conversation, checks for a delivered notification in Notification Center, then forces the TCP socket closed and verifies a second round trip after automatic reconnect.

To exercise the same messaging test through `rmap.world:4242`, append `rmap` to the command for each simulator. In GitHub Actions, add the `ios-rmap-test` label to the pull request or enable the `rmap` workflow input once the workflow is available on the default branch. Both endpoints use disposable LXMF identities and the peer echoes only the randomly generated test message. Test names and public LXMF addresses are announced to the Reticulum network.

**FamilyLive** is a foreground TCP development app with its own bundle ID and private storage. It links the native CPython bridge to the shared Family backend. It uses the same TCP write recovery as Android, reconnects when iOS reports a restored or changed network path, and rechecks the mailbox after reconnecting. For manual use, run `bash ios/prepare-live.sh`, then generate `ios/project-live.yml` using XcodeGen from the `ios` directory. Open `FamilyLive.xcodeproj`, select the **FamilyLive** scheme, and enter the TCP peer and contact in Guardian settings.

## Wi-Fi RNode

Open **Guardian settings → Wi-Fi RNode** and enter the radio’s hostname or IPv4 address and LoRa settings. The radio must offer RNode TCP on port 7633. The connection screen shows link status and the radio’s reported battery level when available. Approved Reticulum messages, rooms, and private location can use this link. Verify actual radio and battery behavior on a signed device build.

## Contact discovery and the live map

In Guardian settings, open **Find messaging client** to search Reticulum announces by name or LXMF address. You can also scan a contact QR on supported devices or import a QR image. Review the populated name and address before saving the contact.

Open **Guardian settings → Location sharing** to choose which approved contacts can exchange private location updates, set the sharing duration, and decide whether children can start or stop timed sharing. The Family map displays approved locations and their last update time. iOS samples GPS and sends updates while Family is open. The live map uses Apple Maps; the preview’s bundled tiles are separate.

## Reticulum Relay Chat

Open **Guardian settings → Approved rooms** to add a Relay Chat hub and channel. You can enter the hub address, import a room QR code, or choose a discovered hub and list its channels. Family saves the room password and rejoins approved rooms after reconnecting. Set a room to read only to disable posting. The home screen lists approved rooms separately from private conversations.

## Notifications and background delivery

Tap **Enable message notifications** on the home screen. Incoming messages from approved contacts can trigger a local alert while the app is running. The alert leaves out the sender and message text. Family keeps a record of posted alerts to avoid repeating them on refresh.

If Family is sending a message when iOS moves it to the background, it requests a short period to finish the send. iOS can then suspend the app and its TCP connection.

To receive messages sent while Family is offline, open **Guardian settings → Offline message mailbox** and enter a trusted LXMF propagation node's 32-character address. The sender needs to use the same mailbox in propagated delivery mode. Exchange a direct message from each contact first so Family can keep the contact's verified public key. Family checks the mailbox on return to the app and requests periodic iOS Background App Refresh. iOS controls whether and when those background checks run. Leave the mailbox field blank and save to disable it.

Timely alerts during suspension still need a push provider that can detect new relay mail and send generic alerts through Apple Push Notification service. The relay can hold encrypted messages until Family checks for them. The workflow also compiles an unsigned arm64 device build to check the embedded runtime before signing. Use a signed build on a physical iPad to check the lock screen, Background App Refresh, and eventual Apple push delivery. Reticulum voice, Bluetooth radio transport, SIP, offline maps, and distribution are separate iOS milestones. Validate camera scanning and GPS on a signed physical-device build. Android APK installation runs only on Android. Signed iOS beta updates use TestFlight.

[Python embedding on iOS](https://docs.python.org/3.14/using/ios.html) · [Apple device and simulator testing](https://developer.apple.com/documentation/xcode/building-and-running-an-app) · [iOS background execution](https://developer.apple.com/documentation/uikit/extending-your-app-s-background-execution-time) · [Apple push notifications](https://developer.apple.com/documentation/usernotifications/setting-up-a-remote-notification-server)
