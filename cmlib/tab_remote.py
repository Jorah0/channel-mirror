"""The phone remote tab."""
import hashlib
import json
import queue
import re
import threading
import time
from pathlib import Path
from .core import secret_keep, secret_read, settings_put
from .deck import sd_sounds, sd_title
from .link import link_public_network
from .music import MusicOut, SoundFeed, music_title
from .peers import PEER_ASK, peer_name
from .remote import REMOTE_PORT, RemoteServer, qr_matrix, qr_png, remote_apk, remote_app_label, remote_hosts, \
    remote_tailnet, remote_url, remote_versions, tailscale_info
from .vts import VTS_API_PORT, vts_api, vts_backgrounds
from .ui import Tip, px, ui_background, ui_empty

DECK_SB = "The Stream Deck soundboard tab's sounds"


def remote_tab(page, cfg, parts):
    """The Phone remote page: turn the remote on (it listens on the home network and Tailscale addresses only), pair a
    phone (a one-time code as a QR code; this PC's user allows it), the paired phones (last seen, Remove), what the
    phone's Deck shows (the soundboard tab's sounds or a Stream Deck page's sound keys), VTube Studio's API (allowed
    once here) and how to reach it from anywhere with Tailscale. parts = the other pages' handles: music, obs,
    recorder, sound (the soundboard), editor (or None), name() (this PC's name).
    Returns {"stop", "save", "toggle", "pair", "remove", "vars", "state", "devices", ...} for the window and tests."""
    import base64
    import tkinter as tk
    from tkinter import messagebox, ttk
    rc = cfg.setdefault("remote", {})
    devices, unread = [], 0  # {id, name, key, since, seen}
    for d in rc.get("devices") or []:
        key = secret_read(d.get("key")) if isinstance(d, dict) else None
        if key and re.fullmatch(r"[0-9a-f]{64}", key) and re.fullmatch(r"[0-9a-f]{32}", str(d.get("id", ""))):
            app = d.get("app") if isinstance(d.get("app"), dict) else {}
            devices.append({"id": d["id"], "name": peer_name(d.get("name", ""), 40) or "Phone", "key": key,
                            "since": float(d.get("since") or 0), "seen": float(d.get("seen") or 0),
                            "app": {"web": str(app.get("web", ""))[:16], "apk": app["apk"]}
                            if isinstance(app.get("apk"), int) else None})
        else:  # sealed for another Windows user / PC, or damaged: that phone pairs again
            unread += 1
    calls = queue.Queue()  # work for this window's thread, from the server's
    here, lock = SoundFeed(), threading.Lock()  # sounds a phone plays on this PC's own output
    tok = secret_read(rc.get("vts_token")) or ""
    st = {"server": None, "deck": ("0" * 16, []), "choices": {}, "vts": (0.0, {}), "ts": {}, "out": None,
          "idle": 0.0, "code": None, "get": False, "img": None, "urls": {}, "vts_tok": tok, "n": 0, "nonces": {},
          "vts_port": int(rc.get("vts_port") or VTS_API_PORT), "here_playing": here.playing}
    v = {"port": tk.StringVar(value=str(rc.get("port", REMOTE_PORT))), "addr": tk.StringVar(),
         "deck": tk.StringVar(value=rc.get("deck") or DECK_SB), "vts_port": tk.StringVar(value=str(st["vts_port"])),
         "state": tk.StringVar(value="Off - turn it on to use a phone or tablet as a remote."),
         "code": tk.StringVar(), "vts": tk.StringVar(value="Allowed - VTube Studio answers phones." if tok else
                                                     "Not allowed yet."),
         "ts": tk.StringVar(value="Press Look again to find this PC on Tailscale.")}
    status = ttk.Label(page, style="Status.TLabel", anchor="w", wraplength=1100, justify="left")
    status.pack(side="bottom", fill="x", padx=12, pady=(0, 6))
    body = ttk.Frame(page, padding=(12, 6, 12, 0))
    body.pack(fill="both", expand=True)
    cols = [ttk.Frame(body) for _ in range(3)]
    for i, c in enumerate(cols):
        c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
        body.columnconfigure(i, weight=1, uniform="remote")
    body.rowconfigure(0, weight=1)

    def box(col, text, grow=False):
        f = ttk.LabelFrame(col, text=text)
        f.pack(fill="both" if grow else "x", expand=grow, pady=(0, 8))
        return f

    def row(parent, pady=(4, 0)):
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=pady)
        return r

    def hint(parent, text="", var=None):
        lab = ttk.Label(parent, text=text, textvariable=var, style="Hint.TLabel", wraplength=px(320), justify="left")
        lab.pack(anchor="w", fill="x", pady=(4, 0))
        return lab

    # the remote: on / off, where the phone opens it
    rf = box(cols[0], "Phone remote")
    r = row(rf, 0)
    on_b = ttk.Button(r, text="Turn on", style="Accent.TButton", command=lambda: toggle())
    on_b.pack(side="left")
    ttk.Label(r, text="Port").pack(side="left", padx=(12, 4))
    ttk.Spinbox(r, textvariable=v["port"], from_=1024, to=65535, width=6).pack(side="left")
    hint(rf, var=v["state"])
    ttk.Label(rf, text="Open on the phone").pack(anchor="w", pady=(8, 0))
    r = row(rf)
    addr_cb = ttk.Combobox(r, textvariable=v["addr"], state="readonly", width=30)
    addr_cb.pack(side="left", fill="x", expand=True)
    ttk.Button(r, text="Copy", style="Tool.TButton", command=lambda: copy()).pack(side="left", padx=(4, 0))
    hint(rf, "Plain http. Through Tailscale it's encrypted (WireGuard) - use that address. On the home network it "
             "isn't: someone on your Wi-Fi who intercepts traffic could see what you tap, or change the page and take "
             "over the pairing. Use the home address only on a network you trust.")
    df = box(cols[0], "Deck")
    ttk.Label(df, text="The phone's Deck shows").pack(anchor="w")
    deck_cb = ttk.Combobox(df, textvariable=v["deck"], state="readonly", postcommand=lambda: deck_cb.configure(
        values=list(choices())))
    deck_cb.pack(fill="x", pady=(4, 0))
    hint(df, "A tap plays the sound into the soundboard feed (start it on the OBS page) and / or on this PC.")
    vf = box(cols[0], "VTube Studio")
    r = row(vf, 0)
    allow_b = ttk.Button(r, text="Allow in VTube Studio", style="Tool.TButton", command=lambda: allow_vts())
    allow_b.pack(side="left")
    ttk.Label(r, text="API port").pack(side="left", padx=(12, 4))
    ttk.Spinbox(r, textvariable=v["vts_port"], from_=1, to=65535, width=6).pack(side="left")
    hint(vf, var=v["vts"])
    hint(vf, "In VTube Studio: Settings > Start API on. Then Allow here, and Allow in VTube Studio. Phones switch the "
             "loaded model's background hotkeys (the VTube Studio backgrounds page makes them).")

    # pairing
    pf = box(cols[1], "Pair a phone")
    pair_b = ttk.Button(pf, text="Pair a phone", style="Accent.TButton", command=lambda: pair())
    pair_b.pack(anchor="w")
    Tip(pair_b, "A new one-time code (5 minutes) - scan it with the phone's camera")
    qr = ttk.Label(pf, anchor="center")
    qr.pack(fill="x", pady=(8, 0))
    ttk.Label(pf, textvariable=v["code"], style="Name.TLabel", anchor="center").pack(fill="x")
    hint(pf, "Scan the code with the phone's camera (or open the address and type the code). The PC asks you to "
             "allow it. Don't show the code on stream or in a screen share. iPhone: Share > Add to Home Screen first, open it from there, and pair there. Android: "
             "the app below, or menu > Add to Home screen.")
    get_b = ttk.Button(pf, text="Get the Android app", style="Tool.TButton", command=lambda: get_app())
    get_b.pack(anchor="w", pady=(8, 0))
    Tip(get_b, "A QR code for the phone's camera: it downloads the app (CM Remote) from this PC")
    hint(pf, "Android: the phone's browser downloads it (best over the Tailscale address: encrypted); allow that "
             "browser to install unknown apps when Android asks (once). Open CM Remote, check its signing key matches "
             "the one said below, type the address above, then pair it with a code. It updates itself from this PC.")

    # the paired phones; Tailscale
    lf = box(cols[2], "Paired phones", grow=True)
    r = ttk.Frame(lf)
    r.pack(side="bottom", fill="x", pady=(4, 0))
    ttk.Button(r, text="Remove", style="Tool.TButton", command=lambda: remove()).pack(side="left")
    tree = ttk.Treeview(lf, columns=("name", "since", "seen", "app"), show="headings", height=3, selectmode="browse")
    ui_empty(tree, "No phone paired yet.")
    for c, h, w in (("name", "Phone", 100), ("since", "Paired", 60), ("seen", "Last seen", 80), ("app", "App", 110)):
        tree.heading(c, text=h)
        tree.column(c, width=px(w), stretch=c == "name")
    tree.pack(fill="both", expand=True)
    tf = box(cols[2], "From anywhere: Tailscale")
    hint(tf, "1. Install Tailscale (free) on this PC and on the phone: tailscale.com/download\n2. Sign in to the same "
             "account on both.\n3. Pair the phone with the Tailscale address (it works at home and away).")
    hint(tf, var=v["ts"])
    ttk.Button(tf, text="Look again", style="Tool.TButton", command=lambda: look()).pack(anchor="w", pady=(4, 0))

    def say(text):
        status.config(text=text)

    def pc_name():
        try:
            return peer_name(parts["name"](), 60) or "Channel Mirror"
        except Exception:
            return "Channel Mirror"

    def ui(fn, secs=10):
        """fn() on this window's thread (from the server's), its answer; ValueError when the PC is too busy."""
        box_, ev = {}, threading.Event()
        calls.put((fn, box_, ev))
        if not ev.wait(secs):
            box_["late"] = True  # never run (or its answer used) once given up on
            raise ValueError("The PC is busy - try again")
        if "e" in box_:
            raise box_["e"]
        return box_.get("r")

    def by_id(i):
        return next((d for d in devices if d["id"] == i), None)

    # --- what a phone asks (server thread) ---
    def run(dev, cmd, a):
        d = by_id(dev)
        if d:
            d["seen"] = time.time()
        who = d["name"] if d else "A phone"
        if cmd == "state":
            out = ui(local)
            try:
                o = parts["obs"]["phone"]("state", {})
                o.pop("sounds", None)
                out["obs"] = o
            except Exception as e:
                out["obs"] = {"error": str(e)[:200]}
            out["vts"] = vts_state()
            return out
        if cmd == "deck":
            rev, items = ui(deck_list)
            return {"rev": rev, "sounds": [{"id": i, "name": n} for i, (n, _) in enumerate(items)]}
        if cmd == "deck.play":
            rev, items = st["deck"]
            if a["rev"] != rev or a["id"] >= len(items):
                raise ValueError("The deck changed on the PC - it's shown again now")
            name, f = items[a["id"]]
            if not f.is_file():
                raise ValueError(f"{name}: its sound file isn't on the PC any more")
            if a["to"] in ("feed", "both"):
                parts["obs"]["feed"].play(f)
            if a["to"] in ("here", "both"):
                play_here(f)
            note(f"{who} played {name}")
            return {}
        if cmd == "deck.stop":
            parts["obs"]["feed"].stop()
            here.stop()
            return {}
        if cmd == "obs":
            out = parts["obs"]["phone"](a["cmd"], a["args"])
            if a["cmd"] != "state":
                note(f"{who}: OBS {a['cmd']}")
            return {"result": out}
        if cmd.startswith("music."):
            return ui(lambda: music(cmd, a, who))
        if cmd.startswith("rec."):
            return ui(lambda: rec(cmd, who))
        if cmd.startswith("app."):  # the server answers these; noted here: its version, an update going on
            if cmd == "app.check" and d:
                d["app"] = dict(a)
                calls.put((show_devices, {"late": False}, threading.Event()))  # its version shown now
            elif cmd == "app.web" or a.get("part") == 0:
                note(f"{who} is updating its app")
            return {}
        if cmd == "vts.bg":
            bgs = {b["id"]: b["name"] for b in vts_state().get("backgrounds") or []}
            if a["id"] not in bgs:
                raise ValueError("That background isn't on the model in VTube Studio now")
            vts_api(st["vts_port"], st["vts_tok"], [("HotkeyTriggerRequest", {"hotkeyID": a["id"]})])
            note(f"{who}: VTube Studio background {bgs[a['id']]}")
            return {}
        raise ValueError("Not something the phone remote does")

    def note(text):
        calls.put((lambda: say(f"{time.strftime('%H:%M:%S')}  {text}"), {"late": False}, threading.Event()))

    def local():
        """What the phone shows that lives in this window: the music, the recorder, the deck's version."""
        M, R = parts["music"], parts["recorder"]
        eng, ms, lists = M["engine"], M["state"], M["lists"]
        li = next((i for i, p in enumerate(lists) if p is ms["pl"]), -1) if eng.song else -1
        si = next((j for j, s in enumerate(lists[li]["songs"]) if s["path"] == ms["path"]), -1) if li >= 0 else -1
        cur = min(max(int(cfg.get("music", {}).get("current", 0) or 0), 0), len(lists) - 1)
        rec = R["state"]
        rev = deck_list()[0]
        feed_off = not parts["obs"]["state"].get("srv")
        return {"pc": pc_name(), "deck_rev": rev, "deck_note": "The soundboard feed is off on the PC, so 'OBS feed' "
                "isn't heard in OBS - start it on Channel Mirror's OBS page (Feeds)." if feed_off else "",
                "music": {"title": M["now"]["title"] if eng.song else "", "playlist": M["now"]["playlist"],
                          "paused": bool(eng.song and eng.paused), "pos": round(eng.position(), 1),
                          "len": round(float(ms["len"] or 0), 1), "volume": int(M["vars"]["vol"].get()),
                          "lists": [{"name": p["name"], "n": len(p["songs"])} for p in lists][:200],
                          "current": cur, "list": li, "song": si},
                "rec": {"recording": rec["proc"] is not None,
                        "secs": int(time.time() - rec.get("t0", time.time())) if rec["proc"] is not None else 0}}

    def choices():
        """The Deck's choices: the soundboard tab, or a page of a Stream Deck profile -> {text: (profile, page)}."""
        out = {DECK_SB: None}
        E = parts.get("editor")
        if E:
            for lb in E["profiles"]():
                for i, (pn, _) in enumerate(E["pages"](lb)):
                    out[f"{lb.replace('[connected] ', '')}: {pn}"] = (lb, i)
        st["choices"] = out
        return out

    def deck_list():
        """The sounds the phone's Deck shows (window thread): (version, [(name, file)])."""
        src, items, E = v["deck"].get(), [], parts.get("editor")
        where = st["choices"].get(src) or (choices().get(src) if src != DECK_SB else None)
        if where and E and where[0] in E["profiles"]():
            pages = E["pages"](where[0])
            kp = E["keys"](pages[where[1]][1]) if where[1] < len(pages) else {}

            def place(k):
                m = re.fullmatch(r"(\d+),(\d+)", k)
                return (int(m[2]), int(m[1])) if m else (999, 999)
            for k in sorted(kp, key=place):
                snd = [s for s in sd_sounds(kp[k]) if (s.get("Settings") or {}).get("path")] if kp[k] else []
                if snd:
                    f = Path(snd[0]["Settings"]["path"])
                    items.append((peer_name(sd_title(kp[k]).replace("\n", " "), 60) or f.stem, f))
        elif src == DECK_SB:
            items = [(peer_name(x.get("title") or Path(x["path"]).stem, 60), Path(x["path"]))
                     for x in list(parts["sound"].sounds)]
        items = items[:500]
        rev = hashlib.sha256(json.dumps([[n, str(f)] for n, f in items]).encode()).hexdigest()[:16]
        st["deck"] = (rev, items)
        return rev, items

    def play_here(f):
        with lock:  # this PC's output opens with the first sound and closes when they're done (an open one keeps
            if st["out"] is None:  # Windows from sleeping)
                st["out"] = MusicOut("")
                here.set_sink("out", st["out"].write)
            st["idle"] = time.time()
        here.play(f)

    def music(cmd, a, who):
        M = parts["music"]
        lists = M["lists"]
        if cmd in ("music.list", "music.play"):
            if a["list"] >= len(lists):
                raise ValueError("That playlist isn't there any more")
            p = lists[a["list"]]
            if cmd == "music.list":
                return {"songs": [music_title(s) for s in p["songs"]][:2000]}
            if a["song"] >= len(p["songs"]):
                raise ValueError("That song isn't in the playlist any more")
            M["play_at"](p, a["song"])
        elif cmd == "music.pause":
            M["pause"]()
        elif cmd == "music.resume":
            M["play"]()
        elif cmd in ("music.next", "music.prev"):
            M["skip"](1 if cmd == "music.next" else -1)
        elif cmd == "music.stop":
            M["halt"]()
        elif cmd == "music.seek":
            if M["engine"].song:
                M["engine"].seek(a["secs"])
        elif cmd == "music.volume":
            M["vars"]["vol"].set(a["percent"])
        say(f"{time.strftime('%H:%M:%S')}  {who}: {cmd[6:]}")
        return {}

    def rec(cmd, who):
        R = parts["recorder"]
        if cmd == "rec.start" and R["state"]["proc"] is None:
            R["start"]()
            if R["state"]["proc"] is None:
                raise ValueError("The recorder didn't start - see the Screen recorder page on the PC")
        elif cmd == "rec.stop" and R["state"]["proc"] is not None:
            R["stop"]()
        say(f"{time.strftime('%H:%M:%S')}  {who}: recording {'started' if cmd == 'rec.start' else 'stopped'}")
        return {}

    def vts_state():
        t0, got = st["vts"]
        if time.time() - t0 < 3:  # VTube Studio is asked at most every 3 s, however many phones look
            return got
        if not st["vts_tok"]:
            got = {"error": "VTube Studio isn't allowed yet - on the PC: Phone remote page > Allow in VTube Studio."}
        else:
            try:
                got = vts_backgrounds(st["vts_port"], st["vts_tok"])
            except OSError as e:
                got = {"error": str(e)[:200]}
        st["vts"] = (time.time(), got)
        return got

    def ask(info):
        """A phone proved the code (server thread): this PC's user allows it, or not."""
        return ui(lambda: allow(info), PEER_ASK)

    def allow(info):
        clear_code()
        if by_id(info["id"]):
            say(f"{info['name']} asked to pair with an id that's already paired - not allowed.")
            return None
        if not messagebox.askyesno("Pair a phone", f"Allow '{info['name']}' ({info['ip']}) to control Channel Mirror "
                                   "on this PC?\n\nIt can play sounds, switch OBS scenes and sources, start or stop "
                                   "streaming and recording, control the music, record the screen and switch VTube "
                                   "Studio backgrounds - until you remove it here.\n\nOnly allow a phone you just "
                                   "paired yourself.", parent=page, icon="warning", default="no"):
            say(f"{info['name']} wasn't allowed.")
            return None
        devices.append({"id": info["id"], "name": info["name"], "key": info["key"], "since": time.time(),
                        "seen": time.time()})
        save()
        show_devices()
        say(f"{info['name']} is paired - it can control Channel Mirror now.")
        return {"ok": True}

    # --- this window ---
    def addresses():
        srv, urls = st["server"], {}
        if srv:
            ts = st["ts"]
            for h in srv.hosts:
                urls[f"{remote_url(h, srv.port)}  ({'Tailscale' if remote_tailnet(h) else 'home network'})"] = \
                    remote_url(h, srv.port)
            if ts.get("name") and ts.get("ip") in srv.hosts:  # (its name finds the address listened on)
                urls = {f"{remote_url(ts['name'], srv.port)}  (Tailscale name)": remote_url(ts["name"], srv.port),
                        **urls}
            urls = dict(sorted(urls.items(), key=lambda kv: "home network" in kv[0]))  # Tailscale ones first
        if list(urls) != list(st["urls"]):  # new addresses: the first (Tailscale's, when there is one) is picked
            v["addr"].set(next(iter(urls), ""))
        st["urls"] = urls
        addr_cb.configure(values=list(urls))

    def copy():
        url = st["urls"].get(v["addr"].get())
        if not url:
            return say("Turn the remote on first - then its address shows here.")
        page.clipboard_clear()
        page.clipboard_append(url)
        say("Copied.")

    def toggle(auto=False):
        if st["server"]:
            st["server"].stop()
            st["server"], rc["on"] = None, False
            on_b.config(text="Turn on")
            v["state"].set("Off - phones can't reach this PC's remote now.")
            clear_code()
            return addresses()
        if link_public_network():
            if auto:
                return v["state"].set("Not started by itself: Windows has this network marked Public.")
            if not messagebox.askyesno("Phone remote", "Windows has this network marked Public (like cafe or hotel "
                                       "Wi-Fi). Only paired phones can use the remote, but others there could see "
                                       "what you tap.\n\nTurn it on anyway?", parent=page):
                return None
        try:
            port = int(v["port"].get())
            if not 0 <= port <= 65535:
                raise ValueError("a port is a number up to 65535")
            hosts = remote_hosts() + [st["ts"]["ip"]] if remote_tailnet(st["ts"].get("ip")) else remote_hosts()
            st["server"] = RemoteServer(hosts, port, lambda: {d["id"]: d["key"] for d in list(devices)},
                                        run, ask, pc_name(), st["nonces"])
        except (ValueError, OSError) as e:
            if auto:
                return v["state"].set(f"Not started by itself on port {v['port'].get()}: {e}")
            return messagebox.showerror("Phone remote", f"Couldn't start on port {v['port'].get()}:\n{e}", parent=page)
        rc.update(on=True, port=st["server"].port)
        on_b.config(text="Turn off")
        v["state"].set(f"On - listening on {', '.join(st['server'].hosts)} (port {st['server'].port}). Windows may "
                       "ask once: allow private networks.")
        addresses()
        look()
        return None

    def pair():
        if not st["server"]:
            toggle()
            if not st["server"]:
                return
        code = st["server"].open_pairing()
        st["code"], st["get"] = (code, time.time() + st["server"].CODE_SECS), False
        show_qr()
        say("Scan the code with the phone (it works once, for 5 minutes).")

    def get_app():
        if not st["server"]:
            toggle()
            if not st["server"]:
                return
        a = remote_apk()
        if not a:
            return say("The Android app isn't built on this PC: run build-apk.ps1 (see README), then press this again.")
        clear_code()
        st["get"] = True
        show_qr()
        c = a["cert"]
        say(f"Scan it with the Android phone's camera: it downloads CM Remote {a['name']} from this PC. Its first "
            "screen shows its signing key: it must read " + (" ".join(c[i:i + 4] for i in range(0, 16, 4)) if c else
                                                              "(unknown - rebuild it with build-apk.ps1)") + ".")

    def show_qr(*_):
        url, c = st["urls"].get(v["addr"].get()), st["code"]
        if not url or not (c or st["get"]):
            qr.configure(image="")
            st["img"] = None
            return v["code"].set("")
        m = qr_matrix(f"{url}#pair={c[0]}" if c else f"{url}app.apk")
        st["img"] = tk.PhotoImage(master=page, data=base64.b64encode(qr_png(m, max(2, px(200) // (len(m) + 8)))))
        qr.configure(image=st["img"])
        v["code"].set(f"{c[0][:4]} {c[0][4:]}" if c else f"{url}app.apk")

    def clear_code():
        st["code"], st["get"] = None, False
        if st["server"]:
            st["server"].close_pairing()
        show_qr()

    def ago(t):
        if not t:
            return "never"
        s = time.time() - t
        return "now" if s < 15 else f"{int(s // 60)} min ago" if s < 3600 else time.strftime("%d %b %H:%M",
                                                                                              time.localtime(t))

    def show_devices():
        sel = tree.selection()
        tree.delete(*tree.get_children())
        pc = remote_versions()
        for d in devices:
            tree.insert("", "end", iid=d["id"], values=(d["name"], time.strftime("%d %b", time.localtime(d["since"])),
                                                       ago(d["seen"]), remote_app_label(d.get("app"), pc)))
        if sel and tree.exists(sel[0]):
            tree.selection_set(sel[0])

    def remove():
        d = by_id((tree.selection() or [""])[0])
        if not d:
            return say("Pick a phone in the list first.")
        if not messagebox.askyesno("Remove phone", f"Remove '{d['name']}'? It stops working at once (pair it again "
                                   "to use it).", parent=page):
            return
        devices.remove(d)
        save()
        show_devices()
        say(f"{d['name']} was removed - it can't control this PC any more.")

    def look():
        def done(r):
            st["ts"] = r if isinstance(r, dict) else {}
            ts = st["ts"]
            srv = st["server"]
            v["ts"].set(f"This PC on Tailscale: {ts.get('ip', '?')}" + (f"  ({ts['name']})" if ts.get("name") else "")
                        + (" - turn the remote off and on to use it there" if srv and ts.get("ip") not in srv.hosts
                           else "") if ts else "Tailscale wasn't found on this PC (once it's installed and signed in, its "
                                   "address shows here; turn the remote off and on to listen on it).")
            addresses()
        ui_background(page, tailscale_info, done)

    def allow_vts():
        try:
            port = int(v["vts_port"].get())
        except ValueError:
            return say("VTube Studio's API port is a number (8001 unless changed in VTube Studio).")
        v["vts"].set("Asking VTube Studio - click Allow there (up to a minute)...")
        allow_b.state(["disabled"])

        def done(r):
            allow_b.state(["!disabled"])
            if isinstance(r, Exception):
                return v["vts"].set(f"Not allowed: {r}")
            st.update(vts_tok=r, vts=(0.0, {}), vts_port=port)
            v["vts"].set("Allowed - VTube Studio answers phones.")
            save()
        ui_background(page, lambda: vts_api(port, None, timeout=60)[0], done)

    def on_vts_port(*_):
        try:
            st["vts_port"] = int(v["vts_port"].get())
            st["vts"] = (0.0, {})
        except ValueError:
            pass
    v["vts_port"].trace_add("write", on_vts_port)
    v["addr"].trace_add("write", show_qr)

    def tick():
        # first: a question shown below still lets other phones' work through; fast only while phones can call
        page.after(50 if st["server"] or st["out"] is not None else 500, tick)
        st["n"] += 1
        try:
            while True:
                fn, box_, ev = calls.get_nowait()
                if box_.get("late"):
                    continue
                try:
                    box_["r"] = fn()
                except Exception as e:
                    box_["e"] = e
                ev.set()
        except queue.Empty:
            pass
        with lock:
            if st["out"] is not None and here.playing():
                st["idle"] = time.time()
            elif st["out"] is not None and time.time() - st["idle"] > 3:
                here.set_sink("out", None)
                st["out"].close()
                st["out"] = None
        if st["code"] and time.time() > st["code"][1]:
            clear_code()
            say("The pairing code ran out - press Pair a phone for a new one.")
        if st["n"] % 100 == 0 and page.winfo_ismapped():
            show_devices()  # last seen

    def sealed(d):
        try:
            return dict(d, key=secret_keep(d["key"]))
        except OSError:  # Windows couldn't seal it: not kept (that phone pairs again after a restart)
            return dict(d, key="")

    def save():
        try:
            rc["port"] = int(v["port"].get())
        except ValueError:
            pass
        try:
            vt = secret_keep(st["vts_tok"]) if st["vts_tok"] else ""
        except OSError:
            vt = ""
        rc.update(devices=[sealed(d) for d in devices], deck=v["deck"].get(), vts_port=st["vts_port"], vts_token=vt,
                  on=bool(st["server"]))
        try:
            settings_put(remote=rc)
        except OSError:
            say("Couldn't write the settings file - the phones are kept when the app closes.")

    def stop():
        save()
        if st["server"]:
            st["server"].stop()
            st["server"] = None
        here.close()
        if st["out"] is not None:
            st["out"].close()
            st["out"] = None
    show_devices()
    addresses()
    tick()
    if unread:
        say(f"{unread} paired phone(s) can't be read on this PC (another Windows user?) - pair them again.")
    if rc.get("on"):  # on when the app closed: on again
        page.after(1600, lambda: toggle(auto=True))
    return {"stop": stop, "save": save, "toggle": toggle, "pair": pair, "remove": remove, "vars": v, "state": st,
            "get_app": get_app,
            "devices": devices, "tree": tree, "look": look, "allow_vts": allow_vts, "deck": deck_list,
            "choices": choices, "qr": qr,
            "status": lambda: status.cget("text")}
