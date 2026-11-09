package org.meshchat.family.preview;
import android.app.*;
import android.content.Intent;
import android.os.*;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import java.util.concurrent.*;
import org.json.JSONObject;
/** Keeps the standalone TCP/LXMF runtime alive with an explicit silent notification. */
public class FamilyService extends Service {
 private final ScheduledExecutorService worker=Executors.newSingleThreadScheduledExecutor();
 private FamilyLocationRuntime locationRuntime;
 private FamilyMessageNotifications messageNotifications;
 private volatile boolean locationForeground;
 private static final String CHANNEL="reticulum_connection";
 private Notification notification(String detail){
  PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
  return AppBackgroundNotification.group(new Notification.Builder(this,CHANNEL)).setSmallIcon(R.drawable.ic_family).setContentTitle("neXt Family · messaging").setContentText(detail).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).build();
 }
 @Override public void onCreate(){
  super.onCreate();NotificationManager manager=getSystemService(NotificationManager.class);
  manager.createNotificationChannel(new NotificationChannel(CHANNEL,"Reticulum connection",NotificationManager.IMPORTANCE_LOW));
  messageNotifications=new FamilyMessageNotifications(this);
  showForeground(false);
  AppBackgroundNotification.sync(this);
  worker.scheduleWithFixedDelay(()->{try{
   PyObject backend=FamilyRuntime.backend(this);
   JSONObject state=new JSONObject(backend.callAttr("request","{\"action\":\"status\"}").toString());
   JSONObject location=state.optJSONObject("location");if(!state.optBoolean("messagingEnabled")&&(location==null||!location.optBoolean("active"))){stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();return;}if(locationForeground&&(location==null||!location.optBoolean("active")))new Handler(Looper.getMainLooper()).post(()->setLocation(false));
   JSONObject peer=state.optJSONObject("peer");String host=peer==null?"TCP peer":peer.optString("host");
   JSONObject radio=state.optJSONObject("rnodeRuntime");boolean radioOnline=radio!=null&&radio.optBoolean("online");
   String detail=state.optBoolean("tcpOnline")?(radioOnline?"TCP and RNode connected":"Connected to "+host):radioOnline?"RNode connected":state.optBoolean("connecting")?"Connecting to "+host:"Reticulum disconnected · open for details";
   JSONObject mesh=state.optJSONObject("meshcore");if(mesh!=null&&mesh.optBoolean("connected"))detail=(state.optBoolean("online")?"Reticulum and MeshCore connected":"MeshCore connected")+" · "+mesh.optString("name","companion");if(locationForeground)detail="Location sharing active · "+detail;
   manager.notify(41,notification(detail));
   messageNotifications.update(state);
   JSONObject health=new JSONObject().put("timestamp",System.currentTimeMillis()/1000.0).put("uptimeMs",SystemClock.elapsedRealtime()).put("tcpOnline",state.optBoolean("tcpOnline")).put("rnodeOnline",radioOnline).put("meshcoreConnected",mesh!=null&&mesh.optBoolean("connected")).put("voiceReady",state.optJSONObject("voice")!=null&&state.getJSONObject("voice").optBoolean("ready")).put("locationSharing",location!=null&&location.optBoolean("active"));
   boolean callsDeferred=getSharedPreferences("boot_recovery",0).getBoolean("defer_calls",false);
   boolean sipEnabled=getSharedPreferences("sip_accounts",0).getBoolean("enabled",false);
   if(sipEnabled&&!callsDeferred){try{JSONObject sipState=new JSONObject(com.meshchatnext.sip.SipController.get(this).status());health.put("sipRegistered",sipState.optBoolean("registered")).put("sipCallState",sipState.optString("call_state","idle"));}catch(Exception ignored){health.put("sipRegistered",false);}}
   health.put("callsDeferred",callsDeferred).put("voiceCallState",state.optJSONObject("voice")==null?"idle":state.getJSONObject("voice").optString("call_state","idle"));
   android.util.AtomicFile healthFile=new android.util.AtomicFile(new java.io.File(getFilesDir(),"runtime-health.json"));java.io.FileOutputStream stream=null;try{stream=healthFile.startWrite();stream.write(health.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));healthFile.finishWrite(stream);}catch(Exception e){if(stream!=null)healthFile.failWrite(stream);}

  }catch(Exception ignored){}},0,10,TimeUnit.SECONDS);
 }
 private void showForeground(boolean location){int type=Build.VERSION.SDK_INT>=34?android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING:0;if(location&&Build.VERSION.SDK_INT>=29)type|=android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION;if(Build.VERSION.SDK_INT>=29)startForeground(41,notification(location?"Location sharing active":"Reticulum messaging"),type);else startForeground(41,notification("Reticulum messaging"));}
 private void setLocation(boolean active){try{if(!Python.isStarted())return;PyObject backend=Python.getInstance().getModule("family_backend");JSONObject state=new JSONObject(backend.callAttr("request","{\"action\":\"status\"}").toString());active=active&&state.getJSONObject("location").optBoolean("active");if(locationRuntime==null)locationRuntime=new FamilyLocationRuntime(this,backend);if(active){showForeground(true);locationForeground=true;locationRuntime.start();}else{locationRuntime.stop();locationForeground=false;showForeground(false);}}catch(Exception e){locationForeground=false;Python.getInstance().getModule("family_backend").callAttr("location_error","Location access unavailable. Open guardian map settings to enable it.");}}
 @Override public int onStartCommand(Intent intent,int flags,int id){if(intent!=null&&intent.hasExtra("locationSharing"))setLocation(intent.getBooleanExtra("locationSharing",false));return START_STICKY;}
 @Override public IBinder onBind(Intent intent){return null;}
 @Override public void onDestroy(){if(locationRuntime!=null)locationRuntime.stop();worker.shutdownNow();stopForeground(STOP_FOREGROUND_REMOVE);AppBackgroundNotification.sync(this);super.onDestroy();}
}
