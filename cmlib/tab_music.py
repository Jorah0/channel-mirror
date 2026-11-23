"""The music tab."""
from pathlib import Path
from .mirror import clean_name, media_files
from .link import LINK_INBOX, link_public_network, link_safe_name
from .peers import peer_name
from .music import (
    MUSIC_DEFAULT_OUT,
    MUSIC_EXT,
    MUSIC_NOW,
    MUSIC_PORT,
    MUSIC_REPEAT,
    MusicEngine,
    MusicOut,
    MusicServer,
    m3u_read,
    m3u_write,
    music_add,
    music_devices,
    music_length,
    music_local,
    music_move,
    music_next,
    music_now_file,
    music_order,
    music_title,
)
from .ui import Tip, UI, ui_background, ui_empty, ui_keys, ui_volume


def music_tab(page, cfg):
    """The Music player tab: playlists (new / rename / duplicate / delete; songs from files, folders, .m3u / .m3u8
    files or a linked computer; reorder, shuffle, repeat), a player that can also be heard here on a chosen output,
    and two links for OBS on this or any PC on the home network: one endless music stream (a Media Source) and a
    now-playing overlay (a Browser Source). Nothing here changes OBS itself.
    Returns {"add", "receive", "songs", "files", "name", "stop", "save", ...} for the window."""
    import copy
    import queue
    import re
    import secrets
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    mc = cfg.setdefault("music", {})
    if not isinstance(mc.get("playlists"), list) or not mc["playlists"]:
        mc["playlists"] = [{"name": "Playlist 1", "songs": []}]
    lists = mc["playlists"]
    for p in lists:  # a settings file edited elsewhere: only files on this PC's own drives
        p["songs"] = [x for x in p.get("songs") or [] if isinstance(x, dict) and music_local(x.get("path", ""))]
    if not re.fullmatch(r"[0-9a-f]{32}", str(mc.get("token", ""))):
        mc["token"] = secrets.token_hex(16)  # kept: OBS keeps working after a restart
    events = queue.Queue()  # songs that ended, from the engine's thread
    eng = MusicEngine(on_end=lambda: events.put("end"))
    st = {"server": None, "out": None, "out_dev": None, "pl": None, "path": None, "order": [], "len": 0.0,
          "drag": False}
    now = {"title": "", "playlist": "", "playing": False}  # what the overlay shows
    devices = [MUSIC_DEFAULT_OUT] + music_devices()
    rep_label = {k: lab for lab, k in MUSIC_REPEAT.items()}
    v = {"vol": tk.IntVar(value=int(mc.get("volume", 80))), "shuffle": tk.BooleanVar(value=bool(mc.get("shuffle"))),
         "repeat": tk.StringVar(value=rep_label.get(mc.get("repeat"), "Repeat all")),
         "hear": tk.BooleanVar(value=mc.get("hear", True)),
         "device": tk.StringVar(value=mc.get("device") if mc.get("device") in devices else MUSIC_DEFAULT_OUT),
         "port": tk.StringVar(value=str(mc.get("port", MUSIC_PORT))), "stream": tk.StringVar(),
         "overlay": tk.StringVar(), "pos": tk.DoubleVar(), "time": tk.StringVar(value="0:00 / 0:00"),
         "now": tk.StringVar(value="Nothing playing")}
    eng.volume = v["vol"].get()
    status = ttk.Label(page, style="Status.TLabel", anchor="w", wraplength=1100, justify="left")
    status.pack(side="bottom", fill="x", padx=12, pady=(0, 6))
    body = ttk.Frame(page, padding=(12, 6, 12, 0))
    body.pack(fill="both", expand=True)

    # OBS: the links (packed first from the bottom, so they always keep their room)
    of = ttk.LabelFrame(body, text="Play it in OBS  (this PC or any PC on your home network)")
    of.pack(side="bottom", fill="x", pady=(8, 0))
    o1 = ttk.Frame(of)
    o1.pack(fill="x")
    share_b = ttk.Button(o1, text="Start sharing", style="Accent.TButton", command=lambda: share())
    share_b.pack(side="left")
    ttk.Label(o1, text="Port").pack(side="left", padx=(12, 0))
    ttk.Spinbox(o1, textvariable=v["port"], from_=1024, to=65535, width=6).pack(side="left", padx=4)
    nl =ttk.Button(o1, text="New link", style="Tool.TButton", command=lambda: new_link())
    nl.pack(side="left", padx=4)
    Tip(nl, "New links: the old ones stop working (paste the new ones into OBS again)")
    share_l = ttk.Label(o1, style="Hint.TLabel", text="Not shared - press Start sharing for the OBS links.")
    share_l.pack(side="left", padx=8, fill="x", expand=True)
    o2 = ttk.Frame(of)
    o2.pack(fill="x", pady=(6, 0))
    for key, text in (("stream", "Music stream"), ("overlay", "Now-playing overlay")):
        ttk.Label(o2, text=text).pack(side="left", padx=(0 if key == "stream" else 12, 4))
        ttk.Entry(o2, textvariable=v[key], width=30, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(o2, text="Copy", style="Tool.TButton", command=lambda k=key: copy_text(v[k].get())).pack(
            side="left", padx=(4, 0))
    ttk.Label(of, text="In OBS: Media Source -> untick Local File -> paste the stream link.  Browser Source -> paste "
                       f"the overlay link (800 x 160).  OBS on this PC can also show the song with a Text source "
                       f"reading from the file {MUSIC_NOW}.", style="Hint.TLabel", wraplength=1050,
              justify="left").pack(anchor="w", pady=(4, 0))

    # the player
    pf = ttk.LabelFrame(body, text="Player")
    pf.pack(side="bottom", fill="x", pady=(8, 0))
    p1 = ttk.Frame(pf)
    p1.pack(fill="x")
    for text, fn in (("Previous", lambda: skip(-1)), ("Play", lambda: play()), ("Pause", lambda: pause()),
                     ("Stop", lambda: stop()), ("Next", lambda: skip(1))):
        ttk.Button(p1, text=text, style="Accent.TButton" if text == "Play" else "TButton", command=fn).pack(
            side="left", padx=(0, 6))
    ttk.Label(p1, textvariable=v["now"], style="Name.TLabel").pack(side="left", padx=8, fill="x", expand=True)
    p2 = ttk.Frame(pf)
    p2.pack(fill="x", pady=(6, 0))
    bar = ttk.Scale(p2, from_=0, to=1, variable=v["pos"], orient="horizontal")
    bar.pack(side="left", fill="x", expand=True)
    ttk.Label(p2, textvariable=v["time"], width=12, anchor="e").pack(side="left", padx=(8, 0))
    p3 = ttk.Frame(pf)
    p3.pack(fill="x", pady=(6, 0))
    ttk.Label(p3, text="Volume").pack(side="left")
    ui_volume(p3, v["vol"], 130).pack(side="left", padx=(6, 12))
    ttk.Checkbutton(p3, text="Shuffle", variable=v["shuffle"]).pack(side="left")
    ttk.Combobox(p3, textvariable=v["repeat"], values=list(MUSIC_REPEAT), state="readonly", width=11).pack(
        side="left", padx=(12, 0))
    ttk.Checkbutton(p3, text="Hear it here on", variable=v["hear"]).pack(side="left", padx=(16, 4))
    ttk.Combobox(p3, textvariable=v["device"], values=devices, state="readonly", width=30).pack(side="left")

    # playlists and their songs
    top = ttk.Frame(body)
    top.pack(fill="both", expand=True)
    lf = ttk.LabelFrame(top, text="Playlists")
    lf.pack(side="left", fill="y", padx=(0, 10))
    ptv = ttk.Treeview(lf, show="tree", selectmode="browse", height=3)
    ptv.column("#0", width=200)
    ptv.pack(fill="both", expand=True)
    pb = ttk.Frame(lf)
    pb.pack(fill="x", pady=(6, 0))
    sf = ttk.LabelFrame(top, text="Songs")
    sf.pack(side="left", fill="both", expand=True)
    side = ttk.Frame(sf)
    side.pack(side="right", fill="y", padx=(8, 0))
    box = ttk.Frame(sf)
    box.pack(side="left", fill="both", expand=True)
    stv = ttk.Treeview(box, columns=("n", "song", "folder"), show="headings", selectmode="extended", height=3)
    ui_empty(stv, "This playlist is empty. Add files or a folder of songs.")
    for c, h, w in (("n", "#", 40), ("song", "Song", 320), ("folder", "Folder", 220)):
        stv.heading(c, text=h)
        stv.column(c, width=w, stretch=c != "n", anchor="e" if c == "n" else "w")
    ys = ttk.Scrollbar(box, command=stv.yview)
    stv.config(yscrollcommand=ys.set)
    ys.pack(side="right", fill="y")
    stv.pack(fill="both", expand=True)
    for t in (stv, ptv):
        t.tag_configure("now", foreground=UI["good"])
    stv.tag_configure("missing", foreground=UI["bad"])  # red, as everywhere: its file is missing

    def say(text):
        status.config(text=text)

    def copy_text(text):
        if text:
            page.clipboard_clear()
            page.clipboard_append(text)
            say("Copied.")
        else:
            say("Start sharing first - then the links show here.")

    def cur():
        mc["current"] = min(max(int(mc.get("current", 0)), 0), len(lists) - 1)
        return lists[mc["current"]]

    def show_lists():
        ptv.delete(*ptv.get_children())
        for i, p in enumerate(lists):
            ptv.insert("", "end", iid=str(i), text=f"{p['name']}  ({len(p['songs'])})",
                       tags=("now",) if p is st["pl"] and st["path"] else ())
        ptv.selection_set(str(lists.index(cur())))
        show_songs()

    there = {}  # song path -> its file is there; looked at once, again on add / import / when the tab is shown

    def recheck(*_):
        there.clear()
        show_songs([int(i) for i in stv.selection()])

    def show_songs(sel=()):
        p = cur()
        sf.config(text=f"Songs in {p['name']}  (double-click one to play it; red = file not found)")
        stv.delete(*stv.get_children())
        for i, s in enumerate(p["songs"]):
            f = Path(s["path"])
            if s["path"] not in there:
                there[s["path"]] = f.is_file()
            tags = ("now",) if p is st["pl"] and s["path"] == st["path"] else () if there[s["path"]] else ("missing",)
            stv.insert("", "end", iid=str(i), values=(i + 1, music_title(s), f.parent.name), tags=tags)
        for i in sel:
            stv.selection_add(str(i))

    def picked(*_):
        sel = ptv.selection()
        if sel and int(sel[0]) != mc.get("current"):
            mc["current"] = int(sel[0])
            show_songs()
    ptv.bind("<<TreeviewSelect>>", picked)
    page.bind("<Map>", recheck)  # the tab shown again: files may have been moved or deleted meanwhile
    stv.bind("<FocusIn>", recheck, add="+")

    def unique(name, but=None):
        names, n, out = {p["name"] for p in lists if p is not but}, 2, name
        while out in names:
            out, n = f"{name} {n}", n + 1
        return out

    def new_list(name=None, items=()):
        if name is None:
            name = simpledialog.askstring("New playlist", "Name for the playlist:", initialvalue=unique("Playlist"),
                                          parent=page)
        name = peer_name(name or "", 60)
        if not name:
            return None
        p = {"name": unique(name), "songs": []}
        music_add(p["songs"], items)
        lists.append(p)
        mc["current"] = len(lists) - 1
        show_lists()
        return p

    def rename():
        p = cur()
        name = peer_name(simpledialog.askstring("Rename playlist", "New name:", initialvalue=p["name"],
                                                parent=page) or "", 60)
        if name:
            p["name"] = unique(name, p)
            show_lists()

    def duplicate():
        p = copy.deepcopy(cur())
        p["name"] = unique(peer_name(p["name"] + " copy", 60))
        lists.append(p)
        mc["current"] = len(lists) - 1
        show_lists()

    def delete():
        p = cur()
        if not messagebox.askyesno("Delete playlist", f"Delete the playlist '{p['name']}'? (Its song files stay "
                                   "where they are.)", parent=page):
            return
        if p is st["pl"]:
            stop()
            st["pl"] = None
        lists.remove(p)
        if not lists:
            lists.append({"name": "Playlist 1", "songs": []})
        mc["current"] = min(mc["current"], len(lists) - 1)
        show_lists()

    def import_m3u():
        done = []
        for f in filedialog.askopenfilenames(parent=page, title="Import playlists", filetypes=[
                ("Playlists", "*.m3u *.m3u8"), ("All files", "*.*")]):
            try:
                items = m3u_read(f)
            except OSError as e:
                say(f"Couldn't read {Path(f).name}: {e}")
                continue
            there.clear()
            p = new_list(Path(f).stem, items)
            for x in p["songs"]:
                x["m3u"] = True  # named by a file from anywhere: never offered to a linked computer
            done.append(f"{p['name']} ({len(p['songs'])} songs, "
                        f"{sum(not Path(s['path']).is_file() for s in p['songs'])} not found here)")
        if done:
            say("Imported: " + "; ".join(done))

    def export_m3u():
        p = cur()
        f = filedialog.asksaveasfilename(parent=page, title="Export playlist", defaultextension=".m3u8",
                                         initialfile=link_safe_name(p["name"] + ".png")[:-4] + ".m3u8",
                                         filetypes=[("Playlist (UTF-8)", "*.m3u8"), ("Playlist", "*.m3u")])
        if f:
            try:
                m3u_write(f, [(s["path"], music_title(s)) for s in p["songs"]])
                say(f"Exported {len(p['songs'])} song(s) to {f}")
            except OSError as e:
                say(f"Couldn't write {f}: {e}")

    def title_of(f):
        f = Path(f)  # fetched from a linked computer: "001 name.mp3" in Received\<when> - the title is the name
        return clean_name(f.stem[4:], 80) if (f.parent.parent == LINK_INBOX / "Received"
                                              and re.match(r"\d{3} ", f.stem)) else ""

    def add_songs(files):
        there.clear()
        p = cur()
        n = music_add(p["songs"], [(f, title_of(f)) for f in files if Path(f).suffix.lower() in MUSIC_EXT])
        changed()
        say(f"Added {n} song(s) to {p['name']}." + (f" ({len(files) - n} already in it or not a sound / video "
                                                     "file.)" if len(files) > n else ""))
        return n

    def add_files():
        pat = " ".join(f"*{e}" for e in MUSIC_EXT)
        add_songs(filedialog.askopenfilenames(parent=page, title="Add songs", filetypes=[
            ("Sound and video files", pat), ("All files", "*.*")]))

    def add_folder():
        folder = filedialog.askdirectory(parent=page, title="Add every song in a folder")
        if folder:
            add_songs(media_files([folder]))

    def selected():
        return sorted(int(i) for i in stv.selection())

    def move(step):
        p = cur()
        p["songs"][:], sel = music_move(p["songs"], selected(), step)
        changed(sel)

    def remove():
        p, sel = cur(), set(selected())
        p["songs"][:] = [s for i, s in enumerate(p["songs"]) if i not in sel]
        changed()

    def changed(sel=()):
        if cur() is st["pl"]:
            reorder()
        show_lists()
        show_songs(sel)

    def idx():
        pl = st["pl"]
        return next((i for i, s in enumerate(pl["songs"]) if s["path"] == st["path"]), None) if pl else None

    def reorder(*_):
        st["order"] = music_order(len(st["pl"]["songs"]) if st["pl"] else 0, idx(), v["shuffle"].get())

    def repeat():
        return MUSIC_REPEAT.get(v["repeat"].get(), "all")

    def fmt(secs):
        return f"{int(secs) // 60}:{int(secs) % 60:02d}"

    def sync_out():
        """Listening here: the device open while a song plays (closed when paused or stopped - an open device keeps
        Windows from sleeping)."""
        want, dev = v["hear"].get() and eng.song is not None and not eng.paused, v["device"].get()
        if st["out"] and (not want or st["out_dev"] != dev):
            eng.set_sink("here", None)
            st["out"].close()
            st["out"] = None
        if want and not st["out"]:
            try:
                st["out"], st["out_dev"] = MusicOut("" if dev == MUSIC_DEFAULT_OUT else dev), dev
                eng.set_sink("here", st["out"].write)
            except OSError as e:
                say(f"Can't play on {dev} here: {e}")

    def play_at(pl, i, tries=0):
        """Song i of playlist pl; a song whose file isn't there is skipped."""
        if pl is not st["pl"] or len(st["order"]) != len(pl["songs"]):
            st["pl"] = pl
            st["order"] = music_order(len(pl["songs"]), i, v["shuffle"].get())
        s = pl["songs"][i]
        st["path"] = s["path"]
        if not Path(s["path"]).is_file():
            say(f"Not found, skipped: {s['path']}")
            nxt = music_next(st["order"], i, repeat())
            return play_at(pl, nxt, tries + 1) if nxt is not None and tries < len(pl["songs"]) else stop()
        try:
            eng.play(s["path"])
        except OSError as e:
            say(f"Can't play {Path(s['path']).name}: {e}")
            return stop()
        title = music_title(s)
        now.update(title=title, playlist=pl["name"], playing=True)
        v["now"].set(f"{title}   -   {pl['name']}")
        music_now_file(title)
        st["len"] = 0.0

        def got_len(r):
            if st["path"] == s["path"] and not isinstance(r, Exception):
                st["len"] = r
                bar.config(to=max(r, 1.0))
        ui_background(page, lambda: music_length(s["path"]), got_len)
        sync_out()
        show_lists()

    def play():
        if eng.song and eng.paused:
            eng.pause(False)
            now["playing"] = True
            return sync_out()
        p, sel = cur(), selected()
        if not p["songs"]:
            return say("Add songs to the playlist first.")
        if eng.song and p is st["pl"] and not sel:
            return  # playing already
        play_at(p, sel[0] if sel else music_order(len(p["songs"]), None, v["shuffle"].get())[0])

    def pause():
        if eng.song:
            eng.pause(True)
            now["playing"] = False
            sync_out()

    def stop():
        eng.stop()
        st["path"], st["len"] = None, 0.0
        now.update(title="", playlist="", playing=False)
        v["now"].set("Nothing playing")
        v["pos"].set(0)
        music_now_file("")
        sync_out()
        show_lists()

    def skip(step):
        pl = st["pl"]
        if not pl or not pl["songs"]:
            return play() if step > 0 else None
        if step < 0 and eng.position() > 3:  # Previous a few seconds in: this song from the start
            return eng.seek(0)
        nxt = music_next(st["order"], idx(), repeat(), step)
        return play_at(pl, nxt) if nxt is not None else stop()

    def ended():
        pl = st["pl"]
        nxt = music_next(st["order"], idx(), repeat(), 1, auto=True) if pl and pl["songs"] else None
        return play_at(pl, nxt) if nxt is not None else stop()

    def seek(e=None):
        st["drag"] = False
        if eng.song:
            eng.seek(v["pos"].get())
    bar.bind("<ButtonPress-1>", lambda e: st.update(drag=True))
    bar.bind("<ButtonRelease-1>", seek)

    def links():
        srv = st["server"]
        base = f"http://{srv.host}:{srv.port}/music/{mc['token']}" if srv else ""
        v["stream"].set(base and base + "/stream.mp3")
        v["overlay"].set(base and base + "/now")

    def share(auto=False):
        if st["server"]:
            eng.set_sink("obs", None)
            st["server"].stop()
            st["server"], mc["share"] = None, False
            share_b.config(text="Start sharing")
            share_l.config(text="Not shared - OBS gets nothing from here now.")
            return links()
        if link_public_network():
            if auto:
                return share_l.config(text="Not started by itself: Windows has this network marked Public.")
            if not messagebox.askyesno("Share music", "Windows has this network marked Public (like cafe or hotel "
                                       "Wi-Fi). Other people on it could listen with the link.\n\nOnly share on your "
                                       "own home network. Start anyway?", parent=page):
                return
        try:
            port = int(v["port"].get())
            if not 0 <= port <= 65535:
                raise ValueError("a port is a number up to 65535")
            st["server"] = MusicServer(port, mc["token"], lambda: dict(now))
        except (ValueError, OSError) as e:
            if auto:
                return share_l.config(text=f"Not started by itself on port {v['port'].get()}: {e}")
            return messagebox.showerror("Share music", f"Couldn't start on port {v['port'].get()}:\n{e}", parent=page)
        eng.set_sink("obs", st["server"].feed)
        mc.update(share=True, port=port)
        share_b.config(text="Stop sharing")
        share_l.config(text="Shared: OBS can play it with the links below (plain http on your own network - home "
                            "only; Windows may ask once: allow private networks).")
        links()

    def new_link():
        if not messagebox.askyesno("New link", "Make new links? The old ones stop working - paste the new ones into "
                                   "OBS again.", parent=page):
            return
        mc["token"] = secrets.token_hex(16)
        if st["server"]:
            st["server"].retoken(mc["token"])
        links()
        say("New links made - the old ones don't work any more.")

    def receive(files, name=None):
        """Songs that arrived (a linked computer, another device, a link): a new playlist with that name, or the one
        that's open."""
        items = [(f, "") for f in files if Path(f).suffix.lower() in MUSIC_EXT]
        if name:
            p = new_list(name, items)
        else:
            p = cur()
            music_add(p["songs"], items)
            changed()
        say(f"{len(items)} song(s) into the playlist {p['name']}.")

    def tick():
        try:
            while True:
                events.get_nowait()
                ended()
        except queue.Empty:
            pass
        finally:
            pos = eng.position()
            if not st["drag"]:
                v["pos"].set(pos)
            v["time"].set(f"{fmt(v['pos'].get() if st['drag'] else pos)} / {fmt(st['len'])}")
            page.after(250, tick)

    def save():
        try:
            mc["port"] = int(v["port"].get())
        except ValueError:
            pass
        mc.update(volume=v["vol"].get(), shuffle=v["shuffle"].get(), repeat=repeat(), hear=v["hear"].get(),
                  device=v["device"].get())

    def close():
        save()
        if st["server"]:
            st["server"].stop()
            st["server"] = None
        eng.close()
        if st["out"]:
            st["out"].close()
            st["out"] = None
    for i, (text, fn, tip) in enumerate((
            ("New", new_list, "A new, empty playlist"), ("Rename", rename, "Rename this playlist"),
            ("Duplicate", duplicate, "A copy of this playlist"), ("Delete", delete, "Delete this playlist"),
            ("Import .m3u...", import_m3u, "Playlists from other players (.m3u / .m3u8): one new playlist each"),
            ("Export .m3u...", export_m3u, "This playlist as an .m3u8 file for other players"))):
        b = ttk.Button(pb, text=text, style="Tool.TButton", command=fn)
        b.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 4), pady=1)
        Tip(b, tip)
    pb.columnconfigure((0, 1), weight=1)
    for text, fn, tip in (("Add files...", add_files, "Songs from this PC (sound or video files)"),
                          ("Add folder...", add_folder, "Every song in a folder, in name order"),
                          ("Move up", lambda: move(-1), "The selected songs one place up"),
                          ("Move down", lambda: move(1), "The selected songs one place down"),
                          ("Remove", remove, "Take the selected songs off the playlist (Del)")):
        b = ttk.Button(side, text=text, command=fn, width=14)
        b.pack(pady=2, fill="x")
        Tip(b, tip)
    stv.bind("<Double-1>", lambda e: (it := stv.identify_row(e.y)) and play_at(cur(), int(it)))
    ui_keys(page, {"<Delete>": remove})
    v["vol"].trace_add("write", lambda *_: setattr(eng, "volume", v["vol"].get()))
    v["shuffle"].trace_add("write", reorder)
    for k in ("hear", "device"):
        v[k].trace_add("write", lambda *_: sync_out())
    show_lists()
    tick()
    if mc.get("share"):  # shared when the app closed: OBS finds it again by itself
        page.after(1200, lambda: share(auto=True))
    return {"add": add_songs, "receive": receive,  # songs: what a linked computer may pick from (not imported ones)
            "songs": lambda: [Path(s["path"]) for p in lists for s in p["songs"] if not s.get("m3u")],
            "files": lambda: [Path(s["path"]) for s in cur()["songs"]], "name": lambda: cur()["name"], "stop": close,
            "save": save, "vars": v, "state": st, "engine": eng, "now": now, "lists": lists, "play": play,
            "pause": pause, "share": share, "tree": stv, "playlists": ptv, "status": lambda: status.cget("text")}
