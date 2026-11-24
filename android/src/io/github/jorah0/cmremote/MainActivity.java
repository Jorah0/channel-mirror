package io.github.jorah0.cmremote;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.graphics.Bitmap;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.util.Base64;
import android.util.TypedValue;
import android.view.View;
import android.view.WindowInsets;
import android.view.inputmethod.EditorInfo;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** CM Remote: Channel Mirror's phone remote as an app. One WebView with the web app the PC serves - but its files come
 * from this app (bundled in the APK, or an update from the paired PC checked against the hashes the PC signed), never
 * from the network: only the remote's requests (POST) go out, and only to the one PC address it was given. */
public class MainActivity extends Activity {
    static final int BG = 0xff111317, FG = 0xffeceef2, MUTED = 0xff9aa1ad, BAD = 0xffff6b6b;
    static final String CSP = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; "
            + "form-action 'none'";
    static volatile MainActivity current;  // for Events: how an install went

    /** The web app's files: {"version", "apk", "files": {path: {"type", "sha256"}}}, bundled or kept (files/web). */
    static final class Files {
        final JSONObject m;
        final boolean bundled;

        Files(JSONObject m, boolean bundled) {
            this.m = m;
            this.bundled = bundled;
        }
    }

    SharedPreferences prefs;
    FrameLayout root;
    WebView web;
    volatile String pc;  // the paired PC's origin: http://host:port
    volatile String page;  // the origin of the page showing now (set on the UI thread)
    volatile Files files;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        current = this;
        prefs = getSharedPreferences("cm", MODE_PRIVATE);
        root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        root.setOnApplyWindowInsetsListener((v, in) -> {  // edge to edge (Android 15+): bars and keyboard never cover it
            if (Build.VERSION.SDK_INT < 30) {
                return in;
            }
            Insets i = in.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
            v.setPadding(i.left, i.top, i.right, i.bottom);
            return WindowInsets.CONSUMED;
        });
        setContentView(root);
        files = loadFiles();
        pc = prefs.getString("pc", null);
        if (pc == null) {
            ask("");
        } else {
            open("");
        }
    }

    @Override
    protected void onDestroy() {
        if (current == this) {
            current = null;
        }
        if (web != null) {
            web.destroy();
        }
        super.onDestroy();
    }

    // ---- the PC's address: typed once (or the pairing link pasted) ----
    void ask(String msg) {
        page = null;
        root.removeAllViews();
        if (web != null) {
            web.destroy();
            web = null;
        }
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setPadding(dp(24), dp(32), dp(24), dp(24));
        EditText addr = new EditText(this);
        addr.setSingleLine();
        addr.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        addr.setImeOptions(EditorInfo.IME_ACTION_GO);
        addr.setHint("192.168.1.23:8770");
        addr.setTextColor(FG);
        addr.setHintTextColor(MUTED);
        String was = prefs.getString("typed", "");
        addr.setText(was);
        Button go = new Button(this);
        go.setText("Connect");
        TextView err = text(msg, 15, BAD);
        Runnable connect = () -> {
            String[] a = parse(addr.getText().toString());
            if (a == null) {
                err.setText("That isn't the remote's address. It's the PC's home-network address (192.168.x.x, 10.x.x.x "
                        + "or 172.16-31.x.x) or its Tailscale one (100.x.x.x or a .ts.net name), with the port - for "
                        + "example 192.168.1.23:8770.");
                return;
            }
            prefs.edit().putString("pc", a[0]).putString("typed", a[0].substring(7)).apply();
            pc = a[0];
            open(a[1]);
        };
        go.setOnClickListener(v -> connect.run());
        addr.setOnEditorActionListener((v, id, ev) -> {
            connect.run();
            return true;
        });
        l.addView(text("Channel Mirror Remote", 24, FG));
        l.addView(text("On the PC: Channel Mirror > Phone remote > Turn on. Type the address it shows under \"Open on "
                + "the phone\" (the Tailscale one works at home and away). Then pair with the code the PC shows.", 15,
                MUTED));
        l.addView(addr);
        l.addView(go);
        l.addView(err);
        l.addView(text("This app's signing key: " + fingerprint() + " - the PC's Phone remote page shows the same "
                + "one when this is the app it built.", 13, MUTED));
        ScrollView s = new ScrollView(this);
        s.addView(l);
        root.addView(s);
    }

    TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setPadding(0, dp(8), 0, dp(8));
        return t;
    }

    int dp(int x) {
        return Math.round(x * getResources().getDisplayMetrics().density);
    }

    /** "192.168.1.23:8770", "http://host:port/#pair=12345678", "pc.tail1234.ts.net:8770" -> {origin, pairing code or
     * ""}; null when it isn't where the remote can be: the home network or Tailscale. */
    static String[] parse(String s) {
        s = s.trim();
        Matcher m = Pattern.compile("[#&]pair=(\\d{8})").matcher(s);
        String code = m.find() ? m.group(1) : "";
        Uri u = Uri.parse(s.contains("://") ? s : "http://" + s);
        String h = u.getHost();
        int port = u.getPort() == -1 ? 8770 : u.getPort();
        if (!"http".equals(u.getScheme()) || h == null || port < 1 || port > 65535) {
            return null;
        }
        h = h.replace("[", "").replace("]", "").toLowerCase(Locale.ROOT);
        if (!privateIp(h) && !h.matches("([a-z0-9-]{1,63}\\.){1,6}ts\\.net")) {
            return null;
        }
        return new String[]{origin(Uri.parse("http://" + (h.contains(":") ? "[" + h + "]" : h) + ":" + port + "/")),
                code};
    }

    static boolean privateIp(String h) {
        String o = "(0|[1-9]\\d{0,2})";  // no leading zeros: "010.1.1.1" is octal (8.1.1.1) to the WebView
        Matcher m = Pattern.compile(o + "\\." + o + "\\." + o + "\\." + o).matcher(h);
        if (m.matches()) {
            int[] n = new int[4];
            for (int i = 0; i < 4; i++) {
                n[i] = Integer.parseInt(m.group(i + 1));
                if (n[i] > 255) {
                    return false;
                }
            }
            return n[0] == 10 || n[0] == 192 && n[1] == 168 || n[0] == 172 && n[1] >= 16 && n[1] <= 31
                    || n[0] == 100 && n[1] >= 64 && n[1] <= 127;  // 100.64.0.0/10: Tailscale
        }
        return h.matches("fd7a:115c:a1e0:[0-9a-f:]{1,30}");  // Tailscale's IPv6 addresses
    }

    /** http://host:port of a URL ("" for anything but http). */
    static String origin(Uri u) {
        if (u == null || !"http".equals(u.getScheme()) || u.getHost() == null) {
            return "";
        }
        String h = u.getHost().replace("[", "").replace("]", "").toLowerCase(Locale.ROOT);
        return "http://" + (h.contains(":") ? "[" + h + "]" : h) + ":" + (u.getPort() == -1 ? 80 : u.getPort());
    }

    // ---- the remote: the web app in a WebView that only ever talks to the paired PC ----
    void open(String code) {
        root.removeAllViews();
        if (web != null) {
            web.destroy();
        }
        web = new WebView(this);
        web.setBackgroundColor(BG);
        WebSettings w = web.getSettings();
        w.setJavaScriptEnabled(true);
        w.setDomStorageEnabled(true);  // the pairing (device id + key) is kept by the web app in localStorage
        w.setAllowFileAccess(false);
        w.setAllowContentAccess(false);
        w.setAllowFileAccessFromFileURLs(false);
        w.setAllowUniversalAccessFromFileURLs(false);
        w.setGeolocationEnabled(false);
        w.setSupportMultipleWindows(false);
        w.setJavaScriptCanOpenWindowsAutomatically(false);
        w.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        w.setSafeBrowsingEnabled(false);
        w.setCacheMode(WebSettings.LOAD_NO_CACHE);
        web.addJavascriptInterface(new Bridge(), "CMShell");
        web.setWebChromeClient(new WebChromeClient());  // confirm() works (it asks before going live); nothing else
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                return !origin(r.getUrl()).equals(pc);  // anywhere else: not opened
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) {
                return serve(r);
            }

            @Override
            public void onPageStarted(WebView v, String url, Bitmap icon) {
                page = origin(Uri.parse(url));
            }
        });
        root.addView(web);
        web.loadUrl(pc + "/" + (code.isEmpty() ? "" : "#pair=" + code));
    }

    /** Every request the page makes: the PC's own address only; its files from this app, never from the network. */
    WebResourceResponse serve(WebResourceRequest r) {
        if (!origin(r.getUrl()).equals(pc)) {
            return refused(403, "Forbidden");
        }
        if (!"GET".equals(r.getMethod())) {
            return null;  // the remote's own requests (signed by the web app): to the PC
        }
        String path = r.getUrl().getPath() == null || r.getUrl().getPath().isEmpty() ? "/" : r.getUrl().getPath();
        Files f = files;
        JSONObject e = f.m.optJSONObject("files") == null ? null : f.m.optJSONObject("files").optJSONObject(path);
        if (e == null) {
            return refused(404, "Not Found");
        }
        String type = e.optString("type"), sha = e.optString("sha256");
        try {
            InputStream in = f.bundled ? getAssets().open("web/" + sha)
                    : new FileInputStream(new File(getFilesDir(), "web/" + sha));
            Map<String, String> h = new HashMap<>();
            h.put("Content-Security-Policy", CSP);
            h.put("Cache-Control", "no-store");
            h.put("X-Content-Type-Options", "nosniff");
            int cs = type.indexOf("charset=");
            return new WebResourceResponse(type.split(";")[0].trim(), cs < 0 ? null : type.substring(cs + 8).trim(),
                    200, "OK", h, in);
        } catch (IOException x) {
            return refused(404, "Not Found");
        }
    }

    static WebResourceResponse refused(int status, String why) {
        return new WebResourceResponse("text/plain", "utf-8", status, why, null, new ByteArrayInputStream(new byte[0]));
    }

    /** The files kept from an update when they were made for this build of the app, else the APK's own. */
    Files loadFiles() {
        try {
            JSONObject m = new JSONObject(read(new FileInputStream(new File(getFilesDir(), "web/manifest.json"))));
            if (m.optLong("apk") == versionCode()) {
                return new Files(m, false);
            }
        } catch (Exception e) {
            // none kept (or damaged): the bundled ones
        }
        try {
            return new Files(new JSONObject(read(getAssets().open("web/manifest.json"))), true);
        } catch (Exception e) {
            throw new IllegalStateException("the APK has no web app", e);
        }
    }

    /** A web update {"version", "files": {path: {"type", "sha256", "data"}}} - the PC signed it and the page checked
     * that; checked again here: every file against its hash, the version against the list. Kept, used from the next
     * page load. (Only an integrity check: the device key lives in the page, so the page's signature check is the
     * one that counts - a script in the page could hand anything here; none but these files ever runs in it.) */
    synchronized void save(JSONObject u) throws Exception {
        String version = u.getString("version");
        JSONObject in = u.getJSONObject("files"), keep = new JSONObject();
        if (!version.matches("[0-9a-f]{16}") || in.length() == 0 || in.length() > 64) {
            throw new IOException("it isn't an update");
        }
        File dir = new File(getFilesDir(), "web");
        if (!dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException("no room for it");
        }
        List<String> paths = new ArrayList<>();
        Set<String> names = new HashSet<>();
        for (Iterator<String> it = in.keys(); it.hasNext(); ) {
            paths.add(it.next());
        }
        Collections.sort(paths);
        StringBuilder list = new StringBuilder("{");
        for (String p : paths) {
            JSONObject f = in.getJSONObject(p);
            String sha = f.getString("sha256"), type = f.getString("type");
            if (!p.matches("/[A-Za-z0-9._-]{0,64}") || !sha.matches("[0-9a-f]{64}")
                    || !type.matches("[a-z]+/[a-z0-9.+-]+(; charset=utf-8)?")) {
                throw new IOException("it isn't an update");
            }
            byte[] data = Base64.decode(f.getString("data"), Base64.DEFAULT);
            if (!hex(sha256(data)).equals(sha)) {
                throw new IOException("a file isn't the one the PC listed");
            }
            write(new File(dir, sha), data);
            keep.put(p, new JSONObject().put("type", type).put("sha256", sha));
            names.add(sha);
            list.append(list.length() > 1 ? "," : "").append('"').append(p).append("\":\"").append(sha).append('"');
        }
        if (!hex(sha256(list.append("}").toString().getBytes(StandardCharsets.UTF_8))).substring(0, 16).equals(version)) {
            throw new IOException("it isn't the version the PC announced");
        }
        JSONObject m = new JSONObject().put("version", version).put("apk", versionCode()).put("files", keep);
        File tmp = new File(dir, "manifest.json.tmp");
        write(tmp, m.toString().getBytes(StandardCharsets.UTF_8));
        if (!tmp.renameTo(new File(dir, "manifest.json"))) {
            throw new IOException("it couldn't be kept");
        }
        files = new Files(m, false);
        File[] old = dir.listFiles();
        for (File f : old == null ? new File[0] : old) {
            if (!names.contains(f.getName()) && !f.getName().equals("manifest.json")) {
                f.delete();
            }
        }
    }

    // ---- updating the app itself: an APK from the paired PC, installed only when signed like this one ----
    void install(String b64, String sha) {
        File f = new File(getCacheDir(), "update.apk");
        try {
            byte[] apk = Base64.decode(b64, Base64.DEFAULT);
            if (!hex(sha256(apk)).equals(sha)) {
                throw new IOException("the download isn't the app the PC listed");
            }
            write(f, apk);
            PackageManager pm = getPackageManager();
            int flags = Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES
                    : PackageManager.GET_SIGNATURES;
            PackageInfo got = pm.getPackageArchiveInfo(f.getPath(), flags);
            PackageInfo me = pm.getPackageInfo(getPackageName(), flags);
            if (got == null || !getPackageName().equals(got.packageName)) {
                throw new IOException("it isn't CM Remote");
            }
            if (code(got) <= code(me)) {
                throw new IOException("it isn't newer than this one");
            }
            Set<String> mine = certs(me);
            if (mine.isEmpty() || !mine.equals(certs(got))) {
                throw new IOException("it isn't signed with this app's key");
            }
            if (!pm.canRequestPackageInstalls()) {  // once: Android's switch for this app
                say("error", "Allow CM Remote to install updates (Android shows the switch now), then come back and "
                        + "press Check for updates.");
                startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + getPackageName())));
                return;
            }
            PackageInstaller pi = pm.getPackageInstaller();
            PackageInstaller.SessionParams p = new PackageInstaller.SessionParams(
                    PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            p.setAppPackageName(getPackageName());
            p.setSize(apk.length);
            if (Build.VERSION.SDK_INT >= 31) {  // silent when this app installed itself last time
                p.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED);
            }
            int id = pi.createSession(p);
            try (PackageInstaller.Session s = pi.openSession(id)) {
                try (OutputStream o = s.openWrite("base.apk", 0, apk.length)) {
                    o.write(apk);
                    s.fsync(o);
                }
                Intent done = new Intent(this, Events.class).setAction(Events.INSTALL);
                s.commit(PendingIntent.getBroadcast(this, id, done, PendingIntent.FLAG_UPDATE_CURRENT
                        | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0)).getIntentSender());
            }
            say("progress", "Installing - the app closes and opens again when it's done.");
        } catch (Exception e) {
            say("error", "Not installed: " + e.getMessage());
        } finally {
            f.delete();
        }
    }

    static long code(PackageInfo p) {
        return Build.VERSION.SDK_INT >= 28 ? p.getLongVersionCode() : p.versionCode;
    }

    long versionCode() {
        try {
            return code(getPackageManager().getPackageInfo(getPackageName(), 0));
        } catch (PackageManager.NameNotFoundException e) {
            return 0;
        }
    }

    String versionName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "?";
        }
    }

    /** SHA-256 of each certificate an APK is signed with now. */
    static Set<String> certs(PackageInfo p) {
        Signature[] s = null;
        if (Build.VERSION.SDK_INT >= 28) {
            if (p.signingInfo != null) {
                s = p.signingInfo.getApkContentsSigners();
            }
        } else {
            s = p.signatures;
        }
        Set<String> out = new HashSet<>();
        for (Signature x : s == null ? new Signature[0] : s) {
            out.add(hex(sha256(x.toByteArray())));
        }
        return out;
    }

    /** The first 16 hex of this app's signing certificate's SHA-256, in groups of 4 (compared with the PC's). */
    String fingerprint() {
        try {
            Set<String> c = certs(getPackageManager().getPackageInfo(getPackageName(), Build.VERSION.SDK_INT >= 28
                    ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES));
            String f = c.size() == 1 ? c.iterator().next() : "";
            return f.isEmpty() ? "?" : f.substring(0, 4) + " " + f.substring(4, 8) + " " + f.substring(8, 12) + " "
                    + f.substring(12, 16);
        } catch (PackageManager.NameNotFoundException e) {
            return "?";
        }
    }

    /** To the page: how an install goes (kind: progress, done, error). */
    static void say(String kind, String text) {
        MainActivity a = current;
        if (a != null) {
            a.runOnUiThread(() -> {
                if (a.web != null) {
                    a.web.evaluateJavascript("window.CMRemote&&CMRemote.shell&&CMRemote.shell(" + JSONObject.quote(kind)
                            + "," + JSONObject.quote(text) + ")", null);
                }
            });
        }
    }

    /** What the page may ask of the app (window.CMShell) - only the paired PC's page, which is this app's own files. */
    final class Bridge {
        boolean ours() {
            String p = page;
            return p != null && p.equals(pc);
        }

        @JavascriptInterface
        public String info() {
            try {
                return new JSONObject().put("web", files.m.optString("version")).put("apk", versionCode())
                        .put("name", versionName()).toString();
            } catch (Exception e) {
                return "{}";
            }
        }

        @JavascriptInterface
        public String saveWeb(String json) {
            if (!ours()) {
                return "Not allowed here.";
            }
            try {
                save(new JSONObject(json));
                return "";
            } catch (Exception e) {
                return "The update wasn't applied: " + e.getMessage();
            }
        }

        @JavascriptInterface
        public void installApk(String b64, String sha) {
            if (ours()) {
                new Thread(() -> install(b64, sha)).start();
            }
        }

        @JavascriptInterface
        public void forget() {
            if (ours()) {
                runOnUiThread(() -> {
                    android.webkit.WebStorage.getInstance().deleteAllData();  // the old pairing (device key) too
                    prefs.edit().remove("pc").apply();
                    pc = null;
                    ask("");
                });
            }
        }
    }

    // ---- small helpers ----
    static byte[] sha256(byte[] b) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(b);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    static String hex(byte[] b) {
        StringBuilder s = new StringBuilder();
        for (byte x : b) {
            s.append(String.format(Locale.ROOT, "%02x", x));
        }
        return s.toString();
    }

    static String read(InputStream in) throws IOException {
        try (InputStream i = in) {
            ByteArrayOutputStream o = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            for (int n; (n = i.read(buf)) > 0; ) {
                o.write(buf, 0, n);
            }
            return new String(o.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    static void write(File f, byte[] b) throws IOException {
        try (FileOutputStream o = new FileOutputStream(f)) {
            o.write(b);
            o.getFD().sync();
        }
    }
}
