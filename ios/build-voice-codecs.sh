#!/usr/bin/env bash
# Build the native Opus and Codec2 libraries for the iOS voice runtime.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

build="$PWD/RuntimeBuild/voice-codecs"
mkdir -p "$build"
fetch_source() {
    local url="$1" expected="$2" archive="$3"
    if [[ ! -f "$archive" ]]; then
        curl --fail --silent --show-error --location --retry 3 --max-time 180 "$url" -o "$archive.part"
        mv -- "$archive.part" "$archive"
    fi
    printf '%s  %s\n' "$expected" "$archive" | shasum -a 256 -c -
}

codec2_commit=25014a290752fb830390ff24a612a9694319a47a
fetch_source "https://codeload.github.com/drowe67/codec2/tar.gz/$codec2_commit" \
    05d08f69108a216bb894adbfa432f737081395eb653d133610441b50c5d8f1cd "$build/codec2.tar.gz"
fetch_source https://downloads.xiph.org/releases/opus/opus-1.6.1.tar.gz \
    6ffcb593207be92584df15b32466ed64bbec99109f007c82205f0194572411a1 "$build/opus.tar.gz"

fetch_source https://files.pythonhosted.org/packages/a6/28/956b52132ca2f3569f1784a2f1a0354489f74ef6b930b04586798ec54985/lxst-0.5.4-py3-none-any.whl \
    feadeb244d12378c27c35dbe48a251ff4db03faf3c8f55b769f9d7656d0adeb7 "$build/lxst.whl"
fetch_source https://files.pythonhosted.org/packages/38/53/946db57842a50b2da2e0c1e34bd37f36f5aadba1a929a3971c5d7841dbca/audioop_lts-0.2.2.tar.gz \
    64d0c62d88e67b98a1a5e71987b7aa7b5bcffc7dcee65b635823dbdd0a8dbbd0 "$build/audioop.tar.gz"

unzip -p "$build/lxst.whl" LXST/Filters.c > "$build/Filters.c"
unzip -p "$build/lxst.whl" LXST/Filters.h > "$build/Filters.h"
tar -xzf "$build/audioop.tar.gz" -C "$build"
tar -xzf "$build/codec2.tar.gz" -C "$build"
tar -xzf "$build/opus.tar.gz" -C "$build"

# Codec2's native codebook generator uses a nested CMake build. Apply the
# compatibility policy to both that host build and the iOS target build.
export CMAKE_POLICY_VERSION_MINIMUM=3.5

build_slice() {
    local sdk="$1" arch="$2" output="$build/$1-$2" sdk_path
    sdk_path="$(xcrun --sdk "$sdk" --show-sdk-path)"
    local args=(
        -DCMAKE_SYSTEM_NAME=iOS
        "-DCMAKE_OSX_SYSROOT=$sdk_path"
        "-DCMAKE_OSX_ARCHITECTURES=$arch"
        -DCMAKE_OSX_DEPLOYMENT_TARGET=17.0
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON
        -DBUILD_SHARED_LIBS=OFF
    )
    cmake -S "$build/opus-1.6.1" -B "$output/opus" "${args[@]}" \
        -DOPUS_BUILD_TESTING=OFF -DOPUS_BUILD_PROGRAMS=OFF
    cmake --build "$output/opus" --target opus --parallel 2
    cmake -S "$build/codec2-$codec2_commit" -B "$output/codec2" "${args[@]}" -DUNITTEST=OFF
    cmake --build "$output/codec2" --target codec2 --parallel 2
    xcrun libtool -static -o "$output/libFamilyVoiceCodecs.a" \
        "$output/opus/libopus.a" "$output/codec2/src/libcodec2.a"
    local target="$arch-apple-ios17.0" python_variant=ios-arm64
    if [[ "$sdk" == iphonesimulator ]]; then
        target+=-simulator
        python_variant=ios-arm64_x86_64-simulator
    fi
    local python_dir="$PWD/RuntimeBuild/Python.xcframework/$python_variant"
    xcrun --sdk "$sdk" clang -target "$target" -isysroot "$sdk_path" -O2 -dynamiclib \
        -Wl,-force_load,"$output/libFamilyVoiceCodecs.a" "$build/Filters.c" \
        -Wl,-install_name,@rpath/FamilyVoiceCodecs.framework/FamilyVoiceCodecs \
        -o "$output/FamilyVoiceCodecs"
    xcrun --sdk "$sdk" clang -target "$target" -isysroot "$sdk_path" -O2 -dynamiclib \
        -DPy_LIMITED_API=0x030D0000 -I "$python_dir/Python.framework/Headers" \
        -F "$python_dir" -framework Python "$build/audioop_lts-0.2.2/audioop/_audioop.c" \
        -Wl,-install_name,@rpath/audioop._audioop.framework/audioop._audioop \
        -o "$output/_audioop.abi3.so"
    xcrun lipo "$output/FamilyVoiceCodecs" -verify_arch "$arch"
    xcrun lipo "$output/_audioop.abi3.so" -verify_arch "$arch"
    xcrun nm -gU "$output/_audioop.abi3.so" > "$output/audioop-symbols.txt"
    grep -Eq ' [Tt] _PyInit__audioop$' "$output/audioop-symbols.txt"
    xcrun lipo "$output/libFamilyVoiceCodecs.a" -verify_arch "$arch"
    xcrun nm -gU "$output/libFamilyVoiceCodecs.a" > "$output/symbols.txt"
    for symbol in opus_encode opus_decode codec2_encode codec2_decode; do
        grep -Eq " [Tt] _$symbol\$" "$output/symbols.txt"
    done
}

if [[ "${1:-}" == --slice ]]; then
    [[ "$#" == 3 ]]
    case "$2-$3" in
        iphoneos-arm64|iphonesimulator-arm64|iphonesimulator-x86_64) ;;
        *) printf 'Unsupported iOS voice target: %s %s\n' "$2" "$3" >&2; exit 2 ;;
    esac
    build_slice "$2" "$3"
    exit 0
fi

build_slice iphoneos arm64
build_slice iphonesimulator arm64
build_slice iphonesimulator x86_64
mkdir -p "$build/simulator"
xcrun lipo -create "$build/iphonesimulator-arm64/libFamilyVoiceCodecs.a" \
    "$build/iphonesimulator-x86_64/libFamilyVoiceCodecs.a" \
    -output "$build/simulator/libFamilyVoiceCodecs.a"
framework="$build/FamilyVoiceCodecs.xcframework"
rm -rf -- "$framework"
xcodebuild -create-xcframework -library "$build/iphoneos-arm64/libFamilyVoiceCodecs.a" \
    -library "$build/simulator/libFamilyVoiceCodecs.a" -output "$framework"
printf 'Built iOS voice codec libraries at %s\n' "$framework"
