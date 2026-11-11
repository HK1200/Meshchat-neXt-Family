#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

mode="${1:-unsigned}"
case "$mode" in unsigned|testflight) ;; *) exit 2 ;; esac
sdk="$(xcrun --sdk iphoneos --show-sdk-version)"
if [[ "${sdk%%.*}" -lt 26 ]]; then
    echo "Xcode with the iOS 26 SDK or later is required." >&2
    exit 1
fi

archive="$PWD/RuntimeBuild/FamilyLive.xcarchive"
build_number="${GITHUB_RUN_NUMBER:-1}.${GITHUB_RUN_ATTEMPT:-1}"
signing=(CODE_SIGNING_ALLOWED=NO)
if [[ "$mode" == testflight ]]; then
    : "${APPLE_CERTIFICATE_BASE64:?Missing Apple Distribution certificate}"
    : "${APPLE_CERTIFICATE_PASSWORD:?Missing certificate password}"
    : "${APPLE_PROFILE_BASE64:?Missing App Store provisioning profile}"
    : "${APPLE_CONNECT_KEY_BASE64:?Missing App Store Connect API key}"
    : "${APPLE_CONNECT_KEY_ID:?Missing App Store Connect API key ID}"
    : "${APPLE_CONNECT_ISSUER_ID:?Missing App Store Connect issuer ID}"
    umask 077
    signing_dir="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/family-ios-signing.XXXXXXXX")"
    keychain="$signing_dir/signing.keychain-db"
    installed_profile=""
    cleanup() {
        security list-keychains -d user -s "${old_keychains[@]}" >/dev/null || true
        security delete-keychain "$keychain" >/dev/null 2>&1 || true
        if [[ -n "$installed_profile" ]]; then rm -f -- "$installed_profile"; fi
        rm -rf -- "$signing_dir"
    }
    old_keychains=()
    while IFS= read -r entry; do old_keychains+=("$entry"); done < <(
        security list-keychains -d user | sed -E 's/^[[:space:]]*"([^"]+)"[[:space:]]*$/\1/'
    )
    trap cleanup EXIT
    printf '%s' "$APPLE_CERTIFICATE_BASE64" | base64 -D > "$signing_dir/distribution.p12"
    printf '%s' "$APPLE_PROFILE_BASE64" | base64 -D > "$signing_dir/distribution.mobileprovision"
    printf '%s' "$APPLE_CONNECT_KEY_BASE64" | base64 -D > "$signing_dir/api-key.p8"
    unset APPLE_CERTIFICATE_BASE64 APPLE_PROFILE_BASE64 APPLE_CONNECT_KEY_BASE64
    security cms -D -i "$signing_dir/distribution.mobileprovision" > "$signing_dir/profile.plist"
    team="$(python3 - "$signing_dir/profile.plist" <<'PY'
import datetime
import plistlib
import sys
from pathlib import Path

profile = plistlib.loads(Path(sys.argv[1]).read_bytes())
team, = profile["TeamIdentifier"]
entitlements = profile["Entitlements"]
app_id = entitlements["application-identifier"]
prefixes = profile["ApplicationIdentifierPrefix"]
if app_id.rsplit(".", 1)[0].split(".", 1)[0] not in prefixes:
    raise SystemExit("Unexpected App ID prefix in the profile.")
if not any(app_id == f"{prefix}.org.meshchat.family.ios.live" for prefix in prefixes):
    raise SystemExit("The profile must target org.meshchat.family.ios.live.")
if (entitlements.get("get-task-allow") or profile.get("ProvisionedDevices")
        or profile.get("ProvisionsAllDevices")
        or profile["ExpirationDate"] <= datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)):
    raise SystemExit("An unexpired App Store distribution profile is required.")
print(team)
PY
    )"
    uuid="$(/usr/libexec/PlistBuddy -c 'Print :UUID' "$signing_dir/profile.plist")"
    [[ "$uuid" =~ ^[[:xdigit:]-]{36}$ ]]
    profiles="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
    mkdir -p "$profiles"
    test ! -e "$profiles/$uuid.mobileprovision"
    installed_profile="$profiles/$uuid.mobileprovision"
    install -m 600 "$signing_dir/distribution.mobileprovision" "$installed_profile"
    keychain_password="$(openssl rand -hex 24)"
    security create-keychain -p "$keychain_password" "$keychain"
    security set-keychain-settings -lut 3600 "$keychain"
    security unlock-keychain -p "$keychain_password" "$keychain"
    security import "$signing_dir/distribution.p12" -k "$keychain" -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign >/dev/null
    unset APPLE_CERTIFICATE_PASSWORD
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$keychain_password" "$keychain" >/dev/null
    security list-keychains -d user -s "$keychain" "${old_keychains[@]}"
    identity="$(security find-identity -v -p codesigning "$keychain" | awk '/Apple Distribution:/ { print $2 }')"
    [[ "$identity" =~ ^[[:xdigit:]]{40}$ ]]
    signing=(CODE_SIGN_STYLE=Manual "DEVELOPMENT_TEAM=$team" "CODE_SIGN_IDENTITY=$identity"
             "PROVISIONING_PROFILE_SPECIFIER=$uuid")
fi

bash prepare-live.sh
xcodegen generate --spec project-live.yml
xcodebuild archive -project FamilyLive.xcodeproj -scheme FamilyLive -configuration Release \
    -destination 'generic/platform=iOS' -derivedDataPath DerivedData \
    -archivePath "$archive" "CURRENT_PROJECT_VERSION=$build_number" "${signing[@]}"
app="$archive/Products/Applications/FamilyLive.app"
lipo "$app/FamilyLive" -verify_arch arm64
test -f "$app/Frameworks/Python.framework/Python"
test -f "$app/Frameworks/FamilyVoiceCodecs.framework/FamilyVoiceCodecs"
test -f "$app/staged/family_tcp.py"
test -s "$app/offline-tiles/tiles.bin"
test -s "$app/offline-tiles/index.json"
test -f "$app/PrivacyInfo.xcprivacy"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Info.plist")" = org.meshchat.family.ios.live
/usr/libexec/PlistBuddy -c 'Print :CFBundleIcons:CFBundlePrimaryIcon' "$app/Info.plist" >/dev/null

if [[ "$mode" == testflight ]]; then
    codesign --verify --deep --strict "$app"
    python3 - "$signing_dir/ExportOptions.plist" "$team" "$identity" "$uuid" <<'PY'
import plistlib
import sys
from pathlib import Path

path, team, identity, profile = sys.argv[1:]
Path(path).write_bytes(plistlib.dumps({
    "method": "app-store-connect",
    "destination": "upload",
    "signingStyle": "manual",
    "teamID": team,
    "signingCertificate": identity,
    "provisioningProfiles": {"org.meshchat.family.ios.live": profile},
    "manageAppVersionAndBuildNumber": False,
    "testFlightInternalTestingOnly": True,
}))
PY
    xcodebuild -exportArchive -archivePath "$archive" -exportPath "$signing_dir/export" \
        -exportOptionsPlist "$signing_dir/ExportOptions.plist" -allowProvisioningUpdates \
        -authenticationKeyPath "$signing_dir/api-key.p8" \
        -authenticationKeyID "$APPLE_CONNECT_KEY_ID" -authenticationKeyIssuerID "$APPLE_CONNECT_ISSUER_ID"
fi
