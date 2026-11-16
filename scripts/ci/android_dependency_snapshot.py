"""Describe the Python wheels declared by the Family Android build."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

GRADLE_FILE = "app/build.gradle"


def resolved_wheels(gradle_source):
    wheel_paths = re.findall(r'^\s*install "\$familyWheelDir/([^"]+\.whl)"', gradle_source, re.MULTILINE)
    if not wheel_paths:
        raise ValueError(f"No Python wheel declarations found in {GRADLE_FILE}")

    resolved = {}
    for wheel in wheel_paths:
        # Wheel names begin with distribution and version, before the build and platform tags.
        distribution, version, _ = wheel.split("-", 2)
        # Support wheels built for Android have no matching PyPI distribution.
        if distribution.startswith("chaquopy_") or distribution == "lxst_filterlib_android":
            continue
        package = re.sub(r"[-_.]+", "-", distribution).lower()
        package_url = f"pkg:pypi/{package}@{version}"
        resolved[package_url] = {
            "package_url": package_url,
            "relationship": "direct",
            "scope": "runtime",
        }
    return resolved


def main():
    repo_url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
    resolved = resolved_wheels(Path(GRADLE_FILE).read_text(encoding="utf-8"))
    snapshot = {
        "version": 0,
        "sha": os.environ["GITHUB_SHA"],
        "ref": os.environ["GITHUB_REF"],
        "job": {
            "correlator": "family-android-python-wheels",
            "id": os.environ["GITHUB_RUN_ID"],
        },
        "detector": {"name": "family-android-python-wheels", "version": "1", "url": repo_url},
        "scanned": datetime.now(timezone.utc).isoformat(),
        "manifests": {
            GRADLE_FILE: {
                "name": GRADLE_FILE,
                "file": {"source_location": GRADLE_FILE},
                "resolved": resolved,
            }
        },
    }
    print(json.dumps(snapshot))


if __name__ == "__main__":
    main()
