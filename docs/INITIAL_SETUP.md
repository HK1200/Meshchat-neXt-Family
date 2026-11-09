# Initial setup for neXt Family

## 1. Install on the family member’s device

1. On an ARM64 Android 8.0 or later device, open the Family GitHub Releases page and download the latest Family APK.
2. Open the download. If Android asks, allow installation from the browser or Files app you used, then confirm the install. You can turn that allowance off again afterward.
3. Open **neXt Family**. On the welcome screen, enter and confirm a guardian password that the family member does not know. Keep it somewhere safe. A fresh install has no preset guardian password.
4. If you want to try Reticulum over the internet, select **Connect Reticulum through rmap.world:4242**. Otherwise leave it unchecked. Choose **Create guardian access**.
5. Allow notifications when prompted if you want incoming message alerts and call controls. Grant microphone access when you make or answer your first call. Android may request additional permissions for Bluetooth, camera scanning, or location when you use those features.

[Family GitHub Releases](https://github.com/HK1200/Meshchat-neXt-Family/releases)

## 2. Enable the connections you want

Tap the key icon on the home screen, enter the guardian password, and open **Connections**. You can start with a single service and add the others later.

| Connection | How to set it up |
| --- | --- |
| Reticulum over the internet | Choose **Configure TCP peer**. Enter the peer hostname and port, enable the peer, and save. The suggested starting point is `rmap.world` on port `4242`. |
| Reticulum over LoRa | Configure an **RNode radio**. Choose its supported Bluetooth, USB serial, or Wi-Fi connection and select or enter the device address. Match the frequency, bandwidth, spreading factor, and coding rate to your local network. Set the transmit power to the value appropriate for your hardware and location. Enable the RNode and save. TCP and an RNode can both be enabled. |
| MeshCore | Use a separate radio running MeshCore companion firmware. For Bluetooth, grant **Allow Bluetooth access**, tap **Find Bluetooth companions**, and select the radio. For USB serial, attach it with a data-capable adapter and grant Android’s USB permission. Enable MeshCore and **Receive messages on this device**, then choose **Save and connect**. |
| Reticulum calls | Open **Configure Reticulum calls** and enable calling. The contact must have an approved LXST address and a Reticulum path with enough capacity for voice. |
| SIP calls | Choose **Configure SIP account**. Enter your provider’s server, port, your own extension and password, and any transport setting the provider requires. Save and wait for the account to register. |

A MeshCore companion should be used by one phone app at a time. If Family cannot connect, disconnect the radio in the other app first. For LoRa, use the parameters supplied by the network you intend to join.

## 3. Approve people

1. Open **Guardian settings → Contacts** and choose **Add contact**. Enter a display name and optionally add a profile picture.
2. Add only the addresses you want this family member to use. A contact may have one address or several.

   | Address | What to enter |
   | --- | --- |
   | Reticulum text | The person’s 32-character hexadecimal **LXMF destination**. |
   | Reticulum voice | The person’s 32-character hexadecimal **LXST address**. Family can offer to derive it when the approved Reticulum identity is known. |
   | MeshCore | The person’s full 64-character hexadecimal **public key**. Use the full key from their companion. |
   | SIP | The other person’s SIP URI, for example `sip:101@provider.example:5060`. Enter their port when needed. Your own account belongs under **Connections**. |

3. Save with **Save approved contact**. You can import contact details from a QR code, or enable the announce stream and search under **Contact discovery**. Verify the address with the person before approving it. The contact discovery list is for clients. Room servers are approved separately.
4. Choose **Lock and return**. Tap **Text** or **Call** on the person’s card. **Automatic** uses an available compatible route. Use the connection picker when you want to choose it yourself.
5. Send one short message and have the person reply. If calling is enabled, make a short call in both directions and verify the incoming **Answer** and **Decline** controls.

MeshCore supports private text in Family. Use SIP or Reticulum for calls.

## 4. Approve rooms

Open **Guardian settings → Rooms**. Add a MeshCore room server or a Reticulum Relay Chat hub and channel. Choose a supported QR import, the corresponding discovery list, or enter the address manually. Add the room’s password or access information if it requires one. Save the approval, then open the room from the Family home screen.

A room is shared with its participants. A saved participant label helps Family users identify an author in the room. It does not add that author to approved contacts or allow private calls or texts to them.

## 5. Set up the map and location sharing

1. Open **Family Map**. On first use choose the download button, grant location permission if you want Family to find your region, and download the supported map. The map can be used offline after it is installed.
2. If Family cannot find a supported regional download, use **Guardian settings → Maps → Offline map files** to import a raster MBTiles map. Guardians can add or remove their own maps.
3. In **Maps**, choose whether this device can receive approved locations or share its own. Review the contact permissions and decide whether timed sharing may be used. Only a guardian can choose **Until a guardian stops it**.
4. Open the map to see reported contact positions and when each position last updated. A contact needs a compatible client, permission to share, and an available connection to send updates.

Location sharing is optional. Grant device location access only if you intend to use GPS or share a location. If a timed session is active, use the stop control when it is no longer needed.

## 6. Check day-to-day operation

- Use **Day mode** or **Night mode** on the home screen without opening guardian settings.
- Check the RNode or MeshCore battery indicators when the corresponding radio is connected.
- If a service cannot reach a person, verify the contact address, selected route, and radio or account status under **Connections**.
- If notifications are missing, check the app’s notification permissions in Android settings. If calls can’t use audio, check microphone permission.
- Use the home screen’s **Install now** button when an update is offered. Guardians can also use **Security → Family updates → Check for updates**. Updates come from this repository.
