#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mkdir -p RuntimeBuild

fetch() {
    local url="$1" expected="$2" file="$3"
    if [[ ! -f "$file" ]]; then
        curl --fail --silent --show-error --location --retry 3 --retry-all-errors --max-time 180 "$url" -o "$file.part"
        mv -- "$file.part" "$file"
    fi
    printf '%s  %s\n' "$expected" "$file" | shasum -a 256 -c -
}

support=RuntimeBuild/Python-3.14-iOS-support.b14.tar.gz
fetch https://github.com/beeware/Python-Apple-support/releases/download/3.14-b14/Python-3.14-iOS-support.b14.tar.gz \
    703ff822529f46edcbcd8b88096b2544f6990f3109ad38b4b4b61bb489a7c1ee "$support"
if [[ ! -f RuntimeBuild/Python.xcframework/build/utils.sh ]]; then
    tar -xzf "$support" -C RuntimeBuild Python.xcframework
fi

mkdir -p RuntimeBuild/public
wheel=RuntimeBuild/public/rns-1.5.7-py3-none-any.whl
fetch https://files.pythonhosted.org/packages/6a/5a/ee933b9f465040039286ffa76c5e509f334b61014061cdc1b0e46bcb3753/rns-1.5.7-py3-none-any.whl \
    0e4aaf8cc47f770da34572d2215b45fea900e104b009551600eb9741a41faddf "$wheel"
cbor=RuntimeBuild/public/cbor2-5.6.5-py3-none-any.whl
fetch https://files.pythonhosted.org/packages/9b/ef/1c4698cac96d792005ef0611832f38eaee477c275ab4b02cbfc4daba7ad3/cbor2-5.6.5-py3-none-any.whl \
    3038523b8fc7de312bb9cdcbbbd599987e64307c4db357cd2030c472a6c7d468 "$cbor"
mkdir -p RuntimeBuild/room-wheels
python3 -c 'import json; print("\n".join(" ".join((w["url"], w["sha256"], w["file"])) for ws in json.load(open("room-wheels.json")).values() for w in ws))' | \
while read -r url digest filename; do
    fetch "$url" "$digest" "RuntimeBuild/room-wheels/$filename"
done
mkdir -p RuntimeBuild/voice-wheels
python3 -c 'import json; print("\n".join(" ".join((w["url"], w["sha256"], w["file"])) for ws in json.load(open("voice-wheels.json")).values() for w in ws))' | \
while read -r url digest filename; do
    fetch "$url" "$digest" "RuntimeBuild/voice-wheels/$filename"
done
stage="$(mktemp -d "$PWD/RuntimeBuild/staging.XXXXXXXX")"
trap 'rm -rf -- "$stage"' EXIT
python3 stage-runtime.py "$wheel" "$stage/staged" --cbor-wheel "$cbor"
if [[ -d RuntimeBuild/staged ]]; then rm -rf RuntimeBuild/staged; fi
mv -- "$stage/staged" RuntimeBuild/staged
