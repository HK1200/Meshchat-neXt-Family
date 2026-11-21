"""Record simulator signing diagnostics without modifying Xcode's signatures.

The real Keychain checks run in the app-hosted unit target. A UI-test runner is
an Apple-supplied helper, not the app, and must not be re-signed with app rights.
"""
import argparse
from pathlib import Path
import plistlib
import subprocess


def inspect(products, reports):
    reports.mkdir(parents=True, exist_ok=True)
    for name, identifier in (
        ('NextRuntimeProbe', 'org.meshchat.next.ios.runtimeprobe'),
        ('NextRuntimeProbeUITests-Runner', 'org.meshchat.next.ios.runtimeprobe.uitests.xctrunner'),
    ):
        app = products / (name + '.app')
        info = plistlib.loads((app / 'Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != identifier:
            raise ValueError('Unexpected simulator app identity')
        subprocess.run(['codesign', '--verify', str(app)], check=True)
        observed = subprocess.check_output(['codesign', '-d', '--entitlements', ':-', str(app)])
        (reports / (name + '-signed-entitlements.plist')).write_bytes(observed)
    print('Original Xcode simulator signatures verified; Keychain tests use the app host.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('products', type=Path)
    parser.add_argument('reports', type=Path)
    args = parser.parse_args()
    inspect(args.products, args.reports)
