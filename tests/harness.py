"""Start the whole Channel Mirror app (the main window, every tab) for a test, on temp copies only.

    from harness import App
    app = App({"recorder": {...}})     # settings for this run (a temp file; yours are never read or written)
    cm = app.cm                        # set anything else first: cm.SD_DIR = my_fake_stream_deck_folder
    app.start()                        # builds the real main window, exactly as the user gets it
    page = app.tab("Screen recorder")  # selects that tab -> its page;  app.api("recorder") = the tab's own handles
    app.button("Drag area on screen", page, startswith=True).invoke()
    saved = app.close()                # the window's close button: settings saved (to the temp file) -> them

Safe by default: Stream Deck is never written (sends are recorded in app.sent), VTube Studio / Stream Deck folders
point at empty temp folders, received files / backups / now-playing go to temp, servers bind to 127.0.0.1, no link
hand-over port or token of the real app is touched, nothing plays out loud, no network broadcasts; the phone remote
listens on 127.0.0.1 only and reaches only a fake VTube Studio API (app.vts_ports). Every message box
is recorded (app.boxes); questions take answers from app.yes / app.picks / app.texts (default: yes / nothing), so a
test can never hang on a dialog. A callback error inside Tk fails the test (app.errors)."""
import ctypes
import faulthandler
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

# never stuck: a test still running after CM_TEST_TIMEOUT seconds (default 300) prints where it is and exits (code 1)
faulthandler.dump_traceback_later(int(os.environ.get("CM_TEST_TIMEOUT", "300")), exit=True)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if len(sys.argv) > 1 and os.path.isfile(os.path.join(sys.argv[1], "channel_mirror.py")):
    REPO = sys.argv[1]  # run_all.py passes the repo
sys.path.insert(0, REPO)
sys.argv = sys.argv[:1]  # the app reads extra words on its command line as dropped files
ctypes.windll.shcore.SetProcessDpiAwareness(1)
import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, simpledialog, ttk  # noqa: E402

import channel_mirror as cm  # noqa: E402

# tab builder -> short name for app.api()
BUILDERS = {"streamdeck_tab": "soundboard", "sd_editor_tab": "editor", "import_tab": "import", "mover_tab": "mover",
            "recorder_tab": "recorder", "vts_tab": "vts", "music_tab": "music", "link_tab": "link",
            "setup_tab": "setup", "obs_tab": "obs", "remote_tab": "remote"}


class FakeOut:
    """Music "Hear it here" output that plays nothing (the stream to OBS still runs)."""
    def __init__(self, *a, **k):
        self.blocks = 0

    def write(self, *a, **k):
        self.blocks += 1

    def close(self):
        pass


def safe_obs(real, ports):
    """ObsClient that connects only to the fake OBS servers in ports; anything else (the user's OBS on 4455) goes to a
    port nobody listens on."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()

    class TestObs(real):
        def __init__(self, host, port, *a, **k):
            super().__init__("127.0.0.1", int(port) if int(port) in ports else dead, *a, **k)
    return TestObs


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


class App:
    def __init__(self, settings=None):
        self.cm = cm
        self.tmp = Path(tempfile.mkdtemp(prefix="cm_test_"))
        self.errors, self.boxes, self.asked, self.sent = [], [], [], []
        self.yes, self.picks, self.texts = [], [], []  # queued answers: ask yes/no, file pickers, typed text
        self.apis = {}
        tk.Tk.report_callback_exception = lambda root, *a: self.errors.append(a)
        for kind in ("showerror", "showinfo", "showwarning"):
            setattr(messagebox, kind, functools.partial(self._box, kind))
        for kind in ("askyesno", "askokcancel", "askyesnocancel", "askquestion", "askretrycancel"):
            setattr(messagebox, kind, functools.partial(self._ask, kind))
        for kind in ("askopenfilename", "askopenfilenames", "askdirectory", "asksaveasfilename"):
            setattr(filedialog, kind, functools.partial(self._pick, kind))
        simpledialog.askstring = lambda title, prompt, **k: self.texts.pop(0) if self.texts else None
        simpledialog.askinteger = lambda title, prompt, **k: self.texts.pop(0) if self.texts else None
        t = self.tmp
        cm.SETTINGS = t / "settings.json"
        cm.SETTINGS.write_text(json.dumps({"sd_autosend": False, "theme": "light", "close_to_taskbar": False, **(settings or {})}))
        for name, sub in (("SD_DIR", "StreamDeck"), ("SD_BACKUPS", "Stream Deck backups"),
                          ("SD_OUT", "Stream Deck profiles"), ("VTS_ASSETS", "VTube Studio"),
                          ("VTS_BACKUPS", "VTube Studio backups"), ("LINK_INBOX", "Incoming")):
            setattr(cm, name, t / sub)
        cm.SD_EXE = t / "no Stream Deck.exe"
        cm.MUSIC_NOW = t / "Now playing.txt"
        cm.sd_push = lambda writes, folders, *a, **k: self.sent.append((dict(writes), list(folders))) or "backup.zip"
        cm.sd_running = lambda: False
        cm.LinkServer = functools.partial(cm.LinkServer, host="127.0.0.1")
        cm.link_lan_ip = lambda: "127.0.0.1"
        cm.link_public_network = lambda: False
        cm.link_handover_serve = lambda on_link, port=None: None  # the real app's hand-over port stays its own
        cm.link_token = lambda: "test-token-" + "0" * 40
        cm.peer_find = lambda *a, **k: None  # no broadcasts onto the real network
        cm.MusicOut = FakeOut
        # OBS: only a fake one a test starts (cmlib.selftest.FakeObs; its port into app.obs_ports) - never the real OBS
        self.obs_ports = set()
        cm.ObsClient = safe_obs(cm.ObsClient, self.obs_ports)
        # the phone remote: 127.0.0.1 only, Tailscale's command line never run, VTube Studio's API only a fake one
        # (cmlib.selftest.FakeVts; its port into app.vts_ports) - never the real VTube Studio
        cm.remote_hosts = lambda: ["127.0.0.1"]
        cm.tailscale_info = lambda: {}
        self.vts_ports = set()
        real_vts = cm.vts_api
        cm.vts_api = lambda port, *a, **k: real_vts(int(port) if int(port) in self.vts_ports else 9, *a, **k)
        # never close or start real programs: taskkill (VTube Studio, Stream Deck) and opening files / steam:// links
        # are recorded in app.launched instead (a test checks them there)
        self.launched = []
        real_run, real_popen = subprocess.run, subprocess.Popen

        def outside(cmd):
            words = [str(c).lower() for c in (cmd if isinstance(cmd, (list, tuple)) else [cmd])]
            return words and (words[0].startswith("taskkill") or words[0].endswith("taskkill.exe")
                              or any("vtube studio.exe" in w or "streamdeck.exe" in w for w in words))

        def run(cmd, *a, **k):
            if outside(cmd):
                self.launched.append(list(map(str, cmd)) if isinstance(cmd, (list, tuple)) else str(cmd))
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return real_run(cmd, *a, **k)

        class Popen(real_popen):  # ffmpeg and a second app instance still start; the user's real programs don't
            def __init__(p, cmd, *a, **k):
                if outside(cmd):
                    self.launched.append(list(map(str, cmd)) if isinstance(cmd, (list, tuple)) else str(cmd))
                    cmd = [sys.executable, "-c", "pass"]
                super().__init__(cmd, *a, **k)
        subprocess.run, subprocess.Popen = run, Popen
        os.startfile = lambda path, *a, **k: self.launched.append(str(path))
        webbrowser.open = lambda url, *a, **k: self.launched.append(str(url)) or True
        for fn, short in BUILDERS.items():
            real = getattr(cm, fn)
            setattr(cm, fn, functools.partial(self._keep, short, real))

    def _keep(self, short, real, *a, **k):
        self.apis[short] = real(*a, **k)
        return self.apis[short]

    def _box(self, kind, title="", message="", **k):
        self.boxes.append((kind, title, message))

    def _ask(self, kind, title="", message="", **k):
        self.asked.append((kind, title, message))
        return self.yes.pop(0) if self.yes else True

    def _pick(self, kind, **k):
        self.asked.append((kind, k.get("title", ""), ""))
        if not self.picks:
            return () if kind == "askopenfilenames" else ""
        got = self.picks.pop(0)
        return tuple(map(str, got)) if kind == "askopenfilenames" else str(got)

    # --- running the app ---
    def start(self):
        real = tk.Tk.mainloop
        tk.Tk.mainloop = lambda *a, **k: None  # gui() builds the window and returns; the test drives it
        try:
            cm.gui()
        finally:
            tk.Tk.mainloop = real
        self.root = tk._default_root
        self.nb = next(w for w in walk(self.root) if isinstance(w, ttk.Notebook))
        self.pump(0.3)
        return self

    def tabs(self):
        return [self.nb.tab(t, "text") for t in self.nb.tabs()]

    def tab(self, name):
        """Select a main-window tab by its name -> its page."""
        tid = next(t for t in self.nb.tabs() if self.nb.tab(t, "text") == name)
        self.nb.select(tid)
        self.pump(0.1)
        return self.root.nametowidget(tid)

    def api(self, short):
        return self.apis[short]

    def pump(self, secs=0.0):
        t0 = time.time()
        while True:
            self.root.update()
            if time.time() - t0 >= secs:
                return
            time.sleep(0.02)

    def wait(self, cond, secs=15):
        t0 = time.time()
        while time.time() - t0 < secs:
            self.root.update()
            if cond():
                return True
            time.sleep(0.03)
        return False

    # --- finding controls ---
    def walk(self, w=None):
        return walk(w or self.root)

    def find(self, kind, within=None, **match):
        """Widgets of a type under `within` (default: the whole app) whose options match, e.g. text="Send"."""
        return [w for w in walk(within or self.root) if isinstance(w, kind)
                and all(str(w.cget(k)) == str(v) for k, v in match.items())]

    def button(self, text, within=None, startswith=False):
        hits = [b for b in walk(within or self.root) if isinstance(b, (ttk.Button, tk.Button))
                and (str(b.cget("text")).startswith(text) if startswith else str(b.cget("text")) == text)]
        assert hits, f"no button {text!r}"
        return hits[0]

    def windows(self):
        """Open windows besides the main one (dialogs, overlays)."""
        return [w for w in walk(self.root) if isinstance(w, tk.Toplevel) and w.winfo_exists()]

    _clock = [0]

    def click(self, widget, x=None, y=None, button=1, double=False):
        """A real mouse click on a widget (centre by default). Each click gets its own time stamp, a second after the
        last, so two clicks never merge into a double-click unless double=True."""
        x = widget.winfo_width() // 2 if x is None else x
        y = widget.winfo_height() // 2 if y is None else y
        App._clock[0] += 1000
        t = App._clock[0]
        for n in range(2 if double else 1):
            widget.event_generate(f"<ButtonPress-{button}>", x=x, y=y, time=t + 40 * n)
            widget.event_generate(f"<ButtonRelease-{button}>", x=x, y=y, time=t + 40 * n + 10)
        self.pump(0.05)  # (two presses 40 ms apart: Tk makes the <Double-Button> itself; it can't be generated)

    def menu_item(self, menu, label):
        """Run a context-menu entry by its label (the menu a right-click opens)."""
        for i in range(menu.index("end") + 1):
            if menu.type(i) == "command" and menu.entrycget(i, "label") == label:
                return menu.invoke(i)
        raise AssertionError(f"no menu item {label!r}")

    def close(self, check=True):
        """The window's close button -> the settings it saved."""
        root = self.root
        root.tk.call(root.protocol("WM_DELETE_WINDOW"))
        t0 = time.time()
        while time.time() - t0 < 30:
            try:
                if not root.winfo_exists():
                    break
                root.update()
            except tk.TclError:
                break
            time.sleep(0.03)
        saved = json.loads(cm.SETTINGS.read_text()) if cm.SETTINGS.exists() else {}
        if check:
            assert not self.errors, self.errors
        shutil.rmtree(self.tmp, ignore_errors=True)
        return saved
