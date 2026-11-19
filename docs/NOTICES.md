# Third-party notices

Family uses components from Meshchat neXt and the Reticulum, LXMF, LXST and MeshCore ecosystems. Notices distributed with the app are under `app/src/main/assets/notices`. The vendored source retains its upstream notices. See the parent project for its license and native library sources. [Meshchat neXt license](https://github.com/HK1200/Meshchat-neXt/blob/v0.1.8/LICENSE)

The bundled regional street map credits OpenStreetMap contributors, Natural Earth and Protomaps. The map’s source snapshot and rendering instructions are recorded in `app/src/main/assets/notices/whatcom-maps.txt` and `map-src/`. Credits appear on the map. [OpenStreetMap attribution](https://www.openstreetmap.org/copyright) · [Protomaps basemaps](https://docs.protomaps.com/basemaps/downloads)

Reticulum’s low-bandwidth call profiles use Codec2 1.2.0 and pycodec2 4.1.1. Their licenses are bundled with Family. [Codec2 source](https://github.com/drowe67/codec2/tree/1.2.0) · [pycodec2 source](https://pypi.org/project/pycodec2/4.1.1/)

The Android binaries also include USB Serial for Android 3.8.1, libffi 3.3, the Android NDK's shared C++ runtime, and the neXt SIP engine with Opus 1.5.2, Baresip and re 4.12.0, and Mbed TLS 3.6.7. The package includes their upstream license texts in `app/src/main/assets/notices`. See [Android binary sources and verification](BUILDING.md#bundled-android-binaries).

The Android Python runtime’s XML parser uses the checksum-pinned Expat 2.10.0 security backport also used by neXt. Its upstream license is included as `assets/notices/expat-2.10.0-COPYING.txt`; other Python target archive entries remain unchanged. See the build instructions for reproduction and packaged-byte verification.
