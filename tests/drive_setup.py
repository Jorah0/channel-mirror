"""The Setup tab on the whole app: Light / Dark / Follow Windows switched live (ttk styles, classic tk widgets, key
grids, list row colours, title bars), folders picked with Browse... (saved, used at once, and applied at the next
start: the editor reads profiles from the picked folder), Auto going back, and Restart building the right command.
Settings go to a temp copy; Stream Deck is never sent to; the restart launch is caught, not run."""
import ctypes, gc, json, os, shutil, subprocess, sys, tempfile
import faulthandler  # never stuck: still running after CM_TEST_TIMEOUT s (default 300) -> where it is, exit
faulthandler.dump_traceback_later(int(__import__("os").environ.get("CM_TEST_TIMEOUT", "300")), exit=True)
from pathlib import Path
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # default: this repo
sys.path.insert(0, REPO)
ctypes.windll.shcore.SetProcessDpiAwareness(1)
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import channel_mirror as cm
sys.argv = sys.argv[:1]  # the app reads extra words as dropped files: keep its command line clean
from tkinter import messagebox as _mb
for _n in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askyesnocancel", "askretrycancel"):
    setattr(_mb, _n, lambda *a, _n=_n, **k: popups.append((_n, a)))  # nothing may pop up on the desktop
popups = []

errors, launched, answers, titlebars = [], [], [], []
tk.Tk.report_callback_exception = lambda self, *a: errors.append(a)
cm.sd_push = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send to Stream Deck"))
messagebox.askyesnocancel = lambda *a, **k: errors.append(("unexpected question", a))
filedialog.askdirectory = lambda **k: answers.pop(0)
real_popen = subprocess.Popen


def fake_popen(cmd, *a, **k):  # catch only the app relaunching itself
    if isinstance(cmd, list) and cmd[:1] == [sys.executable] and any(str(x).endswith(".py") for x in cmd[1:]):
        return launched.append(cmd)
    return real_popen(cmd, *a, **k)


subprocess.Popen = fake_popen
real_titlebar = cm.ui_titlebar
cm.ui_titlebar = lambda win, redraw=False: (titlebars.append((str(win), redraw)), real_titlebar(win, redraw))[1]

tmp = Path(tempfile.mkdtemp())
sd = tmp / "SD"  # a Stream Deck folder of our own: one profile called "SetupTest"
pg = sd / "ProfilesV3" / "S1.sdProfile" / "Profiles" / "PAGE1" / "manifest.json"
pg.parent.mkdir(parents=True)
(pg.parents[2] / "manifest.json").write_text(json.dumps({"Device": {"Model": "20GBA9901", "UUID": "dev"},
                                                          "Name": "SetupTest", "Pages": {"Current": "page1",
                                                          "Default": "x", "Pages": ["page1"]}}))
pg.write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": {}}]}))
ff, inbox, rec = tmp / "ff", tmp / "inbox", tmp / "rec"
ff.mkdir()
cm.SETTINGS = tmp / "settings.json"
cm.SETTINGS.write_text(json.dumps({"theme": "light", "sd_autosend": False, "tab": 9}))  # 9 = Setup, as 2.1 saved it (by number)
REAL_SD = cm.SD_DIR
cm.RUN_KEY = r"Software\ChannelMirrorTest\Run"  # start-with-Windows goes here, never the real Run key


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def setup_page(r):
    nb = next(w for w in walk(r) if isinstance(w, ttk.Notebook))
    t = next(t for t in nb.tabs() if nb.tab(t, "text") == "Setup")
    nb.select(t)
    r.update()
    return r.nametowidget(t)


def cell(page, key, kind, text=None):
    """The widget in a folder's row: its Browse... / Auto button, or its status label."""
    row = [k for k, *_ in cm.SETUP_ITEMS].index(key) + 1
    for w in walk(page):
        if isinstance(w, kind) and str(w.grid_info().get("row", "")) == str(row) and (
                text is None or w.cget("text") == text):
            if kind is not ttk.Label or str(w.grid_info().get("column")) == "2":
                return w
    raise LookupError(key)


def radio(page, text):
    next(b for b in walk(page) if isinstance(b, ttk.Radiobutton) and b.cget("text") == text).invoke()
    page.update()


def check(page, text):
    next(b for b in walk(page) if isinstance(b, ttk.Checkbutton) and b.cget("text").startswith(text)).invoke()
    page.update()


def dark_titlebar(w):
    hwnd, v = ctypes.windll.user32.GetParent(w.winfo_id()), ctypes.c_int(-1)
    ok = ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v)) == 0
    return v.value if ok else None


def tour1():
    r = tk._default_root
    try:
        page = setup_page(r)
        st = ttk.Style(r)
        assert cm.UI["mode"] == "light" and st.lookup("TFrame", "background") == cm.UI_LIGHT["bg"]
        box = tk.Text(page)  # made in light mode, like the Edit key window's name box
        grids = [g for g in gc.get_objects() if isinstance(g, cm.DeckGrid) and g.size]
        assert grids, "no key grid drawn"
        legend = [w for w in walk(r) if isinstance(w, tk.Label) and str(w.cget("bg")).lower() == cm.UI_LIGHT["sound"]]
        trees = [w for w in walk(r) if isinstance(w, ttk.Treeview) and w.tag_configure("missing", "foreground")]
        assert legend and trees
        # Dark: styles, classic widgets, tiles, row colours, title bars
        titlebars.clear()
        radio(page, "Dark")
        assert cm.UI["mode"] == "dark"
        assert st.lookup("TFrame", "background") == cm.UI_DARK["bg"]
        assert st.lookup("TButton", "background") == cm.UI_DARK["button"]
        assert st.lookup("Hint.TLabel", "foreground") == cm.UI_DARK["muted"]
        assert str(r.cget("bg")).lower() == cm.UI_DARK["bg"]
        assert str(box.cget("bg")).lower() == cm.UI_DARK["panel"] and str(box.cget("fg")).lower() == cm.UI_DARK["text"]
        assert all(str(w.cget("bg")).lower() == cm.UI_DARK["sound"] for w in legend)
        assert all(str(t.tag_configure("missing", "foreground")).lower() == cm.UI_DARK["bad"] for t in trees)
        tile_colours = {cm.UI_DARK[k] for k in ("empty", "sound", "missing", "other", "accent", "auto")}
        for g in grids:
            assert {str(t.cget("bg")).lower() for t in g.tiles.values()} <= tile_colours, g.tiles
        assert (str(r), True) in titlebars, titlebars  # the main window's title bar redrawn
        assert dark_titlebar(r) in (1, None)  # None: this Windows can't report it
        top = tk.Toplevel(r)  # a dialog opened in dark mode
        top.update()
        assert str(top.cget("bg")).lower() == cm.UI_DARK["bg"] and dark_titlebar(top) in (1, None)
        top.destroy()
        radio(page, "Light")
        assert st.lookup("TFrame", "background") == cm.UI_LIGHT["bg"]
        assert str(box.cget("bg")).lower() == cm.UI_LIGHT["panel"]
        assert all(str(w.cget("bg")).lower() == cm.UI_LIGHT["sound"] for w in legend)
        assert dark_titlebar(r) in (0, None)
        radio(page, "Follow Windows")
        assert cm.UI["mode"] == cm.ui_mode("system")
        radio(page, "Dark")  # kept for the next start
        box.destroy()

        # folders: Stream Deck profiles picked (needs a restart for the open tabs), used straight away
        answers.append(str(sd))
        cell(page, "sd_dir", ttk.Button, "Browse...").invoke()
        assert cm.SD_DIR == sd and cell(page, "sd_dir", ttk.Label).cget("text") == "✓ Found"
        assert str(cell(page, "sd_dir", ttk.Button, "Auto").cget("state")) == "normal"
        assert "Restart" in next(w for w in walk(page) if isinstance(w, ttk.Label)
                                 and "Restart Channel Mirror" in str(w.cget("text"))).cget("text")
        # ffmpeg folder: first on PATH, then Auto takes it away again
        answers.append(str(ff))
        cell(page, "ffmpeg", ttk.Button, "Browse...").invoke()
        assert os.environ["PATH"].split(os.pathsep)[0] == str(ff)
        assert cell(page, "ffmpeg", ttk.Label).cget("text") == "✗ Not found"  # no ffmpeg.exe in it
        cell(page, "ffmpeg", ttk.Button, "Auto").invoke()
        assert os.environ["PATH"] == cm.PATH_START and cell(page, "ffmpeg", ttk.Label).cget("text") == "✓ Found"
        # received files: picked, then Auto
        answers.append(str(inbox))
        cell(page, "inbox", ttk.Button, "Browse...").invoke()
        assert cm.LINK_INBOX == inbox and cell(page, "inbox", ttk.Label).cget("text") == "Made when first used"
        cell(page, "inbox", ttk.Button, "Auto").invoke()
        assert cm.LINK_INBOX == cm.SETUP_AUTO["inbox"]
        assert str(cell(page, "inbox", ttk.Button, "Auto").cget("state")) == "disabled"
        # recordings: the Screen recorder tab's own folder box follows
        answers.append(str(rec))
        cell(page, "rec", ttk.Button, "Browse...").invoke()
        rbox = [w for w in walk(r) if isinstance(w, ttk.Entry) and str(w.cget("textvariable"))
                and w.getvar(w.cget("textvariable")) == str(rec)]
        assert len(rbox) >= 2, rbox  # the Setup row and the recorder tab's box
        # window: the close button minimizes by default (still running); start with Windows on, then off again
        r.tk.call(r.protocol("WM_DELETE_WINDOW"))
        r.update()
        assert r.winfo_exists() and r.state() == "iconic", r.state()
        r.deiconify()
        r.update()
        assert cm.startup_get() is None
        check(page, "Start Channel Mirror when Windows starts")
        assert "--minimized" in cm.startup_get() and "channel_mirror.py" in cm.startup_get(), cm.startup_get()
        check(page, "Start Channel Mirror when Windows starts")
        assert cm.startup_get() is None
        # Restart: closes like the close button (settings saved), then starts the app again
        next(b for b in walk(page) if isinstance(b, ttk.Button) and b.cget("text") == "Restart now").invoke()
    except BaseException as e:
        errors.append(e)
        r.destroy()


def tour2():
    r = tk._default_root
    try:
        page = setup_page(r)
        assert cm.UI["mode"] == "dark" and ttk.Style(r).lookup("TFrame", "background") == cm.UI_DARK["bg"]
        assert cm.SD_DIR == sd, cm.SD_DIR  # applied at start, before the tabs were built
        profiles = {v for w in walk(r) if isinstance(w, ttk.Combobox) for v in w.cget("values")}
        assert any(str(v).startswith("SetupTest") for v in profiles), profiles  # read from the picked folder
        cell(page, "sd_dir", ttk.Button, "Auto").invoke()
        assert cm.SD_DIR == cm.SETUP_AUTO["sd_dir"]
        check(page, "Close button minimizes")  # off: the close button quits
        r.tk.call(r.protocol("WM_DELETE_WINDOW"))  # the window's close button
    except BaseException as e:
        errors.append(e)
        r.destroy()


real_mainloop = tk.Tk.mainloop
tour = [tour1]
tk.Tk.mainloop = lambda self, n=0: (self.after(1500, tour[0]), real_mainloop(self, n))[1]
cm.gui()
assert not errors, errors
saved = json.loads(cm.SETTINGS.read_text())
assert saved["theme"] == "dark" and saved["paths"] == {"sd_dir": str(sd)}, saved  # Auto ones left out
assert saved["recorder"]["folder"] == str(rec) and saved["tab"] == "Setup"
assert launched == [[sys.executable, str(Path(cm.__file__).resolve())]], launched

cm.SD_DIR = REAL_SD  # a fresh start: the saved choice must be applied again by gui()
tour[0] = tour2
cm.gui()
assert not errors, errors
saved = json.loads(cm.SETTINGS.read_text())
assert saved["close_to_taskbar"] is False, saved
assert "sd_dir" not in saved["paths"] and len(launched) == 1, (saved, launched)  # a plain close: no restart
subprocess.Popen = real_popen
assert not popups, popups  # no message box was needed
shutil.rmtree(tmp, ignore_errors=True)
import winreg
winreg.DeleteKey(winreg.HKEY_CURRENT_USER, cm.RUN_KEY)  # the test key (left empty above)
winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\ChannelMirrorTest")
print("setup tab ok: light/dark/follow live, folders picked + Auto + applied at next start, restart command, close to taskbar + toggle, start with Windows")
