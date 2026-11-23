"""The editor tab."""
import json
import os
from pathlib import Path
from .core import AUDIO_EXT
from .mirror import clean_name, sound_folders
from .deck import (
    SD_AUTO,
    SD_DEFAULT_OUT,
    SD_DIR,
    SD_FADES,
    SD_FOLDER,
    SD_GOALS,
    SD_KINDS,
    SD_MODES,
    SD_PARENT,
    SD_PLAY,
    SD_TOL,
    SD_TUNE,
    sd_add_sounds,
    sd_beside,
    sd_clone_folders,
    sd_combine,
    sd_connected,
    sd_devices,
    sd_fill,
    sd_folders,
    sd_free,
    sd_images,
    sd_key,
    sd_keypad,
    sd_kind,
    sd_label,
    sd_level_rows,
    sd_listen,
    sd_match_loudness,
    sd_missing,
    sd_move,
    sd_multis,
    sd_out,
    sd_out_name,
    sd_output_choices,
    sd_pages,
    sd_plays_like,
    sd_profiles,
    sd_push,
    sd_reachable,
    sd_relink,
    sd_renew,
    sd_running,
    sd_set_levels,
    sd_set_sound,
    sd_sounds,
    sd_split,
    sd_stop_key,
    sd_title,
    sd_wrap,
)
from .ui import (
    DeckGrid,
    GOAL_HELP,
    Tip,
    UI,
    UI_SWATCH,
    sd_levels_text,
    ui_background,
    ui_cell_edit,
    ui_keys,
    ui_level_report,
    ui_menu,
    ui_multi_rows,
    ui_obs_levels,
    ui_pick_sounds,
    ui_volume,
)
from .dialogs import ui_bulk_dialog, ui_grow_kind, ui_key_dialog, ui_new_key_dialog


def sd_editor_tab(page, cfg, made=()):
    """Edit the buttons of profiles already in the local Stream Deck app: select keys, use a tool, save.
    made = files the Channel Mirror tab wrote this session (offered by the import window).
    Returns {pending, save, saving} so the window can send unsent changes when it closes; None without Stream Deck."""
    import copy
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk

    if not (SD_DIR / "ProfilesV3").is_dir():
        ttk.Label(page, text="No local Stream Deck install found (looked in %APPDATA%\\Elgato\\StreamDeck).\n"
                             "Install the Stream Deck app, then reopen Channel Mirror.", justify="left"
                  ).pack(padx=20, pady=20, anchor="w")
        return
    plugged = sd_connected()
    kinds = {u for u in SD_KINDS.values() if u}  # Multi Action / Random Action ids
    grids = {v[1]: v[2:] for v in sd_devices(plugged=plugged).values()}  # device id -> (cols, rows)
    profs = {}
    for folder, m in sd_profiles():
        did = m.get("Device", {}).get("UUID", "")
        try:
            vid, pid, serial = did[did.index("[") + 1:did.rindex("]")].split("/")
            on = f"USB\\VID_{int(vid):04X}&PID_{int(pid):04X}\\{serial.upper()}" in plugged
        except ValueError:
            on = False
        lbl = f"{'[connected] ' if on else ''}{m.get('Name') or folder.stem}  ({m.get('Device', {}).get('Model', '?')})"
        n = 2
        while lbl in profs:  # profiles can share a name
            lbl, n = f"{lbl.rsplit(' #', 1)[0]} #{n}", n + 1
        profs[lbl] = (folder, m)
    labels_ = sorted(profs, key=lambda s: (not s.startswith("[connected]"), s.lower()))
    edits = {}  # page manifest path -> edited json (unsaved)
    blobs = {}  # icon file -> bytes, copied with keys; written with the next send
    listeners, hooks = [], {}  # other tabs redrawn after each change; hooks["import"] opens the import tab
    st = {"pages": [], "named": [], "idx": None, "page": None, "sel": [], "back": []}
    hist = {"undo": [], "redo": [], "clip": None}
    FOLDER, PARENT = SD_FOLDER, SD_PARENT

    # toolbar
    bar = ttk.Frame(page, padding=(10, 10, 10, 4))
    bar.pack(fill="x")
    prof_v, multi_v, multi_map = tk.StringVar(value=labels_[0] if labels_ else ""), tk.StringVar(), {}
    ttk.Label(bar, text="Profile").pack(side="left")
    ttk.Combobox(bar, textvariable=prof_v, values=labels_, state="readonly", width=36).pack(side="left", padx=(6, 14))
    ttk.Label(bar, text="Jump to Multi / Random").pack(side="left")
    multi_cb = ttk.Combobox(bar, textvariable=multi_v, state="readonly", width=36)
    multi_cb.pack(side="left", padx=6)
    bar2 = ttk.Frame(page, padding=(10, 0, 10, 4))  # its own row, so it stays on screen in a small window
    bar2.pack(fill="x")
    save_btn = ttk.Button(bar2, text="Save to Stream Deck", style="Accent.TButton")
    save_btn.pack(side="left")
    auto_v = tk.BooleanVar(value=cfg.get("sd_autosend", True))
    auto_v.trace_add("write", lambda *_: (cfg.update(sd_autosend=auto_v.get()), changed()))
    ab = ttk.Checkbutton(bar2, text="Send changes automatically", variable=auto_v)
    ab.pack(side="left", padx=(10, 0))
    Tip(ab, "Each change goes to Stream Deck about 1.5 s after you stop editing. Stream Deck closes and reopens "
            "for a few seconds to take it. Off = changes wait for Save to Stream Deck (Ctrl+S).")
    tbtn = {}
    for name, text, tip in (("revert", "Revert", "Throw away every unsaved change (can be undone)"),
                            ("redo", "Redo", "Ctrl+Y"), ("undo", "Undo", "Ctrl+Z")):
        tbtn[name] = ttk.Button(bar2, text=text, style="Tool.TButton")
        tbtn[name].pack(side="right", padx=(6, 0))
        Tip(tbtn[name], tip)
    unsent_l = ttk.Label(bar2, font=("Segoe UI", 9, "bold"))
    unsent_l.pack(side="left", padx=(12, 0))

    panes = ttk.PanedWindow(page, orient="horizontal")
    panes.pack(fill="both", expand=True, padx=10, pady=6)
    pages_f = ttk.LabelFrame(panes, text="Pages")
    left = ttk.LabelFrame(panes, text="Keys")
    right = ttk.LabelFrame(panes, text="Tools for the selected keys")
    panes.add(pages_f, weight=1)
    panes.add(left, weight=3)
    panes.add(right, weight=2)
    status = ttk.Label(page, style="Status.TLabel", anchor="w",
                       text="Pick a profile and page. Click keys to select them (Ctrl+click adds).")
    status.pack(fill="x", padx=12, pady=(0, 8))

    # pages: list with per-page counts, prev / next, jump to problems, folder back
    nav = ttk.Frame(pages_f)
    nav.pack(fill="x")
    prev_b = ttk.Button(nav, text="< Prev", style="Tool.TButton", command=lambda: go_page(st["idx"] - 1))
    next_b = ttk.Button(nav, text="Next >", style="Tool.TButton", command=lambda: go_page(st["idx"] + 1))
    prev_b.pack(side="left")
    next_b.pack(side="left", padx=4)
    count_l = ttk.Label(nav, style="Hint.TLabel")
    count_l.pack(side="left", padx=6)
    Tip(prev_b, "Previous page (PgUp)")
    Tip(next_b, "Next page (PgDn)")
    pcols = ("page", "keys", "sounds", "missing")
    ptv = ttk.Treeview(pages_f, columns=pcols, show="headings", selectmode="browse", height=8)
    for c, h, w in zip(pcols, ("Page", "Keys", "Sounds", "Missing"), (150, 45, 55, 60)):
        ptv.heading(c, text=h)
        ptv.column(c, width=w, stretch=c == "page", anchor="w" if c == "page" else "center")
    ptv.tag_configure("missing", foreground=UI["bad"])
    ptv.tag_configure("edited", font=("Segoe UI", 10, "bold"))
    ptv.pack(fill="both", expand=True, pady=6)
    nav2 = ttk.Frame(pages_f)
    nav2.pack(fill="x")
    issue_b = ttk.Button(nav2, text="Next page with missing sounds", style="Tool.TButton",
                         command=lambda: next_issue())
    issue_b.pack(fill="x")
    back_b = ttk.Button(nav2, text="Back (out of folder)", style="Tool.TButton", command=lambda: go_back())
    back_b.pack(fill="x", pady=(4, 0))
    Tip(back_b, "Alt+Left. Also: double-click the Parent Folder key")
    ttk.Label(pages_f, text="Red = has missing sound files\nBold * = unsaved changes\nDouble-click a folder key "
                            "to open it", style="Hint.TLabel", justify="left").pack(anchor="w", pady=(6, 0))

    # left: selection buttons, the deck, legend, details
    sb = ttk.Frame(left)
    sb.pack(fill="x")
    ttk.Label(sb, text="Select", style="Hint.TLabel").pack(side="left", padx=(0, 6))
    for text, test, tip in (("Sounds", lambda a: bool(sd_sounds(a)), "Every key that plays a sound"),
                            ("Missing", lambda a: bool(sd_missing(a)), "Sound keys whose file can't be found"),
                            ("Multi / Random", lambda a: bool(a) and a.get("UUID") in kinds, "Multi and Random Actions"),
                            ("All", bool, "Every key in use (Ctrl+A)"), ("None", lambda a: False, "Esc")):
        b = ttk.Button(sb, text=text, style="Tool.TButton", command=lambda t=test: select(t))
        b.pack(side="left", padx=(0, 4))
        Tip(b, tip)
    sb2 = ttk.Frame(left)
    sb2.pack(fill="x", pady=(4, 0))
    eb = ttk.Button(sb2, text="Edit selected...", style="Tool.TButton", command=lambda: bulk_edit())
    eb.pack(side="left")
    ib = ttk.Button(sb2, text="Import sounds into folders...", style="Tool.TButton", command=lambda: import_sounds())
    ib.pack(side="left", padx=(6, 0))
    Tip(ib, "Each sound its own key (play once or loop), in folders of N; you pick the keys the folders go on, on any "
            "page, and see which keys are in use. Volume, levels and output too.")
    Tip(eb, "Edit every selected key in one window (Ctrl+E / Enter)")

    def tile(pos):
        a, on = keys_now().get(pos), pos in st["sel"]
        c, r_ = map(int, pos.split(","))
        bg = (UI["accent"] if on else UI["missing"] if a and sd_missing(a) else UI["sound"] if a and sd_sounds(a)
              else UI["other"] if a else UI["empty"])
        fg = UI["on_accent"] if on else UI["text"] if a else UI["muted"]
        if not a:
            return f"{c + 1},{r_ + 1}", bg, fg
        return f"{(sd_title(a).replace(chr(10), ' ') or '-')[:22]}\n{sd_kind(a)[:16]}", bg, fg

    def tip_for(pos):
        a = keys_now().get(pos)
        c, r_ = map(int, pos.split(","))
        if not a:
            return (f"Empty key {c + 1},{r_ + 1}\nDouble-click to add a sound key; right-click for a new folder of "
                    "sounds, or to fill the free keys from here in order.")
        lines = [f"Key {c + 1},{r_ + 1}: {sd_title(a).replace(chr(10), ' ') or '(no name)'}  -  {sd_kind(a)}"]
        for s in sd_sounds(a)[:10]:
            se = s.get("Settings", {})
            miss = "" if Path(se.get("path", "")).is_file() else "   MISSING"
            lines.append(f"  - {Path(se.get('path', '')).name}  ({SD_MODES[se.get('actionType', 0)] if se.get('actionType', 0) < 4 else '?'}"
                         f", vol {se.get('volume', '?')}){miss}")
        if len(sd_sounds(a)) > 10:
            lines.append(f"  ...and {len(sd_sounds(a)) - 10} more")
        how = ("Double-click to open this folder" if a.get("UUID") == FOLDER else
               "Double-click to go back out of the folder" if a.get("UUID") == PARENT else "Double-click to edit")
        return "\n".join(lines + [f"{how}; drag to move; right-click for more."])

    def click(pos, e):
        if e.state & 0x0001 and st.get("anchor"):  # Shift: the rectangle from the last clicked key
            c1, r1 = map(int, st["anchor"].split(","))
            c2, r2 = map(int, pos.split(","))
            st["sel"] = [f"{c},{r_}" for r_ in range(min(r1, r2), max(r1, r2) + 1)
                         for c in range(min(c1, c2), max(c1, c2) + 1)]
        else:
            if e.state & 0x0004:  # Ctrl: add or remove one key
                st["sel"].remove(pos) if pos in st["sel"] else st["sel"].append(pos)
            else:
                st["sel"] = [] if st["sel"] == [pos] else [pos]
            st["anchor"] = pos
        draw()

    def double(pos):
        a = keys_now().get(pos)
        if a and a.get("UUID") == FOLDER:
            return open_folder(pos)
        if a and a.get("UUID") == PARENT:
            return go_back()
        return edit_key(pos) if a else new_key(pos)

    deck = DeckGrid(left, tile, on_click=click, on_double=lambda p, e: double(p),
                    on_menu=lambda p, e: key_menu(p, e), on_drop=lambda a, b: drop(a, b), tip=tip_for)
    deck.frame.pack(pady=(10, 6))
    legend = ttk.Frame(left)
    legend.pack(fill="x")
    for color, text in ((UI["sound"], "sound"), (UI["missing"], "file missing"), (UI["other"], "other action"),
                        (UI["accent"], "selected")):
        tk.Label(legend, bg=color, width=2, **UI_SWATCH).pack(side="left")
        ttk.Label(legend, text=text, style="Hint.TLabel").pack(side="left", padx=(4, 14))
    ttk.Label(legend, text="Ctrl/Shift+click = select several  -  Drag = move/swap  -  Double-click = edit",
              style="Hint.TLabel").pack(side="right")
    dcols = ("key", "name", "type", "mode", "fade", "volume", "output", "file")
    dt = ttk.Frame(left)
    dt.pack(fill="both", expand=True, pady=(8, 0))
    details = ttk.Treeview(dt, columns=dcols, show="headings", height=4, selectmode="extended")
    for c, h, w in zip(dcols, ("Key", "Name", "Type", "Action", "Fade", "Vol", "Output", "File"),
                       (40, 90, 70, 90, 95, 40, 100, 140)):  # they stretch; small starting widths fit small windows
        details.heading(c, text=h)
        details.column(c, width=w, stretch=c in ("name", "file", "output"))
    dys = ttk.Scrollbar(dt, command=details.yview)
    details.config(yscrollcommand=dys.set)
    dys.pack(side="right", fill="y")
    details.pack(fill="both", expand=True)
    ttk.Label(left, text="Double-click a cell to change it - select several rows first to change them all at once.",
              style="Hint.TLabel").pack(anchor="w", pady=(4, 0))

    # right: tool list + options
    goals = tuple(GOAL_HELP)
    goal_v = tk.StringVar(value=goals[0])
    tools = ttk.Frame(right)
    tools.pack(side="left", fill="y", padx=(0, 12))
    for g in goals:
        ttk.Radiobutton(tools, text=g, value=g, variable=goal_v, style="Toolbutton").pack(fill="x", pady=1)
    opts = ttk.Frame(right)
    opts.pack(side="left", fill="both", expand=True)
    help_lbl = ttk.Label(opts, style="Hint.TLabel", wraplength=420, justify="left")
    help_lbl.pack(fill="x", pady=(0, 8))
    holder = ttk.Frame(opts)
    holder.pack(fill="both", expand=True)
    SCOPES = ("Selected keys (a folder = every sound inside it)", "Every sound key on this page",
              "Every sound key in this profile (all pages)")
    scope_v = tk.StringVar(value=SCOPES[0])
    arow = ttk.Frame(opts)
    arow.pack(fill="x", pady=(8, 0))
    ttk.Label(arow, text="Apply to").pack(side="left")
    ttk.Combobox(arow, textvariable=scope_v, values=SCOPES, state="readonly", width=34).pack(side="left", padx=6)
    arow2 = ttk.Frame(opts)  # its own row: always on screen
    arow2.pack(fill="x", pady=(6, 0))
    apply_btn = ttk.Button(arow2, text="Apply", style="Accent.TButton")
    apply_btn.pack(side="right")
    frames = {g: ttk.Frame(holder) for g in goals}
    o = {}

    def row(g, label, make):
        fr = ttk.Frame(frames[g])
        fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=14).pack(side="left")
        make(fr)
        return fr

    def combo(g, key, label, values, width=22):
        o[key] = tk.StringVar(value=values[0])
        row(g, label, lambda fr: ttk.Combobox(fr, textvariable=o[key], values=values, state="readonly",
                                               width=width).pack(side="left"))

    def entry(g, key, label, value="", width=24):
        o[key] = tk.StringVar(value=value)
        row(g, label, lambda fr: ttk.Entry(fr, textvariable=o[key], width=width).pack(side="left"))

    g = goals[0]
    combo(g, "goal", "Purpose", tuple(SD_GOALS), 34)
    goal_desc = ttk.Label(frames[g], style="Hint.TLabel")
    goal_desc.pack(fill="x", pady=(4, 0))
    o["goal"].trace_add("write", lambda *_: goal_desc.config(text="Sets: {} / {} {}s{}".format(
        *SD_GOALS[o["goal"].get()][:3],
        f" / volume {SD_GOALS[o['goal'].get()][3]}" if SD_GOALS[o["goal"].get()][3] is not None else "")))
    o["goal"].set(o["goal"].get())
    g = goals[1]
    combo(g, "mode", "Action", ("Keep",) + SD_MODES)
    combo(g, "fade", "Fade", ("Keep",) + SD_FADES)
    combo(g, "fade_len", "Fade length (s)", ("Keep", "1", "2", "3", "4", "5"), 8)
    g = goals[2]
    o["vol_how"], o["vol"], o["step"] = tk.StringVar(value="set"), tk.IntVar(value=80), tk.IntVar(value=-10)
    o["scale"] = tk.IntVar(value=80)
    o["tune"] = tk.StringVar(value=SD_AUTO)

    sd_set_levels(cfg.get("obs_levels"))

    def tune_box(fr):
        ttk.Combobox(fr, textvariable=o["tune"], values=list(SD_TUNE), state="readonly", width=34).pack(side="left")
        fr2 = ttk.Frame(fr.master)  # under it: the levels and the button to change them
        fr2.pack(fill="x", padx=(120, 0))
        lv = ttk.Label(fr2, text=f"{sd_levels_text()}; within {SD_TOL:.0f} dB is left alone", style="Hint.TLabel",
                       wraplength=300, justify="left")
        ttk.Button(fr2, text="My OBS levels...", style="Tool.TButton", command=lambda: ui_obs_levels(page, cfg) and lv.config(
            text=f"{sd_levels_text()}; within {SD_TOL:.0f} dB is left alone")).pack(side="left", padx=(0, 8))
        lv.pack(side="left")
        lv.bind("<Map>", lambda e: lv.config(text=f"{sd_levels_text()}; within {SD_TOL:.0f} dB is left alone"))
    for how, text, make in (("set", "Set to", lambda fr: ui_volume(fr, o["vol"], 180).pack(side="left")),
                            ("step", "Change by (+/-)", lambda fr: ttk.Spinbox(fr, textvariable=o["step"], from_=-100,
                                                                              to=100, width=6).pack(side="left")),
                            ("scale", "Scale by %", lambda fr: (
                                ttk.Spinbox(fr, textvariable=o["scale"], from_=1, to=400, width=6).pack(side="left"),
                                ttk.Label(fr, text="keeps them in proportion: 50 = half each volume setting, 150 = "
                                                   "half as much again (100 at most)", style="Hint.TLabel").pack(
                                    side="left", padx=6))),
                            ("match", "Match loudness", lambda fr: ttk.Label(
                                fr, text="measures each file; louder ones are turned down to the quietest",
                                style="Hint.TLabel").pack(side="left")),
                            ("tune", "Tune to level", tune_box),
                            ("check", "Check levels", lambda fr: ttk.Label(
                                fr, text="listens to each sound and lists where it sits; changes nothing until you "
                                         "press Tune in the list", style="Hint.TLabel").pack(side="left"))):
        fr = ttk.Frame(frames[g])
        fr.pack(fill="x", pady=4)
        ttk.Radiobutton(fr, text=text, variable=o["vol_how"], value=how, width=16).pack(side="left")
        make(fr)
    g = goals[3]
    o["output"] = tk.StringVar(value=SD_DEFAULT_OUT)

    def out_box(fr):
        cb = ttk.Combobox(fr, textvariable=o["output"], width=34)
        cb.config(postcommand=lambda: cb.config(values=sd_output_choices()))
        cb.pack(side="left")
    row(g, "Output device", out_box)
    g = goals[4]
    combo(g, "source", "Name from", ("Keep", "File name", "Folder name", "Number", "Clear"))
    entry(g, "prefix", "Add before")
    entry(g, "suffix", "Add after")
    entry(g, "find", "Replace text")
    entry(g, "repl", "   with")
    combo(g, "show", "Show name", ("Keep", "Show", "Hide"), 10)
    combo(g, "size", "Font size", ("Keep", "7", "8", "9", "10", "12", "14", "16", "18"), 10)
    combo(g, "align", "Name position", ("Keep", "top", "middle", "bottom"), 10)
    o["color"] = tk.StringVar(value="")

    def color_row(fr):
        sw = tk.Label(fr, width=3, bg=UI["panel"], **UI_SWATCH)

        def pick():
            c = colorchooser.askcolor(o["color"].get() or "#ffffff", title="Name colour")[1]
            if c:
                o["color"].set(c)
                sw.config(bg=c, text="")
        sw.pack(side="left", padx=(0, 6))
        ttk.Button(fr, text="Pick...", style="Tool.TButton", command=pick).pack(side="left")
        st_["swatch"] = sw
    st_ = {}
    row(g, "Name colour", color_row)
    row(g, "", lambda fr: ttk.Button(fr, text="Keep", style="Tool.TButton", command=lambda: (
        o["color"].set(""), st_["swatch"].config(bg=UI["panel"]))).pack(side="left"))  # under Pick: fits small windows
    g = goals[5]
    o["arr"], o["slot"], o["ctitle"] = tk.StringVar(value="combine"), tk.StringVar(value="1,1"), tk.StringVar()
    o["ckind"] = tk.StringVar(value="Random Action")
    for how, text, extra in (
            ("combine", "Combine selected into one",
             lambda fr: (ttk.Combobox(fr, textvariable=o["ckind"], values=("Random Action", "Multi Action"),
                                      state="readonly", width=13).pack(anchor="w"),
                         (lambda f2: (f2.pack(anchor="w", pady=(3, 0)),  # the name on the line under it
                                      ttk.Label(f2, text="named").pack(side="left"),
                                      ttk.Entry(f2, textvariable=o["ctitle"], width=14).pack(side="left", padx=6)
                                      ))(ttk.Frame(fr)))),
            ("split", "Split Multi / Random keys into single keys", lambda fr: None),
            ("move", "Move the selected key to (col,row)",
             lambda fr: ttk.Entry(fr, textvariable=o["slot"], width=6).pack(side="left")),
            ("stop", "Add a 'Stop all audio' key at (col,row)",
             lambda fr: ttk.Entry(fr, textvariable=o["slot"], width=6).pack(side="left")),
            ("delete", "Delete the selected keys", lambda fr: None)):
        fr = ttk.Frame(frames[g])
        fr.pack(fill="x", pady=3)
        ttk.Radiobutton(fr, text=text, variable=o["arr"], value=how).pack(anchor="w")
        sub = ttk.Frame(fr)  # its box / choices under it, so they stay on screen in a narrow window
        sub.pack(fill="x", padx=(26, 0))
        extra(sub)
    g = goals[6]
    entry(g, "folder", "Search folder", str(Path.home() / "Music"), 30)
    row(g, "", lambda fr: ttk.Button(fr, text="Browse...", style="Tool.TButton", command=lambda: o["folder"].set(
        filedialog.askdirectory(title="Folder that holds the sounds") or o["folder"].get())).pack(side="left"))

    def on_goal(*_):
        for f in frames.values():
            f.pack_forget()
        frames[goal_v.get()].pack(fill="both", expand=True)
        help_lbl.config(text=GOAL_HELP[goal_v.get()])
    goal_v.trace_add("write", on_goal)
    on_goal()

    # state helpers
    def disk(p):
        """The page as Stream Deck has it; None for a new folder's page that hasn't been sent yet."""
        import time
        for _ in range(20):  # Windows locks a file for a moment while it's replaced (a send, or Stream Deck saving)
            try:
                return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
            except (PermissionError, ValueError):  # locked, or caught half-written by Stream Deck: read it again
                time.sleep(0.025)
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def cur_page():
        p = st["page"]
        if p and p not in edits:
            edits[p] = disk(p) or {}
        return edits.get(p)

    def keys_now():  # read-only view; sd_keypad() would normalise the json and make the page look edited
        ctrl = next((c for c in (cur_page() or {}).get("Controllers") or [] if c.get("Type") == "Keypad"), {})
        return ctrl.get("Actions") or {}

    def dev_grid():
        return grids.get(profs[prof_v.get()][1].get("Device", {}).get("UUID", ""), (5, 3))

    def size():
        cols, rows = dev_grid()
        for k in keys_now():
            c, r_ = map(int, k.split(","))
            cols, rows = max(cols, c + 1), max(rows, r_ + 1)
        return cols, rows

    def snap():
        return copy.deepcopy(edits), list(st["sel"])

    def commit(before, msg):
        """Record an edit for undo and show it."""
        hist["undo"].append(before)
        del hist["undo"][:-60]
        hist["redo"].clear()
        status.config(text=f"{msg}. " + ("Sending to Stream Deck in a moment..." if auto_v.get() else
                                         "Not sent yet - Save to Stream Deck (Ctrl+S) sends it; Ctrl+Z undoes it."))
        reload_pages()
        refresh_lists()
        draw()
        changed()
        for f in listeners:
            f()

    def restore(frm, to, msg):
        if not hist[frm]:
            return
        hist[to].append(snap())
        e, sel = hist[frm].pop()
        edits.clear()
        edits.update(e)
        st["sel"] = sel
        status.config(text=msg)
        reload_pages()
        refresh_lists()
        draw()
        changed()
        for f in listeners:
            f()

    def reload_pages():
        """Page list again after an edit: a new folder's page appears (unsent), an undone one goes."""
        folder, m = profs[prof_v.get()]
        # a new folder's page whose key was deleted or replaced before sending (and the folders inside it): nothing
        # can open it any more, so it isn't sent. Undo brings it back with its key.
        new = [p for p in edits if p.parents[2] == folder and not p.is_file()]
        if new:
            every = {p.parent.name.lower(): p for p in [*(folder / "Profiles").glob("*/manifest.json"), *new]}

            def read(p):
                try:
                    return page_json(p)
                except (OSError, ValueError):
                    return {}
            live = sd_reachable([i for i, p in every.items() if p.is_file()], {i: read(p) for i, p in every.items()})
            for p in new:
                if p.parent.name.lower() not in live:
                    del edits[p]
        st["named"] = sd_pages(folder, m, {p: d for p, d in edits.items() if p.parents[2] == folder})
        st["pages"] = [p for _, p in st["named"]]
        if st["page"] in st["pages"]:
            st["idx"] = st["pages"].index(st["page"])
        else:  # callers redraw the lists next
            st.update(idx=0 if st["pages"] else None, page=st["pages"][0] if st["pages"] else None, sel=[])

    def changed():
        """With auto-send on, send to Stream Deck shortly after the last change (one restart per burst of edits)."""
        if st.get("job"):
            page.after_cancel(st["job"])
            st["job"] = None
        if auto_v.get() and pending():
            st["job"] = page.after(1500, lambda: save(auto=True))

    def pending():
        """Pages whose edits haven't reached Stream Deck yet: {page file: json}."""
        return {p: d for p, d in edits.items() if d != disk(p)}

    def kp_edit():
        return sd_keypad(cur_page())

    def draw():
        if st["page"]:
            deck.draw(*size())
        details.delete(*details.get_children())
        kp = keys_now()
        for k in st["sel"]:
            a = kp.get(k)
            c, r_ = map(int, k.split(","))
            key = f"{c + 1},{r_ + 1}"
            if not a:
                details.insert("", "end", iid=f"e|{k}", values=(key, "(empty)", "", "", "", "", "", ""))
                continue
            snds = sd_sounds(a)
            if a.get("UUID") != SD_PLAY:
                details.insert("", "end", iid=f"k|{k}", values=(key, sd_title(a).replace("\n", " "), sd_kind(a),
                                                               "", "", "", "", ""))
            for i, s in enumerate(snds):
                se = s.get("Settings", {})
                miss = "" if Path(se.get("path", "")).is_file() else "  (missing)"
                fade = (SD_FADES[se.get("fadeType", 0)] if se.get("fadeType", 0) < 4 else "?") + (
                    f" {se.get('fadeLen', 1)}s" if se.get("fadeType") else "")
                single = a.get("UUID") == SD_PLAY
                details.insert("", "end", iid=f"s|{k}|{i}", values=(
                    key if single else "", sd_title(a).replace("\n", " ") if single else "",
                    "Sound" if single else "  sound", SD_MODES[se.get("actionType", 0)] if se.get("actionType", 0) < 4
                    else "?", fade, se.get("volume", "?"), sd_out_name(se.get("outputType")),
                    Path(se.get("path", "")).name + miss))
        dirty = len(pending())
        save_btn.config(text=f"Save to Stream Deck ({dirty} page{'s' * (dirty != 1)} changed)" if dirty
                        else "Save to Stream Deck")
        unsent_l.config(text=f"{dirty} page{'s' * (dirty != 1)} not sent to Stream Deck yet" if dirty else
                        "Stream Deck is up to date")
        unsent_l.config(foreground=UI["warn"] if dirty else UI["good"])
        used = sum(1 for k in st["sel"] if kp.get(k))
        apply_btn.config(text="Apply" if scope_v.get() != SCOPES[0] or not used else
                         f"Apply to {used} key{'s' * (used != 1)}")
        n, i = len(st["named"]), st["idx"]
        prev_b.state(["!disabled"] if i else ["disabled"])
        next_b.state(["!disabled"] if i is not None and i < n - 1 else ["disabled"])
        back_b.state(["!disabled"] if st["back"] or parent_of_page() is not None else ["disabled"])
        count_l.config(text=f"{st['named'][i][0]}  ({i + 1} of {n})" if i is not None else "no pages")
        tbtn["undo"].state(["!disabled"] if hist["undo"] else ["disabled"])
        tbtn["redo"].state(["!disabled"] if hist["redo"] else ["disabled"])

    def select(test):
        kp = keys_now()
        cols, rows = size()
        st["sel"] = [k for k in (f"{c},{r_}" for r_ in range(rows) for c in range(cols)) if test(kp.get(k))]
        draw()

    def on_prof(*_):
        if prof_v.get() not in profs:
            return
        st.update(idx=None, page=None, sel=[], back=[])
        reload_pages()
        st.update(idx=None, page=None)  # go_page(0) below opens the first page
        refresh_lists()
        go_page(0)

    def page_json(p):
        return edits.get(p) or disk(p) or {}

    def page_keys(p):
        ctrl = next((c for c in page_json(p).get("Controllers") or [] if c.get("Type") == "Keypad"), {})
        return ctrl.get("Actions") or {}

    def page_stats(p):
        acts = [a for a in page_keys(p).values() if a]
        return len(acts), sum(len(sd_sounds(a)) for a in acts), sum(len(sd_missing(a)) for a in acts)

    def refresh_lists():
        list_multis()
        ptv.delete(*ptv.get_children())
        for i, (name, p) in enumerate(st["named"]):
            k, snd, miss = page_stats(p)
            edited = p in edits and edits[p] != disk(p)
            ptv.insert("", "end", iid=str(i), values=(name + (" *" if edited else ""), k, snd, miss or ""),
                       tags=(("missing",) if miss else ()) + (("edited",) if edited else ()))
        if st["idx"] is not None:
            ptv.selection_set(str(st["idx"]))

    def go_page(i, remember=False):
        if not st["named"]:
            st.update(idx=None, page=None, sel=[])
            status.config(text="This profile has no pages.")
            return draw()
        i = max(0, min(int(i), len(st["named"]) - 1))
        if i != st["idx"]:
            if remember and st["page"] is not None:
                st["back"].append(st["page"])  # a page, not its index: new folders shift the indexes
            st.update(idx=i, page=st["named"][i][1], sel=[])
        if ptv.selection() != (str(i),):  # re-selecting fires <<TreeviewSelect>> -> go_page again: an endless loop
            ptv.selection_set(str(i))
        ptv.see(str(i))
        draw()

    def parent_of_page():
        """Index of the page holding the folder key that opens the current page (None on top-level pages)."""
        if not st["page"]:
            return None
        me = st["page"].parent.name.lower()
        for i, (_, p) in enumerate(st["named"]):
            for a in page_keys(p).values():
                if a and a.get("UUID") == FOLDER and str((a.get("Settings") or {}).get("ProfileUUID", "")).lower() == me:
                    return i
        return None

    def open_folder(pos):
        pid = str((keys_now()[pos].get("Settings") or {}).get("ProfileUUID", "")).lower()
        i = next((i for i, (_, p) in enumerate(st["named"]) if p.parent.name.lower() == pid), None)
        if i is None:
            return status.config(text="That folder's page isn't in this profile.")
        go_page(i, remember=True)
        status.config(text=f"Opened {st['named'][i][0]}. Back (Alt+Left) or the Parent Folder key returns.")

    def go_back():
        p = st["back"].pop() if st["back"] else None
        i = st["pages"].index(p) if p in st["pages"] else parent_of_page()
        if i is not None:
            go_page(i)

    def next_issue():
        n = len(st["named"])
        for step in range(1, n + 1):
            i = ((st["idx"] or 0) + step) % n
            if page_stats(st["named"][i][1])[2]:
                go_page(i)
                select(lambda a: bool(sd_missing(a)))
                return status.config(text=f"{st['named'][i][0]}: the red keys have missing files. Try the "
                                          "'Fix missing sound files' tool, or double-click File in the list.")
        status.config(text="No page in this profile has missing sound files.")

    def list_multis():
        pages = [(n, page_json(p)) for n, p in st["named"]]
        multi_map.clear()
        for label, k, a in sorted(sd_multis(pages), key=lambda x: not sd_sounds(x[2])):  # sound keys first
            c, r_ = map(int, k.split(","))
            multi_map[f"{label} - key {c + 1},{r_ + 1} - {sd_title(a).replace(chr(10), ' ') or '(no name)'}"
                      f" [{sd_kind(a)}]"] = (label, k)
        multi_cb.config(values=list(multi_map) or ["(no Multi or Random Actions in this profile)"])
        multi_v.set("")

    def on_multi(*_):
        if multi_v.get() in multi_map:
            label, k = multi_map[multi_v.get()]
            go_page([n for n, _ in st["named"]].index(label))
            st["sel"] = [k]
            draw()
            status.config(text=f"Selected {multi_v.get()}. Choose a tool on the right (e.g. Output device) and Apply.")


    def slot(text):
        c, r_ = sd_key(text, *size())
        return f"{c},{r_}"

    # key actions (grid, menus, shortcuts)
    def edit_key(pos):
        st["sel"] = [pos]
        draw()
        a = keys_now().get(pos)
        new = ui_key_dialog(page, a) if a else None
        if new is not None and new != a:
            before = snap()
            kp_edit()[pos] = new
            commit(before, f"Edited key {pos_label(pos)}")

    def new_key(pos):
        files = ui_pick_sounds(page, f"Sound(s) for key {pos_label(pos)}",
                               initialdir=cfg.get("out_dir") or None)  # where Channel Mirror saved its generated files
        got = ui_new_key_dialog(page, files) if files else None
        if not got:
            return
        kind, name, plays = got
        before = snap()
        kp_edit()[pos] = plays[0] if kind == "Single sound" else sd_wrap(kind, name, plays)
        st["sel"] = [pos]
        commit(before, f"New sound key at {pos_label(pos)}")

    def add_to_key(pos, folder=False):
        """More sounds on a sound / Random / Multi key; they copy its first sound's playback settings."""
        a = keys_now().get(pos)
        files = ui_pick_sounds(page, f"{'A folder of sounds' if folder else 'Sounds'} to add to key {pos_label(pos)}",
                               folder)
        kind = (ui_grow_kind(page) if a.get("UUID") == SD_PLAY else "Random Action") if files else None
        if not kind:
            return
        before = snap()
        kp_edit()[pos] = sd_add_sounds(kp_edit()[pos], sd_plays_like(files, sd_sounds(a)[0] if sd_sounds(a) else None),
                                       kind)
        st["sel"] = [pos]
        commit(before, f"Added {len(files)} sound(s) to key {pos_label(pos)} ({sd_kind(kp_edit()[pos])})")

    def fit(files, free, where):
        """The files that fit in `free` places, after asking when some don't; [] = cancelled."""
        if len(files) <= free or (free and messagebox.askyesno(
                "Not enough keys", f"{where} has room for {free} of these {len(files)} sounds.\n"
                f"Add the first {free} ({Path(files[0]).name} ... {Path(files[free - 1]).name})?")):
            return files[:free]
        if not free:
            messagebox.showinfo("Not enough keys", f"{where} has no room for more sounds.")
        return []

    def folder_page(a):
        """The page file a folder key opens (None if it isn't in this profile)."""
        pid = str((a.get("Settings") or {}).get("ProfileUUID", "")).lower()
        return next((p for p in st["pages"] if p.parent.name.lower() == pid), None)

    def folder_names():
        """Names of the folder keys on this page, which new folders must not repeat."""
        return {sd_title(b) for b in keys_now().values() if b and b.get("UUID") == FOLDER}

    def add_folders(chunks, spots):
        """New folders (from sd_folders) onto these keys of this page, their pages into the unsent edits."""
        for spot, (key, pid, pg) in zip(spots, chunks):
            edits[profs[prof_v.get()][0] / "Profiles" / pid.upper() / "manifest.json"] = pg
            kp_edit()[spot] = key
        return spots[:len(chunks)]

    def inside(pairs, seen=None):
        """[(keypad, key)] with each folder key swapped for every sound key inside it (folders in folders too).
        Loads those pages into the edits, so an undo covers them."""
        seen = set() if seen is None else seen
        out = []
        for kp, k in pairs:
            a = kp[k]
            if a.get("UUID") != FOLDER:
                out.append((kp, k))
                continue
            p = folder_page(a)
            if p is None or p in seen:
                continue
            seen.add(p)
            if p not in edits:
                edits[p] = disk(p) or {}
            # read-only lookup: sd_keypad() would add an empty keypad to a bare page and make it look edited
            sub = next((c for c in edits[p].get("Controllers") or [] if c.get("Type") == "Keypad"), {}).get(
                "Actions") or {}
            out += inside([(sub, x) for x, b in sub.items() if b and (sd_sounds(b) or b.get("UUID") == FOLDER)],
                          seen)
        return out

    def fill_page(target, start, folder, where):
        """Sounds onto a page (this one, or a folder key's), one key each, on the free keys from `start` in order."""
        files = ui_pick_sounds(page, f"{'A folder of sounds' if folder else 'Sounds'} for {where}", folder)
        if not files:
            return
        cols, rows = dev_grid()
        if target == st["page"]:
            cols, rows = size()
        kp = sd_keypad(copy.deepcopy(page_json(target)))
        files = fit(files, len(files) - len(sd_fill(kp, files, cols, rows, start)), where)
        got = ui_new_key_dialog(page, files, ("One key per sound",)) if files else None
        if not got:
            return
        before = snap()
        if target not in edits:
            edits[target] = disk(target) or {}
        sd_fill(sd_keypad(edits[target]), got[2], cols, rows, start)
        commit(before, f"Added {len(files)} sound key(s) to {where}, in order")

    def fill_folder(pos, folder=False):
        """Sounds into a folder key's page, one key each in order; what doesn't fit carries over into new folders
        (title 2, title 3...) just beside it, or on the next free keys of this page."""
        a = keys_now()[pos]
        title = sd_title(a).replace("\n", " ").strip() or "Sounds"
        target = folder_page(a)
        if target is None:
            return status.config(text="That folder's page isn't in this profile.")
        files = ui_pick_sounds(page, f"{'A folder of sounds' if folder else 'Sounds'} for folder '{title}'", folder)
        if not files:
            return
        cols, rows = dev_grid()
        room = len(sd_free(sd_keypad(copy.deepcopy(page_json(target))), cols, rows))
        spots = sd_beside(keys_now(), pos, *size())
        files = fit(files, room + max(0, cols * rows - 1) * len(spots), f"Folder '{title}' and the free keys beside it")
        got = ui_new_key_dialog(page, files, ("One key per sound",)) if files else None
        if not got:
            return
        before = snap()
        if target not in edits:
            edits[target] = disk(target) or {}
        rest = sd_fill(sd_keypad(edits[target]), got[2], cols, rows)
        made = add_folders(sd_folders(title, rest, cols, rows, 2, folder_names()), spots) if rest else []
        st["sel"] = [pos] + made
        commit(before, f"Added {len(files)} sound(s) to folder '{title}'" + (
            f"; {len(rest)} carried over into {len(made)} new folder(s) at key(s) "
            f"{', '.join(map(pos_label, made))}" if made else ""))

    def import_sounds(pos=None):
        """Open the Import to folders tab on this profile and page, with this key picked first."""
        if hooks.get("import"):
            hooks["import"](prof_v.get(), st["page"], pos)

    def folder_per_subfolder(pos):
        """Mass import from a folder of folders: a Stream Deck folder per subfolder (and one for sounds loose in the
        picked folder), named after it; full ones carry over into "<name> 2"... Placed from this key, each one
        beside the last, or on the next free keys."""
        d = filedialog.askdirectory(parent=page, title="A folder of sound folders - one Stream Deck folder each")
        groups = sound_folders(d) if d else []
        if d and not groups:
            return messagebox.showinfo("Import", "No sound files in that folder or its subfolders.")
        cols, rows = dev_grid()
        if not groups:
            return
        if cols * rows < 2:
            return messagebox.showinfo("Import", "This deck has no room in a folder beside its Parent Folder key.")
        cap = cols * rows - 1
        spots = [pos] + sd_beside({**keys_now(), pos: True}, pos, *size())
        need = sum(-(-len(fs) // cap) for _, fs in groups)
        if need > len(spots) and not messagebox.askyesno(
                "Not enough keys", f"These {sum(len(fs) for _, fs in groups)} sounds need {need} folders ({cap} "
                f"sounds each); this page has room for {len(spots)}.\nMake the first {len(spots)}?"):
            return
        got = ui_new_key_dialog(page, [f for _, fs in groups for f in fs], ("Folder per subfolder",))
        if not got:
            return
        plays, taken, chunks = list(got[2]), folder_names(), []
        for name, fs in groups:
            mine, plays = plays[:len(fs)], plays[len(fs):]
            chunks += sd_folders(clean_name(name), mine, cols, rows, taken=taken)
            taken |= {sd_title(k) for k, _, _ in chunks}
        before = snap()
        made = add_folders(chunks, spots)
        placed = sum(1 for _, _, pg in chunks[:len(made)] for a in sd_keypad(pg).values() if a["UUID"] == SD_PLAY)
        left = len(got[2]) - placed
        st["sel"] = made
        commit(before, f"{len(made)} new folder(s), {placed} sound(s), at key(s) {', '.join(map(pos_label, made))}"
                       + (f"; {left} sound(s) didn't fit on this page and weren't added" if left else ""))

    def new_folder(pos, folder=False):
        """New folder keys from here, as many as the sounds need: the first on this key, the rest just beside it (or
        on the next free keys). Each page: the Parent Folder key, then one key per sound in order."""
        files = ui_pick_sounds(page, f"{'A folder of sounds' if folder else 'Sounds'} for new folder(s) at key "
                                     f"{pos_label(pos)}", folder)
        if not files:
            return
        cols, rows = dev_grid()
        if cols * rows < 2:
            return messagebox.showinfo("New folder", "This deck has no room in a folder beside its Parent Folder key.")
        spots = [pos] + sd_beside({**keys_now(), pos: True}, pos, *size())
        files = fit(files, (cols * rows - 1) * len(spots), f"This page ({cols * rows - 1} sounds per folder)")
        got = ui_new_key_dialog(page, files, ("Folder",)) if files else None
        if not got:
            return
        before = snap()
        chunks = sd_folders(got[1].strip() or "Sounds", got[2], cols, rows, taken=folder_names())
        made = add_folders(chunks, spots)
        st["sel"] = made
        commit(before, f"{len(made)} new folder(s) '{sd_title(chunks[0][0])}' at key(s) "
                       f"{', '.join(map(pos_label, made))} with "
                       f"{len(files)} sound(s) in order - double-click one to open it")

    def pos_label(pos):
        c, r_ = map(int, pos.split(","))
        return f"{c + 1},{r_ + 1}"

    def drop(src, dst):
        before = snap()
        sd_move(kp_edit(), src, dst)
        st["sel"] = [dst]
        commit(before, f"Moved key {pos_label(src)} to {pos_label(dst)} (anything there swapped places)")

    def copy_key():
        a = next((keys_now()[k] for k in st["sel"] if keys_now().get(k)), None)
        if a:
            hist["clip"] = copy.deepcopy(a)
            hist["clip_dirs"] = {}
            hist["clip_pages"] = folder_tree(a, {}, hist["clip_dirs"])  # a folder key takes what's inside it along
            hist["clip_src"] = st["page"].parent  # where its icons are
            status.config(text=f"Copied '{sd_title(a).replace(chr(10), ' ') or sd_kind(a)}'. Select a key "
                               "(any page or profile) and paste with Ctrl+V or right-click.")

    def folder_tree(a, out, dirs=None):
        """{page id: page json} copies of every page a folder key leads to, folders in folders too; dirs collects
        {page id: its folder} (for the icons)."""
        p = folder_page(a) if a.get("UUID") == FOLDER else None
        if p is not None and p.parent.name.lower() not in out:
            out[p.parent.name.lower()] = pg = copy.deepcopy(page_json(p))
            if dirs is not None:
                dirs[p.parent.name.lower()] = p.parent
            for c in pg.get("Controllers") or []:
                for b in (c.get("Actions") or {}).values():
                    if b:
                        folder_tree(b, out, dirs)
        return out

    def icons(src_dir, dst_dir, obj):
        """Queue the icon files obj shows, from its page folder to the new one (written with the next send)."""
        if src_dir and Path(src_dir) != Path(dst_dir):
            for rel in sd_images(obj):
                f = Path(src_dir) / rel
                if f.is_file():
                    blobs[Path(dst_dir) / rel] = f.read_bytes()

    def paste_key(pos=None):
        if not hist["clip"] or not st["page"]:
            return
        pos = pos or (st["sel"][0] if len(st["sel"]) == 1 else next(iter(sd_free(keys_now(), *size())), None))
        if not pos:
            return messagebox.showinfo("Paste", "No free key on this page; select the key to paste onto.")
        if keys_now().get(pos) and not messagebox.askyesno("Paste", f"Replace key {pos_label(pos)}?"):
            return
        before = snap()
        act = sd_renew(copy.deepcopy(hist["clip"]))
        ids = {}
        pages_ = sd_clone_folders(act, hist.get("clip_pages") or {}, ids=ids)  # the folder's own copy, here
        icons(hist.get("clip_src"), st["page"].parent, act)
        for pid, pg in pages_.items():
            dst = profs[prof_v.get()][0] / "Profiles" / pid.upper() / "manifest.json"
            edits[dst] = pg
            icons((hist.get("clip_dirs") or {}).get(ids.get(pid)), dst.parent, pg)
        kp_edit()[pos] = act
        st["sel"] = [pos]
        commit(before, f"Pasted onto key {pos_label(pos)}" + (
            f" with its own copy of {len(pages_)} folder page(s)" if pages_ else ""))

    def delete_keys(keys):
        keys = [k for k in keys if keys_now().get(k)]
        if keys and messagebox.askyesno("Delete keys", f"Delete {len(keys)} key(s) from this page?"):
            before = snap()
            for k in keys:
                kp_edit().pop(k, None)
            st["sel"] = []
            commit(before, f"Deleted {len(keys)} key(s)")

    def preview(pos):
        for s in sd_sounds(keys_now().get(pos)):
            if Path(s["Settings"].get("path", "")).is_file():
                return os.startfile(s["Settings"]["path"])
        status.config(text="That key has no sound file that can be played.")

    def combine(kind):
        keys = [k for k in st["sel"] if keys_now().get(k)]
        before = snap()
        try:
            sd_combine(kp_edit(), keys, kind, "")
        except ValueError as e:
            edits.clear(), edits.update(before[0])
            return messagebox.showerror("Combine", str(e))
        st["sel"] = [keys[0]]
        commit(before, f"Combined {len(keys)} keys into a {kind}")

    def split(pos):
        before = snap()
        try:
            n = sd_split(kp_edit(), pos, *size())
        except ValueError as e:
            edits.clear(), edits.update(before[0])
            return messagebox.showerror("Split", str(e))
        commit(before, f"Split into {n} single sound keys")

    def stop_key(pos):
        before = snap()
        kp_edit()[pos] = sd_stop_key()
        commit(before, f"Added a Stop Audio key at {pos_label(pos)}")

    def key_menu(pos, e):
        if pos not in st["sel"]:
            st["sel"] = [pos]
            draw()
        a = keys_now().get(pos)
        multi_sel = [k for k in st["sel"] if keys_now().get(k) and sd_sounds(keys_now()[k])]
        many = [k for k in st["sel"] if keys_now().get(k)]
        if a and len(many) > 1:
            ui_menu(deck.frame, e, [(f"Edit {len(many)} keys together...   Ctrl+E", bulk_edit), None,
                                    ("Combine into a Random Action", (lambda: combine("Random Action"))
                                     if len(multi_sel) > 1 else None),
                                    ("Combine into a Multi Action", (lambda: combine("Multi Action"))
                                     if len(multi_sel) > 1 else None),
                                    ("Copy first key   Ctrl+C", copy_key), None,
                                    (f"Delete {len(many)} keys   Del", lambda: delete_keys(st["sel"]))])
            return
        if a:
            grows = a.get("UUID") == SD_PLAY or a.get("UUID") in kinds
            items = ([("Open folder", lambda: open_folder(pos)),
                      ("Add sound files into this folder...", lambda: fill_folder(pos)),
                      ("Add a folder of sounds into this folder...", lambda: fill_folder(pos, True)),
                      ("Same settings for every sound inside...", lambda: bulk_edit([pos])), None]
                     if a.get("UUID") == FOLDER else
                     [("Go back out of the folder", go_back), None] if a.get("UUID") == PARENT else []) + [
                     ("Edit key...", lambda: edit_key(pos)),
                     ("Add sound files to this key...", (lambda: add_to_key(pos)) if grows else None),
                     ("Add a folder of sounds to this key...", (lambda: add_to_key(pos, True)) if grows else None),
                     ("Preview sound", (lambda: preview(pos)) if sd_sounds(a) else None), None,
                     ("Copy key   Ctrl+C", copy_key), ("Paste here   Ctrl+V", (lambda: paste_key(pos))
                                                       if hist["clip"] else None), None,
                     ("Combine selected into a Random Action", (lambda: combine("Random Action"))
                      if len(multi_sel) > 1 else None),
                     ("Combine selected into a Multi Action", (lambda: combine("Multi Action"))
                      if len(multi_sel) > 1 else None),
                     ("Split into single keys", (lambda: split(pos)) if len(sd_sounds(a)) > 1 else None), None,
                     ("Delete key   Del", lambda: delete_keys(st["sel"]))]
        else:
            items = [("New sound key...", lambda: new_key(pos)),
                     ("Import sounds into folders (pick keys, any page)...", lambda: import_sounds(pos)),
                     ("New folder(s) of sounds from files...", lambda: new_folder(pos)),
                     ("New folder(s) of sounds from a folder...", lambda: new_folder(pos, True)),
                     ("New folders, one per subfolder (mass import)...", lambda: folder_per_subfolder(pos)), None,
                     ("Fill free keys from here with files...", lambda: fill_page(st["page"], pos, False,
                                                                                  "this page")),
                     ("Fill free keys from here with a folder...", lambda: fill_page(st["page"], pos, True,
                                                                                     "this page")), None,
                     ("Add 'Stop all audio' key here", lambda: stop_key(pos)),
                     ("Paste here   Ctrl+V", (lambda: paste_key(pos)) if hist["clip"] else None)]
        ui_menu(deck.frame, e, items)

    def edit_cell(e):
        item, col = details.identify_row(e.y), details.identify_column(e.x)
        if not item or not col:
            return
        name = dcols[int(col[1:]) - 1]
        kind, k, *idx = item.split("|")
        if kind == "e":
            return new_key(k)
        a = keys_now().get(k)
        s = sd_sounds(a)[int(idx[0])] if kind == "s" else None
        se = (s or {}).get("Settings", {})
        if name in ("key", "type"):
            return edit_key(k)

        def done(val, field=name):
            chosen = details.selection()
            rows = [r for r in chosen if r[0] in "ks"] if item in chosen else [item]  # every selected row
            try:
                vol = int(val) if field == "volume" else None
                assert vol is None or 0 <= vol <= 100
            except (ValueError, AssertionError):
                return messagebox.showerror("Volume", "Volume is a whole number from 0 to 100.")
            before = snap()
            for r in rows:
                rk, rkey, *ridx = r.split("|")
                live = kp_edit()[rkey]
                if field == "name":
                    if rk == "k" or live.get("UUID") == SD_PLAY:
                        if not live.get("States"):
                            live["States"] = [{}]
                        for x in live["States"]:
                            x["Title"] = val
                elif rk == "s":
                    snd = sd_sounds(live)[int(ridx[0])]
                    sd_set_sound([snd], **{"mode": {"mode": val}, "fade": {"fade": val}, "volume": {"volume": vol},
                                           "output": {"output": val}}[field])
            commit(before, f"Changed {field} on {len(rows)} row(s)")
        if name == "name" and (kind == "k" or a.get("UUID") == SD_PLAY):
            ui_cell_edit(details, item, col, sd_title(a), done)
        elif s is None:
            return
        elif name == "mode":
            ui_cell_edit(details, item, col, details.set(item, col), done, SD_MODES)
        elif name == "fade":
            ui_cell_edit(details, item, col, SD_FADES[se.get("fadeType", 0)] if se.get("fadeType", 0) < 4 else "",
                         done, SD_FADES)
        elif name == "volume":
            ui_cell_edit(details, item, col, str(se.get("volume", 100)), done)
        elif name == "output":
            ui_cell_edit(details, item, col, sd_out_name(se["outputType"]) if se.get("outputType") else SD_DEFAULT_OUT,
                         done, sd_output_choices(), True)
        elif name == "file":
            f = filedialog.askopenfilename(title="Sound file", initialdir=str(Path(se.get("path", "")).parent)
                                           if Path(se.get("path", "")).parent.is_dir() else None,
                                           filetypes=[("Audio", " ".join(f"*{x}" for x in AUDIO_EXT)),
                                                      ("All files", "*.*")])
            if f:
                before = snap()
                sd_sounds(kp_edit()[k])[int(idx[0])]["Settings"]["path"] = str(Path(f))
                commit(before, f"Changed the file on key {pos_label(k)}")
    ui_multi_rows(details, edit_cell)

    def targets_for(scope, into=False):
        """[(keypad, key)] the tools act on: the selection, every sound key on this page, or on every page.
        into = a selected folder key stands for every sound key inside it (the sound tools)."""
        if scope == SCOPES[0]:
            kp = kp_edit()
            pairs = [(kp, k) for k in st["sel"] if kp.get(k)]
            return inside(pairs) if into else pairs
        if scope == SCOPES[1]:
            kp = kp_edit()
            return [(kp, k) for k, a in kp.items() if a and sd_sounds(a)]
        out = []
        for _, p in st["named"]:
            if any(a and sd_sounds(a) for a in page_keys(p).values()):
                if p not in edits:
                    edits[p] = disk(p) or {}
                kp = sd_keypad(edits[p])
                out += [(kp, k) for k, a in kp.items() if a and sd_sounds(a)]
        return out

    def apply():
        if not st["page"]:
            return
        g, scope = goal_v.get(), scope_v.get()
        if g == goals[5] and scope != SCOPES[0]:
            return messagebox.showinfo("Arrange keys", "Arranging works on the selected keys of this page - set "
                                       "'Apply to' to 'Selected keys'.")
        if scope == SCOPES[0] and not any(keys_now().get(k) for k in st["sel"]) and not (
                g == goals[5] and o["arr"].get() == "stop"):
            return messagebox.showinfo("Select keys", "Click keys on the grid (Ctrl / Shift+click for several), use "
                                       "the Select buttons, or set 'Apply to' to a whole page or the profile.")
        # loads the pages first, so undo restores them too; names / arranging act on the selected keys themselves
        targets = targets_for(scope, into=g not in goals[4:6])
        before = snap()
        kp = kp_edit()
        sel = [k for k in st["sel"] if kp.get(k)]
        sounds = [s for kpx, k in targets for s in sd_sounds(kpx[k])]
        if not sounds and g in goals[:4]:
            edits.clear()
            edits.update(before[0])
            return messagebox.showinfo("No sounds", "There are no Play Audio actions there (e.g. only hotkey "
                                       "macros or empty folders), so there's nothing to change.")
        deep = sum(1 for kpx, _ in targets if kpx is not kp)
        where = {SCOPES[0]: f"{len(targets)} selected key(s)" + (f" ({deep} inside folders)" if deep else ""),
                 SCOPES[1]: f"{len(targets)} key(s) on this page",
                 SCOPES[2]: f"{len(targets)} key(s) across the profile"}[scope]
        keep = lambda x: None if x == "Keep" else x
        try:
            if g == goals[0]:
                mode, fade, secs, vol = SD_GOALS[o["goal"].get()]
                sd_set_sound(sounds, mode, fade, secs, vol)
                msg = f"{len(sounds)} sound(s) on {where} set up for: {o['goal'].get()}"
            elif g == goals[1]:
                sd_set_sound(sounds, keep(o["mode"].get()), keep(o["fade"].get()), keep(o["fade_len"].get()))
                msg = f"Playback changed on {len(sounds)} sound(s), {where}"
            elif g == goals[2]:
                how = o["vol_how"].get()
                if how in ("match", "tune", "check"):
                    heard = {}
                    paths = {s.get("Settings", {}).get("path", "") for s in sounds}
                    for i, p in enumerate(sorted(p for p in paths if Path(p).is_file()), 1):
                        status.config(text=f"Listening {i}/{len(paths)}: {Path(p).name}...")
                        page.update()
                        try:
                            heard[p] = sd_listen(p)
                        except Exception:
                            pass
                    rows = sd_level_rows(sounds, heard, o["tune"].get())
                    if how == "check":
                        names = {id(s): sd_title(kpx[k]).replace("\n", " ") or k for kpx, k in targets
                                 for s in sd_sounds(kpx[k])}
                        status.config(text=f"Listened to {len(heard)} file(s) on {where}.")
                        if not ui_level_report(page, rows, names, o["tune"].get()):
                            raise LookupError  # only looked: nothing changed
                        how = "tune"
                    if how == "match":
                        levels = {p: h["level"] for p, h in heard.items() if h["level"] is not None}
                        msg = f"Loudness matched on {sd_match_loudness(sounds, levels)} sound(s), {where}"
                    else:
                        for r in rows:
                            if r["new"] is not None:
                                r["s"]["Settings"]["volume"] = r["new"]
                        n = lambda test: sum(1 for r in rows if test(r))
                        msg = (f"Tuned {n(lambda r: r['new'] is not None)} sound(s) to {o['tune'].get()}, {where}; "
                               f"{n(lambda r: r['verdict'] == 'in range')} already in range"
                               + (f"; {k} too quiet even at full volume" if (k := n(
                                   lambda r: r['verdict'].startswith('too quiet even'))) else "")
                               + (f"; {k} missing or silent" if (k := n(lambda r: r['now'] is None)) else ""))
                else:
                    sd_set_sound(sounds, volume=o["vol"].get() if how == "set" else None,
                                 step=int(o["step"].get()) if how == "step" else None,
                                 scale=int(o["scale"].get()) if how == "scale" else None)
                    msg = f"Volume changed on {len(sounds)} sound(s), {where}"
            elif g == goals[3]:
                sd_set_sound(sounds, output=o["output"].get())
                msg = (f"Output set to {sd_out_name(sd_out(o['output'].get()))} on {len(sounds)} "
                       f"sound(s), {where}")
            elif g == goals[4]:
                style = {}
                if o["show"].get() != "Keep":
                    style["ShowTitle"] = o["show"].get() == "Show"
                if o["size"].get() != "Keep":
                    style["FontSize"] = int(o["size"].get())
                if o["align"].get() != "Keep":
                    style["TitleAlignment"] = o["align"].get()
                if o["color"].get():
                    style["TitleColor"] = o["color"].get()
                for n, (kpx, k) in enumerate(targets, 1):
                    sd_label(kpx[k], o["source"].get(), o["prefix"].get(), o["suffix"].get(), o["find"].get(),
                             o["repl"].get(), style, n)
                msg = f"Renamed / restyled {where}"
            elif g == goals[5]:
                how = o["arr"].get()
                if how == "move":
                    dst = slot(o["slot"].get())
                    sd_move(kp, sel[0], dst)
                    st["sel"] = [dst]
                    msg = "Key moved (anything already there swapped places)"
                elif how == "combine":
                    sd_combine(kp, sel, o["ckind"].get(), o["ctitle"].get().strip())
                    st["sel"] = [sel[0]]
                    msg = f"{len(sounds)} sound(s) combined into a {o['ckind'].get()}"
                elif how == "split":
                    n = sum(sd_split(kp, k, *size()) for k in sel if len(sd_sounds(kp.get(k))) > 1)
                    msg = f"Split into {n} single sound keys"
                elif how == "stop":
                    k = slot(o["slot"].get())
                    if kp.get(k) and not messagebox.askyesno("Replace key", "That key is in use. Replace it?"):
                        raise LookupError
                    kp[k] = sd_stop_key()
                    msg = "Added a Stop Audio key"
                else:
                    if not messagebox.askyesno("Delete keys", f"Delete {len(sel)} key(s) from this page?"):
                        raise LookupError
                    for k in sel:
                        kp.pop(k, None)
                    st["sel"] = []
                    msg = f"Deleted {len(sel)} key(s)"
            else:
                if not Path(o["folder"].get()).is_dir():
                    raise ValueError("Pick the folder that holds your sounds.")
                status.config(text="Searching...")
                page.update()
                fixed, still = sd_relink(sounds, o["folder"].get())
                msg = f"Fixed {fixed} missing sound(s) on {where}; {still} still missing"
        except (ValueError, LookupError) as e:
            edits.clear()
            edits.update(before[0])  # nothing half-done
            st["sel"] = before[1]
            draw()
            if isinstance(e, ValueError):
                messagebox.showerror("Can't do that", str(e))
            return
        commit(before, msg)

    def bulk_edit(keys=None):
        """Several keys in one window (one key opens the normal Edit key window)."""
        keys = [k for k in (keys or st["sel"]) if keys_now().get(k)]
        if not keys:
            return messagebox.showinfo("Edit keys", "Select the keys to edit first (Ctrl / Shift+click for several).")
        if len(keys) == 1 and keys_now()[keys[0]].get("UUID") != FOLDER:
            return edit_key(keys[0])
        kp = kp_edit()
        acts = [kp[k] for k in keys]
        inner = [kpx[k] for kpx, k in inside([(kp, k) for k in keys]) if kpx is not kp]  # keys inside folders
        ch = ui_bulk_dialog(page, acts + inner)
        if not ch:
            return
        before = snap()
        sd_set_sound([s for a in acts + inner for s in sd_sounds(a)], ch.get("mode"), ch.get("fade"),
                     ch.get("fade_len"), ch.get("volume"), output=ch.get("output"))
        for a in acts:
            if "title" in ch or ch.get("style"):
                if not a.get("States"):
                    a["States"] = [{}]
                for x in a["States"]:
                    if "title" in ch:
                        x["Title"] = ch["title"]
                    x.update(ch.get("style") or {})
        commit(before, f"Edited {len(keys)} key(s) together" + (
            f", and the sounds on {len(inner)} key(s) inside the folder(s)" if inner else ""))

    def revert():
        if edits:
            before = snap()
            edits.clear()
            st["sel"] = []
            commit(before, "All unsaved changes thrown away")

    def save(auto=False):
        """Send every changed page to Stream Deck: close it (it rewrites its profiles on exit and would undo
        ours), back up, write, read back to check, reopen. auto = no question first (auto-send / app closing)."""
        st["job"] = None
        if st.get("saving"):  # a send is running; go again when it's done
            st["again"] = True
            return
        todo = copy.deepcopy(pending())  # a snapshot: editing can carry on while it's written
        icons = {f: b for f, b in blobs.items()  # only for pages that exist or are being sent (not undone ones)
                 if f.parents[1] / "manifest.json" in edits or (f.parents[1] / "manifest.json").is_file()}
        if not todo and not icons:
            return status.config(text="Nothing to send - Stream Deck already has every change.")
        if not auto and sd_running() and not messagebox.askyesno(
                "Close Stream Deck", "Stream Deck must close for a moment while the changes are written "
                "(it rewrites its profiles when it exits).\nClose it now and reopen it after?"):
            return
        st["saving"] = True
        save_btn.state(["disabled"])
        status.config(text=f"Sending {len(todo)} page(s) to Stream Deck - it closes and reopens for a few seconds; "
                           "you can keep working...")

        def finish(res):
            st["saving"] = False
            save_btn.state(["!disabled"])
            if isinstance(res, Exception):
                status.config(text=f"Sending failed: {res}")
                messagebox.showerror("Send to Stream Deck", str(res))
            else:  # edits stay as they are (now equal to the files), so undo keeps working across sends
                for f in icons:
                    blobs.pop(f, None)
                status.config(text=f"Sent {len(todo)} page(s) to Stream Deck and checked they were written; "
                                   f"Stream Deck reopened. Backup: {res}")
            refresh_lists()
            draw()
            if st.pop("again", False) or (auto_v.get() and pending()):
                changed()
        ui_background(page, lambda: sd_push({**todo, **icons}, {p.parents[2] for p in todo}), finish)

    apply_btn.config(command=apply)
    save_btn.config(command=save)
    tbtn["undo"].config(command=lambda: restore("undo", "redo", "Undone."))
    tbtn["redo"].config(command=lambda: restore("redo", "undo", "Redone."))
    tbtn["revert"].config(command=revert)
    ui_keys(page, {"<Control-z>": lambda: restore("undo", "redo", "Undone."),
                   "<Control-y>": lambda: restore("redo", "undo", "Redone."), "<Control-s>": save,
                   "<Control-c>": copy_key, "<Control-v>": paste_key, "<Delete>": lambda: delete_keys(st["sel"]),
                   "<Control-a>": lambda: select(bool), "<Escape>": lambda: select(lambda a: False),
                   "<Prior>": lambda: go_page((st["idx"] or 0) - 1), "<Next>": lambda: go_page((st["idx"] or 0) + 1),
                   "<Alt-Left>": go_back, "<Control-e>": lambda: bulk_edit(), "<Return>": lambda: bulk_edit()})
    scope_v.trace_add("write", lambda *_: draw())
    ptv.bind("<<TreeviewSelect>>", lambda e: ptv.selection() and go_page(int(ptv.selection()[0])))
    prof_v.trace_add("write", on_prof)
    multi_v.trace_add("write", on_multi)
    on_prof()
    def change(fn, msg):
        """For the other tabs: run fn(edit) as one undoable change, then show it. edit(page file) -> its json to
        change (loaded on first use); edit(page file, json) puts a new page. Raises (and undoes) on error."""
        before = snap()

        def edit(p, new=None):
            if new is not None:
                edits[p] = new
            elif p not in edits:
                edits[p] = disk(p) or {}
            return edits[p]
        try:
            fn(edit)
        except Exception:
            edits.clear()
            edits.update(before[0])
            raise
        commit(before, msg)

    def put_files(files):
        """Sounds picked elsewhere (From Channel Mirror...) onto the selected key: a new key, or added to it."""
        files = [f for f in map(Path, files) if f.suffix.lower() in AUDIO_EXT]
        if not files:
            return
        if len(st["sel"]) != 1:
            return status.config(text="Click one key first, then pick its sounds.")
        pos = st["sel"][0]
        a = keys_now().get(pos)
        if a and sd_sounds(a):
            kind = ui_grow_kind(page) if a.get("UUID") == SD_PLAY else "Random Action"
            if kind:
                before = snap()
                kp_edit()[pos] = sd_add_sounds(kp_edit()[pos], sd_plays_like(files, sd_sounds(a)[0]), kind)
                commit(before, f"Added {len(files)} sound(s) to key {pos_label(pos)}")
        elif not a:
            got = ui_new_key_dialog(page, files)
            if got:
                kind, name, plays = got
                before = snap()
                kp_edit()[pos] = plays[0] if kind == "Single sound" else sd_wrap(kind, name, plays)
                commit(before, f"New sound key at {pos_label(pos)}")
        else:
            status.config(text="That key isn't a sound key - pick an empty key or a sound key.")

    def profile_pages(label):
        folder, m = profs[label]
        return sd_pages(folder, m, {p: d for p, d in edits.items() if p.parents[2] == folder})

    return {"pending": pending, "save": save, "saving": lambda: bool(st.get("saving")),
            # shared with the Import to folders and Key mover tabs (one set of unsent edits, one undo)
            "profiles": lambda: list(labels_), "pages": profile_pages, "keys": page_keys, "change": change,
            "grid": lambda label: grids.get(profs[label][1].get("Device", {}).get("UUID", ""), (5, 3)),
            "folder": lambda label: profs[label][0], "icons": icons, "page": page_json,
            "undo": lambda: restore("undo", "redo", "Undone."), "listeners": listeners, "hooks": hooks,
            "current": lambda: (prof_v.get(), st["page"]), "status": lambda: status.cget("text"),
            "put_files": put_files}
