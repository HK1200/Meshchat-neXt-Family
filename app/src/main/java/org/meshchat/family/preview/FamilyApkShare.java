package org.meshchat.family.preview;

import android.content.ClipData;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Exposes only this installation's standalone APK through a temporary read grant. */
public final class FamilyApkShare extends ContentProvider {
    private static final String MIME = "application/vnd.android.package-archive";

    private static Uri apkUri(Context context) {
        return new Uri.Builder().scheme("content")
                .authority(context.getPackageName() + ".apkshare").appendPath("family.apk").build();
    }

    private static File installedApk(Context context) throws FileNotFoundException {
        ApplicationInfo app = context.getApplicationInfo();
        if (app.splitSourceDirs != null && app.splitSourceDirs.length != 0) {
            throw new FileNotFoundException("This installation uses split APKs.");
        }
        File apk = new File(app.sourceDir);
        if (!apk.isFile() || !apk.canRead()) throw new FileNotFoundException("Family APK unavailable.");
        return apk;
    }

    static Intent chooser(Context context) throws FileNotFoundException {
        installedApk(context);
        Uri uri = apkUri(context);
        Intent send = new Intent(Intent.ACTION_SEND)
                .setType(MIME)
                .putExtra(Intent.EXTRA_STREAM, uri)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        send.setClipData(ClipData.newRawUri("neXt Family APK", uri));
        return Intent.createChooser(send, "Send Family APK");
    }

    @Override public boolean onCreate() { return true; }

    @Override public String getType(Uri uri) {
        return apkUri(getContext()).equals(uri) ? MIME : null;
    }

    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (getType(uri) == null || !"r".equals(mode)) throw new FileNotFoundException();
        return ParcelFileDescriptor.open(installedApk(getContext()), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection,
            String[] selectionArgs, String sortOrder) {
        if (getType(uri) == null) return null;
        Context context = getContext();
        String[] columns = projection != null ? projection
                : new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        MatrixCursor cursor = new MatrixCursor(columns, 1);
        try {
            File apk = installedApk(context);
            String version = context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionName;
            String name = "MeshchatNextFamily-v" + version + "-android-arm64.apk";
            Object[] row = new Object[columns.length];
            for (int i = 0; i < columns.length; i++) {
                if (OpenableColumns.DISPLAY_NAME.equals(columns[i])) row[i] = name;
                if (OpenableColumns.SIZE.equals(columns[i])) row[i] = apk.length();
            }
            cursor.addRow(row);
        } catch (FileNotFoundException | PackageManager.NameNotFoundException unavailable) {
            // An unavailable package has no openable row.
        }
        return cursor;
    }

    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }
}
