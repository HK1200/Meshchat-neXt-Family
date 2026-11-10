#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mkdir -p RuntimeBuild

fetch() {
    local url="$1" expected="$2" file="$3"
    if [[ ! -f "$file" ]]; then
        curl --fail --silent --show-error --location --retry 3 --max-time 180 "$url" -o "$file.part"
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

wheel=RuntimeBuild/rns-1.5.7-py3-none-any.whl
if [[ ! -f "$wheel" ]]; then
    python3 -m pip download --disable-pip-version-check --no-deps --only-binary=:all: --dest RuntimeBuild rns==1.5.7
fi
stage="$(mktemp -d "$PWD/RuntimeBuild/staging.XXXXXXXX")"
trap 'rm -rf -- "$stage"' EXIT
python3 stage-runtime.py "$wheel" "$stage/staged"
if [[ -d RuntimeBuild/staged ]]; then rm -rf RuntimeBuild/staged; fi
mv -- "$stage/staged" RuntimeBuild/staged
