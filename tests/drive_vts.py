"""The VTube Studio backgrounds tab in the main window, on a synthetic VTube Studio install + Stream Deck profile (temp
only). VTube Studio 'running' is simulated: close (caught, nothing is closed) -> write -> reopen (caught, not launched).
One key each, then folders of 2 (nothing copied twice, hotkeys reused), two files with the same name, a model file
that can't be written (unchanged, VTube Studio reopened), a blank "folders of" box, Find missing, and the settings
kept when the window closes."""
import json
import os
import stat
import subprocess
import time

from tkinter import ttk

from harness import App, walk

app = App()
cm = app.cm
started, closed = [], []
os.startfile = lambda p, *a: started.append(str(p))  # VTube Studio isn't started
real_run = subprocess.run
subprocess.run = lambda cmd, *a, **k: (closed.append(cmd) or subprocess.CompletedProcess(cmd, 0)) \
    if cmd[:1] == ["taskkill"] else real_run(cmd, *a, **k)  # nor closed
running = [True]  # VTube Studio "running" at the first check, then closed
cm.vts_running = lambda: running.pop(0) if running else False
tmp = app.tmp / "data"

# synthetic VTube Studio (the install the Setup tab points at)
vts = tmp / "VTube Studio_Data" / "StreamingAssets"
(vts / "Backgrounds").mkdir(parents=True)
(vts / "Live2DModels" / "Wolf").mkdir(parents=True)
mfile = vts / "Live2DModels" / "Wolf" / "Wolf.vtube.json"
mfile.write_text(json.dumps({"Version": 1, "Name": "Wolf", "ModelID": "w" * 32, "Hotkeys": [
    dict(cm.VTS_HOTKEY, HotkeyID="a" * 32, File="Balcony", Name="")]}, indent=4))
src = tmp / "my backgrounds"
src.mkdir()
for n, data in (("Balcony.mp4", b"balcony"), ("Room 2.png", b"r2"), ("Room 10.jpg", b"r10"), ("notes.txt", b"x")):
    (src / n).write_bytes(data)
cm.VTS_ASSETS = vts
# synthetic Stream Deck profile, 3x2, key 0,0 in use
sd = tmp / "SD"
prof = sd / "ProfilesV3" / "P.sdProfile"
pg = prof / "Profiles" / "PAGE1" / "manifest.json"
pg.parent.mkdir(parents=True)
(prof / "manifest.json").write_text(json.dumps({"Device": {"Model": "m", "UUID": "dev"}, "Name": "Deck", "Pages": {
    "Current": "page1", "Default": "x", "Pages": ["page1"]}}))
pg.write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": {"0,0": cm.sd_stop_key()}}]}))
cm.SD_DIR = sd
cm.sd_devices = lambda *a, **k: {"x": ("m", "dev", 3, 2)}
cm.sd_connected = lambda: set()  # no USB query
app.start()
deck = app.api("editor")
t = app.api("vts")
v = t["vars"]
page = app.tab("VTube Studio backgrounds")
grid = next(g for g in cm.DeckGrid.shown if str(g.frame).startswith(str(page) + "."))
clock = [int(time.monotonic() * 1000) % 2 ** 30]


def click(pos):
    """A left click on a key (each stamped a second after the last, so two on one key aren't a double-click)."""
    clock[0] += 1000
    grid.tiles[pos].event_generate("<ButtonPress-1>", x=4, y=4, time=clock[0])
    grid.tiles[pos].event_generate("<ButtonRelease-1>", x=4, y=4, time=clock[0] + 50)
    app.pump(0.02)


def bound(kind, var):
    return next(w for w in walk(page) if isinstance(w, kind) and str(w.cget("textvariable")) == str(var))


def tick(text):
    return next(c for c in walk(page) if isinstance(c, ttk.Checkbutton) and str(c.cget("text")).startswith(text))


def status():
    return next(str(lb.cget("text")) for lb in walk(page) if isinstance(lb, ttk.Label)
                and "Status" in str(lb.cget("style")))


def add_files(*files):
    app.picks.append(list(files))
    app.button("Add files...", page).invoke()


def go():
    app.button("Copy and set up", page).invoke()
    app.pump(0.05)


assert v["assets"].get() == str(vts) and v["model"].get() == "Wolf", (v["assets"].get(), v["model"].get())
app.picks.append(src)
app.button("Add folder...", page).invoke()  # a folder
add_files(src / "notes.txt")  # a file it can't use
assert "1 file(s) skipped" in status(), status()
assert [f.name for f in t["files"]] == ["Balcony.mp4", "Room 2.png", "Room 10.jpg"]
tv = next(w for w in walk(page) if isinstance(w, ttk.Treeview))
assert [tv.set(i, "state") for i in tv.get_children()] == ["new"] * 3
click("0,0")  # in use: refused
assert not t["picks"] and "is in use" in status(), status()
click("1,0")  # start here: 1,0 then the next free keys (2,0, 0,1)
go()
assert not app.errors and not app.boxes, (app.errors, app.boxes)
assert any("close for a moment" in q[2] for q in app.asked), app.asked
assert closed and closed[0][:2] == ["taskkill", "/IM"], closed  # asked to close (caught)
assert started == [f"steam://rungameid/{cm.VTS_APPID}"], started  # reopened after writing
assert sorted(p.name for p in (vts / "Backgrounds").iterdir()) == ["Balcony.mp4", "Room 10.jpg", "Room 2.png"]
data = json.loads(mfile.read_text(encoding="utf-8"))
bg = {h["File"]: h["HotkeyID"] for h in data["Hotkeys"] if h["Action"] == "ChangeBackground"}
assert set(bg) == {"Balcony", "Room 2", "Room 10"} and bg["Balcony"] == "a" * 32 and len(data["Hotkeys"]) == 3
assert len(list(cm.vts_backups().glob("Wolf *.vtube.json"))) == 1  # backed up first
assert cm.vts_backups().is_relative_to(app.tmp)
keys = deck["pending"]()[pg]["Controllers"][0]["Actions"]
got = {k: (a["Settings"]["hotkeyId"], cm.sd_title(a)) for k, a in keys.items() if a["UUID"] == cm.SD_VTS_HOTKEY}
assert got == {"1,0": (bg["Balcony"], "Balcony"), "2,0": (bg["Room 2"], "Room 2"), "0,1": (bg["Room 10"], "Room 10")}
assert all(a["Settings"]["modelId"] == "w" * 32 and a["Plugin"]["UUID"] == "dev.cazzar.streamdeck.vtubestudio"
           for a in keys.values() if a["UUID"] == cm.SD_VTS_HOTKEY)
assert cm.sd_title(keys["0,0"]) == "STOP"  # nothing overwritten
assert str(grid.tiles["1,0"].cget("text")).startswith("Balcony"), grid.tiles["1,0"].cget("text")  # the grid shows it
assert [tv.set(i, "state") for i in tv.get_children()] == ["already there"] * 3
print("one key each ok:", got)

# again, in folders of 2: nothing copied twice, hotkeys reused, 2 folders from the picked key
running[:] = []  # not running now: no close / reopen
asked = len(app.asked)
tick("in folders of").invoke()
next(s for s in walk(page) if isinstance(s, ttk.Spinbox) and str(s.cget("textvariable")) == str(v["per"])).set(2)
e = bound(ttk.Entry, v["title"])
e.delete(0, "end")
e.insert(0, "BGs")
assert v["folders"].get() is True and v["per"].get() == 2 and v["title"].get() == "BGs"
click("1,1")
go()
assert not app.errors and not app.boxes and len(app.asked) == asked, (app.errors, app.boxes, app.asked[asked:])
assert len(list((vts / "Backgrounds").iterdir())) == 3 and len(json.loads(mfile.read_text())["Hotkeys"]) == 3
keys = deck["pending"]()[pg]["Controllers"][0]["Actions"]
folders = {k: a for k, a in keys.items() if a["UUID"] == cm.SD_FOLDER}
assert [cm.sd_title(folders[k]) for k in sorted(folders, key=cm.sd_order)] == ["BGs", "BGs 2"], folders.keys()
inside = []
for k in sorted(folders, key=cm.sd_order):
    fp = prof / "Profiles" / folders[k]["Settings"]["ProfileUUID"].upper() / "manifest.json"
    fk = deck["pending"]()[fp]["Controllers"][0]["Actions"]
    inside += [cm.sd_title(fk[x]) for x in sorted(fk, key=cm.sd_order) if fk[x]["UUID"] == cm.SD_VTS_HOTKEY]
assert inside == ["Balcony", "Room 2", "Room 10"], inside
print("folders ok:", inside)

# review fixes. 1: two different files with the same name -> two backgrounds, two keys (none dropped)
tick("in folders of").invoke()
app.button("Undo keys", page).invoke()  # take the two folders back off the page: 1,1 and 2,1 free again
keys = deck["pending"]()[pg]["Controllers"][0]["Actions"]
assert "1,1" not in keys and "2,1" not in keys, keys.keys()
same = tmp / "same"
(same / "a").mkdir(parents=True)
(same / "b").mkdir(parents=True)
(same / "a" / "bg.png").write_bytes(b"first")
(same / "b" / "bg.png").write_bytes(b"second")
app.button("Clear", page).invoke()
assert not t["files"]
add_files(same / "a" / "bg.png", same / "b" / "bg.png")
click("1,1")  # one pick; the second key goes on the next free key (2,1)
go()
assert not app.errors and not app.boxes, (app.errors, app.boxes)
keys = deck["pending"]()[pg]["Controllers"][0]["Actions"]
titles = sorted(cm.sd_title(a) for a in keys.values() if a["UUID"] == cm.SD_VTS_HOTKEY)
assert "Bg" in titles and "Bg (2)" in titles, titles
# 2/3: a broken model file: the error says so, the file is unchanged, VTube Studio is reopened
running[:] = [True]
started.clear()
before_model = mfile.read_bytes()
os.chmod(mfile, stat.S_IREAD)  # the write can't happen (like no permission)
fresh = tmp / "fresh.png"
fresh.write_bytes(b"fresh")  # a new background, so a hotkey has to be added
app.button("Clear", page).invoke()
add_files(fresh)
tick("Put a Stream Deck key").invoke()
assert v["keys"].get() is False
go()
os.chmod(mfile, stat.S_IREAD | stat.S_IWRITE)
assert app.boxes and app.boxes[-1][0] == "showerror" and "unchanged" in app.boxes[-1][2], app.boxes[-1:]
assert mfile.read_bytes() == before_model and started == [f"steam://rungameid/{cm.VTS_APPID}"], started
assert not list(mfile.parent.glob("*.channelmirror-new"))  # the half-way file is cleaned up
app.boxes.clear()
# 4: a blank "folders of" box: saving still works (checked when the window closes)
tick("in folders of").invoke()  # folders back on, so the saved settings show it
spin = next(s for s in walk(page) if isinstance(s, ttk.Spinbox) and str(s.cget("textvariable")) == str(v["per"]))
spin.delete(0, "end")
assert spin.get() == "" and not app.errors
print("review fixes ok")

# Find missing: a hotkey whose file was removed from Backgrounds is found two folders down and copied back
(vts / "Backgrounds" / "Room 10.jpg").unlink()
cb = bound(ttk.Combobox, v["model"])
cb.set("Wolf")  # picked again: the tab looks again
cb.event_generate("<<ComboboxSelected>>")
app.pump(0.05)
deep = tmp / "stash" / "old" / "bits"
deep.mkdir(parents=True)
(deep / "ROOM 10.JPG").write_bytes(b"r10")
btn = app.button("Find missing...", page)
assert btn.winfo_manager(), "the Find missing button should show when something is missing"
app.picks.append(tmp / "stash")
btn.invoke()
assert (vts / "Backgrounds" / "Room 10.jpg").read_bytes() == b"r10"  # the hotkey's exact name
assert not btn.winfo_manager(), "nothing missing now: the button goes away"
assert "Every background hotkey has its file now" in status(), status()
print("find missing ok")

# the window's close button: unsent Stream Deck keys offered (No = thrown away); the tab's settings are kept
app.yes.append(False)
for f in app.tmp.rglob("*"):
    os.chmod(f, stat.S_IREAD | stat.S_IWRITE)  # the read-only model's backup copy can be cleaned up
saved = app.close()
subprocess.run = real_run
assert any(q[1] == "Stream Deck changes not sent" for q in app.asked), app.asked
vc = saved["vts"]
assert vc["folders"] is True and vc["per"] == 1 and vc["model"] == "Wolf" and vc["title"] == "BGs" and \
    vc["keys"] is False and vc["assets"] == str(vts), vc
print("vts tab ok")
