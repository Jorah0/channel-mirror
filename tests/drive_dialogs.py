"""The key dialogs and the sound picker, opened the way a user opens them in the main window: the Stream Deck editor's
right-click menus (new sound key, new folder from files / a folder, fill free keys, one folder per subfolder, a
cancelled folder pick, Edit key with its Add folder / Add sounds buttons), the Stream Deck soundboard tab (add files,
a folder onto a key, export the profile file), then every tab shown and the window closed. Modal dialogs are answered
from root.after callbacks scheduled before the action that opens them. Temp copies only (harness): a synthetic Stream
Deck profile, nothing sent to or closed in Stream Deck, files "opened" only recorded."""
import json
import time
import wave
import zipfile
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import ttk

from harness import App, walk

app = App()
cm = app.cm
popped, problems = [], []  # the exported profile is "opened" into app.launched (harness), not Stream Deck
cm.sd_stop = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not close Stream Deck"))
cm.sd_connected = lambda: set()  # no USB query (2 s); no deck counts as plugged in
tk.Menu.tk_popup = lambda m, x, y, entry="": popped.append(m)  # the real menu is built; it just isn't shown

snd = app.tmp / "snd"
snd.mkdir()
for n in ("t10", "t2", "T1", "b"):
    with wave.open(str(snd / f"{n}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000), w.writeframes(np.zeros(800, "<i2").tobytes())
(snd / "notes.txt").write_text("x")
order = ["b", "T1", "t2", "t10"]  # Explorer order
explorer = [snd / f"{n}.wav" for n in ("t10", "b", "t2", "T1")]  # what a file picker hands back, unsorted

# a synthetic installed Stream Deck profile (5x3: the key at 4,2 sets the grid): page 1 = a single sound at 0,0
prof = cm.SD_DIR / "ProfilesV3" / "P1.sdProfile"
pg = prof / "Profiles" / "PAGE1" / "manifest.json"
pg.parent.mkdir(parents=True)
(prof / "manifest.json").write_text(json.dumps({"Device": {"Model": "20GBA9901", "UUID": "dev"}, "Name": "Test",
                                                "Pages": {"Current": "page1", "Default": "x", "Pages": ["page1"]}}))
pg.write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": {
    "0,0": cm.sd_play(snd / "b.wav", "solo", volume=40), "4,2": cm.sd_stop_key()}}]}))

app.start()


def labels(w):
    return "".join(str(x.cget("text")) for x in walk(w) if isinstance(x, ttk.Label))


def when(title, do, secs=10, expect=True):
    """Once a window titled `title...` is open (the modal dialog the next action opens), do(win). A failure closes
    the dialog (so the test never sticks in its wait_window) and is reported; so is no window (when expected)."""
    t0 = time.time()

    def go():
        win = next((w for w in app.windows() if w.title().startswith(title)), None)
        if win is None:
            if time.time() - t0 < secs:
                app.root.after(50, go)
            elif expect:
                problems.append(f"no {title!r} window")
            return
        try:
            do(win)
        except Exception as e:  # noqa: BLE001 - reported below
            problems.append(e)
        if win.winfo_exists():
            win.destroy()
    app.root.after(50, go)


def press(win, text):
    next(b for b in walk(win) if isinstance(b, ttk.Button) and b.cget("text") == text).invoke()


def new_key(seen):
    """Answer the New key dialog: note what it shows, press Create."""
    def do(w):
        seen.update(title=w.title(), name="NAME" in labels(w),
                    kinds=[str(r.cget("text")).split(" (")[0] for r in walk(w) if isinstance(r, ttk.Radiobutton)
                           and str(r.cget("text")).split(" (")[0] in cm.SD_KINDS | {
                               "Folder": 1, "One key per sound": 1, "Folder per subfolder": 1, "Single sound": 1}])
        press(w, "Create")
    when("New key", do)
    return seen


def grid_of(page):
    return next(g for g in cm.DeckGrid.shown if str(g.frame).startswith(str(page) + "."))


def right_click(grid, pos):
    """Right-click a key on the grid -> the menu it opens."""
    popped.clear()
    grid.tiles[pos].event_generate("<Button-3>", x=5, y=5)
    app.pump(0.05)
    assert popped, f"no menu on key {pos}"
    return popped[-1]


def check(*why):
    assert not problems and not app.errors, (why, problems, app.errors)


# --- the Stream Deck editor: its right-click menus open the picker and the dialogs ---
ed_page = app.tab("Stream Deck editor")
ed = app.api("editor")
eg = grid_of(ed_page)


def keys(page_file=pg):
    return cm.sd_keypad(json.loads(json.dumps(ed["pending"]().get(page_file) or json.loads(page_file.read_text()))))


def folder_keys(key):
    """The keys on the page a (new, unsent) folder key opens."""
    return keys(prof / "Profiles" / key["Settings"]["ProfileUUID"].upper() / "manifest.json")


def titles(kp, slots):
    return [cm.sd_title(kp[s]) for s in slots]


inside = ["1,0", "2,0", "3,0", "4,0"]  # a folder page: Parent Folder at 0,0, then one key per sound in order

# A + B) New sound key on an empty key: the picker hands files back in Explorer order; several = Random (named)
app.picks.append(explorer)
seen = new_key({})
app.menu_item(right_click(eg, "1,0"), "New sound key...")
check("new sound key")
k = keys()["1,0"]
print("new sound key:", seen, cm.sd_kind(k))
assert seen["title"] == "New key - 4 sound(s)" and seen["kinds"] == ["Random Action", "Multi Action"] and seen["name"]
assert cm.sd_kind(k) == "Random x4" and cm.sd_title(k) == "Snd", (cm.sd_kind(k), cm.sd_title(k))
assert [cm.sd_title(p) for p in cm.sd_sounds(k)] == [cm.clean_name(o) for o in order]
assert [Path(p["Settings"]["path"]).stem for p in cm.sd_sounds(k)] == order
assert eg.tiles["1,0"].cget("text").startswith("Snd\nRandom x4")  # the grid shows it

# a folder pick = its sounds only (notes.txt left out), in order; Folder kind is named
app.picks.append(snd)
seen = new_key({})
app.menu_item(right_click(eg, "2,0"), "New folder(s) of sounds from a folder...")
check("new folder from a folder")
k = keys()["2,0"]
assert seen["title"] == "New key - 4 sound(s)" and seen["kinds"] == ["Folder"] and seen["name"], seen
assert k["UUID"] == cm.SD_FOLDER and cm.sd_title(k) == "Snd", k
assert titles(folder_keys(k), inside) == [cm.clean_name(o) for o in order]
print("new folder from a folder ok:", seen)

# a cancelled folder pick: no dialog, nothing changes
before = ed["pending"]()
when("New key", lambda w: problems.append("a dialog opened after a cancelled pick"), secs=1, expect=False)
app.menu_item(right_click(eg, "3,0"), "New folder(s) of sounds from a folder...")
app.pump(1.2)
check("cancelled folder")
assert ed["pending"]() == before and "3,0" not in keys()
print("cancelled folder pick ok")

# One key per sound: no name asked; keys on the free keys from here, in order
app.picks.append(explorer)
seen = new_key({})
app.menu_item(right_click(eg, "0,1"), "Fill free keys from here with files...")
check("fill free keys")
assert seen["kinds"] == ["One key per sound"] and not seen["name"], seen
assert titles(keys(), ["0,1", "1,1", "2,1", "3,1"]) == [cm.clean_name(o) for o in order]
print("fill free keys (one key per sound) ok:", seen)

# Folder per subfolder: no name asked; the folder is named after the picked folder ("Snd 2": this page has a "Snd"
# folder already and folder names don't repeat), sounds in order
app.picks.append(snd)
seen = new_key({})
app.menu_item(right_click(eg, "0,2"), "New folders, one per subfolder (mass import)...")
check("folder per subfolder")
k = keys()["0,2"]
assert seen["kinds"] == ["Folder per subfolder"] and not seen["name"], seen
assert k["UUID"] == cm.SD_FOLDER and cm.sd_title(k) == "Snd 2", k
assert titles(folder_keys(k), inside) == [cm.clean_name(o) for o in order]
print("folder per subfolder ok:", seen)

# one file = a Single sound, named after the file
app.picks.append([snd / "b.wav"])
seen = new_key({})
app.menu_item(right_click(eg, "1,2"), "New sound key...")
check("single sound")
k = keys()["1,2"]
assert seen["title"] == "New key - 1 sound(s)" and seen["kinds"] == ["Single sound"], seen
assert k["UUID"] == cm.SD_PLAY and cm.sd_title(k) == "B", k
print("single sound key ok")

# C) Edit key: Add folder... on a single sound asks Random / Multi (Random), new sounds copy its volume (40)
asked = lambda: [a for a in app.asked if a[0] == "askyesnocancel"]  # noqa: E731
app.picks.append(snd)
app.yes.append(True)  # Random Action


def add_then_ok(button, want):
    def do(w):
        press(w, button)
        assert want in labels(w), (want, labels(w))
        press(w, "OK")
    return do


when("Edit key", add_then_ok("Add folder...", "Random x5"))
app.menu_item(right_click(eg, "0,0"), "Edit key...")
check("edit key: add folder")
k = keys()["0,0"]
assert len(asked()) == 1, app.asked
assert cm.sd_kind(k) == "Random x5" and cm.sd_title(k) == "solo", cm.sd_kind(k)
assert [Path(s["Settings"]["path"]).stem for s in cm.sd_sounds(k)] == ["b"] + order
assert {s["Settings"]["volume"] for s in cm.sd_sounds(k)} == {40}
# Add sounds... on a Random: no question
app.picks.append(explorer)
when("Edit key", add_then_ok("Add sounds...", "Random x9"))
app.menu_item(right_click(eg, "0,0"), "Edit key...")
check("edit key: add sounds")
assert cm.sd_kind(keys()["0,0"]) == "Random x9" and len(asked()) == 1, app.asked
print("edit key: add folder (asks Random / Multi) + add sounds (no question) ok")

# D) the Stream Deck soundboard tab: add files, a folder onto key 2,0 (right-click), export the profile file
sb_page = app.tab("Stream Deck soundboard")
app.picks.append([snd / "t10.wav", snd / "b.wav"])
app.button("Add files...", sb_page).invoke()
app.picks.append(snd)
app.menu_item(right_click(grid_of(sb_page), "2,0"), "Add folder to this key...")
app.button("Send to Stream Deck", sb_page).invoke()
app.pump(0.2)
check("soundboard")
out = cm.SD_OUT
prof_file = next(out.glob("*.streamDeckProfile"))
assert app.launched == [str(prof_file)], app.launched
with zipfile.ZipFile(prof_file) as z:
    pages = [json.loads(z.read(n)) for n in z.namelist() if n.endswith("manifest.json")]
page = next(p for p in pages if p.get("Name") and "Controllers" in p)
kp = cm.sd_keypad(page)
assert cm.sd_kind(kp["2,0"]) == "Random x4" and cm.sd_title(kp["2,0"]) == "Snd", kp["2,0"]["States"]
assert [Path(s["Settings"]["path"]).stem for s in cm.sd_sounds(kp["2,0"])] == order  # folder order
assert list(kp) == ["2,0"]  # both listed sounds were in the folder, so they moved onto its key
print("soundboard: files + folder onto a key + export ok")

# E) every tab shown, then the window's close button (the editor's unsent changes thrown away when it asks)
want = ["Channel Mirror", "Stream Deck soundboard", "Stream Deck editor", "Import to folders", "Key mover",
        "Screen recorder", "VTube Studio backgrounds", "Music player", "OBS", "Transcribe", "Link",
        "Linked computers", "Phone remote", "Setup"]
assert app.tabs() == want, app.tabs()
for name in want:
    assert app.tab(name).winfo_viewable(), name
app.yes.append(False)  # "Stream Deck changes not sent - send them now?" No = throw them away
saved = app.close()
assert saved.get("tab") == "Setup", saved.get("tab")  # closed cleanly, settings saved (to the temp copy)
assert not app.sent and not problems, (app.sent, problems)
print("dialogs + soundboard + every tab through the main window ok")
