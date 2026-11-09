package org.meshchat.family.preview;
import android.content.Context;
import android.media.*;
import com.chaquo.python.PyObject;
/** PCM stays in memory and crosses the native/Python boundary only for the active call. */
final class FamilyVoiceAudio {
 private final Context context;private final PyObject backend;private volatile boolean running;private AudioRecord microphone;private AudioTrack speaker;private AudioManager manager;private AudioFocusRequest focus;private android.media.audiofx.AcousticEchoCanceler echo;private String callId="";
 FamilyVoiceAudio(Context c,PyObject backend){context=c;this.backend=backend;}
 synchronized void start(String id){if(running&&callId.equals(id))return;stop();try{
  if(context.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)!=android.content.pm.PackageManager.PERMISSION_GRANTED)throw new SecurityException("Microphone permission is required");
  manager=context.getSystemService(AudioManager.class);AudioAttributes attributes=new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build();
  focus=new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE).setAudioAttributes(attributes).setOnAudioFocusChangeListener(change->{if(change==AudioManager.AUDIOFOCUS_LOSS||change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT)backend.callAttr("voice_audio_error","Audio focus lost");}).build();
  if(manager.requestAudioFocus(focus)!=AudioManager.AUDIOFOCUS_REQUEST_GRANTED)throw new IllegalStateException("Audio is busy");manager.setMode(AudioManager.MODE_IN_COMMUNICATION);
  AudioFormat input=new AudioFormat.Builder().setSampleRate(48000).setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_IN_MONO).build(),output=new AudioFormat.Builder().setSampleRate(48000).setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build();
  microphone=new AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.VOICE_COMMUNICATION).setAudioFormat(input).setBufferSizeInBytes(Math.max(23040,AudioRecord.getMinBufferSize(48000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)*2)).build();
  speaker=new AudioTrack.Builder().setAudioAttributes(attributes).setAudioFormat(output).setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(Math.max(23040,AudioTrack.getMinBufferSize(48000,AudioFormat.CHANNEL_OUT_MONO,AudioFormat.ENCODING_PCM_16BIT)*2)).build();
  if(microphone.getState()!=AudioRecord.STATE_INITIALIZED||speaker.getState()!=AudioTrack.STATE_INITIALIZED)throw new IllegalStateException("Audio unavailable");
  if(android.media.audiofx.AcousticEchoCanceler.isAvailable()){echo=android.media.audiofx.AcousticEchoCanceler.create(microphone.getAudioSessionId());if(echo!=null)echo.setEnabled(true);}
  callId=id;running=true;microphone.startRecording();speaker.play();final AudioRecord capture=microphone;final AudioTrack playback=speaker;
  new Thread(()->{byte[] frame=new byte[5760];try{while(running&&id.equals(callId)){int count=capture.read(frame,0,frame.length);if(count<0)throw new IllegalStateException("Microphone read failed");if(count>0)backend.callAttr("voice_push",id,java.util.Arrays.copyOf(frame,count));}}catch(Exception e){if(running&&id.equals(callId))backend.callAttr("voice_audio_error","Microphone unavailable");}},"Family-LXST-capture").start();
  new Thread(()->{try{while(running&&id.equals(callId)){byte[] frame=backend.callAttr("voice_pull",id).toJava(byte[].class);if(frame.length>0)playback.write(frame,0,frame.length);else Thread.sleep(10);}}catch(Exception e){if(running&&id.equals(callId))backend.callAttr("voice_audio_error","Playback unavailable");}},"Family-LXST-playback").start();
 }catch(Exception e){stop();backend.callAttr("voice_audio_error","Native audio could not start");}}
 synchronized void stop(){running=false;callId="";try{if(microphone!=null){microphone.stop();microphone.release();}}catch(Exception ignored){}microphone=null;try{if(speaker!=null){speaker.stop();speaker.release();}}catch(Exception ignored){}speaker=null;if(echo!=null){echo.release();echo=null;}if(manager!=null){if(focus!=null)manager.abandonAudioFocusRequest(focus);manager.setMode(AudioManager.MODE_NORMAL);}focus=null;manager=null;}
}
