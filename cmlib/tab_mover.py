"""The mover tab."""
from .deck import (
    SD_FOLDER,
    SD_PARENT,
    sd_clone_folders,
    sd_keypad,
    sd_kind,
    sd_missing,
    sd_order,
    sd_place,
    sd_renew,
    sd_sounds,
    sd_title,
)
from .ui import DeckGrid, UI


def mover_tab(page, deck):
    """The Key mover tab: copy or move keys of any kind (sounds, Multi / Random, folders with everything inside,
    hotkeys and other plugin actions, with their icons) between pages, profiles and devices. Two decks side by side;
    click keys on one side, click where they go on the other (or one key to start from), Copy / Move. Keys in use on
    the target side are kept: the next free key, replace, or skip, as chosen. Changes go through the editor tab
    (deck = its shared API): one undo, sent to Stream Deck from there or automatically."""
    import copy
    import tkinter as tk
    from tkinter import ttk
    if deck is None:
        ttk.Label(page, text="No local Stream Deck install found.").pack(padx=20, pady=20, anchor="w")
        return {}
    POLICIES = {"Put it on the next free key": "next", "Replace what's there": "replace", "Skip it": "skip"}
    ttk.Label(page, text="Click keys on one side (click again to drop one), then on the other side click where they "
                         "go - one key to start from (they keep their layout), or a key for each, in order. Then "
                         "Copy or Move. Folders take everything inside them; icons come along.",
              style="Hint.TLabel", wraplength=1100, justify="left").pack(anchor="w", padx=12, pady=(10, 0))
    body = ttk.Frame(page, padding=(12, 6))
    body.pack(fill="both", expand=True)
    sides = []

    def side(parent, name):
        s = {"prof": tk.StringVar(value=(deck["profiles"]() or [""])[0]), "page": tk.StringVar(), "sel": []}
        f = ttk.LabelFrame(parent, text=name)
        f.pack(fill="both", expand=True)
        r = ttk.Frame(f)
        r.pack(fill="x")
        ttk.Label(r, text="Profile").pack(side="left")
        ttk.Combobox(r, textvariable=s["prof"], values=deck["profiles"](), state="readonly", width=46).pack(
            side="left", padx=6)
        r2 = ttk.Frame(f)
        r2.pack(fill="x", pady=(4, 0))
        ttk.Label(r2, text="Page").pack(side="left")
        s["page_cb"] = ttk.Combobox(r2, textvariable=s["page"], state="readonly", width=40)
        s["page_cb"].pack(side="left", padx=(18, 6))
        s["pages"] = lambda: deck["pages"](s["prof"].get()) if s["prof"].get() else []
        s["cur"] = lambda: dict(s["pages"]()).get(s["page"].get())
        s["keys"] = lambda: deck["keys"](s["cur"]()) if s["cur"]() else {}

        def size():
            c_, r_ = deck["grid"](s["prof"].get()) if s["prof"].get() else (5, 3)
            for k in s["keys"]():
                x, y = map(int, k.split(","))
                c_, r_ = max(c_, x + 1), max(r_, y + 1)
            return c_, r_
        s["size"] = size

        def tile(pos):
            a = s["keys"]().get(pos)
            c, r_ = map(int, pos.split(","))
            if pos in s["sel"]:
                n = s["sel"].index(pos) + 1
                return (f"{n}: " + ((sd_title(a).replace(chr(10), " ") or sd_kind(a))[:14] if a else "here")), \
                    UI["accent"], UI["on_accent"]
            if a:
                bg = UI["missing"] if sd_missing(a) else UI["sound"] if sd_sounds(a) else UI["other"]
                return f"{(sd_title(a).replace(chr(10), ' ') or '-')[:22]}\n{sd_kind(a)[:16]}", bg, UI["text"]
            return f"{c + 1},{r_ + 1}", UI["empty"], UI["muted"]

        def click(pos, _e=None):
            s["sel"].remove(pos) if pos in s["sel"] else s["sel"].append(pos)
            redraw()
        g = DeckGrid(f, tile, on_click=click, tip=lambda pos: (
            f"{sd_title(s['keys']()[pos]).replace(chr(10), ' ') or '(no name)'} - {sd_kind(s['keys']()[pos])}"
            if s["keys"]().get(pos) else "Free key"))
        g.frame.pack(pady=8)
        s["grid"] = g
        s["info"] = ttk.Label(f, style="Hint.TLabel")
        s["info"].pack(anchor="w")
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(4, 0))
        ttk.Button(b, text="Select every key", style="Tool.TButton", command=lambda: (
            s["sel"].clear(), s["sel"].extend(sorted((k for k, a in s["keys"]().items()
                                                      if a and a.get("UUID") != SD_PARENT), key=sd_order)),
            redraw())).pack(side="left")
        ttk.Button(b, text="Select none", style="Tool.TButton",
                   command=lambda: (s["sel"].clear(), redraw())).pack(side="left", padx=4)

        def on_prof(*_):
            s["page_cb"].config(values=[n for n, _ in s["pages"]()])
            if s["page"].get() not in dict(s["pages"]()):
                s["page"].set(s["pages"]()[0][0] if s["pages"]() else "")
            s["sel"].clear()
            redraw()
        s["prof"].trace_add("write", on_prof)
        s["page"].trace_add("write", lambda *_: (s["sel"].clear(), redraw()))
        s["on_prof"] = on_prof
        return s
    lf, mid, rf = ttk.Frame(body), ttk.Frame(body), ttk.Frame(body)
    lf.pack(side="left", fill="both", expand=True)
    mid.pack(side="left", fill="y", padx=12)
    rf.pack(side="left", fill="both", expand=True)
    L, R = side(lf, "Left deck"), side(rf, "Right deck")
    sides += [L, R]
    policy = tk.StringVar(value=next(iter(POLICIES)))
    keep = tk.BooleanVar(value=True)
    ttk.Label(mid, text="").pack(pady=30)
    for text, a, b, move in (("Copy  >>", L, R, False), ("Move  >>", L, R, True),
                             ("<<  Copy", R, L, False), ("<<  Move", R, L, True)):
        ttk.Button(mid, text=text, width=14, style="Accent.TButton" if not move else "TButton",
                   command=lambda a=a, b=b, move=move: transfer(a, b, move)).pack(pady=4)
    ttk.Label(mid, text="WHEN A TARGET KEY IS IN USE", style="Field.TLabel").pack(anchor="w", pady=(18, 0))
    ttk.Combobox(mid, textvariable=policy, values=list(POLICIES), state="readonly", width=28).pack(anchor="w")
    ttk.Checkbutton(mid, text="Keep their layout", variable=keep).pack(anchor="w", pady=(8, 0))
    ttk.Button(mid, text="Undo", command=deck["undo"]).pack(anchor="w", pady=(18, 0))
    status = ttk.Label(page, style="Status.TLabel", anchor="w", wraplength=1200, justify="left")
    status.pack(fill="x", padx=12, pady=(0, 8))

    def redraw():
        for s in sides:
            if s["cur"]():
                s["grid"].draw(*s["size"]())
            used = sum(1 for a in s["keys"]().values() if a)
            c_, r_ = s["size"]()
            s["info"].config(text=f"{used} of {c_ * r_} keys in use; {len(s['sel'])} selected")

    def transfer(src, dst, move):
        keys = [k for k in src["sel"] if src["keys"]().get(k) and src["keys"]()[k].get("UUID") != SD_PARENT]
        if not keys:
            return status.config(text="Click the keys to copy or move first (on the side they're on). The back "
                                      "(Parent Folder) key of a folder stays where it is.")
        if not dst["cur"]():
            return status.config(text="Pick the page they go to.")
        same = src["cur"]() == dst["cur"]()
        picks = [k for k in dst["sel"] if not (same and k in keys)]
        cols, rows = dst["size"]()
        view = {k: a for k, a in dst["keys"]().items() if not (same and move and k in keys)}  # moving frees them
        plan = sd_place(keys, view, cols, rows, picks[0] if picks else "0,0", picks,
                        POLICIES[policy.get()], keep.get())
        if not any(plan.values()):
            return status.config(text="No room: every target key is in use (or skipped). Pick other keys or a "
                                      "different 'when in use' choice.")
        sp, dp = src["cur"](), dst["cur"]()
        one_profile = src["prof"].get() == dst["prof"].get()
        by_id = {p.parent.name.lower(): p for _, p in deck["pages"](src["prof"].get())}
        tree, dirs = {}, {}

        def walk(a):  # the folder pages a key leads to, folders in folders too
            pid = str((a.get("Settings") or {}).get("ProfileUUID", "")).lower()
            if a.get("UUID") != SD_FOLDER or pid in tree or pid not in by_id:
                return
            tree[pid] = copy.deepcopy(deck["page"](by_id[pid]))
            dirs[pid] = by_id[pid].parent
            for c in tree[pid].get("Controllers") or []:
                for b in (c.get("Actions") or {}).values():
                    if b:
                        walk(b)
        for k in keys:
            walk(src["keys"]()[k])
        if move and one_profile and dp.parent.name.lower() in tree:
            return status.config(text="A folder can't be moved into itself (or a folder inside it). Copy it "
                                      "instead, or move it to another page.")
        folder = deck["folder"](dst["prof"].get())

        def put(edit):
            src_kp = sd_keypad(edit(sp))
            dst_kp = sd_keypad(edit(dp))
            acts = {k: src_kp[k] for k in keys}
            if move:
                for k, to in plan.items():
                    if to:
                        src_kp.pop(k, None)
            for k, to in plan.items():
                if not to:
                    continue
                a = copy.deepcopy(acts[k])
                if not (move and one_profile):  # a copy, or into another profile: its own folder pages
                    sd_renew(a)
                    ids = {}
                    for pid, pg in sd_clone_folders(a, tree, ids=ids).items():
                        f = folder / "Profiles" / pid.upper() / "manifest.json"
                        edit(f, pg)
                        deck["icons"](dirs.get(ids[pid]), f.parent, pg)
                deck["icons"](sp.parent, dp.parent, a)
                dst_kp[to] = a
        done = {k: to for k, to in plan.items() if to}
        names = lambda s: f"{s['prof'].get().replace('[connected] ', '')} / {s['page'].get()}"
        msg = (f"{'Moved' if move else 'Copied'} {len(done)} key(s) from {names(src)} to {names(dst)}" +
               (f"; {sum(1 for t in plan.values() if not t)} skipped" if len(done) < len(plan) else "") +
               " (" + ", ".join("{} -> {}".format(*("{},{}".format(*(int(x) + 1 for x in q.split(","))) for q in kv))
                                 for kv in done.items()) + ")")
        deck["change"](put, msg)
        src["sel"].clear()
        dst["sel"].clear()
        redraw()
        status.config(text=msg + ". Undo is here or in the Stream Deck editor tab; it's sent to Stream Deck from "
                                 "there (or automatically).")
    deck["listeners"].append(lambda: [s["page_cb"].config(values=[n for n, _ in s["pages"]()]) for s in sides]
                             and redraw())
    for s in sides:
        s["on_prof"]()
    return {"sides": sides, "transfer": transfer}
