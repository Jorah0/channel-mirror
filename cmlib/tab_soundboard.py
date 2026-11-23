"""The soundboard tab."""
import os
from pathlib import Path
from .mirror import clean_name
from .deck import (
    SD_AUTO,
    SD_DEFAULT_OUT,
    SD_EXE,
    SD_FADES,
    SD_KINDS,
    SD_MODES,
    SD_OUT,
    SD_TUNE,
    sd_devices,
    sd_free,
    sd_install,
    sd_key,
    sd_layout,
    sd_level_rows,
    sd_listen,
    sd_out,
    sd_out_name,
    sd_output_choices,
    sd_profile,
    sd_push,
    sd_running,
    sd_set_levels,
)
from .ui import (
    DeckGrid,
    Tip,
    UI,
    sd_levels_text,
    ui_background,
    ui_cell_edit,
    ui_keys,
    ui_level_report,
    ui_menu,
    ui_multi_rows,
    ui_obs_levels,
    ui_pick_sounds,
    ui_sound_form,
    ui_empty,
)


def streamdeck_tab(page, cfg, made):
    """The Stream Deck sub-app. made = files the Channel Mirror tab wrote this session. Returns a save() for cfg."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    sc = cfg.setdefault("streamdeck", {})
    sounds, keys = [], {}  # keys: 'col,row' (from 1) -> {"kind", "title"}
    cur = tk.StringVar(value="1,1")  # the deck key being edited
    st = {"lay": {}}
    one = lambda p0: "{},{}".format(*(int(x) + 1 for x in p0.split(",")))  # grid pos (from 0) -> key (from 1)

    # toolbar
    bar = ttk.Frame(page, padding=(10, 10, 10, 4))
    bar.pack(fill="x")
    devices = sd_devices() or {"Stream Deck 5x3": ("20GBA9901", "", 5, 3)}
    k = {"profile": tk.StringVar(value=sc.get("profile", "Soundboard")),
         "device": tk.StringVar(value=sc.get("device") if sc.get("device") in devices else next(iter(devices))),
         "cols": tk.IntVar(value=sc.get("cols", 5)), "rows": tk.IntVar(value=sc.get("rows", 3))}
    adders = ttk.Frame(bar)
    adders.pack(side="left")
    bar2 = ttk.Frame(page, padding=(10, 0, 10, 4))  # the deck on its own row, so it stays on screen
    bar2.pack(fill="x")
    ttk.Label(bar2, text="Device").pack(side="left")
    ttk.Combobox(bar2, textvariable=k["device"], values=tuple(devices), state="readonly", width=36).pack(
        side="left", padx=6)
    ttk.Label(bar2, text="Columns").pack(side="left", padx=(8, 0))
    ttk.Spinbox(bar2, textvariable=k["cols"], from_=1, to=16, width=3).pack(side="left", padx=4)
    ttk.Label(bar2, text="Rows").pack(side="left")
    ttk.Spinbox(bar2, textvariable=k["rows"], from_=1, to=16, width=3).pack(side="left", padx=4)
    ttk.Label(bar2, text="Profile name").pack(side="left", padx=(12, 0))
    ttk.Entry(bar2, textvariable=k["profile"], width=18).pack(side="left", padx=6)

    panes = ttk.PanedWindow(page, orient="horizontal")
    panes.pack(fill="both", expand=True, padx=10, pady=6)
    box = ttk.LabelFrame(panes, text="Sounds")
    deckf = ttk.LabelFrame(panes, text="Stream Deck keys")
    panes.add(box, weight=3)
    panes.add(deckf, weight=2)

    # sounds list
    cols = ("title", "key", "mode", "fade", "volume", "output", "file")
    tl = ttk.Frame(box)
    tl.pack(fill="both", expand=True)
    tree = ttk.Treeview(tl, columns=cols, show="headings", height=6)
    ui_empty(tree, "No sounds yet. Add files, a folder, or the Channel Mirror tab's outputs.")
    for c, h, w in zip(cols, ("Name", "Key", "Action", "Fade", "Vol", "Output", "File"), (130, 50, 105, 120, 45, 110, 240)):
        tree.heading(c, text=h)
        tree.column(c, width=w, stretch=c in ("file", "title"))
    ys = ttk.Scrollbar(tl, command=tree.yview)
    tree.config(yscrollcommand=ys.set)
    ys.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    tools = ttk.Frame(box)
    tools.pack(fill="x", pady=(8, 0))
    lvl = ttk.Frame(box)  # levels: listen to the files and set their volumes for my OBS levels
    lvl.pack(fill="x", pady=(6, 0))
    sd_set_levels(cfg.get("obs_levels"))
    tune_v = tk.StringVar(value=sc.get("tune") if sc.get("tune") in SD_TUNE else SD_AUTO)
    auto_tune = tk.BooleanVar(value=sc.get("auto_tune", False))
    ttk.Label(box, text="Drag sounds onto a key to map them  -  Ctrl/Shift+click several rows, then double-click a "
                        "cell to change them all  -  right-click for more", style="Hint.TLabel").pack(anchor="w",
                                                                                         pady=(6, 0))

    # deck
    kgrid = DeckGrid(deckf, lambda p: tile(p), on_click=lambda p, e: pick_key(one(p)),
                     on_double=lambda p, e: (pick_key(one(p)), title_entry.focus_set()),
                     on_menu=lambda p, e: key_menu(one(p), e), on_drop=lambda a, b: swap_keys(one(a), one(b)),
                     tip=lambda p: tip_for(one(p)))
    kgrid.frame.pack(pady=(4, 8))
    ke = ttk.LabelFrame(deckf, text="Selected key")
    ke.pack(fill="x")
    kind_v, title_v = tk.StringVar(value="Single sound"), tk.StringVar()
    r = ttk.Frame(ke)
    r.pack(fill="x")
    ttk.Label(r, textvariable=cur, font=("Segoe UI", 12, "bold"), width=5).pack(side="left")
    ttk.Label(r, text="Action").pack(side="left")
    ttk.Combobox(r, textvariable=kind_v, values=tuple(SD_KINDS), state="readonly", width=14).pack(side="left", padx=6)
    ttk.Label(r, text="Key name").pack(side="left", padx=(8, 0))
    title_entry = ttk.Entry(r, textvariable=title_v, width=16)
    title_entry.pack(side="left", padx=6)
    kbtns = ttk.Frame(ke)
    kbtns.pack(fill="x", pady=(8, 0))
    ttk.Label(deckf, text="Click a key to select it  -  drag keys to swap them  -  right-click for more",
              style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

    # per-sound settings
    ed = ttk.LabelFrame(page, text="Sound settings  (for the selected sounds; new sounds start with these)")
    ed.pack(fill="x", padx=10, pady=(0, 6))
    v = {"title": tk.StringVar(), "mode": tk.StringVar(value=sc.get("mode", SD_MODES[0])),
         "fade": tk.StringVar(value=sc.get("fade", SD_FADES[0])), "fade_len": tk.StringVar(value=sc.get("fade_len", "1")),
         "volume": tk.IntVar(value=sc.get("volume", 100)), "output": tk.StringVar(value=sc.get("output", ""))}
    er = ttk.Frame(ed)
    er.pack(fill="x")
    nf = ttk.Frame(er)
    nf.pack(side="left", padx=(0, 14))
    ttk.Label(nf, text="NAME", style="Field.TLabel").pack(anchor="w")
    ttk.Entry(nf, textvariable=v["title"], width=20).pack()
    ui_sound_form(er, v).pack(side="left")
    apply_btn = ttk.Button(er, text="Apply to selected")
    apply_btn.pack(side="right", anchor="s")

    runbar = ttk.Frame(page, padding=(10, 2, 10, 10))
    runbar.pack(fill="x")
    status = ttk.Label(runbar, style="Status.TLabel", anchor="w",
                       text="Add sounds, map them to keys, then Send to Stream Deck.")

    def deck_size():
        try:
            return max(1, int(k["cols"].get())), max(1, int(k["rows"].get()))
        except (tk.TclError, ValueError):
            return 5, 3

    def show(keep=None):
        sel = keep if keep is not None else tree.selection()
        tree.delete(*tree.get_children())
        for i, s in enumerate(sounds):
            tree.insert("", "end", iid=str(i), values=(s["title"], s["key"] or "auto", s["mode"],
                        s["fade"] + (f" {s['fade_len']}s" if s["fade"] != SD_FADES[0] else ""),
                        s["volume"], sd_out_name(sd_out(s["output"])), s["path"]))
        tree.selection_set([i for i in sel if tree.exists(i)])
        draw()

    def folders_opt():
        """{"title", "per"} when 'one key per sound, in folders' is on (else None)."""
        if not fold_on.get():
            return None
        try:
            n = max(1, int(fper.get()))
        except (tk.TclError, ValueError):
            n = 1
        return {"title": ftitle.get().strip()[:20] or "Sounds", "per": n}

    def draw():
        c_n, r_n = deck_size()
        status_note = ""
        f = folders_opt()
        if f:  # preview: the folder keys, filled in order
            per_ = max(1, min(f["per"], c_n * r_n - 1))
            sizes = [min(per_, len(sounds) - i) for i in range(0, len(sounds), per_)]
            st["lay"] = {"{},{}".format(*(int(x) + 1 for x in key.split(","))): (
                "Folder", f["title"] if i == 0 else f"{f['title']} {i + 1}", [None] * n_)
                for i, (key, n_) in enumerate(zip(sd_free({}, c_n, r_n), sizes))}
            if len(sizes) > c_n * r_n:
                status_note = (f"{len(sounds)} sounds need {len(sizes)} folders but the page has {c_n * r_n} keys - "
                               "put more sounds in each folder")
        else:
            try:
                st["lay"] = {f"{c + 1},{r + 1}": x for (c, r), x in sd_layout(sounds, keys, c_n, r_n).items()}
            except ValueError as e:
                st["lay"], status_note = {}, str(e)  # mid-edit conflict; shown, and Send reports it too
        kgrid.draw(c_n, r_n)
        if status_note:
            status.config(text=status_note)

    def tile(p0):
        pos = one(p0)
        kind, title, group = st["lay"].get(pos, ("", "", []))
        if kind == "Folder":
            return f"{title[:22]}\nFolder x{len(group)}", UI["sound"], UI["text"]
        auto = bool(group) and not group[0]["key"]
        if pos == cur.get():
            bg, fg = UI["accent"], UI["on_accent"]
        else:
            bg, fg = (UI["auto"] if auto else UI["sound"] if group else UI["empty"]), (UI["text"] if group else UI["muted"])
        if not group:
            return pos, bg, fg
        label = "auto" if auto else kind.split()[0]
        return f"{title[:22]}\n{label}" + (f" x{len(group)}" if len(group) > 1 else ""), bg, fg

    def tip_for(pos):
        kind, title, group = st["lay"].get(pos, ("", "", []))
        if kind == "Folder":
            return f"Key {pos}: folder '{title}' with {len(group)} sound(s), one key each, in list order."
        if not group:
            return f"Key {pos} is free.\nDrag sounds here, or right-click to add a folder or files."
        auto = "  (placed automatically - drag it to pin it)" if not group[0]["key"] else ""
        return "\n".join([f"Key {pos}: {title} - {kind}{auto}"] + [f"  - {Path(s['path']).name}" for s in group[:10]]
                         + ([f"  ...and {len(group) - 10} more"] if len(group) > 10 else []))

    def pick_key(pos):
        cur.set(pos)
        kc = keys.get(pos, {})
        kind_v.set(kc.get("kind", "Single sound"))
        title_v.set(kc.get("title", ""))
        tree.selection_set([str(i) for i, s in enumerate(sounds) if s["key"] == pos])
        draw()

    def key_changed(*_):
        keys[cur.get()] = {"kind": kind_v.get(), "title": title_v.get().strip()}
        draw()

    def assign(idx, pos):
        """Put sounds (list indexes) on a key; several on one key make it a Random Action unless set otherwise."""
        for i in idx:
            sounds[i]["key"] = pos
        if sum(s["key"] == pos for s in sounds) > 1 and keys.get(pos, {}).get("kind", "Single sound") == "Single sound":
            keys[pos] = {"kind": "Random Action", "title": keys.get(pos, {}).get("title", "")}
        pick_key(pos)
        show([str(i) for i in idx])
        status.config(text=f"{len(idx)} sound(s) mapped to key {pos}.")

    def swap_keys(a, b):
        if folders_opt():
            return status.config(text="With 'one key per sound, in folders' on, the folders fill the page in order; "
                                      "reorder the sounds in the list instead.")
        for s in st["lay"].get(a, ("", "", []))[2]:  # pin auto-placed sounds before swapping
            s["key"] = s["key"] or a
        for s in st["lay"].get(b, ("", "", []))[2]:
            s["key"] = s["key"] or b
        for s in sounds:
            s["key"] = b if s["key"] == a else a if s["key"] == b else s["key"]
        ka, kb = keys.pop(a, None), keys.pop(b, None)
        if ka:
            keys[b] = ka
        if kb:
            keys[a] = kb
        pick_key(b)
        show()
        status.config(text=f"Keys {a} and {b} swapped.")

    def level_rows(ss):
        """Listen to these sounds and work out their volumes for my OBS levels (sd_level_rows on stand-ins)."""
        heard, paths = {}, sorted({str(s["path"]) for s in ss if Path(s["path"]).is_file()})
        for i, p in enumerate(paths, 1):
            status.config(text=f"Listening {i}/{len(paths)}: {Path(p).name}...")
            page.update()
            try:
                heard[p] = sd_listen(p)
            except Exception:
                pass
        stand = [{"Settings": {"path": str(s["path"]), "volume": int(s["volume"])}} for s in ss]
        return sd_level_rows(stand, heard, tune_v.get()), stand

    def tune(ss, rows):
        for s, r in zip(ss, rows):
            if r["new"] is not None:
                s["volume"] = r["new"]
        n = lambda test: sum(1 for r in rows if test(r))
        return (f"tuned {n(lambda r: r['new'] is not None)} to {tune_v.get()} ({sd_levels_text()}); "
                f"{n(lambda r: r['verdict'] == 'in range')} already in range"
                + (f"; {k} too quiet even at full volume" if (k := n(lambda r: r['verdict'].startswith('too quiet even')))
                   else "") + (f"; {k} silent or unreadable" if (k := n(lambda r: r['now'] is None)) else ""))

    def check_levels():
        ss = [sounds[i] for i in picked()] or sounds
        if not ss:
            return messagebox.showinfo("Check levels", "Add sounds first (Add files / Add folder).")
        rows, stand = level_rows(ss)
        status.config(text=f"Listened to {len(ss)} sound(s).")
        if ui_level_report(page, rows, {id(x): s["title"] for x, s in zip(stand, ss)}, tune_v.get()):
            status.config(text=f"{len(ss)} sound(s): {tune(ss, rows)}.")
            show()

    def add(paths, key=""):
        have = {str(s["path"]): s for s in sounds}
        new, mine = [], []
        for p in map(Path, paths):
            if str(p) in have:
                have[str(p)]["key"] = key or have[str(p)]["key"]
                mine.append(have[str(p)])
            elif p.is_file():
                new.append({"path": p, "title": clean_name(p.stem), "key": key, **{n: v[n].get() for n in
                            ("mode", "fade", "fade_len", "volume", "output")}})  # new sounds take the editor's settings
                mine.append(new[-1])
        if key:  # a key holds its sounds in the order given (a folder's name order), also ones already in the list
            ids = {id(s) for s in mine}
            sounds[:] = [s for s in sounds if id(s) not in ids] + mine
        else:
            sounds.extend(new)
        show()
        msg = f"Added {len(new)} sound(s)" + (f" to key {key}" if key else "")
        if new and auto_tune.get():
            msg += "; " + tune(new, level_rows(new)[0])
            show()
        status.config(text=msg + ".")
        return len(new)

    def folder_sounds(title):
        return ui_pick_sounds(page, title, folder=True)

    def folder_to_key(pos=None):
        """Every sound in a folder onto a key as one action (Random unless already Multi)."""
        pos = pos or cur.get()
        files = folder_sounds(f"Sounds for key {pos}")
        if not files:
            return
        pick_key(pos)
        add(files, pos)
        if len(files) > 1 and kind_v.get() == "Single sound":
            kind_v.set("Random Action")
        if not title_v.get().strip():
            title_v.set(clean_name(Path(files[0]).parent.name))
        status.config(text=f"Key {pos}: {len(files)} sound(s) from {Path(files[0]).parent}")

    def files_to_key(pos=None):
        pos = pos or cur.get()
        pick_key(pos)
        files = ui_pick_sounds(page, f"Sounds for key {pos}")
        if files:
            add(files, pos)
            if len(files) > 1 and kind_v.get() == "Single sound":
                kind_v.set("Random Action")

    def clear_key(pos=None):
        pos = pos or cur.get()
        for s in sounds:
            if s["key"] == pos:
                s["key"] = ""
        keys.pop(pos, None)
        pick_key(pos)
        show()

    def set_kind(pos, kind):
        pick_key(pos)
        kind_v.set(kind)

    def key_menu(pos, e):
        pick_key(pos)
        sel = picked()
        ui_menu(kgrid.frame, e, [("Add folder to this key...", lambda: folder_to_key(pos)),
                                 ("Add files to this key...", lambda: files_to_key(pos)),
                                 (f"Put the {len(sel)} selected sound(s) here", (lambda: assign(sel, pos)) if sel
                                  else None), None,
                                 *[(f"Make it: {kd}", lambda kd=kd: set_kind(pos, kd)) for kd in SD_KINDS], None,
                                 ("Clear this key", lambda: clear_key(pos))])

    def picked():
        return [int(i) for i in tree.selection()]

    def on_pick(_=None):
        sel = picked()
        if sel:
            s = sounds[sel[0]]
            for n in v:
                v[n].set(s[n] if len(sel) == 1 or n != "title" else "")

    def apply():
        sel = picked()
        if not sel:
            return messagebox.showinfo("Apply", "Select one or more sounds first.")
        for i in sel:
            for n in v:
                if len(sel) == 1 or n != "title":  # the name is per sound
                    val = v[n].get()
                    sounds[i][n] = val.strip() if isinstance(val, str) else val
        show()
        status.config(text=f"Settings applied to {len(sel)} sound(s).")

    def move(step):
        sel = picked()
        if len(sel) == 1 and 0 <= sel[0] + step < len(sounds):
            i = sel[0]
            sounds[i], sounds[i + step] = sounds[i + step], sounds[i]
            show([str(i + step)])

    def remove():
        for i in sorted(picked(), reverse=True):
            del sounds[i]
        show([])

    def unassign():
        for i in picked():
            sounds[i]["key"] = ""
        show()

    def preview():
        sel = picked()
        if sel:
            os.startfile(sounds[sel[0]]["path"])  # ponytail: plays in the default player, not through Stream Deck

    # tree: in-place editing, menu, drag onto keys
    def edit_cell(e):
        item, col = tree.identify_row(e.y), tree.identify_column(e.x)
        if not item or not col:
            return
        name, s = cols[int(col[1:]) - 1], sounds[int(item)]
        if name == "file":
            return preview()

        def done(val):
            rows = picked() if item in tree.selection() else [int(item)]  # every selected row
            if name == "key":
                val = val.strip()
                if val.lower() == "auto":
                    val = ""
                try:
                    sd_key(val, *deck_size())
                except ValueError as err:
                    return messagebox.showerror("Key", str(err))
                if val:
                    return assign(rows, val)
                for i in rows:
                    sounds[i]["key"] = ""
                return show()
            if name == "volume":
                try:
                    val = int(val)
                    assert 0 <= val <= 100
                except (ValueError, AssertionError):
                    return messagebox.showerror("Volume", "Volume is a whole number from 0 to 100.")
            for i in rows:
                sounds[i][name] = val
            show()
            status.config(text=f"Changed {name} on {len(rows)} sound(s).")
        if name == "mode":
            ui_cell_edit(tree, item, col, s["mode"], done, SD_MODES)
        elif name == "fade":
            ui_cell_edit(tree, item, col, s["fade"], done, SD_FADES)
        elif name == "output":
            ui_cell_edit(tree, item, col, s["output"] or SD_DEFAULT_OUT, done, sd_output_choices(), True)
        else:
            ui_cell_edit(tree, item, col, str(s[name] or ("auto" if name == "key" else "")), done)

    def tree_menu(e):
        item = tree.identify_row(e.y)
        if item and item not in tree.selection():
            tree.selection_set(item)
        sel = picked()
        if not sel:
            return
        ui_menu(tree, e, [("Preview", preview), (f"Put on key {cur.get()}", lambda: assign(sel, cur.get())),
                          ("Unassign (place automatically)", unassign), None,
                          ("Move up", lambda: move(-1)), ("Move down", lambda: move(1)), None,
                          (f"Remove {len(sel)} sound(s)   Del", remove), None, *save.more()])
    tree.bind("<Button-3>", tree_menu)

    def drop_on_key(e):  # selected sounds dragged from the list onto a key
        pos = kgrid.key_at(e.x_root, e.y_root)
        if pos and picked():
            assign(picked(), one(pos))
    ui_multi_rows(tree, edit_cell, drop_on_key)

    def on_device(*_):
        _, _, c, r_ = devices[k["device"].get()]
        k["cols"].set(c), k["rows"].set(r_)

    def save():
        sc.update({n: x.get() for n, x in k.items()})
        sc.update({n: v[n].get() for n in ("mode", "fade", "fade_len", "volume", "output")}, direct=direct.get(),
                  tune=tune_v.get(), auto_tune=auto_tune.get(), folders=fold_on.get(), folder_title=ftitle.get(),
                  folder_play=fplay.get())
        try:
            sc["folder_per"] = int(fper.get())
        except (tk.TclError, ValueError):
            pass

    def to_send():
        """The sounds as they go out: with the folder option's Play once / Loop, every sound plays that way."""
        if fold_on.get() and fplay.get() in ("Play / Stop", "Loop / Stop"):
            return [dict(s, mode=fplay.get()) for s in sounds]
        return sounds

    def push(writes, name, n):
        """A new profile into Stream Deck: backup, Stream Deck closed, written and checked, reopened."""
        status.config(text="Installing the profile - Stream Deck closes and reopens for a few seconds...")
        send_btn.state(["disabled"])

        def finish(res):
            send_btn.state(["!disabled"])
            if isinstance(res, Exception):
                status.config(text=f"Installing failed: {res}")
                return messagebox.showerror("Send to Stream Deck", str(res))
            status.config(text=f"Installed profile '{name}' with {n} sound(s) and checked it was "
                               "written; Stream Deck reopened. Pick it in Stream Deck's profile list.")
        ui_background(page, lambda: sd_push(writes, []), finish)

    def install(name, items):
        """Sounds accepted from a linked computer, installed into Stream Deck here as a new profile the way Send to
        Stream Deck with Install directly does (this PC's deck and folder choices; no question: accepted already).
        ValueError when it can't be done here."""
        if not SD_EXE.exists():
            raise ValueError("there's no Stream Deck app on this PC to install it into")
        model, dev_id, _, _ = devices[k["device"].get()]
        push(sd_install(name, (model, dev_id, *deck_size()), items, {}, folders=folders_opt()), name, len(items))

    def send():
        if not sounds:
            return messagebox.showinfo("Nothing to send", "Add some sounds first.")
        missing = [str(s["path"]) for s in sounds if not Path(s["path"]).is_file()]
        if missing:
            return messagebox.showerror("Missing files", "These sounds no longer exist:\n" + "\n".join(missing[:20]))
        save()
        model, dev_id, _, _ = devices[k["device"].get()]
        name = k["profile"].get().strip() or "Soundboard"
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name)
        if direct.get() and SD_EXE.exists():
            try:
                writes = sd_install(name, (model, dev_id, *deck_size()), to_send(), keys, folders=folders_opt())
            except ValueError as e:
                return messagebox.showerror("Mapping", str(e))
            if sd_running() and not messagebox.askyesno(
                    "Close Stream Deck", "Stream Deck must close for a moment to add the profile "
                    "(it rewrites its profiles when it exits).\nClose it now and reopen it after?"):
                return
            return push(writes, name, len(sounds))
        try:
            out = sd_profile(SD_OUT / f"{safe}.streamDeckProfile", name, (model, dev_id, *deck_size()), to_send(), keys,
                             folders_opt())
        except ValueError as e:
            return messagebox.showerror("Mapping", str(e))
        except OSError as e:
            return messagebox.showerror("Profile", f"Couldn't write the profile:\n{e}")
        try:
            os.startfile(out)  # Stream Deck owns .streamDeckProfile: it opens its import prompt
            status.config(text=f"Sent {len(sounds)} sound(s) to Stream Deck - confirm the import there. File: {out}")
        except OSError:
            status.config(text=f"Stream Deck app not found. Profile saved: {out} (double-click it once installed)")

    for text, cmd, tip in (("Add files...", lambda: add(ui_pick_sounds(page, "Select sounds")), "Pick sound files"),
                           ("Add folder...", lambda: add(folder_sounds("Add every sound in folder")),
                            "Every sound file in a folder"),
                           ("Add Channel Mirror outputs", lambda: add(made) if made else messagebox.showinfo(
                               "No outputs yet", "Run the Channel Mirror tab first; the files it writes show up here."),
                            "The files the Channel Mirror tab wrote this session")):
        b = ttk.Button(adders, text=text, command=cmd)
        b.pack(side="left", padx=(0, 6))
        Tip(b, tip)
    for text, cmd in (("Preview", preview), ("Up", lambda: move(-1)), ("Down", lambda: move(1)),
                      ("Unassign", unassign), ("Remove", remove),
                      ("Clear all", lambda: (sounds.clear(), keys.clear(), show([])))):
        ttk.Button(tools, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 4))
    b = ttk.Button(lvl, text="Check levels...", style="Tool.TButton", command=check_levels)
    b.pack(side="left", padx=(0, 4))
    Tip(b, "Listen to the selected sounds (or all) and list how loud each one plays against your OBS levels; "
           "Tune in the list sets their volumes.")
    ttk.Combobox(lvl, textvariable=tune_v, values=list(SD_TUNE), state="readonly", width=34).pack(side="left", padx=4)
    ttk.Button(lvl, text="My OBS levels...", style="Tool.TButton",
               command=lambda: ui_obs_levels(page, cfg)).pack(side="left", padx=4)
    lvl2 = ttk.Frame(box)  # a second row, so these stay on screen in a narrow window
    lvl2.pack(fill="x", pady=(4, 0), after=lvl)
    ttk.Checkbutton(lvl2, text="Tune new sounds as they're added", variable=auto_tune).pack(side="left")
    b = ttk.Button(lvl2, text="Scale volume...", style="Tool.TButton", command=lambda: scale_volume())
    b.pack(side="left", padx=4)
    Tip(b, "Multiply the volume of the selected sounds (or all) by a percentage, keeping them in proportion.")

    def scale_volume():
        ss = [sounds[i] for i in picked()] or sounds
        if not ss:
            return messagebox.showinfo("Scale volume", "Add sounds first.")
        from tkinter import simpledialog
        pct = simpledialog.askinteger("Scale volume", f"Scale the volume of {len(ss)} sound(s) by what % ?\n"
                                      "(50 = half each volume setting, 150 = half as much again; 100 at most)",
                                      initialvalue=80, minvalue=1, maxvalue=400, parent=page)
        if pct:
            for s in ss:
                s["volume"] = max(0, min(100, round(int(s["volume"]) * pct / 100)))
            show()
            status.config(text=f"Scaled the volume of {len(ss)} sound(s) by {pct}%.")
    # one key per sound, in folders (instead of the key mapping)
    fold = ttk.Frame(box)
    fold.pack(fill="x", pady=(6, 0), before=lvl)
    fold_on = tk.BooleanVar(value=sc.get("folders", False))
    fper = tk.IntVar(value=sc.get("folder_per", 11))
    ftitle = tk.StringVar(value=sc.get("folder_title", "Sounds"))
    fplay = tk.StringVar(value=sc.get("folder_play", "Play / Stop"))
    ttk.Checkbutton(fold, text="One key per sound, in folders of", variable=fold_on).pack(side="left")
    ttk.Spinbox(fold, textvariable=fper, from_=1, to=99, width=4).pack(side="left", padx=4)
    ttk.Label(fold, text="named").pack(side="left")
    ttk.Entry(fold, textvariable=ftitle, width=14).pack(side="left", padx=4)
    for text, m in (("Play once", "Play / Stop"), ("Loop", "Loop / Stop"), ("As set per sound", "as set")):
        ttk.Radiobutton(fold, text=text, variable=fplay, value=m).pack(side="left", padx=(6, 0))
    Tip(fold, "Every sound gets its own key inside a folder, in list order; when a folder is full the next one is "
              "made (name, name 2...). The folder keys fill the page. Off = keys as mapped on the grid.")
    for x in (fold_on, fper, ftitle):
        x.trace_add("write", lambda *_: draw())
    for text, cmd in (("Add folder...", folder_to_key), ("Add files...", files_to_key),
                      ("Selected sounds here", lambda: assign(picked(), cur.get()) if picked() else
                       messagebox.showinfo("Assign", "Select sounds in the list first.")),
                      ("Clear key", clear_key)):
        n_ = len(kbtns.grid_slaves())  # two by two: all four stay on screen in a narrow window
        ttk.Button(kbtns, text=text, style="Tool.TButton", command=cmd).grid(row=n_ // 2, column=n_ % 2,
                                                                             sticky="ew", padx=(0, 4), pady=(0, 4))
    kbtns.columnconfigure((0, 1), weight=1)
    apply_btn.config(command=apply)
    send_btn = ttk.Button(runbar, text="Send to Stream Deck", style="Accent.TButton", command=send)
    send_btn.pack(side="left")
    direct = tk.BooleanVar(value=sc.get("direct", SD_EXE.exists()))
    ttk.Checkbutton(runbar, text="Install directly (no import prompt; restarts Stream Deck)", variable=direct,
                    state="normal" if SD_EXE.exists() else "disabled").pack(side="left", padx=12)
    status.pack(side="left", fill="x", expand=True, padx=6)
    tree.bind("<<TreeviewSelect>>", on_pick)
    ui_keys(page, {"<Delete>": remove, "<Control-a>": lambda: tree.selection_set(tree.get_children()),
                   "<space>": preview})
    k["device"].trace_add("write", on_device)
    for x in (k["cols"], k["rows"]):
        x.trace_add("write", lambda *_: draw())
    kind_v.trace_add("write", key_changed)
    title_v.trace_add("write", key_changed)
    if "cols" not in sc:
        on_device()
    draw()
    save.add = add  # accepted files from the Link tab

    def put(items):
        """Sounds with their keys and playback settings (accepted from a linked computer) -> the sounds added."""
        new = [{"output": "", **x, "path": Path(x["path"])} for x in items]
        sounds.extend(new)
        show()
        return new
    save.put, save.sounds, save.install, save.picked = put, sounds, install, picked
    save.name = lambda: k["profile"].get().strip()  # the profile name Send to Stream Deck would use
    save.device = lambda: k["device"].get()
    save.more = lambda: []  # more right-click entries for the sound list (Send to <linked PC>)
    return save
