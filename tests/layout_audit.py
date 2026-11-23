"""Layout audit: launch the whole app at a given window size and list every control (button, checkbox, radio,
dropdown, box, spinbox, slider) that the layout has squeezed off screen, per tab (and per editor tool).
Settings go to a temp copy; Stream Deck / VTube Studio are only read."""
import ctypes, json, os, shutil, sys, tempfile
import faulthandler  # never stuck: still running after CM_TEST_TIMEOUT s (default 300) -> where it is, exit
faulthandler.dump_traceback_later(int(__import__("os").environ.get("CM_TEST_TIMEOUT", "300")), exit=True)
from pathlib import Path
sys.path.insert(0, sys.argv[1])
ctypes.windll.shcore.SetProcessDpiAwareness(1)
import tkinter as tk
from tkinter import ttk
import channel_mirror as cm

W, H = int(sys.argv[2]), int(sys.argv[3])
SCALE = sys.argv[4] if len(sys.argv) > 4 else None
sys.argv = sys.argv[:1]  # the app reads extra words as dropped files: keep its command line clean
if SCALE:  # pretend the display scaling is different (1.3333 = 100%)
    _theme = cm.ui_theme
    cm.ui_theme = lambda r: (r.tk.call("tk", "scaling", float(SCALE)), _theme(r))[1]
tmp = Path(tempfile.mkdtemp())
cm.SETTINGS = tmp / "settings.json"
if os.environ.get("CM_THEME"):  # light / dark / system
    cm.SETTINGS.write_text(json.dumps({"theme": os.environ["CM_THEME"]}))
cm.sd_push = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send"))
CONTROLS = (ttk.Button, ttk.Checkbutton, ttk.Radiobutton, ttk.Combobox, ttk.Entry, ttk.Spinbox, ttk.Scale,
            tk.Button)
found = {}


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def lost(top):
    out = []
    for w in walk(top):
        if isinstance(w, CONTROLS) and not w.winfo_ismapped() and w.master.winfo_ismapped():
            label = (str(w.cget("text")) if "text" in w.keys() else "") or type(w).__name__
            out.append(label[:28])
    return out


def tour():
    r = tk._default_root
    r.geometry(f"{W}x{H}+0+0")
    r.update()
    nb = next(w for w in walk(r) if isinstance(w, ttk.Notebook))
    nb_names = [nb.tab(t, "text") for t in nb.tabs()]
    for t in nb.tabs():
        nb.select(t)
        r.update()
        name = nb.tab(t, "text")
        tab = r.nametowidget(t)
        if name == "Stream Deck editor":
            for g in cm.GOAL_HELP:
                next(b for b in walk(tab) if isinstance(b, ttk.Radiobutton) and b.cget("text") == g).invoke()
                r.update()
                if lost(tab):
                    found[f"{name} / {g}"] = lost(tab)
        elif lost(tab):
            found[name] = lost(tab)
    # the sidebar: every page's item shown whole inside it (above the status bar), its own controls on screen, and
    # page names shown on a wide window / icons only on a narrow one
    side = r.nametowidget("sidebar")
    bottom = side.winfo_rooty() + side.winfo_height()
    items = [w for w in walk(side) if w.winfo_class() == "NavItem"]
    names = [str(c.cget("text")) for w in items for c in w.winfo_children() if c.winfo_ismapped()
             and "text" in c.keys() and str(c.cget("text")) in nb_names]
    bad = [str(w) for w in items if not w.winfo_ismapped() or w.winfo_rooty() + w.winfo_height() > bottom]
    wide = r.winfo_width() >= cm.px(1280)
    if len(items) != len(nb_names) or bad or lost(side) or (sorted(names) == sorted(nb_names)) != wide:
        found["sidebar"] = {"items": len(items), "off screen": bad, "lost": lost(side), "names shown": names}
    print(cm.UI["mode"], json.dumps(found, indent=1) if found else
          f"{W}x{H}: every control is on screen (sidebar: {'names' if wide else 'icons only'})")
    LOST.extend(found)
    r.destroy()


LOST = []
real_mainloop = tk.Tk.mainloop
tk.Tk.mainloop = lambda self, n=0: (self.after(800, tour), real_mainloop(self, n))[1]
cm.gui()
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if LOST else 0)  # a control off screen fails
