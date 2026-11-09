package org.meshchat.family.preview;
import android.content.Context;
import java.io.*;
import java.nio.channels.*;
/** OS-released exclusive call ownership across the main and SIP processes. */
public final class FamilyCallGate {
 private static FileChannel channel;private static FileLock lock;private static String owner="";
 public static synchronized boolean acquire(Context context,String service){
  if(lock!=null&&lock.isValid())return owner.equals(service);
  try{channel=new RandomAccessFile(new File(context.getFilesDir(),"active-call.lock"),"rw").getChannel();lock=channel.tryLock();if(lock==null){channel.close();channel=null;return false;}owner=service;return true;}catch(Exception e){try{if(channel!=null)channel.close();}catch(Exception ignored){}channel=null;lock=null;return false;}
 }
 public static synchronized void release(String service){if(!owner.equals(service))return;if(service.equals("reticulum"))FamilyVoiceService.releaseAudio();try{if(lock!=null)lock.release();}catch(Exception ignored){}try{if(channel!=null)channel.close();}catch(Exception ignored){}lock=null;channel=null;owner="";}
 private FamilyCallGate(){}
}
