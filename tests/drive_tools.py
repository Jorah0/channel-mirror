"""Every Stream Deck editor tool through its real controls in the main window, plus selection, navigation, undo /
redo / revert, cell editing, Save and auto-send, and the soundboard tab's Check levels and direct install.
Synthetic profile + real audio in a temp dir; 'sending' writes into that temp dir (never the real Stream Deck)."""
import json
import shutil
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from tkinter import ttk

from harness import App

tmp = Path(tempfile.mkdtemp(prefix="cm_tools_"))
snd = tmp / "sounds"
(snd / "sub").mkdir(parents=True)


def tone(path, amp, secs=1.0):
    t = np.arange(int(44100 * secs)) / 44100
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(44100)
        w.writeframes((amp * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2").tobytes())


tone(snd / "loud.wav", 0.8)
tone(snd / "quiet.wav", 0.1)
tone(snd / "sfx.wav", 0.3)
tone(snd / "sub" / "missing.wav", 0.3)
app = App()
cm = app.cm
sd = tmp / "SD"
prof = sd / "ProfilesV3" / "P.sdProfile"
fkey, fid, fpg, _ = cm.sd_folder("Sub", [cm.sd_play(snd / "sfx.wav", "sfx")], 5, 3)
page1 = {"Controllers": [{"Type": "Keypad", "Actions": {
    "0,0": cm.sd_play(snd / "loud.wav", "loud"), "1,0": cm.sd_play(snd / "quiet.wav", "quiet"),
    "2,0": cm.sd_wrap("Random Action", "rnd", [cm.sd_play(snd / "loud.wav", "l"), cm.sd_play(snd / "quiet.wav", "q")]),
    "3,0": cm.sd_stop_key(), "4,0": fkey, "0,1": cm.sd_play(Path("C:/gone/missing.wav"), "lost")}}]}
for pid, pg in (("PAGE1", page1), (fid.upper(), fpg), ("PAGE2", {"Controllers": [{"Type": "Keypad", "Actions": {}}]})):
    (prof / "Profiles" / pid).mkdir(parents=True)
    (prof / "Profiles" / pid / "manifest.json").write_text(json.dumps(pg))
(prof / "manifest.json").write_text(json.dumps({"Device": {"Model": "m", "UUID": "dev"}, "Name": "Tools",
                                                "Pages": {"Current": "page1", "Default": "x", "Pages": ["page1", "page2"]}}))
p1 = prof / "Profiles" / "PAGE1" / "manifest.json"
cm.SD_DIR = sd
cm.sd_devices = lambda *a, **k: {"x": ("m", "dev", 5, 3)}
cm.SD_EXE = tmp / "StreamDeck.exe"  # "installed" (an empty file nothing runs): the soundboard installs directly
cm.SD_EXE.write_bytes(b"")
# sending = written into the temp profile (backups to temp too), recorded in app.sent; Stream Deck isn't touched
cm.sd_push = lambda writes, folders, *a, **k: (app.sent.append(dict(writes)),
                                               cm.sd_save(writes, folders, sd, tmp / "bk"))[1]
app.start()
ed = app.tab("Stream Deck editor")
deck = app.api("editor")
grid = next(g for g in cm.DeckGrid.shown if str(g.frame).startswith(str(ed) + "."))
T = [int(time.time() * 1000) % 2_000_000_000]


def stamp(dt=1000):
    """Event times far apart, so two clicks are never taken for a double-click (and a double-click is one)."""
    T[0] += dt
    return T[0]


def btn(text, w=None, start=False):
    return next(b for b in app.walk(w or ed) if isinstance(b, (ttk.Button, ttk.Radiobutton, ttk.Checkbutton))
                and (str(b.cget("text")).startswith(text) if start else str(b.cget("text")) == text))


def shown(cls):
    app.pump()
    return [w for w in app.walk(ed) if isinstance(w, cls) and w.winfo_ismapped()]


def combo(has, value):
    cb = next(c for c in shown(ttk.Combobox) if has in c.cget("values"))
    cb.set(value)
    app.pump()


def click(pos, ctrl=False):
    t, w = stamp(), grid.tiles[pos]
    w.event_generate("<ButtonPress-1>", x=10, y=10, time=t, state=0x4 if ctrl else 0)
    w.event_generate("<ButtonRelease-1>", x=10, y=10, time=t + 10, state=0x4 if ctrl else 0)


def double(w, x, y):
    t = stamp()
    for kind, dt in (("ButtonPress-1", 0), ("ButtonRelease-1", 10), ("ButtonPress-1", 80), ("ButtonRelease-1", 90)):
        w.event_generate(f"<{kind}>", x=x, y=y, time=t + dt)
    app.pump()


def select(*keys):
    btn("None").invoke()  # start from nothing selected (clicking the only selected key toggles it off)
    click(keys[0])
    for k in keys[1:]:
        click(k, ctrl=True)  # Ctrl+click adds
    app.pump()


def kp():
    return deck["pending"]().get(p1, json.loads(p1.read_text()))["Controllers"][0]["Actions"]


def settings(k):
    return [s["Settings"] for s in cm.sd_sounds(kp()[k])]


def apply():
    btn("Apply", start=True).invoke()
    app.pump()
    assert not app.errors and not app.boxes, (app.errors, app.boxes)


def goal(name):
    btn(name).invoke()
    app.pump()


seen = []  # dialogs answered: (title, what was in them)


def answer(title, act, secs=10):
    """Answer the dialog whose title starts with `title` once it opens: act(window) -> noted in `seen`. Set up
    before the action that opens it (a modal dialog waits in its own loop, which runs this check)."""
    t0 = time.time()

    def poll():
        win = next((w for w in app.windows() if str(w.title()).startswith(title)), None)
        if win is not None:
            return seen.append((win.title(), act(win)))
        if time.time() - t0 < secs:
            app.root.after(40, poll)
    app.root.after(40, poll)


def level_report(win):
    """The Sound levels list: its rows and summary; Close (only looked, nothing changes)."""
    tv = next(w for w in app.walk(win) if isinstance(w, ttk.Treeview))
    said = next(str(w.cget("text")) for w in app.walk(win) if isinstance(w, ttk.Label) and "checked" in
                str(w.cget("text")))
    rows = len(tv.get_children())
    app.button("Close", win).invoke()
    return rows, said


# --- select buttons and the apply count
btn("Sounds").invoke()
assert btn("Apply", start=True).cget("text") == "Apply to 4 keys", btn("Apply", start=True).cget("text")
btn("Missing").invoke()
assert btn("Apply", start=True).cget("text") == "Apply to 1 key"
btn("Multi / Random").invoke()
assert btn("Apply", start=True).cget("text") == "Apply to 1 key"
btn("All").invoke()
assert btn("Apply", start=True).cget("text") == "Apply to 6 keys"
btn("None").invoke()
assert btn("Apply", start=True).cget("text") == "Apply"
print("select buttons ok")

# --- purpose preset
select("0,0")
assert btn("Apply", start=True).cget("text") == "Apply to 1 key"
goal("Set them up for a purpose")
combo("Stinger / one-shot (press restarts it)", "Stinger / one-shot (press restarts it)")
apply()
assert settings("0,0")[0]["actionType"] == cm.SD_MODES.index("Play / Restart")
# --- playback and fade, on a single key + every sound inside the Random
select("0,0", "2,0")
assert btn("Apply", start=True).cget("text") == "Apply to 2 keys"
goal("Playback and fade")
combo("Loop / Stop", "Loop / Stop")
combo("Fade Out", "Fade Out")
next(c for c in shown(ttk.Combobox) if c.cget("values") == ("Keep", "1", "2", "3", "4", "5")).set("3")
apply()
for k in ("0,0", "2,0"):
    assert all((s["actionType"], s["fadeType"], s["fadeLen"]) == (3, 2, 3) for s in settings(k)), settings(k)
assert settings("1,0")[0]["actionType"] == 0  # not selected: untouched
print("presets + playback ok")

# --- volume: set, change by, scale, match loudness, tune, check
select("1,0")
goal("Volume")
btn("Set to").invoke()
next(s for s in shown(ttk.Scale)).set(55)
apply()
assert settings("1,0")[0]["volume"] == 55
btn("Change by (+/-)").invoke()
next(s for s in shown(ttk.Spinbox) if s.cget("from") == -100.0).set("-10")
apply()
assert settings("1,0")[0]["volume"] == 45
btn("Scale by %").invoke()
next(s for s in shown(ttk.Spinbox) if s.cget("to") == 400.0).set("200")
apply()
assert settings("1,0")[0]["volume"] == 90
select("0,0", "1,0")
btn("Set to").invoke()
next(s for s in shown(ttk.Scale)).set(100)
apply()
btn("Match loudness").invoke()
apply()
loud_v, quiet_v = settings("0,0")[0]["volume"], settings("1,0")[0]["volume"]
assert quiet_v == 100 and loud_v < 30, (loud_v, quiet_v)  # 0.8 vs 0.1 amplitude: ~18 dB apart
btn("Tune to level").invoke()
combo("Everything at my effects level", "Everything at my effects level")
apply()
lvl = cm.sd_listen(snd / "loud.wav")["level"]
want = max(1, min(100, round(100 * 10 ** ((cm.SD_LEVELS["effect"] - lvl) / 20))))
assert settings("0,0")[0]["volume"] == want, (settings("0,0")[0]["volume"], want)
tuned = (settings("0,0"), settings("1,0"))
btn("Check levels").invoke()
answer("Sound levels", level_report)
apply()
assert seen and seen[-1][0] == "Sound levels" and seen[-1][1][0] == 2, seen  # both sounds listed
assert seen[-1][1][1].startswith("2 sound(s) checked against Everything at my effects level"), seen[-1]
assert (settings("0,0"), settings("1,0")) == tuned  # only looked: Close changes nothing
print("volume tools ok")

# --- output device
goal("Output device")
outs = cm.sd_output_choices()
dev = outs[1] if len(outs) > 1 else cm.SD_DEFAULT_OUT
next(c for c in shown(ttk.Combobox) if str(c.cget("state")) != "readonly").set(dev)  # the device box
apply()
assert settings("0,0")[0]["outputType"] == cm.sd_out(dev)
print("output ok:", dev[:40])

# --- names and look
select("0,0")
goal("Key names and look")
combo("File name", "File name")
next(e for e in shown(ttk.Entry) if not isinstance(e, ttk.Combobox)).insert(0, "> ")  # Add before
combo("Hide", "Hide")
combo("14", "14")
combo("middle", "top")
apply()
st0 = kp()["0,0"]["States"][0]
assert st0["Title"] == "> Loud" and st0["ShowTitle"] is False and st0["FontSize"] == 14 and \
    st0["TitleAlignment"] == "top", st0
print("names + look ok")

# --- arrange: combine, split, move, stop key, delete
goal("Arrange keys")
select("0,0", "1,0")
btn("Combine selected into one").invoke()
next(e for e in shown(ttk.Entry) if not isinstance(e, ttk.Combobox) and str(e.cget("width")) == "14").insert(0, "Mix")
apply()
assert cm.sd_kind(kp()["0,0"]) == "Random x2" and cm.sd_title(kp()["0,0"]) == "Mix" and "1,0" not in kp()
select("0,0")
btn("Split Multi / Random keys into single keys").invoke()
apply()
assert cm.sd_kind(kp()["0,0"]) == "Sound" and cm.sd_kind(kp()["1,0"]) == "Sound"
select("1,0")
btn("Move the selected key to (col,row)").invoke()
slot = next(e for e in shown(ttk.Entry) if not isinstance(e, ttk.Combobox) and str(e.cget("width")) == "6")
slot.delete(0, "end")
slot.insert(0, "5,3")
apply()
assert "1,0" not in kp() and cm.sd_kind(kp()["4,2"]) == "Sound"
btn("Add a 'Stop all audio' key at (col,row)").invoke()
slot = next(e for e in shown(ttk.Entry) if not isinstance(e, ttk.Combobox) and str(e.cget("width")) == "6")
slot.delete(0, "end")
slot.insert(0, "1,3")
apply()
assert kp()["0,2"]["UUID"] == cm.SD_STOP
select("0,2")
btn("Delete the selected keys").invoke()
apply()
assert "0,2" not in kp() and app.asked[-1][:2] == ("askyesno", "Delete keys"), app.asked[-1]
print("arrange ok")

# --- fix missing sound files
select("0,1")
goal("Fix missing sound files")
folder_e = next(e for e in shown(ttk.Entry) if not isinstance(e, ttk.Combobox))
folder_e.delete(0, "end")
folder_e.insert(0, str(snd))
apply()
assert Path(settings("0,1")[0]["path"]) == snd / "sub" / "missing.wav"
print("fix missing ok")

# --- jump to Multi / Random, and folders: open (double-click the key), back, next page, previous
jump = next(c for c in app.walk(ed) if isinstance(c, ttk.Combobox) and any("Random" in str(v) for v in c.cget("values")))
jump.set(jump.cget("values")[0])
app.pump()
assert btn("Apply", start=True).cget("text") == "Apply to 1 key"
double(grid.tiles["4,0"], 10, 10)  # open the folder
assert any(cm.sd_title(a) == "sfx" for a in deck["keys"](deck["current"]()[1]).values())
btn("Back (out of folder)").invoke()
app.pump()
assert deck["current"]()[1] == p1
btn("Next >").invoke()
app.pump()
assert deck["current"]()[1].parent.name == "PAGE2"
btn("< Prev").invoke()
app.pump()
assert deck["current"]()[1] == p1
print("navigation ok")

# --- undo / redo
before = json.dumps(kp(), sort_keys=True)
select("2,0")
goal("Volume")
btn("Set to").invoke()
next(s for s in shown(ttk.Scale)).set(33)
apply()
assert {s["volume"] for s in settings("2,0")} == {33}
btn("Undo").invoke()
app.pump()
assert json.dumps(kp(), sort_keys=True) == before
btn("Redo").invoke()
app.pump()
assert {s["volume"] for s in settings("2,0")} == {33}
print("undo / redo ok")

# --- edit a cell in place: the volume of the Random's first sound in the list (double-click it, type, Enter)
details = next(w for w in app.walk(ed) if isinstance(w, ttk.Treeview) and "volume" in w.cget("columns"))
select("2,0")
row_id = next(i for i in details.get_children() if i.startswith("s|2,0|"))
col = "#" + str(list(details.cget("columns")).index("volume") + 1)
details.see(row_id)
app.pump()
x, y, w_, h_ = details.bbox(row_id, col)
double(details, x + w_ // 2, y + h_ // 2)
cell = next(e for e in details.winfo_children() if isinstance(e, ttk.Entry))
cell.focus_force()
app.pump()
cell.delete(0, "end")
cell.insert(0, "61")
# the Enter that confirms the cell is the cell's own: it must not also reach the window's Enter shortcut (Edit
# selected) and open an "Edit key" window (it did, until the fix). A stray one is cancelled so it can't hold the test.
answer("Edit key", lambda win: app.button("Cancel", win).invoke(), secs=3)
cell.event_generate("<Return>")
app.pump(0.4)
assert settings("2,0")[0]["volume"] == 61, settings("2,0")
stray = [t for t, _ in seen if t.startswith("Edit key")]
assert not stray, f"Enter in a cell also opened {stray}"
print("cell edit ok (Enter kept the cell, opened nothing else)")

# --- send (Save to Stream Deck), then auto-send, then revert
assert deck["pending"]()
assert not app.sent
btn("Save to Stream Deck", start=True).invoke()
assert app.wait(lambda: not deck["saving"](), 15), "sending didn't finish"
assert app.sent and not deck["pending"](), (len(app.sent), list(deck["pending"]()))
assert json.loads(p1.read_text())["Controllers"][0]["Actions"]["2,0"]["Actions"][0]["Actions"][0]["Settings"][
    "volume"] == 61
assert any(f.suffix == ".zip" for f in (tmp / "bk").iterdir())  # backed up first
n_sent = len(app.sent)
btn("Send changes automatically").invoke()  # on
select("2,0")
goal("Volume")
btn("Set to").invoke()
next(s for s in shown(ttk.Scale)).set(44)
apply()
assert app.wait(lambda: len(app.sent) > n_sent and not deck["saving"]() and not deck["pending"](), 15), "auto-send"
on_disk = json.loads(p1.read_text())["Controllers"][0]["Actions"]["2,0"]
assert {s["Settings"]["volume"] for s in cm.sd_sounds(on_disk)} == {44}
btn("Send changes automatically").invoke()  # off again
next(s for s in shown(ttk.Scale)).set(12)
apply()
assert deck["pending"]()
n_sent = len(app.sent)
btn("Revert").invoke()
app.pump(1.8)  # longer than auto-send's wait: it's off, so nothing goes
assert not deck["pending"]() and len(app.sent) == n_sent
print("save + auto-send + revert ok")

# --- soundboard tab: Check levels, then direct install (no import prompt)
sb = app.tab("Stream Deck soundboard")
app.picks.append([snd / "loud.wav", snd / "quiet.wav"])
next(b for b in app.walk(sb) if isinstance(b, ttk.Button) and str(b.cget("text")) == "Add files..."
     and str(b.cget("style")) != "Tool.TButton").invoke()  # the list's Add files (not the key's)
answer("Sound levels", level_report)
app.button("Check levels...", sb).invoke()
app.pump()
assert seen[-1][0] == "Sound levels" and seen[-1][1][0] == 2, seen
n_sent = len(app.sent)
app.button("Send to Stream Deck", sb).invoke()
assert app.wait(lambda: len(app.sent) > n_sent, 15), "the soundboard wasn't installed"
tops = [d for d in app.sent[-1].values() if isinstance(d, dict) and d.get("Name") == "Soundboard" and "Controllers" in d]
assert tops, app.sent[-1].keys()
assert sorted(cm.sd_title(a) for a in cm.sd_keypad(tops[0]).values()) == ["Loud", "Quiet"]
assert not app.errors and not app.boxes, (app.errors, app.boxes)
print("soundboard check levels + direct install ok")

saved = app.close()  # nothing unsent in the editor: no question
assert not any(a[1] == "Stream Deck changes not sent" for a in app.asked), app.asked
assert saved["sd_autosend"] is False and saved["tab"] == "Stream Deck soundboard", saved
shutil.rmtree(tmp, ignore_errors=True)
print("drive tools ok")
