package org.meshchat.family.preview;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.os.Build;
import android.os.SystemClock;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.function.BooleanSupplier;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONException;
import org.json.JSONObject;

/** Checks the guardian's GitHub Releases feed and verifies APKs in private storage. */
final class FamilyUpdates {
    private static final int MAX_MANIFEST_BYTES = 65_536;
    private static final long MAX_APK_BYTES = 128L * 1024 * 1024;
    private static final long CHECK_INTERVAL_MS = 24L * 60 * 60 * 1000;
    private static FamilyUpdates instance;

    private final Context context;
    private final SharedPreferences preferences;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private Release candidate;
    private long lastAttempt;
    private boolean checking;
    private boolean retryCheck;
    private String message = "";

    static synchronized FamilyUpdates get(Context context) {
        if (instance == null) instance = new FamilyUpdates(context.getApplicationContext());
        return instance;
    }

    private FamilyUpdates(Context context) {
        this.context = context;
        preferences = context.getSharedPreferences("family_updates", Context.MODE_PRIVATE);
        try {
            String cached = preferences.getString("release", "");
            if (repository().equals(preferences.getString("repository", "")) && !cached.isEmpty()) {
                Release release = parse(repository(), new JSONObject(cached), context.getPackageName());
                if (release.code > version(installed(context, 0))) candidate = release;
            }
        } catch (Exception ignored) {
            // An invalid or superseded cache never becomes an install candidate.
        }
    }

    String repository() { return FamilyUpdateSource.REPOSITORY; }

    synchronized JSONObject status() throws JSONException {
        JSONObject result = new JSONObject()
                .put("configured", true)
                .put("checking", checking)
                .put("available", candidate != null)
                .put("message", message);
        if (candidate != null) result.put("version", candidate.name);
        return result;
    }

    synchronized Intent installerIntent(Context activity) {
        if (candidate == null) return null;
        return new Intent(activity, FamilyUpdateActivity.class)
                .putExtra("repository", candidate.repo)
                .putExtra("release", candidate.metadata);
    }

    synchronized void check(boolean manual) {
        String repo = repository();
        long now = SystemClock.elapsedRealtime();
        if (checking) return;
        long delay = manual ? 15_000 : retryCheck ? 15 * 60_000 : CHECK_INTERVAL_MS;
        if (lastAttempt != 0 && now - lastAttempt < delay) return;
        lastAttempt = now;
        checking = true;
        message = "Checking GitHub Releases…";
        worker.execute(() -> fetch(repo));
    }

    private void fetch(String repo) {
        Release found = null;
        String result;
        try {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            HttpsURLConnection connection = open(FamilyUpdateSource.manifest(repo, context.getPackageName()), repo);
            try (InputStream input = connection.getInputStream()) {
                byte[] buffer = new byte[4096];
                int count;
                long deadline = SystemClock.elapsedRealtime() + 20_000;
                while ((count = input.read(buffer)) != -1) {
                    if (bytes.size() + count > MAX_MANIFEST_BYTES || SystemClock.elapsedRealtime() > deadline) {
                        throw new IOException("Update metadata exceeded its limit.");
                    }
                    bytes.write(buffer, 0, count);
                }
            } finally { connection.disconnect(); }
            found = parse(repo, new JSONObject(bytes.toString("UTF-8")), context.getPackageName());
            if (found.code <= version(installed(context, 0))) found = null;
            result = found == null ? "Family is up to date." : "A new version is available.";
        } catch (Exception error) {
            synchronized (this) {
                checking = false;
                message = "Could not check the Family release on GitHub.";
                // Retry a failed automatic check on the next opening after 15 minutes.
                retryCheck = true;
            }
            return;
        }
        synchronized (this) {
            candidate = found;
            retryCheck = false;
            checking = false;
            message = result;
            SharedPreferences.Editor edit = preferences.edit().putString("repository", repo);
            if (found == null) edit.remove("release");
            else edit.putString("release", found.metadata);
            edit.apply();
        }
    }

    static final class Release {
        final String repo, name, digest, metadata;
        final long code, size;
        final URI uri;

        Release(String repo, String name, String digest, String metadata, long code, long size, URI uri) {
            this.repo = repo;
            this.name = name;
            this.digest = digest;
            this.metadata = metadata;
            this.code = code;
            this.size = size;
            this.uri = uri;
        }
    }

    static Release parse(String repo, JSONObject data, String packageName) throws JSONException {
        if (!FamilyUpdateSource.REPOSITORY.equals(repo)
                || data.getInt("schema") != 1 || !packageName.equals(data.getString("package"))) {
            throw new IllegalArgumentException("The release does not describe Family.");
        }
        long code = data.getLong("versionCode");
        long size = data.getLong("size");
        String name = data.getString("versionName");
        String digest = data.getString("sha256");
        if (code <= 0 || size <= 0 || size > MAX_APK_BYTES
                || !name.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,63}") || !digest.matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException("Invalid Family release metadata.");
        }
        URI uri = FamilyUpdateSource.apk(repo, data.getString("tag"), data.getString("apk"));
        return new Release(repo, name, digest, data.toString(), code, size, uri);
    }

    private static HttpsURLConnection open(URI start, String repo) throws IOException {
        return openRelease(start, uri -> FamilyUpdateSource.allows(uri, repo), "neXt-Family-Updater");
    }

    static HttpsURLConnection openRelease(URI start, java.util.function.Predicate<URI> allowed, String userAgent)
            throws IOException {
        URI uri = start;
        for (int redirects = 0; redirects <= 5; redirects++) {
            if (!allowed.test(uri)) throw new IOException("Download source is outside GitHub Releases.");
            HttpsURLConnection connection = (HttpsURLConnection) uri.toURL().openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(12_000);
            connection.setReadTimeout(15_000);
            connection.setRequestProperty("User-Agent", userAgent);
            int code = connection.getResponseCode();
            if (code == 200) return connection;
            String redirect = connection.getHeaderField("Location");
            connection.disconnect();
            if (code < 300 || code >= 400 || redirect == null) throw new IOException("GitHub release download failed.");
            uri = uri.resolve(redirect);
        }
        throw new IOException("Too many release redirects.");
    }

    static void download(Release release, File destination, BooleanSupplier cancelled) throws Exception {
        downloadVerified(open(release.uri, release.repo), destination, release.size, release.digest, 180_000, cancelled);
    }

    static void downloadVerified(HttpsURLConnection connection, File destination, long expectedSize, String digest,
            long timeout, BooleanSupplier cancelled) throws Exception {
        MessageDigest sha = MessageDigest.getInstance("SHA-256");
        long size = 0;
        long deadline = SystemClock.elapsedRealtime() + timeout;
        try (InputStream input = connection.getInputStream(); FileOutputStream output = new FileOutputStream(destination)) {
            byte[] buffer = new byte[65_536];
            int count;
            while ((count = input.read(buffer)) != -1) {
                size += count;
                if (cancelled.getAsBoolean() || size > expectedSize || SystemClock.elapsedRealtime() > deadline) {
                    throw new IOException("Download stopped or exceeded its limit.");
                }
                output.write(buffer, 0, count);
                sha.update(buffer, 0, count);
            }
        } finally { connection.disconnect(); }
        byte[] expected = new byte[32];
        for (int i = 0; i < expected.length; i++) {
            expected[i] = (byte) Integer.parseInt(digest.substring(2 * i, 2 * i + 2), 16);
        }
        if (size != expectedSize || !MessageDigest.isEqual(sha.digest(), expected)) {
            throw new IOException("The download checksum or size did not match.");
        }
    }

    static void verifyApk(Context context, File apk, Release release) throws Exception {
        int flags = Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo current = installed(context, flags);
        PackageInfo archive = context.getPackageManager().getPackageArchiveInfo(apk.getAbsolutePath(), flags);
        Set<Signature> signer = signers(current);
        if (archive == null || !current.packageName.equals(archive.packageName)
                || version(archive) <= version(current) || version(archive) != release.code
                || !release.name.equals(archive.versionName)
                || signer.isEmpty() || !signer.equals(signers(archive))) {
            throw new IOException("The APK version, package, or signature did not match.");
        }
    }

    private static PackageInfo installed(Context context, int flags) throws PackageManager.NameNotFoundException {
        return context.getPackageManager().getPackageInfo(context.getPackageName(), flags);
    }

    private static long version(PackageInfo info) {
        return Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
    }

    private static Set<Signature> signers(PackageInfo info) {
        Signature[] signatures = Build.VERSION.SDK_INT >= 28
                ? (info.signingInfo == null ? null : info.signingInfo.getApkContentsSigners())
                : info.signatures;
        return signatures == null ? new HashSet<>() : new HashSet<>(Arrays.asList(signatures));
    }
}
