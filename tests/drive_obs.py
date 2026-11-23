"""The OBS tab in the whole app (PC-B, this process, through harness.App) with a linked PC-A (crosspc_peer.py, a second
process), on this PC only (127.0.0.1). OBS is a FAKE obs-websocket server on each PC (cmlib.selftest.FakeObs) - the
real OBS is never touched (harness.safe_obs). Covers: connecting (a wrong password refused, then the right one),
scenes (switched here, and changed in OBS showing by itself), sources shown / hidden, the mixer (mute, volume), media
(play / pause / restart / stop), streaming / recording / virtual camera, Feeds (the music stream and the soundboard
feed: links, Copy, Add to OBS as Media / Browser Sources - and the fake OBS really hearing the soundboard feed carry a
sound played from the soundboard and from a file), files to OBS (into a source, as a new source, a fake file refused),
then PC-A's OBS from here: refused while PC-A hasn't allowed this PC ("May control OBS" off), working once allowed
there (scenes, streaming, mute, Add to OBS), files sent for its OBS (accepted -> into its OBS; declined -> nothing),
refused again when switched off, and back to this PC's OBS. Settings kept on close.
Usage: python -u drive_obs.py <repo>"""
import json
import time
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from harness import REPO, App, walk

import numpy as np
from tkinter import ttk
from cmlib.selftest import FakeObs

HERE = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp(prefix="cm_obs_"))
work = tmp / "A"
work.mkdir()


def tone(p, hz, secs=1.0, rate=44100):
    t = np.arange(int(rate * secs)) / rate
    x = (0.4 * np.sin(2 * np.pi * hz * t) * 32767).astype("<i2")
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(rate), w.writeframes(np.stack([x, x], 1).tobytes())
    return p


def png(p):
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
    return p


# PC-A: a Stream Deck folder, VTube Studio, and its own (fake) OBS with the password "pw-a"
pg = work / "A_SD" / "ProfilesV3" / "A-Main.sdProfile" / "Profiles" / "PAGE1" / "manifest.json"
pg.parent.mkdir(parents=True)
(pg.parents[2] / "manifest.json").write_text(json.dumps({
    "Device": {"Model": "20GBA9901", "UUID": "@(1)[4057/128/AMAIN]"}, "Name": "A-Main",
    "Pages": {"Current": "page1", "Default": "x", "Pages": ["page1"]}}))
pg.write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": {}}]}))
(work / "A_VTS" / "StreamingAssets" / "Backgrounds").mkdir(parents=True)
(work / "a_settings.json").write_text(json.dumps({"theme": "dark", "sd_autosend": False}))
(work / "a_obs.json").write_text(json.dumps({"password": "pw-a"}))
peer_proc = subprocess.Popen([sys.executable, "-u", str(HERE / "crosspc_peer.py"), REPO, str(work)])

boom, hum, jingle = tone(tmp / "boom.wav", 600, 1.5), tone(tmp / "hum.wav", 220, 1.0), tone(tmp / "jingle.wav", 330)
logo, banner, fake_png = png(tmp / "logo.png"), png(tmp / "banner.png"), tmp / "not a picture.png"
fake_png.write_bytes(b"MZ" + bytes(100))
fake = FakeObs("pw-b")  # PC-B's OBS
app = App({"obs": {"password": "pw-old"}})  # kept in plain text by an older version
app.obs_ports.add(fake.port)
cm = app.cm
app.start()
on_disk = json.loads(cm.SETTINGS.read_text())["obs"]["password"]  # sealed at once (DPAPI), still the same password
assert on_disk.startswith("dpapi:") and "pw-old" not in on_disk and cm.secret_read(on_disk) == "pw-old", on_disk
assert app.api("obs")["vars"]["password"].get() == "pw-old"
print("an old plain OBS password: sealed in the settings at start, still filled in")
app.root.geometry("1400x900+0+0")
assert app.tabs()[-6:] == ["Music player", "OBS", "Transcribe", "Link", "Linked computers", "Setup"], app.tabs()
page = app.tab("OBS")
O = app.api("obs")
v, st = O["vars"], O["state"]


def a_state():
    for _ in range(25):  # PC-A rewrites the file all the time: a read caught mid-write is tried again
        try:
            return json.loads((work / "a_state.json").read_text())
        except (OSError, ValueError):
            time.sleep(0.02)
    return {}


def a_log():
    try:
        return [json.loads(x) for x in (work / "a_log.jsonl").read_text(encoding="utf-8").splitlines()]
    except OSError:
        return []


def must(cond, secs=10, what=""):
    if not app.wait(cond, secs):
        raise AssertionError(f"timed out: {what} | status {O['status']()!r} | conn {v['conn'].get()!r} | "
                             f"link {app.api('link')['status']()!r} | errors {app.errors[-2:]} | A log {a_log()[-3:]}")


def scene_names():
    return [b.cget("text") for b in O["scenes"].winfo_children()]


def scene_btn(n):
    return next(b for b in O["scenes"].winfo_children() if b.cget("text") == n)


def frame(title):
    return next(w for w in walk(page) if isinstance(w, ttk.Labelframe) and str(w.cget("text")).startswith(title))


try:
    assert any(isinstance(w, ttk.Label) and w.cget("text") == " Working on: This PC " for w in walk(page))
    assert any(isinstance(w, ttk.Label) and w.cget("text") == " Controlling: OBS on this PC " for w in walk(page))

    # connect: a wrong password is refused (and it stops trying), then the right one
    v["port"].set(str(fake.port))
    v["password"].set("wrong")
    app.button("Connect", page).invoke()
    must(lambda: v["conn"].get().startswith("Wrong password"), 10, "wrong password refused")
    must(lambda: st["client"] is None and app.button("Connect", page), 5, "stopped trying")
    assert not scene_names()
    v["password"].set("pw-b")
    app.button("Connect", page).invoke()
    must(lambda: scene_names() == ["Main", "BRB"], 10, "scenes")
    assert v["conn"].get().startswith("Connected to OBS 30.2.0") and app.button("Disconnect", page)
    print("connect: wrong password refused ->", v["conn"].get())

    # scenes: switched here; changed in OBS shows by itself
    assert scene_btn("Main").cget("style") == "Accent.TButton" and scene_btn("BRB").cget("style") == "TButton"
    scene_btn("BRB").invoke()
    must(lambda: fake.scene == "BRB" and scene_btn("BRB").cget("style") == "Accent.TButton", 10, "BRB on air")
    fake.scene = "Main"
    fake.event("CurrentProgramSceneChanged", {"sceneName": "Main"})
    must(lambda: scene_btn("Main").cget("style") == "Accent.TButton", 5, "OBS's own scene change shown")
    print("scenes: switched to BRB here; switched back in OBS shows here by itself")

    # sources of the scene: show / hide
    src = O["sources"]
    must(lambda: [src.item(i, "values")[0] for i in src.get_children()] == ["Camera", "Clip", "Logo"], 5, "sources")
    assert frame("Sources in Main")
    src.selection_set("1")
    app.button("Show / hide", page).invoke()
    must(lambda: not fake.items["Main"][0]["sceneItemEnabled"] and src.item("1", "values")[1] == "hidden", 5, "hide")
    x, y, w, h = src.bbox("1")
    app.click(src, x + w // 2, y + h // 2, double=True)  # double-click: shown again
    must(lambda: fake.items["Main"][0]["sceneItemEnabled"] and src.item("1", "values")[1] == "shown", 5, "show")
    print("sources: Camera hidden (Show / hide) and shown again (double-click)")

    # audio mixer: mute, volume
    mix = O["mixer"]
    assert mix.get_children() == ("Mic", "Desktop Audio", "Clip"), mix.get_children()  # Logo / Camera: no sound
    mix.selection_set("Mic")
    app.pump(0.1)
    app.button("Mute / unmute", page).invoke()
    must(lambda: fake.inputs["Mic"]["muted"] and mix.item("Mic", "values")[1] == "muted", 5, "muted")
    v["vol"].set(50)
    O["volume"].event_generate("<ButtonRelease-1>")
    must(lambda: fake.inputs["Mic"]["mul"] == 0.25 and mix.item("Mic", "values")[2] == "50%", 5, "volume")
    app.button("Mute / unmute", page).invoke()
    must(lambda: not fake.inputs["Mic"]["muted"], 5, "unmuted")
    print("mixer: Mic muted, set to 50% (OBS x0.25), unmuted")

    # media sources
    assert v["media"].get() == "Clip"
    mf = frame("Media sources")
    for a, want in (("Pause", "paused"), ("Play", "playing"), ("Restart", "playing"), ("Stop", "stopped")):
        n = len(fake.requests)
        app.button(a, mf).invoke()
        must(lambda: ("TriggerMediaInputAction", {"inputName": "Clip", "mediaAction":
                                                  f"OBS_WEBSOCKET_MEDIA_INPUT_ACTION_{a.upper()}"}) in fake.requests[n:]
             and fake.inputs["Clip"]["media"] == want, 5, a)
    must(lambda: any(isinstance(w, ttk.Label) and w.cget("text") == "stopped" for w in walk(mf)), 5, "media state")
    print("media: pause / play / restart / stop, state shown")

    # streaming / recording / virtual camera, with their live state
    for k, text, live in (("stream", "streaming", "LIVE"), ("record", "recording", "REC"),
                          ("vcam", "virtual camera", "ON")):
        app.button(f"Start {text}", page).invoke()
        must(lambda: fake.outputs[k] and O["outputs"][k][0].cget("text") == live
             and O["outputs"][k][1].cget("text") == f"Stop {text}", 5, f"start {k}")
        app.button(f"Stop {text}", page).invoke()
        must(lambda: not fake.outputs[k] and O["outputs"][k][0].cget("text") == "off", 5, f"stop {k}")
    print("live: streaming / recording / virtual camera started and stopped, state shown")

    # feeds: the music stream and the soundboard feed - links, Copy, Add to OBS
    ff = frame("Feeds for OBS")
    app.button("Copy", ff).invoke()
    assert "Start sharing in the Music player tab" in O["status"]()
    mus = app.tab("Music player")
    M = app.api("music")
    M["vars"]["port"].set("0")
    app.button("Start sharing", mus).invoke()
    music_url, overlay_url = M["vars"]["stream"].get(), M["vars"]["overlay"].get()
    page = app.tab("OBS")
    v["feed_port"].set("0")
    app.button("Start soundboard feed", ff).invoke()
    feed_url = v["feed"].get()
    assert feed_url.startswith("http://127.0.0.1:") and feed_url.endswith("/stream.mp3") and st["srv"], feed_url
    copies = [b for b in walk(ff) if isinstance(b, ttk.Button) and b.cget("text") == "Copy"]
    for b, want in zip(copies, (music_url, feed_url)):
        b.invoke()
        assert app.root.clipboard_get() == want
    assert v["scene_to"].get() == "Main"
    for text, name, kind, key, url in (("Music", "Channel Mirror music", "ffmpeg_source", "input", music_url),
                                       ("Overlay", "Channel Mirror now playing", "browser_source", "url", overlay_url),
                                       ("Soundboard", "Channel Mirror soundboard", "ffmpeg_source", "input", feed_url)):
        app.button(text, ff).invoke()
        must(lambda: name in fake.inputs and fake.inputs[name]["kind"] == kind
             and fake.inputs[name]["settings"][key] == url, 5, f"add {text}")
        assert any(i["sourceName"] == name for i in fake.items["Main"])
    print("feeds: links copied; music stream, overlay and soundboard feed added to OBS's scene Main")

    # the soundboard feed carries the sound into OBS (the fake OBS is listening to it)
    heard = fake.heard
    must(lambda: len(heard.get("Channel Mirror soundboard", b"")) > 40000, 15, "OBS hearing the feed")
    quiet_until = len(heard["Channel Mirror soundboard"])
    sb = app.tab("Stream Deck soundboard")
    app.picks.append([boom])
    app.button("Add files...", sb).invoke()
    page = app.tab("OBS")
    sound_cb = next(c for c in walk(ff) if isinstance(c, ttk.Combobox) and str(c.cget("textvariable")) == str(v["sound"]))
    app.button("Play", ff).invoke()  # nothing picked yet: Play says so
    assert "Pick a sound first" in O["status"](), O["status"]()
    sound_cb.set("boom.wav")
    app.button("Play", ff).invoke()
    must(lambda: "Playing boom.wav in the soundboard feed" in O["status"](), 5, "played")
    app.picks.append([hum])
    app.button("Play a file in the feed...", ff).invoke()
    must(lambda: len(heard["Channel Mirror soundboard"]) > quiet_until + 120000, 20, "more of the feed heard")
    mp3 = tmp / "heard.mp3"
    mp3.write_bytes(bytes(heard["Channel Mirror soundboard"]))
    pcm = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "s16le", "-ac", "1", "-ar",
                                        "8000", "-"], capture_output=True).stdout, "<i2").astype(float)
    secs = [np.sqrt(np.mean(pcm[i:i + 800] ** 2)) for i in range(0, len(pcm) - 800, 800)]  # 0.1 s each
    first_loud = next(i for i, x in enumerate(secs) if x > 3000)
    assert first_loud >= 10 and max(secs[:first_loud - 2]) < 50, secs[:first_loud]  # silence first, then the sound
    assert sum(x > 3000 for x in secs) >= 10, secs  # over a second of sound in OBS
    app.button("Stop", ff).invoke()
    must(lambda: not O["feed"].playing(), 5, "sounds stopped")
    print(f"soundboard feed: OBS heard {len(secs) / 10:.1f} s - silence, then {sum(x > 3000 for x in secs) / 10:.1f} s "
          "of the sounds (from the soundboard list and from a file); Stop ends them")

    # files to OBS on this PC: into a source; as a new source; a fake file refused
    fl = frame("Files to OBS")
    v["into"].set("Logo")
    app.picks.append([logo])
    app.button("Send files to OBS...", fl).invoke()
    must(lambda: fake.inputs["Logo"]["settings"].get("file") == str(logo.resolve()), 5, "into Logo")
    v["into"].set("(a new source in the scene)")
    v["scene_to"].set("BRB")
    app.picks.append([jingle])
    app.button("Send files to OBS...", fl).invoke()
    must(lambda: "Jingle" in [i["sourceName"] for i in fake.items["BRB"]], 5, "new source")
    assert fake.inputs["Jingle"]["settings"]["local_file"] == str(jingle.resolve())
    v["into"].set("Logo")
    app.picks.append([fake_png])
    app.button("Send files to OBS...", fl).invoke()
    assert "Can't send that" in O["status"]() and "isn't a .png" in O["status"](), O["status"]()
    v["scene_to"].set("Main")
    print("files to OBS here: logo.png into Logo, jingle.wav as a new source in BRB - a renamed program refused")

    # PC-A's OBS from here
    lk = app.api("link")
    hub = lk["hub"]
    must(lambda: (work / "a_pair.txt").exists(), 60, "PC-A started")
    lk["vars"]["port"].set("0")
    lk["vars"]["device"].set("PC-B")
    lk["toggle"]()
    lk["vars"]["link_to"].set((work / "a_pair.txt").read_text())
    app.button("Link", app.tab("Linked computers")).invoke()
    must(lambda: hub["peers"]() and any(p["name"] == "PC-B" for p in a_state().get("peers", [])), 40, "paired")
    must(lambda: a_state().get("obs", {}).get("trusted") == [], 10, "PC-A's OBS up")
    page = app.tab("OBS")
    O["bar"]["who"].set("PC-A")
    app.button("Control its OBS", page).invoke()
    assert any(isinstance(w, ttk.Label) and w.cget("text") == " Controlling: OBS on PC-A "
               and w.cget("style") == "Remote.TLabel" for w in walk(page))
    must(lambda: "PC-A: PC-B may not control OBS here" in O["status"](), 20, "refused while not allowed")
    assert not scene_names()
    print("PC-A's OBS while not allowed there:", O["status"]())
    (work / "a_obs_trust").write_text("1")  # on PC-A: Linked computers tab, "May control OBS" for PC-B
    must(lambda: a_state().get("obs", {}).get("trusted") == ["PC-B"], 20, "allowed on PC-A")
    must(lambda: scene_names() == ["Main", "BRB"], 15, "PC-A's scenes")
    scene_btn("BRB").invoke()
    must(lambda: a_state()["obs"]["scene"] == "BRB" and scene_btn("BRB").cget("style") == "Accent.TButton", 15,
         "PC-A's scene switched")
    app.button("Start streaming", page).invoke()
    must(lambda: a_state()["obs"]["outputs"]["stream"] and O["outputs"]["stream"][0].cget("text") == "LIVE", 15,
         "PC-A streaming")
    app.button("Stop streaming", page).invoke()
    must(lambda: not a_state()["obs"]["outputs"]["stream"], 15, "PC-A stopped")
    must(lambda: "Mic" in O["mixer"].get_children(), 10, "PC-A's mixer")
    O["mixer"].selection_set("Mic")
    app.pump(0.1)
    app.button("Mute / unmute", page).invoke()
    must(lambda: any(r[0] == "SetInputMute" for r in map(json.loads, (work / "a_obs_log.jsonl").read_text()
                                                         .splitlines())), 15, "PC-A's Mic muted")
    v["scene_to"].set("Main")
    app.button("Soundboard", frame("Feeds for OBS")).invoke()
    must(lambda: (a_state()["obs"]["inputs"].get("Channel Mirror soundboard") or {}).get("input") == feed_url, 15,
         "this PC's feed added to PC-A's OBS")
    print("PC-A's OBS once allowed: scene BRB, streaming on / off, Mic muted, this PC's soundboard feed added")

    # a soundboard sound played into PC-A's soundboard feed from here, end to end: the sound goes to PC-A's soundboard
    # (Send there, accepted there), PC-A's OBS listens to PC-A's own feed, Play here -> PC-A's OBS hears the sound
    (work / "answers.json").write_text("[true]")
    sbp = app.tab("Stream Deck soundboard")
    app.button("Send there", sbp).invoke()
    pid = hub["peers"]()[0]["id"]
    must(lambda: "accepted on PC-A" in (hub["activity"].get(pid) or ""), 40, "boom.wav accepted on PC-A's soundboard")
    assert any("Stream Deck soundboard" in x.get("proposal", "") for x in a_log())
    must(lambda: a_state()["obs"].get("feed", "").endswith("/stream.mp3"), 20, "PC-A's soundboard feed on")
    (work / "a_feed_listen").write_text("1")  # PC-A's OBS: a Media Source on PC-A's own feed
    must(lambda: a_state()["obs"]["heard"].get("A soundboard feed", 0) > 40000, 20, "PC-A's OBS hearing its feed")
    quiet_until = a_state()["obs"]["heard"]["A soundboard feed"]
    page = app.tab("OBS")
    ff = frame("Feeds for OBS")
    must(lambda: "boom.wav" in (st["state"].get("sounds") or []), 15, "PC-A's soundboard sounds listed here")
    sound_cb.set("boom.wav")
    app.button("Play", ff).invoke()
    must(lambda: "Playing boom.wav in the soundboard feed" in O["status"]() and "PC-A" in O["status"](), 15,
         "played on PC-A")
    must(lambda: a_state()["obs"]["heard"]["A soundboard feed"] > quiet_until + 120000, 25, "more of PC-A's feed heard")
    (work / "a_heard_dump").write_text("1")
    must(lambda: not (work / "a_heard_dump").exists() and (work / "a_heard.mp3").exists(), 10, "what PC-A's OBS heard")
    pcm = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(work / "a_heard.mp3"), "-f", "s16le", "-ac",
                                        "1", "-ar", "8000", "-"], capture_output=True).stdout, "<i2").astype(float)
    secs = [np.sqrt(np.mean(pcm[i:i + 800] ** 2)) for i in range(0, len(pcm) - 800, 800)]  # 0.1 s each
    first_loud = next(i for i, x in enumerate(secs) if x > 3000)
    assert first_loud >= 10 and max(secs[:first_loud - 2]) < 50, secs[:first_loud]  # silence first, then the sound
    assert sum(x > 3000 for x in secs) >= 10, secs  # over a second of boom.wav in PC-A's OBS
    print(f"soundboard sound from here into PC-A's feed: PC-A's OBS heard silence, then "
          f"{sum(x > 3000 for x in secs) / 10:.1f} s of boom.wav")

    # files for PC-A's OBS: asked there - accepted, then declined
    fl = frame("Files to OBS")
    (work / "answers.json").write_text("[true]")
    v["into"].set("(a new source in the scene)")
    app.picks.append([banner])
    app.button("Send files to OBS...", fl).invoke()
    pid = hub["peers"]()[0]["id"]
    must(lambda: "accepted on PC-A" in (hub["activity"].get(pid) or ""), 40, "accepted on PC-A")
    must(lambda: "Banner" in a_state()["obs"]["inputs"], 10, "Banner in PC-A's OBS")
    got = a_state()["obs"]["inputs"]["Banner"]
    assert Path(got["file"]).is_relative_to(work / "A_Incoming" / "Received"), got  # the copy kept there
    prop = [x for x in a_log() if "proposal" in x]
    assert prop and "for OBS" in prop[-1]["proposal"] and "As new source(s) named 'Banner' in the OBS scene 'Main'" in \
        prop[-1]["lines"], prop[-1:]
    n_inputs = len(a_state()["obs"]["inputs"])
    (work / "answers.json").write_text("[false]")
    app.picks.append([jingle])
    app.button("Send files to OBS...", fl).invoke()
    must(lambda: "declined on PC-A" in (hub["activity"].get(pid) or ""), 40, "declined on PC-A")
    app.pump(0.5)
    assert len(a_state()["obs"]["inputs"]) == n_inputs
    print("files for PC-A's OBS: accepted there -> a new source showing", Path(got["file"]).name, "; declined -> nothing")

    # switched off there: refused again; then this PC's OBS again
    (work / "a_obs_trust").write_text("0")
    must(lambda: a_state()["obs"]["trusted"] == [], 20, "not allowed on PC-A")
    must(lambda: "may not control OBS here" in O["status"](), 15, "refused again")
    app.button("This PC's OBS", page).invoke()
    must(lambda: scene_names() == ["Main", "BRB"] and scene_btn("Main").cget("style") == "Accent.TButton", 10,
         "this PC's OBS again")
    assert any(isinstance(w, ttk.Label) and w.cget("text") == " Controlling: OBS on this PC " for w in walk(page))
    print("switched off on PC-A: refused again; back on this PC's OBS")
finally:
    (work / "a_quit").write_text("1")

try:
    peer_proc.wait(40)
except subprocess.TimeoutExpired:
    peer_proc.kill()
assert not [x for x in a_log() if "error" in x], [x for x in a_log() if "error" in x]
saved = app.close()["obs"]
fake.stop()
assert saved["port"] == fake.port and saved["connect"] is True, saved
assert saved["password"].startswith("dpapi:") and cm.secret_read(saved["password"]) == "pw-b", saved  # sealed
assert saved["feed_share"] is True and len(saved["feed_token"]) == 32 and saved["feed_token"] in feed_url, saved
assert not any(r[0] not in ("GetSceneList", "SetCurrentProgramScene", "GetSceneItemList", "SetSceneItemEnabled",
                            "GetInputList", "GetInputMute", "GetInputVolume", "SetInputMute", "SetInputVolume",
                            "GetMediaInputStatus", "TriggerMediaInputAction", "GetStreamStatus", "GetRecordStatus",
                            "GetVirtualCamStatus", "StartStream", "StopStream", "StartRecord", "StopRecord",
                            "StartVirtualCam", "StopVirtualCam", "CreateInput", "GetInputSettings", "SetInputSettings")
               for r in fake.requests)
print("settings kept: port, password, connected, feed on with its link")
shutil.rmtree(tmp, ignore_errors=True)
print("drive obs ok")
