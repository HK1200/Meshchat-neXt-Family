package org.meshchat.family.preview;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import java.util.ArrayList;
import java.util.List;
import java.util.function.BooleanSupplier;

/** Explains one permission before opening its Android prompt or settings. */
final class PermissionCheckup {
    private static final int REQUEST = 9171;
    private static final int SETTINGS = 9172;
    private final Activity activity;
    private final List<Step> steps = new ArrayList<>();
    private int next;
    private boolean active;
    private volatile boolean requestInFlight;
    private AlertDialog dialog;

    private static final class Step {
        final String title;
        final String reason;
        final BooleanSupplier granted;
        final Runnable request;

        Step(String title, String reason, BooleanSupplier granted, Runnable request) {
            this.title = title;
            this.reason = reason;
            this.granted = granted;
            this.request = request;
        }
    }

    PermissionCheckup(Activity activity) {
        this.activity = activity;
    }

    boolean isRequestInFlight() {
        return requestInFlight;
    }

    void show() {
        if (active || activity.isFinishing() || activity.isDestroyed()) return;
        active = true;
        next = 0;
        steps.clear();

        NotificationManager notifications = activity.getSystemService(NotificationManager.class);
        if (notifications != null) {
            steps.add(new Step("Notifications", "Show incoming calls and new messages when the app is in the background.",
                notifications::areNotificationsEnabled, () -> {
                    if (Build.VERSION.SDK_INT >= 33 && !granted(Manifest.permission.POST_NOTIFICATIONS)) {
                        request(Manifest.permission.POST_NOTIFICATIONS);
                    } else {
                        open(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                            .putExtra(Settings.EXTRA_APP_PACKAGE, activity.getPackageName()));
                    }
                }));
        }
        runtime("Microphone", "Let the other person hear you during a call.",
            Manifest.permission.RECORD_AUDIO);
        if (Build.VERSION.SDK_INT >= 31) {
            runtime("Nearby Bluetooth devices", "Find and connect to Bluetooth radios and compatible headsets.",
                Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT);
        }
        if (activity.getPackageManager().hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY)) {
            runtime("Camera", "Scan contact and room QR codes with the camera.",
                Manifest.permission.CAMERA);
        }
        runtime("Location while using the app", "Use your location for the family map and sharing you enable. Older Android versions also need this to find Bluetooth radios.",
            Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION);
        dialog = new AlertDialog.Builder(activity)
            .setTitle("Permission checkup")
            .setMessage("Review permissions one at a time. Each step explains what it enables, and you can skip features you don’t use.")
            .setPositiveButton("Start checkup", (d, which) -> advance())
            .setNegativeButton("Not now", (d, which) -> finish())
            .setOnCancelListener(d -> finish())
            .show();
    }

    private boolean granted(String permission) {
        return activity.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }

    private void runtime(String title, String reason, String... permissions) {
        steps.add(new Step(title, reason, () -> {
            if (Manifest.permission.ACCESS_COARSE_LOCATION.equals(permissions[0])) {
                return granted(Manifest.permission.ACCESS_COARSE_LOCATION);
            }
            for (String permission : permissions) {
                if (!granted(permission)) return false;
            }
            return true;
        }, () -> request(permissions)));
    }

    private void request(String... permissions) {
        android.content.SharedPreferences history = activity.getSharedPreferences("permission_checkup", Activity.MODE_PRIVATE);
        List<String> missing = new ArrayList<>();
        for (String permission : permissions) {
            if (!granted(permission)) {
                if (history.getBoolean(permission, false)
                    && !activity.shouldShowRequestPermissionRationale(permission)) {
                    open(packageSettings(Settings.ACTION_APPLICATION_DETAILS_SETTINGS));
                    return;
                }
                missing.add(permission);
            }
        }
        if (missing.isEmpty()) {
            advance();
            return;
        }
        android.content.SharedPreferences.Editor editor = history.edit();
        for (String permission : missing) editor.putBoolean(permission, true);
        editor.apply();
        requestInFlight = true;
        activity.requestPermissions(missing.toArray(new String[0]), REQUEST);
    }

    private Intent packageSettings(String action) {
        return new Intent(action, Uri.parse("package:" + activity.getPackageName()));
    }

    private void open(Intent intent) {
        try {
            requestInFlight = true;
            activity.startActivityForResult(intent, SETTINGS);
        } catch (ActivityNotFoundException | SecurityException error) {
            requestInFlight = false;
            if (!Settings.ACTION_APPLICATION_DETAILS_SETTINGS.equals(intent.getAction())) {
                open(packageSettings(Settings.ACTION_APPLICATION_DETAILS_SETTINGS));
            } else {
                advance();
            }
        }
    }

    boolean onResult(int requestCode) {
        if (requestCode != REQUEST && requestCode != SETTINGS) return false;
        requestInFlight = false;
        if (active) activity.getWindow().getDecorView().post(this::advance);
        return true;
    }

    private void advance() {
        if (!active || activity.isFinishing() || activity.isDestroyed()) return;
        while (next < steps.size()) {
            Step step = steps.get(next++);
            if (step.granted.getAsBoolean()) continue;
            dialog = new AlertDialog.Builder(activity)
                .setTitle(step.title)
                .setMessage(step.reason)
                .setPositiveButton("Continue", (d, which) -> step.request.run())
                .setNegativeButton("Skip", (d, which) -> advance())
                .setOnCancelListener(d -> finish())
                .show();
            return;
        }
        List<String> missing = new ArrayList<>();
        for (Step step : steps) if (!step.granted.getAsBoolean()) missing.add(step.title);
        dialog = new AlertDialog.Builder(activity)
            .setTitle("Permission checkup complete")
            .setMessage(missing.isEmpty() ? "All permissions in this checkup are enabled."
                : "You can revisit these permissions later.\n\n" + String.join("\n", missing))
            .setPositiveButton("Done", (d, which) -> finish())
            .setOnCancelListener(d -> finish())
            .show();
    }

    void finish() {
        active = false;
        requestInFlight = false;
        if (dialog != null) dialog.dismiss();
        dialog = null;
    }
}
