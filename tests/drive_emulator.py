"""The Android app (CM Remote) for real: dist/ChannelMirror-Remote.apk - the signed release build, unchanged - installed
on an Android emulator and driven like a person would: taps and typing through Android's own input, the screens read
back through its accessibility tree (uiautomator; the web screens' HTML ids are their resource ids). The PC side is the
whole app (harness.App) with the phone remote on 127.0.0.1, a FAKE OBS and stand-in sounds; the emulator reaches it at
10.0.2.2 (the emulator's name for this PC).
Covers: install (the version the .json says), the first screen refusing an address outside the home network, typing
the pairing link, pairing (allowed on the PC), Connected, the Deck playing into the OBS feed, OBS scenes switched, the
app closed and opened again (still paired, straight to the remote), removed on the PC (the phone says so).
Isolated: its own emulator (a temp AVD, no window, no sound, wiped) on its own adb server and a console port outside the
range other adb servers look at - nothing else on this PC can see or use it, and it never touches another emulator.
SKIPPED (exit 0, says so) without the Android SDK's emulator, an x86_64 system image, hardware acceleration or a
built APK (build-apk.ps1). Faster reruns: CM_EMU_KEEP=1 leaves the emulator running and prints how to reuse it
(CM_EMU_REUSE=<adb port>:<serial>). Screenshots: CM_SHOTS=<folder>.
Usage: python -u drive_emulator.py <repo>"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(REPO))
APK = REPO / "dist" / "ChannelMirror-Remote.apk"
PKG = "io.github.jorah0.cmremote"
SHOTS = os.environ.get("CM_SHOTS")


def skip(why):
    print(f"SKIPPED: {why}")
    sys.exit(0)


sdk = next((Path(p) for p in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                               Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk")
            if p and (Path(p) / "platform-tools").is_dir()), None)
if not sdk:
    skip("no Android SDK (%LOCALAPPDATA%\\Android\\Sdk)")
EMU, ADB = sdk / "emulator" / "emulator.exe", sdk / "platform-tools" / "adb.exe"
if not EMU.is_file():
    skip("the Android SDK has no emulator (sdkmanager: emulator)")
images = sorted((p for p in (sdk / "system-images").glob("android-*/*/x86_64") if (p / "system.img").is_file()
                 and p.parent.name in ("default", "google_apis")),
                key=lambda p: [int(x) for x in re.findall(r"\d+", p.parent.parent.name)])
if not images:
    skip("no x86_64 system image (android sdk install system-images/android-36/default/x86_64)")
if not APK.is_file() or not APK.with_name(APK.name + ".json").is_file():
    skip("the Android app isn't built (.\\build-apk.ps1)")
if subprocess.run([str(EMU), "-accel-check"], capture_output=True, timeout=60).returncode:
    skip("no hardware acceleration for the emulator (Windows Hypervisor Platform)")
IMAGE = images[-1]


def free(*ports):
    socks = []
    try:
        for p in ports:
            s = socket.socket()
            socks.append(s)
            s.bind(("127.0.0.1", p))
        return socks[0].getsockname()[1]
    except OSError:
        return None
    finally:
        for s in socks:
            s.close()


tmp = Path(tempfile.mkdtemp(prefix="cm_emu_"))
reuse = os.environ.get("CM_EMU_REUSE")
if reuse:
    adb_port, SERIAL = reuse.split(":", 1)
else:
    adb_port = str(free(0))  # its own adb server: other adb servers (5037) never see this emulator
    # an even console port (+1: its adb port) past 5585 - the range every adb server scans for emulators
    con = next((p for p in range(5600, 5680, 2) if free(p, p + 1)), None)
    assert con, "no free emulator port in 5600-5680"
    SERIAL = f"emulator-{con}"
ENV = {**os.environ, "ANDROID_SDK_ROOT": str(sdk), "ANDROID_HOME": str(sdk), "ANDROID_AVD_HOME": str(tmp / "avd"),
       "ANDROID_ADB_SERVER_PORT": adb_port}
emu = emu_log = None
if not reuse:
    # the AVD: written here (no avdmanager / JDK needed), a phone like a Pixel 7
    avd = tmp / "avd" / "cmtest.avd"
    avd.mkdir(parents=True)
    rel = IMAGE.relative_to(sdk)
    (tmp / "avd" / "cmtest.ini").write_text(f"avd.ini.encoding=UTF-8\npath={avd}\ntarget={rel.parts[1]}\n")
    (avd / "config.ini").write_text("\n".join([
        "avd.ini.encoding=UTF-8", f"image.sysdir.1={rel}{os.sep}", "abi.type=x86_64", "hw.cpu.arch=x86_64",
        f"tag.id={IMAGE.parent.name}", "hw.lcd.width=1080", "hw.lcd.height=2400", "hw.lcd.density=420",
        "hw.ramSize=2048", "hw.keyboard=yes", "hw.gpu.enabled=yes", "hw.gpu.mode=swiftshader_indirect",
        "disk.dataPartition.size=2G", "PlayStore.enabled=no", "hw.audioInput=no", "hw.audioOutput=no"]) + "\n")
    subprocess.run([str(ADB), "start-server"], env=ENV, capture_output=True, timeout=60)


def launch():
    """Start the emulator (cold, wiped) -> its process; its output in emulator.log."""
    global emu_log
    if emu_log:
        emu_log.close()
    emu_log = open(tmp / "emulator.log", "w")
    return subprocess.Popen([str(EMU), "-avd", "cmtest", "-port", str(con), "-no-window", "-no-audio",
                             "-no-boot-anim", "-no-snapshot", "-wipe-data", "-gpu", "swiftshader_indirect",
                             "-no-metrics"], env=ENV, stdout=emu_log, stderr=subprocess.STDOUT)


def stop_emu():
    subprocess.run([str(ADB), "-s", SERIAL, "emu", "kill"], env=ENV, capture_output=True, timeout=60)
    try:
        emu.wait(60)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(emu.pid)], capture_output=True)


if not reuse:
    emu = launch()
t_boot = time.time()

from harness import App  # noqa: E402 (after the skips: they need no app)

import numpy as np  # noqa: E402
from cmlib.selftest import FakeObs  # noqa: E402


def adb(*a, timeout=60, check=True):
    r = subprocess.run([str(ADB), "-s", SERIAL, *map(str, a)], env=ENV, capture_output=True, timeout=timeout)
    out = r.stdout.decode("utf-8", "replace")
    if check and r.returncode:
        raise AssertionError(f"adb {' '.join(map(str, a))}: {out} {r.stderr.decode('utf-8', 'replace')}")
    return out


def shell(cmd, **k):
    return adb("shell", cmd, **k)


def tone(p, hz, secs=1.0, rate=44100):
    t = np.arange(int(rate * secs)) / rate
    x = (0.3 * np.sin(2 * np.pi * hz * t) * 32767).astype("<i2")
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(rate), w.writeframes(np.stack([x, x], 1).tobytes())
    return p


# ---- the phone's screen: what Android's accessibility sees, and real input ----
def ui():
    """Every node on screen now: {text, id, cls, box (l, t, r, b)}. id = the resource id (a web screen's HTML id)."""
    raw = adb("exec-out", "uiautomator", "dump", "/dev/tty", check=False)
    raw = raw[raw.find("<?xml"):raw.rfind(">") + 1] if "<?xml" in raw else ""
    if not raw:
        return []
    out = []
    for n in ET.fromstring(raw).iter("node"):
        b = [int(x) for x in re.findall(r"\d+", n.get("bounds", ""))]
        out.append({"text": (n.get("text") or n.get("content-desc") or "").strip(),
                    "id": (n.get("resource-id") or "").split("/")[-1], "cls": n.get("class", ""),
                    "box": tuple(b) if len(b) == 4 else (0, 0, 0, 0)})
    return out


def find(nodes, text=None, id=None, cls=None, has=None):
    for n in nodes:
        if ((text is None or n["text"] == text) and (id is None or n["id"] == id) and (cls is None or n["cls"] == cls)
                and (has is None or has in n["text"]) and n["box"][2] > n["box"][0] and n["box"][3] > n["box"][1]):
            return n
    return None


def tap(n):
    assert n, "nothing to tap"
    l, t, r, b = n["box"]
    shell(f"input tap {(l + r) // 2} {(t + b) // 2}")


def type_text(s):
    assert re.fullmatch(r"[A-Za-z0-9.:#=/_-]+", s), s  # quoted for the phone's shell: '#' would start a comment
    shell(f"input text '{s}'")


def shot(name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        (Path(SHOTS) / f"emu {name}.png").write_bytes(subprocess.run(
            [str(ADB), "-s", SERIAL, "exec-out", "screencap", "-p"], env=ENV, capture_output=True, timeout=60).stdout)


# the PC: fakes and the app's settings (a temp copy)
boom, hum = tone(tmp / "boom.wav", 600), tone(tmp / "hum.wav", 220)
fake_obs = FakeObs("pw-emu")
app = App({"obs": {"password": "pw-emu", "port": fake_obs.port}})
app.obs_ports.add(fake_obs.port)
app.start()
app.root.geometry("1400x900+0+0")
seen = []  # the last screen, for a failure's message
try:
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

    page = app.tab("Phone remote")
    Rm = app.api("remote")
    app.button("Turn on", page).invoke()
    srv = Rm["state"]["server"]
    assert srv and srv.hosts == ["127.0.0.1"]

    def must(cond, secs=30, what=""):
        def look():
            seen[:] = ui()
            return cond(seen)
        if not app.wait(look, secs):
            shot("FAILED")
            raise AssertionError(f"timed out: {what} | PC status {Rm['status']()!r} | errors {app.errors[-2:]} | "
                                 f"phone shows {[(n['id'], n['text']) for n in seen if n['text'] or n['id']][:40]}")
        return seen

    # the emulator: booted (it started before the app), the release APK installed
    def booted(secs):
        return app.wait(lambda: shell("getprop sys.boot_completed", check=False).strip() == "1", secs)
    # a boot can hang (seen with other projects' emulators sharing the hypervisor): one more cold boot, then fail
    if not booted(240 - (time.time() - t_boot)) and not reuse:
        print(f"the emulator didn't boot in {time.time() - t_boot:.0f} s: starting it again")
        stop_emu()
        emu, t_boot = launch(), time.time()
        if not booted(300):
            log = tmp / "emulator.log"
            raise AssertionError("the emulator didn't boot (twice)" + (":\n" + log.read_text()[-2000:]
                                                                      if log.exists() else ""))
    elif reuse and not booted(10):
        raise AssertionError(f"CM_EMU_REUSE: {SERIAL} isn't up")
    print(f"emulator {SERIAL} ({IMAGE.parent.parent.name}, {IMAGE.parent.name}) up in {time.time() - t_boot:.0f} s, "
          f"its own adb server on port {adb_port}")
    adb("uninstall", PKG, check=False)
    assert "Success" in adb("install", APK, timeout=180)
    want = json.loads(APK.with_name(APK.name + ".json").read_text())
    dump = shell(f"dumpsys package {PKG}")
    assert f"versionCode={want['code']}" in dump and f"versionName={want['name']}" in dump, want
    shell("settings put global window_animation_scale 0; settings put global transition_animation_scale 0; "
          "settings put global animator_duration_scale 0", check=False)
    shell(f"am start -W -n {PKG}/.MainActivity")
    print(f"installed: CM Remote {want['name']} (code {want['code']}), the signed release build")

    # the first screen: an address outside the home network / Tailscale is refused, the pairing link accepted
    s = must(lambda s: find(s, cls="android.widget.EditText") and find(s, text="CONNECT"), 30, "the first screen")
    assert find(s, text="Channel Mirror Remote") and find(s, has=want["cert"][:4])  # its signing key shown
    shot("1 address")
    tap(find(s, cls="android.widget.EditText"))
    type_text("8.8.8.8:8770")
    tap(find(s, text="CONNECT"))
    s = must(lambda s: find(s, has="isn't the remote's address"), 15, "outside address refused")
    tap(find(s, cls="android.widget.EditText"))
    shell("input keycombination 113 29; input keyevent 67")  # Ctrl+A, Delete
    app.button("Pair a phone", page).invoke()
    app.pump(0.2)
    code = Rm["state"]["code"][0]
    type_text(f"10.0.2.2:{srv.port}/#pair={code}")
    tap(find(s, text="CONNECT"))
    s = must(lambda s: find(s, id="pairbtn"), 60, "the web app (from the APK) open")
    print("first screen: 8.8.8.8 refused; the pairing link typed, the remote's screen open")
    shot("2 pair")

    # pairing: the PC asks, allowed; the phone shows Connected and the Deck
    app.yes.append(True)
    n = len(app.asked)
    tap(find(s, id="pairbtn"))
    s = must(lambda s: len(Rm["devices"]) == 1 and find(s, text="Boom") and find(s, text="Hum"), 60,
             "paired, the Deck shown")
    assert app.asked[n][1] == "Pair a phone", app.asked[n:]
    assert find(s, id="conn", has="Connected") or find(s, text="Connected"), "Connected"
    print(f"paired as {Rm['devices'][0]['name']!r} (allowed on the PC); Connected; the Deck: Boom, Hum")
    shot("3 deck")

    # the Deck: a tap plays into the OBS feed
    tap(find(s, text="Boom"))
    assert app.wait(lambda: fed == ["boom.wav"], 15), fed
    # OBS: its scenes; a tap switches
    tap(find(s, text="OBS"))
    s = must(lambda s: find(s, text="BRB") and find(s, text="Main"), 30, "OBS scenes")
    shot("4 obs")
    tap(find(s, text="BRB"))
    assert app.wait(lambda: fake_obs.scene == "BRB", 15), fake_obs.scene
    print("Deck: Boom into the OBS feed; OBS: switched to BRB")

    # closed and opened again: the PC's address and the pairing kept - straight to the remote, still working
    shell(f"am force-stop {PKG}")
    shell(f"am start -W -n {PKG}/.MainActivity")
    s = must(lambda s: find(s, id="conn", has="Connected") and not find(s, cls="android.widget.EditText"), 60,
             "reopened, paired")
    tap(find(s, text="Deck"))  # it comes back on the tab last used (OBS)
    s = must(lambda s: find(s, text="Hum"), 30, "the Deck")
    tap(find(s, text="Hum"))
    assert app.wait(lambda: fed[-1:] == ["hum.wav"], 15), fed
    print("reopened: straight to the remote, still paired (Hum played)")

    # removed on the PC: the phone's next request is refused and it says so
    Rm["tree"].selection_set(Rm["devices"][0]["id"])
    app.button("Remove", page).invoke()
    assert not Rm["devices"]
    tap(find(s, text="Boom"))
    must(lambda s: find(s, has="isn't paired with this PC any more") or find(s, has="Not paired"), 30,
         "the phone told it's removed")
    shot("5 removed")
    print("removed on the PC: the phone shows it isn't paired")
finally:
    fake_obs.stop()
    if os.environ.get("CM_EMU_KEEP") and not reuse:
        print(f"emulator left running: CM_EMU_REUSE={adb_port}:{SERIAL} (stop it: set ANDROID_ADB_SERVER_PORT="
              f"{adb_port} & adb -s {SERIAL} emu kill)")
    elif not reuse:
        stop_emu()
        subprocess.run([str(ADB), "kill-server"], env=ENV, capture_output=True, timeout=60)
        emu_log.close()
saved = app.close()
assert saved["remote"]["devices"] == []
if not os.environ.get("CM_EMU_KEEP"):
    shutil.rmtree(tmp, ignore_errors=True)
print("Android app ok on an emulator: installed, refused a bad address, paired, Deck + OBS, reopened, removed")
