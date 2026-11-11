package org.meshchat.family.preview;

import java.net.URI;
import java.util.Locale;

/** An update feed is a repository, never an arbitrary download URL. */
final class FamilyUpdateSource {
    static final String REPOSITORY = "HK1200/Meshchat-neXt-Family";

    private FamilyUpdateSource() {}

    static String repository(String value) {
        String slug = value.trim();
        if (!slug.isEmpty() && !slug.matches("[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")) {
            throw new IllegalArgumentException("Enter a GitHub repository as owner/repository.");
        }
        return slug;
    }

    static URI manifest(String repo) {
        return URI.create("https://github.com/" + repo + "/releases/download/family-stable/family-update.json");
    }

    static URI apk(String repo, String tag, String asset) {
        if (!tag.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
                || !asset.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,119}\\.apk")) {
            throw new IllegalArgumentException("Invalid release asset.");
        }
        return URI.create("https://github.com/" + repo + "/releases/download/" + tag + "/" + asset);
    }

    static boolean allows(URI uri, String repo) {
        return allowsReleaseAsset(uri, repo, false);
    }

    static boolean allowsMap(URI uri, String repo, String assetPath) {
        return allowsReleaseAsset(uri, repo, true)
                && (!"github.com".equalsIgnoreCase(uri.getHost()) || assetPath.equals(uri.getPath()));
    }

    private static boolean allowsReleaseAsset(URI uri, String repo, boolean map) {
        String host = uri.getHost();
        if (!"https".equalsIgnoreCase(uri.getScheme()) || host == null
                || uri.getUserInfo() != null || uri.getFragment() != null
                || (uri.getPort() != -1 && uri.getPort() != 443)) return false;
        host = host.toLowerCase(Locale.ROOT);
        if (host.equals("release-assets.githubusercontent.com") || host.equals("objects.githubusercontent.com")) {
            return true; // GitHub redirects release downloads to its asset host.
        }
        String path = uri.getPath();
        return host.equals("github.com") && uri.getQuery() == null && path.equals(uri.getRawPath())
                && uri.normalize().equals(uri)
                && path.toLowerCase(Locale.ROOT).startsWith("/" + repo.toLowerCase(Locale.ROOT) + "/releases/")
                && (map ? path.endsWith(".mbtiles") : path.endsWith(".apk") || path.endsWith("/family-update.json"));
    }
}
