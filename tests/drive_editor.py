"""The Stream Deck editor tab in the main window: its right-click menus on the key grid (add sounds to a key, new
folders from files / a folder / one per subfolder, fill free keys, copy / delete / paste, same settings inside a
folder), the dialogs they open (new keys, Random or Multi, not enough keys, edit keys together), Apply and Undo -
against a synthetic Stream Deck profile in a temp folder. Nothing is sent to Stream Deck; closing throws the
changes away and leaves the profile on disk as it was."""
import json
import shutil
import tempfile
import time
import tkinter as tk
import wave
from pathlib import Path

import numpy as np
from tkinter import ttk

from harness import App

tmp = Path(tempfile.mkdtemp(prefix="cm_editor_"))
snd = tmp / "snd"
snd.mkdir()


def tone_file(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000), w.writeframes(np.zeros(800, "<i2").tobytes())


for n in ("a10", "a2", "a1", "b"):
    tone_file(snd / f"{n}.wav")
many = tmp / "many"  # 12 different sounds for the mass import (a file picker gives each file once)
many.mkdir()
for i in range(1, 13):
    tone_file(many / f"m{i}.wav")

app = App()
cm = app.cm
wavs = sorted(snd.glob("*.wav"), key=cm.natural)
assert [p.stem for p in wavs] == ["a1", "a2", "a10", "b"]

# synthetic installed profile, 3x2 deck: page 1 = a single sound at 0,0 (volume 30) and a Random at 1,0
sd = tmp / "SD"
prof = sd / "ProfilesV3" / "P1.sdProfile"
pg = prof / "Profiles" / "PAGE1" / "manifest.json"
pg.parent.mkdir(parents=True)
(prof / "manifest.json").write_text(json.dumps({"Device": {"Model": "20GBA9901", "UUID": "dev"}, "Name": "Test",
                                                "Pages": {"Current": "page1", "Default": "x", "Pages": ["page1"]}}))
pg.write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": {
    "0,0": cm.sd_play(wavs[3], "solo", volume=30),
    "1,0": cm.sd_wrap("Random Action", "rnd", [cm.sd_play(wavs[3], "b")])}}]}))
on_disk = pg.read_text()
cm.SD_DIR = sd
cm.sd_devices = lambda *a, **k: {"x": ("20GBA9901", "dev", 3, 2)}  # the deck: 3 x 2 keys
# a right-click menu is the app's own (built by it, entries and greyed-out state as the user gets them); only showing
# it is skipped: on Windows tk_popup waits in the OS menu loop until a click, which a script can't give it
menus = []
tk.Menu.tk_popup = lambda m, *a, **k: menus.append(m)
app.start()
page = app.tab("Stream Deck editor")
api = app.api("editor")
grid = next(g for g in cm.DeckGrid.shown if str(g.frame).startswith(str(page) + "."))
T = [int(time.time() * 1000) % 2_000_000_000]


def stamp(dt=1000):
    """Event times far apart, so two clicks on one key are never taken for a double-click (and a double is one)."""
    T[0] += dt
    return T[0]


def click(pos):
    t, w = stamp(), grid.tiles[pos]
    w.event_generate("<ButtonPress-1>", x=10, y=10, time=t)
    w.event_generate("<ButtonRelease-1>", x=10, y=10, time=t + 10)
    app.pump()


def double(pos):
    t, w = stamp(), grid.tiles[pos]
    for kind, dt in (("ButtonPress-1", 0), ("ButtonRelease-1", 10), ("ButtonPress-1", 80), ("ButtonRelease-1", 90)):
        w.event_generate(f"<{kind}>", x=10, y=10, time=t + dt)
    app.pump()


def right_click(pos):
    menus.clear()
    grid.tiles[pos].event_generate("<Button-3>", x=10, y=10, time=stamp())
    assert menus, f"no menu on key {pos}"
    return menus[-1]


def menu(pos, label):
    app.menu_item(right_click(pos), label)
    app.pump()


shown = []  # titles of the dialogs answered


def answer(title, act, secs=10):
    """Answer the dialog whose title starts with `title` once it opens: act(window). Set up before the action that
    opens it (a modal dialog waits in its own loop, which runs this check)."""
    t0 = time.time()

    def poll():
        win = next((w for w in app.windows() if str(w.title()).startswith(title)), None)
        if win is not None:
            shown.append(win.title())
            return act(win)
        if time.time() - t0 < secs:
            app.root.after(40, poll)
    app.root.after(40, poll)


def create(name=None):
    """The New key dialog: type the name (when given), press Create."""
    def act(win):
        if name is not None:
            e = next(e for e in app.walk(win) if isinstance(e, ttk.Entry) and not isinstance(e, ttk.Combobox))
            e.delete(0, "end")
            e.insert(0, name)
        app.button("Create", win).invoke()
    answer("New key - ", act)


def keys(p=pg):
    return api["pending"]()[p]["Controllers"][0]["Actions"]


def folder_file(a):
    return prof / "Profiles" / a["Settings"]["ProfileUUID"].upper() / "manifest.json"


# 1) single sound key + 2 files -> "Random? No = Multi" says No: Multi; the new sounds copy its settings (volume 30)
app.picks.append(wavs[:2])
app.yes.append(False)
menu("0,0", "Add sound files to this key...")
assert app.asked[-1][:2] == ("askyesnocancel", "Add sounds"), app.asked[-1]
# 2) Random key + a folder -> grows in place
app.picks.append(snd)
menu("1,0", "Add a folder of sounds to this key...")
# 3) empty key 2,0 -> new folder from a folder, named in the dialog: 3x2 = 5 keys after Parent Folder, 4 sounds in order
app.picks.append(snd)
create("MyFolder")
menu("2,0", "New folder(s) of sounds from a folder...")
assert shown[-1] == "New key - 4 sound(s)", shown
p = api["pending"]()
assert len(p) == 2, p.keys()
main = keys()
assert cm.sd_kind(main["0,0"]) == "Multi x3" and {s["Settings"]["volume"] for s in cm.sd_sounds(main["0,0"])} == {30}
assert cm.sd_kind(main["1,0"]) == "Random x5"
assert main["2,0"]["UUID"] == cm.SD_FOLDER and cm.sd_title(main["2,0"]) == "MyFolder"
newp = next(k for k in p if k != pg)
assert not newp.exists() and newp == folder_file(main["2,0"])
fk = p[newp]["Controllers"][0]["Actions"]
assert fk["0,0"]["UUID"] == cm.SD_PARENT
assert [cm.sd_title(fk[k]) for k in ("1,0", "2,0", "0,1", "1,1")] == ["A1", "A2", "A10", "B"] and "2,1" not in fk
# 4) the folder key + 3 files: 1 free key inside; the other 2 carry over into "MyFolder 2" on the next free key (0,1)
app.picks.append(wavs[:3])
create()
menu("2,0", "Add sound files into this folder...")
fk = keys(newp)
assert cm.sd_title(fk["2,1"]) == "A1" and len(fk) == 6
main = keys()
assert main["0,1"]["UUID"] == cm.SD_FOLDER and cm.sd_title(main["0,1"]) == "MyFolder 2"
ovk = keys(folder_file(main["0,1"]))
assert [cm.sd_title(ovk[k]) for k in ("1,0", "2,0")] == ["A2", "A10"] and len(ovk) == 3
# 5) fill free keys on this page from 1,1 with 2 files: 1,1 and 2,1
app.picks.append(wavs[2:])
create()
menu("1,1", "Fill free keys from here with files...")
main = keys()
assert cm.sd_title(main["1,1"]) == "A10" and cm.sd_title(main["2,1"]) == "B"
m = json.loads((prof / "manifest.json").read_text())
names = [n for n, _ in cm.sd_pages(prof, m, api["pending"]())]
assert names == ["Page 1", "Folder: MyFolder", "Folder: MyFolder 2"], names
assert len(shown) == 3 and not app.sent, (shown, app.sent)
# 6) double-click the new (unsent) folder to open it, then undo everything while inside it: back on page 1, nothing
#    pending, its page gone
double("2,0")
assert api["current"]()[1] == newp, api["current"]()
undo = app.button("Undo", page)
for _ in range(5):
    undo.invoke()
app.pump()
assert api["pending"]() == {}, api["pending"]()
assert [n for n, _ in cm.sd_pages(prof, m, {})] == ["Page 1"] and api["current"]()[1] == pg
assert undo.instate(["disabled"])  # nothing left to undo

# 7) mass import: 12 sounds, 5 per folder (3x2 minus Parent) -> 3 folders, the first at 0,1, the rest beside it, the
#    sounds in name order (m2 before m10) across them
app.picks.append(sorted(many.glob("*.wav"), reverse=True))  # picked in any order
create("MyFolder")
menu("0,1", "New folder(s) of sounds from files...")
main = keys()
assert {k: cm.sd_title(a) for k, a in main.items() if a["UUID"] == cm.SD_FOLDER} == {
    "0,1": "MyFolder", "1,1": "MyFolder 2", "2,1": "MyFolder 3"}, main.keys()
order = []
for k in ("0,1", "1,1", "2,1"):
    fkp = keys(folder_file(main[k]))
    order += [cm.sd_title(fkp[x]) for x in sorted(fkp, key=cm.sd_order) if fkp[x]["UUID"] == cm.SD_PLAY]
assert order == [f"M{i}" for i in range(1, 13)], order
# 8) adding 6 more into the full first folder: no room inside, so they carry over to a new folder on the free 2,0;
#    only 5 fit in one folder there, and "add the first 5?" is answered yes
click("0,1")  # just this folder selected (the import selected all three)
app.picks.append(wavs + wavs[:2])
create()
menu("0,1", "Add sound files into this folder...")
assert any(a[:2] == ("askyesno", "Not enough keys") and "room for 5 of these 6" in a[2] for a in app.asked), app.asked
main = keys()
assert cm.sd_title(main["2,0"]) == "MyFolder 4" and main["2,0"]["UUID"] == cm.SD_FOLDER

# 9) select the first folder key, Apply the default tool (purpose preset): reaches every sound inside it
click("0,1")
apply_b = app.button("Apply to", page, startswith=True)
assert apply_b.cget("text") == "Apply to 1 key", apply_b.cget("text")
apply_b.invoke()
app.pump()
fp = folder_file(main["0,1"])
inner = [a for a in keys(fp).values() if a["UUID"] == cm.SD_PLAY]
assert len(inner) == 5 and {a["Settings"]["actionType"] for a in inner} == {cm.SD_MODES.index("Play / Overlap")}
other = [a for a in keys(folder_file(main["1,1"])).values() if a["UUID"] == cm.SD_PLAY]
assert {a["Settings"]["actionType"] for a in other} == {0}  # the other folders untouched


# 10) right-click > Same settings for every sound inside: the Edit keys together window lists the folder key + its 5
#     sound keys; volume 55 there -> on every sound inside, the folder keeps its name
def volume_55(win):
    vol = next(c for c in app.walk(win) if isinstance(c, ttk.Combobox) and "100" in map(str, c.cget("values")))
    vol.set("55")
    app.button("Apply to 6 keys", win).invoke()


answer("Edit ", volume_55)
menu("0,1", "Same settings for every sound inside...")
assert shown[-1] == "Edit 6 keys together", shown
inner = [a for a in keys(fp).values() if a["UUID"] == cm.SD_PLAY]
assert {a["Settings"]["volume"] for a in inner} == {55}
assert cm.sd_title(keys()["0,1"]) == "MyFolder"

# 11) copy the folder key, free 2,0, paste there: the paste gets its own copy of the folder page
menu("0,1", "Copy key   Ctrl+C")
click("2,0")
menu("2,0", "Delete key   Del")
assert "2,0" not in keys()
paste = right_click("2,0")
i = next(i for i in range(paste.index("end") + 1) if paste.type(i) == "command"
         and paste.entrycget(i, "label") == "Paste here   Ctrl+V")
assert str(paste.entrycget(i, "state")) == "normal"  # greyed out until something is copied
app.menu_item(paste, "Paste here   Ctrl+V")
app.pump()
main = keys()
src_id, new_id = main["0,1"]["Settings"]["ProfileUUID"], main["2,0"]["Settings"]["ProfileUUID"]
assert src_id != new_id and cm.sd_title(main["2,0"]) == "MyFolder"
newpg, srcpg = keys(folder_file(main["2,0"])), keys(fp)
assert [cm.sd_title(newpg[k]) for k in sorted(newpg, key=cm.sd_order)] == [
    cm.sd_title(srcpg[k]) for k in sorted(srcpg, key=cm.sd_order)]
assert {a["Settings"]["volume"] for a in newpg.values() if a["UUID"] == cm.SD_PLAY} == {55}
assert not {a["ActionID"] for a in newpg.values()} & {a["ActionID"] for a in srcpg.values()}

# 12) mass import, one folder per subfolder: "2 drums" (7 sounds = 2 folders), "memes" (1); 2 keys free -> the first
#     2 ("make the first 2?" yes)
lib = tmp / "lib"
for sub, n in (("memes", 1), ("2 drums", 7)):
    (lib / sub).mkdir(parents=True)
    for i in range(n):
        shutil.copy2(wavs[0], lib / sub / f"s{i}.wav")
click("1,1")
menu("1,1", "Delete key   Del")
click("2,1")
menu("2,1", "Delete key   Del")
app.picks.append(lib)
create()
menu("1,1", "New folders, one per subfolder (mass import)...")
assert shown[-1] == "New key - 8 sound(s)", shown
assert any(a[:2] == ("askyesno", "Not enough keys") and "Make the first 2?" in a[2] for a in app.asked), app.asked
main = keys()
assert [cm.sd_title(main[k]) for k in ("1,1", "2,1")] == ["2 Drums", "2 Drums 2"], main.keys()
d2 = api["pending"]()[folder_file(main["2,1"])]
assert [cm.sd_title(a) for k, a in sorted(cm.sd_keypad(d2).items(), key=lambda x: cm.sd_order(x[0]))
        if a["UUID"] == cm.SD_PLAY] == ["S5", "S6"]
# the pages of new folders deleted before sending (MyFolder 2, 3, 4) aren't sent: page 1 + the 4 folders on it now
assert len(api["pending"]()) == 5, [p.parent.name for p in api["pending"]()]
for _ in range(4):  # undo the import, 2 deletes and the paste: MyFolder 2 and 3 come back with their pages
    undo.invoke()
app.pump()
main = keys()
assert cm.sd_title(main["1,1"]) == "MyFolder 2" and "2,0" not in main
assert len(api["pending"]()) == 4  # page 1 + MyFolder, 2, 3 (MyFolder 4 was deleted in step 11)

# nothing went to Stream Deck while editing; the window's close button asks about the 4 unsent pages: No = throw away
assert not app.sent and not app.boxes, (app.sent, app.boxes)
app.yes.append(False)
saved = app.close()
assert app.asked[-1][:2] == ("askyesnocancel", "Stream Deck changes not sent") and "4 edited" in app.asked[-1][2], \
    app.asked[-1]
assert not app.sent and pg.read_text() == on_disk and len(list((prof / "Profiles").iterdir())) == 1
assert saved["tab"] == "Stream Deck editor" and saved["sd_autosend"] is False, saved
assert len(shown) == 7, shown
shutil.rmtree(tmp, ignore_errors=True)
print("editor tab menus ok: every right-click action, its dialogs, undo, nothing sent")
