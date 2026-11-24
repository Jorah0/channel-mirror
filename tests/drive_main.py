"""The whole app on this PC: Channel Mirror tab Add files -> Run -> output files; soundboard 'Add Channel Mirror
outputs'; an unsent editor change, then closing and throwing it away. Settings: a temp copy with auto-send off;
sending to Stream Deck is blocked; the real profiles must be unchanged afterwards."""
import ctypes, json, os, shutil, subprocess, sys, tempfile, wave
import faulthandler  # never stuck: still running after CM_TEST_TIMEOUT s (default 300) -> where it is, exit
faulthandler.dump_traceback_later(int(__import__("os").environ.get("CM_TEST_TIMEOUT", "300")), exit=True)
from pathlib import Path
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # default: this repo
sys.path.insert(0, REPO)
ctypes.windll.shcore.SetProcessDpiAwareness(1)
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import channel_mirror as cm

errors, info, closing = [], [], []
tk.Tk.report_callback_exception = lambda self, *a: errors.append(a)
cm.sd_push = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send"))
tmp = Path(tempfile.mkdtemp())
cfg = json.loads((Path.home() / ".channel_mirror.json").read_text()) if (Path.home() / ".channel_mirror.json").is_file() else {}
cfg.update(sd_autosend=False, out_dir=str(tmp / "out"), tab=0, close_to_taskbar=False)
cfg.pop("obs", None)  # never the user's real OBS (it would connect by itself if it was connected)
cfg.pop("link", None)  # nor their linked computers (receiving would write the real Incoming / nonce files)
cm.LINK_INBOX = tmp / "Incoming"
cm.SETTINGS = tmp / "settings.json"
cm.SETTINGS.write_text(json.dumps(cfg))
src = tmp / "song.wav"
t = np.arange(44100) / 44100
pcm = (np.stack([0.8 * np.sin(2 * np.pi * 440 * t), 0.05 * np.sin(2 * np.pi * 660 * t)], 1) * 32767).astype("<i2")
with wave.open(str(src), "wb") as w:
    w.setnchannels(2), w.setsampwidth(2), w.setframerate(44100), w.writeframes(pcm.tobytes())
filedialog.askopenfilenames = lambda **k: [str(src)]
messagebox.showinfo = lambda *a, **k: info.append(a)
messagebox.showerror = lambda *a, **k: errors.append(("error", a))
messagebox.askyesno = lambda *a, **k: True  # "delete this key?"
messagebox.askyesnocancel = lambda *a, **k: closing.append(a) or False  # on close: No = throw changes away
real = {p: p.stat().st_mtime_ns for p in (cm.SD_DIR / "ProfilesV3").rglob("manifest.json")}
seen = {}


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def tour():
    r = tk._default_root
    try:
        r.geometry("1800x1200+0+0")
        nb = next(w for w in walk(r) if isinstance(w, ttk.Notebook))
        tabs = {nb.tab(t_, "text"): r.nametowidget(t_) for t_ in nb.tabs()}
        main = tabs["Channel Mirror"]
        nb.select(main)
        r.update()
        next(b for b in walk(main) if isinstance(b, ttk.Button) and b.cget("text") == "Add files...").invoke()
        r.update()
        next(b for b in walk(main) if isinstance(b, ttk.Button) and b.cget("text") == "Run").invoke()
        r.update()
        outs = sorted((tmp / "out").rglob("*.*"))
        seen["outs"] = outs
        seen["decodes"] = [subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                           "csv=p=0", str(o)], capture_output=True, text=True).stdout.strip()
                           for o in outs]
        sb = tabs["Stream Deck soundboard"]
        nb.select(sb)
        r.update()
        next(b for b in walk(sb) if isinstance(b, ttk.Button) and b.cget("text") == "Add Channel Mirror outputs").invoke()
        r.update()
        tree = next(w for w in walk(sb) if isinstance(w, ttk.Treeview))
        seen["sounds"] = len(tree.get_children())
        ed = tabs["Stream Deck editor"]
        nb.select(ed)
        r.update()
        import gc
        grid = next(o for o in gc.get_objects() if isinstance(o, cm.DeckGrid) and str(o.frame).startswith(str(ed)))
        used = next(k for k, wdg in grid.tiles.items() if "\n" in str(wdg.cget("text")))  # a key in use
        grid.on_click(used, type("E", (), {"state": 0})())
        r.update()
        r.focus_force()
        r.event_generate("<Delete>")
        r.update()
        seen["pending_before_close"] = True
        r.tk.call(r.protocol("WM_DELETE_WINDOW"))  # the close button
    except Exception as e:
        errors.append(e)
        r.destroy()


real_mainloop = tk.Tk.mainloop
tk.Tk.mainloop = lambda self, n=0: (self.after(1500, tour), real_mainloop(self, n))[1]
cm.gui()
print("outputs:", [o.name for o in seen.get("outs", [])], "durations:", seen.get("decodes"))
assert seen.get("outs") and all(d and float(d) > 0.9 for d in seen["decodes"]), seen
assert seen.get("sounds") == len(seen["outs"]), seen
assert closing and "haven't been sent" in closing[0][1], closing  # asked before throwing the change away
after = {p: p.stat().st_mtime_ns for p in (cm.SD_DIR / "ProfilesV3").rglob("manifest.json")}
assert after == real, "the real Stream Deck profiles changed"
saved = json.loads(cm.SETTINGS.read_text())
assert saved.get("tab") == "Stream Deck editor" and saved.get("out_dir") == str(tmp / "out")  # closed properly, settings saved
assert not errors, errors
shutil.rmtree(tmp)
print("main app ok: Channel Mirror run, outputs to soundboard, close with unsent change (thrown away)")
