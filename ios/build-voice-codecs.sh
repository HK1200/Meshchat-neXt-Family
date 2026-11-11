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
    xcrun lipo "$output/libFamilyVoiceCodecs.a" -verify_arch "$arch"
    xcrun nm -gU "$output/libFamilyVoiceCodecs.a" > "$output/symbols.txt"
    for symbol in opus_encode opus_decode codec2_encode codec2_decode; do
        grep -Eq " [Tt] _$symbol\$" "$output/symbols.txt"
    done
}

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
