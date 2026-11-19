package org.meshchat.family.preview;

import android.app.Activity;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.companion.AssociationInfo;
import android.companion.AssociationRequest;
import android.companion.BluetoothDeviceFilter;
import android.companion.BluetoothLeDeviceFilter;
import android.companion.CompanionDeviceManager;
import android.content.Intent;
import android.content.IntentSender;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import java.util.UUID;
import java.util.regex.Pattern;
import org.json.JSONObject;

/** Runs the Android companion picker for a guardian-selected radio type. */
final class RadioAssociation {
    static final int REQUEST = 54;
    private static final Pattern RNODE_NAME = Pattern.compile("^RNode.*", Pattern.CASE_INSENSITIVE);
    private final Activity activity;
    private volatile JSONObject result = new JSONObject();
    private volatile boolean pending;

    RadioAssociation(Activity activity) {
        this.activity = activity;
    }

    boolean isPending() {
        return pending;
    }

    String status() {
        return result.toString();
    }

    void start(String type) {
        if (pending) return;
        CompanionDeviceManager manager = activity.getSystemService(CompanionDeviceManager.class);
        if (manager == null) {
            finish(null, "Android companion pairing is unavailable.");
            return;
        }
        AssociationRequest.Builder request = new AssociationRequest.Builder().setSingleDevice(false);
        if ("classic".equals(type)) {
            request.addDeviceFilter(new BluetoothDeviceFilter.Builder().setNamePattern(RNODE_NAME).build());
        } else {
            BluetoothLeDeviceFilter.Builder filter = new BluetoothLeDeviceFilter.Builder();
            if ("meshcore".equals(type)) {
                ParcelUuid uart = new ParcelUuid(UUID.fromString("6e400001-b5a3-f393-e0a9-e50e24dcca9e"));
                filter.setScanFilter(new ScanFilter.Builder().setServiceUuid(uart).build());
            } else {
                filter.setNamePattern(RNODE_NAME);
            }
            request.addDeviceFilter(filter.build());
        }
        pending = true;
        result = new JSONObject();
        try {
            manager.associate(request.build(), new CompanionDeviceManager.Callback() {
                @Override public void onDeviceFound(IntentSender sender) {
                    try {
                        activity.startIntentSenderForResult(sender, REQUEST, null, 0, 0, 0);
                    } catch (IntentSender.SendIntentException error) {
                        finish(null, "Could not open Android’s radio picker.");
                    }
                }

                @Override public void onFailure(CharSequence message) {
                    finish(null, message == null ? "No compatible radio found." : message.toString());
                }
            }, new Handler(Looper.getMainLooper()));
        } catch (RuntimeException error) {
            finish(null, "Could not start Android companion pairing.");
        }
    }

    @SuppressWarnings("deprecation")
    void onResult(int resultCode, Intent data) {
        if (resultCode != Activity.RESULT_OK || data == null) {
            finish(null, "No radio selected.");
            return;
        }
        Object selected = data.getParcelableExtra(CompanionDeviceManager.EXTRA_DEVICE);
        if (selected instanceof ScanResult) selected = ((ScanResult) selected).getDevice();
        if (selected instanceof BluetoothDevice) {
            finish(((BluetoothDevice) selected).getAddress(), null);
        } else if (Build.VERSION.SDK_INT >= 33) {
            AssociationInfo association = data.getParcelableExtra(CompanionDeviceManager.EXTRA_ASSOCIATION);
            finish(association == null || association.getDeviceMacAddress() == null
                    ? null : association.getDeviceMacAddress().toString(), "No Bluetooth address was returned.");
        } else {
            finish(null, "No Bluetooth address was returned.");
        }
    }

    private void finish(String address, String error) {
        JSONObject value = new JSONObject();
        try {
            if (address != null) value.put("address", address);
            else value.put("error", error);
        } catch (org.json.JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
        result = value;
        pending = false;
    }
}
