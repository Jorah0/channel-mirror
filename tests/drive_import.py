"""The Import to folders tab, the Key mover tab and the soundboard tab's folder option, in the main window, on synthetic
Stream Deck profiles (temp only; Stream Deck is never closed or written - sends are recorded by the harness).
Import: the editor's right-click "Import sounds into folders" puts Alpha / Page 1 / key 3,2 first; a folder of 7 sounds,
Loop, 3 per folder, 50 %; a key in use is refused; a second pick inside the Old folder; nothing overwritten.
Key mover: a sound with an icon + a folder (folders inside it too) copied to another device; icons go with the next
send; a move onto a key in use goes to the next free key; Undo; a folder can't move into itself; the back key stays.
The import tab drops a pick that got used meanwhile. Soundboard: one key per sound in folders of 3, Loop, the tip,
a refused drag, the exported profile, and the option kept when the window closes."""
import json
import os
import time
import wave
import zipfile

import numpy as np
import tkinter as tk
from tkinter import ttk

from harness import App, walk

app = App({"streamdeck": {"cols": 3, "rows": 2}})
cm = app.cm
started = []
os.startfile = lambda p, *a: started.append(str(p))  # the exported profile isn't opened in Stream Deck
tmp = app.tmp / "data"
snd = tmp / "Boom Pack"
snd.mkdir(parents=True)
names = [f"s{i}" for i in range(1, 8)]
for n in names:
    with wave.open(str(snd / f"{n}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000), w.writeframes(np.zeros(800, "<i2").tobytes())

sd = tmp / "SD"


def profile(dirname, name, dev, pages):
    prof = sd / "ProfilesV3" / f"{dirname}.sdProfile"
    for pid, pg in pages.items():
        (prof / "Profiles" / pid).mkdir(parents=True)
        (prof / "Profiles" / pid / "manifest.json").write_text(json.dumps(pg))
    (prof / "manifest.json").write_text(json.dumps({"Device": {"Model": "m", "UUID": dev}, "Name": name, "Pages": {
        "Current": "p", "Default": "x", "Pages": [next(iter(pages)).lower()]}}))
    return prof


# A: 3x2 deck. page 1: sound (with an icon), stop key, folder "Old"; Old's page: Parent + old1 (with an icon)
okey, oid, opg, _ = cm.sd_folder("Old", [dict(cm.sd_play(snd / "s1.wav", "old1"), States=[
    {"Title": "old1", "Image": "Images/OLDICON.png"}])], 3, 2)
iconic = cm.sd_play(snd / "s1.wav", "a")
iconic["States"] = [{"Title": "a", "Image": "Images/AICON.png"}]
A = profile("A", "Alpha", "devA", {"PAGEA": {"Controllers": [{"Type": "Keypad", "Actions": {
    "0,0": iconic, "1,0": cm.sd_stop_key(), "2,0": okey}}]}, oid.upper(): opg})
(A / "Profiles" / "PAGEA" / "Images").mkdir()
(A / "Profiles" / "PAGEA" / "Images" / "AICON.png").write_bytes(b"A-ICON")
(A / "Profiles" / oid.upper() / "Images").mkdir()
(A / "Profiles" / oid.upper() / "Images" / "OLDICON.png").write_bytes(b"OLD-ICON")
# B: a different device, 4x2; page 1 has a key at 0,0
B = profile("B", "Beta", "devB", {"PAGEB": {"Controllers": [{"Type": "Keypad", "Actions": {
    "0,0": cm.sd_stop_key()}}]}})
cm.SD_DIR = sd
cm.sd_devices = lambda *a, **k: {"a": ("m", "devA", 3, 2), "b": ("m", "devB", 4, 2)}
cm.sd_connected = lambda: set()  # no USB query
app.start()
deck = app.api("editor")
mover = app.api("mover")
pA = A / "Profiles" / "PAGEA" / "manifest.json"
pOld = A / "Profiles" / oid.upper() / "manifest.json"
pB = B / "Profiles" / "PAGEB" / "manifest.json"
alpha = next(p for p in deck["profiles"]() if "Alpha" in p)
beta = next(p for p in deck["profiles"]() if "Beta" in p)


def grid_on(page):
    """The key grid(s) shown on a main-window tab."""
    return [g for g in cm.DeckGrid.shown if str(g.frame).startswith(str(page) + ".")]


clock = [int(time.monotonic() * 1000) % 2 ** 30]


def click(g, pos):
    """A left click on a key of a grid. Each click stamped a second after the last: two clicks on one key aren't a
    double-click (unstamped generated clicks all have time 0, so Tk takes the second for one)."""
    t = g.tiles[pos]
    clock[0] += 1000
    t.event_generate("<ButtonPress-1>", x=4, y=4, time=clock[0])
    t.event_generate("<ButtonRelease-1>", x=4, y=4, time=clock[0] + 50)
    app.pump(0.02)


def right_click(g, pos):
    """A right-click on a key -> the menu it opens (taken instead of shown: a shown menu waits for the mouse)."""
    menus, real = [], tk.Menu.tk_popup
    tk.Menu.tk_popup = lambda m, *a, **k: menus.append(m)
    try:
        g.tiles[pos].event_generate("<Button-3>", x=4, y=4)
    finally:
        tk.Menu.tk_popup = real
    assert menus, "no menu"
    return menus[-1]


def combo(within, var=None, has=None):
    """The dropdown bound to var (or offering the value `has`)."""
    return next(c for c in walk(within) if isinstance(c, ttk.Combobox) and (
        str(c.cget("textvariable")) == str(var) if var is not None else has in c.tk.splitlist(c.cget("values"))))


def choose(cb, value):
    assert value in cb.tk.splitlist(cb.cget("values")), (value, cb.cget("values"))
    cb.set(value)
    cb.event_generate("<<ComboboxSelected>>")
    app.pump(0.05)


def text(g, pos):
    return str(g.tiles[pos].cget("text"))


# ---- Import to folders tab: the editor's right-click on Alpha / Page 1 / key 3,2 opens it with that key first
ed = app.tab("Stream Deck editor")
eg = grid_on(ed)[0]
assert deck["current"]() == (alpha, pA), deck["current"]()
app.menu_item(right_click(eg, "2,1"), "Import sounds into folders (pick keys, any page)...")
app.pump(0.1)
imp = app.root.nametowidget(app.nb.select())
assert app.nb.tab(imp, "text") == "Import to folders"
g = grid_on(imp)[0]
assert text(g, "2,1") == "Folder 1", text(g, "2,1")
app.picks.append(snd)
app.button("Add folder...", imp).invoke()  # 7 sounds
assert len(app.api("import")["files"]) == 7
next(r for r in walk(imp) if isinstance(r, ttk.Radiobutton) and r.cget("text").startswith("Loop")).invoke()
next(s for s in walk(imp) if isinstance(s, ttk.Spinbox) and s.cget("to") == 5.0).set(3)  # 3 per folder
next(s for s in walk(imp) if isinstance(s, ttk.Spinbox) and s.cget("to") == 400.0).set(50)  # scale 50%
app.pump(0.05)
click(g, "0,0")  # in use: refused
assert any("in use - pick a free" in str(lb.cget("text")) for lb in walk(imp) if isinstance(lb, ttk.Label))
choose(combo(imp, has="Folder: Old"), "Folder: Old")
assert text(g, "1,0").endswith("(in use)"), text(g, "1,0")
click(g, "2,1")  # folder 2: inside Old
assert text(g, "2,1") == "Folder 2", text(g, "2,1")
app.button("Import", imp).invoke()
pend = deck["pending"]()
main, inner = pend[pA]["Controllers"][0]["Actions"], pend[pOld]["Controllers"][0]["Actions"]
assert cm.sd_title(main["2,1"]) == "Boom Pack" and cm.sd_title(inner["2,1"]) == "Boom Pack 2"
assert cm.sd_title(inner["2,0"]) == "Boom Pack 3" and cm.sd_title(inner["1,0"]) == "old1"  # nothing overwritten
order, modes, vols = [], set(), set()
for kp, k in ((main, "2,1"), (inner, "2,1"), (inner, "2,0")):
    fk = pend[A / "Profiles" / kp[k]["Settings"]["ProfileUUID"].upper() / "manifest.json"]["Controllers"][0]["Actions"]
    for x in sorted(fk, key=cm.sd_order):
        if fk[x]["UUID"] == cm.SD_PLAY:
            order.append(cm.sd_title(fk[x]))
            modes.add(fk[x]["Settings"]["actionType"])
            vols.add(fk[x]["Settings"]["volume"])
assert order == [n.upper() for n in names] and modes == {cm.SD_MODES.index("Loop / Stop")} and vols == {50}, (
    order, modes, vols)
assert not app.errors and not app.boxes and not app.sent, (app.errors, app.boxes, app.sent)
print("import tab ok")

# ---- Key mover: copy Alpha's iconic sound + the Old folder to Beta (another device), starting at key 2,1
mv = app.tab("Key mover")
L, R = mover["sides"]
lg, rg = L["grid"], R["grid"]
choose(combo(mv, L["prof"]), alpha)
choose(combo(mv, R["prof"]), beta)
click(lg, "0,0")
click(lg, "2,0")  # the Old folder (now holding Boom Pack 2 and 3 too)
click(rg, "2,1")  # start here; keep layout: 0,0 -> 2,1, 2,0 -> 4,1 is off this 4x2 deck -> next free
app.button("Copy  >>", mv).invoke()
assert not app.errors, app.errors
pend = deck["pending"]()
bk = pend[pB]["Controllers"][0]["Actions"]
assert cm.sd_title(bk["2,1"]) == "a" and cm.sd_title(bk["0,0"]) == "STOP"  # the existing key kept
moved_folder = next(a for k, a in bk.items() if a.get("UUID") == cm.SD_FOLDER)
assert cm.sd_title(moved_folder) == "Old" and moved_folder["Settings"]["ProfileUUID"] != oid
newp = B / "Profiles" / moved_folder["Settings"]["ProfileUUID"].upper() / "manifest.json"
inside = pend[newp]["Controllers"][0]["Actions"]
assert cm.sd_title(inside["1,0"]) == "old1" and {cm.sd_title(a) for a in inside.values()} >= {"Boom Pack 2",
                                                                                               "Boom Pack 3"}
nested = [a for a in inside.values() if a.get("UUID") == cm.SD_FOLDER]  # Boom Pack 2/3 copied as Beta's own pages
assert nested and all(B / "Profiles" / a["Settings"]["ProfileUUID"].upper() / "manifest.json" in pend for a in nested)
assert pend[pA]["Controllers"][0]["Actions"]["0,0"]["ActionID"] != bk["2,1"]["ActionID"]  # its own key
# icons wait in the editor until sent: the editor's Save to Stream Deck sends them with the pages
assert not app.sent, "nothing is sent before Save"
app.button("Save to Stream Deck (", app.tab("Stream Deck editor"), startswith=True).invoke()  # "(N pages changed)"
assert app.wait(lambda: app.sent and not deck["saving"](), 15), "the send didn't happen"
send = app.sent[-1][0]
assert send.get(B / "Profiles" / "PAGEB" / "Images" / "AICON.png") == b"A-ICON", [p for p in send if "png" in str(p)]
assert send.get(newp.parent / "Images" / "OLDICON.png") == b"OLD-ICON"
assert pB in send and newp in send, "the pages go with their icons"
sent_once = len(app.sent)
print("mover copy ok")

# ---- Key mover: move within Beta's page onto a key in use -> next free; then undo
mv = app.tab("Key mover")
choose(combo(mv, R["prof"]), beta)
before = json.dumps(deck["pending"]().get(pB), sort_keys=True)
click(rg, "2,1")  # the copied sound "a"
choose(combo(mv, L["prof"]), beta)
click(lg, "0,0")  # target: key 1,1 is in use (STOP) -> the next free key after it
app.button("<<  Move", mv).invoke()
bk = deck["pending"]()[pB]["Controllers"][0]["Actions"]
assert "2,1" not in bk and cm.sd_title(bk["0,0"]) == "STOP"
landed = [k for k, a in bk.items() if cm.sd_title(a) == "a"]
assert landed and landed[0] not in ("0,0",), bk.keys()
app.button("Undo", mv).invoke()
assert json.dumps(deck["pending"]().get(pB), sort_keys=True) == before
assert not app.errors, app.errors
print("mover move + undo ok")


# review fixes. a folder can't be moved into its own page
def status_of():
    return next(lb for lb in walk(mv) if isinstance(lb, ttk.Label) and "Status" in str(lb.cget("style"))).cget("text")


fkey = next(k for k, a in deck["pending"]()[pB]["Controllers"][0]["Actions"].items() if a.get("UUID") == cm.SD_FOLDER)
choose(combo(mv, R["prof"]), beta)
choose(combo(mv, L["prof"]), beta)
choose(combo(mv, L["page"]), next(n for n, _ in L["pages"]() if n.startswith("Folder: Old")))
snapshot = json.dumps({str(k): v for k, v in deck["pending"]().items()}, sort_keys=True)
click(rg, fkey)
app.button("<<  Move", mv).invoke()
assert "can't be moved into itself" in status_of() and json.dumps(
    {str(k): v for k, v in deck["pending"]().items()}, sort_keys=True) == snapshot
# the back key stays put
app.button("Select none", rg.frame.master).invoke()
assert not R["sel"]
click(lg, "0,0")  # the Parent Folder key inside Old
app.button("Move  >>", mv).invoke()
assert "stays where it is" in status_of(), status_of()
app.button("Select none", lg.frame.master).invoke()
assert not L["sel"]
# the import tab drops a pick that got used meanwhile (here: by the mover). The pick comes from the editor's
# right-click on Beta's page
free = next(k for k in cm.sd_free(deck["keys"](pB), 4, 2))
ed = app.tab("Stream Deck editor")
choose(combo(ed, has=beta), beta)
assert deck["current"]() == (beta, pB), deck["current"]()
app.menu_item(right_click(eg, free), "Import sounds into folders (pick keys, any page)...")
app.pump(0.1)
assert app.nb.tab(app.nb.select(), "text") == "Import to folders"
assert text(g, free) == "Folder 1", text(g, free)
mv = app.tab("Key mover")
choose(combo(mv, L["page"]), next(n for n, p in L["pages"]() if p == pB))
choose(combo(mv, L["prof"]), alpha)
click(lg, "1,0")  # Alpha's STOP key
choose(combo(mv, R["page"]), next(n for n, p in R["pages"]() if p == pB))
click(rg, free)
app.button("Copy  >>", mv).invoke()
assert cm.sd_title(deck["keys"](pB)[free]) == "STOP"
before_imp = json.dumps(deck["pending"]().get(pB), sort_keys=True)
imp = app.tab("Import to folders")
assert text(g, free).endswith("(in use)"), text(g, free)  # the pick is gone, the key shows what's on it now
app.button("Import", imp).invoke()
assert [b[:2] for b in app.boxes] == [("showinfo", "Import")] and (
    "Pick a free key" in app.boxes[0][2] or "in use now" in app.boxes[0][2]), app.boxes
assert json.dumps(deck["pending"]().get(pB), sort_keys=True) == before_imp  # nothing overwritten
app.boxes.clear()
assert not app.errors and len(app.sent) == sent_once, (app.errors, len(app.sent))
print("review fixes ok")

# ---- soundboard tab: one key per sound, in folders of 3, Loop, export file
bf = app.tab("Stream Deck soundboard")
app.picks.append([snd / f"{n}.wav" for n in names])
app.button("Add files...", bf).invoke()
next(c for c in walk(bf) if isinstance(c, ttk.Checkbutton) and c.cget("text").startswith("One key per sound")).invoke()
next(s for s in walk(bf) if isinstance(s, ttk.Spinbox) and s.cget("to") == 99.0).set(3)
next(r for r in walk(bf) if isinstance(r, ttk.Radiobutton) and r.cget("text") == "Loop").invoke()
app.pump(0.05)
sg = grid_on(bf)[0]
assert text(sg, "0,0") == "Sounds\nFolder x3" and text(sg, "2,0") == "Sounds 3\nFolder x1", text(sg, "0,0")
# hovering a key shows what it holds
sg.tiles["1,0"].event_generate("<Enter>")


def tip():
    return [str(lb.cget("text")) for t in walk(sg.tiles["1,0"]) if isinstance(t, tk.Toplevel)
            for lb in t.winfo_children()]


assert app.wait(lambda: tip(), 3), "no tip"
assert tip()[0].startswith("Key 2,1: folder 'Sounds 2' with 3 sound(s)"), tip()
sg.tiles["1,0"].event_generate("<Leave>")
# dragging a key onto another is refused politely in folder mode (a real drag: the window on top for it)
app.root.attributes("-topmost", True)
app.root.lift()
app.pump(0.2)
a, b = sg.tiles["0,0"], sg.tiles["1,0"]
ax, ay = a.winfo_rootx() + 5, a.winfo_rooty() + 5
bx, by = b.winfo_rootx() + b.winfo_width() // 2, b.winfo_rooty() + b.winfo_height() // 2
clock[0] += 1000
a.event_generate("<ButtonPress-1>", x=5, y=5, rootx=ax, rooty=ay, time=clock[0])
a.event_generate("<B1-Motion>", x=bx - ax + 5, y=by - ay + 5, rootx=bx, rooty=by, time=clock[0] + 100)
a.event_generate("<ButtonRelease-1>", x=bx - ax + 5, y=by - ay + 5, rootx=bx, rooty=by, time=clock[0] + 200)
app.pump(0.1)
app.root.attributes("-topmost", False)
said = next(str(lb.cget("text")) for lb in walk(bf) if isinstance(lb, ttk.Label) and "Status" in str(lb.cget("style")))
assert "reorder the sounds in the list instead" in said, said
assert text(sg, "0,0") == "Sounds\nFolder x3" and text(sg, "1,0") == "Sounds 2\nFolder x3"  # nothing swapped
app.button("Send to Stream Deck", bf).invoke()
out = next(cm.SD_OUT.glob("*.streamDeckProfile"))
assert started == [str(out)], started  # opened for Stream Deck's import prompt
with zipfile.ZipFile(out) as z:
    pages = {n: json.loads(z.read(n)) for n in z.namelist() if n.endswith("manifest.json")}
    assert sum(n.endswith(".wav") for n in z.namelist()) == 7
top = next(v for v in pages.values() if v.get("Name") and "Controllers" in v)
keys = cm.sd_keypad(top)
assert [cm.sd_title(keys[k]) for k in sorted(keys, key=cm.sd_order)] == ["Sounds", "Sounds 2", "Sounds 3"]
plays = [a for v in pages.values() if "Controllers" in v and v is not top for a in cm.sd_keypad(v).values()
         if a["UUID"] == cm.SD_PLAY]
assert len(plays) == 7 and {a["Settings"]["actionType"] for a in plays} == {cm.SD_MODES.index("Loop / Stop")}
assert not app.errors and not app.boxes and len(app.sent) == sent_once, (app.errors, app.boxes)

# the window's close button: the unsent editor changes are offered (No = throw them away); the option is kept
app.yes.append(False)
saved = app.close()
assert any(q[1] == "Stream Deck changes not sent" for q in app.asked), app.asked
assert len(app.sent) == sent_once, "No = nothing sent"
sc = saved["streamdeck"]
assert sc["folders"] is True and sc["folder_per"] == 3 and sc["folder_play"] == "Loop / Stop", sc
print("drive import + mover + soundboard ok")
