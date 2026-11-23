"""The vts tab."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from .core import NO_WINDOW
from .mirror import clean_name
from .deck import SD_DIR, SD_FOLDER, sd_beside, sd_folders, sd_free, sd_keypad, sd_kind, sd_title
from .vts import (
    SD_VTS,
    VTS_APPID,
    VTS_ASSETS,
    VTS_EXT,
    sd_vts_key,
    vts_assets,
    vts_backups,
    vts_copy,
    vts_files,
    vts_find,
    vts_hotkeys,
    vts_last_model,
    vts_missing,
    vts_models,
    vts_running,
)
from .ui import DeckGrid, Tip, UI


def vts_tab(page, cfg, deck):
    """The VTube Studio backgrounds tab: files (single, several, or a folder) are copied into VTube Studio's
    Backgrounds folder, a Change Background hotkey is made for each on the chosen model, and a Stream Deck key that
    triggers it (Cazzar's VTube Studio plugin) goes on keys picked on any page, one each or in folders of N. Stream
    Deck changes go through the editor tab (deck = its shared API): one undo, sent from there or automatically."""
    import time
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    vc = cfg.setdefault("vts", {})
    files, picks = [], []
    assets = vts_assets()
    if VTS_ASSETS and Path(VTS_ASSETS) not in assets:  # the install picked in the Setup tab
        assets.insert(0, Path(VTS_ASSETS))
    start = str(VTS_ASSETS) if VTS_ASSETS else vc.get("assets") or (str(assets[0]) if assets else "")
    v = {"assets": tk.StringVar(value=start),
         "model": tk.StringVar(value=vc.get("model") or vts_last_model(Path(start) if start else None)),
         "hotkeys": tk.BooleanVar(value=vc.get("hotkeys", True)), "keys": tk.BooleanVar(value=vc.get("keys", True)),
         "folders": tk.BooleanVar(value=vc.get("folders", False)), "per": tk.IntVar(value=vc.get("per", 11)),
         "title": tk.StringVar(value=vc.get("title", "Backgrounds")),
         "prof": tk.StringVar(value=(deck["profiles"]() if deck else [""])[0] if deck and deck["profiles"]() else ""),
         "page": tk.StringVar()}
    body = ttk.Frame(page, padding=12)
    body.pack(fill="both", expand=True)
    left, right = ttk.Frame(body), ttk.Frame(body)
    left.pack(side="left", fill="both", expand=True, padx=(0, 12))
    right.pack(side="left", fill="both")

    # VTube Studio
    vf = ttk.LabelFrame(left, text="VTube Studio")
    vf.pack(fill="x")
    r = ttk.Frame(vf)
    r.pack(fill="x")
    ttk.Label(r, text="Install").pack(side="left")
    ttk.Combobox(r, textvariable=v["assets"], values=[str(a) for a in assets], width=70).pack(side="left", padx=6,
                                                                                         fill="x", expand=True)
    ttk.Button(r, text="Browse...", style="Tool.TButton", command=lambda: v["assets"].set(
        filedialog.askdirectory(parent=page, title="VTube Studio's StreamingAssets folder") or v["assets"].get())
               ).pack(side="left")
    r2 = ttk.Frame(vf)
    r2.pack(fill="x", pady=(6, 0))
    ttk.Label(r2, text="Model").pack(side="left")
    model_cb = ttk.Combobox(r2, textvariable=v["model"], state="readonly", width=40)
    model_cb.pack(side="left", padx=6)
    ttk.Label(r2, text="gets the hotkeys (they work while this model is loaded)", style="Hint.TLabel").pack(
        side="left")

    r3 = ttk.Frame(vf)
    r3.pack(fill="x", pady=(6, 0))
    miss_l = ttk.Label(r3, style="Hint.TLabel", wraplength=560, justify="left")
    miss_l.pack(side="left")
    find_b = ttk.Button(r3, text="Find missing...", style="Tool.TButton", command=lambda: find_missing())
    Tip(find_b, "Look through a folder (and the folders inside it) for files named like the missing backgrounds, and "
                "copy them into VTube Studio under those names, so the hotkeys work again.")

    def models():
        try:
            return vts_models(v["assets"].get()) if v["assets"].get() else []
        except OSError:
            return []

    def missing():
        """The chosen model's Change Background hotkeys whose file isn't in VTube Studio's Backgrounds folder."""
        m = next((m for m in models() if m[0] == v["model"].get()), None)
        try:
            return vts_missing(json.loads(m[1].read_text(encoding="utf-8-sig")), bg_dir()) if m and bg_dir() else []
        except (OSError, ValueError):
            return []

    def show_missing(*_):
        miss = missing()
        miss_l.config(text=f"{len(miss)} of this model's background hotkeys point at files VTube Studio doesn't "
                           "have." if miss else "")
        find_b.pack(side="left", padx=8) if miss else find_b.pack_forget()

    def find_missing():
        miss = missing()
        folder = filedialog.askdirectory(parent=page, title="Where the missing backgrounds might be (folders inside "
                                         "it are searched too)", initialdir=str(Path.home() / "Downloads"))
        if not folder or not miss:
            return
        status.config(text="Searching...")
        page.update()
        found = vts_find(miss, [folder])
        try:
            for name, f in found.items():  # under the exact name the hotkey uses; nothing there has that name
                shutil.copy2(f, bg_dir() / f"{name}{f.suffix.lower()}")
        except OSError as e:
            return messagebox.showerror("VTube Studio", f"Couldn't copy into {bg_dir()}:\n{e}", parent=page)
        still = [n for n in miss if n not in found]
        status.config(text=f"Found and copied {len(found)} of {len(miss)} missing background(s)." + (
            f" Still missing ({len(still)}): " + ", ".join(still[:8]) + (" ..." if len(still) > 8 else "")
            if still else " Every background hotkey has its file now."))
        refresh()
        show_missing()

    def on_assets(*_):
        names = [m[0] for m in models()]
        model_cb.config(values=names)
        if v["model"].get() not in names:
            v["model"].set(names[0] if names else "")
        refresh()
        show_missing()
    v["assets"].trace_add("write", on_assets)
    v["model"].trace_add("write", show_missing)

    # backgrounds
    bf = ttk.LabelFrame(left, text="1. Backgrounds (pictures: png / jpg; videos: mp4) - copied in this order")
    bf.pack(fill="both", expand=True, pady=(10, 0))
    tv = ttk.Treeview(bf, columns=("n", "file", "folder", "state"), show="headings", height=8)
    for c, h, w in (("n", "#", 36), ("file", "File", 220), ("folder", "From folder", 170),
                    ("state", "In VTube Studio", 170)):
        tv.heading(c, text=h)
        tv.column(c, width=w, stretch=c in ("file", "folder"))
    tv.pack(fill="both", expand=True)

    def bg_dir():
        return Path(v["assets"].get()) / "Backgrounds" if v["assets"].get() else None

    def refresh():
        tv.delete(*tv.get_children())
        there = {}
        if bg_dir() and bg_dir().is_dir():
            there = {q.stem.lower(): q for q in bg_dir().iterdir() if q.is_file()}
        for i, f in enumerate(files):
            q = there.get(f.stem.lower())
            state = ("new" if q is None else "already there" if q.stat().st_size == f.stat().st_size
                     else "name taken - goes in as (2)")
            tv.insert("", "end", iid=str(i), values=(i + 1, f.name, f.parent.name, state))
        redraw()

    def add(paths):
        got = vts_files(paths)
        for f in got:
            if f not in files:
                files.append(f)
        skipped = sum(1 for p in map(Path, paths) if p.is_file() and p.suffix.lower() not in VTS_EXT)
        status.config(text=f"Added {len(got)} background(s)" + (f"; {skipped} file(s) skipped (not png / jpg / "
                                                                "mp4)" if skipped else "") + ".")
        refresh()
    pick = lambda **k: filedialog.askopenfilenames(parent=page, title="Backgrounds", filetypes=[
        ("Backgrounds", " ".join(f"*{e}" for e in VTS_EXT)), ("All files", "*.*")])
    bb = ttk.Frame(bf)
    bb.pack(fill="x", pady=(6, 0))
    for text, cmd in (("Add files...", lambda: add(pick())),
                      ("Add folder...", lambda: add([d] if (d := filedialog.askdirectory(
                          parent=page, title="A folder of backgrounds")) else [])),
                      ("Remove", lambda: ([files.pop(i) for i in sorted(map(int, tv.selection()), reverse=True)],
                                          refresh())),
                      ("Clear", lambda: (files.clear(), refresh()))):
        ttk.Button(bb, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 4))

    # what to do
    of = ttk.LabelFrame(left, text="2. Then")
    of.pack(fill="x", pady=(10, 0))
    ttk.Checkbutton(of, text="Make a Change Background hotkey for each, on the model above (ones it already has are "
                             "reused)", variable=v["hotkeys"]).pack(anchor="w")
    ttk.Checkbutton(of, text="Put a Stream Deck key for each, that triggers its hotkey", variable=v["keys"]).pack(
        anchor="w")
    fr = ttk.Frame(of)
    fr.pack(anchor="w", padx=(22, 0))
    ttk.Checkbutton(fr, text="in folders of", variable=v["folders"]).pack(side="left")
    ttk.Spinbox(fr, textvariable=v["per"], from_=1, to=99, width=4).pack(side="left", padx=4)
    ttk.Label(fr, text="named").pack(side="left")
    ttk.Entry(fr, textvariable=v["title"], width=16).pack(side="left", padx=4)
    plugin = (SD_DIR / "Plugins" / f"{SD_VTS['UUID']}.sdPlugin").is_dir()
    ttk.Label(of, style="Hint.TLabel", wraplength=560, justify="left", text=(
        "Stream Deck keys use the VTube Studio plugin by Cazzar (installed). VTube Studio closes for a moment while "
        "hotkeys are written (it saves its model file when it closes); it's reopened after." if plugin else
        "The keys need the VTube Studio plugin by Cazzar - install it from Stream Deck's store for them to work."
    )).pack(anchor="w", pady=(4, 0))
    status = ttk.Label(left, style="Status.TLabel", anchor="w", wraplength=640, justify="left")
    status.pack(fill="x", pady=(8, 0))

    # where the Stream Deck keys go
    tf = ttk.LabelFrame(right, text="3. Where the Stream Deck keys go")
    tf.pack(fill="both", expand=True)
    if deck is None:
        ttk.Label(tf, text="No local Stream Deck install found.").pack(padx=10, pady=10)
    ttk.Label(tf, text="Pick a profile and page, then click free keys in order (a key for each, or for each folder). "
                       "Grey keys are in use and can't be picked; more keys than picked go on the free keys after "
                       "the last pick.", style="Hint.TLabel", wraplength=430, justify="left").pack(anchor="w")
    pr = ttk.Frame(tf)
    pr.pack(fill="x", pady=(6, 0))
    ttk.Label(pr, text="Profile").pack(side="left")
    ttk.Combobox(pr, textvariable=v["prof"], values=deck["profiles"]() if deck else [], state="readonly",
                 width=44).pack(side="left", padx=6)
    page_cb = ttk.Combobox(tf, textvariable=v["page"], state="readonly", width=40)
    page_cb.pack(anchor="w", pady=6)
    pages = lambda: deck["pages"](v["prof"].get()) if deck and v["prof"].get() else []
    cur = lambda: dict(pages()).get(v["page"].get())
    keys_of = lambda p: deck["keys"](p) if deck and p else {}

    def size(p):
        c_, r_ = deck["grid"](v["prof"].get()) if deck and v["prof"].get() else (5, 3)
        for k in keys_of(p):
            x, y = map(int, k.split(","))
            c_, r_ = max(c_, x + 1), max(r_, y + 1)
        return c_, r_

    def tile(pos):
        a = keys_of(cur()).get(pos)
        c, r_ = map(int, pos.split(","))
        if (cur(), pos) in picks:
            return f"{picks.index((cur(), pos)) + 1}", UI["accent"], UI["on_accent"]
        if a:
            return f"{(sd_title(a).replace(chr(10), ' ') or sd_kind(a))[:16]}\n(in use)", UI["other"], UI["muted"]
        return f"{c + 1},{r_ + 1}", UI["empty"], UI["muted"]

    def click(pos, _e=None):
        here = (cur(), pos)
        if here in picks:
            picks.remove(here)
        elif keys_of(cur()).get(pos):
            return status.config(text=f"That key ({pos}) is in use - pick a free (white) one.")
        else:
            picks.append(here)
        redraw()
    grid = DeckGrid(tf, tile, on_click=click)
    grid.frame.pack(pady=4)
    pick_l = ttk.Label(tf, style="Hint.TLabel", wraplength=430, justify="left")
    pick_l.pack(anchor="w")

    def per_n():
        try:
            return max(1, int(v["per"].get()))
        except (tk.TclError, ValueError):  # a blank / non-number box
            return 1

    def planned():
        """The names the picked files will have in VTube Studio (one key each), worked out the way the copy does."""
        try:
            return list(dict.fromkeys(vts_copy(files, bg_dir(), dry=True))) if files and bg_dir() else []
        except OSError:
            return list(dict.fromkeys(f.stem for f in files))

    def need():
        n = len(planned())
        if v["folders"].get():
            per = per_n()
            cols, rows = size(cur()) if cur() else (5, 3)
            per = min(per, max(1, cols * rows - 1))
            return -(-n // per) if n else 0
        return n

    def targets(n):
        spots = list(picks)
        if picks and len(spots) < n:
            p, k = picks[-1]
            taken = {**keys_of(p), **{k2: 1 for p2, k2 in picks if p2 == p}}
            spots += [(p, x) for x in sd_beside(taken, k, *size(p))]
        return spots[:n]

    def redraw():
        if cur():
            grid.draw(*size(cur()))
        n = need() if v["keys"].get() else 0
        what = "folder" if v["folders"].get() else "key"
        got = len(targets(n)) if picks else 0
        pick_l.config(text=(f"{n} {what}(s) needed; {len(picks)} picked" +
                            (", the rest after the last pick" if picks and got >= n > len(picks) else "") +
                            (f" - only room for {got}: pick more keys" if picks and got < n else "") +
                            ("" if picks or not n else " - pick where they start")) if n else
                      "No Stream Deck keys (tick 'Put a Stream Deck key for each').")

    def on_prof(*_):
        picks.clear()
        page_cb.config(values=[n for n, _ in pages()])
        if v["page"].get() not in dict(pages()):
            v["page"].set(pages()[0][0] if pages() else "")
        redraw()
    v["prof"].trace_add("write", on_prof)
    v["page"].trace_add("write", lambda *_: redraw())
    for x in ("keys", "folders", "per"):
        v[x].trace_add("write", lambda *_: redraw())
    if deck:
        deck["listeners"].append(lambda: (page_cb.config(values=[n for n, _ in pages()]),
                                          picks.__setitem__(slice(None), [(p, k) for p, k in picks
                                                                          if not keys_of(p).get(k)]), redraw()))

    def close_vts():
        """Close VTube Studio politely (it saves its files) and wait; True when it's closed."""
        subprocess.run(["taskkill", "/IM", "VTube Studio.exe"], capture_output=True, creationflags=NO_WINDOW)
        for _ in range(60):
            if not vts_running():
                return True
            status.config(text="Waiting for VTube Studio to close...")
            page.update()
            time.sleep(0.25)
        return False

    def start_vts():
        try:
            os.startfile(f"steam://rungameid/{VTS_APPID}")
            return True
        except OSError:
            return False

    def run(auto=False):
        """Copy and set up. auto = accepted from a linked computer: hotkeys and keys made (keys on the picked keys, or
        the first free one of the page here), no questions; what can't be done raises ValueError instead."""
        def fail(kind, msg):
            if auto:
                raise ValueError(msg)
            return getattr(messagebox, kind)("VTube Studio", msg, parent=page)
        if not files:
            return fail("showinfo", "Add the backgrounds first.")
        if not bg_dir() or not (bg_dir().parent / "Live2DModels").is_dir():
            return fail("showerror", "Pick VTube Studio's StreamingAssets folder (the one with Backgrounds and "
                                     "Live2DModels in it).")
        want_hk = auto or v["hotkeys"].get() or v["keys"].get()
        want_keys, no_room = (auto or v["keys"].get()) and deck is not None, ""
        model = next((m for m in models() if m[0] == v["model"].get()), None)
        if want_hk and model is None:
            return fail("showinfo", "Pick the model that gets the hotkeys.")
        if want_keys:
            n = need()
            if auto and not picks and cur():
                picks[:] = [(cur(), k) for k in sd_free(keys_of(cur()), *size(cur()))[:1]]
            if not picks or len(targets(n)) < n:
                if not auto:
                    return messagebox.showinfo("VTube Studio", f"These need {n} Stream Deck key(s). Pick where they "
                                               "go (a free key for each, or one with free keys after it).", parent=page)
                want_keys, no_room = False, f"no room for the {n} Stream Deck key(s) on {v['page'].get()}"
                picks.clear()
        # 1. copy
        try:
            names = vts_copy(files, bg_dir())
        except OSError as e:
            return fail("showerror", f"Couldn't copy into {bg_dir()}:\n{e}")
        names = list(dict.fromkeys(names))  # the same background twice gets one hotkey / key
        done = [f"copied {len(files)} background(s) into VTube Studio"]
        refresh()
        if not want_hk:
            return status.config(text=done[0].capitalize() + ".")
        # 2. hotkeys: VTube Studio rewrites its model file when it closes, so it's closed while this is written
        reopen = False
        if vts_running():
            if not auto and not messagebox.askyesno(  # accepted from a linked computer: that was the question
                    "VTube Studio", "VTube Studio must close for a moment while the hotkeys are written (it saves its "
                    "model files when it closes).\nClose it now and reopen it after?", parent=page):
                return status.config(text=done[0].capitalize() + "; hotkeys and keys not made (VTube Studio was "
                                     "left open). Press again when it can close.")
            if not close_vts():
                status.config(text=done[0].capitalize() + "; VTube Studio didn't close, so no hotkeys were "
                              "made. Close it yourself and press again.")
                return fail("showinfo", "The backgrounds were copied, but VTube Studio didn't close, so no hotkeys "
                                        "were made - close it and press Copy and set up there.") if auto else None
            reopen = True
        _, mfile, mid = model
        bk = vts_backups()
        tmp_file = mfile.with_name(mfile.name + ".channelmirror-new")
        try:
            data = json.loads(mfile.read_text(encoding="utf-8-sig"))
            bk.mkdir(parents=True, exist_ok=True)
            shutil.copy2(mfile, bk / f"{mfile.name[:-len('.vtube.json')]} {time.strftime('%Y%m%d-%H%M%S')}.vtube.json")
            ids, added = vts_hotkeys(data, names)
            if added:  # written beside it and checked, then swapped in: the model file is never left half-written
                tmp_file.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
                if json.loads(tmp_file.read_text(encoding="utf-8")) != data:
                    raise OSError("the new model file didn't read back as written")
                os.replace(tmp_file, mfile)
        except (OSError, ValueError) as e:
            try:
                tmp_file.unlink()
            except OSError:
                pass
            if reopen:
                start_vts()
            return fail("showerror", f"Couldn't add the hotkeys to {mfile.name} (it's unchanged):\n{e}\n\nThe "
                                     f"backgrounds were copied. Model file backups are in {bk}.")
        done.append(f"{added} new hotkey(s) on {model[0]}" + (f" ({len(names) - added} already there)"
                                                               if len(names) > added else ""))
        if reopen:
            done.append("VTube Studio reopened" if start_vts() else "start VTube Studio again yourself")
        # 3. Stream Deck keys
        if want_keys:
            acts = [sd_vts_key(mid, ids[nm], clean_name(nm)) for nm in names]
            if v["folders"].get():
                cols, rows = deck["grid"](v["prof"].get())
                on = {p for p, _ in picks}
                taken = {sd_title(a) for p in on for a in keys_of(p).values() if a and a.get("UUID") == SD_FOLDER}
                placed = sd_folders(v["title"].get().strip()[:20] or "Backgrounds", acts, cols, rows, taken=taken,
                                    per=per_n())
            else:
                placed = acts
            spots = targets(len(placed))
            if len(spots) < len(placed):  # never place only some of them
                save()
                return status.config(text="; ".join(done).capitalize() + f". The {len(placed)} Stream Deck "
                                     "key(s) / folder(s) didn't all fit after the picked keys, so none were added - "
                                     "pick more keys and press again (nothing is copied or added twice).")
            folder = deck["folder"](v["prof"].get())

            def put(edit):
                for (p, k), item in zip(spots, placed):
                    if isinstance(item, tuple):  # a folder: its key here, its page beside the others
                        fkey, pid, pg = item
                        sd_keypad(edit(p))[k] = fkey
                        edit(folder / "Profiles" / pid.upper() / "manifest.json", pg)
                    else:
                        sd_keypad(edit(p))[k] = item
            deck["change"](put, f"{len(names)} VTube Studio background key(s) on Stream Deck")
            picks.clear()
            done.append(f"{len(names)} Stream Deck key(s) added" + (f" in {len(placed)} folder(s)"
                                                                    if v["folders"].get() else "") +
                        " (sent to Stream Deck from the editor tab, or automatically; Undo there)")
        if no_room:
            done.append(no_room)
        save()
        redraw()
        status.config(text="; ".join(done).capitalize() + ".")
        return status.cget("text")

    def auto(paths):
        """Backgrounds accepted from a linked computer, set up by this tab (run(auto=True)) - only these: whatever
        else is in the list stays there for later. What was done; ValueError when it can't be done here."""
        keep = list(files)
        files[:] = vts_files(paths)
        try:
            return run(auto=True)
        finally:
            files[:] = keep + [f for f in files if f not in keep]
            refresh()

    bar = ttk.Frame(right)
    bar.pack(fill="x", pady=(10, 0))
    ttk.Button(bar, text="Copy and set up", style="Accent.TButton", command=run).pack(side="right")
    if deck:
        ttk.Button(bar, text="Undo keys", command=deck["undo"]).pack(side="right", padx=8)

    def save():
        vc.update({k: x.get() for k, x in v.items() if k not in ("prof", "page", "per")}, per=per_n())
    on_assets()
    on_prof()
    return {"save": save, "add": add, "run": run, "vars": v, "picks": picks, "grid": grid, "files": files,
            "refresh": refresh, "auto": auto, "list": tv}
