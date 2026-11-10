package org.meshchat.family.preview;

import android.app.Activity;
import android.app.ActivityOptions;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInstaller;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Private activity for an explicitly requested, Android-confirmed update. */
public final class FamilyUpdateActivity extends Activity {
    private static final String RESULT = "org.meshchat.family.preview.UPDATE_RESULT";
    private static final int INSTALL_PERMISSION = 1901;
    private static final AtomicBoolean ACTIVE = new AtomicBoolean();

    private TextView message;
    private Button proceed;
    private volatile File verified;
    private FamilyUpdates.Release release;
    private volatile boolean cancelled;
    private boolean ownsDownload;
    private boolean awaitingPermission;
    private boolean staging;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(24 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding, padding, padding);
        TextView title = new TextView(this);
        title.setText("Install Family update");
        title.setTextSize(22);
        layout.addView(title);
        message = new TextView(this);
        layout.addView(message);
        proceed = new Button(this);
        proceed.setText("Continue to Android installer");
        proceed.setEnabled(false);
        proceed.setOnClickListener(view -> continueInstall());
        layout.addView(proceed);
        Button close = new Button(this);
        close.setText("Close");
        close.setOnClickListener(view -> finish());
        layout.addView(close);
        setContentView(layout);
        if (RESULT.equals(getIntent().getAction())) {
            handleResult(getIntent());
            return;
        }
        ownsDownload = ACTIVE.compareAndSet(false, true);
        if (!ownsDownload) {
            finish();
            return;
        }
        message.setText("Downloading and verifying the Family update…");
        new Thread(this::prepare, "family-verify-update").start();
    }

    private void prepare() {
        File file = null;
        try {
            String repo = getIntent().getStringExtra("repository");
            if (!FamilyUpdates.get(this).repository().equals(repo)) throw new IOException();
            release = FamilyUpdates.parse(repo, new JSONObject(getIntent().getStringExtra("release")), getPackageName());
            file = File.createTempFile("family-update-", ".apk", getCacheDir());
            FamilyUpdates.download(release, file, () -> cancelled);
            FamilyUpdates.verifyApk(this, file, release);
            if (cancelled || !FamilyUpdates.get(this).repository().equals(release.repo)) throw new IOException();
            verified = file;
            file = null;
            runOnUiThread(() -> {
                if (!isFinishing()) {
                    message.setText("Verified Family " + release.name + ". Review the update in Android.");
                    continueInstall();
                }
            });
        } catch (Exception error) {
            show("Could not download or verify this Family update. Return to Family to retry.");
        } finally {
            if (file != null) file.delete();
        }
    }

    private void continueInstall() {
        File file = verified;
        if (file == null || !file.isFile() || cancelled || awaitingPermission || staging) return;
        proceed.setEnabled(false);
        if (!getPackageManager().canRequestPackageInstalls()) {
            message.setText("Allow Family to install updates in Android settings, then return here.");
            try {
                awaitingPermission = true;
                startActivityForResult(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + getPackageName())), INSTALL_PERMISSION);
            } catch (RuntimeException error) {
                awaitingPermission = false;
                message.setText("Android could not open install permissions.");
                proceed.setEnabled(true);
            }
            return;
        }
        staging = true;
        message.setText("Preparing Android’s install confirmation…");
        new Thread(() -> stage(file), "family-install-update").start();
    }

    private SharedPreferences resultPreferences() {
        return getSharedPreferences("family_update_install", MODE_PRIVATE);
    }

    private void stage(File file) {
        PackageInstaller installer = getPackageManager().getPackageInstaller();
        int id = -1;
        try {
            if (!FamilyUpdates.get(this).repository().equals(release.repo)) throw new IOException();
            FamilyUpdates.verifyApk(this, file, release);
            PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(
                    PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            params.setAppPackageName(getPackageName());
            params.setSize(file.length());
            if (Build.VERSION.SDK_INT >= 31) {
                params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED);
            }
            id = installer.createSession(params);
            try (PackageInstaller.Session session = installer.openSession(id)) {
                try (FileInputStream input = new FileInputStream(file);
                        OutputStream output = session.openWrite("base.apk", 0, file.length())) {
                    byte[] buffer = new byte[65_536];
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        if (cancelled) throw new IOException();
                        output.write(buffer, 0, count);
                    }
                    session.fsync(output);
                }
                if (cancelled) throw new IOException();
                String token = UUID.randomUUID().toString();
                if (!resultPreferences().edit().putInt("session", id).putString("token", token).commit()) {
                    throw new IOException();
                }
                Intent result = new Intent(this, FamilyUpdateActivity.class).setAction(RESULT)
                        .setData(Uri.parse("family-update://install/" + token))
                        .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= 31) flags |= PendingIntent.FLAG_MUTABLE;
                Bundle options = null;
                if (Build.VERSION.SDK_INT >= 35) {
                    options = ActivityOptions.makeBasic()
                            .setPendingIntentCreatorBackgroundActivityStartMode(
                                    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED)
                            .toBundle();
                }
                session.commit(PendingIntent.getActivity(this, id, result, flags, options).getIntentSender());
            }
            id = -1; // The committed session now belongs to Android.
        } catch (Exception error) {
            if (id >= 0) {
                try { installer.abandonSession(id); } catch (RuntimeException ignored) {}
            }
            show("Android could not prepare the update. Return to Family to retry.");
        } finally {
            file.delete();
            verified = null;
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == INSTALL_PERMISSION) resumeInstallPermission();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (awaitingPermission) resumeInstallPermission();
    }

    private void resumeInstallPermission() {
        if (!awaitingPermission) return;
        awaitingPermission = false;
        if (getPackageManager().canRequestPackageInstalls()) {
            continueInstall();
        } else {
            proceed.setEnabled(true);
            message.setText("Install permission is off. You can retry or close this screen.");
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (RESULT.equals(intent.getAction())) handleResult(intent);
    }

    private void handleResult(Intent intent) {
        SharedPreferences prefs = resultPreferences();
        String token = prefs.getString("token", "");
        if (token.isEmpty() || intent.getData() == null || !token.equals(intent.getData().getLastPathSegment())
                || prefs.getInt("session", -1) != intent.getIntExtra(PackageInstaller.EXTRA_SESSION_ID, -2)) {
            finish();
            return;
        }
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirmation = Build.VERSION.SDK_INT >= 33
                    ? intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent.class)
                    : intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirmation != null) {
                message.setText("Approve the update in Android’s installer.");
                try {
                    startActivity(confirmation);
                } catch (RuntimeException error) {
                    show("Android could not open the install confirmation. Close this screen and retry.");
                }
            } else {
                show("Android did not provide an install confirmation.");
            }
            return;
        }
        prefs.edit().clear().apply();
        if (status == PackageInstaller.STATUS_SUCCESS) {
            message.setText("Family is updated.");
            proceed.setText("Open Family");
            proceed.setOnClickListener(view -> {
                startActivity(new Intent(this, MainActivity.class));
                finish();
            });
            proceed.setEnabled(true);
        } else {
            if (status == PackageInstaller.STATUS_FAILURE_ABORTED) {
                message.setText("The update was cancelled.");
            } else if (status == PackageInstaller.STATUS_FAILURE_BLOCKED) {
                message.setText("Android blocked the update. Check the installer or Play Protect for details.");
            } else {
                message.setText("Android could not install the update.");
            }
        }
    }

    private void show(String value) {
        runOnUiThread(() -> {
            if (!cancelled && !isFinishing()) message.setText(value);
        });
    }

    @Override
    protected void onDestroy() {
        cancelled = true;
        File file = verified;
        if (file != null) file.delete();
        if (ownsDownload) ACTIVE.set(false);
        super.onDestroy();
    }
}
