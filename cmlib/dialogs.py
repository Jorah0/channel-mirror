"""Key dialogs: new key, edit key, bulk edit."""
import os
from pathlib import Path
from .core import AUDIO_EXT
from .mirror import clean_name
from .deck import (
    SD_DEFAULT_OUT,
    SD_FADES,
    SD_KINDS,
    SD_MODES,
    sd_add_sounds,
    sd_kind,
    sd_out_name,
    sd_output_choices,
    sd_play,
    sd_plays_like,
    sd_set_sound,
    sd_sounds,
    sd_title,
)
from .ui import UI, UI_SWATCH, ui_pick_sounds, ui_play_choice, ui_sound_form


def ui_grow_kind(parent):
    """Asked before a single-sound key takes more sounds: "Random Action", "Multi Action", or None (cancelled)."""
    from tkinter import messagebox
    ans = messagebox.askyesnocancel("Add sounds", "This key plays one sound. Turn it into a Random Action (one random "
                                    "sound per press)?\n\nNo = Multi Action (all play together)", parent=parent)
    return None if ans is None else "Random Action" if ans else "Multi Action"


def ui_new_key_dialog(parent, files, kinds=None):
    """Make keys from files: pick what they become and the settings every sound gets. kinds = the choices
    (default: Single sound for one file, Random / Multi Action for several; also "Folder" and "One key per sound").
    Returns (kind, name, [Play Audio actions]), or None when cancelled."""
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(parent)
    win.title(f"New key - {len(files)} sound(s)")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="\n".join(Path(f).name for f in files[:8]) + (f"\n... and {len(files) - 8} more"
              if len(files) > 8 else ""), style="Hint.TLabel").pack(anchor="w")
    kinds = kinds or (("Single sound",) if len(files) == 1 else ("Random Action", "Multi Action"))
    hints = {"Single sound": "plays it", "Random Action": "one random sound per press",
             "Multi Action": "all play together", "Folder": "a folder key; inside, one key per sound in this order",
             "One key per sound": "on the free keys, in this order",
             "Folder per subfolder": "named after it; inside, one key per sound in name order"}
    kind = tk.StringVar(value=kinds[0])
    kf = ttk.Frame(body)
    kf.pack(fill="x", pady=(10, 0))
    for k in kinds:
        ttk.Radiobutton(kf, text=f"{k} ({hints[k]})", variable=kind, value=k).pack(anchor="w")
    name = tk.StringVar(value=clean_name(Path(files[0]).stem if kinds == ("Single sound",) else Path(files[0]).parent.name))
    if not {"One key per sound", "Folder per subfolder"} & set(kinds):  # named after their files / folders
        ttk.Label(body, text="NAME", style="Field.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Entry(body, textvariable=name, width=24).pack(anchor="w")
    v = {"mode": tk.StringVar(value=SD_MODES[0]), "fade": tk.StringVar(value=SD_FADES[0]),
         "fade_len": tk.StringVar(value="1"), "volume": tk.IntVar(value=100),
         "output": tk.StringVar(value=SD_DEFAULT_OUT)}
    ui_play_choice(body, v["mode"]).pack(anchor="w", pady=(12, 0))
    ttk.Label(body, text="EVERY SOUND GETS", style="Field.TLabel").pack(anchor="w", pady=(10, 0))
    ui_sound_form(body, v).pack(fill="x", pady=4)
    result = [None]

    def ok():
        single = kind.get() == "Single sound"
        plays = [sd_play(Path(f), name.get() if single else clean_name(Path(f).stem), v["mode"].get(), v["fade"].get(),
                         v["fade_len"].get(), int(v["volume"].get()), v["output"].get()) for f in files]
        result[0] = (kind.get(), name.get(), plays)
        win.destroy()
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(14, 0))
    ttk.Button(bar, text="Create", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.grab_set()
    win.wait_window()
    return result[0]


def ui_key_dialog(parent, action):
    """Edit one key in its own window: name and look, plus every sound on it (file, playback, fade, volume,
    output). Sounds can be added to a key (a single sound becomes a Random / Multi Action) or removed from one.
    Returns the edited copy, or None when cancelled."""
    import copy
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk
    kinds = {u for u in SD_KINDS.values() if u}
    work, result = [copy.deepcopy(action)], [None]
    states = action.get("States") or [{}]
    st0 = states[min(int(action.get("State") or 0), len(states) - 1)]
    win = tk.Toplevel(parent)
    win.title(f"Edit key - {sd_title(action).replace(chr(10), ' ') or sd_kind(action)}")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    kind_lbl = ttk.Label(body, style="Hint.TLabel")
    kind_lbl.pack(anchor="w", pady=(0, 8))

    look = ttk.LabelFrame(body, text="Name and look")
    look.pack(fill="x")
    ttk.Label(look, text="NAME (Enter = new line)", style="Field.TLabel").grid(row=0, column=0, sticky="w")
    name = tk.Text(look, height=3, width=24, relief="flat", bd=0, highlightthickness=1, wrap="none", undo=True,
                   highlightbackground=UI["border"], highlightcolor=UI["accent"])
    name.insert("1.0", st0.get("Title") or "")
    name.grid(row=1, column=0, rowspan=3, sticky="nw", padx=(0, 16))
    show = tk.BooleanVar(value=st0.get("ShowTitle", True))
    size = tk.StringVar(value=str(st0.get("FontSize", "")))
    align = tk.StringVar(value=st0.get("TitleAlignment") or "bottom")
    color = tk.StringVar(value=st0.get("TitleColor") or "")
    ttk.Checkbutton(look, text="Show name on the key", variable=show).grid(row=1, column=1, columnspan=3, sticky="w")
    for col, (label, w) in enumerate((
            ("FONT SIZE", ttk.Combobox(look, textvariable=size, values=("", "7", "8", "9", "10", "11", "12", "14",
                                                                        "16", "18", "20", "24"), width=5)),
            ("POSITION", ttk.Combobox(look, textvariable=align, values=("top", "middle", "bottom"), state="readonly",
                                      width=8))), 1):
        ttk.Label(look, text=label, style="Field.TLabel").grid(row=2, column=col, sticky="w", padx=(0, 12))
        w.grid(row=3, column=col, sticky="w", padx=(0, 12))
    ttk.Label(look, text="COLOUR", style="Field.TLabel").grid(row=2, column=3, sticky="w")
    cbox = ttk.Frame(look)
    cbox.grid(row=3, column=3, sticky="w")
    swatch = tk.Label(cbox, width=3, bg=color.get() or UI["panel"], **UI_SWATCH)
    swatch.pack(side="left", padx=(0, 6))

    def pick_color():
        c = colorchooser.askcolor(color.get() or "#ffffff", parent=win, title="Name colour")[1]
        if c:
            color.set(c)
            swatch.config(bg=c)
    ttk.Button(cbox, text="Pick...", style="Tool.TButton", command=pick_color).pack(side="left")

    has_sounds = bool(sd_sounds(action)) or action.get("UUID") in kinds
    if has_sounds:
        sf = ttk.LabelFrame(body, text="Sounds on this key")
        sf.pack(fill="both", expand=True, pady=(12, 0))
        cols = ("file", "mode", "fade", "volume", "output")
        tv = ttk.Treeview(sf, columns=cols, show="headings", height=6, selectmode="browse")
        for c, h, w in zip(cols, ("File", "Action", "Fade", "Volume", "Output"), (240, 110, 130, 60, 200)):
            tv.heading(c, text=h)
            tv.column(c, width=w, stretch=c in ("file", "output"))
        tv.pack(fill="both", expand=True)
        v = {"path": tk.StringVar(), "mode": tk.StringVar(), "fade": tk.StringVar(), "fade_len": tk.StringVar(),
             "volume": tk.IntVar(value=100), "output": tk.StringVar()}
        fr = ttk.Frame(sf)
        fr.pack(fill="x", pady=(10, 4))
        ttk.Label(fr, text="FILE", style="Field.TLabel").pack(anchor="w")
        ttk.Entry(fr, textvariable=v["path"], width=70).pack(side="left", fill="x", expand=True)
        ui_sound_form(sf, v).pack(fill="x", pady=4)
        btns = ttk.Frame(sf)
        btns.pack(fill="x", pady=(6, 0))
        loading, cur = [False], [None]
        pick = lambda t, i: t[i] if isinstance(i, int) and 0 <= i < len(t) else t[0]

        def row_of(s):
            se = s.get("Settings", {})
            ok = Path(se.get("path", "")).is_file()
            return (Path(se.get("path", "")).name + ("" if ok else "  (missing)"), pick(SD_MODES, se.get("actionType")),
                    pick(SD_FADES, se.get("fadeType")) + (f" {se.get('fadeLen', 1)}s" if se.get("fadeType") else ""),
                    se.get("volume", 100), sd_out_name(se.get("outputType")))

        def fill(select=0):
            tv.delete(*tv.get_children())
            for i, s in enumerate(sd_sounds(work[0])):
                tv.insert("", "end", iid=str(i), values=row_of(s))
            kind_lbl.config(text=f"Type: {sd_kind(work[0])}   -   select a sound to change it; changes apply as you "
                                 "make them and are kept when you press OK")
            if tv.get_children():
                tv.selection_set(str(min(select, len(tv.get_children()) - 1)))

        def on_sel(_=None):
            sel = tv.selection()
            if not sel:
                return
            cur[0] = sd_sounds(work[0])[int(sel[0])]
            se = cur[0].setdefault("Settings", {})
            loading[0] = True
            v["path"].set(se.get("path", ""))
            v["mode"].set(pick(SD_MODES, se.get("actionType")))
            v["fade"].set(pick(SD_FADES, se.get("fadeType")))
            v["fade_len"].set(str(se.get("fadeLen", 1)))
            v["volume"].set(int(se.get("volume", 100)))
            v["output"].set(sd_out_name(se["outputType"]) if se.get("outputType") else SD_DEFAULT_OUT)
            loading[0] = False

        def on_var(*_):
            if loading[0] or not cur[0]:
                return
            try:
                vol = int(v["volume"].get())
            except (tk.TclError, ValueError):
                return
            cur[0].setdefault("Settings", {})["path"] = v["path"].get().strip()
            sd_set_sound([cur[0]], v["mode"].get(), v["fade"].get(), v["fade_len"].get(), vol, output=v["output"].get())
            if tv.selection():
                tv.item(tv.selection()[0], values=row_of(cur[0]))
        for var in v.values():
            var.trace_add("write", on_var)
        tv.bind("<<TreeviewSelect>>", on_sel)

        def inner():
            a = work[0]
            if a.get("UUID") in kinds:
                if not a.get("Actions"):
                    a["Actions"] = [{"Actions": []}]
                return a["Actions"][0].setdefault("Actions", [])
            return None

        def add_sounds(folder=False):
            files = ui_pick_sounds(win, "Add every sound in a folder to this key" if folder else
                                   "Add sounds to this key", folder)
            if not files:
                return
            kind = ui_grow_kind(win) if inner() is None else "Random Action"
            if kind:  # new sounds copy the selected sound's playback settings
                work[0] = sd_add_sounds(work[0], sd_plays_like(files, cur[0]), kind)
                fill(len(sd_sounds(work[0])) - 1)

        def reorder(step):
            lst, s = inner(), cur[0]
            i = next((n for n, x in enumerate(lst or []) if x is s), None)
            if i is None:
                return
            if step == 0:
                if len(lst) < 2:
                    return messagebox.showinfo("Remove", "A key needs at least one sound.", parent=win)
                del lst[i]
                return fill(i)
            j = i + step
            if 0 <= j < len(lst):
                lst[i], lst[j] = lst[j], lst[i]
                fill(j)

        def preview():
            if cur[0] and Path(cur[0]["Settings"].get("path", "")).is_file():
                os.startfile(cur[0]["Settings"]["path"])

        def browse():
            f = filedialog.askopenfilename(parent=win, title="Sound file", filetypes=[
                ("Audio", " ".join(f"*{e}" for e in AUDIO_EXT)), ("All files", "*.*")])
            if f:
                v["path"].set(str(Path(f)))
        ttk.Button(fr, text="Browse...", style="Tool.TButton", command=browse).pack(side="left", padx=(6, 0))
        ttk.Button(fr, text="Preview", style="Tool.TButton", command=preview).pack(side="left", padx=(6, 0))
        def apply_all():
            if not cur[0]:
                return
            sd_set_sound(sd_sounds(work[0]), v["mode"].get(), v["fade"].get(), v["fade_len"].get(),
                         int(v["volume"].get()), output=v["output"].get())
            fill(int(tv.selection()[0]) if tv.selection() else 0)
        for text, cmd in (("Add sounds...", add_sounds), ("Add folder...", lambda: add_sounds(True)),
                          ("Apply to all sounds", apply_all),
                          ("Remove sound", lambda: reorder(0)),
                          ("Move up", lambda: reorder(-1)), ("Move down", lambda: reorder(1))):
            ttk.Button(btns, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 6))
        fill()
    else:
        kind_lbl.config(text=f"Type: {sd_kind(action)}   -   this key isn't a sound; its name and look can be edited")

    def ok():
        a = work[0]
        if not a.get("States"):
            a["States"] = [{}]
        for s in a["States"]:
            s["Title"] = name.get("1.0", "end-1c")
            if "ShowTitle" in s or show.get() != st0.get("ShowTitle", True):  # untouched defaults stay unwritten
                s["ShowTitle"] = show.get()
            if "TitleAlignment" in s or align.get() != (st0.get("TitleAlignment") or "bottom"):
                s["TitleAlignment"] = align.get()
            if size.get().strip().isdigit():
                s["FontSize"] = int(size.get())
            if color.get():
                s["TitleColor"] = color.get()
        result[0] = a
        win.destroy()
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(14, 0))
    ttk.Button(bar, text="OK", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.update_idletasks()
    p = parent.winfo_toplevel()
    win.geometry(f"+{p.winfo_rootx() + max(0, (p.winfo_width() - win.winfo_width()) // 2)}"
                 f"+{p.winfo_rooty() + max(0, (p.winfo_height() - win.winfo_height()) // 3)}")
    win.grab_set()
    win.wait_window()
    return result[0]


def ui_bulk_dialog(parent, actions):
    """Edit many keys at once. Each field starts on the value the keys share, or Keep when they differ; only
    fields moved off their starting value are applied. Returns the changes as a dict, or None when cancelled:
    title, mode, fade, fade_len, volume, output (sounds) and style (Stream Deck title fields)."""
    import tkinter as tk
    from tkinter import colorchooser, messagebox, ttk
    keep = "Keep (mixed)"
    sounds = [s for a in actions for s in sd_sounds(a)]
    se = [s.get("Settings", {}) for s in sounds]
    states = [(a.get("States") or [{}])[0] for a in actions]
    pick = lambda t, i: t[i] if isinstance(i, int) and 0 <= i < len(t) else t[0]
    same = lambda vals, other=keep: vals[0] if vals and all(x == vals[0] for x in vals) else other
    start = {"title": same([sd_title(a) for a in actions], ""),
             "show": same(["Show" if x.get("ShowTitle", True) else "Hide" for x in states]),
             "size": same([str(x.get("FontSize", "")) for x in states]) or keep,
             "align": same([x.get("TitleAlignment") or "bottom" for x in states]),
             "mode": same([pick(SD_MODES, x.get("actionType")) for x in se]),
             "fade": same([pick(SD_FADES, x.get("fadeType")) for x in se]),
             "fade_len": same([str(x.get("fadeLen", 1)) for x in se]),
             "volume": same([str(x.get("volume", 100)) for x in se]),
             "output": same([sd_out_name(x["outputType"]) if x.get("outputType") else SD_DEFAULT_OUT for x in se])}
    v = {k: tk.StringVar(value=val) for k, val in start.items()}
    color, result = tk.StringVar(), [None]
    win = tk.Toplevel(parent)
    win.title(f"Edit {len(actions)} keys together")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, style="Hint.TLabel", text=f"{len(actions)} keys, {len(sounds)} sounds. Fields showing "
              f"'{keep}' differ between the keys and are left alone unless you change them.").pack(anchor="w")

    def grid(frame, rows):
        for r, (label, w) in enumerate(rows):
            ttk.Label(frame, text=label, width=16).grid(row=r, column=0, sticky="w", pady=3)
            w.grid(row=r, column=1, sticky="w", pady=3)
    kf = ttk.LabelFrame(body, text="Keys")
    kf.pack(fill="x", pady=(10, 0))
    cf = ttk.Frame(kf)
    sw = tk.Label(cf, width=3, bg=UI["panel"], **UI_SWATCH)
    sw.pack(side="left", padx=(0, 6))

    def pick_color():
        c = colorchooser.askcolor("#ffffff", parent=win, title="Name colour")[1]
        if c:
            color.set(c)
            sw.config(bg=c)
    ttk.Button(cf, text="Pick...", style="Tool.TButton", command=pick_color).pack(side="left")
    combo = lambda frame, key, values, width=18, ro=True: ttk.Combobox(
        frame, textvariable=v[key], values=(keep,) + tuple(values), state="readonly" if ro else "normal", width=width)
    grid(kf, (("Name", ttk.Entry(kf, textvariable=v["title"], width=28)),
              ("Show name", combo(kf, "show", ("Show", "Hide"))),
              ("Font size", combo(kf, "size", ("7", "8", "9", "10", "11", "12", "14", "16", "18", "20", "24"))),
              ("Name position", combo(kf, "align", ("top", "middle", "bottom"))),
              ("Name colour", cf)))
    if start["title"] == "" and len({sd_title(a) for a in actions}) > 1:
        ttk.Label(kf, text="(names differ - leave blank to keep each key's own name)", style="Hint.TLabel").grid(
            row=0, column=2, sticky="w", padx=6)
    sf = ttk.LabelFrame(body, text="Sounds on these keys")
    sf.pack(fill="x", pady=(10, 0))
    if sounds:
        out = combo(sf, "output", (), 44, ro=False)
        out.config(postcommand=lambda: out.config(values=(keep,) + tuple(sd_output_choices())))
        grid(sf, (("Action", combo(sf, "mode", SD_MODES)), ("Fade", combo(sf, "fade", SD_FADES)),
                  ("Fade length (s)", combo(sf, "fade_len", ("1", "2", "3", "4", "5"), 14)),
                  ("Volume (0-100)", combo(sf, "volume", [str(n) for n in range(0, 101, 10)], 14, ro=False)),
                  ("Output device", out)))
    else:
        ttk.Label(sf, text="None of these keys plays a sound.", style="Hint.TLabel").pack(anchor="w")

    def ok():
        ch = {k: x.get().strip() for k, x in v.items()
              if x.get().strip() != start[k] and x.get().strip() != keep and (k != "title" or x.get().strip())}
        if "volume" in ch:
            try:
                ch["volume"] = int(ch["volume"])
                assert 0 <= ch["volume"] <= 100
            except (ValueError, AssertionError):
                return messagebox.showerror("Volume", "Volume is a whole number from 0 to 100.", parent=win)
        style = {}
        if "show" in ch:
            style["ShowTitle"] = ch.pop("show") == "Show"
        if "size" in ch:
            style["FontSize"] = int(ch.pop("size"))
        if "align" in ch:
            style["TitleAlignment"] = ch.pop("align")
        if color.get():
            style["TitleColor"] = color.get()
        if style:
            ch["style"] = style
        result[0] = ch
        win.destroy()
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(14, 0))
    ttk.Button(bar, text=f"Apply to {len(actions)} keys", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.bind("<Return>", lambda e: ok())
    win.update_idletasks()
    p = parent.winfo_toplevel()
    win.geometry(f"+{p.winfo_rootx() + max(0, (p.winfo_width() - win.winfo_width()) // 2)}"
                 f"+{p.winfo_rooty() + max(0, (p.winfo_height() - win.winfo_height()) // 3)}")
    win.grab_set()
    win.wait_window()
    return result[0]
