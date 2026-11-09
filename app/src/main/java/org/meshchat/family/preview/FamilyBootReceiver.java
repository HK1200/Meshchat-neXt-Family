package org.meshchat.family.preview;
import android.app.*;
import android.content.*;
import android.os.*;
import java.io.*;
import org.json.JSONObject;
/** Restore only saved, enabled services after credential storage becomes available. */
public final class FamilyBootReceiver extends BroadcastReceiver {
 static final int NOTICE=43;
 @Override public void onReceive(Context context,Intent intent){
  String action=intent.getAction();
  if(!Intent.ACTION_BOOT_COMPLETED.equals(action)&&!Intent.ACTION_MY_PACKAGE_REPLACED.equals(action))return;
  if(!context.getSystemService(UserManager.class).isUserUnlocked())return;
  PendingResult result=goAsync();
  new Thread(()->{try{restore(context.getApplicationContext(),action);}finally{result.finish();}},"family-boot").start();
 }
 static void restore(Context context,String action){
  boolean messaging=false,voice=false,sip=false,started=false,needsTap=false;
  try{
   File file=new File(context.getFilesDir(),"family-live/state.json");if(!file.isFile())return;
   JSONObject state=new JSONObject(new String(java.nio.file.Files.readAllBytes(file.toPath()),java.nio.charset.StandardCharsets.UTF_8));
   if(!state.optBoolean("setup_complete"))return;
   boolean tcp=state.optJSONObject("peer")!=null&&state.getJSONObject("peer").optBoolean("enabled");
   boolean radio=state.optJSONObject("rnode")!=null&&state.getJSONObject("rnode").optBoolean("enabled");
   boolean mesh=state.optJSONObject("meshcore")!=null&&state.getJSONObject("meshcore").optBoolean("enabled");
   messaging=FamilyBootPolicy.messaging(true,tcp,radio,mesh);voice=state.optBoolean("voiceEnabled")&&(tcp||radio);
   sip=context.getSharedPreferences("sip_accounts",0).getBoolean("enabled",false);
   context.getSharedPreferences("boot_recovery",0).edit().putBoolean("defer_calls",!FamilyBootPolicy.callsAllowed(Build.VERSION.SDK_INT,Intent.ACTION_BOOT_COMPLETED.equals(action))&&(voice||sip)).commit();
   if(messaging){try{context.startForegroundService(new Intent(context,FamilyService.class));started=true;}catch(RuntimeException e){needsTap=true;}}
   if(FamilyBootPolicy.callsAllowed(Build.VERSION.SDK_INT,Intent.ACTION_BOOT_COMPLETED.equals(action))){
    if(voice)try{context.startForegroundService(new Intent(context,FamilyVoiceService.class));}catch(RuntimeException e){needsTap=true;}
    if(sip)try{context.startForegroundService(new Intent(context,com.meshchatnext.sip.SipService.class).setAction("restore_saved"));}catch(RuntimeException e){needsTap=true;}
   }else if(voice||sip)needsTap=true;
   if(needsTap)notifyRestore(context);
  }catch(Exception e){android.util.Log.e("FamilyBoot","Saved service recovery failed",e);needsTap=true;notifyRestore(context);}
  finally{context.getSharedPreferences("boot_recovery",0).edit().putString("last_action",action).putLong("last_attempt",System.currentTimeMillis()).putBoolean("messaging_requested",messaging).putBoolean("messaging_started",started).putBoolean("calls_requested",voice||sip).putBoolean("needs_tap",needsTap).apply();}
 }
 private static void notifyRestore(Context context){
  NotificationManager manager=context.getSystemService(NotificationManager.class);
  manager.createNotificationChannel(new NotificationChannel("family_recovery","Connection recovery",NotificationManager.IMPORTANCE_DEFAULT));
  PendingIntent open=PendingIntent.getActivity(context,NOTICE,new Intent(context,MainActivity.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
  try{manager.notify(NOTICE,new Notification.Builder(context,"family_recovery").setSmallIcon(R.drawable.ic_family).setContentTitle("Restore family connections").setContentText("Tap to restore calling and check your connections.").setContentIntent(open).setAutoCancel(true).setVisibility(Notification.VISIBILITY_PRIVATE).build());}catch(SecurityException ignored){}
 }
}
