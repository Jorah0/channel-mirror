"""Linked computers, end to end, with two real Channel Mirror apps on this PC only (127.0.0.1, different ports):
PC-B is the whole app in this process (driven here); PC-A is the whole app in a second process
(crosspc_peer.py: answers its questions from a file, logs what it shows and does). Synthetic Stream Deck folders
and VTube Studio installs only; settings in temp files; Stream Deck is never sent to (its sd_push writes into the
synthetic folder); no screen is recorded (the recorder runs a stand-in for ffmpeg); nothing pops up.
Covers: pairing (accepted there), the This PC banner on every tool tab, Send there from five tabs (accepted / declined,
the answer shown back here), opening PC-A's Stream Deck (devices, its keys), remote key edits applied there only
after its accept (not on decline) through its editor and on to its Stream Deck, keys copied both ways (key mover
across PCs; folders' allowlist), PC-A's VTube Studio backgrounds, Record / Stop there with the file coming back,
recordings saved to VTube Studio backgrounds here and on PC-A, the From Channel Mirror library (here and PC-A),
reconnecting after an address change, renew, expiry, unlink."""
import ctypes, functools, json, re, shutil, subprocess, sys, tempfile, threading, time, wave
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
sys.argv = sys.argv[:1]  # the app reads extra words as dropped files
HERE = Path(__file__).parent
popups, errors, b_answers, b_asked = [], [], [], []
for n in ("showinfo", "showwarning", "showerror", "askokcancel", "askretrycancel"):
    setattr(messagebox, n, lambda *a, _n=n, **k: popups.append((_n, a[:2])))
messagebox.askyesno = lambda *a, **k: popups.append(("askyesno", a[:2])) or True
messagebox.askyesnocancel = lambda *a, **k: True
tk.Tk.report_callback_exception = lambda self, *a: errors.append(a)
picks = []
filedialog.askopenfilenames = lambda **k: tuple(str(p) for p in picks)
simpledialog.askstring = lambda *a, **k: "Renamed"
cm.ui_proposal = lambda parent, title, lines: (b_asked.append((title, lines)), b_answers.pop(0) if b_answers else True)[1]

tmp = Path(tempfile.mkdtemp())
work = tmp / "A"
work.mkdir()


def wav(p, n=800):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000), w.writeframes(np.zeros(n, "<i2").tobytes())
    return p


def png(p):
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
    return p


def make_sd(root, name, keys):
    pg = root / "ProfilesV3" / f"{name}.sdProfile" / "Profiles" / "PAGE1" / "manifest.json"
    pg.parent.mkdir(parents=True)
    (pg.parents[2] / "manifest.json").write_text(json.dumps({
        "Device": {"Model": "20GBA9901", "UUID": f"@(1)[4057/128/{name.upper()}]"}, "Name": name,
        "Pages": {"Current": "page1", "Default": "x", "Pages": ["page1"]}}))
    pg.write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": keys}]}))


def make_vts(root, model):
    m = root / "StreamingAssets" / "Live2DModels" / model / f"{model}.vtube.json"
    m.parent.mkdir(parents=True)
    m.write_text(json.dumps({"Name": model, "ModelID": f"id-{model}", "Hotkeys": []}))
    (root / "StreamingAssets" / "Backgrounds").mkdir()
    png(root / "StreamingAssets" / "Backgrounds" / f"{model} sky.png")
    return root / "StreamingAssets"


# PC-A: its own sounds, Stream Deck profile "A-Main" (a sound on key 1,1), VTube Studio model "Wolf"
a_snd = wav(work / "a boom.wav")
make_sd(work / "A_SD", "A-Main", {"0,0": cm.sd_play(a_snd, "A Boom"), "4,2": cm.sd_stop_key()})
make_vts(work / "A_VTS", "Wolf")
(work / "a_settings.json").write_text(json.dumps({"theme": "dark", "sd_autosend": False, "close_to_taskbar": False}))
peer_proc = subprocess.Popen([sys.executable, "-u", str(HERE / "crosspc_peer.py"), REPO, str(work)])
# PC-B (here): profile "B-Main": a sound key, and a key that opens a program (never allowed over the link)
b_snd, snd2, bg = wav(tmp / "b drum.wav"), wav(tmp / "b clap.wav"), png(tmp / "b stars.png")
opener = {"ActionID": cm.sd_uid(), "Name": "Open", "UUID": "com.elgato.streamdeck.system.open",
          "Settings": {"path": "C:\\Windows\\System32\\calc.exe"}, "States": [{"Title": "Calc"}]}
make_sd(tmp / "B_SD", "B-Main", {"0,0": cm.sd_play(b_snd, "B Drum"), "1,1": opener, "4,2": cm.sd_stop_key(),
                                  "2,0": {"ActionID": cm.sd_uid(), "Name": "Folder", "UUID": cm.SD_FOLDER,
                                          "Settings": {"ProfileUUID": "fold1"},
                                          "States": [{"Image": "Images/F.png", "Title": "Folder"}]}})
b_prof = tmp / "B_SD" / "ProfilesV3" / "B-Main.sdProfile" / "Profiles"  # a folder key with an icon; inside it a sound
for sub in ("PAGE1/Images", "FOLD1/Images"):
    (b_prof / sub).mkdir(parents=True)
png(b_prof / "PAGE1" / "Images" / "F.png")
png(b_prof / "FOLD1" / "Images" / "S.png")
(b_prof / "FOLD1" / "manifest.json").write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": {
    "1,0": dict(cm.sd_play(b_snd, "In Fold"), States=[{"Image": "Images/S.png", "Title": "In Fold"}])
}}]}))
sendto_dir = tmp / "send to"  # what Explorer's Send to > Channel Mirror (linked computers) hands over: two sounds
sendto_dir.mkdir()
cm.SD_DIR, cm.SD_BACKUPS = tmp / "B_SD", tmp / "B_backups"
b_vts = make_vts(tmp / "B_VTS", "Fox")
cm.VTS_ASSETS, cm.vts_assets = b_vts, lambda: []
pushed = []
cm.sd_push = lambda writes, folders, sd_dir=None, backups=None: (
    pushed.append(sorted(writes)), cm.sd_save(writes, folders, tmp / "B_SD", tmp / "B_backups"))[1]
cm.sd_start, cm.sd_running, cm.sd_connected = (lambda: None), (lambda: False), (lambda: set())
cm.SETTINGS = tmp / "b_settings.json"
cm.SETTINGS.write_text(json.dumps({"theme": "light", "sd_autosend": False, "close_to_taskbar": False, "recorder": {"folder": str(tmp / "rec")}}))
cm.LINK_INBOX = tmp / "B_Incoming"
cm.LinkServer = functools.partial(cm.LinkServer, host="127.0.0.1")
cm.link_lan_ip = lambda: "127.0.0.1"
cm.link_public_network = lambda: False
handovers = []  # the open app's hand-over (Send to while it's open): called here like the hand-over server does
cm.link_handover_serve = lambda on_link, port=None: handovers.append(on_link)
real_find = cm.peer_find
cm.peer_find = lambda peer, me, addrs=None, timeout=2.0: None  # no broadcasts onto the real network
FAKE_REC = "import sys; sys.stdin.read(1); open(sys.argv[1], 'wb').write(b'\\0\\0\\0\\x18ftypmp42' + bytes(4000))"
cm.rec_command = lambda area, fps, out, mouse=True: [sys.executable, "-c", FAKE_REC, str(out)]  # no screen grab
held, bars, windows = {}, {}, {}
real = {n: getattr(cm, n) for n in ("link_tab", "sd_editor_tab", "ui_linked_bar", "ui_remote_deck", "ui_remote_vts",
                                     "recorder_tab", "vts_tab", "ui_library", "import_tab", "music_tab",
                                     "ui_send_linked")}
cm.link_tab = lambda *a, **k: held.setdefault("link", real["link_tab"](*a, **k))
cm.sd_editor_tab = lambda *a, **k: held.setdefault("editor", real["sd_editor_tab"](*a, **k))
cm.recorder_tab = lambda *a, **k: held.setdefault("rec", real["recorder_tab"](*a, **k))
cm.vts_tab = lambda *a, **k: held.setdefault("vts", real["vts_tab"](*a, **k))
cm.import_tab = lambda *a, **k: held.setdefault("imp", real["import_tab"](*a, **k))
cm.music_tab = lambda *a, **k: held.setdefault("music", real["music_tab"](*a, **k))
sendtos = []  # the Send to > Channel Mirror (linked computers) windows
cm.ui_send_linked = lambda *a, **k: sendtos.append(real["ui_send_linked"](*a, **k)) or sendtos[-1]
popped = []
tk.Menu.tk_popup = lambda m, x, y, entry="": popped.append(m)  # right-click menus: built, not shown


def menu_item(menu, label):
    for i in range(menu.index("end") + 1):
        if menu.type(i) == "command" and menu.entrycget(i, "label") == label:
            return menu.invoke(i)
    raise AssertionError(f"no menu item {label!r}")
cm.ui_linked_bar = lambda page, *a, **k: bars.setdefault(str(page), real["ui_linked_bar"](page, *a, **k))
cm.ui_remote_deck = lambda *a, **k: windows.setdefault("deck", real["ui_remote_deck"](*a, **k))
cm.ui_remote_vts = lambda *a, **k: windows.setdefault("vts", real["ui_remote_vts"](*a, **k))
lib_picks = []
cm.ui_library = lambda parent, hub, exts=None, title="": [p for p in lib_picks if not exts or p.suffix in exts]
real_library = real["ui_library"]


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def btn(w, text):
    return next(b for b in walk(w) if isinstance(b, ttk.Button) and b.cget("text") == text)


def a_state():
    try:
        return json.loads((work / "a_state.json").read_text())
    except (OSError, ValueError):
        return {}


def a_keys():
    return next((v for k, v in a_state().get("keys", {}).items() if k.startswith("A-Main") and k.endswith("|Page 1")), {})


def a_log():
    try:
        return [json.loads(x) for x in (work / "a_log.jsonl").read_text(encoding="utf-8").splitlines()]
    except OSError:
        return []


def a_answers(*xs):
    (work / "answers.tmp").write_text(json.dumps(list(xs)))
    (work / "answers.tmp").replace(work / "answers.json")  # never read half-written


def wait(cond, secs=30, what=""):
    r, t0 = tk._default_root, time.time()
    while time.time() - t0 < secs:
        r.update()
        if cond():
            return True
        time.sleep(0.05)
    raise AssertionError(f"timed out: {what} | errors {errors[-3:]} popups {popups[-3:]} A log {a_log()[-4:]}")


def tour():
    r = tk._default_root
    try:
        nb = next(w for w in walk(r) if isinstance(w, ttk.Notebook))
        tabs = {nb.tab(t, "text"): r.nametowidget(t) for t in nb.tabs()}
        lk, hub, ed = held["link"], held["link"]["hub"], held["editor"]
        bar = {name: bars[str(tabs[name])] for name in ("Channel Mirror", "Stream Deck soundboard", "Stream Deck editor",
                                                        "Import to folders", "Key mover", "Screen recorder",
                                                        "VTube Studio backgrounds")}
        # every tool tab shows which computer it works on, and the first-time hint
        for name in bar:
            assert any(isinstance(w, ttk.Label) and w.cget("text") == " Working on: This PC " and
                       w.cget("style") == "Local.TLabel" for w in walk(tabs[name])), name
        assert "No linked computers yet" in bar["Channel Mirror"]["note"].cget("text")
        print("banner + first-time hint on every tool tab ok")
        # started from Send to > Channel Mirror (linked computers): the chooser opens with its files (no PC linked yet)
        wait(lambda: sendtos, 20, "Send to chooser at start")
        first = sendtos[0]
        assert "No linked computers yet" in first["status"].cget("text")
        assert any(str(x.cget("text")).startswith("3 file(s): b stars.png, s1.wav, s2.wav") for x in walk(first["win"])
                   if isinstance(x, ttk.Label))
        btn(first["win"], "Send").invoke()
        assert "Pick a linked computer" in first["status"].cget("text") and first["win"].winfo_exists()
        btn(first["win"], "Cancel").invoke()
        print("Send to (linked computers) at start: the chooser lists its files; nothing sent without a linked PC")

        # pair: B pastes A's pairing link; A's user accepts
        wait(lambda: (work / "a_pair.txt").exists(), 60, "PC-A started")
        lk["vars"]["port"].set("0")
        lk["vars"]["device"].set("PC-B")
        lk["toggle"]()
        lk["vars"]["link_to"].set((work / "a_pair.txt").read_text())
        btn(tabs["Linked computers"], "Link").invoke()
        wait(lambda: hub["peers"]() and any(p["name"] == "PC-B" for p in a_state().get("peers", [])), 40, "paired")
        pa = hub["peers"]()[0]
        assert pa["name"] == "PC-A" and cm.peer_days_left(pa) == cm.PEER_DAYS

        def kept(f):  # the pair secrets in a settings file on disk: sealed (DPAPI), readable by this Windows user
            try:
                ps = json.loads(f.read_text())["link"]["peers"]
            except (OSError, ValueError, KeyError):  # not written yet
                return {}
            assert all(p_["secret"].startswith("dpapi:") for p_ in ps), ps
            return {p_["name"]: cm.secret_read(p_["secret"]) for p_ in ps}
        # saved at once on both PCs (a crash now doesn't lose the link), sealed
        wait(lambda: kept(work / "a_settings.json").get("PC-B") == pa["secret"], 10, "pairing saved on PC-A")
        assert kept(cm.SETTINGS) == {"PC-A": pa["secret"]}
        assert any("wants to link" in str(x.get("asked", "")) for x in a_log())  # asked on PC-A first
        wait(lambda: lk["tree"].exists(pa["id"]), 10, "listed")
        wait(lambda: "online" in lk["tree"].item(pa["id"], "values")[3] or "linked" in lk["tree"].item(pa["id"], "values")[3])
        assert "(30 days)" in lk["tree"].item(pa["id"], "values")[2]
        wait(lambda: "PC-A" in bar["Channel Mirror"]["who"].get())
        print("paired (accepted on PC-A), linked for 30 days:", lk["tree"].item(pa["id"], "values"))
        # the Linked computers tab: its Stream Decks and models, and a tool opened already pointed at it
        home = tabs["Linked computers"]
        lk["tree"].selection_set(pa["id"])
        btn(home, "Its Stream Decks").invoke()
        devl = next(x for x in walk(home) if isinstance(x, ttk.Label) and str(x.cget("text")).startswith(("Asking",
                                                                                                        "Stream Decks on")))
        wait(lambda: "Stream Decks on PC-A" in devl.cget("text"), 30, "its decks")
        assert "A-Main" in devl.cget("text") and "Wolf" in devl.cget("text"), devl.cget("text")
        btn(home, "Soundboard: send there").invoke()
        assert nb.tab(nb.select(), "text") == "Stream Deck soundboard" and bar["Stream Deck soundboard"]["who"].get() == "PC-A"
        print("Linked computers tab: its decks / models, jump to a tool pointed at it ok:", devl.cget("text"))

        # Send there from five tabs: each lands as a proposal on PC-A; the answer comes back here
        def send_from(name, add, files, expect, answer=True):
            n0 = len([x for x in a_log() if "answered" in x])
            a_answers(answer)
            if add:
                lib_picks[:] = files
                btn(bar[name]["bar"], "From Channel Mirror...").invoke()
            elif files:
                lib_picks[:] = files
            btn(bar[name]["bar"], "Send there").invoke()
            wait(lambda: len([x for x in a_log() if "answered" in x]) > n0, 40, f"{name}: PC-A asked")
            prop = [x for x in a_log() if "proposal" in x][-1]
            assert expect in prop["proposal"] + " ".join(prop["lines"]), prop
            word = "accepted" if answer else "declined"
            wait(lambda: f"{word} on PC-A" in bar[name]["note"].cget("text"), 20, f"{name}: {word} shown here")
            return prop
        send_from("Channel Mirror", True, [b_snd], "Channel Mirror")
        prop = send_from("Stream Deck soundboard", True, [snd2], "soundboard")
        assert any("sound(s) with their keys" in x for x in prop["lines"])
        send_from("Import to folders", True, [snd2], "Import to folders")
        prop = send_from("VTube Studio backgrounds", True, [bg], "VTube Studio")
        rec_file = tmp / "made.mp4"
        rec_file.write_bytes(b"\0\0\0\x18ftypmp42" + bytes(500))
        send_from("Screen recorder", False, [rec_file], "Just keep the files")
        send_from("Channel Mirror", False, [], "Channel Mirror", answer=False)
        assert not [x for x in a_log() if "error" in x], a_log()
        print("Send there from 5 tabs ok; accepted / declined shown back here:", bar["Channel Mirror"]["note"].cget("text"))
        # what can't go is refused up front, by name
        lib_picks[:] = [tmp / "b stars.png"]
        btn(bar["Stream Deck soundboard"]["bar"], "From Channel Mirror...").invoke()  # not a sound: not added
        fake = tmp / "fake.wav"
        fake.write_bytes(b"MZ" + bytes(100))
        vt = held["vts"]
        vt["files"].append(fake)  # slipped into a list somehow: still refused before sending
        btn(bar["VTube Studio backgrounds"]["bar"], "Send there").invoke()
        wait(lambda: "not sent" in bar["VTube Studio backgrounds"]["note"].cget("text"), 20, "fake refused")
        assert "fake.wav" in bar["VTube Studio backgrounds"]["note"].cget("text")
        vt["files"].remove(fake)
        print("a wrong file is refused before sending:", bar["VTube Studio backgrounds"]["note"].cget("text"))

        # PC-A's Stream Deck: open it, see its devices and keys; stage changes; declined = nothing changes there
        btn(bar["Stream Deck editor"]["bar"], "Open its Stream Deck...").invoke()
        wait(lambda: "deck" in windows, 30, "remote deck opened")
        w = windows["deck"]
        banner = next(x for x in walk(w["win"]) if isinstance(x, ttk.Label) and x.cget("style") == "Remote.TLabel")
        assert "PC-A (linked until" in banner.cget("text"), banner.cget("text")
        assert any("A-Main" in str(x.cget("text")) for x in walk(w["win"]) if isinstance(x, ttk.Label))  # its decks
        before = a_keys()
        assert before == {"0,0": "A Boom|Sound", "4,2": "STOP|Stop audio"}, before

        def stage_and_send(answer):
            w["R"]["sel"][:] = ["1,0"]
            picks[:] = [b_snd]
            btn(w["win"], "Sounds on key...").invoke()
            w["R"]["sel"][:] = ["0,0"]
            btn(w["win"], "Rename key...").invoke()
            assert len(w["ops"]) == 2
            n0 = len([x for x in a_log() if "answered" in x])
            a_answers(answer)
            next(b for b in walk(w["win"]) if isinstance(b, ttk.Button) and b.cget("text").startswith("Send 2")).invoke()
            wait(lambda: len([x for x in a_log() if "answered" in x]) > n0, 40, "edit asked on PC-A")
            return [x for x in a_log() if "proposal" in x][-1]
        prop = stage_and_send(False)
        assert prop["lines"][0].startswith("2 key(s) on A-Main") and prop["lines"][0].endswith("Page 1:"), prop
        wait(lambda: "declined on PC-A" in hub["activity"].get(pa["id"], ""), 20, "decline reported")
        time.sleep(1)
        assert a_keys() == before and not [x for x in a_log() if "pushed" in x]
        print("remote edit declined on PC-A: nothing changed there")
        prop = stage_and_send(True)
        wait(lambda: a_keys().get("1,0"), 30, "edit applied on PC-A")
        keys = a_keys()
        assert keys["0,0"].startswith("Renamed|") and keys["1,0"].endswith("|Sound"), keys
        wait(lambda: [x for x in a_log() if "pushed" in x], 30, "sent to PC-A's Stream Deck")
        wait(lambda: a_state()["status"].startswith("Sent 1 page(s) to Stream Deck"), 30, "PC-A says it was sent")
        print("remote edit accepted on PC-A: applied by its editor and sent to its Stream Deck:", keys)

        # key mover across PCs: B's key -> PC-A (accepted there); PC-A's key -> here (its file comes too), undo
        w["L"]["prof"].set(next(x for x in ed["profiles"]() if "B-Main" in x))
        wait(lambda: w["L"]["page"].get())
        w["L"]["sel"][:] = ["1,1"]  # the program-opening key: never goes over the link
        btn(w["win"], "Copy to PC-A >").invoke()
        assert "Can't send that" in w["status"].cget("text") and "Open" in w["status"].cget("text"), w["status"].cget("text")
        w["L"]["sel"][:] = ["0,0"]
        w["R"]["sel"][:] = ["3,0"]
        btn(w["win"], "Copy to PC-A >").invoke()
        assert w["ops"], w["status"].cget("text")
        a_answers(True)
        next(b for b in walk(w["win"]) if isinstance(b, ttk.Button) and b.cget("text").startswith("Send 1")).invoke()
        try:
            wait(lambda: a_keys().get("3,0"), 30, "key copied to PC-A")
        except AssertionError:
            print("STATUS", w["status"].cget("text"), "| ACT", hub["activity"])
            raise
        assert a_keys()["3,0"] == "B Drum|Sound"
        btn(w["win"], "Refresh").invoke()
        b_page = ed["pages"](w["L"]["prof"].get())[0][1]
        w["R"]["sel"][:] = ["0,0"]
        w["L"]["sel"][:] = ["4,0"]
        btn(w["win"], "< Copy here").invoke()
        wait(lambda: ed["keys"](b_page).get("4,0"), 30, "key copied here")
        got = cm.sd_sounds(ed["keys"](b_page)["4,0"])[0]["Settings"]["path"]
        assert Path(got).is_file() and Path(got).is_relative_to(cm.LINK_INBOX / "Received") and \
            Path(got).read_bytes() == a_snd.read_bytes(), got
        ed["undo"]()
        assert not ed["keys"](b_page).get("4,0")  # one undoable change here
        print("key mover across PCs ok (to PC-A after its accept; from PC-A with its sound; undo; Open refused)")

        # PC-A's VTube Studio: its models and backgrounds; send one, placed there once accepted
        btn(bar["VTube Studio backgrounds"]["bar"], "Open its VTube Studio...").invoke()
        wait(lambda: "vts" in windows, 30, "remote VTS opened")
        v = windows["vts"]
        assert v["model"].get() == "Wolf"
        v["add"]([bg])
        a_answers(True)
        v["send"]()
        wait(lambda: (work / "A_VTS" / "StreamingAssets" / "Backgrounds" / "b stars.png").exists(), 30, "bg on PC-A")
        print("PC-A's VTube Studio backgrounds ok")

        # Record / Stop there: started on PC-A after its accept; the file comes back here (accepted here)
        n_b = len(b_asked)
        a_answers(True)
        btn(bar["Screen recorder"]["bar"], "Record there").invoke()
        wait(lambda: [x for x in a_log() if x.get("recording") == "start"], 30, "recording on PC-A")
        a_answers(True)
        btn(bar["Screen recorder"]["bar"], "Stop there").invoke()
        wait(lambda: len(b_asked) > n_b, 40, "recording offered back")
        wait(lambda: list((cm.LINK_INBOX / "Received").rglob("A_rec*.mp4")), 20, "recording kept here")
        print("Record / Stop on PC-A; the recording came back:", b_asked[-1][0])

        # the recorder's "Recordings go to": VTube Studio backgrounds here, and on PC-A
        rv = held["rec"]["vars"]
        rv["dest"].set(cm.REC_DEST[1])
        rv["to_vts"].set(True)
        held["rec"]["start"]()
        wait(lambda: held["rec"]["state"]["proc"] is not None)
        held["rec"]["stop"]()
        wait(lambda: list((b_vts / "Backgrounds").glob("*.mp4")), 30, "recording in VTS backgrounds here")
        wait(lambda: any(f.suffix == ".mp4" for f in held["vts"]["files"]), 20, "in the VTube Studio tab too")
        rv["to_vts"].set(False)
        rv["dest"].set(cm.REC_PEER + "PC-A")
        a_answers(True)
        held["rec"]["start"]()
        wait(lambda: held["rec"]["state"]["proc"] is not None)
        held["rec"]["stop"]()
        wait(lambda: len(list((work / "A_VTS" / "StreamingAssets" / "Backgrounds").glob("*.mp4"))) == 1, 40,
             "recording in PC-A's VTS backgrounds")
        print("recordings to VTube Studio backgrounds here and on PC-A ok")

        # the From Channel Mirror library: this PC's groups, and PC-A's (fetched and checked)
        groups = hub["library"]()
        assert {p.name for p in groups["VTube Studio backgrounds"]} >= {"Fox sky.png"}
        items = cm.library_items(groups, cm.LINK_AUDIO)
        assert ("Sounds on Stream Deck keys", b_snd, True) in items and all(p.suffix == ".wav" for _, p, _ in items)
        remote = {}
        hub["run"](lambda: cm.peer_library(pa, hub["me"]()), lambda r_: remote.update(r=r_))
        wait(lambda: "r" in remote, 30, "PC-A's library")
        assert not isinstance(remote["r"], Exception), remote
        pick = next(x for x in remote["r"]["Sounds on Stream Deck keys"] if x["name"] == "a boom.wav")
        dst = tmp / "fetched a boom.wav"
        got = {}
        hub["run"](lambda: cm.peer_download(pa, hub["me"](), pick["token"], dst), lambda r_: got.update(r=r_))
        wait(lambda: "r" in got, 30, "fetched")
        assert dst.read_bytes() == a_snd.read_bytes()
        print("library: this PC's groups and PC-A's (fetched, signed) ok")

        # the Link tab's Send files... (to the tab that fits them there) and Send again
        lk["tree"].selection_set(pa["id"])
        for text in ("Send files...", "Send again"):
            n0 = len([x for x in a_log() if "answered" in x])
            picks[:] = [bg]
            a_answers(True)
            btn(tabs["Linked computers"], text).invoke()
            wait(lambda: len([x for x in a_log() if "answered" in x]) > n0, 30, text)
            assert "VTube Studio backgrounds" in [x for x in a_log() if "proposal" in x][-1]["proposal"]
        print("Link tab: Send files... and Send again ok")

        def answered():
            return len([x for x in a_log() if "answered" in x])

        # Explorer's Send to > Channel Mirror (linked computers) while the app is open: handed over, a chooser here
        n0 = answered()
        threading.Thread(target=handovers[0], args=(f"{cm.LINK_TO_PEER}\n{sendto_dir}\n{bg}",)).start()
        wait(lambda: len(sendtos) > 1, 15, "chooser from a hand-over")
        sw = sendtos[-1]
        assert sw["who"].get() == "PC-A (127.0.0.1)" and sw["to"].get() == cm.LINK_TARGETS["mirror"], sw["to"].get()  # mixed
        sw["to"].set(cm.LINK_TARGETS["import"])
        a_answers(True)
        btn(sw["win"], "Send").invoke()
        assert not sw["win"].winfo_exists()
        wait(lambda: answered() > n0, 40, "Send to: asked on PC-A")
        prop = [x for x in a_log() if "proposal" in x][-1]
        assert prop["lines"][0].startswith("2 file(s) for Stream Deck keys (Import to folders): s1.wav, s2.wav"), prop
        assert any("1 file(s) of another type left out" in x[2] for x in hub["log"])
        print("Send to (linked computers) while open: handed over; 2 sounds to PC-A's Import tab, the picture left out")

        # right-click "Send to PC-A" on the tabs' file lists: the selected files, with that tab's proposal
        lib_picks[:] = [b_snd]
        btn(bars[str(tabs["Music player"])]["bar"], "From Channel Mirror...").invoke()
        rec_rows = [i for i in held["rec"]["list"].get_children() if Path(i).is_file()]
        sb_tree = next(x for x in walk(tabs["Stream Deck soundboard"]) if isinstance(x, ttk.Treeview))
        for tab, tree, row, expect in (
                ("Stream Deck soundboard", sb_tree, sb_tree.get_children()[0], "Stream Deck soundboard"),
                ("Import to folders", held["imp"]["list"], "0", "Import to folders"),
                ("VTube Studio backgrounds", held["vts"]["list"], "0", "VTube Studio backgrounds"),
                ("Screen recorder", held["rec"]["list"], rec_rows[0], "Just keep the files"),
                ("Music player", held["music"]["tree"], "0", "Music player")):
            nb.select(tabs[tab])
            r.update()
            tree.selection_set(())
            tree.see(row)
            r.update()
            x, y, w_, h = tree.bbox(row)
            tree.event_generate("<Button-3>", x=x + 5, y=y + h // 2)
            r.update()
            assert tree.selection() == (row,), (tab, tree.selection())
            n0 = answered()
            a_answers(True)
            menu_item(popped[-1], "Send to PC-A")
            wait(lambda: answered() > n0, 40, f"right-click send from {tab}")
            prop = [x for x in a_log() if "proposal" in x][-1]
            assert expect in prop["proposal"] and prop["lines"][0].startswith("1 file(s)"), (tab, prop)
        print("right-click Send to PC-A: soundboard, import, VTube Studio, recordings, music lists - each accepted there")

        # key mover across PCs, Move: a folder key (its icon; a sound inside with its own icon) - declined: it stays
        # here; accepted: applied there with both icons, then taken away here (one undo)
        b_page = ed["pages"](w["L"]["prof"].get())[0][1]
        assert ed["keys"](b_page).get("2,0")

        def move(answer):
            w["L"]["sel"][:] = ["2,0"]
            w["R"]["sel"][:] = ["2,1"]
            btn(w["win"], "Move to PC-A >").invoke()
            assert "1 key(s) to move there" in w["status"].cget("text"), w["status"].cget("text")
            n0 = answered()
            a_answers(answer)
            next(b for b in walk(w["win"]) if isinstance(b, ttk.Button) and b.cget("text").startswith("Send 1")).invoke()
            wait(lambda: answered() > n0, 40, "move asked on PC-A")
            return [x for x in a_log() if "proposal" in x][-1]
        prop = move(False)
        wait(lambda: "declined on PC-A" in hub["activity"].get(pa["id"], ""), 20, "move declined")
        r.update()
        time.sleep(0.5)
        r.update()
        assert ed["keys"](b_page).get("2,0") and not a_keys().get("2,1")
        prop = move(True)
        assert any("1 folder page(s), 2 icon(s)" in x for x in prop["lines"]), prop
        wait(lambda: a_keys().get("2,1"), 30, "moved key on PC-A")
        wait(lambda: not ed["keys"](b_page).get("2,0"), 20, "moved key taken away here")
        assert any("moved 1 key(s) there" in x[2] for x in hub["log"])
        a_prof = work / "A_SD" / "ProfilesV3" / "A-Main.sdProfile" / "Profiles"
        wait(lambda: (a_prof / "PAGE1" / "Images" / "F.png").is_file() and [
            p for p in a_prof.glob("*/Images/S.png") if p.parents[1].name != "PAGE1"], 30, "both icons on PC-A")
        ed["undo"]()
        assert ed["keys"](b_page).get("2,0")  # the taking away is one undo here
        print("key mover Move to PC-A: declined -> kept here; accepted -> on PC-A with the folder's icons too, "
              "then taken away here (undoable)")

        # a soundboard sent with "install it there": accepted -> installed into PC-A's Stream Deck as a new profile
        sb_bar = bar["Stream Deck soundboard"]["bar"]
        inst = next(x for x in walk(sb_bar) if isinstance(x, ttk.Checkbutton) and x.cget("text") == "install it there")
        inst.invoke()
        prop = send_from("Stream Deck soundboard", False, [], "installed into Stream Deck here")
        name = re.search(r"new profile '(.+?)'", " ".join(prop["lines"])).group(1)
        assert any(x.startswith("Here: for the Stream Deck '") for x in prop["lines"]), prop["lines"]
        wait(lambda: any(json.loads(m.read_text()).get("Name") == name for m in (work / "A_SD" / "ProfilesV3").glob(
            "*.sdProfile/manifest.json")), 30, "installed on PC-A")
        inst.invoke()
        print(f"soundboard installed into PC-A's Stream Deck as '{name}' once accepted there")

        # VTube Studio backgrounds with "set them up there": PC-A's own VTube Studio tab copies them, makes the
        # hotkeys (its model Wolf; VTube Studio open there: closed, backed up, reopened) and a Stream Deck key each
        (work / "a_vts_running").write_text("1")
        vs = next(x for x in walk(bar["VTube Studio backgrounds"]["bar"]) if isinstance(x, ttk.Checkbutton))
        vs.invoke()
        prop = send_from("VTube Studio backgrounds", False, [], "close and reopen VTube Studio")
        assert any(x.startswith("Here: hotkeys on the model 'Wolf'; Stream Deck keys on A-Main") and "/ Page 1" in x
                   for x in prop["lines"]), prop["lines"]  # Fox isn't on PC-A: its own model, named
        wolf = work / "A_VTS" / "StreamingAssets" / "Live2DModels" / "Wolf" / "Wolf.vtube.json"
        wait(lambda: json.loads(wolf.read_text(encoding="utf-8-sig")).get("Hotkeys"), 30, "hotkeys on PC-A's model")
        wait(lambda: any(v_.endswith("|Trigger Hotkey") for v_ in a_keys().values()), 20, "its Stream Deck key")
        launched = [x["launched"] for x in a_log() if "launched" in x]
        assert any("taskkill" in str(x) for x in launched) and any("steam://" in str(x) for x in launched), launched
        assert list((work / "A_VTS backups").glob("Wolf *.vtube.json"))  # the model file backed up first
        vs.invoke()
        print("VTube Studio set up there:", len(json.loads(wolf.read_text(encoding="utf-8-sig"))["Hotkeys"]),
              "hotkey(s) on Wolf, a Stream Deck key, VTube Studio closed / backed up / reopened on PC-A")

        # more than 200 files: sent in batches of 200, each accepted there on its own
        many = tmp / "many"
        many.mkdir()
        lib_picks[:] = [wav(many / f"m{i:03d}.wav", 80) for i in range(201)]
        btn(bar["Import to folders"]["bar"], "From Channel Mirror...").invoke()
        total = len(held["imp"]["files"])
        assert total > 200, total
        n0 = answered()
        a_answers(True, True)
        btn(bar["Import to folders"]["bar"], "Send there").invoke()
        wait(lambda: answered() >= n0 + 2, 120, "two batches asked on PC-A")
        props = [x for x in a_log() if "proposal" in x][-2:]
        assert [x["lines"][0].split(" ")[0] for x in props] == ["200", str(total - 200)], [x["lines"][0] for x in props]
        assert any("in 2 batches of up to 200" in x[2] for x in hub["log"])
        print(f"{total} files to PC-A's Import tab: sent in 2 batches (200 + {total - 200}), each accepted there")

        # its address changed: found again; renew; expiry; unlink
        cm.peer_find = lambda peer, me, addrs=None, timeout=2.0: real_find(peer, me, [("127.0.0.1", a_state()["port"])], 1.0)
        pa["host"] = "127.0.0.2"
        hub["state"].pop(pa["id"], None)
        lk["check"](False)
        wait(lambda: pa["host"] == "127.0.0.1" and (hub["state"].get(pa["id"]) or (0,))[0], 30, "found again")
        old = (pa["secret"], pa["since"])
        lk["tree"].selection_set(pa["id"])
        a_answers(True)
        pa["since"] -= 10 * 86400  # 20 days left
        btn(tabs["Linked computers"], "Renew").invoke()
        wait(lambda: hub["peers"]()[0]["secret"] != old[0], 40, "renewed")
        pa = hub["peers"]()[0]
        assert cm.peer_days_left(pa) == cm.PEER_DAYS
        wait(lambda: kept(work / "a_settings.json").get("PC-B") == pa["secret"], 10, "renewal saved on PC-A")
        assert kept(cm.SETTINGS) == {"PC-A": pa["secret"]}  # saved at once here too
        pa["since"] = time.time() - (cm.PEER_DAYS + 1) * 86400  # 31 days on
        hub["act"](pa, "x")
        wait(lambda: "expired" in lk["tree"].item(pa["id"], "values")[2])
        lib_picks[:] = [b_snd]
        btn(bar["Import to folders"]["bar"], "Send there").invoke()
        wait(lambda: "expired" in bar["Import to folders"]["note"].cget("text"), 10, "expired shown")
        print("found again after an address change; renewed (30 fresh days); expired shown:",
              bar["Import to folders"]["note"].cget("text"))
        logv = next(x for x in walk(home) if isinstance(x, ttk.Treeview) and x.cget("columns") == ("t", "who", "what"))
        whats = [logv.item(i, "values")[2] for i in logv.get_children()]
        assert any("accepted on PC-A" in x for x in whats) and any("declined on PC-A" in x for x in whats)
        assert any("a proposal arrived" in x for x in whats) and any("accepted here" in x for x in whats), whats[:8]
        print("activity log, both directions:", len(whats), "rows, e.g.", whats[:3])
        lk["tree"].selection_set(pa["id"])
        btn(tabs["Linked computers"], "Unlink").invoke()
        assert not hub["peers"]()
        wait(lambda: not a_state().get("peers"), 20, "PC-A told")
        print("unlink: forgotten here and on PC-A")
        assert not errors, errors
    except Exception as e:
        import traceback
        traceback.print_exc()
        errors.append(e)
    (work / "a_quit").write_text("1")
    r.tk.call(r.protocol("WM_DELETE_WINDOW"))


real_mainloop = tk.Tk.mainloop
tk.Tk.mainloop = lambda self, n=0: (self.after(1500, tour), real_mainloop(self, n))[1]
wav(sendto_dir / "s1.wav"), wav(sendto_dir / "s2.wav")
sys.argv = [sys.argv[0], cm.LINK_TO_PEER, str(bg), str(sendto_dir)]  # started from Send to (linked computers)
cm.gui()
try:
    peer_proc.wait(30)
except subprocess.TimeoutExpired:
    peer_proc.kill()
assert not errors, errors
assert not [x for x in a_log() if "error" in x], [x for x in a_log() if "error" in x]
shutil.rmtree(tmp, ignore_errors=True)
print("drive crosspc ok")
