"""Reject mixed personal/simulator builds before retaining a production archive."""
import importlib.util
import plistlib
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('next_archive', Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe/verify-appstore-archive.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def archive(tmp_path):
    app = tmp_path / 'Products/Applications/NextRuntimeProbe.app'
    app.mkdir(parents=True)
    info = dict(CFBundleIdentifier=module.BUNDLE, CFBundleShortVersionString='0.1.27',
                CFBundleVersion='1.1', CFBundleExecutable='NextRuntimeProbe',
                CFBundleSupportedPlatforms=['iPhoneOS'], UIDeviceFamily=[1, 2],
                DTSDKName='iphoneos26.2', DTXcode='2620',
                MinimumOSVersion='17.0', UIBackgroundModes=['audio', 'voip', 'location', 'bluetooth-central'])
    for key in ('NSMicrophoneUsageDescription', 'NSBluetoothAlwaysUsageDescription',
                'NSLocalNetworkUsageDescription', 'NSCameraUsageDescription',
                'NSPhotoLibraryUsageDescription', 'NSPhotoLibraryAddUsageDescription',
                'NSLocationWhenInUseUsageDescription'):
        info[key] = 'Explicitly chosen feature'
    (app / 'Info.plist').write_bytes(plistlib.dumps(info))
    (tmp_path / 'Info.plist').write_bytes(plistlib.dumps(dict(ApplicationProperties=dict(
        ApplicationPath='Applications/NextRuntimeProbe.app', CFBundleIdentifier=module.BUNDLE,
        CFBundleShortVersionString='0.1.27', CFBundleVersion='1.1'))))
    (app / 'PrivacyInfo.xcprivacy').write_bytes(plistlib.dumps(dict(NSPrivacyAccessedAPITypes=[dict(NSPrivacyAccessedAPIType='UserDefaults')])) )
    for name in ('NextRuntimeProbe', 'Frameworks/Python.framework/Python',
                 'Frameworks/FamilyVoiceCodecs.framework/FamilyVoiceCodecs',
                 'staged/frontend/index.html', 'staged/network_runtime.py',
                 'staged/voice_runtime.py', 'staged/lxmf_reconnect.py', 'staged/file_runtime.py', 'staged/mobile_rncp_guard.py', 'staged/terminal_runtime.py', 'SIP-NOTICES.txt',
                 'staged/voice-notices/Opus-COPYING', 'staged/voice-notices/Codec2-COPYING',
                 'staged/voice-notices/audioop-LICENSE'):
        target = app / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'Fixture for metadata gate only, not an executable qualification')
    return tmp_path, app


def test_accepts_only_unsigned_production_metadata(archive):
    result = module.verify(archive[0])
    assert result['iphone_and_ipad'] and not result['release_ready']
    assert result['submission_toolchain_verified'] and result['sdk']=='iphoneos26.2' and result['xcode']=='2620'
    assert not result['apple_enrollment_performed'] and not result['app_store_submission_performed']


@pytest.mark.parametrize('name', ['embedded.mobileprovision', '_CodeSignature', 'staged/peer.json', 'staged/sip-account.json', 'bad.xctest'])
def test_rejects_personal_signing_or_fixture_contamination(archive, name):
    path = archive[1] / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'Not for production')
    with pytest.raises(AssertionError):
        module.verify(archive[0])


@pytest.mark.parametrize('key,value', [('CFBundleIdentifier', 'org.meshchat.next.ios.runtimeprobe'),
    ('CFBundleSupportedPlatforms', ['iPhoneSimulator']), ('UIDeviceFamily', [2]),
    ('NextPushEnvironment', 'development'), ('NSMicrophoneUsageDescription', ''),
    ('UIBackgroundModes', ['audio']), ('CFBundleVersion', 'stale')])
def test_rejects_wrong_build_or_missing_native_capability(archive, key, value):
    target = archive[1] / 'Info.plist'
    info = plistlib.loads(target.read_bytes())
    info[key] = value
    target.write_bytes(plistlib.dumps(info))
    with pytest.raises(AssertionError):
        module.verify(archive[0])


def test_rejects_developer_web_inspection_in_production_executable(archive):
    target = archive[1] / 'NextRuntimeProbe'
    target.write_bytes(target.read_bytes() + b'--inspect-web-interface')
    with pytest.raises(AssertionError, match='Web Inspector'):
        module.verify(archive[0])


@pytest.mark.parametrize('key,value', [
    ('DTSDKName', 'iphoneos18.5'), ('DTSDKName', 'iphonesimulator26.2'),
    ('DTSDKName', ''), ('DTSDKName', None), ('DTSDKName', 'iphoneos26garbage'),
    ('DTXcode', '1640'), ('DTXcode', ''), ('DTXcode', None),
    ('DTXcode', '26.2'), ('DTXcode', True),
])
def test_rejects_older_missing_or_malformed_submission_toolchain(archive, key, value):
    target=archive[1]/'Info.plist'
    info=plistlib.loads(target.read_bytes())
    if value is None: info.pop(key)
    else: info[key]=value
    target.write_bytes(plistlib.dumps(info))
    with pytest.raises(AssertionError, match='SDK|Xcode'):
        module.verify(archive[0])
