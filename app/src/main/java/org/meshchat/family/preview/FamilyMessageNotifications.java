package org.meshchat.family.preview;
import android.app.*;
import android.content.*;
import org.json.*;
import java.util.*;
/** Approved direct and room messages; no message content on the lock screen. */
final class FamilyMessageNotifications {
 static final String CHANNEL="family_messages";
 private final Context context;
 private final String contactTag,roomTag;
 private final NotificationManager manager;
 private final android.content.SharedPreferences preferences;
 FamilyMessageNotifications(Context context){this(context,"message_notifications");}
 FamilyMessageNotifications(Context context,String preferenceName){this.context=context;String suffix="message_notifications".equals(preferenceName)?"":"_test";contactTag="contact"+suffix;roomTag="room"+suffix;manager=context.getSystemService(NotificationManager.class);preferences=context.getSharedPreferences(preferenceName,Context.MODE_PRIVATE);NotificationChannel channel=new NotificationChannel(CHANNEL,"Messages",NotificationManager.IMPORTANCE_HIGH);channel.setDescription("Messages from approved contacts and rooms");channel.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);manager.createNotificationChannel(channel);}
 void update(JSONObject state)throws JSONException{
  JSONObject messages=state.optJSONObject("messages");JSONArray contacts=state.optJSONArray("contacts");if(messages==null||contacts==null)return;
  Set<String> previous=preferences.getStringSet("seen",null),current=new HashSet<>(),approved=new HashSet<>();boolean initialized=previous!=null;
  for(int n=0;n<contacts.length();n++){
   JSONObject contact=contacts.getJSONObject(n);int id=contact.getInt("id"),unread=0;approved.add(String.valueOf(id));boolean fresh=false;JSONArray rows=messages.optJSONArray(String.valueOf(id));
   if(rows!=null)for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if(!row.optBoolean("incoming"))continue;String key=id+":"+row.getString("id");current.add(key);if(!row.optBoolean("read")){unread++;if(initialized&&!previous.contains(key))fresh=true;}}
   if(unread==0){manager.cancel(contactTag,id);continue;}
   if(!fresh)continue;
   Intent intent=new Intent(context,MainActivity.class).putExtra("contactId",id).setAction("org.meshchat.family.OPEN_CONTACT."+id).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
   PendingIntent open=PendingIntent.getActivity(context,id,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
   Notification publicVersion=new Notification.Builder(context,CHANNEL).setSmallIcon(R.drawable.ic_family).setContentTitle("neXt Family").setContentText("New message").build();
   Notification notification=new Notification.Builder(context,CHANNEL).setSmallIcon(R.drawable.ic_family).setContentTitle(contact.optString("name","Approved contact")).setContentText(unread==1?"New private message":unread+" unread messages").setContentIntent(open).setAutoCancel(true).setNumber(unread).setCategory(Notification.CATEGORY_MESSAGE).setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(publicVersion).build();
   manager.notify(contactTag,id,notification);
  }
  // Also clear alerts left by versions which did not persist approved IDs.
  for(android.service.notification.StatusBarNotification active:manager.getActiveNotifications())if(contactTag.equals(active.getTag())&&!approved.contains(String.valueOf(active.getId())))manager.cancel(contactTag,active.getId());
  for(String old:preferences.getStringSet("approved_contacts",java.util.Collections.emptySet()))if(!approved.contains(old))try{manager.cancel(contactTag,Integer.parseInt(old));}catch(NumberFormatException ignored){}
  preferences.edit().putStringSet("seen",current).putStringSet("approved_contacts",approved).apply();
  updateRooms(state);
 }
 private void updateRooms(JSONObject state)throws JSONException{
  JSONArray rooms=state.optJSONArray("rooms");JSONObject runtime=state.optJSONObject("roomRuntime");if(rooms==null||runtime==null)return;
  Set<String> previous=preferences.getStringSet("seen_rooms",null),current=new HashSet<>(),approved=new HashSet<>();String self=state.optString("rrcIdentity");
  for(int n=0;n<rooms.length();n++){
   JSONObject room=rooms.getJSONObject(n);int id=room.getInt("id");approved.add(String.valueOf(id));JSONObject status=runtime.optJSONObject(String.valueOf(id));if(status==null)continue;JSONArray rows=status.optJSONArray("messages");boolean fresh=false;
   if(rows!=null)for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);boolean incoming=row.has("incoming")?row.optBoolean("incoming"):!self.equals(row.optString("src"));if(!incoming)continue;String mid=row.optString("msg_id",row.optString("id",row.optString("mid","")));if(mid.isEmpty()&&row.has("seq"))mid="seq:"+row.optLong("seq");if(mid.isEmpty())continue;String key=id+":"+mid;current.add(key);if(previous!=null&&!previous.contains(key))fresh=true;}
   int unread=status.optInt("unread");if(unread==0){manager.cancel(roomTag,id);continue;}if(!fresh)continue;
   Intent intent=new Intent(context,MainActivity.class).putExtra("roomId",id).setAction("org.meshchat.family.OPEN_ROOM."+id).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);PendingIntent open=PendingIntent.getActivity(context,id,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
   Notification publicVersion=new Notification.Builder(context,CHANNEL).setSmallIcon(R.drawable.ic_family).setContentTitle("neXt Family").setContentText("New room message").build();
   manager.notify(roomTag,id,new Notification.Builder(context,CHANNEL).setSmallIcon(R.drawable.ic_family).setContentTitle(room.optString("name","Approved room")).setContentText(unread==1?"New room message":unread+" unread room messages").setNumber(unread).setContentIntent(open).setAutoCancel(true).setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(publicVersion).setCategory(Notification.CATEGORY_MESSAGE).build());
  }
  for(String old:preferences.getStringSet("approved_rooms",java.util.Collections.emptySet()))if(!approved.contains(old))try{manager.cancel(roomTag,Integer.parseInt(old));}catch(NumberFormatException ignored){}
  preferences.edit().putStringSet("seen_rooms",current).putStringSet("approved_rooms",approved).apply();
 }

}
