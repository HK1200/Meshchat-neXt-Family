package org.meshchat.family.preview;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.service.notification.StatusBarNotification;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Presents call actions without exposing Family's other screens above the lock screen. */
public final class FamilyIncomingCallActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable watchCall = new Runnable() {
        @Override public void run() {
            if (isRinging()) handler.postDelayed(this, 500);
            else finish();
        }
    };

    public static void attach(Context context, Notification.Builder notification, int notificationId,
                              String callId, String caller, PendingIntent answer, PendingIntent decline) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null || (Build.VERSION.SDK_INT >= 34 && !manager.canUseFullScreenIntent())) return;

        Intent screen = new Intent(context, FamilyIncomingCallActivity.class)
            .setData(new Uri.Builder().scheme("family-incoming").authority(String.valueOf(notificationId))
                .appendPath(callId).build())
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra("notificationId", notificationId)
            .putExtra("caller", caller)
            .putExtra("answer", answer)
            .putExtra("decline", decline);
        Bundle call = new Bundle();
        call.putString("familyRingingCall", callId);
        notification.addExtras(call);
        notification.setFullScreenIntent(PendingIntent.getActivity(context, notificationId, screen,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE), true);
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }
        showCall();
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        showCall();
        handler.removeCallbacks(watchCall);
        handler.post(watchCall);
    }

    private void showCall() {
        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setGravity(Gravity.CENTER);
        int padding = Math.round(24 * getResources().getDisplayMetrics().density);
        screen.setPadding(padding, padding, padding, padding);
        TextView title = new TextView(this);
        title.setText("Incoming call");
        title.setTextSize(22);
        screen.addView(title);
        TextView name = new TextView(this);
        name.setText(getIntent().getStringExtra("caller"));
        name.setTextSize(30);
        name.setGravity(Gravity.CENTER);
        screen.addView(name);
        addAction(screen, "Answer", "answer");
        addAction(screen, "Decline", "decline");
        setContentView(screen);
    }

    private void addAction(LinearLayout screen, String title, String key) {
        Button button = new Button(this);
        button.setText(title);
        button.setOnClickListener(view -> {
            if (isRinging()) {
                PendingIntent action = getIntent().getParcelableExtra(key);
                if (action != null) {
                    try {
                        action.send();
                        button.setEnabled(false);
                        return;
                    } catch (PendingIntent.CanceledException ignored) {
                        // The call ended before the action could be dispatched.
                    }
                }
            }
            finish();
        });
        screen.addView(button);
    }

    private boolean isRinging() {
        Intent intent = getIntent();
        int id = intent.getIntExtra("notificationId", -1);
        if (id < 0 || intent.getData() == null) return false;
        NotificationManager manager = getSystemService(NotificationManager.class);
        String callId = intent.getData().getLastPathSegment();
        if (manager == null || callId == null) return false;
        for (StatusBarNotification active : manager.getActiveNotifications()) {
            if (active.getId() == id && callId.equals(active.getNotification().extras.getString("familyRingingCall"))) {
                return true;
            }
        }
        return false;
    }

    @Override protected void onStart() {
        super.onStart();
        handler.post(watchCall);
    }

    @Override protected void onStop() {
        handler.removeCallbacks(watchCall);
        super.onStop();
    }
}
