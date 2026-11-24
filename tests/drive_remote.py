"""The phone remote through the whole app (harness.App) and the REAL web app in a REAL browser: Microsoft Edge, headless,
driven over its DevTools protocol (a websocket, stdlib only), as a phone (412 x 915, touch, an Android user agent).
Everything on 127.0.0.1: the remote (harness: remote_hosts), Edge's DevTools port, a FAKE OBS (cmlib.selftest.FakeObs)
and a FAKE VTube Studio API (FakeVts) - the real ones are never touched; the recorder runs a stand-in for ffmpeg; the
music and "this PC" sounds go to harness.FakeOut (nothing out loud); settings are a temp copy.
Covers: turning it on (127.0.0.1 only), Pair a phone (the QR code read back by OpenCV when installed), the web app's
crypto = Python's (same vectors), pairing refused on the PC then allowed, the Deck (soundboard sounds into the OBS feed
/ on this PC / both, Stop all, then a Stream Deck page's sound keys), OBS (scenes, a source, mute, volume, recording),
Music (play a song, pause, next, volume, seek, stop), Capture (record / stop; VTube Studio allowed on the PC, its
backgrounds listed and switched), the Android app's updates (Edge as its WebView, a stand-in window.CMShell for its
Java side: screens updated by themselves, a tampered file / an answer not signed by the PC refused, a newer APK fetched
in signed parts and handed over with the right hash; the PC page's App column; Get the Android app), a replayed
request refused, an unpaired device refused, removing the phone on the PC (it shows it's not paired), the pairing kept
sealed in the settings.
Usage: python -u drive_remote.py <repo>"""
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path
from urllib.parse import urlsplit

from harness import App

import numpy as np
import cmlib.remote as RM
from cmlib.obs import ws_frame, ws_read
from cmlib.selftest import FakeObs, FakeVts, remote_call

EDGE = next((p for p in (Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application"
                         / "msedge.exe", Path(os.environ.get("ProgramFiles", "C:/Program Files")) /
                         "Microsoft/Edge/Application/msedge.exe") if p.is_file()), None)
assert EDGE, "Microsoft Edge isn't installed - the phone remote's web app needs a real browser to be tested"
tmp = Path(tempfile.mkdtemp(prefix="cm_remote_"))
SHOTS = os.environ.get("CM_SHOTS")  # a folder: screenshots of the phone's screens go there (to look at by eye)


def tone(p, hz, secs=2.0, rate=44100):
    t = np.arange(int(rate * secs)) / rate
    x = (0.3 * np.sin(2 * np.pi * hz * t) * 32767).astype("<i2")
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(rate), w.writeframes(np.stack([x, x], 1).tobytes())
    return p


class Cdp:
    """A DevTools protocol connection to one page (a websocket client: obs.py's frames)."""

    def __init__(self, url):
        u = urlsplit(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(f"GET {u.path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        self.buf, self.n = bytearray(), 0
        while b"\r\n\r\n" not in self.buf:
            self.buf += self.s.recv(4096)
        head, rest = bytes(self.buf).split(b"\r\n\r\n", 1)
        assert b" 101 " in head.split(b"\r\n")[0], head
        self.buf = bytearray(rest)

    def recv(self, n):
        while len(self.buf) < n:
            c = self.s.recv(1 << 20)
            if not c:
                raise OSError("Edge closed the DevTools connection")
            self.buf += c
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def call(self, method, params=None):
        self.n += 1
        self.s.sendall(ws_frame(1, json.dumps({"id": self.n, "method": method, "params": params or {}}).encode()))
        while True:
            op, data = ws_read(self.recv, masked=False, limit=64 << 20)
            m = json.loads(data)
            if m.get("id") == self.n:
                assert "error" not in m, m
                return m["result"]

    def js(self, expr):
        """Run JavaScript in the page -> its value. Never await the remote here: answers to the phone may need this
        thread (the app's window) - start things, then poll with app.wait."""
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        assert "exceptionDetails" not in r, r["exceptionDetails"]
        return r["result"].get("value")

    def shot(self, name):
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            (Path(SHOTS) / f"{name}.png").write_bytes(base64.b64decode(self.call("Page.captureScreenshot")["data"]))


# the fakes, and the app's settings: a playlist, OBS's port / password, VTube Studio's API port
songs = [tone(tmp / "Intro song.wav", 330, 3.0), tone(tmp / "Second song.wav", 440, 3.0)]
boom, hum = tone(tmp / "boom.wav", 600, 1.0), tone(tmp / "hum.wav", 220, 1.0)
fake_obs, fake_vts = FakeObs("pw-remote"), FakeVts()
app = App({"obs": {"password": "pw-remote", "port": fake_obs.port},
           "music": {"playlists": [{"name": "Stream mix", "songs": [{"path": str(s)} for s in songs]}]},
           "recorder": {"folder": str(tmp / "rec")}, "remote": {"vts_port": fake_vts.port}})
app.obs_ports.add(fake_obs.port)
app.vts_ports.add(fake_vts.port)
cm = app.cm
# a Stream Deck profile whose page has two sound keys and a key that isn't a sound
prof = cm.SD_DIR / "ProfilesV3" / "Deck.sdProfile"
pg = prof / "Profiles" / "PAGE1" / "manifest.json"
pg.parent.mkdir(parents=True)
(prof / "manifest.json").write_text(json.dumps({"Device": {"Model": "20GBA9901", "UUID": "dev"}, "Name": "Live deck",
                                                "Pages": {"Current": "page1", "Default": "x", "Pages": ["page1"]}}))
pg.write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": {
    "1,0": cm.sd_play(hum, "Hum key"), "0,0": cm.sd_play(boom, "Boom key"),
    "2,0": {"UUID": "com.elgato.streamdeck.system.website", "Settings": {"path": "https://example.com"}}}}]}))
cm.sd_devices = lambda *a, **k: {"x": ("20GBA9901", "dev", 3, 2)}
FAKE_REC = "import sys; sys.stdin.read(1); open(sys.argv[1], 'wb').write(b'\\0\\0\\0\\x18ftypmp42' + bytes(4000))"
cm.rec_command = lambda area, fps, out, mouse=True: [sys.executable, "-c", FAKE_REC, str(out)]  # no screen grab
edge, cdp = None, None
app.start()
app.root.geometry("1400x900+0+0")
try:
    # OBS connected on the PC (the fake one); the soundboard has two sounds
    page = app.tab("OBS")
    O = app.api("obs")
    app.button("Connect", page).invoke()
    assert app.wait(lambda: O["state"]["client"] and O["state"]["client"].connected, 15), O["vars"]["conn"].get()
    fed = []
    real_play = O["feed"].play
    O["feed"].play = lambda p, *a, **k: (fed.append(Path(p).name), real_play(p, *a, **k))[1]
    sb = app.api("soundboard")
    sb.add([boom, hum])
    assert app.wait(lambda: len(sb.sounds) == 2, 10), sb.sounds

    # the remote: on (127.0.0.1 only here), then Pair a phone -> a QR code with the address and a one-time code
    page = app.tab("Phone remote")
    Rm = app.api("remote")
    app.button("Turn on", page).invoke()
    srv = Rm["state"]["server"]
    assert srv and srv.hosts == ["127.0.0.1"] and all(h.server_address[0] == "127.0.0.1" for h in srv.httpds)
    assert app.button("Turn off", page) and Rm["vars"]["addr"].get().startswith(f"http://127.0.0.1:{srv.port}/")
    app.button("Pair a phone", page).invoke()
    app.pump(0.2)
    code = Rm["state"]["code"][0]
    assert Rm["vars"]["code"].get() == f"{code[:4]} {code[4:]}" and str(Rm["qr"].cget("image"))
    url = f"http://127.0.0.1:{srv.port}/#pair={code}"
    try:
        import cv2
        png = tmp / "qr.png"
        Rm["state"]["img"].write(str(png), format="png")
        got = cv2.QRCodeDetector().detectAndDecode(cv2.imread(str(png)))[0]
        assert got == url, (got, url)
        print("the QR code shown reads back (OpenCV):", got)
    except ImportError:
        print("QR code not read back: OpenCV isn't installed")

    # the phone: Edge, headless, on its own temp profile; DevTools on 127.0.0.1 only
    prof_dir = tmp / "edge"
    edge = subprocess.Popen([str(EDGE), "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={prof_dir}",
                             "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--mute-audio",
                             "--disable-sync", "--disable-background-networking", "--disable-component-update",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert app.wait(lambda: (prof_dir / "DevToolsActivePort").is_file()
                    and (prof_dir / "DevToolsActivePort").read_text().strip(), 60), "Edge didn't start"
    dport = int((prof_dir / "DevToolsActivePort").read_text().split()[0])
    with urllib.request.urlopen(f"http://127.0.0.1:{dport}/json/list", timeout=10) as r:
        target = next(t for t in json.loads(r.read()) if t["type"] == "page")
    cdp = Cdp(target["webSocketDebuggerUrl"])
    cdp.call("Emulation.setDeviceMetricsOverride", {"width": 412, "height": 915, "deviceScaleFactor": 2,
                                                    "mobile": True})
    cdp.call("Emulation.setUserAgentOverride", {"userAgent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/"
                                                             "537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"})
    cdp.call("Page.enable")
    cdp.call("Page.navigate", {"url": url})
    js = cdp.js

    def must(cond, secs=15, what=""):
        if not app.wait(cond, secs):
            raise AssertionError(f"timed out: {what} | PC status {Rm['status']()!r} | phone "
                                 f"{js('document.getElementById(`conn`).textContent')!r} "
                                 f"{js('document.getElementById(`pairmsg`).textContent')!r} "
                                 f"{js('document.getElementById(`toast`).textContent')!r} "
                                 f"{js('document.getElementById(`appmsg`).textContent')!r} | errors {app.errors[-2:]}")

    def click(sel, text=None):
        ok = js(f"(() => {{ const e = [...document.querySelectorAll({json.dumps(sel)})].find(x => {json.dumps(text)} "
                f"=== null || x.textContent.trim() === {json.dumps(text)}); if (!e) return false; e.click(); "
                "return true; })()")
        assert ok, (sel, text)

    def texts(sel):
        return js(f"[...document.querySelectorAll({json.dumps(sel)})].map(e => e.textContent.trim())")
    must(lambda: js("document.readyState === 'complete' && !!window.CMRemote"), 20, "the web app loaded")
    assert js("location.hash") == "" and js("document.getElementById('code').value") == code  # the code, then gone
    assert js("document.getElementById('devname').value") == "Android phone"
    assert js("getComputedStyle(document.body).backgroundColor") in ("rgb(17, 19, 23)", "rgb(243, 244, 247)")

    # the web app's own SHA-256 / HMAC / SPAKE2 / signatures give Python's answers (cmlib.remote.remote_vectors)
    vec = cm.remote_vectors()
    t0 = time.time()
    got = js(f"CMRemote.vectors({json.dumps(vec)})")
    for k in ("sha_abc", "sha_long", "hmac_fox", "sign", "point_a", "code_w", "pub_a", "pub_b", "secret", "proof_a",
              "proof_b"):
        assert got[k] == vec[k], (k, got[k][:40], vec[k][:40])
    assert got["same"] is True
    print(f"the web app's crypto = Python's ({len(vec)} vectors, SPAKE2 both ways, {time.time() - t0:.1f} s in Edge)")
    # installable: manifest, icons, the service worker (a secure page here: 127.0.0.1)
    man = js("fetch('/manifest.webmanifest').then(r => r.json())")
    assert man["display"] == "standalone" and {i["sizes"] for i in man["icons"]} == {"192x192", "512x512"}
    assert js("fetch('/icon-512.png').then(r => r.status + ' ' + r.headers.get('content-type'))") == "200 image/png"
    assert app.wait(lambda: js("navigator.serviceWorker.getRegistration().then(r => !!r)"), 15)
    cdp.shot("1 pair")

    # pairing: refused on the PC first (the code is then used up), then a new code, allowed
    n = len(app.asked)
    app.yes.append(False)
    click("#pairbtn")
    must(lambda: "Not allowed on the PC" in js("document.getElementById('pairmsg').textContent"), 30, "refused")
    assert app.asked[n][1] == "Pair a phone" and "Android phone" in app.asked[n][2] and not Rm["devices"]
    click("#pairbtn")
    must(lambda: "No pairing is open" in js("document.getElementById('pairmsg').textContent"), 30, "code used up")
    app.button("Pair a phone", page).invoke()
    code = Rm["state"]["code"][0]
    js(f"document.getElementById('code').value = '{code[:4]} {code[4:]}'; "
       "document.getElementById('devname').value = 'Test phone'")
    app.yes.append(True)
    click("#pairbtn")
    must(lambda: len(Rm["devices"]) == 1 and js("!!localStorage.getItem('cm.remote.device')"), 30, "paired")
    d = Rm["devices"][0]
    assert d["name"] == "Test phone" and js("JSON.parse(localStorage.getItem('cm.remote.device')).key") == d["key"]
    assert not Rm["state"]["code"] and Rm["tree"].get_children() == (d["id"],)
    kept = json.loads(cm.SETTINGS.read_text())["remote"]["devices"][0]  # written at once, the key sealed
    assert kept["id"] == d["id"] and kept["key"].startswith("dpapi:") and d["key"] not in json.dumps(kept)
    must(lambda: js("document.getElementById('conn').className") == "pill ok", 15, "connected")
    assert js("document.getElementById('pcname').textContent") and not js("document.getElementById('tabs').hidden")
    print("paired: refused on the PC once, then allowed; the phone shows Connected")

    # Deck: the soundboard's sounds; into the OBS feed, on this PC, both; Stop all
    must(lambda: texts("#grid .tile") == ["Boom", "Hum"], 15, "deck tiles")
    assert not js("document.getElementById('decknote').hidden")  # the soundboard feed is off on the PC: it says so
    cdp.shot("2 deck")
    click("#grid .tile", "Boom")
    must(lambda: fed == ["boom.wav"], 10, "Boom into the feed")
    click("#to button", "This PC")
    click("#grid .tile", "Hum")
    must(lambda: Rm["state"]["out"] is not None and Rm["state"]["out"].blocks > 0, 10, "Hum on this PC")
    assert fed == ["boom.wav"]
    click("#to button", "Both")
    click("#grid .tile", "Boom")
    must(lambda: fed == ["boom.wav", "boom.wav"], 10, "both")
    click("#stopall")
    must(lambda: not O["feed"].playing() and not Rm["state"]["here_playing"](), 5, "stopped")
    # the Deck showing a Stream Deck page instead: its sound keys, in key order (the website key isn't one)
    choice = next(c for c in Rm["choices"]() if c.startswith("Live deck"))
    Rm["vars"]["deck"].set(choice)
    must(lambda: texts("#grid .tile") == ["Boom key", "Hum key"], 15, "Stream Deck page on the phone")
    click("#to button", "OBS feed")
    click("#grid .tile", "Hum key")
    must(lambda: fed[-1] == "hum.wav", 10, "a page's key played")
    print("Deck: soundboard sounds into the OBS feed / this PC / both, Stop all; a Stream Deck page's keys")

    # OBS: scenes, a source, mute, volume, recording
    click("#tabs button", "OBS")
    must(lambda: texts("#scenes .chip") == ["Main", "BRB"] or texts("#scenes .chip") == ["BRB", "Main"], 15, "scenes")
    cdp.shot("3 obs")
    click("#scenes .chip", "BRB")
    must(lambda: fake_obs.scene == "BRB", 10, "scene switched")
    must(lambda: js("[...document.querySelectorAll('#scenes .chip.on')].map(e => e.textContent).join()") == "BRB", 10)
    must(lambda: texts("#items .name") == ["Logo"], 10, "BRB's sources")
    click("#items .sw")
    must(lambda: fake_obs.items["BRB"][0]["sceneItemEnabled"] is False, 10, "source hidden")
    js("[...document.querySelectorAll('#mixer .row')].find(r => r.textContent.startsWith('Mic'))"
       ".querySelector('.mini').click()")
    must(lambda: fake_obs.inputs["Mic"]["muted"] is True, 10, "Mic muted")
    js("(() => { const r = [...document.querySelectorAll('#mixer .row')].find(r => r.textContent.startsWith("
       "'Desktop Audio')).querySelector('input'); r.value = 50; r.dispatchEvent(new Event('change')); })()")
    must(lambda: abs(fake_obs.inputs["Desktop Audio"]["mul"] - 0.25) < 1e-6, 10, "volume")
    js("window.confirm = () => false")
    click("#outs .out")  # the first: Stream - it asks first; said no
    app.wait(lambda: False, 1.0)
    assert fake_obs.outputs["stream"] is False
    js("[...document.querySelectorAll('#outs .out')][1].click()")  # Record: no question
    must(lambda: fake_obs.outputs["record"] is True, 10, "recording in OBS")
    print("OBS: scene, source, mute, volume, recording (going live asks first)")

    # Music: play a song of the playlist, pause, next, volume, seek, stop
    M = app.api("music")
    click("#tabs button", "Music")
    must(lambda: texts("#songs .row") == ["1.  Intro song", "2.  Second song"], 15, "songs")
    click("#songs .row", "2.  Second song")
    must(lambda: M["now"]["title"] == "Second song" and M["engine"].song, 10, "playing")
    must(lambda: js("document.getElementById('mtitle').textContent") == "Second song", 10, "now playing shown")
    cdp.shot("4 music")
    click("#mplay")  # pause
    must(lambda: M["engine"].paused, 10, "paused")
    click("#mplay")
    must(lambda: not M["engine"].paused, 10, "playing again")
    click("#mnext")
    must(lambda: M["now"]["title"] == "Intro song", 10, "next (repeat all: round to the first)")
    js("(() => { const v = document.getElementById('mvol'); v.value = 35; v.dispatchEvent(new Event('change')); })()")
    must(lambda: M["vars"]["vol"].get() == 35, 10, "volume")
    js("(() => { const v = document.getElementById('mseek'); v.max = 3; v.value = 2; "
       "v.dispatchEvent(new Event('change')); })()")
    must(lambda: M["engine"].position() >= 2.0, 10, "seek")
    click("#mstop")
    must(lambda: not M["engine"].song, 10, "stopped")
    print("Music: play, pause, play, next, volume, seek, stop")

    # Capture: the recorder from the phone (it asks first); VTube Studio allowed on the PC, backgrounds switched
    R = app.api("recorder")
    click("#tabs button", "Capture")
    must(lambda: "allowed yet" in js("document.getElementById('vtsnote').textContent"), 15, "VTS not allowed")
    js("window.confirm = () => true")
    click("#recbtn")
    must(lambda: R["state"]["proc"] is not None, 15, "recording")
    must(lambda: js("document.getElementById('recstate').textContent").startswith("Recording"), 10, "shown")
    click("#recbtn")
    must(lambda: R["state"]["proc"] is None and list((tmp / "rec").glob("*.mp4")), 20, "recording stopped, kept")
    app.button("Allow in VTube Studio", page).invoke()
    must(lambda: Rm["vars"]["vts"].get().startswith("Allowed"), 15, "allowed in VTube Studio")
    assert fake_vts.asked == 1 and json.loads(cm.SETTINGS.read_text())["remote"]["vts_token"].startswith("dpapi:")
    must(lambda: texts("#bgs .tile") == ["Stars", "Rain"], 15, "backgrounds on the phone")
    assert js("document.getElementById('vtsmodel').textContent") == "Model: Wolf"
    cdp.shot("5 capture")
    click("#bgs .tile", "Rain")
    must(lambda: fake_vts.triggered == [FakeVts.HOTKEYS[1]["hotkeyID"]], 10, "background switched")
    print("Capture: recording started / stopped from the phone; VTube Studio backgrounds listed and switched")

    # the Android app (CM Remote): Edge stands in for its WebView, window.CMShell for the app's side (it records what
    # the app would be given: the Java side itself needs a phone). Its screens are older than the PC's: updated by
    # themselves, checked; a tampered file and an answer not signed by the PC refused; then a newer APK announced:
    # downloaded in signed parts, its hash checked, handed to the app to install
    web_v = cm.remote_web()["version"]
    # (the steps above can make 30+ signed requests within seconds: let the remote's 40-per-10-s limit per phone,
    # RemoteServer.RATE, drain first - it would refuse the update's requests as "too many at once", as it should)
    must(lambda: len(srv.hits.get(d["id"], [])) < 10, 20, "the rate window drained")
    cm.APK_DIRS = [tmp / "no-apk"]  # (this PC hasn't built the Android app yet)
    cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": """(() => {
      const K = "fakeShell", get = () => JSON.parse(localStorage.getItem(K) ||
        '{"web": "0000000000000000", "apk": 2020001, "saved": [], "apks": []}'), put = x => localStorage.setItem(K, JSON.stringify(x));
      window.CMShell = {
        info() { const x = get(); return JSON.stringify({web: x.web, apk: x.apk, name: "2.2.1"}); },
        saveWeb(json) { const x = get(), u = JSON.parse(json); x.saved.push(u.version); x.web = u.version; put(x); return ""; },
        installApk(b64, sha) { const x = get(); x.apks.push({b64, sha}); put(x); setTimeout(() => CMRemote.shell("progress", "Installing (test)"), 0); },
        forget() { const x = get(); x.forgot = true; put(x); }};
    })();"""})

    def fake(k):
        return js(f"(JSON.parse(localStorage.getItem('fakeShell') || '{{}}'))[{json.dumps(k)}]")

    def fake_web(v):
        js(f"(() => {{ const x = JSON.parse(localStorage.getItem('fakeShell')); x.web = '{v}'; "
           "localStorage.setItem('fakeShell', JSON.stringify(x)); })()")
    cdp.call("Page.reload")
    must(lambda: fake("web") == web_v, 30, "the app's screens updated from the PC by themselves")
    assert fake("saved") == [web_v]
    click("#tabs button", "Capture")
    must(lambda: js("document.getElementById('appmsg').textContent") == "Up to date.", 15, "up to date after it")
    assert not js("document.getElementById('appbox').hidden") and js("document.body.classList.contains('shell')")
    must(lambda: Rm["devices"][0].get("app") == {"web": web_v, "apk": 2020001}, 10, "the PC knows its version")
    must(lambda: Rm["tree"].set(d["id"], "app") == "2.2.1", 15, "the App column")
    cdp.shot("7 app up to date")
    real_web = cm.remote_web

    def tampered(data=False):  # one file changed after its hash was listed (as if altered on the way)
        w = real_web(data)
        if data:
            f = w["files"]["/app.css"]
            f["data"] = base64.b64encode(base64.b64decode(f["data"]) + b"/* changed */").decode()
        return w
    cm.remote_web = tampered
    try:
        fake_web("1" * 16)
        click("#appbtn")
        must(lambda: "isn't the one the PC listed" in js("document.getElementById('appmsg').textContent"), 15,
             "a tampered file refused")
        assert fake("saved") == [web_v] and fake("web") == "1" * 16
    finally:
        cm.remote_web = real_web
    here_tl, real_sign, real_update = threading.local(), RM.peer_sign, RM.remote_update

    def update_marked(cmd, args):  # the web bundle's answer gets a signature that isn't the PC's
        here_tl.bad = cmd == "app.web"
        return real_update(cmd, args)

    def sign_spoiled(key, method, *a):
        if method == "REPLY" and getattr(here_tl, "bad", False):
            here_tl.bad = False
            return "0" * 64
        return real_sign(key, method, *a)
    RM.remote_update, RM.peer_sign = update_marked, sign_spoiled
    try:
        click("#appbtn")
        must(lambda: "wasn't signed by your PC" in js("document.getElementById('appmsg').textContent"), 15,
             "an answer not signed by the PC refused")
        assert fake("saved") == [web_v]
    finally:
        RM.remote_update, RM.peer_sign = real_update, real_sign
    click("#appbtn")  # the real one: applied
    must(lambda: fake("web") == web_v and fake("saved") == [web_v, web_v], 20, "applied when it's right")
    print("Android app (its page side, in Edge): screens updated by themselves, checked; a tampered file and an answer "
          "not signed by the PC refused")
    # a newer APK built on the PC: announced in the signed state, fetched by the phone, handed to the app
    apk_dir = tmp / "apk"
    apk_dir.mkdir()
    apk = os.urandom(cm.APK_PART * 2 + 777)
    (apk_dir / cm.APK_NAME).write_bytes(apk)
    (apk_dir / (cm.APK_NAME + ".json")).write_text(json.dumps({"code": 2020009, "name": "2.2.9"}))
    cm.APK_DIRS = [apk_dir]
    must(lambda: len(fake("apks") or []) == 1, 30, "the new APK handed to the app")
    got = fake("apks")[0]
    assert got["sha"] == hashlib.sha256(apk).hexdigest() and base64.b64decode(got["b64"]) == apk
    must(lambda: "Installing (test)" in js("document.getElementById('appmsg').textContent"), 10, "the app's word shown")
    must(lambda: Rm["tree"].set(d["id"], "app") == "2.2.1 - update available", 15, "the PC shows it's behind")
    assert remote_call(srv.port, "ab" * 32, "cd" * 16, "app.apk", {"part": 0})[0] == 401  # never to others
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/app.apk", timeout=10) as r:  # the first install's link
        assert r.read() == apk
    app.button("Get the Android app", page).invoke()
    app.pump(0.2)
    assert Rm["vars"]["code"].get() == f"http://127.0.0.1:{srv.port}/app.apk" and str(Rm["qr"].cget("image"))
    print("Android app: a newer APK announced, downloaded in signed parts (3), its hash right, handed to the app to "
          "install; the PC page shows the phone's version, update available; Get the Android app shows its link")

    # a request heard on the network and sent again: refused; a device that was never paired: refused
    key, dev = d["key"], d["id"]
    st_, _, out = remote_call(srv.port, key, dev, "deck.stop", nonce="5a" * 16)  # (answered on the server's thread)
    assert st_ == 200 and out["ok"], out
    assert remote_call(srv.port, key, dev, "deck.stop", nonce="5a" * 16)[0] == 403
    assert remote_call(srv.port, "ab" * 32, "cd" * 16, "deck.stop")[0] == 401
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/", timeout=10) as r:  # only the (pairing) page
        assert b"Pair this phone" in r.read()
    print("a replayed request and an unpaired device: refused")

    # removed on the PC: the phone's next request is refused and it says it's not paired any more
    Rm["tree"].selection_set(dev)
    app.button("Remove", page).invoke()
    assert not Rm["devices"] and not json.loads(cm.SETTINGS.read_text())["remote"]["devices"]
    must(lambda: "isn't paired with this PC any more" in js("document.getElementById('pairmsg').textContent"), 15,
         "the phone told")
    assert js("document.getElementById('tabs').hidden") and remote_call(srv.port, key, dev, "deck.stop")[0] == 401
    cdp.shot("6 removed")
    print("removed on the PC: refused at once, the phone shows it")
finally:
    if edge:
        edge.kill()
        edge.wait(15)
    fake_obs.stop()
    fake_vts.stop()
saved = app.close()
assert saved["remote"]["on"] is True and saved["remote"]["devices"] == [] and saved["remote"]["vts_token"]
shutil.rmtree(tmp, ignore_errors=True)
print("phone remote ok: paired, Deck / OBS / Music / Capture from a real browser, replay + unpaired refused, removed")
