package org.meshchat.family.preview;

import android.app.Activity;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.*;
import android.view.View;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.*;

/** Native companion host with guardian-controlled radio configuration. */
public class MainActivity extends Activity {
    private static final String HOST = "appassets.androidplatform.net";
    private static final int PICK_FILE = 10;
    private static final int MAP_PICK_FILE = 15;
    private static final int MAP_LOCATION_PERMISSION = 17;
    private WebView web;
    private PyObject runtime;
    private FamilyMapDownload mapDownload;
    private volatile String mapImportToken;
    private boolean guardianPaused;
    private PermissionRequest cameraRequest;
    private volatile String cameraToken="";
    private volatile boolean ownedPermission;
    private boolean ownedDocument;
    private volatile String mapImportStatus="{\"busy\":false}";
    private final java.util.concurrent.ExecutorService lifecycle=java.util.concurrent.Executors.newSingleThreadExecutor();
    private volatile ValueCallback<Uri[]> fileCallback;
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);if(intent.getBooleanExtra("openReticulumCall",false)&&web!=null)web.evaluateJavascript("window.familyOpenReticulumCall?.()",null);if(intent.getBooleanExtra("openCall",false)&&web!=null)web.evaluateJavascript("window.familyOpenCall?.()",null);int room=intent.getIntExtra("roomId",0);if(web!=null&&room>0)web.evaluateJavascript("window.familyOpenRoom?.("+room+")",null);int contact=intent.getIntExtra("contactId",0);if(web!=null&&contact>0)web.evaluateJavascript("window.familyOpenContact?.("+contact+")",null);}
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        FamilyRuntime.allowCalls(this);
        getSystemService(android.app.NotificationManager.class).cancel(FamilyBootReceiver.NOTICE);
        getWindow().setStatusBarColor(Color.rgb(25,37,32));
        getWindow().setNavigationBarColor(Color.rgb(25,37,32));
        getWindow().getDecorView().setSystemUiVisibility(0);
        PyObject backend=FamilyRuntime.backend(this);
        runtime=backend;
        mapDownload=new FamilyMapDownload(this,backend);
        // Service startup must use initialized persisted settings, including on
        // a cold launch where no Python backend state existed beforehand.
        org.json.JSONObject startupState=null;boolean setupComplete=false;try{startupState=new org.json.JSONObject(backend.callAttr("request","{\"action\":\"status\"}").toString());setupComplete=startupState.optBoolean("setupComplete");}catch(Exception e){android.util.Log.e("FamilyStartup","Could not read initialized startup settings",e);}
        if(setupComplete)com.meshchatnext.sip.SipController.get(this);
        web = new WebView(this);
        web.addJavascriptInterface(new NativeBridge(this,backend), "FamilyNative");
        setContentView(web);
        // Fit content inside system bars on Android 15+.
        web.setOnApplyWindowInsetsListener((v,insets)->{
            v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });
        WebSettings settings=web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setGeolocationEnabled(false);
        settings.setSupportMultipleWindows(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                // Keep this preview offline and inside its own asset origin.
                return !isLocal(request.getUrl());
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri=request.getUrl();
                if(!isLocal(uri))return denied();
                String path=uri.getPath().substring(1);
                if(path.isEmpty())path="index.html";
                if(path.contains("..")||path.contains("\\"))return denied();
                if(path.startsWith("offline-tiles/")){try{String[] parts=path.split("/");if(parts.length!=5)return denied();PyObject tile=backend.callAttr("map_tile",parts[1],Integer.parseInt(parts[2]),Integer.parseInt(parts[3]),Integer.parseInt(parts[4]));if(tile==null)return denied();return new WebResourceResponse(tile.callAttr("__getitem__","mime").toString(),null,new ByteArrayInputStream(tile.callAttr("__getitem__","bytes").toJava(byte[].class)));}catch(Exception e){return denied();}}
                String mime=path.endsWith(".html")?"text/html":path.endsWith(".png")?"image/png":path.endsWith(".json")?"application/json":path.endsWith(".js")?"application/javascript":"application/octet-stream";
                try {
                    Map<String,String> headers=new HashMap<>();
                    headers.put("Content-Security-Policy","default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; media-src blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'");
                    headers.put("X-Content-Type-Options","nosniff");
                    return new WebResourceResponse(mime,"UTF-8",200,"OK",headers,getAssets().open(path));
                } catch(IOException e) {return denied();}
            }
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if(fileCallback!=null)fileCallback.onReceiveValue(null);
                fileCallback=callback;
                Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                String[] accepted=params.getAcceptTypes();
                boolean image=accepted!=null&&accepted.length>0&&accepted[0].startsWith("image/");
                intent.setType(image?"image/*":"*/*");
                try {startActivityForResult(intent,PICK_FILE);} catch(android.content.ActivityNotFoundException e){fileCallback.onReceiveValue(null);fileCallback=null;}
                return true;
            }
            @Override public void onPermissionRequest(PermissionRequest request){runOnUiThread(()->{
                if(!isLocal(request.getOrigin())||!cameraAllowed()||!java.util.Arrays.equals(request.getResources(),new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE})){request.deny();return;}
                if(checkSelfPermission(android.Manifest.permission.CAMERA)==android.content.pm.PackageManager.PERMISSION_GRANTED)request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
                else{if(cameraRequest!=null)cameraRequest.deny();cameraRequest=request;ownedPermission=true;requestPermissions(new String[]{android.Manifest.permission.CAMERA},13);}
            });}
            @Override public void onPermissionRequestCanceled(PermissionRequest request){if(cameraRequest==request)cameraRequest=null;}
        });
        web.loadUrl("https://"+HOST+"/index.html");
        if(setupComplete&&startupState!=null&&startupState.optBoolean("messagingEnabled"))startForegroundService(new Intent(this, FamilyService.class));
        try{if(new org.json.JSONObject(backend.callAttr("voice_state").toString()).optBoolean("enabled"))startForegroundService(new Intent(this,FamilyVoiceService.class));}catch(Exception ignored){}
        try{boolean active=new org.json.JSONObject(backend.callAttr("request","{\"action\":\"status\"}").toString()).getJSONObject("location").optBoolean("active");if(active)startForegroundService(new Intent(this,FamilyService.class).putExtra("locationSharing",true));}catch(Exception ignored){}
    }
    private boolean cameraAllowed(){try{return new org.json.JSONObject(runtime.callAttr("request",new org.json.JSONObject().put("action","authorize_camera").put("payload",new org.json.JSONObject().put("token",cameraToken)).toString()).toString()).optBoolean("ok");}catch(Exception e){return false;}}
    public static class NativeBridge {
        private final PyObject backend;
        private final MainActivity activity;
        NativeBridge(MainActivity owner,PyObject module){activity=owner;backend=module;}
        @JavascriptInterface public void importMap(String token) {
            try {
                org.json.JSONObject command = new org.json.JSONObject().put("action","authorize_map_import")
                        .put("payload",new org.json.JSONObject().put("token",token));
                if (!new org.json.JSONObject(backend.callAttr("request",command.toString()).toString()).optBoolean("ok")) return;
                activity.runOnUiThread(() -> activity.openMapPicker(token));
            } catch (Exception ignored) {}
        }
        @JavascriptInterface public void downloadMap(boolean useLocation) {
            activity.runOnUiThread(() -> activity.startMapDownload(useLocation));
        }
        @JavascriptInterface public String mapDownloadStatus() { return activity.mapDownload.status(); }
        @JavascriptInterface public String mapImportStatus(){return activity.mapImportStatus;}
        @JavascriptInterface public boolean guardianDialogOpen(){return activity.mapImportToken!=null||activity.ownedPermission||activity.fileCallback!=null;}
        @JavascriptInterface public String tileSource(int z,int x,int y){try{return backend.callAttr("map_source",z,x,y).toString();}catch(Exception e){return "";}}
        @JavascriptInterface public boolean locationPermissionGranted(){return activity.checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION)==android.content.pm.PackageManager.PERMISSION_GRANTED;}
        @JavascriptInterface public void requestLocation(String token){try{org.json.JSONObject payload=new org.json.JSONObject().put("token",token);boolean allowed=new org.json.JSONObject(backend.callAttr("request",new org.json.JSONObject().put("action","authorize_location").put("payload",payload).toString()).toString()).optBoolean("ok");if(allowed)activity.runOnUiThread(()->{activity.ownedPermission=true;activity.requestPermissions(new String[]{android.Manifest.permission.ACCESS_FINE_LOCATION,android.Manifest.permission.ACCESS_COARSE_LOCATION},14);});}catch(Exception ignored){}}
        @JavascriptInterface public boolean authorizeCamera(String token){activity.cameraToken=token;return activity.cameraAllowed();}
        @JavascriptInterface public void requestBluetooth(){activity.runOnUiThread(()->{activity.ownedPermission=true;activity.requestPermissions(android.os.Build.VERSION.SDK_INT>=31?new String[]{android.Manifest.permission.BLUETOOTH_SCAN,android.Manifest.permission.BLUETOOTH_CONNECT}:new String[]{android.Manifest.permission.ACCESS_FINE_LOCATION},12);});}
        @JavascriptInterface public boolean microphoneGranted(){return activity.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)==android.content.pm.PackageManager.PERMISSION_GRANTED;}
        @JavascriptInterface public void requestMicrophone(){activity.runOnUiThread(()->{activity.ownedPermission=true;activity.requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO},16);});}
        @JavascriptInterface public boolean notificationReticulumCall(){return activity.getIntent().getBooleanExtra("openReticulumCall",false);}
        @JavascriptInterface public boolean notificationCall(){return activity.getIntent().getBooleanExtra("openCall",false);}
        @JavascriptInterface public int notificationRoom(){return activity.getIntent().getIntExtra("roomId",0);}
        @JavascriptInterface public int notificationContact(){return activity.getIntent().getIntExtra("contactId",0);}
        @JavascriptInterface public boolean notificationsEnabled(){return android.os.Build.VERSION.SDK_INT<33||activity.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)==android.content.pm.PackageManager.PERMISSION_GRANTED;}
        @JavascriptInterface public void requestNotifications(){activity.runOnUiThread(()->{if(android.os.Build.VERSION.SDK_INT>=33)activity.requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS},11);});}
        @JavascriptInterface public String request(String request){
            try{org.json.JSONObject input=new org.json.JSONObject(request);String action=input.optString("action");
            if ("apk_share".equals(action)) {
                org.json.JSONObject auth = new org.json.JSONObject(input.toString());
                auth.put("action", "authorize_apk_share");
                String response = backend.callAttr("request", auth.toString()).toString();
                if (!new org.json.JSONObject(response).optBoolean("ok")) return response;
                final Intent chooser;
                try {
                    chooser = FamilyApkShare.chooser(activity);
                } catch (java.io.FileNotFoundException unavailable) {
                    return new org.json.JSONObject().put("ok", false)
                            .put("error", "Family could not share this installation. Use the standalone APK from GitHub Releases.")
                            .toString();
                }
                activity.runOnUiThread(() -> activity.startActivity(chooser));
                return response;
            }
            if ("update_install".equals(action)) {
                Intent installer = FamilyUpdates.get(activity).installerIntent(activity);
                if (installer == null) {
                    return new org.json.JSONObject().put("ok", false).put("error", "No Family update is available.").toString();
                }
                activity.runOnUiThread(() -> activity.startActivity(installer));
                return new org.json.JSONObject().put("ok", true).toString();
            }
            if ("update_config".equals(action) || "update_check".equals(action)) {
                org.json.JSONObject payload = input.getJSONObject("payload");
                String check = new org.json.JSONObject().put("action", "authorize_update_config")
                        .put("payload", new org.json.JSONObject().put("token", payload.optString("token"))).toString();
                org.json.JSONObject auth = new org.json.JSONObject(backend.callAttr("request", check).toString());
                if (!auth.optBoolean("ok")) return auth.toString();
                FamilyUpdates updates = FamilyUpdates.get(activity);
                if ("update_check".equals(action)) updates.check(true);
                return new org.json.JSONObject().put("ok", true).put("repository", updates.repository())
                        .put("updates", updates.status()).toString();
            }
            if("call_auto".equals(action)){
                int id=input.getJSONObject("payload").getInt("contactId");
                backend.callAttr("set_network_context",FamilyRuntime.networkContext(activity));
                String sipState=com.meshchatnext.sip.SipController.get(activity).status();
                org.json.JSONArray choices=new org.json.JSONObject(backend.callAttr("call_routes",sipState).toString()).optJSONArray(String.valueOf(id));
                if(choices==null)return "{\"ok\":false,\"error\":\"Call contact is not approved\"}";
                String method="";for(int i=0;i<choices.length();i++)if(choices.getJSONObject(i).optBoolean("automatic")){method=choices.getJSONObject(i).getString("service");break;}
                if(method.isEmpty())return "{\"ok\":false,\"error\":\"No suitable calling connection is available\"}";
                String target=backend.callAttr("approved_call_target",id,method).toString();
                String response=method.equals("sip")?com.meshchatnext.sip.SipController.get(activity).send(new org.json.JSONObject().put("op","call").put("target",target).toString()):backend.callAttr("request",new org.json.JSONObject().put("action","voice_call").put("payload",new org.json.JSONObject().put("contactId",id).put("automatic",true)).toString()).toString();
                org.json.JSONObject result=new org.json.JSONObject(response);result.put("selectedMethod",method);return result.toString();
            }
            if("sip_diagnostics".equals(action)){
                org.json.JSONObject authorization=new org.json.JSONObject(backend.callAttr("request",new org.json.JSONObject().put("action","authorize_camera").put("payload",new org.json.JSONObject().put("token",input.getJSONObject("payload").optString("token"))).toString()).toString());
                if(!authorization.optBoolean("ok"))return authorization.toString();
                return new org.json.JSONObject().put("ok",true).put("sip",new org.json.JSONObject(com.meshchatnext.sip.SipController.get(activity).status())).toString();
            }
            if("sip".equals(action)){
                org.json.JSONObject payload=input.optJSONObject("payload"),command=payload.getJSONObject("command");String op=command.optString("op");
                if(java.util.Arrays.asList("save","remove","connect","disconnect").contains(op)){
                    org.json.JSONObject authorization=new org.json.JSONObject(backend.callAttr("request",new org.json.JSONObject().put("action","authorize_camera").put("payload",new org.json.JSONObject().put("token",payload.optString("token"))).toString()).toString());
                    if(!authorization.optBoolean("ok"))return authorization.toString();
                }else if(!java.util.Arrays.asList("call","answer","hangup","mute","speaker","status").contains(op))return "{\"ok\":false,\"error\":\"Unsupported calling action\"}";
                return com.meshchatnext.sip.SipController.get(activity).send(command.toString());
            }
            String result=backend.callAttr("request",request).toString();
            if("setup".equals(action)&&new org.json.JSONObject(result).optBoolean("ok")){boolean messaging=new org.json.JSONObject(result).optBoolean("messagingEnabled");activity.runOnUiThread(()->{com.meshchatnext.sip.SipController.get(activity);if(messaging)activity.startForegroundService(new Intent(activity,FamilyService.class));});}
            if(java.util.Arrays.asList("peer","rnode","meshcore_config").contains(action)&&new org.json.JSONObject(result).optBoolean("ok")){org.json.JSONObject snapshot=new org.json.JSONObject(result);boolean messaging=snapshot.optBoolean("messagingEnabled")||(snapshot.optJSONObject("location")!=null&&snapshot.getJSONObject("location").optBoolean("active"));activity.runOnUiThread(()->{if(messaging)activity.startForegroundService(new Intent(activity,FamilyService.class));else activity.stopService(new Intent(activity,FamilyService.class));});}
            if("contacts".equals(action)&&new org.json.JSONObject(result).optBoolean("ok"))com.meshchatnext.sip.SipController.get(activity).send("{\"op\":\"reconcile_contacts\"}");
            if("status".equals(action)){org.json.JSONObject state=new org.json.JSONObject(result);org.json.JSONObject sip=state.optBoolean("setupComplete")?new org.json.JSONObject(com.meshchatnext.sip.SipController.get(activity).status()):new org.json.JSONObject("{\"enabled\":false,\"registered\":false,\"call_state\":\"idle\",\"accounts\":[]}");sip.remove("_blocked_peer");sip.remove("_blocked_at");backend.callAttr("set_network_context",FamilyRuntime.networkContext(activity));org.json.JSONObject ranked=new org.json.JSONObject(backend.callAttr("call_routes",sip.toString()).toString());sip.remove("route_quality");state.put("sip",sip);state.put("callRoutes",ranked);state.put("updates",FamilyUpdates.get(activity).status());result=state.toString();}
            if(action.startsWith("location_")&&new org.json.JSONObject(result).optBoolean("ok")){boolean active=new org.json.JSONObject(result).getJSONObject("location").optBoolean("active");activity.runOnUiThread(()->activity.startForegroundService(new Intent(activity,FamilyService.class).putExtra("locationSharing",active)));}if(action.startsWith("voice_")&&new org.json.JSONObject(result).optBoolean("ok")&&new org.json.JSONObject(result).has("voice")&&new org.json.JSONObject(result).getJSONObject("voice").optBoolean("enabled"))activity.runOnUiThread(()->activity.startForegroundService(new Intent(activity,FamilyVoiceService.class)));return result;}
            catch(Exception e){return "{\"ok\":false,\"error\":\"Backend unavailable; check app diagnostics\"}";}
        }
    }
    @Override protected void onPause(){
        super.onPause();
        if (!ownedPermission && mapDownload != null) mapDownload.cancelLocation();
        final boolean lockGuardian=fileCallback==null&&!ownedPermission&&!ownedDocument;
        guardianPaused=guardianPaused||lockGuardian;
        if(runtime!=null)lifecycle.execute(()->{try{runtime.callAttr("background",lockGuardian);}catch(Exception ignored){}});
        if(lockGuardian&&web!=null)web.evaluateJavascript("window.dispatchEvent(new Event('family-native-background'))",null);
    }
    @Override protected void onResume(){
        super.onResume();
        FamilyUpdates.get(this).check(false);
        final boolean relock=guardianPaused;guardianPaused=false;
        lifecycle.execute(()->runOnUiThread(()->{
            if(web!=null){
                if(relock)web.evaluateJavascript("window.dispatchEvent(new Event('family-native-background'))",null);
                web.evaluateJavascript("window.dispatchEvent(new Event('family-native-resume'))",null);
            }
        }));
    }
    private boolean isLocal(Uri uri){return "https".equals(uri.getScheme())&&HOST.equals(uri.getHost());}
    private WebResourceResponse denied(){return new WebResourceResponse("text/plain","UTF-8",404,"Not Found",Collections.emptyMap(),new ByteArrayInputStream(new byte[0]));}
    private void startMapDownload(boolean useLocation) {
        if (useLocation && checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            if (ownedPermission) return;
            ownedPermission = true;
            requestPermissions(new String[]{android.Manifest.permission.ACCESS_FINE_LOCATION,
                    android.Manifest.permission.ACCESS_COARSE_LOCATION}, MAP_LOCATION_PERMISSION);
        } else {
            mapDownload.start(useLocation);
        }
    }

    private void openMapPicker(String token) {
        if (ownedDocument || mapImportStatus.contains("\"busy\":true")) return;
        ownedDocument = true;
        mapImportToken = token;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);
        try {
            startActivityForResult(intent, MAP_PICK_FILE);
        } catch (Exception error) {
            ownedDocument = false;
            mapImportToken = null;
            mapImportStatus = "{\"busy\":false,\"error\":\"No file picker available\"}";
        }
    }

    private void importMapFile(Uri uri, String token) {
        mapImportStatus = "{\"busy\":true}";
        new Thread(() -> {
            java.io.File temp = null;
            try {
                String name = "Offline map";
                String[] columns = {android.provider.OpenableColumns.DISPLAY_NAME};
                try (android.database.Cursor cursor = getContentResolver().query(uri, columns, null, null, null)) {
                    if (cursor != null && cursor.moveToFirst()) name = cursor.getString(0);
                }
                java.io.File directory = new java.io.File(getFilesDir(), "family-live/maps");
                if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Map storage is unavailable.");
                temp = new java.io.File(directory, "import-" + java.util.UUID.randomUUID() + ".tmp");
                try (java.io.InputStream input = getContentResolver().openInputStream(uri);
                        java.io.FileOutputStream output = new java.io.FileOutputStream(temp)) {
                    byte[] buffer = new byte[65_536];
                    long copied = 0;
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        copied += count;
                        if (copied > 2L * 1024 * 1024 * 1024) throw new IOException("Choose a map smaller than 2 GB.");
                        output.write(buffer, 0, count);
                    }
                }
                org.json.JSONObject result = new org.json.JSONObject(
                        runtime.callAttr("install_map", temp.getAbsolutePath(), name, token).toString());
                mapImportStatus = result.put("busy", false).toString();
            } catch (Exception error) {
                try {
                    mapImportStatus = new org.json.JSONObject().put("busy", false)
                            .put("error", error.getMessage() == null ? "Map import failed." : error.getMessage()).toString();
                } catch (Exception ignored) {}
            } finally {
                if (temp != null) temp.delete();
            }
        }, "Family-map-import").start();
    }

    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data){
        super.onActivityResult(requestCode,resultCode,data);
        if (requestCode == MAP_PICK_FILE) {
            ownedDocument = false;
            String token = mapImportToken;
            mapImportToken = null;
            if (token != null && resultCode == RESULT_OK && data != null && data.getData() != null) {
                importMapFile(data.getData(), token);
            }
        }
        if(requestCode==PICK_FILE&&fileCallback!=null){fileCallback.onReceiveValue(resultCode==RESULT_OK&&data!=null&&data.getData()!=null?new Uri[]{data.getData()}:null);fileCallback=null;}
    }
    @Override public void onRequestPermissionsResult(int requestCode,String[] permissions,int[] grantResults){
        super.onRequestPermissionsResult(requestCode,permissions,grantResults);
        if (requestCode == MAP_LOCATION_PERMISSION) {
            ownedPermission = false;
            if (checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION)
                    == android.content.pm.PackageManager.PERMISSION_GRANTED) mapDownload.start(true);
            else mapDownload.unavailable();
        }
        if(requestCode==14||requestCode==12||requestCode==16)ownedPermission=false;
        if(requestCode==13){ownedPermission=false;PermissionRequest pending=cameraRequest;cameraRequest=null;if(pending!=null){if(grantResults.length>0&&grantResults[0]==android.content.pm.PackageManager.PERMISSION_GRANTED&&cameraAllowed())pending.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});else pending.deny();}}
        if(requestCode==11&&grantResults.length>0&&grantResults[0]==android.content.pm.PackageManager.PERMISSION_GRANTED&&web!=null)web.evaluateJavascript("document.getElementById('notification-permission')?.remove();document.getElementById('home-notifications')?.remove()",null);
    }
    @Override public void onBackPressed(){web.evaluateJavascript("(()=>{const gate=document.getElementById('gate');if(gate.open){gate.close();return true;}const back=document.querySelector('#map-back,#offline-back,#connection-back,#back,#discovery-back,#done');if(back){back.click();return true;}return false;})()",result->{if("false".equals(result))moveTaskToBack(true);});}
    @Override protected void onDestroy(){if(cameraRequest!=null){cameraRequest.deny();cameraRequest=null;}if(fileCallback!=null){fileCallback.onReceiveValue(null);fileCallback=null;}if(web!=null){web.loadUrl("about:blank");web.destroy();web=null;}lifecycle.shutdown();super.onDestroy();}
}
