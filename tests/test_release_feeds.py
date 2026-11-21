"""Keep old-package migration separate from normal Family updates."""
import copy
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("family_release_feeds", Path(__file__).resolve().parents[1] / "scripts/ci/family_release_feeds.py")
feeds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feeds)


def fixtures():
    production = dict(schema=1, package="org.meshchat.family", versionName="0.6.29", versionCode=43,
                      tag="v0.6.29", apk="Family-v0.6.29.apk", size=100, sha256="a" * 64)
    legacy = dict(schema=1, package="org.meshchat.family.preview", versionName="0.6.21", versionCode=30,
                  tag="v0.6.21", apk="Family-v0.6.21-transfer.apk", size=90, sha256="b" * 64)
    def release(m): return {"tag_name": m["tag"], "assets": [{"name": m["apk"], "size": m["size"], "digest": "sha256:" + m["sha256"]}]}
    return production, copy.deepcopy(production), legacy, copy.deepcopy(legacy), release(production), release(legacy)


def test_current_and_legacy_packages_are_both_upgradeable():
    assert feeds.validate(*fixtures())["stable_feed_verified"]
    values = list(fixtures()); values[1] = None
    assert not feeds.validate(*values)["stable_feed_verified"]


@pytest.mark.parametrize("failure", ["production_as_legacy", "wrong_stable", "changed_legacy", "missing_apk", "wrong_hash", "invalid_name", "wrong_package"])
def test_publication_regressions_fail_before_users_receive_wrong_updates(failure):
    values = list(fixtures())
    if failure == "production_as_legacy": values[2] = copy.deepcopy(values[0])
    if failure == "wrong_stable": values[1]["versionCode"] = 42
    if failure == "changed_legacy": values[2]["sha256"] = "c" * 64
    if failure == "missing_apk": values[4]["assets"] = []
    if failure == "wrong_hash": values[4]["assets"][0]["digest"] = "sha256:" + "c" * 64
    if failure == "invalid_name": values[0]["apk"] = "../wrong.apk"
    if failure == "wrong_package": values[0]["package"] = "different.app"
    with pytest.raises(feeds.FeedError): feeds.validate(*values)


def test_preflight_finds_draft_without_an_existing_git_tag(monkeypatch):
    draft = {"tag_name": "v0.6.29", "draft": True, "assets": []}
    paths = []
    def api(path):
        paths.append(path)
        return [{"tag_name": "v0.6.28", "draft": False}, draft]
    monkeypatch.setattr(feeds, "_json", api)
    assert feeds.resolve_release("v0.6.29", True) == draft
    assert paths == ["releases?per_page=100"]


@pytest.mark.parametrize("releases", [[], [{"tag_name": "other"}], [{"tag_name": "v0.6.29"}] * 2])
def test_preflight_does_not_substitute_another_release(monkeypatch, releases):
    monkeypatch.setattr(feeds, "_json", lambda path: releases)
    with pytest.raises(feeds.FeedError): feeds.resolve_release("v0.6.29", True)


def test_published_checks_use_the_actual_tag_or_latest_endpoint(monkeypatch):
    paths = []
    def api(path): paths.append(path); return {"path": path}
    monkeypatch.setattr(feeds, "_json", api)
    feeds.resolve_release("v0.6.29")
    feeds.resolve_release()
    assert paths == ["releases/tags/v0.6.29", "releases/latest"]
