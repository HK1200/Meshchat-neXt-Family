"""Verify current Family updates and the frozen old-package transfer route."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

REPOSITORY = "HK1200/Meshchat-neXt-Family"
LEGACY_TAG = "v0.6.21"


class FeedError(ValueError):
    pass


def _manifest(value, package):
    if not isinstance(value, dict) or value.get("schema") != 1 or value.get("package") != package:
        raise FeedError("Wrong app package in update manifest")
    for key in ("versionCode", "size"):
        if type(value.get(key)) is not int or value[key] <= 0:
            raise FeedError("Invalid update " + key)
    if not isinstance(value.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        raise FeedError("Invalid update checksum")
    if not isinstance(value.get("versionName"), str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["versionName"]):
        raise FeedError("Invalid update version")
    if value.get("tag") != "v" + value["versionName"]:
        raise FeedError("Update version does not match its tag")
    if not isinstance(value.get("apk"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.apk", value["apk"]):
        raise FeedError("Invalid APK filename")


def _asset(manifest, release):
    if release.get("tag_name") != manifest["tag"]:
        raise FeedError("APK belongs to a different release")
    candidates = [a for a in release.get("assets", []) if a.get("name") == manifest["apk"]]
    if len(candidates) != 1 or candidates[0].get("size") != manifest["size"]:
        raise FeedError("Published APK missing or size differs from its manifest")
    digest = candidates[0].get("digest")
    if digest and digest != "sha256:" + manifest["sha256"]:
        raise FeedError("GitHub's APK checksum differs from its manifest")
    return bool(digest)


def validate(production, stable, legacy, original_legacy, release, legacy_release):
    _manifest(production, "org.meshchat.family")
    _manifest(legacy, "org.meshchat.family.preview")
    if legacy != original_legacy or legacy.get("tag") != LEGACY_TAG or legacy.get("versionCode") != 30:
        raise FeedError("Old-package feed must retain the original v0.6.21 transfer manifest")
    if stable is not None and stable != production:
        raise FeedError("Current production and family-stable feeds disagree")
    production_digest = _asset(production, release)
    legacy_digest = _asset(legacy, legacy_release)
    return {"version": production["versionName"], "versionCode": production["versionCode"],
            "current_package": production["package"], "stable_feed_verified": stable is not None,
            "legacy_transfer_version": legacy["versionName"], "legacy_package": legacy["package"],
            "production_github_digest_verified": production_digest,
            "legacy_github_digest_verified": legacy_digest}


def _api(path, binary=False):
    args = ["gh", "api"]
    if binary: args += ["-H", "Accept: application/octet-stream"]
    args += ["repos/" + REPOSITORY + "/" + path]
    try:
        return subprocess.check_output(args, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise FeedError("Could not read GitHub release metadata") from error


def _json(path):
    return json.loads(_api(path))


def _release_asset(release, name):
    candidates = [a for a in release.get("assets", []) if a.get("name") == name]
    if len(candidates) != 1: raise FeedError("Missing release asset: " + name)
    asset = candidates[0]
    if type(asset.get("id")) is not int or not 0 < asset.get("size", 0) <= 65536:
        raise FeedError("Invalid or oversized manifest asset")
    data = _api("releases/assets/" + str(asset["id"]), binary=True)
    if len(data) > 65536: raise FeedError("Oversized manifest")
    return json.loads(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Check a particular versioned release")
    parser.add_argument("--preflight", action="store_true", help="Check draft assets before changing live feeds")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.tag and not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", args.tag): parser.error("Use a versioned release tag")
    if args.preflight and not args.tag: parser.error("Preflight requires --tag")
    release = _json("releases/tags/" + args.tag if args.tag else "releases/latest")
    old = _json("releases/tags/" + LEGACY_TAG)
    stable = None if args.preflight else _release_asset(_json("releases/tags/family-stable"), "family-update.json")
    proof = validate(_release_asset(release, "family-production-update.json"), stable,
                     _release_asset(release, "family-update.json"), _release_asset(old, "family-update.json"), release, old)
    output = json.dumps(proof, indent=2) + "\n"
    if args.report: args.report.write_text(output)
    print(output, end="")


if __name__ == "__main__":
    try: main()
    except (FeedError, ValueError) as error:
        print("Family update verification failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
