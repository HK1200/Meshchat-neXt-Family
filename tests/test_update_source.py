"""The Family updater only follows its guardian-configured GitHub release feed."""

import subprocess
from pathlib import Path


def test_release_urls_reject_other_origins_and_repositories(tmp_path):
    app = Path(__file__).resolve().parents[1] / "app/src/main/java/org/meshchat/family/preview"
    harness = tmp_path / "SourceTest.java"
    harness.write_text(
        """
package org.meshchat.family.preview;
import java.net.URI;
public class SourceTest {
    public static void main(String[] args) {
        String repo = FamilyUpdateSource.repository(" family-owner/family-app ");
        check(FamilyUpdateSource.manifest(repo), repo, true);
        check(FamilyUpdateSource.apk(repo, "v0.6.5", "family.apk"), repo, true);
        check(URI.create("https://release-assets.githubusercontent.com/asset?sig=token"), repo, true);
        check(URI.create("https://github.com/other/family-app/releases/download/v1/app.apk"), repo, false);
        check(URI.create("https://github.com/family-owner/family-app/releases/../../other/app.apk"), repo, false);
        check(URI.create("https://github.com/family-owner/family-app/releases/%2e%2e/app.apk"), repo, false);
        check(URI.create("https://github.com.evil.invalid/family-owner/family-app/releases/app.apk"), repo, false);
        check(URI.create("http://release-assets.githubusercontent.com/asset"), repo, false);
        check(URI.create("https://github.com:8443/family-owner/family-app/releases/app.apk"), repo, false);
        try {
            FamilyUpdateSource.repository("https://evil.invalid/feed");
            throw new AssertionError("Accepted an arbitrary URL");
        } catch (IllegalArgumentException expected) {}
    }
    private static void check(URI uri, String repo, boolean expected) {
        if (FamilyUpdateSource.allows(uri, repo) != expected) throw new AssertionError(uri);
    }
}
"""
    )
    subprocess.run(["javac", "-d", str(tmp_path), str(app / "FamilyUpdateSource.java"), str(harness)], check=True)
    subprocess.run(["java", "-cp", str(tmp_path), "org.meshchat.family.preview.SourceTest"], check=True)
