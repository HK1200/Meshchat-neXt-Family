package org.meshchat.family.preview;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Looper;
import android.os.SystemClock;
import com.chaquo.python.PyObject;
import org.json.JSONObject;

/** Requests fixes only while an approved sharing session is active. */
public final class FamilyLocationRuntime implements LocationListener {
    private static final long MOVING_INTERVAL_MS = 30_000;
    private static final long STOPPED_INTERVAL_MS = 90_000;
    private static final String[] PROVIDERS = {
        LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER
    };

    private final Context context;
    private final PyObject backend;
    private LocationManager manager;
    private volatile boolean running;
    private long interval = MOVING_INTERVAL_MS;

    public FamilyLocationRuntime(Context context, PyObject backend) {
        this.context = context;
        this.backend = backend;
    }

    public boolean start() {
        if (context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            backend.callAttr("location_error", "Allow location access in guardian map settings.");
            return false;
        }
        try {
            if (running) {
                updateInterval(MOVING_INTERVAL_MS);
                return running;
            }
            manager = (LocationManager) context.getSystemService(Context.LOCATION_SERVICE);
            interval = MOVING_INTERVAL_MS;
            running = register(interval);
            if (!running) {
                backend.callAttr("location_error", "Turn on device location to share your position.");
                return false;
            }
            for (String provider : PROVIDERS) {
                try {
                    Location last = manager.getLastKnownLocation(provider);
                    if (last != null && SystemClock.elapsedRealtimeNanos()
                            - last.getElapsedRealtimeNanos() < 120_000_000_000L) {
                        onLocationChanged(last);
                    }
                } catch (SecurityException ignored) {
                    // Coarse permission can exclude the GPS provider.
                }
            }
            return running;
        } catch (RuntimeException error) {
            stop();
            backend.callAttr("location_error", "Location service unavailable.");
            return false;
        }
    }

    private boolean register(long period) {
        boolean attached = false;
        for (String provider : PROVIDERS) {
            if (!manager.isProviderEnabled(provider)) continue;
            try {
                manager.requestLocationUpdates(provider, period, 0, this, Looper.getMainLooper());
                attached = true;
            } catch (SecurityException ignored) {
                // Use the remaining provider if permission permits it.
            }
        }
        return attached;
    }

    private void updateInterval(long desired) {
        if (desired == interval || manager == null || !running) return;
        if (desired != MOVING_INTERVAL_MS && desired != STOPPED_INTERVAL_MS) return;
        manager.removeUpdates(this);
        running = register(desired);
        if (running) {
            interval = desired;
        } else {
            running = register(interval);
            if (!running) backend.callAttr("location_error", "Location service unavailable.");
        }
    }

    public void stop() {
        running = false;
        if (manager != null) manager.removeUpdates(this);
    }

    @Override
    public void onLocationChanged(Location location) {
        if (!running) return;
        try {
            JSONObject fix = new JSONObject()
                    .put("latitude", location.getLatitude())
                    .put("longitude", location.getLongitude())
                    .put("altitude", location.hasAltitude() ? location.getAltitude() : 0)
                    .put("accuracy", Math.min(655.35, location.hasAccuracy() ? location.getAccuracy() : 0))
                    .put("speed", location.hasSpeed() ? location.getSpeed() : 0)
                    .put("bearing", location.hasBearing() ? location.getBearing() : 0)
                    .put("last_update", location.getTime() / 1000.0);
            PyObject desired = backend.callAttr("record_location", fix.toString());
            if (desired != null) updateInterval(desired.toLong());
        } catch (Exception ignored) {
            // An invalid fix must never interrupt the location callback.
        }
    }

    @Override
    public void onProviderDisabled(String provider) {
        backend.callAttr("location_error", "Location provider is disabled.");
    }

    @Override
    public void onStatusChanged(String provider, int status, android.os.Bundle extras) {}

    @Override
    public void onProviderEnabled(String provider) {}
}
