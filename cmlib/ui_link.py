"""UI pieces for links and linked computers used by every tab: incoming prompts, linked bar, library."""
import shutil
from pathlib import Path
from .mirror import clean_name, natural
from .deck import sd_folder_map, sd_keypad, sd_kind, sd_place, sd_sounds, sd_title
from .vts import VTS_EXT
from .link import LINK_INBOX, LINK_TARGETS, link_safe_name
from .peers import (
    LINK_AUDIO,
    PEER_FILES,
    link_default_target,
    library_items,
    link_check_file,
    peer_apply,
    peer_browse,
    peer_check_files,
    peer_download,
    peer_fetch,
    peer_library,
    peer_pack,
    peer_proposal,
)
from .ui import DeckGrid, UI, px


def peer_batches(target, spec, files, size=200):
    """A proposal split to go in batches of up to size files (the most one proposal carries): [(files, spec)], each
    accepted there on its own, the files each points at numbered from 0 again. ValueError for one key with more."""
    files = list(files)
    if len(files) <= size:
        return [(files, spec)]
    if target == "soundboard":  # a sound per file; an installed profile per batch: "name", "name 2"...
        out = []
        for k, i in enumerate(range(0, len(spec["sounds"]), size)):
            part = spec["sounds"][i:i + size]
            sp = dict(spec, sounds=[dict(s, file=n) for n, s in enumerate(part)])
            if spec.get("name") and k:
                sp["name"] = f"{spec['name'][:55]} {k + 1}"
            out.append(([files[s["file"]] for s in part], sp))
        return out
    if target != "edit":
        return [(files[i:i + size], spec) for i in range(0, len(files), size)]
    out, fs, ops = [], [], []
    for o in spec["ops"]:
        n = len(o.get("files", [])) + len(o.get("sounds", [])) + len(o.get("icons", {}))
        if n > size:
            raise ValueError(f"key {o['key']} has {n} files - {size} at most go in one go")
        if fs and len(fs) + n > size:
            out.append((fs, dict(spec, ops=ops)))
            fs, ops = [], []
        o = dict(o)
        num = lambda i: fs.append(files[i]) or len(fs) - 1
        for k in ("files", "sounds"):
            if k in o:
                o[k] = [num(i) for i in o[k]]
        if "icons" in o:
            o["icons"] = {r: num(i) for r, i in o["icons"].items()}
        ops.append(o)
    return out + [(fs, dict(spec, ops=ops))]


def ui_put_icons(icons, op, files, src, page_dir, action, made, folder):
    """A carried key's icons placed here (op["icons"]: "Images/x.png" its own, "<page id>/Images/x.png" those on its
    folder pages): copied to src, then icons(src dir, page dir, obj) - the editor's - for the key and for each of its
    new folder pages (made = {new page id: page json}; folder = the profile's folder)."""
    for rel, fi in op["icons"].items():  # a folder page's under "p_<page id>" (never a device name like "con")
        to = Path(src) / (rel if rel.startswith("Images/") else "p_" + rel)
        to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(files[fi], to)
    icons(src, page_dir, action)
    for new, old in sd_folder_map(op["action"], action, op["pages"], made).items():
        icons(Path(src) / f"p_{old}", Path(folder) / "Profiles" / new.upper(), made[new])


def ui_send_items(hub, pick):
    """Right-click entries "Send to <linked PC>", one per linked computer, for a file list: pick() -> (destination,
    files, proposal) for its selected rows (ValueError = can't send that: said in the computer's activity)."""
    def go(p):
        try:
            got = pick()
        except ValueError as e:
            return hub["act"](p, f"not sent: {e}")
        if got:
            hub["send"](p, *got)
    return [(f"Send to {p['name']}", lambda p=p: go(p)) for p in hub["peers"]()] or [
        ("Send to a linked computer (link one first)", None)]


def ui_send_menu(tree, hub, pick):
    """A file list's right-click menu (one that has none of its own): Send to <linked PC>."""
    from .ui import ui_menu

    def menu(e):
        row = tree.identify_row(e.y)
        if row and row not in tree.selection():
            tree.selection_set(row)
        if tree.selection():
            ui_menu(tree, e, ui_send_items(hub, pick))
    tree.bind("<Button-3>", menu, add="+")


def ui_send_linked(parent, hub, files):
    """Files from Explorer's Send to > Channel Mirror (linked computers): which linked computer, and which of its
    tabs they go to; Send sends them as a proposal (accepted there; more than 200 go in batches, each its own)."""
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(parent)
    win.title("Send to a linked computer")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    files = [Path(f) for f in files]
    ttk.Label(body, text=f"{len(files)} file(s): " + ", ".join(f.name for f in files[:8]) +
              (" ..." if len(files) > 8 else ""), wraplength=640, justify="left").pack(anchor="w")
    named = {f"{p['name']} ({p['host']})": p["id"] for p in hub["peers"]()}  # by id: two may share a name
    tabs = {LINK_TARGETS[k]: k for k in ("import", "soundboard", "vts", "mirror", "music", "files")}
    who = tk.StringVar(value=next(iter(named), ""))
    to = tk.StringVar(value=LINK_TARGETS[link_default_target(files)] if files else LINK_TARGETS["import"])
    for text, var, values in (("To", who, list(named)), ("Into its", to, list(tabs))):
        r = ttk.Frame(body)
        r.pack(fill="x", pady=(8, 0))
        ttk.Label(r, text=text, width=8).pack(side="left")
        ttk.Combobox(r, textvariable=var, values=values, state="readonly", width=40).pack(side="left")
    ttk.Label(body, style="Hint.TLabel", wraplength=640, justify="left", text=(
        "It waits there until someone accepts it. Up to 200 files go in one proposal; more are sent in batches of 200, "
        "each one accepted there on its own.")).pack(anchor="w", pady=(10, 0))
    status = ttk.Label(body, style="Hint.TLabel", wraplength=640, justify="left",
                       text="" if named else "No linked computers yet - link one in the Linked computers tab.")
    status.pack(anchor="w", pady=(4, 0))

    def send():
        p = next((x for x in hub["peers"]() if x["id"] == named.get(who.get())), None)
        if not p:
            return status.config(text="Pick a linked computer (link one in the Linked computers tab first).")
        target = tabs[to.get()]
        ok = [f for f in files if f.suffix.lower() in PEER_FILES[target]]
        spec = {"sounds": [{"file": i, "title": clean_name(f.stem)[:60]} for i, f in enumerate(ok)]} \
            if target == "soundboard" else {}
        try:
            if not ok:
                raise ValueError(f"none of these files go to {to.get()}")
            peer_check_files(target, spec, ok)  # each file's real content, before anything goes
        except (ValueError, OSError) as e:
            return status.config(text=f"Can't send that: {e}")
        if len(ok) < len(files):
            hub["act"](p, f"{len(files) - len(ok)} file(s) of another type left out (not for its {to.get()})")
        hub["send"](p, target, ok, spec)
        win.destroy()
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(12, 0))
    ttk.Button(bar, text="Send", style="Accent.TButton", command=send).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    return {"win": win, "who": who, "to": to, "send": send, "status": status}


def ui_incoming(parent, files, target, source):
    """Files arrived (from another device or a link): show them and where they'd go. Returns the chosen
    destination, or None when declined."""
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(parent)
    win.title("Files arrived")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=f"{len(files)} file(s) from {source}:", font=("Segoe UI", 11, "bold")).pack(anchor="w")

    def size(f):
        try:
            return f"{Path(f).stat().st_size / 1e6:.1f} MB"
        except OSError:
            return "?"
    ttk.Label(body, text="\n".join(f"  {Path(f)}  ({size(f)})" for f in files[:12])  # the full path: where it is
              + (f"\n  ...and {len(files) - 12} more" if len(files) > 12 else ""), justify="left",
              wraplength=900).pack(anchor="w", pady=(4, 10))
    names = {v: k for k, v in LINK_TARGETS.items()}
    to = tk.StringVar(value=LINK_TARGETS.get(target, next(iter(LINK_TARGETS.values()))))
    r = ttk.Frame(body)
    r.pack(fill="x")
    ttk.Label(r, text="Put them in").pack(side="left")
    ttk.Combobox(r, textvariable=to, values=list(names), state="readonly", width=40).pack(side="left", padx=6)
    ttk.Label(body, text="Nothing is placed until you accept. Declining deletes the received copies.",
              style="Hint.TLabel").pack(anchor="w", pady=(8, 0))
    res = [None]
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(12, 0))
    ttk.Button(bar, text="Accept", style="Accent.TButton",
               command=lambda: (res.__setitem__(0, names[to.get()]), win.destroy())).pack(side="right")
    ttk.Button(bar, text="Decline", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    try:
        win.wait_visibility()
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()
    return res[0]


def ui_proposal(parent, title, lines):
    """A linked computer's proposal: what it would do here, Accept / Decline. True when accepted."""
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(parent)
    win.title("From a linked computer")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    ttk.Label(win, text=f" {title} ", style="Remote.TLabel", anchor="w").pack(fill="x")
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="\n".join(lines[:30]) + (f"\n...and {len(lines) - 30} more" if len(lines) > 30 else ""),
              justify="left", wraplength=900).pack(anchor="w")
    ttk.Label(body, text="Nothing changes here until you accept. Declining deletes what was received.",
              style="Hint.TLabel").pack(anchor="w", pady=(10, 0))
    res = [False]
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(12, 0))
    ttk.Button(bar, text="Accept", style="Accent.TButton",
               command=lambda: (res.__setitem__(0, True), win.destroy())).pack(side="right")
    ttk.Button(bar, text="Decline", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    try:
        win.wait_visibility()
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()
    return res[0]


def ui_linked_bar(page, hub, send=None, extra=(), add=None, exts=None):
    """The strip at the foot of a tab: which computer the tab works on (This PC), "From Channel Mirror..." (files the
    app already knows, here or on a linked computer) when add(files) is given, a linked computer to send the tab's
    work to (send() -> (destination, files, proposal) or None; ValueError = can't send that), the tab's own
    linked-computer tools (extra: (text, f(peer))), and what's going back and forth with that computer."""
    import tkinter as tk
    from tkinter import ttk
    bar = ttk.Frame(page, padding=(10, px(4), 10, px(2)))
    head = page.children.get("head")  # the page's header (ui_page): right under it
    kids = [k for k in page.pack_slaves() if k is not head]
    bar.pack(side="top", fill="x", **({"after": head} if head else {"before": kids[0]} if kids else {}))
    ttk.Label(bar, text=" Working on: This PC ", style="Local.TLabel").pack(side="left")
    if add:
        ttk.Button(bar, text="From Channel Mirror...", style="Tool.TButton",
                   command=lambda: add(ui_library(page, hub, exts) or [])).pack(side="left", padx=(8, 0))
    who = tk.StringVar()
    ttk.Label(bar, text="Linked computer").pack(side="left", padx=(12, 4))
    cb = ttk.Combobox(bar, textvariable=who, state="readonly", width=16, postcommand=lambda: refresh())
    cb.pack(side="left")
    note = ttk.Label(bar, style="Hint.TLabel")

    def peer():
        return next((p for p in hub["peers"]() if p["name"] == who.get()), None)

    def chosen():
        p = peer()
        if not p:
            note.config(text="Link a computer first (Linked computers tab).")
        return p

    def show():
        p = peer()
        note.config(text=(hub["activity"].get(p["id"]) or hub["label"](p)) if p else
                    "No linked computers yet.")

    def refresh():
        names = [p["name"] for p in hub["peers"]()]
        cb.config(values=names)
        if who.get() not in names:
            who.set(names[0] if names else "")
        show()

    def go():
        p = chosen()
        if not p:
            return
        try:
            got = send()
        except ValueError as e:
            return note.config(text=f"Can't send that: {e}")
        if got:
            hub["send"](p, *got)
    if send:
        ttk.Button(bar, text="Send there", style="Tool.TButton", command=go).pack(side="left", padx=(6, 0))
    for text, fn in extra:
        ttk.Button(bar, text=text, style="Tool.TButton", command=lambda f=fn: (p := chosen()) and f(p)).pack(
            side="left", padx=(6, 0))
    note.pack(side="left", padx=8, fill="x", expand=True)
    who.trace_add("write", lambda *_: show())
    hub["listeners"].append(refresh)
    refresh()
    return {"bar": bar, "who": who, "note": note, "go": go}


def ui_library(parent, hub, exts=None, title="Pick from Channel Mirror", source=None):
    """Files Channel Mirror already knows - on this PC or a linked computer - grouped, searchable, several at once.
    Only the types the tool takes (exts). A linked computer's picks are fetched, checked, and kept in Incoming.
    Returns the files (natural order) or []."""
    import time
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    banner = ttk.Label(win, anchor="w")
    banner.pack(fill="x")
    body = ttk.Frame(win, padding=12)
    body.pack(fill="both", expand=True)
    top = ttk.Frame(body)
    top.pack(fill="x")
    src, q = tk.StringVar(value=source or "This PC"), tk.StringVar()
    ttk.Label(top, text="From").pack(side="left")
    ttk.Combobox(top, textvariable=src, state="readonly", width=20,
                 values=["This PC"] + [p["name"] for p in hub["peers"]()]).pack(side="left", padx=6)
    ttk.Label(top, text="Search").pack(side="left", padx=(12, 0))
    ttk.Entry(top, textvariable=q, width=24).pack(side="left", padx=6)
    if exts:
        ttk.Label(top, text="Only: " + " ".join(sorted(exts)[:12]) + (" ..." if len(exts) > 12 else ""),
                  style="Hint.TLabel").pack(side="left", padx=6)
    tv = ttk.Treeview(body, columns=("size",), show="tree headings", selectmode="extended", height=14)
    tv.heading("#0", text="File")
    tv.heading("size", text="Size")
    tv.column("#0", width=520)
    tv.column("size", width=90, anchor="e")
    tv.tag_configure("missing", foreground=UI["dis"])
    tv.pack(fill="both", expand=True, pady=8)
    status = ttk.Label(body, style="Hint.TLabel")
    status.pack(anchor="w")
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(6, 0))
    rows, cache, res = {}, {}, [[]]

    def peer():
        return next((p for p in hub["peers"]() if p["name"] == src.get()), None)

    def fill(*_):
        tv.delete(*tv.get_children())
        rows.clear()
        p = peer()
        banner.config(text=f" Picking from: {hub['label'](p) if p else 'This PC'} ",
                      style="Remote.TLabel" if p else "Local.TLabel")
        if p is None:
            items = [(g, f, ok, f"{f.stat().st_size / 1e6:.1f} MB" if ok else "missing")
                     for g, f, ok in library_items(hub["library"](), exts, q.get())]
        elif p["id"] in cache:
            got = cache[p["id"]]
            items = [(g, Path(link_safe_name(x["name"])), True, f"{x['size'] / 1e6:.1f} MB", x["token"])
                     for g, xs in got.items() for x in xs
                     if (not exts or Path(x["name"]).suffix.lower() in exts) and q.get().lower() in x["name"].lower()]
        else:
            status.config(text=f"Asking {p['name']}...")
            return hub["run"](lambda: peer_library(p, hub["me"]()), lambda r: (
                status.config(text=f"Couldn't list {p['name']}: {r}") if isinstance(r, Exception) else
                (cache.__setitem__(p["id"], r), fill())))
        groups = {}
        for it in items:
            g = it[0]
            if g not in groups:
                groups[g] = tv.insert("", "end", text=g, open=True)
            iid = tv.insert(groups[g], "end", text=it[1].name, values=(it[3],), tags=() if it[2] else ("missing",))
            rows[iid] = it
        status.config(text=f"{len(rows)} file(s). Ctrl / Shift + click picks several; greyed ones are missing.")

    def ok():
        p, out = peer(), []
        picked = [rows[i] for i in tv.get_children("") for i in tv.get_children(i)
                  if i in tv.selection() and rows[i][2]]
        if p is None:
            out = [it[1] for it in picked]
        else:  # fetched now (signed, checked: type, real content, size), kept in Incoming
            dst = LINK_INBOX / "Received" / f"{time.strftime('%Y-%m-%d %H-%M-%S')} from {link_safe_name(p['name'] + '.png')[:-4]}"
            dst.mkdir(parents=True, exist_ok=True)
            bad = []
            for i, it in enumerate(picked):
                f = dst / f"{i + 1:03d} {it[1].name}"
                try:
                    peer_download(p, hub["me"](), it[4], f)
                    out.append(link_check_file(f, exts))
                except (OSError, ValueError) as e:
                    Path(f).unlink(missing_ok=True)
                    bad.append(f"{it[1].name}: {e}")
            if bad:
                status.config(text="Not fetched: " + "; ".join(bad[:5]))
                if not out:
                    return
        res[0] = sorted(out, key=natural) if p is None else out
        win.destroy()
    ttk.Button(bar, text="Add", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    src.trace_add("write", fill)
    q.trace_add("write", fill)
    tv.bind("<Double-1>", lambda e: ok())
    fill()
    win.bind("<Escape>", lambda e: win.destroy())
    try:
        win.wait_visibility()
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()
    return res[0]


def ui_remote_deck(parent, hub, peer, listing, deck=None):
    """A linked computer's Stream Decks and profiles beside this PC's: browse its pages, stage changes to its keys
    (sounds on a key, rename, clear, keys copied from this PC - folders and icons included) and send them as one
    proposal; or copy its keys here. Nothing changes there until it's accepted there; then it goes to its Stream
    Deck app (backup first)."""
    import copy
    import tkinter as tk
    from tkinter import filedialog, simpledialog, ttk
    win = tk.Toplevel(parent)
    win.title(f"{peer['name']} - Stream Deck (linked computer)")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    banner = ttk.Label(win, text=f" Working on: {hub['label'](peer)} ", style="Remote.TLabel", anchor="w")
    banner.pack(fill="x")
    devs = listing.get("devices") or []
    ttk.Label(win, style="Hint.TLabel", wraplength=1000, justify="left", text=f"Stream Decks on {peer['name']}: " + (
        "; ".join(d.get("name", "?") for d in devs) or "none found")).pack(anchor="w", padx=12, pady=(6, 0))
    body = ttk.Frame(win, padding=(12, 6))
    body.pack(fill="both", expand=True)
    remote = {p["profile"]: p for p in listing.get("deck") or []}
    ops = []  # staged: sent as one proposal
    R = {"prof": tk.StringVar(value=next(iter(remote), "")), "page": tk.StringVar(), "sel": []}
    L = {"prof": tk.StringVar(value=((deck["profiles"]() or [""])[0]) if deck else ""), "page": tk.StringVar(),
         "sel": []}
    status = ttk.Label(win, style="Status.TLabel", anchor="w", wraplength=1000, justify="left")

    def rpages():
        return (remote.get(R["prof"].get()) or {}).get("pages") or []

    def ridx():
        names = [p["name"] for p in rpages()]
        return names.index(R["page"].get()) if R["page"].get() in names else None

    def rkeys():
        i = ridx()
        keys = dict(rpages()[i]["keys"]) if i is not None else {}
        for o in ops:  # what the staged changes would make
            if o["page"] == i:
                if o["op"] == "clear":
                    keys.pop(o["key"], None)
                else:
                    keys[o["key"]] = {"title": o.get("title") or (keys.get(o["key"]) or {}).get("title", ""),
                                      "kind": "changed", "staged": True}
        return keys

    def rgrid():
        cols, rows = (remote.get(R["prof"].get()) or {}).get("grid") or (5, 3)
        for k in rkeys():
            c, r = map(int, k.split(","))
            cols, rows = max(cols, c + 1), max(rows, r + 1)
        return min(cols, 16), min(rows, 16)

    def lpages():
        return deck["pages"](L["prof"].get()) if deck and L["prof"].get() else []

    def lpage():
        return dict(lpages()).get(L["page"].get())

    def lkeys():
        return deck["keys"](lpage()) if lpage() else {}

    def lgrid():
        cols, rows = deck["grid"](L["prof"].get()) if deck and L["prof"].get() else (5, 3)
        for k in lkeys():
            c, r = map(int, k.split(","))
            cols, rows = max(cols, c + 1), max(rows, r + 1)
        return cols, rows

    def tile(keys, sel, pos):
        a = keys.get(pos)
        c, r = map(int, pos.split(","))
        if pos in sel:
            return (a or {}).get("title") or f"{c + 1},{r + 1}", UI["accent"], UI["on_accent"]
        if a and a.get("staged"):
            return f"{a.get('title') or 'changed'}\n(to send)", UI["auto"], UI["text"]
        if a:
            return f"{(a.get('title') or a.get('kind') or '').replace(chr(10), ' ')[:18]}", (
                UI["sound"] if a.get("sounds") else UI["other"]), UI["text"]
        return f"{c + 1},{r + 1}", UI["empty"], UI["muted"]

    def ltile(pos):
        a = lkeys().get(pos)
        k = {pos: {"title": sd_title(a) or sd_kind(a), "sounds": sd_sounds(a)}} if a else {}
        return tile(k, L["sel"], pos)

    def toggle(side, pos):
        side["sel"].remove(pos) if pos in side["sel"] else side["sel"].append(pos)
        draw()

    def side_box(parent_, text, s, values, tilefn):
        f = ttk.LabelFrame(parent_, text=text)
        f.pack(side="left", fill="both", expand=True, padx=(0, 8))
        r = ttk.Frame(f)
        r.pack(fill="x")
        ttk.Combobox(r, textvariable=s["prof"], values=values, state="readonly", width=30).pack(side="left")
        s["page_cb"] = ttk.Combobox(r, textvariable=s["page"], state="readonly", width=18)
        s["page_cb"].pack(side="left", padx=6)
        s["grid"] = DeckGrid(f, tilefn, on_click=lambda pos, e: toggle(s, pos))
        s["grid"].frame.pack(anchor="w", pady=6)
        return f
    if deck:
        side_box(body, "This PC", L, deck["profiles"](), ltile)
    side_box(body, f"{peer['name']} (linked)", R, list(remote), lambda pos: tile(rkeys(), R["sel"], pos))
    tools = ttk.Frame(win, padding=(12, 0))
    tools.pack(fill="x")
    status.pack(fill="x", padx=12, pady=(4, 0))
    send_b = ttk.Button(tools, text="Send changes", style="Accent.TButton", command=lambda: send())

    def draw():
        R["page_cb"].config(values=[p["name"] for p in rpages()])
        if R["page"].get() not in [p["name"] for p in rpages()]:
            R["page"].set(rpages()[0]["name"] if rpages() else "")
        R["grid"].draw(*rgrid())
        if deck:
            L["page_cb"].config(values=[n for n, _ in lpages()])
            if L["page"].get() not in [n for n, _ in lpages()]:
                L["page"].set(lpages()[0][0] if lpages() else "")
            L["grid"].draw(*lgrid())
        send_b.config(text=f"Send {len(ops)} change(s) to {peer['name']}" if ops else "Send changes")
        send_b.state(["!disabled"] if ops else ["disabled"])

    def stage(op, msg):
        i = ridx()
        if i is None:
            return status.config(text="Pick its page first.")
        ops.append(dict(op, page=i, page_name=R["page"].get()))
        status.config(text=msg + f" - not sent yet ({len(ops)} change(s) waiting; Send sends them).")
        draw()

    def one():
        if len(R["sel"]) != 1:
            status.config(text=f"Click one key on {peer['name']}'s side first.")
            return None
        return R["sel"][0]

    def sounds_on():
        k = one()
        files = k and list(filedialog.askopenfilenames(parent=win, title="Sounds for that key", filetypes=[
            ("Sounds", " ".join(f"*{e}" for e in LINK_AUDIO)), ("All files", "*.*")]))
        if files:
            try:
                for f in files:
                    link_check_file(f, LINK_AUDIO)
            except (ValueError, OSError) as e:
                return status.config(text=f"Can't send that: {e}")
            stage({"op": "sounds", "key": k, "files": files, "title": clean_name(Path(files[0]).stem)},
                  f"{len(files)} sound(s) on key {k}")

    def rename():
        k = one()
        t = k and simpledialog.askstring("Rename key", "New name for the key:", parent=win,
                                         initialvalue=(rkeys().get(k) or {}).get("title", ""))
        if t is not None and k:
            stage({"op": "title", "key": k, "title": t[:60]}, f"Key {k} named '{t[:60]}'")

    def clear():
        for k in list(R["sel"]):
            stage({"op": "clear", "key": k}, f"Key {k} cleared")
        R["sel"].clear()
        draw()

    def to_remote(move=False):
        keys = [k for k in L["sel"] if lkeys().get(k)]
        if not keys or ridx() is None:
            return status.config(text="Click keys on This PC's side, and pick the page they go to there.")
        by_id = {p.parent.name.lower(): p for _, p in lpages()}
        try:
            packed = peer_pack({k: copy.deepcopy(lkeys()[k]) for k in keys}, by_id, deck["page"], lpage().parent)
        except (ValueError, OSError) as e:
            return status.config(text=f"Can't send that: {e}")
        cols, rows = rgrid()
        picks = [k for k in R["sel"] if not rkeys().get(k)]
        plan = sd_place(keys, rkeys(), cols, rows, picks[0] if picks else "0,0", picks, "next", True)
        for k, to in plan.items():
            if to:
                ops.append({"op": "put", "key": to, "packed": packed[k], "page": ridx(), "page_name": R["page"].get(),
                            "title": sd_title(packed[k]["action"]) or sd_kind(packed[k]["action"]),
                            **({"from": (lpage(), k, copy.deepcopy(lkeys()[k]))} if move else {})})
        L["sel"].clear()
        R["sel"].clear()
        status.config(text=f"{sum(1 for t in plan.values() if t)} key(s) to {'move' if move else 'copy'} there - Send "
                           "sends them." + (" They're taken away here only once it's accepted and applied there."
                                            if move else ""))
        draw()

    def from_remote():
        keys, i, page = list(R["sel"]), ridx(), lpage()
        if not keys or i is None or not page:
            return status.config(text=f"Click keys on {peer['name']}'s side, and pick the page here they go to.")
        status.config(text=f"Copying {len(keys)} key(s) from {peer['name']}...")
        prof, pname = R["prof"].get(), R["page"].get()

        def work():
            import time
            pkg = peer_fetch(peer, hub["me"](), prof, i, pname, keys)
            dst = LINK_INBOX / "Received" / f"{time.strftime('%Y-%m-%d %H-%M-%S')} keys from {link_safe_name(peer['name'] + '.png')[:-4]}"
            dst.mkdir(parents=True, exist_ok=True)
            files = []
            if len(pkg.get("files") or []) > 200:
                raise ValueError("it offered too many files")
            for n, f in enumerate(pkg.get("files") or []):
                files.append(peer_download(peer, hub["me"](), f["token"], dst / f"{n + 1:03d} {link_safe_name(f['name'])}"))
            return pkg, files, dst

        def done(res):
            if isinstance(res, Exception):
                return status.config(text=f"Not copied: {res}")
            pkg, files, dst = res
            got = [k for k in keys if k in (pkg.get("actions") or {})]
            cols, rows = lgrid()
            picks = [k for k in L["sel"] if not lkeys().get(k)]
            plan = sd_place(got, lkeys(), cols, rows, picks[0] if picks else "0,0", picks, "next", True)
            put = [{"op": "put", "page": 0, "page_name": "here", "key": to, "action": pkg["actions"][k],
                    "pages": pkg["pages"][k], "sounds": pkg["sounds"][k], "icons": pkg["icons"][k]}
                   for k, to in plan.items() if to]
            try:  # checked here like anything that arrives: allowed kinds of keys, real sound / picture files
                spec = peer_proposal("edit", {"profile": "here", "ops": put}, len(files))
                peer_check_files("edit", spec, files)
            except ValueError as e:
                return status.config(text=f"Not copied: {e}")
            folder = deck["folder"](L["prof"].get())

            def fn(edit):
                kp, made = sd_keypad(edit(page)), {}
                peer_apply(kp, spec["ops"], files, lambda pid, pg: (made.__setitem__(pid, pg), edit(
                    folder / "Profiles" / pid.upper() / "manifest.json", pg)))
                for n, o in enumerate(spec["ops"]):
                    ui_put_icons(deck["icons"], o, files, dst / f"icons {n}", page.parent, kp[o["key"]], made, folder)
            deck["change"](fn, f"Copied {len(put)} key(s) from {peer['name']}")
            refused = pkg.get("refused") or {}
            status.config(text=f"Copied {len(put)} key(s) here from {peer['name']} (undo in the Stream Deck editor)."
                          + (" Not copied: " + "; ".join(f"{k}: {v}" for k, v in refused.items()) if refused else ""))
            R["sel"].clear()
            draw()
        hub["run"](work, done)

    def send():
        files, out, moves = [], [], []
        for o in ops:
            o = dict(o)
            if "from" in o:
                moves.append(o.pop("from"))
            if o["op"] == "sounds":
                o["files"] = [len(files) + n for n in range(len(o["files"]))]
                files += [Path(f) for f in ops[len(out)]["files"]]
            elif o["op"] == "put":
                p = o.pop("packed")
                o.pop("title")
                o.update(action=p["action"], pages=p["pages"], sounds=[], icons={})
                for f in p["sounds"]:
                    files.append(Path(f))
                    o["sounds"].append(len(files) - 1)
                for rel, f in p["icons"].items():
                    files.append(Path(f))
                    o["icons"][rel] = len(files) - 1
            out.append(o)
        try:
            spec = peer_proposal("edit", {"profile": R["prof"].get(), "ops": out}, len(files))
            peer_check_files("edit", spec, files)
        except ValueError as e:
            return status.config(text=f"Can't send that: {e}")
        hub["send"](peer, "edit", files, {"profile": R["prof"].get(), "ops": out},
                    then=(lambda ok: ok and moved(moves)) if moves else None)
        ops.clear()
        status.config(text=f"Sent - waiting for someone to accept it on {peer['name']}. The answer shows here and "
                           "in the Linked computers tab." + (f" The {len(moves)} moved key(s) are taken away here once "
                                                             "it's accepted and applied there." if moves else ""))
        draw()

    def moved(moves):
        """Moved keys, once the linked computer accepted and applied their copies: taken away here (one undo) - each
        only if it's still the key that was moved."""
        still = [(pf, k) for pf, k, was in moves if deck["keys"](pf).get(k) == was]
        if still:
            deck["change"](lambda edit: [sd_keypad(edit(pf)).pop(k, None) for pf, k in still],
                           f"Moved {len(still)} key(s) to {peer['name']}")
        hub["act"](peer, f"moved {len(still)} key(s) there - taken away here (undo in the Stream Deck editor)" + (
            f"; {len(moves) - len(still)} changed here since, so kept" if len(still) < len(moves) else ""))
        if win.winfo_exists():
            draw()

    def refresh():
        def done(res):
            if isinstance(res, Exception):
                return status.config(text=f"Couldn't read {peer['name']}: {res}")
            remote.clear()
            remote.update({p["profile"]: p for p in res.get("deck") or []})
            draw()
        hub["run"](lambda: peer_browse(peer, hub["me"]()), done)
    for text, fn in (("Sounds on key...", sounds_on), ("Rename key...", rename), ("Clear key(s)", clear),
                     ("Undo last", lambda: (ops and ops.pop(), draw()))):
        ttk.Button(tools, text=text, style="Tool.TButton", command=fn).pack(side="left", padx=(0, 6))
    if deck:
        ttk.Button(tools, text=f"Copy to {peer['name']} >", style="Tool.TButton", command=to_remote).pack(
            side="left", padx=(12, 6))
        ttk.Button(tools, text=f"Move to {peer['name']} >", style="Tool.TButton",
                   command=lambda: to_remote(True)).pack(side="left", padx=(0, 6))
        ttk.Button(tools, text="< Copy here", style="Tool.TButton", command=from_remote).pack(side="left")
    ttk.Button(tools, text="Refresh", style="Tool.TButton", command=refresh).pack(side="left", padx=6)
    send_b.pack(side="right")
    for s in ([L] if deck else []) + [R]:
        s["prof"].trace_add("write", lambda *_, s=s: (s["sel"].clear(), s["page"].set(""), draw()))
        s["page"].trace_add("write", lambda *_, s=s: (s["sel"].clear(), draw()))
    live = ttk.Label(win, style="Hint.TLabel", anchor="w")
    live.pack(fill="x", padx=12, pady=(0, 8))
    hub["listeners"].append(lambda: win.winfo_exists() and (banner.config(text=f" Working on: {hub['label'](peer)} "),
                                                            live.config(text=hub["activity"].get(peer["id"], ""))))
    draw()
    status.config(text=f"Click keys to select them. Changes to {peer['name']}'s keys wait here until Send; "
                       "they're applied there only when someone accepts them there.")
    return {"win": win, "ops": ops, "L": L, "R": R, "send": send, "to_remote": to_remote,
            "from_remote": from_remote, "stage": stage, "status": status}


def ui_remote_vts(parent, hub, peer, listing):
    """A linked computer's VTube Studio: its models and backgrounds; send backgrounds there (placed in its
    Backgrounds folder, and its VTube Studio tab pre-filled for hotkeys / keys, once accepted there)."""
    import tkinter as tk
    from tkinter import filedialog, ttk
    vts = listing.get("vts") or {}
    win = tk.Toplevel(parent)
    win.title(f"{peer['name']} - VTube Studio (linked computer)")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    ttk.Label(win, text=f" Working on: {hub['label'](peer)} ", style="Remote.TLabel", anchor="w").pack(fill="x")
    body = ttk.Frame(win, padding=12)
    body.pack(fill="both", expand=True)
    if not vts.get("models"):
        ttk.Label(body, text=f"VTube Studio wasn't found on {peer['name']} (set it in its Setup tab).",
                  style="Bad.TLabel").pack(anchor="w")
    r = ttk.Frame(body)
    r.pack(fill="x")
    model = tk.StringVar(value=vts.get("model") or (vts.get("models") or [""])[0])
    ttk.Label(r, text="Model").pack(side="left")
    ttk.Combobox(r, textvariable=model, values=vts.get("models") or [], state="readonly", width=34).pack(
        side="left", padx=6)
    ttk.Label(body, text=f"Backgrounds there ({len(vts.get('backgrounds') or [])}):", style="Field.TLabel").pack(
        anchor="w", pady=(8, 0))
    tv = ttk.Treeview(body, columns=("n",), show="headings", height=7)
    tv.heading("n", text="Background")
    tv.pack(fill="both", expand=True)
    for b in vts.get("backgrounds") or []:
        tv.insert("", "end", values=(b,))
    files = []
    picked = ttk.Label(body, style="Hint.TLabel", wraplength=700, justify="left")
    picked.pack(anchor="w", pady=(6, 0))
    apply_v, hot_v = tk.BooleanVar(value=True), tk.BooleanVar(value=False)
    ttk.Checkbutton(body, text="Put them in its VTube Studio backgrounds once accepted there",
                    variable=apply_v).pack(anchor="w")
    ttk.Checkbutton(body, text="Also set up hotkeys there (its VTube Studio tab opens with them)",
                    variable=hot_v).pack(anchor="w")
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(8, 0))

    def add(got):
        for f in map(Path, got):
            try:
                files.append(link_check_file(f, VTS_EXT))
            except (ValueError, OSError) as e:
                picked.config(text=f"Can't send that: {e}")
                return
        picked.config(text=f"{len(files)} to send: " + ", ".join(f.name for f in files[:6]))

    def send():
        if not files:
            return picked.config(text="Add backgrounds first.")
        hub["send"](peer, "vts", list(files), {"model": model.get(), "apply": apply_v.get(), "hotkeys": hot_v.get()})
        files.clear()
        picked.config(text=f"Sent - waiting for someone to accept it on {peer['name']}.")
    ttk.Button(bar, text="Add backgrounds...", style="Tool.TButton", command=lambda: add(
        filedialog.askopenfilenames(parent=win, title="Backgrounds", filetypes=[
            ("Backgrounds", " ".join(f"*{e}" for e in VTS_EXT))]))).pack(side="left")
    ttk.Button(bar, text="From Channel Mirror...", style="Tool.TButton",
               command=lambda: add(ui_library(win, hub, VTS_EXT))).pack(side="left", padx=6)
    ttk.Button(bar, text="Send", style="Accent.TButton", command=send).pack(side="right")
    return {"win": win, "add": add, "send": send, "model": model, "apply": apply_v, "hotkeys": hot_v}
