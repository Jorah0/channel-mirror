"""The import tab."""
from pathlib import Path
from .core import AUDIO_EXT
from .mirror import clean_name
from .deck import (
    SD_AUTO,
    SD_DEFAULT_OUT,
    SD_FADES,
    SD_FOLDER,
    SD_TUNE,
    sd_beside,
    sd_folders,
    sd_keypad,
    sd_kind,
    sd_level_rows,
    sd_listen,
    sd_play,
    sd_plays_like,
    sd_title,
)
from .ui import DeckGrid, UI, ui_level_report, ui_obs_levels, ui_pick_sounds, ui_play_choice, ui_sound_form


def import_tab(page, cfg, made, deck):
    """The Import to folders tab. Sounds (files, a folder, the Channel Mirror tab's outputs) each get their own key,
    playing once or on a loop, in folders of N. The folder keys go on the keys picked in order, on any page of any
    profile (keys in use can't be picked); folders beyond the picks take the free keys after the last pick. Volume: as
    set, tuned to my OBS levels and/or scaled by %, with a level check first if wanted. Changes go through the
    editor tab (deck = its shared API): one undo, sent to Stream Deck from there or automatically.
    Returns {"prefill": f(profile label, page file, key)} for the editor's right-click."""
    import tkinter as tk
    from tkinter import messagebox, ttk
    if deck is None:
        ttk.Label(page, text="No local Stream Deck install found.").pack(padx=20, pady=20, anchor="w")
        return {"prefill": lambda *a: None}
    files, picks = [], []
    prof_v = tk.StringVar(value=(deck["profiles"]() or [""])[0])
    win = page
    ctx = {}

    def grid():
        return deck["grid"](prof_v.get()) if prof_v.get() else (5, 3)

    def pages():
        return deck["pages"](prof_v.get()) if prof_v.get() else []

    def page_keys(p):
        return deck["keys"](p) if p else {}
    body = ttk.Frame(page, padding=12)
    body.pack(fill="both", expand=True)
    left, right = ttk.Frame(body), ttk.Frame(body)
    left.pack(side="left", fill="both", expand=True, padx=(0, 12))
    right.pack(side="left", fill="both")

    # 1. sounds
    sf = ttk.LabelFrame(left, text="1. Sounds - each one gets its own key, in this order")
    sf.pack(fill="both", expand=True)
    tv = ttk.Treeview(sf, columns=("n", "file", "folder"), show="headings", height=7)
    for c, h, w in (("n", "#", 36), ("file", "File", 220), ("folder", "From folder", 200)):
        tv.heading(c, text=h)
        tv.column(c, width=w, stretch=c != "n")
    tv.pack(fill="both", expand=True)
    title, per = tk.StringVar(), tk.IntVar(value=max(1, grid()[0] * grid()[1] - 1))
    need_l = ttk.Label(sf, style="Hint.TLabel")

    def cap():
        return max(1, grid()[0] * grid()[1] - 1)

    def per_now():
        try:
            return max(1, min(cap(), int(per.get())))
        except (tk.TclError, ValueError):
            return cap()

    def need():
        return -(-len(files) // per_now()) if files else 0

    def refresh(*_):
        tv.delete(*tv.get_children())
        for i, f in enumerate(files):
            tv.insert("", "end", iid=str(i), values=(i + 1, f.name, f.parent.name))
        need_l.config(text=f"{len(files)} sound(s) -> {need()} folder(s) of up to {per_now()}" if files else
                      "Add sounds to import.")
        if "redraw" in st_:
            st_["redraw"]()

    def add(paths):
        for p in map(Path, paths):
            if p not in files and p.suffix.lower() in AUDIO_EXT and p.is_file():
                files.append(p)
        if files and not title.get().strip():
            title.set(clean_name(files[0].parent.name))
        refresh()

    def remove():
        for i in sorted(map(int, tv.selection()), reverse=True):
            del files[i]
        refresh()
    st_ = {}
    bf = ttk.Frame(sf)
    bf.pack(fill="x", pady=(6, 0))
    for text, cmd in (("Add files...", lambda: add(ui_pick_sounds(win, "Sounds to import"))),
                      ("Add folder...", lambda: add(ui_pick_sounds(win, "A folder of sounds to import", True))),
                      ("Channel Mirror outputs", lambda: add(made) if made else messagebox.showinfo(
                          "No outputs yet", "Run the Channel Mirror tab first; the files it writes show up here.",
                          parent=win)),
                      ("Remove", remove), ("Clear", lambda: (files.clear(), refresh()))):
        ttk.Button(bf, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 4))
    need_l.pack(anchor="w", pady=(4, 0))

    # 2. how each key plays
    pf = ttk.LabelFrame(left, text="2. How each key plays, and where it sounds")
    pf.pack(fill="x", pady=(10, 0))
    v = {"mode": tk.StringVar(value="Play / Stop"), "fade": tk.StringVar(value=SD_FADES[0]),
         "fade_len": tk.StringVar(value="1"), "volume": tk.IntVar(value=100),
         "output": tk.StringVar(value=SD_DEFAULT_OUT)}
    ui_play_choice(pf, v["mode"]).pack(anchor="w")
    ui_sound_form(pf, v).pack(fill="x", pady=(6, 0))

    # 3. volume
    vf = ttk.LabelFrame(left, text="3. Volume - adjust and check")
    vf.pack(fill="x", pady=(10, 0))
    tune_on, preset, scale = tk.BooleanVar(value=False), tk.StringVar(value=SD_AUTO), tk.IntVar(value=100)
    r1 = ttk.Frame(vf)
    r1.pack(fill="x")
    ttk.Checkbutton(r1, text="Tune each sound to my OBS levels:", variable=tune_on).pack(side="left")
    ttk.Combobox(r1, textvariable=preset, values=list(SD_TUNE), state="readonly", width=38).pack(side="left", padx=6)
    ttk.Button(r1, text="My OBS levels...", style="Tool.TButton",
               command=lambda: ui_obs_levels(win, cfg)).pack(side="left")
    r2 = ttk.Frame(vf)
    r2.pack(fill="x", pady=(6, 0))
    ttk.Label(r2, text="Then scale every volume by").pack(side="left")
    ttk.Spinbox(r2, textvariable=scale, from_=1, to=400, width=5).pack(side="left", padx=6)
    ttk.Label(r2, text="%").pack(side="left")
    ttk.Button(r2, text="Check levels...", style="Tool.TButton", command=lambda: check()).pack(side="left", padx=14)
    ttk.Label(r2, text="listens to each file; Tune in the list switches tuning on", style="Hint.TLabel").pack(
        side="left")
    status = ttk.Label(left, style="Hint.TLabel")
    status.pack(anchor="w", pady=(6, 0))

    def level_rows():
        heard = {}
        for i, f in enumerate(files, 1):
            status.config(text=f"Listening {i}/{len(files)}: {f.name}...")
            win.update()
            try:
                heard[str(f)] = sd_listen(f)
            except Exception:
                pass
        status.config(text="")
        stand = [{"Settings": {"path": str(f), "volume": int(v["volume"].get())}} for f in files]
        return sd_level_rows(stand, heard, preset.get())

    def check():
        if not files:
            return messagebox.showinfo("Check levels", "Add sounds first.", parent=win)
        rows_ = level_rows()
        if ui_level_report(win, rows_, {id(r["s"]): Path(r["s"]["Settings"]["path"]).name for r in rows_},
                           preset.get()):
            tune_on.set(True)

    # 4. folders
    ff = ttk.LabelFrame(right, text="4. Folders")
    ff.pack(fill="x")
    fr = ttk.Frame(ff)
    fr.pack(fill="x")
    ttk.Label(fr, text="Name").pack(side="left")
    ttk.Entry(fr, textvariable=title, width=20).pack(side="left", padx=6)
    fr = ttk.Frame(ff)
    fr.pack(fill="x", pady=(4, 0))
    ttk.Label(fr, text="Sounds per folder").pack(side="left")
    per_box = ttk.Spinbox(fr, textvariable=per, from_=1, to=cap(), width=4)
    per_box.pack(side="left", padx=6)
    cap_l = ttk.Label(ff, style="Hint.TLabel", wraplength=420)
    cap_l.pack(anchor="w")
    per.trace_add("write", refresh)

    # 5. where the folder keys go
    tf = ttk.LabelFrame(right, text="5. Where the folders go")
    tf.pack(fill="both", expand=True, pady=(10, 0))
    ttk.Label(tf, text="Pick a page, then click free keys in order: folder 1, 2, 3... Grey keys are in use and can't "
                       "be picked; click a picked key again to drop it.", style="Hint.TLabel", wraplength=420,
              justify="left").pack(anchor="w")
    pr = ttk.Frame(tf)
    pr.pack(fill="x", pady=(6, 0))
    ttk.Label(pr, text="Profile").pack(side="left")
    ttk.Combobox(pr, textvariable=prof_v, values=deck["profiles"](), state="readonly", width=44).pack(side="left",
                                                                                                    padx=6)
    page_v = tk.StringVar()
    page_cb = ttk.Combobox(tf, textvariable=page_v, state="readonly", width=40)
    page_cb.pack(anchor="w", pady=6)

    def by_label():
        return dict(pages())

    def labels():
        return {p: n for n, p in pages()}

    def size(p):
        c_, r_ = grid()
        for k in page_keys(p):
            x, y = map(int, k.split(","))
            c_, r_ = max(c_, x + 1), max(r_, y + 1)
        return c_, r_

    def cur():
        return by_label().get(page_v.get())

    def tile(pos):
        a = page_keys(cur()).get(pos)
        c, r = map(int, pos.split(","))
        if (cur(), pos) in picks:
            return f"Folder {picks.index((cur(), pos)) + 1}", UI["accent"], UI["on_accent"]
        if a:
            return f"{(sd_title(a).replace(chr(10), ' ') or sd_kind(a))[:16]}\n(in use)", UI["other"], UI["muted"]
        return f"{c + 1},{r + 1}", UI["empty"], UI["muted"]

    def click(pos, _e=None):
        here = (cur(), pos)
        if here in picks:
            picks.remove(here)
        elif page_keys(cur()).get(pos):
            return pick_l.config(text=f"Key {pos} on {page_v.get()} is in use - pick a free (white) key.")
        else:
            picks.append(here)
        redraw()
    kgrid = DeckGrid(tf, tile, on_click=click,
                    tip=lambda pos: "In use: " + (sd_title(page_keys(cur())[pos]).replace(chr(10), " ") or
                                                  sd_kind(page_keys(cur())[pos])) if page_keys(cur()).get(pos)
                    else "Free - click to put the next folder here")
    kgrid.frame.pack(pady=4)
    pick_l = ttk.Label(tf, style="Hint.TLabel", wraplength=420, justify="left")
    pick_l.pack(anchor="w")

    def targets(n):
        """Keys for n folders: the picks, then the free keys after the last pick on its page."""
        spots = list(picks)
        if picks and len(spots) < n:
            p, k = picks[-1]
            taken = {**page_keys(p), **{k2: 1 for p2, k2 in picks if p2 == p}}
            spots += [(p, x) for x in sd_beside(taken, k, *size(p))]
        return spots[:n]

    def redraw():
        if cur():
            kgrid.draw(*size(cur()))
        n = need()
        lines = [f"{i}: {labels().get(p, '?')}, key {'{},{}'.format(*(int(x) + 1 for x in k.split(',')))}"
                 for i, (p, k) in enumerate(picks, 1)]
        if n > len(picks) and picks:
            got = len(targets(n))
            lines.append(f"Folders {len(picks) + 1}-{n} go on the free keys after the last pick" if got >= n else
                         f"Only room for {got} of {n} folders after the last pick - pick more keys or raise "
                         "Sounds per folder")
        elif not picks:
            lines.append("No key picked yet.")
        elif len(picks) > n:
            lines.append(f"{len(picks) - n} more key(s) picked than folders needed; the extra ones stay free.")
        pick_l.config(text="\n".join(lines))
    st_["redraw"] = redraw
    page_v.trace_add("write", lambda *_: redraw())

    def on_profile(*_):
        """Another profile: its pages, its deck size; picks on the old one are dropped."""
        picks.clear()
        page_cb.config(values=[n for n, _ in pages()])
        if page_v.get() not in by_label():
            page_v.set(pages()[0][0] if pages() else "")
        per_box.config(to=cap())
        if per_now() > cap() or not ctx.get("per_set"):  # full folders until the user sets a number
            ctx["mine"] = True
            per.set(cap())
            ctx["mine"] = False
        cap_l.config(text=f"A folder holds up to {cap()} on this deck (one key is its back key). More sounds than "
                          "that = more folders: name, name 2, name 3...")
        refresh()
        redraw()
    prof_v.trace_add("write", on_profile)

    def prune():
        """Drop picks that are in use now (a key put there from another tab) or whose page is gone (undone)."""
        here = set(by_label().values())
        live = [(p, k) for p, k in picks if p in here and not page_keys(p).get(k)]
        dropped = len(picks) - len(live)
        picks[:] = live
        return dropped

    def ok():
        if not files:
            return messagebox.showinfo("Import", "Add the sounds to import first.", parent=win)
        if prune():
            redraw()
            return messagebox.showinfo("Import", "Some picked keys are in use now (or their page is gone), so they "
                                       "were dropped. Check the picks and press Import again.", parent=win)
        n = need()
        spots = targets(n)
        if not picks or len(spots) < n:
            return messagebox.showinfo("Import", f"These {len(files)} sounds need {n} folder(s). Pick a free key "
                                       "for each (any page), or pick one and leave free keys after it.", parent=win)
        base = int(v["volume"].get())
        vols = {f: base for f in files}
        if tune_on.get():
            for f, r in zip(files, level_rows()):
                if r["new"] is not None:
                    vols[f] = r["new"]
        try:
            pct = int(scale.get())
        except (tk.TclError, ValueError):
            pct = 100
        plays = sd_plays_like(files, sd_play("", "", v["mode"].get(), v["fade"].get(), v["fade_len"].get(), base,
                                             v["output"].get()))
        for f, s in zip(files, plays):
            s["Settings"]["volume"] = max(0, min(100, round(vols[f] * pct / 100)))
        name = title.get().strip()[:20] or "Sounds"
        cols, rows = grid()
        on = {p for p, _ in spots}
        taken = {sd_title(a) for p in on for a in page_keys(p).values() if a and a.get("UUID") == SD_FOLDER}
        chunks = sd_folders(name, plays, cols, rows, taken=taken, per=per_now())
        names, folder = labels(), deck["folder"](prof_v.get())

        def put(edit):
            for (p, k), (key, pid, pg) in zip(spots, chunks):
                sd_keypad(edit(p))[k] = key
                edit(folder / "Profiles" / pid.upper() / "manifest.json", pg)
        msg = (f"Imported {len(plays)} sound(s) into {len(chunks)} folder(s): " + ", ".join(
            f"{sd_title(key)} ({names.get(p, '?')}, key {'{},{}'.format(*(int(x) + 1 for x in k.split(',')))})"
            for (p, k), (key, _, _) in zip(spots, chunks)))
        deck["change"](put, msg)
        picks.clear()
        redraw()
        status.config(text=msg + ". Undo is here or in the Stream Deck editor tab; it's sent to Stream Deck from "
                                 "there (or automatically).")
    bar = ttk.Frame(right)
    bar.pack(fill="x", pady=(10, 0))
    ttk.Button(bar, text="Import", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Undo", command=deck["undo"]).pack(side="right", padx=8)

    def prefill(label, page_file, key):
        """From the editor's right-click: this profile and page, this key picked first."""
        if label in deck["profiles"]():
            prof_v.set(label)
        page_v.set(labels().get(page_file, page_v.get()))
        picks.clear()
        if key and not page_keys(page_file).get(key):
            picks.append((page_file, key))
        redraw()
    deck["listeners"].append(lambda: (page_cb.config(values=[n for n, _ in pages()]), prune(), redraw()))
    per.trace_add("write", lambda *_: ctx.get("mine") or ctx.update(per_set=True))
    on_profile()
    return {"prefill": prefill, "add": add, "files": files, "list": tv}
