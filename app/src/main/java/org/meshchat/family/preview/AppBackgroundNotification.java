package org.meshchat.family.preview;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;

/** All idle foreground services share one system notification. */
public final class AppBackgroundNotification {
    public static final int ID = 6411;
    private static final String CHANNEL = "family_connection_status";

    public static Notification build(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Connection status",
                NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(context, ID,
                new Intent(context, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_family)
                .setContentTitle("neXt Family")
                .setContentText("Open Family to see connection status")
                .setOnlyAlertOnce(true)
                .setOngoing(true)
                .setContentIntent(open)
                .build();
    }
}
