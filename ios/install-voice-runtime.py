"""Assemble LXST and its native Python modules in the built iOS bundle."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from zipfile import ZipFile


def patch(path, needle, replacement):
    content = path.read_text()
    if content.count(needle) != 1:
        raise ValueError(f"Unexpected pinned LXST source: {path.name}")
    path.write_text(content.replace(needle, replacement))


def install(sdk, arch, app, signer):
    root = Path(__file__).resolve().parent
    resources = app / "staged"
    manifest = json.loads((root / "voice-wheels.json").read_text())
    for entry in manifest[f"{sdk}-{arch}"]:
        wheel = root / "RuntimeBuild/voice-wheels" / entry["file"]
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Checksum mismatch for {wheel.name}")
        with ZipFile(wheel) as archive:
            archive.extractall(resources, (item for item in archive.namelist() if not item.endswith(".a")))

    build = root / "RuntimeBuild/voice-codecs"
    with ZipFile(build / "lxst.whl") as archive:
        archive.extractall(resources, (item for item in archive.namelist()
            if not any(part in item.split("/") for part in ("macos", "win32", "win_amd64"))))
    for source in (root / "VoiceRuntime").glob("*.py"):
        shutil.copyfile(source, resources / source.name)
    loader = resources / "LXST/Codecs/libs/pyogg/library_loader.py"
    patch(loader, "        lib = InternalLibrary.load(names, tests)",
          '        if sys.platform == "ios":\n'
          '            from family_ios_codecs import load_pyogg_library\n'
          '            return load_pyogg_library(names["external"], tests)\n'
          '        lib = InternalLibrary.load(names, tests)')
    filters = resources / "LXST/Filters.py"
    patch(filters, "import os\n", "import os\nimport sys\n")
    patch(filters, "            if not RNS.vendor.platformutils.is_windows():",
          '            if sys.platform == "ios":\n'
          '                from family_ios_codecs import library_path\n'
          '                with open(c_src_path / "Filters.h", "r") as f: ffi.cdef(f.read())\n'
          '                native_functions = ffi.dlopen(str(library_path()))\n'
          '                USE_NATIVE_FILTERS = True\n'
          '            elif not RNS.vendor.platformutils.is_windows():')
    # Install the ctypes aliases before Xcode signs the read-only app bundle.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(resources))
    from lxst_pyogg_ctypes_compat import apply_disk_patch

    result = apply_disk_patch(resources / "LXST/Codecs/libs/pyogg/ogg.py")
    if result not in ("patched", "already", "upgraded"):
        raise ValueError(f"Could not prepare LXST’s Ogg compatibility aliases: {result}")

    audioop = resources / "audioop"
    audioop.mkdir(exist_ok=True)
    shutil.copyfile(build / "audioop_lts-0.2.2/audioop/__init__.py", audioop / "__init__.py")
    shutil.copyfile(build / f"{sdk}-{arch}/_audioop.abi3.so", audioop / "_audioop.abi3.so")
    notices = resources / "voice-notices"
    notices.mkdir(exist_ok=True)
    shutil.copyfile(build / "opus-1.6.1/COPYING", notices / "Opus-COPYING")
    shutil.copyfile(build / "codec2-25014a290752fb830390ff24a612a9694319a47a/COPYING", notices / "Codec2-COPYING")
    shutil.copyfile(build / "audioop_lts-0.2.2/LICENSE", notices / "audioop-LICENSE")
    framework = app / "Frameworks/FamilyVoiceCodecs.framework"
    framework.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(build / f"{sdk}-{arch}/FamilyVoiceCodecs", framework / "FamilyVoiceCodecs")
    with (framework / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundlePackageType": "FMWK", "CFBundleExecutable": "FamilyVoiceCodecs",
                       "CFBundleIdentifier": "org.meshchat.family.ios.voicecodecs", "CFBundleVersion": "1",
                       "CFBundleShortVersionString": "1.0", "MinimumOSVersion": "17.0"}, stream)
    subprocess.run(["codesign", "--force", "--sign", signer, "--timestamp=none", str(framework)], check=True)


if __name__ == "__main__":
    _, sdk, arch, app, signer = sys.argv
    install(sdk, arch, Path(app), signer)
