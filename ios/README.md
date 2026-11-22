# neXt Family for iOS

For the native live app, see the [iPhone/iPad setup and recovery guide](../docs/IOS_SETUP_AND_RECOVERY.md) and [feature verification audit](FEATURE-PARITY.md). The sample preview described first below is a separate target.

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

To exercise the same messaging test through RMAP (port `4343` first, then `4242`), append `rmap` to the command for each simulator. In GitHub Actions, add the `ios-rmap-test` label to the pull request or enable the `rmap` workflow input once the workflow is available on the default branch. Both endpoints use disposable LXMF identities and the peer echoes only the randomly generated test message. Test names and public LXMF addresses are announced to the Reticulum network.

**FamilyLive** is a foreground TCP development app with its own bundle ID and private storage. It links the native CPython bridge to the shared Family backend. It uses the same TCP write recovery as Android, reconnects when iOS reports a restored or changed network path, and rechecks the mailbox after reconnecting. For manual use, run `bash ios/prepare-live.sh`, then generate `ios/project-live.yml` using XcodeGen from the `ios` directory. Open `FamilyLive.xcodeproj`, select the **FamilyLive** scheme, and enter the TCP peer and contact in Guardian settings.

## Files and photos

Approved Reticulum conversations can attach files from Files and photos from the photo library. Low, Medium, and High reduce the photo to 320, 640, or 1280 pixels on its longest edge and send it as JPEG. Original keeps the selected image bytes. Direct messages allow up to 9.95 MB of attachments. Guardians can set the incoming message size in Guardian settings. Tap a received attachment to preview or share it.

## Bluetooth radios

In **Guardian settings → RNode**, choose Bluetooth LE, tap **Find Bluetooth radios**, and select the RNode by name. Save the confirmed frequency, bandwidth, spreading factor, coding rate, and power. For a first pairing, enable pairing mode on the radio itself and enter its current PIN on the iPhone or iPad; ordinary Bluetooth-on mode does not accept a new pairing. A brief disconnect and reconnect after successful RNode pairing is normal. Disconnect other apps from the radio before testing. Wi-Fi RNode remains available in the same menu. Bluetooth Classic serial radios require a Bluetooth LE capable firmware or a Wi-Fi connection on iOS.

In **Guardian settings → MeshCore companion**, scan and select the companion, enable approved private-message reception, and save. Approve clients listed by the companion or import a contact QR code. A full MeshCore key can also be added to an existing approved contact. The selected companion’s public key is checked again on reconnect. RNode and MeshCore use separate native Bluetooth sessions.

Bluetooth radio tests need a signed iPhone or iPad and a nearby radio. The simulator checks the runtime and interface, while local transport tests verify lifecycle and packet handoff through a mocked native radio.

## Wi-Fi RNode

Open **Guardian settings → RNode** choose Wi-Fi, and enter the radio’s hostname or IPv4 address and LoRa settings. The radio must offer RNode TCP on port 7633. The connection screen shows link status and the radio’s reported battery level when available. Approved Reticulum messages, rooms, and private location can use this link. Verify actual radio and battery behavior on a signed device build.

## Contact discovery and the live map

In Guardian settings, open **Find messaging client** to search Reticulum announces by name or LXMF address. You can also scan a contact QR on supported devices or import a QR image. Review the populated name and address before saving the contact.

In either contact approval or the approved contact editor, **Find MeshCore contact** searches the connected companion’s discovered clients and saved contacts by name or key. Selecting a radio fills only its MeshCore key; other services, the guardian’s chosen name and photo stay unchanged. Review and save the contact to approve the change. **Done typing** dismisses the editor keyboard.

In the approved contact editor, choose a profile picture from Photos or remove the current picture. Family stores a private 256-pixel square PNG on this device and preserves it when editing the contact’s addresses. Profile pictures are excluded from shared contact QR codes.

Open **Guardian settings → Location sharing** to choose which approved contacts can exchange private location updates, set the sharing duration, and decide whether children can start or stop timed sharing. The Family map displays approved locations and their last update time. iOS samples GPS and sends updates while Family is open by default. A guardian can enable **Continue sharing with the screen locked**, save that preference, and start a sharing session while Family is open. iOS then displays its location indicator while updates continue in the background. This uses more battery. Timed sharing stops at its deadline; force-quitting Family ends the native location session. No Always-location permission or automatic background restart is requested. The live map defaults to Apple Maps. Under **Guardian settings → Offline maps**, choose the bundled Pacific Northwest and southern BC layer with detailed Whatcom County streets or import a raster MBTiles pack from Files. Imported maps stay on the device and can be removed from the same menu.

## Reticulum Relay Chat

Open **Guardian settings → Approved rooms** to add a Relay Chat hub and channel. You can enter the hub address, import a room QR code, or choose a discovered hub and list its channels. Family saves the room password and rejoins approved rooms after reconnecting. Set a room to read only to disable posting. The home screen lists approved rooms separately from private conversations.

## Foreground SIP calling

Open **Guardian settings → SIP calling**, enter the provider account and password, and save. The initial provider fields use Hams Over IP at `premium.hamsoverip.com:5160` and can be edited. Credentials stay in the device Keychain. Add a SIP extension or full address to each approved contact. The chat has a **Call using SIP** action for that contact. Incoming calls are accepted only for a matching approved address. Provider hostnames are resolved again so approved callers can match the provider’s current IP addresses.

The native engine uses the same pinned Baresip and re sources as Android, with Apple’s voice-processing AudioUnit driver. iPad defaults to its speaker and follows connected headsets. The call screen includes Answer, Decline, End call, and Mute. SIP and Reticulum share the microphone and allow one call at a time. Approved calls use the iOS call screen by default. Guardians can turn **Use iOS call screen** off in Guardian settings for in-app controls; the setting cannot change during a call. Active call audio can continue when Family leaves the foreground. Receiving a new call after iOS suspends Family still requires the later push integration.

The Xcode build runs SIP address and native call-identity policy checks before cross-compiling the engine. Private simulator fixtures check authentication, incoming decline, outgoing rejection, pre-answer mute and rejection of stale call controls. Two-way audio and real device routing still need signed-device validation.

## Foreground Reticulum calling

Enable **Reticulum calling** in Guardian settings. Add the contact’s 32-character Reticulum voice address in their approval, import it from a Family contact card, or look it up from a known LXMF identity in the contact editor. Calls use LXST and the shared Family microphone processing. The call screen has Answer, Decline, and Mute controls. iPad uses its speaker by default and follows the system headset route when a headset is connected. iPhone also has a Speaker control. Family reconciles call state when a peer hangs up.

Keep Family open to receive new Reticulum calls. In **Guardian settings → Reticulum calling**, **Keep screen awake for calls** prevents auto-lock while Family is open with calling enabled. The same section shows where the most recent incoming attempt reached Family.

CallKit binds native Answer, Decline, End and Mute actions to one approved Reticulum or SIP call. Outgoing dialing and microphone audio wait for the system audio grant. Calls reported before backgrounding can keep their exact transport session while the screen locks or another app is visible; presence generations prevent an older scene task from reopening call admission. Audio interruptions pause local capture and playback, route changes rebuild the audio path, and media-service resets end the affected call cleanly. This uses the `audio` and `voip` background modes for actual calls, without silent keepalive audio. Call names use approved contact names and calls are excluded from system Recents.

The native lifecycle tests use an injected CallKit driver to check delayed activation, repeated actions, permission races, provider resets and stale actions across calls. These do not prove physical lock-screen behavior or acoustic audio quality. Signed-device validation remains necessary, and CallKit alone does not wake a suspended app for a new decentralized network call.

## Notifications and background delivery

When the embedded runtime is executing, a verified private Reticulum message signals the native inbox after it is saved. The signal contains no message content, address or key. A short background receive task refreshes the approved inbox and posts permitted unread-message notifications. iOS can still suspend TCP completely; reliable alerts during suspension require the optional push service and Apple signing capability described below.

Tap **Enable message notifications** on the home screen. Incoming messages from approved contacts can trigger a local alert while the app is running. The alert leaves out the sender and message text. Family keeps a record of posted alerts to avoid repeating them on refresh.

If Family is sending a message when iOS moves it to the background, it requests a short period to finish the send. iOS can then suspend the app and its TCP connection.

To receive messages sent while Family is offline, open **Guardian settings → Offline message mailbox** and enter a trusted LXMF propagation node's 32-character address. The sender needs to use the same mailbox in propagated delivery mode. Exchange a direct message from each contact first so Family can keep the contact's verified public key. Family checks the mailbox on return to the app and requests periodic iOS Background App Refresh. iOS controls whether and when those background checks run. Leave the mailbox field blank and save to disable it.

Timely alerts during suspension still need a push provider that can detect new relay mail and send generic alerts through Apple Push Notification service. The relay can hold encrypted messages until Family checks for them. The workflow also compiles an unsigned arm64 device build to check the embedded runtime before signing. Use a signed build on a physical iPad to check the lock screen, Background App Refresh, and eventual Apple push delivery. Live Bluetooth radio verification, SIP call verification, and distribution remain separate device checks. Validate camera scanning and GPS on a signed physical-device build. Android APK installation runs only on Android. Signed iOS beta updates use TestFlight.

[Python embedding on iOS](https://docs.python.org/3.14/using/ios.html) · [Apple device and simulator testing](https://developer.apple.com/documentation/xcode/building-and-running-an-app) · [iOS background execution](https://developer.apple.com/documentation/uikit/extending-your-app-s-background-execution-time) · [Apple push notifications](https://developer.apple.com/documentation/usernotifications/setting-up-a-remote-notification-server)

## Internal TestFlight on a stock iPad

The live app supports iPadOS 17 and later. Its bundle ID is
`org.meshchat.family.ios.live`. The **Family iOS simulator** workflow can
build a Release archive on the current device SDK with the
`device_archive` input. That check runs without Apple signing credentials.

To install through internal TestFlight, use an active Apple Developer Program
team. Register the explicit bundle ID and create its app record in App Store
Connect. Create an Apple Distribution certificate with an exportable private
key and an App Store provisioning profile for the same bundle and certificate.
Create a team App Store Connect API key authorized to upload builds. The
account holder should complete Apple's encryption export-compliance answers
for Family's Reticulum and TLS features in App Store Connect.

Configure a GitHub environment named `ios-beta` restricted to the reviewed
`feature/family-ios` branch. Add these environment secrets through GitHub's
settings or CLI.

| Secret | Value |
| --- | --- |
| `APPLE_CERTIFICATE_BASE64` | Base64-encoded Apple Distribution P12 export |
| `APPLE_CERTIFICATE_PASSWORD` | P12 export password |
| `APPLE_PROFILE_BASE64` | Base64-encoded App Store provisioning profile |
| `APPLE_CONNECT_KEY_BASE64` | Base64-encoded App Store Connect team API key P8 |
| `APPLE_CONNECT_KEY_ID` | App Store Connect API key ID |
| `APPLE_CONNECT_ISSUER_ID` | App Store Connect issuer ID |

Run the workflow on `feature/family-ios` with `testflight` selected. It
validates the provisioning profile, signs the app and embedded frameworks,
and uploads an internal-testing-only build to App Store Connect. After
processing, assign it to an internal tester group and accept the invitation
in TestFlight on the iPad. Internal TestFlight does not require the iPad's UDID.

[Apple TestFlight guide](https://developer.apple.com/testflight/)

Use the **AppStore** build configuration when archiving Family for the App Store. It disables room access and room networking. Local and GitHub builds use Debug or Release and include rooms.


## Native neXt TCP connections

The neXt iOS shell uses the released Messages interface and the native **TCP connections** screen. New default TCP profiles list RMAP 4343, RMAP 4242, WashMesh 7242 and Chicago 4242 separately. Each row can be edited, disabled or removed; **Add TCP peer** creates a disabled row for review before connecting. Existing custom/private single-peer profiles keep their custom connection enabled and show the public defaults disabled, rather than silently connecting to them. Saved rows retain their independent on/off state on the next launch.

Use the QR button beside **My LXMF address** to show a scannable Reticulum messaging contact code. Family can scan it in Guardian settings and review the new contact; the code contains the public messaging address only. **Share contact code** shares the same `lxmf://` format. Both simulator tests decode the displayed QR and compare it with the running identity's address.

A contact address is optional at first start. Contacts can be added through neXt’s contact interface after the runtime starts. Editing connections preserves the Reticulum identity, contacts and stored messages. The runtime retires only links on affected interfaces, rejects duplicate endpoints and retries unavailable configured connections. Each connected interface announces when it starts/reconnects and hourly thereafter. The status screen refreshes connection state without overwriting unsaved edits.

The existing Settings profile name and Light/Dark/System theme controls save locally. Updated names are used by the next announce on each enabled connection; the identity and messaging address remain unchanged. The native header follows the selected theme. Simulator tests now retain their private identity and history in their own sandbox so they can verify settings and signed replies after a real app restart. Their peers remain loopback-only.

The conversation list keeps unread state, the latest message preview and failed-send indicators across restarts. Opening a conversation or using the existing mark-read controls clears its unread state. An upgrade preserves old history without flagging every old message as new.

The simulator harness restricts every configured endpoint to `127.0.0.1`, including settings restored after relaunch. It checks adding a disabled peer, editing its port, toggling it, preserving the original peer, reopening the app and receiving a signed reply through the actual Messages view. A separate local HTTP/LXMF integration test exercises two TCP listeners, CSRF rejection, duplicate prevention, delivery over the remaining peer after the primary is disabled, and identity/contact/history preservation across restart.

The Messages file picker and photo controls use standard LXMF file/image fields.
Direct messages use neXt's 10 MB default budget (9,950,000 bytes of content and
attachments reserved below it), with at most 32 attachments. Existing photo
quality presets remain in the released interface. Images are served according
to their detected bytes, and filenames are reduced to a safe basename. History
pages and message events carry metadata; file/photo bytes are fetched only when
needed. Choosing a received file opens a native Save/share sheet; its temporary
copy is removed when that sheet closes. Only the embedded backend's attachment
URLs and its own blob URLs may become native downloads. The camera permission
is requested only if the user chooses to take a photo. Physical camera/Photos/
Files picker checks still require device verification.

The neXt preview also integrates native SIP and Reticulum calls, Bluetooth radio bridges, maps, private location sharing and Relay Chat. The [neXt verification audit](NEXT_FEATURE_PARITY.md) distinguishes implemented controls, simulator results and actual device checks. Fully suspended internet alerts, the remaining Reticulum tools and the physical phone/radio reliability matrix still require work before public iOS release.


### Unsigned neXt production archive

The workflow's **next_appstore_archive** option archives the checksum-pinned
neXt runtime in Release configuration for a generic arm64 iOS device. The
production identifier is `org.meshchat.next.ios`; the separate personal-test
identifier remains `org.meshchat.next.ios.runtimeprobe` before personal signing.
This job neither installs an app nor accesses an Apple account.

The retained archive and validation report check iPhone/iPad support, native
runtime libraries, privacy and permission declarations, upstream notices and
absence of simulator credentials or a personal provisioning profile. These are
packaging checks, not App Store approval or a claim that the remaining physical
and suspended-delivery checks have passed. Apple enrollment, distribution
signing, push entitlements, TestFlight and submission remain on hold.
