package org.meshchat.family.preview;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ComponentName;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.os.Handler;
import android.os.Looper;
import android.os.ResultReceiver;
import android.widget.Toast;
import com.chaquo.python.PyObject;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.UUID;

/** One-release, same-device transfer between Family packages signed by the same certificate. */
public final class FamilyMigration extends ContentProvider {
    static final int REQUEST = 19;
    private static final String LEGACY = "org.meshchat.family.preview";
    private static final String PRODUCTION = "org.meshchat.family";
    private static final String SUFFIX = ".migration";
    private static final String COMPLETION = "family_transfer_completion";
    private static final long EXPIRES_MS = 10 * 60_000L;
    private static final long MAX_ARCHIVE = 4L * 1024 * 1024 * 1024 + 4 * 1024 * 1024;
    private static final Object IMPORT_LOCK = new Object();

    private static String testSuffix(Context context) {
        return context.getPackageName().endsWith(".setuptest") ? ".setuptest" : "";
    }

    static boolean isLegacy(Context context) {
        return (LEGACY + testSuffix(context)).equals(context.getPackageName());
    }

    private static boolean sameSigner(Context context, String other) {
        return context.getPackageManager().checkSignatures(context.getPackageName(), other)
            == PackageManager.SIGNATURE_MATCH;
    }

    private static File transferDirectory(Context context) {
        return new File(context.getCacheDir(), "family-migration");
    }

    private static void toast(Activity activity, String text) {
        Toast.makeText(activity, text, Toast.LENGTH_LONG).show();
    }

    static void send(Activity activity, PyObject backend, String token) {
        String production = PRODUCTION + testSuffix(activity);
        if (!isLegacy(activity) || !sameSigner(activity, production)) {
            toast(activity, "Install the new neXt Family app before transferring.");
            return;
        }
        toast(activity, "Preparing the Family profile…");
        new Thread(() -> {
            File folder = transferDirectory(activity);
            String key = UUID.randomUUID().toString();
            File archive = new File(folder, key);
            try {
                if (!folder.isDirectory() && !folder.mkdirs()) throw new IOException("Transfer folder unavailable");
                File[] expired = folder.listFiles(file -> System.currentTimeMillis() - file.lastModified() > EXPIRES_MS);
                if (expired != null) for (File file : expired) file.delete();
                backend.callAttr("export_migration", token, archive.getAbsolutePath());
                Uri uri = new Uri.Builder().scheme("content").authority(activity.getPackageName() + SUFFIX)
                    .appendPath(key).build();
                Intent intent = new Intent(Intent.ACTION_VIEW, uri)
                    .setComponent(new ComponentName(production, ImportActivity.class.getName()))
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                intent.setClipData(ClipData.newRawUri("Family profile", uri));
                intent.putExtra(COMPLETION, new ResultReceiver(new Handler(Looper.getMainLooper())) {
                    @Override protected void onReceiveResult(int code, Bundle data) {
                        if (code != Activity.RESULT_OK) return;
                        FamilyBootReceiver.setEnabled(activity, false);
                        activity.stopService(new Intent(activity, FamilyService.class));
                        activity.stopService(new Intent(activity, FamilyVoiceService.class));
                        activity.stopService(new Intent(activity, com.meshchatnext.sip.SipService.class));
                        activity.finish();
                        android.os.Process.killProcess(android.os.Process.myPid());
                    }
                });
                activity.runOnUiThread(() -> {
                    try {
                        activity.startActivityForResult(intent, REQUEST);
                    } catch (RuntimeException failure) {
                        archive.delete();
                        toast(activity, "Update the new Family app to a version that supports transfer.");
                    }
                });
            } catch (Exception failure) {
                archive.delete();
                activity.runOnUiThread(() -> toast(activity, "Could not prepare the profile. Unlock Guardian settings and try again."));
            }
        }, "family-transfer-export").start();
    }

    @Override public boolean onCreate() { return true; }

    @Override public synchronized ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        Context context = getContext();
        String recipient = PRODUCTION + testSuffix(context);
        String key = uri.getLastPathSegment();
        if (!"r".equals(mode) || !isLegacy(context) || !recipient.equals(getCallingPackage())
                || !sameSigner(context, recipient) || !(context.getPackageName() + SUFFIX).equals(uri.getAuthority())
                || uri.getPathSegments().size() != 1 || key == null || !key.matches("[0-9a-f-]{36}")) {
            throw new FileNotFoundException("Invalid transfer");
        }
        File archive = new File(transferDirectory(context), key);
        if (!archive.isFile() || System.currentTimeMillis() - archive.lastModified() > EXPIRES_MS) {
            archive.delete();
            throw new FileNotFoundException("Transfer expired");
        }
        ParcelFileDescriptor descriptor = ParcelFileDescriptor.open(archive, ParcelFileDescriptor.MODE_READ_ONLY);
        archive.delete();
        return descriptor;
    }

    @Override public String getType(Uri uri) { return "application/zip"; }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }

    public static final class ImportActivity extends Activity {
        @Override protected void onCreate(Bundle state) {
            super.onCreate(state);
            Uri uri = getIntent().getData();
            String source = LEGACY + testSuffix(this);
            if (isLegacy(this) || !source.equals(getCallingPackage()) || !sameSigner(this, source)
                    || uri == null || !"content".equals(uri.getScheme()) || !(source + SUFFIX).equals(uri.getAuthority())) {
                finish();
                return;
            }
            new AlertDialog.Builder(this).setTitle("Move your Family profile")
                .setMessage("Bring settings, approved contacts, messages and your Reticulum identity into this installation. Transfer requires a new Family installation that has not completed setup.")
                .setNegativeButton("Cancel", (dialog, which) -> finish())
                .setPositiveButton("Transfer", (dialog, which) -> receive(uri))
                .setOnCancelListener(dialog -> finish()).show();
        }

        private void receive(Uri uri) {
            toast(this, "Transferring the Family profile…");
            new Thread(() -> {
                synchronized (IMPORT_LOCK) {
                    File archive = null;
                    try {
                        PyObject backend = FamilyRuntime.backend(this);
                        if (new org.json.JSONObject(backend.callAttr("request", "{\"action\":\"status\"}").toString())
                                .optBoolean("setupComplete")) {
                            runOnUiThread(() -> {
                                toast(this, "This Family app is already set up. Transfer is available before setup.");
                                finish();
                            });
                            return;
                        }
                        archive = File.createTempFile("family-transfer-", ".zip", getCacheDir());
                        try (InputStream input = getContentResolver().openInputStream(uri);
                             FileOutputStream output = new FileOutputStream(archive)) {
                            if (input == null) throw new IOException("Transfer unavailable");
                            byte[] buffer = new byte[64 * 1024];
                            long bytes = 0;
                            for (int count; (count = input.read(buffer)) != -1;) {
                                bytes += count;
                                if (bytes > MAX_ARCHIVE) throw new IOException("Profile exceeds the transfer limit");
                                output.write(buffer, 0, count);
                            }
                        }
                        backend.callAttr("import_migration", archive.getAbsolutePath());
                        runOnUiThread(() -> {
                            setResult(RESULT_OK);
                            startActivity(new Intent(this, MainActivity.class)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
                            ResultReceiver completion = getIntent().getParcelableExtra(COMPLETION);
                            if (completion != null) completion.send(RESULT_OK, null);
                            finish();
                        });
                    } catch (Exception failure) {
                        runOnUiThread(() -> {
                            toast(this, "Could not transfer the profile. Open the old Family app and try again.");
                            finish();
                        });
                    } finally {
                        if (archive != null) archive.delete();
                    }
                }
            }, "family-transfer-import").start();
        }
    }
}
