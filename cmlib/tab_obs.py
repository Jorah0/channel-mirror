"""The OBS tab."""
from pathlib import Path
from .core import secret_keep, secret_read, settings_put
from .mirror import clean_name
from .link import link_public_network
from .peers import LINK_AUDIO, PEER_FILES, peer_check_files, peer_obs, peer_proposal
from .obs import (
    OBS_FEED_PORT,
    OBS_HOST,
    OBS_MEDIA_KINDS,
    OBS_PORT,
    ObsClient,
    ObsRate,
    obs_check,
    obs_here,
    obs_put_files,
    obs_serve,
)
from .music import MusicServer, SoundFeed
from .ui import Tip, ui_background, ui_empty
from .ui_link import ui_linked_bar

OBS_NEW = "(a new source in the scene)"


def obs_tab(page, cfg, hub, music, sounds):
    """The OBS tab: OBS on this PC through its websocket server (or a linked computer's OBS, when that PC allows this
    one) - scenes, the sources in the scene (show / hide), the audio mixer (mute, volume), media sources (play, pause,
    restart, stop), streaming / recording / virtual camera; the feeds Channel Mirror plays (the Music player's stream
    and the soundboard feed: sounds played here mixed into one endless stream) with links and Add to OBS; files to OBS.
    music = the Music player tab's handles; sounds() = the soundboard's files (what the feed may play, by name).
    Returns {"remote": f(info) (a linked computer's command, from the link server's thread), "receive", "stop", ...}."""
    import queue
    import re
    import secrets
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    oc = cfg.setdefault("obs", {})
    if not re.fullmatch(r"[0-9a-f]{32}", str(oc.get("feed_token", ""))):
        oc["feed_token"] = secrets.token_hex(16)  # kept: the feed's link in OBS keeps working after a restart
    events = queue.Queue()  # from the OBS connection's and the link server's threads
    import threading
    import time
    feed, rate, remote_lock, cache = SoundFeed(), ObsRate(), threading.Lock(), {}
    st = {"client": None, "box": None, "peer": None, "state": {}, "srv": None, "asking": False, "again": False,
          "n": 0}
    pw = secret_read(oc.get("password"))  # sealed for this Windows user; None: it can't be read here (typed again)

    def kept(text):
        if not text and pw is None:  # the saved one couldn't be read here and nothing new was typed: left as it was
            return oc.get("password", "")
        try:
            return secret_keep(text)
        except OSError:  # Windows couldn't seal it: not kept (typed again next time)
            return ""
    if oc.get("password") and not str(oc["password"]).startswith("dpapi:"):  # plain, from an older version: sealed now
        oc["password"] = kept(pw)
        try:
            settings_put(obs=oc)
        except OSError:
            pass
    v = {"port": tk.StringVar(value=str(oc.get("port", OBS_PORT))), "password": tk.StringVar(value=pw or ""),
         "scene_to": tk.StringVar(), "sound": tk.StringVar(), "into": tk.StringVar(value=OBS_NEW),
         "media": tk.StringVar(), "vol": tk.DoubleVar(value=100), "feed_port": tk.StringVar(
             value=str(oc.get("feed_port", OBS_FEED_PORT))), "feed": tk.StringVar(), "conn": tk.StringVar(
             value="Not connected - press Connect." if pw is not None else
             "Not connected - the saved OBS password can't be read on this PC: type it again.")}
    status = ttk.Label(page, style="Status.TLabel", anchor="w", wraplength=1100, justify="left")
    status.pack(side="bottom", fill="x", padx=12, pady=(0, 6))
    body = ttk.Frame(page, padding=(12, 6, 12, 0))
    body.pack(fill="both", expand=True)
    cols = [ttk.Frame(body) for _ in range(3)]
    for i, c in enumerate(cols):
        c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
        body.columnconfigure(i, weight=1, uniform="obs")
    body.rowconfigure(0, weight=1)

    def say(text):
        status.config(text=text)

    def box(col, text, **k):
        f = ttk.LabelFrame(col, text=text)
        f.pack(fill="both" if k.get("grow") else "x", expand=bool(k.get("grow")), pady=(0, 8))
        return f

    def row(parent, **k):
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=k.get("pady", (4, 0)))
        return r

    # connection
    cf = box(cols[0], "OBS connection")
    who = ttk.Label(cf, text=" Controlling: OBS on this PC ", style="Local.TLabel", anchor="w")
    who.pack(fill="x")
    r = row(cf)
    ttk.Label(r, text="Port").pack(side="left")
    ttk.Spinbox(r, textvariable=v["port"], from_=1, to=65535, width=6).pack(side="left", padx=(4, 10))
    ttk.Label(r, text="Password").pack(side="left")
    ttk.Entry(r, textvariable=v["password"], show="*", width=14).pack(side="left", padx=4, fill="x", expand=True)
    r = row(cf)
    conn_b = ttk.Button(r, text="Connect", style="Accent.TButton", command=lambda: connect())
    conn_b.pack(side="left")
    here_b = ttk.Button(r, text="This PC's OBS", style="Tool.TButton", command=lambda: control(None))
    here_b.pack(side="left", padx=6)
    Tip(here_b, "Control OBS on this PC again (after controlling a linked computer's)")
    ttk.Label(cf, textvariable=v["conn"], style="Hint.TLabel", wraplength=330, justify="left").pack(anchor="w",
                                                                                                    pady=(4, 0))
    ttk.Label(cf, text="The password: in OBS, Tools > WebSocket Server Settings (tick Enable, then Show Connect "
                       "Info).", style="Hint.TLabel", wraplength=330, justify="left").pack(anchor="w", pady=(2, 0))
    scf = box(cols[0], "Scenes  (click one to put it on air)")
    scenes = ttk.Frame(scf)
    scenes.pack(fill="x")
    srf = box(cols[0], "Sources in the scene", grow=True)
    r = ttk.Frame(srf)
    r.pack(side="bottom", fill="x", pady=(4, 0))
    ttk.Button(r, text="Show / hide", style="Tool.TButton", command=lambda: toggle_item()).pack(side="left")
    srcs = ttk.Treeview(srf, columns=("src", "on"), show="headings", height=4, selectmode="browse")
    ui_empty(srcs, "Connect to OBS to see the scene's sources.")
    for c, h, w in (("src", "Source", 180), ("on", "Shown", 70)):
        srcs.heading(c, text=h)
        srcs.column(c, width=w, stretch=c == "src")
    srcs.pack(fill="both", expand=True)
    srcs.bind("<Double-1>", lambda e: toggle_item())

    # live: stream / record / virtual camera
    lf = box(cols[1], "Live")
    outs = {}
    for i, (k, text) in enumerate((("stream", "streaming"), ("record", "recording"), ("vcam", "virtual camera"))):
        lab = ttk.Label(lf, text="-", style="Hint.TLabel", width=8)
        lab.grid(row=i, column=0, sticky="w", pady=2)
        b = ttk.Button(lf, text=f"Start {text}", style="Tool.TButton", command=lambda k=k: output(k))
        b.grid(row=i, column=1, sticky="ew", padx=(6, 0), pady=2)
        outs[k] = (lab, b, text)
    lf.columnconfigure(1, weight=1)
    mf = box(cols[1], "Media sources")
    r = row(mf, pady=0)
    media_cb = ttk.Combobox(r, textvariable=v["media"], state="readonly", width=18)
    media_cb.pack(side="left", fill="x", expand=True)
    media_l = ttk.Label(r, style="Hint.TLabel", width=10)
    media_l.pack(side="left", padx=(6, 0))
    r = row(mf)
    for a in ("play", "pause", "restart", "stop"):
        ttk.Button(r, text=a.capitalize(), style="Tool.TButton", command=lambda a=a: media(a)).pack(
            side="left", padx=(0, 4))
    mxf = box(cols[1], "Audio mixer", grow=True)
    r = ttk.Frame(mxf)
    r.pack(side="bottom", fill="x", pady=(4, 0))
    ttk.Button(r, text="Mute / unmute", style="Tool.TButton", command=lambda: mute()).pack(side="left")
    vol_s = ttk.Scale(r, from_=0, to=100, variable=v["vol"], orient="horizontal")
    vol_s.pack(side="left", fill="x", expand=True, padx=(8, 4))
    vol_l = ttk.Label(r, text="100%", width=5)
    vol_l.pack(side="left")
    mix = ttk.Treeview(mxf, columns=("in", "mute", "vol"), show="headings", height=4, selectmode="browse")
    for c, h, w in (("in", "Audio", 150), ("mute", "Muted", 60), ("vol", "Volume", 60)):
        mix.heading(c, text=h)
        mix.column(c, width=w, stretch=c == "in")
    mix.pack(fill="both", expand=True)

    # feeds and files
    ff = box(cols[2], "Feeds for OBS  (what Channel Mirror plays)")
    r = row(ff, pady=0)
    ttk.Label(r, text="Music", width=11).pack(side="left")
    ttk.Entry(r, textvariable=music["vars"]["stream"], state="readonly", width=14).pack(side="left", fill="x",
                                                                                        expand=True)
    ttk.Button(r, text="Copy", style="Tool.TButton", command=lambda: copy(music["vars"]["stream"].get(), "music")
               ).pack(side="left", padx=(4, 0))
    r = row(ff)
    ttk.Label(r, text="Soundboard", width=11).pack(side="left")
    ttk.Entry(r, textvariable=v["feed"], state="readonly", width=14).pack(side="left", fill="x", expand=True)
    ttk.Button(r, text="Copy", style="Tool.TButton", command=lambda: copy(v["feed"].get(), "feed")).pack(
        side="left", padx=(4, 0))
    r = row(ff)
    feed_b = ttk.Button(r, text="Start soundboard feed", style="Tool.TButton", command=lambda: share_feed())
    feed_b.pack(side="left")
    ttk.Label(r, text="Port").pack(side="left", padx=(8, 0))
    ttk.Spinbox(r, textvariable=v["feed_port"], from_=0, to=65535, width=6).pack(side="left", padx=4)
    r = row(ff)
    ttk.Label(r, text="Scene", width=11).pack(side="left")
    scene_cb = ttk.Combobox(r, textvariable=v["scene_to"], state="readonly", width=16)
    scene_cb.pack(side="left", fill="x", expand=True)
    r = row(ff)
    ttk.Label(r, text="Add to OBS:").pack(side="left")
    for text, which in (("Music", "stream"), ("Overlay", "overlay"), ("Soundboard", "feed")):
        b = ttk.Button(r, text=text, style="Tool.TButton", command=lambda w=which: add_feed(w))
        b.pack(side="left", padx=(4, 0))
        Tip(b, {"stream": "The music stream as a Media Source in the scene above",
                "overlay": "The now-playing overlay as a Browser Source in the scene above",
                "feed": "The soundboard feed as a Media Source in the scene above"}[which])
    r = row(ff)
    ttk.Label(r, text="Sound", width=11).pack(side="left")
    sound_cb = ttk.Combobox(r, textvariable=v["sound"], state="readonly", width=12,
                            postcommand=lambda: sound_cb.config(values=sound_names()))
    sound_cb.pack(side="left", fill="x", expand=True)
    ttk.Button(r, text="Play", style="Tool.TButton", command=lambda: feed_cmd("feed_play")).pack(side="left",
                                                                                                padx=(4, 0))
    ttk.Button(r, text="Stop", style="Tool.TButton", command=lambda: feed_cmd("feed_stop")).pack(side="left",
                                                                                                padx=(4, 0))
    r = row(ff)
    pf = ttk.Button(r, text="Play a file in the feed...", style="Tool.TButton", command=lambda: play_file())
    pf.pack(side="left")
    Tip(pf, "A sound file played into this PC's soundboard feed (the sounds above are the Stream Deck soundboard "
            "tab's, on the PC whose OBS this controls)")
    fl = box(cols[2], "Files to OBS")
    r = row(fl, pady=0)
    ttk.Label(r, text="Into", width=11).pack(side="left")
    into_cb = ttk.Combobox(r, textvariable=v["into"], state="readonly", width=16)
    into_cb.pack(side="left", fill="x", expand=True)
    r = row(fl)
    ttk.Button(r, text="Send files to OBS...", style="Accent.TButton", command=lambda: send_files()).pack(side="left")
    ttk.Label(fl, text="A new source goes in the scene picked above. On a linked computer it's asked there first.",
              style="Hint.TLabel", wraplength=330, justify="left").pack(anchor="w", pady=(4, 0))

    # --- doing things: on this PC's OBS, or the linked computer's ---
    def where():
        return f"OBS on {st['peer']['name']}" if st["peer"] else "OBS on this PC"

    def run(cmd, args=None, then=None):
        target, args = st["peer"], args or {}

        def work():
            if target:
                return peer_obs(target, hub["me"](), cmd, args)
            return obs_here(st["client"], cmd, obs_check(cmd, args), feed, sounds())

        def done(r):
            if target is not st["peer"]:
                return  # switched meanwhile
            if isinstance(r, Exception):
                if cmd == "state":
                    st["asking"] = False
                    show({})
                return say(str(r) if target else f"OBS: {r}")  # a linked computer's says which one
            if then:
                then(r)
            if cmd != "state":
                refresh()
        ui_background(page, work, done)

    def refresh():
        if st["asking"]:
            st["again"] = True
            return
        if not st["peer"] and not (st["client"] and st["client"].connected):
            return show({})
        st["asking"] = True

        def got(r):
            st["asking"] = False
            show(r)
            if st["again"]:
                st["again"] = False
                refresh()
        run("state", then=got)

    def show(s):
        st["state"] = s
        cur, names = s.get("scene", ""), list(s.get("scenes") or [])
        if [b.cget("text") for b in scenes.winfo_children()] != names or st.get("cur") != cur:
            for b in scenes.winfo_children():
                b.destroy()
            for i, n in enumerate(names):
                ttk.Button(scenes, text=n, style="Accent.TButton" if n == cur else "TButton",
                           command=lambda n=n: run("scene", {"scene": n})).grid(row=i // 3, column=i % 3,
                                                                                 sticky="ew", padx=(0, 4), pady=2)
            for i in range(3):
                scenes.columnconfigure(i, weight=1, uniform="sc")
            st["cur"] = cur
        srf.config(text=f"Sources in {cur}" if cur else "Sources in the scene")
        keep = srcs.selection()
        srcs.delete(*srcs.get_children())
        for it in s.get("items") or []:
            srcs.insert("", "end", iid=str(it["id"]), values=(it["name"], "shown" if it["on"] else "hidden"))
        if keep and srcs.exists(keep[0]):
            srcs.selection_set(keep[0])
        keep = mix.selection()
        mix.delete(*mix.get_children())
        for it in s.get("inputs") or []:
            mix.insert("", "end", iid=it["name"], values=(it["name"], "muted" if it["muted"] else "", f"{it['volume']}%"))
        if keep and mix.exists(keep[0]):
            mix.selection_set(keep[0])
        md = {m["name"]: m for m in s.get("media") or []}
        playable = [n for n, m in md.items() if m["kind"] in OBS_MEDIA_KINDS]
        media_cb.config(values=playable)
        if v["media"].get() not in playable:
            v["media"].set(playable[0] if playable else "")
        media_l.config(text=(md.get(v["media"].get()) or {}).get("state", ""))
        scene_cb.config(values=names)
        if v["scene_to"].get() not in names:
            v["scene_to"].set(cur)
        into_cb.config(values=[OBS_NEW] + list(md))
        if v["into"].get() not in [OBS_NEW] + list(md):
            v["into"].set(OBS_NEW)
        for k, (lab, b, text) in outs.items():
            on = bool(s.get(k))
            lab.config(text={"stream": "LIVE", "record": "REC", "vcam": "ON"}[k] if on else ("off" if s else "-"),
                       style="Bad.TLabel" if on else "Hint.TLabel")
            b.config(text=f"{'Stop' if on else 'Start'} {text}")

    def control(peer):
        """Which OBS the tab works on: this PC's (None) or a linked computer's (it must allow this PC there)."""
        st["peer"], st["asking"] = peer, False
        who.config(text=f" Controlling: {where()} ", style="Remote.TLabel" if peer else "Local.TLabel")
        show({})
        if peer:
            say(f"Asking {peer['name']} for its OBS...")
        refresh()

    def connect():
        if st["client"]:
            st["client"].close()
            st["client"], oc["connect"] = None, False
            conn_b.config(text="Connect")
            v["conn"].set("Disconnected.")
            return None if st["peer"] else show({})
        try:
            port = int(v["port"].get())
            if not 0 < port < 65536:
                raise ValueError
        except ValueError:
            return say("The port is a number from 1 to 65535 (OBS's default is 4455).")
        holder = []
        st["client"] = ObsClient(OBS_HOST, port, v["password"].get(),
                                 on_event=lambda t, d: events.put(("event", holder, t)),
                                 on_status=lambda on, text: events.put(("status", holder, on, text)))
        holder.append(st["client"])
        st["box"] = holder
        oc.update(port=port, password=kept(v["password"].get()), connect=True)
        conn_b.config(text="Disconnect")
        v["conn"].set(f"Connecting to OBS on port {port}...")

    def on_status(holder, on, text):
        c = holder[0] if holder else None
        if c is None or c is not st["client"]:
            return  # an old connection's last word
        v["conn"].set(text)
        if on:
            if not st["peer"]:
                refresh()
        elif c.error and not c.error.endswith("trying again..."):  # wrong password: it stopped trying
            st["client"], oc["connect"] = None, False
            conn_b.config(text="Connect")
            say(text)
        if not on and not st["peer"]:
            show({})

    def need(x, what):
        if not x:
            say(what)
        return x

    def toggle_item():
        sel, s = srcs.selection(), st["state"]
        it = next((i for i in s.get("items") or [] if str(i["id"]) == (sel[0] if sel else "")), None)
        if need(it, "Click a source in the list first."):
            run("item", {"scene": s["scene"], "id": it["id"], "on": not it["on"]})

    def picked_input():
        sel = mix.selection()
        return next((i for i in st["state"].get("inputs") or [] if sel and i["name"] == sel[0]), None)

    def mute():
        it = picked_input()
        if need(it, "Click an audio source in the mixer first."):
            run("mute", {"input": it["name"], "muted": not it["muted"]})

    def volume(e=None):
        it = picked_input()
        if need(it, "Click an audio source in the mixer first."):
            run("volume", {"input": it["name"], "percent": int(round(v["vol"].get()))})

    def on_mix(e=None):
        it = picked_input()
        if it:
            v["vol"].set(it["volume"])
    mix.bind("<<TreeviewSelect>>", on_mix)
    vol_s.bind("<ButtonRelease-1>", volume)  # set when let go: not a command for every pixel dragged
    v["vol"].trace_add("write", lambda *_: vol_l.config(text=f"{int(round(v['vol'].get()))}%"))

    def media(action):
        if need(v["media"].get(), "No media source in OBS to control."):
            run("media", {"input": v["media"].get(), "action": action})
    media_cb.bind("<<ComboboxSelected>>", lambda e: show(st["state"]))

    def output(k):
        run("output", {"output": k, "action": "stop" if st["state"].get(k) else "start"})

    def copy(text, what):
        if not text:
            return say("Start sharing in the Music player tab first - then its link shows here." if what == "music"
                       else "Start the soundboard feed first - then its link shows here.")
        page.clipboard_clear()
        page.clipboard_append(text)
        say("Copied.")

    def feed_link():
        srv = st["srv"]
        v["feed"].set(f"http://{srv.host}:{srv.port}/music/{oc['feed_token']}/stream.mp3" if srv else "")

    def share_feed(auto=False):
        if st["srv"]:
            feed.set_sink("obs", None)
            st["srv"].stop()
            st["srv"], oc["feed_share"] = None, False
            feed_b.config(text="Start soundboard feed")
            feed_link()
            return say("The soundboard feed stopped - OBS gets nothing from it now.")
        if link_public_network():
            if auto:
                return say("The soundboard feed didn't start by itself: Windows has this network marked Public.")
            if not messagebox.askyesno("Soundboard feed", "Windows has this network marked Public (like cafe or "
                                       "hotel Wi-Fi). Other people on it could listen with the link.\n\nOnly share "
                                       "on your own home network. Start anyway?", parent=page):
                return None
        try:
            port = int(v["feed_port"].get())
            if not 0 <= port <= 65535:
                raise ValueError("a port is a number up to 65535")
            st["srv"] = MusicServer(port, oc["feed_token"], lambda: {
                "title": ", ".join(feed.playing())[:200], "playlist": "Soundboard", "playing": bool(feed.playing())})
        except (ValueError, OSError) as e:
            return say(f"The soundboard feed couldn't start on port {v['feed_port'].get()}: {e}")
        feed.set_sink("obs", st["srv"].feed)
        oc.update(feed_share=True, feed_port=port)
        feed_b.config(text="Stop soundboard feed")
        feed_link()
        say("Soundboard feed on: sounds played here go into it. Add it to OBS (Add to OBS: Soundboard) or paste its "
            "link into a Media Source (untick Local File).")

    def add_feed(which):
        url = v["feed"].get() if which == "feed" else music["vars"][which].get()
        if not url:
            return copy("", "music" if which != "feed" else "feed")
        if need(v["scene_to"].get(), "Pick the scene it goes in first (connect to OBS)."):
            name = {"stream": "Channel Mirror music", "overlay": "Channel Mirror now playing",
                    "feed": "Channel Mirror soundboard"}[which]
            run("add_feed", {"scene": v["scene_to"].get(), "name": name, "url": url},
                then=lambda r: say(f"Added '{name}' to the scene {v['scene_to'].get()} ({where()})."))

    def sound_names():
        return list(st["state"].get("sounds") or []) if st["peer"] else sorted({Path(x).name for x in sounds()})

    def feed_cmd(cmd):
        if cmd == "feed_play" and not need(v["sound"].get(), "Pick a sound first (the Stream Deck soundboard tab's)."):
            return
        run(cmd, {"sound": v["sound"].get()} if cmd == "feed_play" else {}, then=lambda r: say(
            f"Playing {v['sound'].get()} in the soundboard feed ({where()})." if cmd == "feed_play"
            else f"Sounds stopped ({where()})."))

    def play_file():
        files = filedialog.askopenfilenames(parent=page, title="Sounds to play in the feed", filetypes=[
            ("Sounds", " ".join(f"*{e}" for e in LINK_AUDIO)), ("All files", "*.*")])
        for f in files:
            feed.play(f)
        if files:
            say(f"Playing {len(files)} sound(s) in this PC's soundboard feed" + (
                "." if st["srv"] else " - start the feed so OBS hears it."))

    def send_files():
        into, scene = v["into"].get(), v["scene_to"].get()
        if into in ("", OBS_NEW) and not need(scene, "Pick the scene for the new source first (connect to OBS)."):
            return
        pat = " ".join(f"*{e}" for e in PEER_FILES["obs"])
        files = [Path(f) for f in filedialog.askopenfilenames(parent=page, title=f"Files for {where()}", filetypes=[
            ("Sounds, videos and pictures", pat), ("All files", "*.*")])]
        if not files:
            return None
        spec = {"scene": scene, "name": clean_name(files[0].stem, 80) or "Channel Mirror"} if into in ("", OBS_NEW) \
            else {"input": into}
        try:
            spec = peer_proposal("obs", spec, len(files))
            peer_check_files("obs", spec, files)  # sounds, videos and pictures, really what they say
        except (ValueError, OSError) as e:
            return say(f"Can't send that: {e}")
        if st["peer"]:
            hub["send"](st["peer"], "obs", files, spec)
            return say(f"Sent {len(files)} file(s) to {st['peer']['name']} - it waits there to be accepted.")
        ui_background(page, lambda: obs_put_files(need_client(), files, spec),
                      lambda r: say(f"OBS: {r}") if isinstance(r, Exception) else (say(f"Into OBS: {r}."), refresh()))

    def need_client():
        c = st["client"]
        if not c or not c.connected:
            raise ValueError("OBS isn't connected on this PC (OBS tab: Connect)")
        return c

    def receive(files, spec):
        """Files a linked computer sent for OBS, accepted here: into this PC's OBS (ValueError when it can't)."""
        try:
            done = obs_put_files(need_client(), files, spec)
        except Exception as e:
            raise ValueError(str(e)) from None
        say(f"Into OBS: {done}.")
        refresh()

    def here(c, a):  # one at a time, the state at most once a second: OBS is never flooded from the link / phones
        if not remote_lock.acquire(timeout=10):
            raise ValueError("OBS is busy here - try again")
        try:
            if c == "state" and time.monotonic() - cache.get("t", -9.0) < 1.0:
                return cache["s"]
            cache.clear()
            out = obs_here(st["client"], c, a, feed, sounds())
            if c == "state":
                cache.update(t=time.monotonic(), s=out)
            return out
        finally:
            remote_lock.release()

    def phone(cmd, args):
        """This PC's OBS for a paired phone (from the phone remote's server thread): a command of the fixed list."""
        if st["client"] is None or not st["client"].connected:
            raise ValueError("OBS isn't connected on the PC - connect it on Channel Mirror's OBS page")
        return here(cmd, obs_check(cmd, args))

    def remote(info):
        """A linked computer's OBS command (from the link server's thread): only if it may, see obs_serve."""
        p = next((x for x in hub["peers"]() if x["id"] == info.get("peer")), None)
        r = obs_serve(p, info["cmd"], info["args"], here, rate)
        if info["cmd"] != "state" or not r.get("ok"):
            events.put(("remote", p, info["cmd"], r.get("error")))
        return r

    def tick():
        try:
            while True:
                e = events.get_nowait()
                if e[0] == "status":
                    on_status(*e[1:])
                elif e[0] == "event" and e[1] and e[1][0] is st["client"] and not st["peer"]:
                    st["n"] = max(st["n"], 8)  # something changed in OBS: shown in a moment
                elif e[0] == "remote" and e[1]:
                    hub["act"](e[1], f"OBS: {e[2]}" + (f" - refused: {e[3]}" if e[3] else ""))
        except queue.Empty:
            pass
        st["n"] += 1
        if st["n"] >= 10:  # every 2 s (sooner after an OBS event), while the tab is on screen
            st["n"] = 0
            if page.winfo_ismapped():
                refresh()
        page.after(200, tick)

    def save():
        try:
            oc["port"] = int(v["port"].get())
        except ValueError:
            pass
        try:
            oc["feed_port"] = int(v["feed_port"].get())
        except ValueError:
            pass
        oc.update(password=kept(v["password"].get()), connect=bool(st["client"]), feed_share=bool(st["srv"]))

    def stop():
        save()
        if st["client"]:
            st["client"].close()
        if st["srv"]:
            st["srv"].stop()
        feed.close()
    bar = ui_linked_bar(page, hub, extra=(("Control its OBS", control),))
    tick()
    if oc.get("connect"):  # connected when the app closed: again by itself
        page.after(1500, connect)
    if oc.get("feed_share"):
        page.after(1300, lambda: share_feed(auto=True))
    return {"remote": remote, "phone": phone, "receive": receive, "stop": stop, "save": save, "vars": v, "state": st, "feed": feed,
            "control": control, "bar": bar, "scenes": scenes, "sources": srcs, "mixer": mix, "volume": vol_s,
            "outputs": outs, "status": lambda: status.cget("text"), "refresh": refresh}
