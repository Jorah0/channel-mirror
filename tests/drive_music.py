"""Drive the Music player tab in the whole app (PC-B, this process) with a linked PC-A (crosspc_peer.py, a second
process), on this PC only (127.0.0.1): playlists built through the UI (new / add files / add folder / rename /
duplicate / delete / move / remove / export + import .m3u8), playing (local output STUBBED: nothing is heard),
seek / pause / next / repeat, sharing to OBS bound to 127.0.0.1 - the stream read with urllib and checked to keep
coming across a song change and a pause and to decode as MP3 - the overlay and now.json, a wrong token and an old
link 404, then a song pulled from PC-A's playlists (From Channel Mirror..., fetched and checked) and played, and a
playlist sent to PC-A (accepted there -> a new playlist there). Synthetic Stream Deck / VTube Studio folders; settings
and the now-playing file in temp; Stream Deck never sent to.
Usage: python -u drive_music.py <repo>"""
import ctypes, functools, json, shutil, subprocess, sys, tempfile, threading, time, wave
import faulthandler  # never stuck: still running after CM_TEST_TIMEOUT s (default 300) -> where it is, exit
faulthandler.dump_traceback_later(int(__import__("os").environ.get("CM_TEST_TIMEOUT", "300")), exit=True)
import os
from pathlib import Path
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # default: this repo
sys.path.insert(0, REPO)
ctypes.windll.shcore.SetProcessDpiAwareness(1)
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import channel_mirror as cm
from urllib.error import HTTPError
sys.argv = sys.argv[:1]  # the app reads extra words as dropped files
HERE = Path(__file__).parent
popups, errors, names = [], [], []
for n in ("showinfo", "showwarning", "showerror", "askokcancel", "askretrycancel"):
    setattr(messagebox, n, lambda *a, _n=n, **k: popups.append((_n, a[:2])))
messagebox.askyesno = lambda *a, **k: popups.append(("askyesno", a[:2])) or True
messagebox.askyesnocancel = lambda *a, **k: True
simpledialog.askstring = lambda *a, **k: names.pop(0) if names else None
tk.Tk.report_callback_exception = lambda self, *a: errors.append(a)
picks, folder_pick, save_pick = [], [], []
filedialog.askopenfilenames = lambda **k: tuple(str(p) for p in picks)
filedialog.askdirectory = lambda **k: str(folder_pick[0]) if folder_pick else ""
filedialog.asksaveasfilename = lambda **k: str(save_pick[0]) if save_pick else ""

tmp = Path(tempfile.mkdtemp())
work = tmp / "A"
work.mkdir()


def song(p, hz, secs=3.0):
    t = np.arange(int(44100 * secs)) / 44100
    x = (0.3 * np.sin(2 * np.pi * hz * t) * 32767).astype("<i2")
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(44100), w.writeframes(np.stack([x, x], 1).tobytes())
    return p


def make_sd(root, name):
    pg = root / "ProfilesV3" / f"{name}.sdProfile" / "Profiles" / "PAGE1" / "manifest.json"
    pg.parent.mkdir(parents=True)
    (pg.parents[2] / "manifest.json").write_text(json.dumps({
        "Device": {"Model": "20GBA9901", "UUID": f"@(1)[4057/128/{name.upper()}]"}, "Name": name,
        "Pages": {"Current": "page1", "Default": "x", "Pages": ["page1"]}}))
    pg.write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": {"4,2": cm.sd_stop_key()}}]}))


def make_vts(root, model):
    m = root / "StreamingAssets" / "Live2DModels" / model / f"{model}.vtube.json"
    m.parent.mkdir(parents=True)
    m.write_text(json.dumps({"Name": model, "ModelID": f"id-{model}", "Hotkeys": []}))
    (root / "StreamingAssets" / "Backgrounds").mkdir()
    return root / "StreamingAssets"


# PC-A: a playlist "A Mix" with one song of its own
a_song = song(work / "a music" / "a_song_from_pc_a.wav", 330, 2.0)
make_sd(work / "A_SD", "A-Main")
make_vts(work / "A_VTS", "Wolf")
(work / "a_settings.json").write_text(json.dumps({"theme": "dark", "sd_autosend": False, "music": {
    "playlists": [{"name": "A Mix", "songs": [{"path": str(a_song), "title": ""}]}]}}))
peer_proc = subprocess.Popen([sys.executable, "-u", str(HERE / "crosspc_peer.py"), REPO, str(work)])

# PC-B (here)
s1, s2 = song(tmp / "songs" / "first_track.wav", 440), song(tmp / "songs" / "second_track.wav", 550)
s3 = song(tmp / "songs" / "folder" / "03 - third track.wav", 660)
s4 = song(tmp / "songs" / "extra.wav", 770, 1.0)
make_sd(tmp / "B_SD", "B-Main")
cm.SD_DIR, cm.SD_BACKUPS = tmp / "B_SD", tmp / "B_backups"
cm.VTS_ASSETS, cm.vts_assets = make_vts(tmp / "B_VTS", "Fox"), lambda: []
cm.sd_push = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send to Stream Deck"))
cm.sd_start, cm.sd_running, cm.sd_connected = (lambda: None), (lambda: False), (lambda: set())
cm.SETTINGS = tmp / "b_settings.json"
cm.SETTINGS.write_text(json.dumps({"theme": "light", "sd_autosend": False}))
cm.LINK_INBOX = tmp / "B_Incoming"
cm.MUSIC_NOW = tmp / "Now playing.txt"
cm.LinkServer = functools.partial(cm.LinkServer, host="127.0.0.1")
cm.link_lan_ip = lambda: "127.0.0.1"  # the music server binds here too
cm.link_public_network = lambda: False
cm.link_handover_serve = lambda on_link, port=None: None
cm.peer_find = lambda peer, me, addrs=None, timeout=2.0: None  # no broadcasts onto the real network
outs = []


class FakeOut:  # this PC's speakers, stubbed: nothing is heard
    def __init__(self, device=""):
        self.device, self.blocks, self.loud, self.closed = device, 0, 0, False
        outs.append(self)

    def write(self, b):
        self.blocks += 1
        self.loud += any(b)

    def close(self):
        self.closed = True


cm.MusicOut = FakeOut
held = {}
real = {n: getattr(cm, n) for n in ("link_tab", "music_tab", "ui_linked_bar")}
bars = {}
cm.link_tab = lambda *a, **k: held.setdefault("link", real["link_tab"](*a, **k))
cm.music_tab = lambda *a, **k: held.setdefault("music", real["music_tab"](*a, **k))
cm.ui_linked_bar = lambda page, *a, **k: bars.setdefault(str(page), real["ui_linked_bar"](page, *a, **k))


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def btn(w, text):
    return next(b for b in walk(w) if isinstance(b, ttk.Button) and b.cget("text") == text)


def a_log():
    try:
        return [json.loads(x) for x in (work / "a_log.jsonl").read_text(encoding="utf-8").splitlines()]
    except OSError:
        return []


def a_state():
    try:
        return json.loads((work / "a_state.json").read_text())
    except (OSError, ValueError):
        return {}


def wait(cond, secs=20, what=""):
    r, t0 = tk._default_root, time.time()
    while time.time() - t0 < secs:
        r.update()
        if cond():
            return True
        time.sleep(0.03)
    raise AssertionError(f"timed out: {what} | errors {errors[-3:]} popups {popups[-3:]} A log {a_log()[-4:]}")


def pause_for(secs):
    end = time.time() + secs
    while time.time() < end:
        tk._default_root.update()
        time.sleep(0.02)


chunks, stop_reading = [], threading.Event()


def reader(url):
    """OBS stand-in: reads the stream, noting when each piece arrived."""
    try:
        with cm.link_noproxy().open(url, timeout=15) as r:
            chunks.append((time.perf_counter(), r.headers["Content-Type"], b""))
            while not stop_reading.is_set():
                b = r.read(1024)
                if not b:
                    break
                chunks.append((time.perf_counter(), len(b), b))
    except Exception as e:
        chunks.append((time.perf_counter(), "error", repr(e)))
    chunks.append((time.perf_counter(), "end", b""))


def get(url):
    with cm.link_noproxy().open(url, timeout=10) as r:
        return r.status, r.headers["Content-Type"], r.read()


def status_of(url):
    try:
        return get(url)[0]
    except HTTPError as e:
        return e.code


def tour():
    r = tk._default_root
    try:
        r.geometry("1300x900+0+0")
        nb = next(w for w in walk(r) if isinstance(w, ttk.Notebook))
        tabs = {nb.tab(t, "text"): r.nametowidget(t) for t in nb.tabs()}
        order = [nb.tab(t, "text") for t in nb.tabs()]
        assert order[-4:] == ["Link", "Linked computers", "Phone remote", "Setup"] and "Music player" in order, order
        mus, M = tabs["Music player"], held["music"]
        nb.select(mus)
        r.update()
        st, v, eng, tree = M["state"], M["vars"], M["engine"], M["tree"]
        assert any(isinstance(w, ttk.Label) and w.cget("text") == " Working on: This PC " for w in walk(mus))
        assert tree.winfo_height() > 60, tree.winfo_height()

        # playlists through the UI
        names[:] = ["Road Trip"]
        btn(mus, "New").invoke()
        assert M["name"]() == "Road Trip"
        picks[:] = [s1, s2, tmp / "songs" / "notes.txt"]
        btn(mus, "Add files...").invoke()
        folder_pick[:] = [s3.parent]
        btn(mus, "Add folder...").invoke()
        picks[:] = [s4, s1]  # s1 again: not twice
        btn(mus, "Add files...").invoke()
        rows = [tree.item(i, "values")[1] for i in tree.get_children()]
        assert rows == ["First Track", "Second Track", "Third Track", "Extra"], rows
        tree.selection_set("3")
        btn(mus, "Remove").invoke()
        tree.selection_set("1")
        btn(mus, "Move up").invoke()
        rows = [tree.item(i, "values")[1] for i in tree.get_children()]
        assert rows == ["Second Track", "First Track", "Third Track"] and tree.selection() == ("0",), rows
        btn(mus, "Move down").invoke()
        assert [tree.item(i, "values")[1] for i in tree.get_children()][:2] == ["First Track", "Second Track"]
        names[:] = ["Drive"]
        btn(mus, "Rename").invoke()
        btn(mus, "Duplicate").invoke()
        assert [p["name"] for p in M["lists"]][-2:] == ["Drive", "Drive copy"] and M["name"]() == "Drive copy"
        btn(mus, "Delete").invoke()
        assert [p["name"] for p in M["lists"]][-1] == "Drive" and M["name"]() == "Drive"
        save_pick[:] = [tmp / "out" / "Drive export.m3u8"]
        (tmp / "out").mkdir()
        btn(mus, "Export .m3u...").invoke()
        text = save_pick[0].read_text(encoding="utf-8").splitlines()
        assert text[0] == "#EXTM3U" and "#EXTINF:-1,First Track" in text and str(s1) in text, text
        picks[:] = [save_pick[0]]
        btn(mus, "Import .m3u...").invoke()
        assert M["name"]() == "Drive export" and len(M["files"]()) == 3 and M["files"]()[0] == s1
        assert M["songs"]() == [s1, s2, s3]  # an imported playlist's songs aren't offered to linked computers
        ptv = M["playlists"]
        drive_i = next(i for i in ptv.get_children() if ptv.item(i, "text").startswith("Drive  "))
        ptv.selection_set(drive_i)
        r.update()
        assert M["name"]() == "Drive"
        print("playlists: new / add files + folder / remove / move / rename / duplicate / delete / export / import ok:",
              [p["name"] for p in M["lists"]])

        # a song's file is looked at once - not on every redraw - and again when songs are added / imported or the
        # tab is shown again (a file deleted meanwhile turns red then)
        gone = tmp / "songs" / "gone soon.wav"
        shutil.copy2(s1, gone)
        picks[:] = [gone]
        btn(mus, "Add files...").invoke()
        other = next(i for i in ptv.get_children() if i != drive_i)
        real_is_file, looked = Path.is_file, []
        Path.is_file = lambda p: (looked.append(Path(p)), real_is_file(p))[1]
        try:
            for _ in range(3):  # redraws: another playlist and back
                ptv.selection_set(other)
                r.update()
                ptv.selection_set(drive_i)
                r.update()
            assert not [p for p in looked if p in (s1, s2, s3, gone)], looked[:5]
        finally:
            Path.is_file = real_is_file
        gone.unlink()
        ptv.selection_set(other), r.update(), ptv.selection_set(drive_i), r.update()
        row = next(i for i in tree.get_children() if tree.item(i, "values")[1] == "Gone Soon")
        assert "missing" not in tree.item(row, "tags")  # not looked at again yet
        nb.select(tabs["Setup"]), r.update(), nb.select(mus), r.update()  # the tab shown again
        row = next(i for i in tree.get_children() if tree.item(i, "values")[1] == "Gone Soon")
        assert "missing" in tree.item(row, "tags"), tree.item(row, "tags")
        tree.selection_set(row)
        btn(mus, "Remove").invoke()
        assert len(M["files"]()) == 3
        print("music: song files looked at once (not on each redraw), again when the tab is shown: a deleted one red")

        # play (heard here through the stubbed output), share, and listen like OBS does
        v["repeat"].set("Repeat off")
        tree.selection_set("0")
        btn(mus, "Play").invoke()
        assert eng.song == s1 and v["now"].get().startswith("First Track") and outs and not outs[-1].closed
        assert cm.MUSIC_NOW.read_text(encoding="utf-8") == "First Track"
        v["port"].set("0")
        btn(mus, "Start sharing").invoke()
        stream = v["stream"].get()
        assert stream.startswith("http://127.0.0.1:") and stream.endswith("/stream.mp3") and st["server"], stream
        base = stream.rsplit("/", 1)[0]
        assert v["overlay"].get() == base + "/now"
        threading.Thread(target=reader, args=(stream,), daemon=True).start()
        wait(lambda: len(chunks) > 5, 10, "stream data")
        assert chunks[0][1] == "audio/mpeg", chunks[0]
        t_start = time.perf_counter()
        # seek into the first song: it ends sooner, then the second plays by itself
        st["drag"] = True
        v["pos"].set(2.0)
        next(w for w in walk(mus) if isinstance(w, ttk.Scale) and str(w.cget("variable")) == str(v["pos"])) \
            .event_generate("<ButtonRelease-1>")
        r.update()
        assert eng.position() >= 2.0, eng.position()
        wait(lambda: eng.song == s2, 6, "second song by itself")
        assert outs[-1].loud > 20, outs[-1].loud
        s, kind, body = get(base + "/now.json")
        assert kind == "application/json" and json.loads(body) == {"title": "Second Track", "playlist": "Drive",
                                                                    "playing": True}, body
        assert cm.MUSIC_NOW.read_text(encoding="utf-8") == "Second Track"
        s, kind, body = get(base + "/now")
        assert kind.startswith("text/html") and b"now.json" in body and b"transparent" in body
        print("play, seek, next song by itself; now.json:", json.loads(get(base + "/now.json")[2]))
        pause_for(0.6)
        btn(mus, "Pause").invoke()
        assert eng.paused and outs[-1].closed  # not heard while paused (the device is let go)
        pos = eng.position()
        assert json.loads(get(base + "/now.json")[2])["playing"] is False
        pause_for(1.5)
        assert eng.position() == pos
        btn(mus, "Play").invoke()  # carries on
        assert not eng.paused and not outs[-1].closed and eng.song == s2
        pause_for(0.5)
        btn(mus, "Next").invoke()
        assert eng.song == s3 and v["now"].get().startswith("Third Track")
        pause_for(0.5)
        btn(mus, "Previous").invoke()
        assert eng.song == s2
        btn(mus, "Next").invoke()
        v["vol"].set(50)
        assert eng.volume == 50
        devs = cm.music_devices()
        if devs:
            v["device"].set(devs[0])
            assert outs[-1].device == devs[0] and not outs[-1].closed and outs[-2].closed
        v["hear"].set(False)
        assert outs[-1].closed
        v["hear"].set(True)
        wait(lambda: v["now"].get() == "Nothing playing", 8, "the last song ends (repeat off)")
        assert eng.song is None and cm.MUSIC_NOW.read_text(encoding="utf-8") == ""
        assert outs[-1].closed
        pause_for(1.0)  # stopped: the stream still goes on (silence)
        t_end = time.perf_counter()
        data = [c for c in chunks if isinstance(c[1], int)]
        times = [c[0] for c in data if t_start <= c[0] <= t_end]
        gaps = max(b - a for a, b in zip(times, times[1:]))
        got = sum(c[1] for c in data if t_start <= c[0] <= t_end)
        rate = got / (t_end - t_start)
        assert gaps < 1.0 and 15000 < rate < 40000, (gaps, rate)  # 192 kbit/s = 24000 bytes a second, no stops
        print(f"stream kept coming across seek, a song change, pause, next / previous and the end: "
              f"{t_end - t_start:.1f} s, longest wait {gaps:.2f} s, {rate:.0f} bytes/s")

        # wrong token / other paths: 404; a new link cuts the old one off; stop sharing
        tok = base.rsplit("/", 1)[1]
        root_url = base.split("/music/")[0]
        for bad in (f"{root_url}/music/{'0' * 32}/stream.mp3", f"{root_url}/", f"{root_url}/music/{tok}/x",
                    f"{root_url}/music/{tok.upper()}/now"):
            assert status_of(bad) == 404, bad
        btn(mus, "New link").invoke()
        wait(lambda: chunks[-1][1] in ("end", "error"), 10, "old listener cut off")
        assert status_of(base + "/now.json") == 404 and v["stream"].get() != stream
        assert status_of(v["overlay"].get() + ".json") == 200
        mp3 = tmp / "heard.mp3"
        mp3.write_bytes(b"".join(c[2] for c in data))
        pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels:"
                             "format=duration", "-of", "json", str(mp3)], capture_output=True, text=True)
        info = json.loads(pr.stdout)
        assert info["streams"][0]["codec_name"] == "mp3" and info["streams"][0]["sample_rate"] == "48000"
        assert float(info["format"]["duration"]) > (t_end - t_start) * 0.8, info
        print("wrong token / other paths 404; New link cut the old one off; what OBS got decodes as MP3:",
              info["streams"][0], info["format"]["duration"])
        new_stream = v["stream"].get()
        btn(mus, "Stop sharing").invoke()
        assert not st["server"] and v["stream"].get() == ""
        try:
            get(new_stream)
            raise AssertionError("still shared")
        except OSError:
            pass
        btn(mus, "Start sharing").invoke()  # same token as before: the links OBS has keep working
        assert v["stream"].get().rsplit("/", 2)[1] == new_stream.rsplit("/", 2)[1]
        print("stop / start sharing ok (the link stays the same)")

        # a song from the linked PC-A's playlists, and a playlist sent to PC-A
        lk, hub = held["link"], held["link"]["hub"]
        wait(lambda: (work / "a_pair.txt").exists(), 60, "PC-A started")
        lk["vars"]["port"].set("0")
        lk["vars"]["device"].set("PC-B")
        lk["toggle"]()
        lk["vars"]["link_to"].set((work / "a_pair.txt").read_text())
        btn(tabs["Linked computers"], "Link").invoke()
        wait(lambda: hub["peers"]() and any(p["name"] == "PC-B" for p in a_state().get("peers", [])), 40, "paired")
        names[:] = ["From A"]
        btn(mus, "New").invoke()
        lib = {}

        def drive_library():
            w = next((x for x in walk(r) if isinstance(x, tk.Toplevel)
                      and x.title() == "Pick from Channel Mirror"), None)
            if w is None:
                return r.after(100, drive_library)
            if "set" not in lib:
                next(x for x in walk(w) if isinstance(x, ttk.Combobox)).set("PC-A")
                lib["set"] = True
            tv = next(x for x in walk(w) if isinstance(x, ttk.Treeview))
            grp = next((g for g in tv.get_children() if tv.item(g, "text") == "Music playlists"), None)
            if grp is None or not tv.get_children(grp):
                return r.after(100, drive_library)
            lib["rows"] = [tv.item(i, "text") for i in tv.get_children(grp)]
            tv.selection_set(tv.get_children(grp)[0])
            btn(w, "Add").invoke()
        r.after(200, drive_library)
        btn(bars[str(mus)]["bar"], "From Channel Mirror...").invoke()
        assert lib.get("rows") == ["a_song_from_pc_a.wav"], lib
        got_files = M["files"]()
        assert len(got_files) == 1 and got_files[0].is_relative_to(cm.LINK_INBOX / "Received"), got_files
        assert got_files[0].read_bytes() == a_song.read_bytes()
        assert [tree.item(i, "values")[1] for i in tree.get_children()] == ["A Song From Pc A"]
        tree.selection_set("0")
        btn(mus, "Play").invoke()
        assert eng.song == got_files[0]
        assert json.loads(get(v["overlay"].get() + ".json")[2])["title"] == "A Song From Pc A"
        print("a song from PC-A's playlist: listed, fetched (signed, checked) into", got_files[0].parent.name,
              "and played")
        btn(mus, "Stop").invoke()
        ptv.selection_set(drive_i)
        r.update()
        btn(bars[str(mus)]["bar"], "Send there").invoke()
        wait(lambda: "accepted on PC-A" in (hub["activity"].get(hub["peers"]()[0]["id"]) or ""), 60,
             "playlist accepted on PC-A")
        prop = [x for x in a_log() if "proposal" in x]
        assert prop and "Music player" in prop[-1]["proposal"] and any("As a new playlist: Drive" in ln
                                                                        for ln in prop[-1]["lines"]), prop[-1:]
        print("playlist sent to PC-A, shown there as:", prop[-1]["proposal"], prop[-1]["lines"])
        assert not errors, errors
    except Exception as e:
        import traceback
        traceback.print_exc()
        for x in errors:
            print("earlier error:", "".join(traceback.format_exception(*x)) if isinstance(x, tuple) else x)
        errors.append(e)
    stop_reading.set()
    (work / "a_quit").write_text("1")
    r.tk.call(r.protocol("WM_DELETE_WINDOW"))


real_mainloop = tk.Tk.mainloop
tk.Tk.mainloop = lambda self, n=0: (self.after(1500, tour), real_mainloop(self, n))[1]
cm.gui()
try:
    peer_proc.wait(40)
except subprocess.TimeoutExpired:
    peer_proc.kill()
assert not errors, errors
assert not [x for x in a_log() if "error" in x], [x for x in a_log() if "error" in x]
saved = json.loads(cm.SETTINGS.read_text())["music"]
assert [p["name"] for p in saved["playlists"]] == ["Playlist 1", "Drive", "Drive export", "From A"], saved
assert saved["share"] is True and len(saved["token"]) == 32 and saved["repeat"] == "off" and saved["volume"] == 50
a_saved = json.loads((work / "a_settings.json").read_text())["music"]
drive_a = next(p for p in a_saved["playlists"] if p["name"] == "Drive")
assert len(drive_a["songs"]) == 3 and all(Path(s["path"]).is_relative_to(work / "A_Incoming" / "Received")
                                           for s in drive_a["songs"]), drive_a
print("settings kept (playlists, link token, sharing on, repeat, volume); PC-A has the playlist 'Drive':",
      [Path(s["path"]).name for s in drive_a["songs"]])
shutil.rmtree(tmp, ignore_errors=True)
print("drive music ok")
