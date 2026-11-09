package org.meshchat.family.preview;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

import com.chaquo.python.PyObject;
import java.io.File;
import java.io.IOException;
import java.net.URI;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONObject;

final class FamilyMapDownload {
    private static final String REPO = "hk1200/Meshchat-neXt";
    private static final URI PNW = URI.create(
            "https://github.com/" + REPO + "/releases/download/v0.1.0/MeshchatNext-PNW-SouthernBC-detail.mbtiles");
    private static final long PNW_BYTES = 108_847_104;
    private static final String PNW_DIGEST = "a9b66376fbb9656c4e0ee20ff8c28b29cbd1b98eefaa23ba2a8ad71e4fd692d5";

    private final Context context;
    private final PyObject backend;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean busy = new AtomicBoolean();
    private volatile String message = "", result = "";
    private LocationManager manager;
    private LocationListener listener;
    private Runnable timeout;

    FamilyMapDownload(Context context, PyObject backend) {
        this.context = context.getApplicationContext();
        this.backend = backend;
    }

    String status() {
        try {
            return new JSONObject().put("busy", busy.get()).put("message", message).put("result", result).toString();
        } catch (Exception ignored) { return "{}"; }
    }

    void unavailable() {
        result = "location-unavailable";
        message = "Could not find your region. You can download the PNW pack or have a guardian import another region.";
        busy.set(false);
    }

    void start(boolean useLocation) {
        if (!busy.compareAndSet(false, true)) return;
        result = "";
        if (!useLocation) {
            download();
            return;
        }
        if (context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            unavailable();
            return;
        }
        message = "Finding your map region…";
        manager = context.getSystemService(LocationManager.class);
        if (manager == null) { unavailable(); return; }
        listener = new LocationListener() {
            @Override public void onLocationChanged(Location location) { onFix(location); }
            @Override public void onProviderDisabled(String provider) {}
            @Override public void onProviderEnabled(String provider) {}
            @Override public void onStatusChanged(String provider, int status, android.os.Bundle extras) {}
        };
        boolean registered = false;
        for (String provider : new String[]{LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER}) {
            try {
                Location last = manager.getLastKnownLocation(provider);
                if (last != null && SystemClock.elapsedRealtimeNanos() - last.getElapsedRealtimeNanos() < 900_000_000_000L) {
                    listener.onLocationChanged(last);
                    return;
                }
                if (manager.isProviderEnabled(provider)) {
                    manager.requestLocationUpdates(provider, 0, 0, listener, Looper.getMainLooper());
                    registered = true;
                }
            } catch (IllegalArgumentException | SecurityException ignored) {}
        }
        if (!registered) { stopLocation(); unavailable(); return; }
        timeout = () -> { stopLocation(); unavailable(); };
        main.postDelayed(timeout, 15_000);
    }

    private void onFix(Location location) {
        if (listener == null) return;
        stopLocation();
        if (location.getLatitude() >= 42 && location.getLatitude() <= 53
                && location.getLongitude() >= -128 && location.getLongitude() <= -110) {
            download();
        } else {
            result = "outside-coverage";
            message = "There’s no downloadable pack for your region yet. A guardian can import a local MBTiles map.";
            busy.set(false);
        }
    }

    void cancelLocation() {
        if (listener == null) return;
        stopLocation();
        unavailable();
    }

    private void stopLocation() {
        if (timeout != null) main.removeCallbacks(timeout);
        timeout = null;
        if (listener != null && manager != null) {
            try { manager.removeUpdates(listener); } catch (SecurityException ignored) {}
        }
        listener = null;
    }

    private void download() {
        message = "Downloading the PNW and southern BC map · 104 MiB…";
        new Thread(() -> {
            File temp = null;
            try {
                File directory = new File(context.getFilesDir(), "family-live/maps");
                if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Map storage is unavailable.");
                temp = new File(directory, "import-" + UUID.randomUUID() + ".tmp");
                HttpsURLConnection connection = FamilyUpdates.openRelease(PNW,
                        uri -> FamilyUpdateSource.allowsMap(uri, REPO, PNW.getPath()), "neXt-Family-Maps");
                FamilyUpdates.downloadVerified(connection, temp, PNW_BYTES, PNW_DIGEST, 480_000, () -> false);
                JSONObject install = new JSONObject(backend.callAttr("install_catalog_map", temp.getAbsolutePath()).toString());
                if (!install.optBoolean("ok")) throw new IOException(install.optString("error", "Map install failed."));
                result = "installed";
                message = "Offline map is ready.";
            } catch (Exception ignored) {
                result = "failed";
                message = "Could not download or verify the map. Check internet access and try again.";
            } finally {
                if (temp != null) temp.delete();
                busy.set(false);
            }
        }, "Family-map-download").start();
    }
}
