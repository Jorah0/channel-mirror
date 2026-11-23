"""PC-A for drive_crosspc.py: the whole Channel Mirror app in its own process, on this PC only (127.0.0.1), with a
synthetic Stream Deck folder and VTube Studio install. Questions are answered from <work>/answers.json (a list:
true / false, popped per question; empty = accept); what it shows and does is logged to <work>/a_log.jsonl.
Usage: crosspc_peer.py <repo> <work>"""
import ctypes, functools, json, subprocess, sys, threading, time
import faulthandler  # never stuck: still running after CM_TEST_TIMEOUT s (default 300) -> where it is, exit
faulthandler.dump_traceback_later(int(__import__("os").environ.get("CM_TEST_TIMEOUT", "300")), exit=True)
import os
from pathlib import Path
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # default: this repo
sys.path.insert(0, REPO)
ctypes.windll.shcore.SetProcessDpiAwareness(1)
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import channel_mirror as cm
work = Path(sys.argv[2])
sys.argv = sys.argv[:1]  # the app reads extra words as dropped files


def log(**kw):
    with open(work / "a_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(kw, default=str) + "\n")


def answer():
    try:
        a = json.loads((work / "answers.json").read_text())
        if a:
            (work / "answers.tmp2").write_text(json.dumps(a[1:]))
            (work / "answers.tmp2").replace(work / "answers.json")
            return a[0]
    except (OSError, ValueError):
        pass
    return True


for n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, n, lambda *a, _n=n, **k: log(popup=_n, text=a[:2]))
messagebox.askyesno = lambda *a, **k: (log(asked=a[:2]), answer())[1]
messagebox.askyesnocancel = lambda *a, **k: log(asked=a[:2]) or True
filedialog.askopenfilenames = lambda **k: ()
simpledialog.askstring = lambda *a, **k: None
cm.ui_proposal = lambda parent, title, lines: (log(proposal=title, lines=lines), (r := answer()), log(answered=r))[-2]
pushed = []
a_sd = work / "A_SD"
cm.SD_DIR, cm.SD_BACKUPS = a_sd, work / "A_backups"
cm.sd_push = lambda writes, folders, sd_dir=None, backups=None: (
    log(pushed=sorted(str(p) for p in writes)), cm.sd_save(writes, folders, a_sd, work / "A_backups"))[1]
cm.sd_start = lambda: log(started=True)
cm.sd_running = lambda: False
cm.sd_connected = lambda: set()
cm.vts_assets = lambda: []
cm.VTS_ASSETS = work / "A_VTS" / "StreamingAssets"
cm.SETTINGS = work / "a_settings.json"
cm.LINK_INBOX = work / "A_Incoming"
cm.LinkServer = functools.partial(cm.LinkServer, host="127.0.0.1")
cm.link_lan_ip = lambda: "127.0.0.1"
cm.link_public_network = lambda: False
cm.peer_find = lambda peer, me, addrs=None, timeout=2.0: None
cm.link_handover_serve = lambda on_link, port=None: None
cm.VTS_BACKUPS, cm.SD_OUT = work / "A_VTS backups", work / "A_SD out"  # never the real backup / profile folders
cm.SD_EXE = work / "A StreamDeck.exe"  # "installed" (never started: sd_start / sd_push above only log and write)
cm.SD_EXE.write_bytes(b"")
# VTube Studio "running" while <work>/a_vts_running exists; closing it (taskkill) and starting it (steam://) are only
# logged - the real VTube Studio is never touched
cm.vts_running = lambda: (work / "a_vts_running").exists()
real_run = subprocess.run


def fake_run(cmd, *a, **k):
    if isinstance(cmd, (list, tuple)) and str(cmd[0]).lower().startswith("taskkill"):
        log(launched=list(map(str, cmd)))
        (work / "a_vts_running").unlink(missing_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return real_run(cmd, *a, **k)


subprocess.run = fake_run
os.startfile = lambda path, *a, **k: log(launched=str(path))
real_rec, real_link = cm.recorder_tab, cm.link_tab
held = {}
fake_obs = None
if (work / "a_obs.json").exists():  # its own OBS: a fake one (never the real OBS), connected by itself at start
    from cmlib.selftest import FakeObs
    sys.path.insert(0, str(Path(__file__).parent))
    from harness import safe_obs
    fake_obs = FakeObs(json.loads((work / "a_obs.json").read_text())["password"], log=work / "a_obs_log.jsonl")
    cm.ObsClient = safe_obs(cm.ObsClient, {fake_obs.port})
    a_cfg = json.loads(cm.SETTINGS.read_text())
    a_cfg["obs"] = {"port": fake_obs.port, "password": fake_obs.password, "connect": True,
                    "feed_share": True, "feed_port": 0}  # its own soundboard feed on, too
    cm.SETTINGS.write_text(json.dumps(a_cfg))


def rec_tab(page, cfg):  # no screen is recorded: a small made-up mp4 is "recorded" instead
    r = real_rec(page, cfg)

    def start():
        r["state"].update(proc=object(), route=r["vars"]["dest"].get())
        log(recording="start")

    def stop():
        out = work / f"A_rec {time.time():.0f}.mp4"
        out.write_bytes(b"\0\0\0\x18ftypmp42" + bytes(2000))
        r["state"]["proc"] = None
        log(recording="stop", file=str(out))
        r["done_with"](out)
    r.update(start=start, stop=stop)
    return r


def link_tab(*a, **k):
    held["link"] = real_link(*a, **k)
    return held["link"]


cm.recorder_tab, cm.link_tab = rec_tab, link_tab
real_editor, real_obs_tab = cm.sd_editor_tab, cm.obs_tab
cm.sd_editor_tab = lambda *a, **k: held.setdefault("editor", real_editor(*a, **k))
cm.obs_tab = lambda *a, **k: held.setdefault("obs", real_obs_tab(*a, **k))


def ready():
    lk = held["link"]
    lk["vars"]["port"].set("0")
    lk["vars"]["device"].set("PC-A")
    lk["toggle"]()
    (work / "a_pair.txt").write_text(lk["vars"]["pair"].get())

    def report():  # what PC-A has now, for the drive to check
        lc = json.loads(json.dumps({k: v for k, v in lk["hub"].items() if k in ("activity",)}, default=str))
        peers = [{k: p[k] for k in ("id", "name", "since", "host", "port")} for p in lk["hub"]["peers"]()]
        ed = held.get("editor")
        keys = {}
        if ed:
            for label in ed["profiles"]():
                for n, pf in ed["pages"](label):
                    keys[f"{label}|{n}"] = {k: cm.sd_title(a) + "|" + cm.sd_kind(a) for k, a in ed["keys"](pf).items() if a}
        obs = {}
        if fake_obs:  # whether PC-B may control its OBS: as the drive asks, through the Linked computers tab
            want = (work / "a_obs_trust").read_text() == "1" if (work / "a_obs_trust").exists() else None
            cb, tree = lk["obs_allow"], lk["tree"]
            if want is not None and peers and bool(tk._default_root.getvar(cb.cget("variable"))) != want:
                tree.selection_set(peers[0]["id"])
                tk._default_root.update()
                cb.invoke()
            feed = held["obs"]["vars"]["feed"].get()
            if (work / "a_feed_listen").exists() and feed and "listen" not in held:  # its OBS opens its own feed
                held["listen"] = threading.Thread(target=fake_obs._play, args=("A soundboard feed", feed), daemon=True)
                held["listen"].start()
            if (work / "a_heard_dump").exists():  # what its OBS heard of it, for the drive to listen to
                (work / "a_heard.mp3").write_bytes(bytes(fake_obs.heard.get("A soundboard feed", b"")))
                (work / "a_heard_dump").unlink()
            obs = {"scene": fake_obs.scene, "outputs": fake_obs.outputs, "trusted": [
                p["name"] for p in lk["hub"]["peers"]() if p.get("obs")], "inputs": {
                n: i["settings"] for n, i in fake_obs.inputs.items()}, "feed": feed,
                "heard": {n: len(b) for n, b in fake_obs.heard.items()}}
        tmp = work / "a_state.tmp"
        tmp.write_text(json.dumps({"peers": peers, "activity": lc["activity"], "keys": keys, "obs": obs,
                                   "status": ed["status"]() if ed else "", "port": lk["state"]["server"].port}))
        try:
            tmp.replace(work / "a_state.json")
        except OSError:  # the drive is reading it this moment: next round
            pass
        if (work / "a_quit").exists():
            return tk._default_root.tk.call(tk._default_root.protocol("WM_DELETE_WINDOW"))
        tk._default_root.after(300, report)
    report()


real_mainloop = tk.Tk.mainloop
tk.Tk.mainloop = lambda self, n=0: (self.after(1200, ready), real_mainloop(self, n))[1]
import traceback
tk.Tk.report_callback_exception = lambda self, *a: log(error=repr(a[1]), where="".join(traceback.format_exception(*a))[-900:])
cm.gui()
log(closed=True)
