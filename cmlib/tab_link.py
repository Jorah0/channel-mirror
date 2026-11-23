"""The link tab."""
import os
import shutil
import sys
from pathlib import Path
from .core import secret_keep, secret_read, settings_put
from .install import installed
from .link import (
    LINK_EXT,
    LINK_INBOX,
    LINK_PORT,
    LINK_TARGETS,
    link_lan_ip,
    link_make,
    link_pair_url,
    link_parse,
    link_public_network,
    link_register,
    link_registered,
    link_send,
    link_unregister,
)
from .peers import (
    LinkServer,
    PEER_ASK,
    PEER_DAYS,
    link_default_target,
    link_fetch,
    peer_browse,
    peer_check_files,
    peer_days_left,
    peer_find,
    peer_hello,
    peer_name,
    peer_pair,
    peer_renew,
    peer_result,
    peer_send,
    peer_summary,
    peer_unlink,
    peer_until,
)
from .ui import Tip, UI, ui_background
from .ui_link import peer_batches, ui_incoming, ui_library, ui_proposal


def link_tab(page, cfg, deliver, provide=None, home=None):
    """The Link tab. channelmirror:// links on this PC (set up, make, open), receiving files from other devices on
    the home network (a pairing link with a code; every batch is shown here and placed only when accepted), sending
    files to another Channel Mirror, and linked computers (paired once for PEER_DAYS days: their proposals are
    shown here and handed on with deliver(target, files, proposal, peer) only when accepted). deliver(target,
    files) puts accepted files in that tab. provide = {"browse", "fetch", "library": f(info)} answers a linked
    computer's reads (filled in by the window); provide["jump"] = [(text, f(peer))] opens a tool already pointed at
    a linked computer. home = the Linked computers tab (the linked computers live there; else in this tab). Returns {"open_link", "stop", "save", "hub", ...}; hub is what the
    other tabs use to work with linked computers."""
    import queue
    import secrets
    import threading
    import time
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    provide = {} if provide is None else provide
    lc = cfg.setdefault("link", {})
    lc.setdefault("peers", [])
    if not lc.get("me"):
        lc["me"] = secrets.token_hex(16)  # this PC's pair id
    peers = []  # the linked computers with their secrets readable; the settings keep them sealed (save)
    for p in lc["peers"]:
        s_ = secret_read(p.get("secret"))  # one this Windows user can't read: shown as needing to be linked again
        peers.append(dict(p, secret=s_) if s_ else dict(p, secret="", since=0, kept=p))
    old_plain = any(p.get("secret") and not str(p["secret"]).startswith("dpapi:") for p in lc["peers"])
    events = queue.Queue()  # from the server threads to this one
    st = {"server": None}
    v = {"port": tk.StringVar(value=str(lc.get("port", LINK_PORT))),
         "code": tk.StringVar(value=f"{secrets.randbelow(10 ** 8):08d}"),  # new each start, never saved
         "pair": tk.StringVar(), "make_to": tk.StringVar(value=LINK_TARGETS["import"]),
         "made": tk.StringVar(), "open": tk.StringVar(),
         "dest": tk.StringVar(value=lc.get("dest", "")), "send_to": tk.StringVar(value=LINK_TARGETS["import"]),
         "device": tk.StringVar(value=lc.get("device") or os.environ.get("COMPUTERNAME", "My PC")),
         "link_to": tk.StringVar()}
    names = {lab: k for k, lab in LINK_TARGETS.items()}
    make_files, send_files = [], []
    body = ttk.Frame(page, padding=12)
    body.pack(fill="both", expand=True)
    status = ttk.Label(page, style="Status.TLabel", anchor="w", wraplength=1100, justify="left")
    status.pack(fill="x", padx=12, pady=(0, 8))
    left, right = ttk.Frame(body), ttk.Frame(body)
    left.pack(side="left", fill="both", expand=True, padx=(0, 12))
    right.pack(side="left", fill="both", expand=True)

    # links on this PC
    lf = ttk.LabelFrame(left, text="Links on this PC  (channelmirror://...)")
    lf.pack(fill="x")
    ttk.Label(lf, text="Clicking a link (in a browser, Discord, a shortcut...) opens Channel Mirror with its files "
                       "ready for the chosen tab; you accept them first. A link can also carry web addresses: those "
                       "files are downloaded.", style="Hint.TLabel", wraplength=520, justify="left").pack(anchor="w")
    reg_l = ttk.Label(lf)
    reg_l.pack(anchor="w", pady=(6, 0))
    rr = ttk.Frame(lf)
    rr.pack(fill="x", pady=(4, 0))

    def show_reg():
        cmd = link_registered()
        reg_l.config(text=f"Links open: {cmd.split(chr(34))[1] if cmd and chr(34) in cmd else cmd}" if cmd else
                     "Links aren't set up on this PC yet.")

    def set_up():
        exe = installed() or (Path(sys.executable) if getattr(sys, "frozen", False) else None)
        if exe is None:
            return status.config(text="Links need the app installed (or run from ChannelMirror.exe).")
        link_register(exe)
        show_reg()
        status.config(text="channelmirror:// links now open Channel Mirror.")
    ttk.Button(rr, text="Set up links", style="Tool.TButton", command=set_up).pack(side="left")
    ttk.Button(rr, text="Remove", style="Tool.TButton", command=lambda: (link_unregister(), show_reg())).pack(
        side="left", padx=6)
    ttk.Label(lf, text="MAKE A LINK", style="Field.TLabel").pack(anchor="w", pady=(10, 0))
    mr = ttk.Frame(lf)
    mr.pack(fill="x")
    ttk.Combobox(mr, textvariable=v["make_to"], values=list(names), state="readonly", width=34).pack(side="left")

    def add_make():
        make_files.extend(Path(f) for f in filedialog.askopenfilenames(parent=page, title="Files for the link"))
        v["made"].set(link_make(names[v["make_to"].get()], make_files))
    ttk.Button(mr, text="Add files...", style="Tool.TButton", command=add_make).pack(side="left", padx=6)
    ttk.Button(mr, text="Clear", style="Tool.TButton",
               command=lambda: (make_files.clear(), v["made"].set(""))).pack(side="left")
    v["make_to"].trace_add("write", lambda *_: make_files and v["made"].set(
        link_make(names[v["make_to"].get()], make_files)))
    me = ttk.Frame(lf)
    me.pack(fill="x", pady=(4, 0))
    ttk.Entry(me, textvariable=v["made"], width=52).pack(side="left", fill="x", expand=True)
    ttk.Button(me, text="Copy", style="Tool.TButton", command=lambda: copy(v["made"].get())).pack(side="left", padx=4)
    ttk.Label(lf, text="OPEN A LINK", style="Field.TLabel").pack(anchor="w", pady=(10, 0))
    oe = ttk.Frame(lf)
    oe.pack(fill="x", pady=(0, 4))
    ttk.Entry(oe, textvariable=v["open"], width=52).pack(side="left", fill="x", expand=True)
    ttk.Button(oe, text="Open", style="Tool.TButton", command=lambda: open_link(v["open"].get())).pack(
        side="left", padx=4)

    # linked computers: their own tab when there is one
    if home is not None:
        ttk.Label(home, text=" Linked computers: two Channel Mirrors working together - everything sent waits for "
                             "someone to accept it on the other PC ", style="Local.TLabel", anchor="w").pack(
            fill="x", padx=12, pady=(10, 0))
        hbody = ttk.Frame(home, padding=12)
        hbody.pack(fill="both", expand=True)
        hl, hr = ttk.Frame(hbody), ttk.Frame(hbody)
        hl.pack(side="left", fill="both", expand=True, padx=(0, 12))
        hr.pack(side="left", fill="both", expand=True)
        hstatus = ttk.Label(home, style="Status.TLabel", anchor="w", wraplength=1100, justify="left")
        hstatus.pack(fill="x", padx=12, pady=(0, 8))
    kf = ttk.LabelFrame(hl if home is not None else left, text=f"Linked computers  (link once - it lasts {PEER_DAYS} days)")
    kf.pack(fill="both", expand=True, pady=(0 if home is not None else 10, 0))
    ttk.Label(kf, text="On the other PC: Start receiving. Paste its pairing link here, Link, and accept on that PC. "
                       "Then every tab can send there and open its Stream Deck and VTube Studio - and anything sent "
                       "still waits for someone to accept it there.", style="Hint.TLabel", wraplength=520,
              justify="left").pack(anchor="w")
    pr = ttk.Frame(kf)
    pr.pack(fill="x", pady=(4, 0))
    ttk.Entry(pr, textvariable=v["link_to"], width=40).pack(side="left", fill="x", expand=True)
    link_b = ttk.Button(pr, text="Link", style="Accent.TButton", command=lambda: pair())
    link_b.pack(side="left", padx=4)
    ptv = ttk.Treeview(kf, columns=("name", "where", "until", "now"), show="headings", height=3, selectmode="browse")
    for c, h, w in (("name", "Computer", 110), ("where", "Address", 120), ("until", "Linked until", 150),
                    ("now", "Now", 230)):
        ptv.heading(c, text=h)
        ptv.column(c, width=w, stretch=c == "now")
    ptv.tag_configure("off", foreground=UI["muted"])
    ptv.tag_configure("expired", foreground=UI["bad"])
    ptv.pack(fill="both", expand=True, pady=(4, 0))
    pb = ttk.Frame(kf)
    pb.pack(fill="x", pady=(4, 4))
    hub = {"peers": lambda: list(peers), "me": lambda: lc["me"], "activity": {}, "state": {}, "sent": {},
           "listeners": [], "v": [0], "library": lambda: provide["mine"]() if "mine" in provide else {}, "log": []}

    def bump():
        hub["v"][0] += 1

    def peer_by(pid):
        return next((p for p in peers if p["id"] == pid), None)

    def label(p):
        left_ = peer_days_left(p)
        if not left_:
            return f"{p['name']} - " + ("its link can't be read on this PC, link it again" if p.get("kept") else
                                        "link expired, verify again")
        on = hub["state"].get(p["id"])
        seen = time.strftime("%H:%M", time.localtime(on[1])) if on and on[1] else ""
        return (f"{p['name']} (linked until {peer_until(p)}, {left_} day{'s' * (left_ != 1)} left) - " +
                ("online" if on and on[0] else f"offline{' (last seen ' + seen + ')' if seen else ''}" if on
                 else "checking..."))

    def act(p, text):
        if p:
            hub["activity"][p["id"]] = f"{p['name']}: {text}"
            hub["log"].append((time.strftime("%H:%M:%S"), p["name"], text))
            del hub["log"][:-300]
            bump()

    def my_port():
        return st["server"].port if st["server"] else int(lc.get("port", LINK_PORT))

    def run(work, done):
        ui_background(page, work, done)

    def out(peer, target, files, spec, then=None):
        """Send the tab's work to a linked computer as a proposal (it waits there to be accepted). More than 200
        files go in batches of up to 200, one after the other, each accepted there on its own. then(ok) once every
        batch was answered there (ok = all accepted and applied there)."""
        if not peer_days_left(peer):
            return act(peer, "the link has expired - link it again in the Linked computers tab")
        try:
            parts = peer_batches(target, spec, files)
        except ValueError as e:
            return act(peer, f"not sent: {e}")
        bids, n, port = [secrets.token_hex(8) for _ in parts], len(parts), my_port()
        hub["sent"].update({b: peer["id"] for b in bids})
        if then:
            group = {"left": set(bids), "ok": True, "then": then, "peer": peer["id"]}
            hub["wait"].update({b: group for b in bids})
        each = f" in {n} batches of up to 200 - each one is accepted there on its own" if n > 1 else ""
        act(peer, f"sending {len(files)} file(s){each}..." if files else "sending...")

        def work():
            for k, ((fs, sp), b) in enumerate(zip(parts, bids)):
                peer_send(peer, lc["me"], fs, target, sp, port=port, batch=b, progress=lambda i, m, k=k: (
                    i == m or i % 25 == 0) and act(  # every 25 files: the log keeps the answers, not every file
                    peer, f"sending {i} of {m}" + (f" (batch {k + 1} of {n})" if n > 1 else "") + "..."))
        run(work, lambda r: act(peer, f"not sent: {r}" if isinstance(r, Exception) else
                                f"sent{each} - waiting for someone to accept it on {peer['name']}"))
    hub.update(label=label, send=out, run=run, act=act, wait={})

    def show_peers():
        sel = ptv.selection()
        ptv.delete(*ptv.get_children())
        for p in peers:
            left_ = peer_days_left(p)
            on = hub["state"].get(p["id"])
            ptv.insert("", "end", iid=p["id"], tags=("expired",) if not left_ else () if on and on[0] else ("off",),
                       values=(p["name"], f"{p['host']}:{p['port']}",
                               f"{peer_until(p)} ({left_} days)" if left_ else
                               "can't be read here - link again" if p.get("kept") else "expired - verify again",
                               hub["activity"].get(p["id"], "").split(": ", 1)[-1] or label(p).rsplit(" - ", 1)[-1]))
        if sel and ptv.exists(sel[0]):
            ptv.selection_set(sel[0])  # still the one picked
        p = peer_by(sel[0]) if sel else (peers[0] if len(peers) == 1 else None)
        obs_v.set(bool(p and p.get("obs")))

    def chosen():
        sel = ptv.selection()
        p = peer_by(sel[0]) if sel else (peers[0] if len(peers) == 1 else None)
        if not p:
            status.config(text="Pick a linked computer in the list first.")
        return p

    def keep_peer(p):
        peers[:] = [q for q in peers if q["id"] != p["id"]] + [p]
        hub["state"][p["id"]] = (True, time.time())
        bump()

    def pair(url=None):
        url = (url or v["link_to"].get()).strip()
        if not url:
            return status.config(text="Paste the other PC's pairing link first (its Link tab: Start receiving).")
        link_b.state(["disabled"])
        status.config(text="Asking the other PC - accept the link there...")

        def done(r):
            link_b.state(["!disabled"])
            if isinstance(r, Exception):
                return status.config(text=f"Not linked: {r}")
            keep_peer(r)
            act(r, "linked")
            v["link_to"].set("")
            status.config(text=f"Linked with {r['name']} until {peer_until(r)}.")
            save()
        name, port = v["device"].get(), my_port()  # read here: Tk is never touched from the worker thread
        run(lambda: peer_pair(url, lc["me"], name, port), done)

    def renew():
        p = chosen()
        if not p:
            return
        if not peer_days_left(p):
            return status.config(text=f"The link with {p['name']} has expired: paste its pairing link above and "
                                      "press Link to verify it again.")
        status.config(text=f"Asking {p['name']} to renew - accept it there...")

        def done(r):
            if isinstance(r, Exception):
                return status.config(text=f"Not renewed: {r}")
            keep_peer(r)
            act(r, f"renewed until {peer_until(r)}")
            status.config(text=f"Renewed: linked with {r['name']} until {peer_until(r)}.")
            save()
        run(lambda: peer_renew(p, lc["me"], port=my_port()), done)

    def rename():
        p = chosen()
        name = p and simpledialog.askstring("Rename", "Name for this computer:", initialvalue=p["name"], parent=page)
        if name and peer_name(name):
            p["name"] = peer_name(name)
            bump()
            save()

    def unlink():
        p = chosen()
        if not p or not messagebox.askyesno("Unlink", f"Unlink {p['name']}? It can't send here or open anything "
                                            "here any more (it's told, if it's online).", parent=page):
            return
        peers[:] = [q for q in peers if q["id"] != p["id"]]
        hub["activity"].pop(p["id"], None)
        bump()
        save()
        status.config(text=f"Unlinked {p['name']}.")
        run(lambda: peer_unlink(p, lc["me"]), lambda r: None)

    def check_all(again=True):
        """Who's online; one whose address changed is looked for on the home network (only it can answer)."""
        todo = [dict(p) for p in peers if peer_days_left(p)]

        def work():
            res = {}
            for p in todo:
                res[p["id"]] = (False, None)
                for where in (None, "find"):
                    if where:
                        try:
                            found = peer_find(p, lc["me"])
                        except OSError:
                            found = None
                        if not found:
                            break
                        p.update(host=found[0], port=found[1])
                    try:
                        peer_hello(p, lc["me"], port=my_port(), timeout=3)
                        res[p["id"]] = (True, (p["host"], p["port"]) if where else None)
                        break
                    except (OSError, ValueError):
                        pass
            return res

        def done(res):
            if not isinstance(res, Exception):
                for pid, (on, found) in res.items():
                    p = peer_by(pid)
                    if p:
                        if found:
                            p.update(host=found[0], port=found[1])
                        hub["state"][pid] = (on, time.time() if on else (hub["state"].get(pid) or (0, 0))[1])
                bump()
            if again:
                page.after(20000, check_all)
        run(work, done)
    last = {}

    def send_files_to(again=False):
        """Files straight to the selected linked computer, to the tab that fits them (pictures: VTube Studio,
        sounds: Import to folders, recordings: kept as files, videos: Channel Mirror) - or the same again."""
        p = chosen()
        if not p:
            return
        if again:
            if not last:
                return status.config(text="Nothing sent yet - Send files... first.")
            files, target = last["files"], last["target"]
        else:
            files = [Path(f) for f in filedialog.askopenfilenames(parent=page, title=f"Files to send to {p['name']}")]
            if not files:
                return
            target = link_default_target(files)
        try:
            peer_check_files(target, {}, files)
        except ValueError as e:
            return status.config(text=f"Can't send that: {e}")
        last.update(files=files, target=target)
        out(p, target, files, {})
        status.config(text=f"Sending {len(files)} file(s) to {p['name']} ({LINK_TARGETS[target]}) - it waits there to "
                           "be accepted.")
    for text, fn, tip in (("Send files...", send_files_to, "Pick files: they go to the tab that fits them there"),
                          ("Send again", lambda: send_files_to(True), "The same files to the same place again"),
                          ("Check now", lambda: check_all(False), "Who's online (checked every 20 s anyway)"),
                          ("Renew", renew, f"Verify the link again: {PEER_DAYS} fresh days (accepted there)"),
                          ("Rename", rename, "The name shown for it here"),
                          ("Unlink", unlink, "Forget it here, and tell it so")):
        Tip(ttk.Button(pb, text=text, style="Tool.TButton", command=fn), tip)
    for b in pb.winfo_children():
        b.pack(side="left", padx=(0, 6))
    obs_v = tk.BooleanVar()  # the selected computer may run OBS commands here at once (no question): off unless on

    def obs_allow():
        p = chosen()
        if not p:
            return obs_v.set(False)
        p["obs"] = obs_v.get()
        act(p, "may control OBS on this PC" if p["obs"] else "may not control OBS on this PC")
        save()
    obs_cb = ttk.Checkbutton(kf, text="May control OBS on this PC (scenes, sources, audio, stream, record - at once, "
                                      "no question)", variable=obs_v, command=obs_allow)
    obs_cb.pack(anchor="w", pady=(0, 4))
    Tip(obs_cb, "For the selected linked computer only, off unless you turn it on. Its OBS commands run straight "
                "away (live use mid-stream). Files it sends for OBS are still asked about here.")
    ptv.bind("<<TreeviewSelect>>", lambda e: obs_v.set(bool((peer_by((ptv.selection() or [""])[0]) or {})
                                                                .get("obs"))), add="+")
    if home is not None:  # everything for the selected computer, and what's going back and forth
        class Both:  # messages show in the Link tab and the Linked computers tab
            def __init__(self, a, b):
                self.a, self.b = a, b

            def config(self, **k):
                self.a.config(**k)
                self.b.config(**k)

            def cget(self, k):
                return self.b.cget(k)
        status = Both(status, hstatus)
        wf = ttk.LabelFrame(hr, text="With the selected computer")
        wf.pack(fill="x")
        ttk.Label(wf, text="Open its things here, or a tool already pointed at it.", style="Hint.TLabel").pack(
            anchor="w")
        tools = ttk.Frame(wf)
        tools.pack(fill="x", pady=(4, 0))
        devl = ttk.Label(wf, style="Hint.TLabel", wraplength=520, justify="left")
        devl.pack(anchor="w", pady=(4, 4))

        def decks():
            p = chosen()
            if p:
                devl.config(text=f"Asking {p['name']}...")
                run(lambda: peer_browse(p, lc["me"]), lambda r: devl.config(
                    text=f"Couldn't ask {p['name']}: {r}" if isinstance(r, Exception) else
                    f"Stream Decks on {p['name']}: " + ("; ".join(d.get("name", "?") for d in r.get("devices") or [])
                                                        or "none") + "  |  VTube Studio models: " +
                    (", ".join((r.get("vts") or {}).get("models") or []) or "none")))

        def pull():
            p = chosen()
            got = p and ui_library(page, hub, LINK_EXT, f"Files from {p['name']}", source=p["name"])
            if got:
                status.config(text=f"Fetched {len(got)} file(s) from {p['name']} into {got[0].parent}")
        buttons = [("Its Stream Decks", decks), ("Get its files...", pull),
                   ("Record there", lambda: (p := chosen()) and out(p, "record", [], {"action": "start"})),
                   ("Stop there", lambda: (p := chosen()) and out(p, "record", [], {"action": "stop"}))]
        for i, (text, fn) in enumerate(buttons + [(t, lambda f=f: (p := chosen()) and f(p))
                                                  for t, f in provide.get("jump", [])]):
            ttk.Button(tools, text=text, style="Tool.TButton", command=fn).grid(row=i // 3, column=i % 3, sticky="ew",
                                                                                padx=(0, 6), pady=2)
        lf_ = ttk.LabelFrame(hr, text="Going back and forth")
        lf_.pack(fill="both", expand=True, pady=(10, 0))
        logv = ttk.Treeview(lf_, columns=("t", "who", "what"), show="headings", height=7)
        for c, h, w in (("t", "Time", 70), ("who", "Computer", 100), ("what", "What", 360)):
            logv.heading(c, text=h)
            logv.column(c, width=w, stretch=c == "what")
        logv.pack(fill="both", expand=True)

        def show_log():
            logv.delete(*logv.get_children())
            for row in reversed(hub["log"][-100:]):
                logv.insert("", "end", values=row)
        hub["listeners"].append(show_log)

    asking = threading.BoundedSemaphore(4)

    def ask(kind, info):
        """A linked computer's request, from the server's thread: answered here (on this window's thread)."""
        if kind in ("seen", "result", "unlink"):
            events.put(("note", (kind, info)))
            return {}
        if kind == "obs":  # live use mid-stream: answered at once, here (the OBS tab checks that PC may)
            return provide["obs"](info) if "obs" in provide else {"ok": False, "error": "No OBS on that computer"}
        if not asking.acquire(timeout=5):  # a few at a time: a flood waits, then is refused
            return None
        try:
            box, ev = {}, threading.Event()
            events.put(("ask", (kind, info, box, ev)))
            if not ev.wait(PEER_ASK if kind in ("pair", "renew") else 30):
                box["dead"] = True  # too late: its question is never shown (or its answer used)
            return box.get("r")
        finally:
            asking.release()

    def answer(kind, info):
        if kind == "pair":
            new_code()  # the code is used up, whatever the answer: a new one shows for the next device
            old = peer_by(info["id"])
            if old and peer_days_left(old):  # never a silent swap of a working link
                status.config(text=f"{info['name']} ({info['host']}) asked to link, but {old['name']} is already "
                                   "linked with that id - unlink it first to link again.")
                return None
            if not messagebox.askyesno("Link computers", f"{info['name']} ({info['host']}) wants to link with this "
                                       f"PC for {PEER_DAYS} days.\n\nLinked, it can see this PC's Stream Deck "
                                       "profiles, VTube Studio models and Channel Mirror files, and send files and "
                                       "changes here - each one still waits for you to accept it.\n\nLink them?",
                                       parent=page):
                return None
            p = {k: info[k] for k in ("id", "name", "host", "port", "secret")}
            keep_peer(dict(p, since=time.time()))
            act(p, "linked")
            save()
            return {"id": lc["me"], "name": peer_name(v["device"].get()) or "Channel Mirror"}
        if kind == "renew":
            p = peer_by(info["id"])
            if not p or not messagebox.askyesno("Renew link", f"{p['name']} asks to renew the link for another "
                                                f"{PEER_DAYS} days. Renew it?", parent=page):
                return None
            keep_peer(dict(p, secret=info["secret"], since=time.time(), host=info["host"]))
            act(p, f"renewed until {peer_until(peer_by(p['id']))}")
            save()
            return {"ok": True}
        try:
            return provide[kind](info) if kind in provide else None
        except Exception as e:  # a read that can't be answered: refused, never half-answered
            status.config(text=f"A linked computer's request failed: {e}")
            return None

    def note(kind, info):
        p = peer_by(info.get("id"))
        if not p:
            return
        if kind == "seen":
            p.update(host=info["host"], port=info["port"])
            hub["state"][p["id"]] = (True, time.time())
            bump()
        elif kind == "result":
            act(p, f"{'accepted' if info['ok'] else 'declined'} on {p['name']}" +
                (f" - {info['note']}" if info["note"] and info["note"] not in ("Accepted", "Declined") else ""))
            g = hub["wait"].get(info["batch"])
            if g and g["peer"] == p["id"]:  # the answer to a send that waits for it (a move), from where it went
                hub["wait"].pop(info["batch"])
                g["left"].discard(info["batch"])
                g["ok"] = g["ok"] and info["ok"]
                if not g["left"]:
                    g["then"](g["ok"])
        elif kind == "unlink":
            peers[:] = [q for q in peers if q["id"] != p["id"]]
            bump()
            save()
            status.config(text=f"{p['name']} unlinked this PC.")

    def keep_files(files):
        """Received copies moved to Incoming\\Received (keys play them from there)."""
        stamp = LINK_INBOX / "Received" / time.strftime("%Y-%m-%d %H-%M-%S")
        placed = []
        for f in map(Path, files):
            if f.is_relative_to(LINK_INBOX / "pending"):
                stamp.mkdir(parents=True, exist_ok=True)
                dst, n = stamp / f.name, 2
                while dst.exists():
                    dst, n = stamp / f"{f.stem} ({n}){f.suffix}", n + 1
                shutil.move(f, dst)
                f = dst
            placed.append(f)
        return placed

    def arrived_peer(x):
        """A linked computer's proposal: shown, then handed to its tab (accepted) or deleted (declined); either way
        the sender is told."""
        p = peer_by(x["peer"])
        name = p["name"] if p else x["address"]
        where = ({"edit": "Stream Deck keys", "record": "Screen recorder", "obs": "OBS"}.get(x["target"])
                 or LINK_TARGETS[x["target"]])
        act(p, f"a proposal arrived for {where}")
        ok, why = ui_proposal(page, f"From {name} (linked computer) - for {where}",
                              peer_summary(x["target"], x["spec"], x["files"]) +  # + what exactly, here
                              (provide["here"](x["target"], x["spec"]) if "here" in provide else [])), ""
        if ok:
            try:
                deliver(x["target"], keep_files(x["files"]), x["spec"], p)
                status.config(text=f"Accepted from {name}: {where}.")
            except Exception as e:
                ok, why = False, f"couldn't be applied here: {e}"
                status.config(text=f"From {name}: {why}")
        else:
            for f in x["files"]:
                if Path(f).is_relative_to(LINK_INBOX):
                    Path(f).unlink(missing_ok=True)
            status.config(text=f"Declined what {name} sent ({where}).")
        act(p, f"{'accepted' if ok else 'declined'} here ({where})")
        if p:
            run(lambda: peer_result(p, lc["me"], x["batch"], ok, why or ("Accepted" if ok else "Declined")),
                lambda r: None)

    # receive
    rf = ttk.LabelFrame(right, text="Receive from other devices  (home network)")
    rf.pack(fill="x")
    ttk.Label(rf, text="Start, then open the pairing link on the other device (phone, laptop, another PC) - it shows "
                       "a page to send files. Each batch shows here and is placed only when you accept it.",
              style="Hint.TLabel", wraplength=520, justify="left").pack(anchor="w")
    r1 = ttk.Frame(rf)
    r1.pack(fill="x", pady=(6, 0))
    start_b = ttk.Button(r1, text="Start receiving", style="Accent.TButton", command=lambda: toggle())
    start_b.pack(side="left")
    ttk.Label(r1, text="Port").pack(side="left", padx=(12, 0))
    ttk.Spinbox(r1, textvariable=v["port"], from_=1024, to=65535, width=6).pack(side="left", padx=4)
    ttk.Label(r1, text="Code").pack(side="left", padx=(8, 0))
    ttk.Label(r1, textvariable=v["code"], font=("Segoe UI", 12, "bold")).pack(side="left", padx=4)
    ttk.Button(r1, text="New code", style="Tool.TButton", command=lambda: new_code()).pack(side="left", padx=4)
    r2 = ttk.Frame(rf)
    r2.pack(fill="x", pady=(6, 0))
    ttk.Entry(r2, textvariable=v["pair"], width=44, state="readonly").pack(side="left", fill="x", expand=True)
    ttk.Button(r2, text="Copy", style="Tool.TButton", command=lambda: copy(v["pair"].get())).pack(side="left", padx=4)
    recv_l = ttk.Label(rf, style="Hint.TLabel", wraplength=520, justify="left")
    recv_l.pack(anchor="w", pady=(4, 4))

    # send
    sf = ttk.LabelFrame(right, text="Send to another device")
    sf.pack(fill="x", pady=(10, 0))
    ttk.Label(sf, text="Paste the pairing link the other Channel Mirror shows (Receive, Start).", style="Hint.TLabel"
              ).pack(anchor="w")
    ttk.Entry(sf, textvariable=v["dest"], width=52).pack(fill="x", pady=(4, 0))
    s2 = ttk.Frame(sf)
    s2.pack(fill="x", pady=(4, 0))
    ttk.Combobox(s2, textvariable=v["send_to"], values=list(names), state="readonly", width=34).pack(side="left")
    ttk.Label(s2, text="from").pack(side="left", padx=(8, 0))
    ttk.Entry(s2, textvariable=v["device"], width=16).pack(side="left", padx=4)
    s3 = ttk.Frame(sf)
    s3.pack(fill="x", pady=(4, 4))
    send_l = ttk.Label(sf, style="Hint.TLabel")

    def add_send(got=None):
        send_files.extend(Path(f) for f in (filedialog.askopenfilenames(parent=page, title="Files to send")
                                            if got is None else got))
        send_l.config(text=f"{len(send_files)} file(s): " + ", ".join(f.name for f in send_files[:5]) +
                      (" ..." if len(send_files) > 5 else ""))
    ttk.Button(s3, text="Add files...", style="Tool.TButton", command=add_send).pack(side="left")
    ttk.Button(s3, text="From Channel Mirror...", style="Tool.TButton",
               command=lambda: add_send(ui_library(page, hub, LINK_EXT))).pack(side="left", padx=(4, 0))
    ttk.Button(s3, text="Clear", style="Tool.TButton",
               command=lambda: (send_files.clear(), send_l.config(text=""))).pack(side="left", padx=4)
    send_b = ttk.Button(s3, text="Send", style="Accent.TButton", command=lambda: send())
    send_b.pack(side="right")
    send_l.pack(anchor="w")

    def copy(text):
        if text:
            page.clipboard_clear()
            page.clipboard_append(text)
            status.config(text="Copied.")

    def new_code():
        v["code"].set(f"{secrets.randbelow(10 ** 8):08d}")
        if st["server"]:
            st["server"].code = v["code"].get()
            v["pair"].set(link_pair_url(link_lan_ip(), st["server"].port, v["code"].get()))
        save()

    def toggle(auto=False):
        if auto and (st["server"] or link_public_network()):
            return recv_l.config(text="Not started by itself: Windows has this network marked Public.")
        if st["server"]:
            st["server"].stop()
            st["server"] = None
            start_b.config(text="Start receiving")
            v["pair"].set("")
            recv_l.config(text="Stopped - nothing can be sent to this PC now.")
            return
        if link_public_network() and not messagebox.askyesno(
                "Receive", "Windows has this network marked Public (like cafe or hotel Wi-Fi). Other people on it "
                "could try to send files here.\n\nOnly start on your own home network. Start anyway?", parent=page):
            return
        v["code"].set(f"{secrets.randbelow(10 ** 8):08d}")  # a fresh code every start
        try:
            port = int(v["port"].get())
            st["server"] = LinkServer(port, v["code"].get(), LINK_INBOX / "pending",
                                      lambda info: events.put(("batch", info)), name=peer_name(v["device"].get()),
                                      peers=lambda: {p["id"]: (p["secret"], p["since"]) for p in list(peers) if p["secret"]},
                                      ask=ask, nonces=LINK_INBOX.with_name(LINK_INBOX.name + ".nonces.json"))
        except (ValueError, OSError) as e:
            return messagebox.showerror("Receive", f"Couldn't start on port {v['port'].get()}:\n{e}", parent=page)
        start_b.config(text="Stop receiving")
        v["pair"].set(link_pair_url(link_lan_ip(), st["server"].port, v["code"].get()))
        recv_l.config(text="Receiving. Open the pairing link on the other device. It's plain http on your own "
                           "network - only use it at home. (Windows may ask once whether Channel Mirror may use the "
                           "network - allow private networks only.)")
        save()

    def send():
        if not send_files:
            return messagebox.showinfo("Send", "Add the files to send first.", parent=page)
        dest, files, to, dev = v["dest"].get(), list(send_files), names[v["send_to"].get()], v["device"].get()
        send_b.state(["disabled"])
        status.config(text=f"Sending {len(files)} file(s)...")

        def done(res):
            send_b.state(["!disabled"])
            if isinstance(res, Exception):
                status.config(text=f"Not sent: {res}")
                return messagebox.showerror("Send", f"Not sent:\n{res}", parent=page)
            status.config(text=f"Sent {res} file(s) - they're waiting to be accepted on the other device.")
            save()
        ui_background(page, lambda: link_send(dest, files, to, dev), done)

    def arrived(files, target, source):
        """Show what came, then place it (accepted) or delete the received copies (declined). Accepted copies move
        to Incoming\\Received (keys will play them from there); waiting ones are cleared on Stop."""
        to = ui_incoming(page, files, target, source)
        if to:
            files = keep_files(files)
            deliver(to, files)
            status.config(text=f"Accepted {len(files)} file(s) from {source} into {LINK_TARGETS[to]}.")
        else:
            for f in files:
                if Path(f).is_relative_to(LINK_INBOX):  # only copies that were received, never your own files
                    Path(f).unlink(missing_ok=True)
            status.config(text=f"Declined {len(files)} file(s) from {source}.")

    def open_link(text):
        """A channelmirror:// link: its files (and downloads) shown, then placed once accepted."""
        try:
            lk = link_parse(text)
        except ValueError as e:
            return status.config(text=f"Not a link Channel Mirror can open: {e}")
        files = [f for f in lk["files"] if f.is_file() and f.suffix.lower() in LINK_EXT]
        missing = len(lk["files"]) - len(files)
        if not lk["urls"]:
            if not files:
                return status.config(text="That link has no files that exist on this PC.")
            return arrived(files, lk["to"], "a link from outside the app" +
                           (f" ({missing} file(s) not found)" if missing else ""))
        if not messagebox.askyesno("Download?", "A link wants to download:\n\n" + "\n".join(lk["urls"][:10]) +
                                   ("\n..." if len(lk["urls"]) > 10 else "") + "\n\nDownload them? (You'll see them "
                                   "before anything is placed.)", parent=page):
            return status.config(text="Download skipped.")
        status.config(text=f"Downloading {len(lk['urls'])} file(s) from the link...")
        folder = LINK_INBOX / "pending" / f"link-{secrets.token_hex(4)}"

        def fetched(res):
            if isinstance(res, Exception):
                shutil.rmtree(folder, ignore_errors=True)
                return status.config(text=f"Download failed (nothing kept): {res}")
            arrived(files + res, lk["to"], "a link from outside the app: " + ", ".join(lk["urls"][:3]))
        ui_background(page, lambda: [link_fetch(u, folder) for u in lk["urls"]], fetched)

    def poll():
        try:
            while True:
                kind, x = events.get_nowait()
                try:  # one bad batch / link never stops the ones after it
                    if kind == "ask":
                        k, info, box, ev = x
                        try:
                            if not box.get("dead"):
                                box["r"] = answer(k, info)
                        finally:
                            ev.set()
                    elif kind == "note":
                        note(*x)
                    elif kind == "batch" and x.get("peer"):
                        page.winfo_toplevel().deiconify()
                        arrived_peer(x)
                    elif kind == "batch":
                        recv_l.config(text=f"{x['time']}: {len(x['files'])} file(s) from {x['from']} "
                                           f"({x['address']})")
                        page.winfo_toplevel().deiconify()
                        arrived(x["files"], x["target"], f"{x['from']} ({x['address']}, another device)")
                    else:
                        page.winfo_toplevel().deiconify()
                        open_link(x)
                except Exception as e:
                    status.config(text=f"Couldn't handle what arrived: {e}")
        except queue.Empty:
            pass
        finally:
            if hub["v"][0] != st.get("v"):  # something changed: the list, every tab's strip, open windows
                st["v"] = hub["v"][0]
                show_peers()
                for f in list(hub["listeners"]):
                    try:
                        f()
                    except Exception:
                        hub["listeners"].remove(f)
            page.after(300, poll)

    def sealed(p):
        if p.get("kept"):  # couldn't be read here: kept as it was
            return p["kept"]
        try:
            return dict(p, secret=secret_keep(p["secret"]))
        except OSError:  # Windows couldn't seal it: not kept (linked again after a restart)
            return dict(p, secret="")

    def save():
        """Into the settings, and written now (a new link or renewal is never lost to a crash): secrets sealed."""
        try:
            lc.update(port=int(v["port"].get()))
        except ValueError:
            pass
        lc.pop("code", None)  # the code is never kept
        lc.update(dest=v["dest"].get(), device=v["device"].get(), peers=[sealed(p) for p in peers])
        try:
            settings_put(link=lc)
        except OSError:
            status.config(text="Couldn't write the settings file - the links are kept when the app closes.")

    def stop():
        if st["server"]:
            st["server"].stop()
            st["server"] = None
    show_reg()
    if old_plain:  # secrets kept in plain text by an older version: sealed now
        save()
    poll()
    show_peers()
    if peers:  # linked computers reach this PC by themselves: receiving starts with the app
        page.after(1000, lambda: toggle(auto=True))
    page.after(1500, check_all)
    return {"open_link": lambda text: events.put(("link", text)), "stop": stop, "save": save,
            "toggle": toggle, "vars": v, "state": st, "make_files": make_files, "send_files": send_files,
            "hub": hub, "pair": pair, "renew": renew, "unlink": unlink, "check": check_all, "tree": ptv,
            "obs_allow": obs_cb,
            "status": lambda: status.cget("text")}
