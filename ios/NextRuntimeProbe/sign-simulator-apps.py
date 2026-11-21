"""Sign only this project's disposable simulator apps with own-app access groups.

No developer account, real-device profile, or cross-app Keychain group is used.
The actual signed entitlements are verified before tests begin.
"""
import argparse
from pathlib import Path
import plistlib
import subprocess


def sign(products, reports):
    reports.mkdir(parents=True, exist_ok=True)
    for name, identifier in (
        ('NextRuntimeProbe', 'org.meshchat.next.ios.runtimeprobe'),
        ('NextRuntimeProbeUITests-Runner', 'org.meshchat.next.ios.runtimeprobe.uitests.xctrunner'),
    ):
        app = products / (name + '.app')
        info = plistlib.loads((app / 'Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != identifier:
            raise ValueError('Unexpected simulator app identity')
        entitlements = {'application-identifier': identifier, 'keychain-access-groups': [identifier]}
        source = reports / (name + '-requested-entitlements.plist')
        source.write_bytes(plistlib.dumps(entitlements))
        subprocess.run(['codesign', '--force', '--sign', '-', '--entitlements', str(source), str(app)], check=True)
        observed = subprocess.check_output(['codesign', '-d', '--entitlements', ':-', str(app)])
        (reports / (name + '-signed-entitlements.plist')).write_bytes(observed)
        if plistlib.loads(observed) != entitlements:
            raise ValueError('Simulator signature does not contain the requested own-app access group')
        subprocess.run(['codesign', '--verify', str(app)], check=True)
    print('Both simulator executable signatures contain only their own app identity and Keychain group.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('products', type=Path)
    parser.add_argument('reports', type=Path)
    args = parser.parse_args()
    sign(args.products, args.reports)
