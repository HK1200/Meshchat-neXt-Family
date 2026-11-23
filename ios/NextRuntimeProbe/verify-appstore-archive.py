# SPDX-License-Identifier: 0BSD
"""Check the unsigned production artifact; never enroll, sign, or upload it."""
import hashlib
import json
import plistlib
import sys
from pathlib import Path

BUNDLE = 'org.meshchat.next.ios'


def verify(archive):
    archive = Path(archive)
    metadata = plistlib.loads((archive / 'Info.plist').read_bytes())
    properties = metadata['ApplicationProperties']
    assert properties['ApplicationPath'] == 'Applications/NextRuntimeProbe.app'
    app = archive / 'Products' / properties['ApplicationPath']
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    assert info['CFBundleIdentifier'] == properties['CFBundleIdentifier'] == BUNDLE
    assert info['CFBundleShortVersionString'] == properties['CFBundleShortVersionString'] == '0.1.27'
    assert info['CFBundleVersion'] == properties['CFBundleVersion'] and info['CFBundleVersion']
    assert info['CFBundleExecutable'] == 'NextRuntimeProbe'
    assert info['CFBundleSupportedPlatforms'] == ['iPhoneOS']
    assert sorted(info['UIDeviceFamily']) == [1, 2]
    assert tuple(map(int, info['MinimumOSVersion'].split('.'))) >= (17, 0)
    assert info.get('NextPushEnvironment', '') == ''
    assert not (app / 'embedded.mobileprovision').exists(), 'Unsigned archive contains a personal profile'
    assert not (app / '_CodeSignature').exists(), 'Unsigned app unexpectedly signed'
    assert {'audio', 'voip', 'location', 'bluetooth-central'} <= set(info['UIBackgroundModes'])
    for key in ('NSMicrophoneUsageDescription', 'NSBluetoothAlwaysUsageDescription',
                'NSLocalNetworkUsageDescription', 'NSCameraUsageDescription',
                'NSPhotoLibraryUsageDescription', 'NSPhotoLibraryAddUsageDescription',
                'NSLocationWhenInUseUsageDescription'):
        assert isinstance(info[key], str) and info[key].strip(), key
    privacy = plistlib.loads((app / 'PrivacyInfo.xcprivacy').read_bytes())
    assert privacy.get('NSPrivacyAccessedAPITypes'), 'Required-reason API declarations missing'
    assert privacy.get('NSPrivacyTracking', False) is False
    assert not privacy.get('NSPrivacyTrackingDomains', [])
    for name in ('NextRuntimeProbe', 'Frameworks/Python.framework/Python',
                 'Frameworks/FamilyVoiceCodecs.framework/FamilyVoiceCodecs',
                 'staged/frontend/index.html', 'staged/network_runtime.py',
                 'staged/voice_runtime.py', 'staged/lxmf_reconnect.py', 'staged/file_runtime.py', 'staged/mobile_rncp_guard.py', 'staged/terminal_runtime.py',
                 'SIP-NOTICES.txt', 'staged/voice-notices/Opus-COPYING',
                 'staged/voice-notices/Codec2-COPYING', 'staged/voice-notices/audioop-LICENSE'):
        assert (app / name).is_file() and (app / name).stat().st_size > 0, name
    fixtures = {'peer.json', 'sip-account.json', 'sip-incoming.json', 'sip-outgoing.json'}
    assert not any(path.name in fixtures or path.suffix in ('.xctest', '.xctestrun')
                   for path in app.rglob('*')), 'Test fixture included in production archive'
    return dict(bundle_identifier=BUNDLE, version=info['CFBundleShortVersionString'],
                build=info['CFBundleVersion'], unsigned=True, personal_profile_absent=True,
                simulator_fixtures_absent=True, iphone_and_ipad=True,
                privacy_manifest_present=True, native_runtime_and_notices_present=True,
                executable_sha256=hashlib.file_digest((app / 'NextRuntimeProbe').open('rb'), 'sha256').hexdigest(),
                apple_enrollment_performed=False, app_store_submission_performed=False,
                release_ready=False)


if __name__ == '__main__':
    result = verify(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
