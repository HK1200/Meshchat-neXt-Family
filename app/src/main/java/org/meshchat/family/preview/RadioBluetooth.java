package org.meshchat.family.preview;
import android.annotation.SuppressLint;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.Context;
import android.content.BroadcastReceiver;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Handler;
import android.os.Looper;
import org.json.*;
import java.util.concurrent.ConcurrentHashMap;
/** Short, guardian-requested scans. Never connects to a radio implicitly. */
@SuppressLint("MissingPermission")
public final class RadioBluetooth {
 private static final ConcurrentHashMap<String,JSONObject> found=new ConcurrentHashMap<>();
 private static BluetoothLeScanner scanner;private static ScanCallback callback;
 private static BroadcastReceiver classicReceiver;private static Context receiverContext;
 private static void stopClassic(BluetoothAdapter adapter){if(adapter.isDiscovering())adapter.cancelDiscovery();if(classicReceiver!=null){try{receiverContext.unregisterReceiver(classicReceiver);}catch(Exception ignored){}classicReceiver=null;}}
 public static synchronized String scan(Context context) throws Exception {
  if(android.os.Build.VERSION.SDK_INT>=31&&(context.checkSelfPermission(android.Manifest.permission.BLUETOOTH_SCAN)!=android.content.pm.PackageManager.PERMISSION_GRANTED||context.checkSelfPermission(android.Manifest.permission.BLUETOOTH_CONNECT)!=android.content.pm.PackageManager.PERMISSION_GRANTED))throw new Exception("Tap Allow Bluetooth access first.");
  BluetoothAdapter adapter=((BluetoothManager)context.getSystemService(Context.BLUETOOTH_SERVICE)).getAdapter();
  if(adapter==null||!adapter.isEnabled())throw new Exception("Turn on Bluetooth first.");
  if(callback!=null&&scanner!=null)scanner.stopScan(callback);
  stopClassic(adapter);
  found.clear();
  for(BluetoothDevice d:adapter.getBondedDevices())add(d,d.getName(),0);
  scanner=adapter.getBluetoothLeScanner();if(scanner==null)throw new Exception("Bluetooth scanner unavailable");
  callback=new ScanCallback(){@Override public void onScanResult(int type,ScanResult r){String n=r.getScanRecord()==null?null:r.getScanRecord().getDeviceName();add(r.getDevice(),n,r.getRssi());}};
  ScanCallback current=callback;scanner.startScan(callback);
  new Handler(Looper.getMainLooper()).postDelayed(()->{synchronized(RadioBluetooth.class){if(callback==current){scanner.stopScan(current);callback=null;
   // Classic and BLE discovery run sequentially so they do not compete.
   receiverContext=context.getApplicationContext();
   classicReceiver=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent intent){BluetoothDevice device=intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE);if(device!=null)add(device,intent.getStringExtra(BluetoothDevice.EXTRA_NAME),intent.getShortExtra(BluetoothDevice.EXTRA_RSSI,(short)0));}};
   IntentFilter filter=new IntentFilter(BluetoothDevice.ACTION_FOUND);
   if(android.os.Build.VERSION.SDK_INT>=33)receiverContext.registerReceiver(classicReceiver,filter,Context.RECEIVER_EXPORTED);else receiverContext.registerReceiver(classicReceiver,filter);
   adapter.startDiscovery();new Handler(Looper.getMainLooper()).postDelayed(()->{synchronized(RadioBluetooth.class){stopClassic(adapter);}},12000);}}},10000);
  return snapshot();
 }
 private static void add(BluetoothDevice d,String name,int rssi){try{if(name==null)name=d.getName();if(name==null||!name.toLowerCase(java.util.Locale.ROOT).startsWith("rnode"))return;found.put(d.getAddress(),new JSONObject().put("name",name).put("address",d.getAddress()).put("type",d.getType()).put("paired",d.getBondState()==BluetoothDevice.BOND_BONDED).put("rssi",rssi));}catch(Exception ignored){}}
 public static String snapshot(){return new JSONArray(found.values()).toString();}
 public static boolean pair(Context context,String address){BluetoothAdapter a=((BluetoothManager)context.getSystemService(Context.BLUETOOTH_SERVICE)).getAdapter();stopClassic(a);BluetoothDevice d=a.getRemoteDevice(address);return d.getBondState()==BluetoothDevice.BOND_BONDED||d.createBond();}
}
