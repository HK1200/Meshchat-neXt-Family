package org.meshchat.family.preview;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
import com.chaquo.python.*;
import org.json.*;
import java.util.concurrent.*;
/** Native LXST incoming-call notification and active-call audio lifecycle. */
public final class FamilyVoiceService extends Service {
 private static volatile FamilyVoiceService instance;
 private final ScheduledExecutorService worker=Executors.newSingleThreadScheduledExecutor();private PyObject backend;private FamilyVoiceAudio audio;private String last="";
 public static void releaseAudio(){FamilyVoiceService current=instance;if(current!=null&&current.audio!=null)current.audio.stop();}
 private PendingIntent open(){return PendingIntent.getActivity(this,6510,new Intent(this,MainActivity.class).putExtra("openReticulumCall",true).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
 private PendingIntent action(String action,String id){return PendingIntent.getService(this,action.equals("voice_answer")?6511:6512,new Intent(this,FamilyVoiceService.class).setAction(action).setData(android.net.Uri.parse("family-reticulum-call:"+id+"/"+action)).putExtra("callId",id),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
 private void foreground(JSONObject state)throws JSONException{
  String phase=state.optString("call_state","idle");boolean incoming=phase.equals("incoming"),connected=phase.equals("connected");String id=state.optString("call_id");
  Notification.Builder builder=new Notification.Builder(this,incoming?"family_reticulum_calls":"family_reticulum_voice").setSmallIcon(R.drawable.ic_family).setContentTitle(incoming?"Incoming Reticulum call":"neXt Family · Reticulum calls").setContentText(incoming?state.optString("caller_name"):phase.equals("idle")?"Ready for approved calls":phase).setContentIntent(open()).setOngoing(true).setVisibility(Notification.VISIBILITY_PRIVATE);
  if(phase.equals("idle"))AppBackgroundNotification.group(builder);
  if(incoming){PendingIntent answer=action("voice_answer",id),decline=action("voice_hangup",id);builder.setCategory(Notification.CATEGORY_CALL);if(Build.VERSION.SDK_INT>=31)builder.setStyle(Notification.CallStyle.forIncomingCall(new Person.Builder().setName(state.optString("caller_name","Approved contact")).setImportant(true).build(),decline,answer));else builder.addAction(new Notification.Action.Builder(null,"Decline",decline).build()).addAction(new Notification.Action.Builder(null,"Answer",answer).build());}
  int type=Build.VERSION.SDK_INT>=29?ServiceInfo.FOREGROUND_SERVICE_TYPE_PHONE_CALL:0;if(connected&&Build.VERSION.SDK_INT>=30)type|=ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE;
  if(Build.VERSION.SDK_INT>=29)startForeground(6510,builder.build(),type);else startForeground(6510,builder.build());
  AppBackgroundNotification.sync(this);
 }
 @Override public void onCreate(){super.onCreate();instance=this;NotificationManager manager=getSystemService(NotificationManager.class);manager.createNotificationChannel(new NotificationChannel("family_reticulum_voice","Reticulum calling connection",NotificationManager.IMPORTANCE_LOW));NotificationChannel incoming=new NotificationChannel("family_reticulum_calls","Reticulum incoming calls",NotificationManager.IMPORTANCE_HIGH);incoming.setSound(android.media.RingtoneManager.getDefaultUri(android.media.RingtoneManager.TYPE_RINGTONE),new android.media.AudioAttributes.Builder().setUsage(android.media.AudioAttributes.USAGE_NOTIFICATION_RINGTONE).build());manager.createNotificationChannel(incoming);
  try{foreground(new JSONObject());}catch(Exception ignored){}
  worker.scheduleWithFixedDelay(()->{try{initializeRuntime();JSONObject state=new JSONObject(backend.callAttr("voice_state").toString());if(!state.optBoolean("enabled")){audio.stop();stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();return;}String fingerprint=state.optString("call_state")+state.optString("call_id")+state.optString("caller_name");if(!fingerprint.equals(last)){foreground(state);last=fingerprint;}if(state.optString("call_state").equals("connected"))audio.start(state.getString("call_id"));else audio.stop();}catch(Exception e){if(audio!=null)audio.stop();if(backend!=null)backend.callAttr("voice_audio_error","Calling audio service unavailable");}},0,500,TimeUnit.MILLISECONDS);
 }
 private void initializeRuntime(){if(backend==null){backend=FamilyRuntime.backend(this);audio=new FamilyVoiceAudio(this,backend);}}
 @Override public int onStartCommand(Intent intent,int flags,int id){if(intent!=null&&("voice_answer".equals(intent.getAction())||"voice_hangup".equals(intent.getAction())))worker.execute(()->{try{initializeRuntime();backend.callAttr("request",new JSONObject().put("action",intent.getAction()).put("payload",new JSONObject().put("callId",intent.getStringExtra("callId"))).toString());}catch(Exception ignored){}});return START_STICKY;}
 @Override public IBinder onBind(Intent intent){return null;}
 @Override public void onDestroy(){worker.shutdownNow();if(audio!=null)audio.stop();FamilyCallGate.release("reticulum");instance=null;stopForeground(STOP_FOREGROUND_REMOVE);AppBackgroundNotification.sync(this);super.onDestroy();}
}
