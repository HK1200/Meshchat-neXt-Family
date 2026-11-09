package org.meshchat.family.preview;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import android.service.notification.StatusBarNotification;

/** Groups connection status while each service retains its own foreground notification. */
public final class AppBackgroundNotification {
    public static final int ID = 6400, LEGACY_SIP_ID = 6409;
    private static final int SUMMARY_ID = 6410;
    private static final String GROUP = "family_background_connections";
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    public static String sipLine(String network, String state, String call) {
        return !"idle".equals(call) ? "Call · " + call :
                "SIP · " + state + (network.isEmpty() ? "" : " · " + network);
    }

    public static Notification.Builder group(Notification.Builder builder) {
        return builder.setGroup(GROUP).setGroupAlertBehavior(Notification.GROUP_ALERT_SUMMARY);
    }

    public static Notification build(Context context, String detail, boolean idle) {
        String channel = "family_sip_connection";
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(channel, "Calling connection",
                NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(context, ID,
                new Intent(context, MainActivity.class).putExtra("openCall", true),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = new Notification.Builder(context, channel)
                .setSmallIcon(R.drawable.ic_family)
                .setContentTitle("neXt Family · calling")
                .setContentText(detail)
                .setOngoing(true)
                .setContentIntent(open);
        return (idle ? group(builder) : builder).build();
    }

    public static void sync(Context context) {
        Context app = context.getApplicationContext();
        // Foreground services enqueue notification changes in Android before they are visible here.
        MAIN.postDelayed(() -> updateSummary(app), 500);
    }

    private static void updateSummary(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        boolean hasConnections = false, hasSummary = false;
        for (StatusBarNotification entry : manager.getActiveNotifications()) {
            if (entry.getId() == SUMMARY_ID) hasSummary = true;
            else if (GROUP.equals(entry.getNotification().getGroup())) hasConnections = true;
        }
        if (hasConnections == hasSummary) return;
        if (!hasConnections) {
            manager.cancel(SUMMARY_ID);
            return;
        }
        manager.createNotificationChannel(new NotificationChannel(GROUP, "Background connections",
                NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(context, SUMMARY_ID,
                new Intent(context, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        manager.notify(SUMMARY_ID, group(new Notification.Builder(context, GROUP))
                .setGroupSummary(true)
                .setSmallIcon(R.drawable.ic_family)
                .setContentTitle("neXt Family")
                .setContentText("Background connections")
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setContentIntent(open)
                .build());
    }
}
