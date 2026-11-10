package org.meshchat.family.preview;
import android.content.Context;
import android.media.*;
import com.chaquo.python.PyObject;
/** PCM stays in memory and crosses the native/Python boundary only for the active call. */
final class FamilyVoiceAudio {
 private static final int PCM_CHUNK_BYTES=1920; // 20 ms of 48 kHz mono PCM16.
 private final Context context;private final PyObject backend;private volatile boolean running;private AudioRecord microphone;private AudioTrack speaker;private AudioManager manager;private AudioFocusRequest focus;private android.media.audiofx.AcousticEchoCanceler echo;private TelephoneBluetoothRoute route;private String callId="";
 FamilyVoiceAudio(Context c,PyObject backend){context=c;this.backend=backend;}
 synchronized void start(String id){if(running&&callId.equals(id))return;stop();try{
  if(context.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)!=android.content.pm.PackageManager.PERMISSION_GRANTED)throw new SecurityException("Microphone permission is required");
  manager=context.getSystemService(AudioManager.class);AudioAttributes attributes=new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build();
  focus=new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE).setAudioAttributes(attributes).setOnAudioFocusChangeListener(change->{if(change==AudioManager.AUDIOFOCUS_LOSS||change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT)backend.callAttr("voice_audio_error","Audio focus lost");}).build();
  if(manager.requestAudioFocus(focus)!=AudioManager.AUDIOFOCUS_REQUEST_GRANTED)throw new IllegalStateException("Audio is busy");manager.setMode(AudioManager.MODE_IN_COMMUNICATION);route=new TelephoneBluetoothRoute(manager);route.start();
  AudioFormat input=new AudioFormat.Builder().setSampleRate(48000).setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_IN_MONO).build(),output=new AudioFormat.Builder().setSampleRate(48000).setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build();
  microphone=new AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.VOICE_COMMUNICATION).setAudioFormat(input).setBufferSizeInBytes(Math.max(23040,AudioRecord.getMinBufferSize(48000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)*2)).build();
  speaker=new AudioTrack.Builder().setAudioAttributes(attributes).setAudioFormat(output).setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(Math.max(PCM_CHUNK_BYTES*3,AudioTrack.getMinBufferSize(48000,AudioFormat.CHANNEL_OUT_MONO,AudioFormat.ENCODING_PCM_16BIT))).build();
  if(microphone.getState()!=AudioRecord.STATE_INITIALIZED||speaker.getState()!=AudioTrack.STATE_INITIALIZED)throw new IllegalStateException("Audio unavailable");
  if(android.media.audiofx.AcousticEchoCanceler.isAvailable()){echo=android.media.audiofx.AcousticEchoCanceler.create(microphone.getAudioSessionId());if(echo!=null)echo.setEnabled(true);}
  speaker.setVolume(AudioTrack.getMaxVolume());
  callId=id;running=true;microphone.startRecording();final AudioRecord capture=microphone;final AudioTrack playback=speaker;
  new Thread(()->{
   try{
    android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_AUDIO);
    byte[] frame=new byte[PCM_CHUNK_BYTES];
    while(isCurrent(id)){
     int count=capture.read(frame,0,frame.length,AudioRecord.READ_BLOCKING);
     if(count<0)throw new IllegalStateException("Microphone read failed");
     if(count>0)backend.callAttr("voice_push",id,count==frame.length?frame:java.util.Arrays.copyOf(frame,count));
    }
   }catch(Exception e){if(isCurrent(id))backend.callAttr("voice_audio_error","Microphone unavailable");}
  },"Family-LXST-capture").start();
  new Thread(()->{
   try{
    android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_AUDIO);
    byte[] silence=new byte[PCM_CHUNK_BYTES];
    if(!isCurrent(id))return;
    // Prime the device buffer before starting its clock.
    int primed=playback.write(silence,0,silence.length,AudioTrack.WRITE_NON_BLOCKING);
    if(primed<0)throw new IllegalStateException("Playback could not be primed");
    playback.play();
    while(isCurrent(id)){
     byte[] frame=backend.callAttr("voice_pull",id).toJava(byte[].class);
     if(frame.length==0)frame=silence;
     for(int offset=0;offset<frame.length&&isCurrent(id);){
      int written=playback.write(frame,offset,frame.length-offset,AudioTrack.WRITE_BLOCKING);
      if(written<0)throw new IllegalStateException("Playback write failed");
      if(written==0){Thread.sleep(2);continue;}
      offset+=written;
     }
    }
   }catch(Exception e){if(isCurrent(id))backend.callAttr("voice_audio_error","Playback unavailable");}
  },"Family-LXST-playback").start();
 }catch(Exception e){stop();backend.callAttr("voice_audio_error","Native audio could not start");}}
 synchronized boolean setSpeaker(String id,boolean enabled){return isCurrent(id)&&route!=null&&route.setSpeaker(enabled);}
 synchronized boolean isSpeakerOn(){return running&&route!=null&&route.isSpeakerOn();}
 private boolean isCurrent(String id){return running&&id.equals(callId);}
 synchronized void stop(){running=false;callId="";if(route!=null){route.stop();route=null;}try{if(microphone!=null){microphone.stop();microphone.release();}}catch(Exception ignored){}microphone=null;try{if(speaker!=null){speaker.stop();speaker.release();}}catch(Exception ignored){}speaker=null;if(echo!=null){echo.release();echo=null;}if(manager!=null){if(focus!=null)manager.abandonAudioFocusRequest(focus);manager.setMode(AudioManager.MODE_NORMAL);}focus=null;manager=null;}
}
