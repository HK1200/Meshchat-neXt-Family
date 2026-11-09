package org.meshchat.family.preview;
import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import com.chaquo.python.android.AndroidPlatform;
/** Serialize cold runtime setup across activities and independently restarted services. */
final class FamilyRuntime {
 private FamilyRuntime(){}
 static String networkContext(Context context){
  try{android.net.Network network=context.getSystemService(android.net.ConnectivityManager.class).getActiveNetwork();return (network==null?"none":String.valueOf(network.getNetworkHandle()))+":"+android.provider.Settings.Global.getInt(context.getContentResolver(),"boot_count",0);}catch(RuntimeException e){return "unknown";}
 }
 static synchronized void allowCalls(Context context){context.getSharedPreferences("boot_recovery",0).edit().putBoolean("defer_calls",false).commit();}
 static synchronized PyObject backend(Context context){
  Context app=context.getApplicationContext();
  if(!Python.isStarted())Python.start(new AndroidPlatform(app));
  Python.getInstance().getModule("family_radios").callAttr("set_context",app);
  PyObject backend=Python.getInstance().getModule("family_backend");
  backend.callAttr("set_network_context",networkContext(app));
  backend.callAttr("set_voice_deferred",app.getSharedPreferences("boot_recovery",0).getBoolean("defer_calls",false));
  backend.callAttr("initialize",new java.io.File(app.getFilesDir(),"family-live").getAbsolutePath());
  return backend;
 }
}
