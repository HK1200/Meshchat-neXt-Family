package org.meshchat.family.preview;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.os.Bundle;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.nio.charset.StandardCharsets;

/** Never targets a regular install, starts an Activity, or requests permissions. */
public final class FamilyTestInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context target = getTargetContext();
            if (!"org.meshchat.family.setuptest".equals(target.getPackageName()) ||
                    (target.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0) {
                throw new SecurityException("Only a disposable debuggable setup-test package is allowed");
            }
            if (!Python.isStarted()) Python.start(new AndroidPlatform(target));
            String source;
            try (java.io.InputStream input = getContext().getAssets().open("private_call_routes.py")) {
                java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
                byte[] buffer = new byte[4096];
                for (int count; (count = input.read(buffer)) != -1;) bytes.write(buffer, 0, count);
                source = new String(bytes.toByteArray(), StandardCharsets.UTF_8);
            }
            Python python = Python.getInstance();
            com.chaquo.python.PyObject globals = python.getModule("builtins").callAttr("dict");
            python.getModule("builtins").callAttr("exec", source, globals);
            String proof = python.getModule("builtins").callAttr("eval", "verify_private_call_routes", globals).call(target.getCacheDir().getAbsolutePath()).toString();
            result.putString("family_call_route_proof", proof);
            finish(Activity.RESULT_OK, result);
        } catch (Throwable error) {
            result.putString("failure", error.getClass().getName() + ": " + error.getMessage());
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}
