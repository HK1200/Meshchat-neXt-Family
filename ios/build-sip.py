#!/usr/bin/env python3
"""Build the same pinned Baresip engine as Android for an Apple SDK slice."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
SOURCES = {
    "re-4.12.0": ("https://codeload.github.com/baresip/re/tar.gz/refs/tags/v4.12.0", "707b6194dd3b8d3fb1641ca08a0999aaac1d38d36b5c45514777a13ded311923"),
    "baresip-4.12.0": ("https://codeload.github.com/baresip/baresip/tar.gz/refs/tags/v4.12.0", "710d79d60c15c09f0aeb93e5d2f219e7f12ab93f62cab826e4280592a1ea155f"),
    "mbedtls-3.6.7": ("https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-3.6.7/mbedtls-3.6.7.tar.bz2", "a7e8bcbec0e6f761b4af24f25677626b35f762f68eef79c08677a363212d11f6"),
}


def run(*args):
    subprocess.run([str(value) for value in args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdk", choices=("iphoneos", "iphonesimulator"))
    parser.add_argument("arch", choices=("arm64", "x86_64"))
    args = parser.parse_args()
    if args.sdk == "iphoneos" and args.arch != "arm64":
        parser.error("Physical iOS builds require arm64")
    for variable in ("SDKROOT", "CC", "CXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "MACOSX_DEPLOYMENT_TARGET", "IPHONEOS_DEPLOYMENT_TARGET"):
        os.environ.pop(variable, None)
    work = ROOT / "RuntimeBuild/sip"
    work.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in SOURCES.items():
        archive = work / (name + ".tar")
        if not archive.exists():
            temporary = archive.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=180) as response, temporary.open("wb") as output:
                import shutil
                shutil.copyfileobj(response, output)
            temporary.replace(archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise ValueError("SIP source checksum mismatch for " + name)
        if not (work / name).exists():
            # Archives are accepted only after checking their pinned digest.
            run("tar", "-xf", archive, "-C", work)
    # Exercise address approval with the macOS host compiler before cross compiling.
    policy_test = work / "sip-policy-test"
    mac_sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
    run("xcrun", "--sdk", "macosx", "swiftc", "-sdk", mac_sdk,
        ROOT / "FamilyLive/FamilySIPPolicy.swift", ROOT / "SIPPolicyTests/main.swift", "-o", policy_test)
    run(policy_test)
    sdk = subprocess.check_output(["xcrun", "--sdk", args.sdk, "--show-sdk-path"], text=True).strip()
    output = work / (args.sdk + "-" + args.arch)
    output.mkdir(parents=True, exist_ok=True)
    common = ["-DCMAKE_SYSTEM_NAME=iOS", "-DCMAKE_OSX_SYSROOT=" + sdk,
              "-DCMAKE_OSX_ARCHITECTURES=" + args.arch, "-DCMAKE_OSX_DEPLOYMENT_TARGET=17.0",
              "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY",
              "-DCMAKE_POSITION_INDEPENDENT_CODE=ON", "-DCMAKE_MACOSX_BUNDLE=OFF", "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_TESTING=OFF"]
    tls = work / "mbedtls-3.6.7"
    mt = output / "mbedtls"
    run("cmake", "-S", tls, "-B", mt, *common, "-DENABLE_TESTING=OFF", "-DENABLE_PROGRAMS=OFF")
    run("cmake", "--build", mt, "--parallel", 2)
    tls_libraries = [mt / ("library/lib" + name + ".a") for name in ("mbedtls", "mbedx509", "mbedcrypto")]
    tls_flags = ["-DUSE_OPENSSL=OFF", "-DUSE_MBEDTLS=ON", "-DMBEDTLS_INCLUDE_DIR=" + str(tls / "include"),
                 "-DMBEDTLS_LIBRARY=" + ";".join(map(str, tls_libraries)), "-DCMAKE_C_FLAGS=-I" + str(tls / "include")]
    re_source = work / "re-4.12.0"
    # Apple selects native AES/HMAC but omits the TLS-unavailable API stubs.
    # The UDP-only engine still links the optional account-certificate helper.
    cmake_file = re_source / "CMakeLists.txt"
    cmake_source = cmake_file.read_text()
    apple_backend = "    src/aes/apple/aes.c\n    src/hmac/apple/hmac.c\n"
    complete_backend = apple_backend + "    src/tls/stub.c\n"
    if complete_backend not in cmake_source:
        if cmake_source.count(apple_backend) != 1:
            raise ValueError("Pinned re Apple backend changed")
        cmake_file.write_text(cmake_source.replace(apple_backend, complete_backend))
    re_build = output / "re"
    run("cmake", "-S", re_source, "-B", re_build, *common, *tls_flags,
        "-DLIBRE_BUILD_SHARED=OFF", "-DLIBRE_BUILD_STATIC=ON", "-DUSE_PCP=OFF", "-DUSE_BFCP=OFF", "-DUSE_RTMP=OFF")
    run("cmake", "--build", re_build, "--parallel", 2)
    # The voice runtime already provisions and builds this exact Opus slice.
    opus = ROOT / "RuntimeBuild/voice-codecs" / (args.sdk + "-" + args.arch) / "opus/libopus.a"
    if not opus.exists():
        run("bash", ROOT / "build-voice-codecs.sh", "--slice", args.sdk, args.arch)
    include = output / "include"
    include.mkdir(exist_ok=True)
    if not (include / "opus").exists():
        (include / "opus").symlink_to(ROOT / "RuntimeBuild/voice-codecs/opus-1.6.1/include", target_is_directory=True)
    bare = output / "baresip"
    run("cmake", "-S", work / "baresip-4.12.0", "-B", bare, *common, *tls_flags,
        "-DSTATIC=ON", "-DMODULES=audiounit;g711;opus", "-DRE_INCLUDE_DIR=" + str(re_source / "include"),
        "-DRE_LIBRARY=" + str(re_build / "libre.a"), "-Dre_DIR=" + str(re_source / "cmake"),
        "-DOPUS_INCLUDE_DIR=" + str(include), "-DOPUS_LIBRARY=" + str(opus))
    run("cmake", "--build", bare, "--target", "baresip", "--parallel", 2)
    run("xcrun", "libtool", "-static", "-o", output / "libFamilySIP.a", bare / "libbaresip.a", re_build / "libre.a", *tls_libraries, opus)
    run("lipo", output / "libFamilySIP.a", "-verify_arch", args.arch)


if __name__ == "__main__":
    main()
