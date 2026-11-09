package com.meshchatnext.sip;
import android.content.Context;
import org.json.*;
import java.nio.file.*;
import java.util.regex.*;
/** Read the atomically saved guardian allowlist at each call boundary. */
public final class FamilySipContacts {
 public static String canonical(String raw){
  if(raw==null||raw.indexOf('\r')>=0||raw.indexOf('\n')>=0||raw.length()>512)return null;
  String value=raw.trim();int start=value.indexOf('<');if(start>=0){int end=value.indexOf('>',start);if(end<0||value.indexOf('<',start+1)>=0)return null;value=value.substring(start+1,end);}
  if(value.toLowerCase(java.util.Locale.ROOT).endsWith(";transport=udp"))value=value.substring(0,value.length()-14);
  Matcher match=Pattern.compile("(?i)^sip:([a-z0-9_.+*%~-]{1,64})@([a-z0-9.-]{1,253})(?::([0-9]{1,5}))?$").matcher(value);
  if(!match.matches())return null;int port=match.group(3)==null?5060:Integer.parseInt(match.group(3));if(port<1||port>65535)return null;
  return "sip:"+match.group(1)+"@"+match.group(2).toLowerCase(java.util.Locale.ROOT)+":"+port;
 }
 /** Provider identity mapping is inbound-only; dial approval remains an exact URI match. */
 public static boolean providerMatch(String approved,String incoming,String provider,int providerPort,java.util.Set<String> currentAddresses){
  String a=canonical(approved),b=canonical(incoming);if(a==null||b==null||provider==null||currentAddresses==null)return false;
  String[] left=parts(a),right=parts(b);String host=provider.toLowerCase(java.util.Locale.ROOT);
  if(!left[0].equals(right[0])||!left[1].equals(host)||Integer.parseInt(left[2])!=providerPort)return false;
  int port=Integer.parseInt(right[2]);if(port!=5060&&port!=providerPort)return false;
  return right[1].equals(host)||currentAddresses.contains(right[1]);
 }
 private static String[] parts(String uri){int at=uri.indexOf('@'),colon=uri.lastIndexOf(':');return new String[]{uri.substring(4,at),uri.substring(at+1,colon),uri.substring(colon+1)};}
 public static String name(Context context,String raw){return find(context,raw,null,0,java.util.Collections.emptySet());}
 public static String incomingName(Context context,String raw,String provider,int port,java.util.Set<String> currentAddresses){return find(context,raw,provider,port,currentAddresses);}
 private static String find(Context context,String raw,String provider,int port,java.util.Set<String> currentAddresses){try{
  String target=canonical(raw);if(target==null)return null;java.nio.file.Path path=new java.io.File(context.getFilesDir(),"family-live/state.json").toPath();if(Files.size(path)>32*1024*1024)return null;
  JSONArray contacts=new JSONObject(new String(Files.readAllBytes(path),java.nio.charset.StandardCharsets.UTF_8)).getJSONArray("contacts");String found=null;
  for(int i=0;i<contacts.length();i++){JSONObject contact=contacts.getJSONObject(i);String address=contact.getJSONObject("addresses").optString("sip");if(target.equals(canonical(address))||providerMatch(address,raw,provider,port,currentAddresses)){if(found!=null)return null;found=contact.getString("name");}}
  return found;
 }catch(Exception e){return null;}}
 private FamilySipContacts(){}
}
