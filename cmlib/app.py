"""The main window: every tab, link delivery, closing; and the uninstall command line."""
import json
import numpy as np
import os
import queue
import shutil
import subprocess
import sys
from pathlib import Path
from .core import AUDIO_EXT, BUNDLE, FFMPEG_DIR, OUTPUT_TYPES, SETTINGS, SOURCES, TARGETS, VIDEO_EXT
from .install import VERSION, first_run_setup, offer_install, uninstall
from .mirror import (
    OUT_SUBDIR,
    natural,
    QUIET_WINDOW,
    analyze,
    clip_seconds,
    db,
    labels,
    media_files,
    out_ext,
    out_folder,
    parse_time,
    plan_jobs,
    route,
    split_points,
)
from .deck import sd_devices, sd_keypad, sd_sounds
from .vts import VTS_EXT, vts_copy, vts_models
from .link import LINK_EXT, LINK_INBOX, LINK_TO_PEER, link_args, link_safe_name, link_to_peer
from .peers import (
    LINK_AUDIO,
    library_files,
    library_items,
    link_check_file,
    link_handover_serve,
    peer_apply,
    peer_browse,
    peer_key,
    peer_name,
    peer_pack,
)
from .setup import app_command, setup_apply
from .ui import Tip, ui_keys, ui_menu, ui_palette, ui_theme
from .ui_link import (
    ui_library,
    ui_linked_bar,
    ui_put_icons,
    ui_remote_deck,
    ui_remote_vts,
    ui_send_items,
    ui_send_linked,
    ui_send_menu,
)
from .tab_import import import_tab
from .tab_mover import mover_tab
from .tab_recorder import recorder_tab
from .tab_vts import vts_tab
from .tab_link import link_tab
from .tab_editor import sd_editor_tab
from .tab_soundboard import streamdeck_tab
from .tab_setup import setup_tab
from .tab_music import music_tab
from .tab_obs import obs_tab
from .tab_transcribe import transcribe_tab


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    try:
        cfg = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        cfg = {}
    setup_apply(cfg.get("paths"))  # folders picked in the Setup tab, before anything looks for them
    ui_palette(cfg.get("theme", "system"))
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on scaled Windows displays
    except (AttributeError, OSError):
        pass
    items = []  # (path, info, rms)
    root = tk.Tk()
    ui_theme(root)
    if (BUNDLE / "icon.ico").exists():
        root.iconbitmap(default=str(BUNDLE / "icon.ico"))
    if offer_install(root, cfg):  # started the installed copy instead
        root.destroy()
        return
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")) and not first_run_setup(root):
        root.destroy()
        return
    root.title(f"Channel Mirror {VERSION}")
    zoom = max(1.0, root.winfo_fpixels("1p") / (96 / 72))  # Windows display scaling (1.5 = 150%)
    root.minsize(int(1100 * zoom), int(720 * zoom))  # the same usable size on every display
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(cfg.get("geometry") or f"{min(sw - 80, max(1100, sw * 4 // 5))}x{min(sh - 100, max(720, sh * 6 // 7))}"
                                         f"+{sw // 20}+{sh // 40}")

    # header
    head = ttk.Frame(root, style="Header.TFrame", padding=(16, 10))
    head.pack(fill="x")
    try:
        img = tk.PhotoImage(file=str(BUNDLE / "icon.png"))
        img = img.subsample(max(1, img.width() // 36))
        ttk.Label(head, image=img, style="Header.TLabel").pack(side="left", padx=(0, 10))
        head.img = img
    except tk.TclError:
        pass
    ttk.Label(head, text="Channel Mirror", style="HeadTitle.TLabel").pack(side="left")
    ttk.Label(head, text=f"  v{VERSION}  -  route audio channels, build and edit Stream Deck soundboards",
              style="HeadSub.TLabel").pack(side="left", pady=(6, 0))
    ttk.Separator(root).pack(fill="x")

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, pady=(6, 0))
    (page, sd_page, ed_page, imp_page, mv_page, rec_page, vts_page, mus_page, obs_page, link_page, peers_page,
     setup_page) = (ttk.Frame(nb) for _ in range(12))
    nb.add(page, text="Channel Mirror")
    nb.add(sd_page, text="Stream Deck soundboard")
    nb.add(ed_page, text="Stream Deck editor")
    nb.add(imp_page, text="Import to folders")
    nb.add(mv_page, text="Key mover")
    nb.add(rec_page, text="Screen recorder")
    nb.add(vts_page, text="VTube Studio backgrounds")
    nb.add(mus_page, text="Music player")
    nb.add(obs_page, text="OBS")
    tr_page = ttk.Frame(nb)
    nb.add(tr_page, text="Transcribe")
    nb.add(link_page, text="Link")
    nb.add(peers_page, text="Linked computers")
    nb.add(setup_page, text="Setup")
    made = []  # files written this session, offered to the Stream Deck tab
    root.update()  # show the window now; reading the Stream Deck profiles below takes a few seconds
    sd_save = streamdeck_tab(sd_page, cfg, made)
    editor = sd_editor_tab(ed_page, cfg, made)
    # the import and key mover tabs change profiles through the editor: one set of unsent changes, one undo
    importer = import_tab(imp_page, cfg, made, editor)
    mover_tab(mv_page, editor)
    recorder = recorder_tab(rec_page, cfg)
    vtube = vts_tab(vts_page, cfg, editor)
    music = music_tab(mus_page, cfg)
    transcriber = transcribe_tab(tr_page, cfg)

    def deliver(target, files, spec=None, peer=None):
        """Accepted files (from another device or a link) into the tab they're meant for; a linked computer's
        proposal (spec) is applied the way the tab itself would. Raises ValueError when it can't be done here."""
        files, spec = [Path(f) for f in files], spec or {}
        if target == "import":
            if "add" not in importer:
                raise ValueError("There's no Stream Deck app on this PC")
            importer["add"](files)
            nb.select(imp_page)
        elif target == "vts":
            if spec.get("model") in [m[0] for m in vts_models(vtube["vars"]["assets"].get() or ".")]:
                vtube["vars"]["model"].set(spec["model"])  # else the model picked here
            nb.select(vts_page)
            if spec.get("hotkeys"):  # set up by this PC's own VTube Studio tab: copied, hotkeys, keys (as accepted)
                return vtube["auto"](files)
            vtube["add"](files)
            if spec.get("apply"):  # placed in VTube Studio's backgrounds now (new names: nothing overwritten)
                bg = Path(vtube["vars"]["assets"].get() or ".") / "Backgrounds"
                if not (bg.parent / "Live2DModels").is_dir():
                    raise ValueError("VTube Studio wasn't found on this PC - pick it in the Setup tab")
                bg.mkdir(exist_ok=True)
                vts_copy(files, bg)
                vtube["refresh"]()
            nb.select(vts_page)
        elif target == "soundboard":
            nb.select(sd_page)
            if spec.get("sounds"):
                new = sd_save.put([{"path": files[x["file"]], "key": x["key"], "title": x["title"], "mode": x["mode"],
                                    "fade": x["fade"], "fade_len": x["fade_len"], "volume": x["volume"]}
                                   for x in spec["sounds"]])
                if spec.get("install"):  # then into Stream Deck here, as its Install directly does (accepted here)
                    sd_save.install(spec["name"], new)
            else:
                sd_save.add(files)
        elif target == "files":
            nb.select(link_page)
        elif target == "obs":  # into OBS here: a source it has, or new ones in a scene
            obs["receive"](files, spec)
            nb.select(obs_page)
        elif target == "music":  # into a playlist (a new one named as the sender's, when it said)
            music["receive"](files, spec.get("playlist"))
            nb.select(mus_page)
        elif target == "edit":
            apply_edit(files, spec, peer)
        elif target == "record":
            if spec["action"] == "start":
                if recorder["state"]["proc"]:
                    raise ValueError("A recording is already running here")
                if peer:  # the finished file goes back to whoever asked (accepted there, like anything else)
                    recorder["state"].setdefault("then", []).append(lambda out: hub["send"](peer, "files", [out], {}))
                nb.select(rec_page)
                recorder["start"]()
            else:
                recorder["stop"]()
        else:
            load([f for f in files if f.suffix.lower() in AUDIO_EXT + VIDEO_EXT])
            st_ = spec.get("settings") or {}
            for k, vars_ in (("sources", src_vars), ("targets", tgt_vars)):
                for name, var in vars_.items() if k in st_ else ():
                    var.set(name in st_[k])
            if "output_type" in st_:
                shown.set(label_of[st_["output_type"]])
            for k, var in (("split", split_var), ("length", len_var), ("loop", loop_var), ("quiet", quiet_var),
                           ("parts", parts_var)):
                if k in st_:
                    var.set(st_[k])
            nb.select(page)

    def apply_edit(files, spec, peer):
        """A linked computer's accepted key changes: through the editor (one undo), then to Stream Deck here."""
        if not editor:
            raise ValueError("There's no Stream Deck app on this PC")
        label = spec["profile"]
        if label not in editor["profiles"]():
            raise ValueError(f"The profile '{label}' isn't on this PC any more")
        pages, folder = editor["pages"](label), editor["folder"](label)
        for o in spec["ops"]:
            if o["page"] >= len(pages) or pages[o["page"]][0] != o["page_name"]:
                raise ValueError(f"'{o['page_name']}' moved or was renamed here - look again and send it again")

        def fn(edit):
            by, made = {}, {}
            for o in spec["ops"]:
                by.setdefault(o["page"], []).append(o)
            for i, ops in by.items():
                pf = pages[i][1]
                kp = sd_keypad(edit(pf))
                peer_apply(kp, ops, files, lambda pid, pg: (made.__setitem__(pid, pg), edit(
                    folder / "Profiles" / pid.upper() / "manifest.json", pg)))
                for n, o in enumerate(ops):
                    if o["op"] == "put" and o["icons"]:  # its own icons and those inside its folders
                        ui_put_icons(editor["icons"], o, files, files[0].parent / f"icons {i}-{n}", pf.parent,
                                     kp[o["key"]], made, folder)
        editor["change"](fn, f"{len(spec['ops'])} change(s) to {label} from {peer['name'] if peer else 'a linked PC'}")
        nb.select(ed_page)
        editor["save"](auto=True)  # to Stream Deck here: it closes and reopens (started if it wasn't), backup first

    def listing(info):
        """What a linked computer sees when it opens this PC's Stream Deck / VTube Studio (names only, no paths)."""
        out = {"name": peer_name(linker["vars"]["device"].get()), "devices": [], "deck": [], "vts": {}}
        if editor:
            out["devices"] = [{"name": k, "model": m, "cols": c, "rows": r, "connected": k.startswith("[connected]")}
                              for k, (m, _, c, r) in sd_devices().items()]
            out["deck"] = [{"profile": lb, "grid": list(editor["grid"](lb)), "pages": [
                {"name": n, "keys": {k: peer_key(a) for k, a in editor["keys"](pf).items() if a}}
                for n, pf in editor["pages"](lb)]} for lb in editor["profiles"]()]
        a = vtube["vars"]["assets"].get()
        if a and Path(a).is_dir():
            out["vts"] = {"models": [m[0] for m in vts_models(a)], "model": vtube["vars"]["model"].get(),
                          "backgrounds": sorted(q.name for q in (Path(a) / "Backgrounds").glob("*")
                                                if q.suffix.lower() in VTS_EXT)}
        return out

    def fetch(info):
        """Keys a linked computer copies from here (a read): packed, each file offered to it alone for a while."""
        import copy
        res = {"actions": {}, "pages": {}, "sounds": {}, "icons": {}, "files": [], "refused": {}}
        if not editor or info["profile"] not in editor["profiles"]():
            return dict(res, refused={"*": "that profile isn't here any more"})
        pages, srv = editor["pages"](info["profile"]), linker["state"]["server"]
        if info["page"] >= len(pages) or pages[info["page"]][0] != info["page_name"]:
            return dict(res, refused={"*": "that page moved or was renamed - look again"})
        pf = pages[info["page"]][1]
        kp, by_id = editor["keys"](pf), {q.parent.name.lower(): q for _, q in pages}

        def num(f):
            res["files"].append({"name": link_safe_name(Path(f).name), "token": srv.offer(f, info["peer"])})
            return len(res["files"]) - 1
        for k in info["keys"]:
            if not kp.get(k):
                continue
            try:
                pk = peer_pack({k: copy.deepcopy(kp[k])}, by_id, editor["page"], pf.parent)[k]
            except (ValueError, OSError) as e:
                res["refused"][k] = str(e)
                continue
            res["actions"][k], res["pages"][k] = pk["action"], pk["pages"]
            res["sounds"][k] = [num(f) for f in pk["sounds"]]
            res["icons"][k] = {r: num(f) for r, f in pk["icons"].items()}
        return res

    def mine():
        """What the "From Channel Mirror..." picker lists on this PC (Setup tab folders and this session)."""
        assets = vtube["vars"]["assets"].get()
        keys = []
        if editor and editor["current"]()[0]:
            keys = [Path(x.get("Settings", {}).get("path", "")) for _, pf in editor["pages"](editor["current"]()[0])
                    for a in editor["keys"](pf).values() if a for x in sd_sounds(a)]
        return {"Channel Mirror outputs": list(made) + (library_files(out_var.get().strip(), AUDIO_EXT + VIDEO_EXT)
                                                       if out_var.get().strip() else []),
                "Screen recordings": library_files(recorder["vars"]["folder"].get().strip(), VIDEO_EXT)
                if recorder["vars"]["folder"].get().strip() else [],
                "Received files": library_files(LINK_INBOX / "Received", LINK_EXT),
                "VTube Studio backgrounds": library_files(Path(assets) / "Backgrounds", VTS_EXT) if assets else [],
                "Sounds on Stream Deck keys": keys, "Music playlists": music["songs"]()}

    def library(info):
        """The same, offered to a linked computer: names and sizes; each file it may fetch for a while."""
        srv, out = linker["state"]["server"], {}
        for g, paths in mine().items():
            got = []
            for _, f, ok in library_items({g: paths}):
                try:
                    if ok and len(got) < 500:
                        link_check_file(f)
                        got.append({"name": f.name, "size": f.stat().st_size, "token": srv.offer(f, info["peer"])})
                except (ValueError, OSError):
                    pass
            out[g] = got
        return out
    def here(target, spec):
        """Accept-prompt lines naming what this PC's own choices will use for a proposal's options."""
        if target == "vts" and spec.get("hotkeys"):
            have = [m[0] for m in vts_models(vtube["vars"]["assets"].get() or ".")]
            model = spec.get("model") if spec.get("model") in have else vtube["vars"]["model"].get()
            v = vtube["vars"]
            return [f"Here: hotkeys on the model '{model or '(none picked - it will fail)'}'" + (
                f"; Stream Deck keys on {v['prof'].get().replace('[connected] ', '')} / {v['page'].get()}" + (
                    f", in folders of {v['per'].get()} named '{v['title'].get()}'" if v["folders"].get() else "") +
                " (the keys picked in its VTube Studio tab, else the first free one)" if editor else "") + "."]
        if target == "soundboard" and spec.get("install"):
            return [f"Here: for the Stream Deck '{sd_save.device()}' (picked in the Stream Deck soundboard tab)."]
        return []

    def jump(tab, pg, peer):
        """A tool already pointed at a linked computer: its strip picks that computer."""
        nb.select(pg)
        if tab in bars:
            bars[tab]["who"].set(peer["name"])
    provide = {"browse": listing, "fetch": fetch, "library": library, "mine": mine, "here": here, "jump": [
        ("Stream Deck editor with it", lambda pr: (jump("editor", ed_page, pr), open_deck(pr))),
        ("Key mover with it", lambda pr: (jump("mover", mv_page, pr), open_deck(pr))),
        ("VTube Studio with it", lambda pr: (jump("vts", vts_page, pr), open_vts(pr))),
        ("Soundboard: send there", lambda pr: jump("soundboard", sd_page, pr)),
        ("Recorder: send there", lambda pr: jump("recorder", rec_page, pr))]}
    linker = link_tab(link_page, cfg, deliver, provide, home=peers_page)
    hub = linker["hub"]
    obs = obs_tab(obs_page, cfg, hub, music, lambda: [Path(s["path"]) for s in list(sd_save.sounds)])
    provide["obs"] = obs["remote"]  # a linked computer's OBS commands (only if it may)
    handed = queue.Queue()  # Send to > Channel Mirror (linked computers) while the app is open: its files
    handover = link_handover_serve(  # links clicked while the app is open come here (both from this PC only)
        lambda text: handed.put(text) if text.startswith(LINK_TO_PEER + "\n") else linker["open_link"](text))

    def to_peer(text):
        """Files / folders from Send to > Channel Mirror (linked computers): which linked computer, which tab."""
        files = []
        for a in map(Path, filter(None, text.split("\n")[1:])):  # (a blank line is no folder)
            files += sorted(library_files(a, LINK_EXT), key=natural) if a.is_dir() else [a] if a.is_file() else []
        root.deiconify()
        ui_send_linked(root, hub, list(dict.fromkeys(files)))

    def take():
        while not handed.empty():
            to_peer(handed.get())
        root.after(300, take)
    take()
    if editor:
        editor["hooks"]["import"] = lambda label, page_file, key: (nb.select(imp_page),
                                                                   importer["prefill"](label, page_file, key))
    pad = {"padx": 10, "pady": 5}

    # 1. Input files
    inp = ttk.LabelFrame(page, text="1. Input files")
    inp.pack(fill="both", expand=True, **pad)
    side = ttk.Frame(inp)
    side.pack(side="right", fill="y", padx=(10, 0))
    box = ttk.Frame(inp)
    box.pack(side="left", fill="both", expand=True)
    fcols = ("file", "levels", "loudest", "outputs")
    lst = ttk.Treeview(box, columns=fcols, show="headings", height=5)
    for c, h, w in zip(fcols, ("File", "Channel levels", "Loudest", "Will write"), (220, 260, 90, 520)):
        lst.heading(c, text=h)
        lst.column(c, width=w, stretch=c in ("file", "outputs"))
    ys = ttk.Scrollbar(box, command=lst.yview)
    xs = ttk.Scrollbar(box, orient="horizontal", command=lst.xview)
    lst.config(yscrollcommand=ys.set, xscrollcommand=xs.set)
    ys.pack(side="right", fill="y")
    xs.pack(side="bottom", fill="x")
    lst.pack(fill="both", expand=True)

    # 2. Settings
    sett = ttk.LabelFrame(page, text="2. Settings")
    sett.pack(fill="x", **pad)
    src_on, tgt_on = cfg.get("sources", ["Auto (loudest)"]), cfg.get("targets", ["both"])
    src_vars = {s: tk.BooleanVar(value=s in src_on) for s in SOURCES}
    tgt_vars = {t: tk.BooleanVar(value=t in tgt_on) for t in TARGETS.values()}
    label_of = {v: k for k, v in OUTPUT_TYPES.items()}
    mode_var = tk.StringVar(value=cfg.get("output_type") if cfg.get("output_type") in label_of else "same")
    len_var = tk.StringVar(value=cfg.get("length", ""))
    loop_var, quiet_var = tk.BooleanVar(value=cfg.get("loop", False)), tk.BooleanVar(value=cfg.get("quiet", False))
    split_var, parts_var = tk.BooleanVar(value=cfg.get("split", False)), tk.StringVar(value=cfg.get("parts", ""))

    # 3. Output folder
    outf = ttk.LabelFrame(page, text=f'3. Output folder  (blank = a "{OUT_SUBDIR}" folder beside the inputs)')
    outf.pack(fill="x", **pad)
    out_var = tk.StringVar(value=cfg.get("out_dir", ""))
    ttk.Entry(outf, textvariable=out_var).pack(side="left", fill="x", expand=True)

    runbar = ttk.Frame(page, padding=(10, 4, 10, 10))
    runbar.pack(fill="x")
    status = ttk.Label(runbar, style="Status.TLabel", anchor="w", text="Add audio files or a folder to begin.")

    def chosen():
        return [s for s, v in src_vars.items() if v.get()], [t for t, v in tgt_vars.items() if v.get()]

    def save_settings():
        sources, targets = chosen()
        try:
            SETTINGS.write_text(json.dumps({**cfg, "sources": sources, "targets": targets, "out_dir": out_var.get().strip(),
                                            "output_type": mode_var.get(), "length": len_var.get().strip(),
                                            "loop": loop_var.get(),
                                            "quiet": user_quiet[0] if split_var.get() else quiet_var.get(),
                                            "split": split_var.get(), "parts": parts_var.get().strip()}))
        except OSError:
            pass  # settings are a convenience; never block the user over them

    def refresh(*_):
        lst.delete(*lst.get_children())
        sources, targets = chosen()
        total = 0
        for i, (src, info, rms) in enumerate(items):
            names = labels(len(rms))
            levels = "  ".join(f"{nm} {v:6.1f} dB" for nm, v in zip(names, db(rms)))
            jobs = plan_jobs(src, rms, sources, targets, out_ext(src, info, mode_var.get()))
            total += len(jobs)
            part = "_partNN" if split_var.get() else ""  # part count is only known once Run finds the silences
            outs = ", ".join(f"{Path(j[2]).stem}{part}{Path(j[2]).suffix}" for j in jobs) or "(nothing selected)"
            lst.insert("", "end", iid=str(i), values=(src.name, levels, names[int(np.argmax(rms))],
                                                      f"{len(jobs)}: {outs}"))
        each = ", each split into parts at silences" if split_var.get() else ""
        status.config(text=f"{len(items)} file(s) loaded, {total} output file(s) will be written{each}.")

    def busy(msg):
        status.config(text=msg)
        root.config(cursor="watch")
        root.update()  # ponytail: work runs on the UI thread; move to a thread if huge batches freeze it too long

    def load(paths):
        have = {p for p, _, _ in items}
        failed = []
        for i, p in enumerate(paths, 1):
            p = Path(p)
            if p in have:
                continue
            busy(f"Analyzing {i}/{len(paths)}: {p.name}...")
            try:
                info, rms, _ = analyze(p)
                items.append((p, info, rms))
            except Exception as e:
                failed.append(str(e))
        root.config(cursor="")
        refresh()
        if failed:  # one dialog for the whole batch (e.g. videos with no audio track)
            messagebox.showerror("Some files skipped", "\n".join(failed[:20]) + (
                f"\n...and {len(failed) - 20} more" if len(failed) > 20 else ""))

    def add_files():
        pat = lambda exts: " ".join(f"*{e}" for e in exts)
        load(filedialog.askopenfilenames(title="Select audio or video files", filetypes=[
            ("Audio & video", pat(AUDIO_EXT + VIDEO_EXT)), ("Audio", pat(AUDIO_EXT)), ("Video", pat(VIDEO_EXT)),
            ("All files", "*.*")]))

    def add_folder():
        folder = filedialog.askdirectory(title="Add every audio/video file in folder")
        if folder:
            load(media_files([folder]))

    def remove_selected():
        for i in sorted(map(int, lst.selection()), reverse=True):
            del items[i]
        refresh()

    def clear():
        items.clear()
        refresh()

    def browse_out():
        folder = filedialog.askdirectory(title="Save output files to...")
        if folder:
            out_var.set(folder)

    def open_out():
        folder = Path(out_var.get().strip()) if out_var.get().strip() else (out_folder(items[0][0]) if items else None)
        if folder and folder.is_dir():
            os.startfile(folder)
        else:
            status.config(text="The output folder doesn't exist yet - it's created on the first Run.")

    def run():
        sources, targets = chosen()
        if not items or not sources or not targets:
            messagebox.showinfo("Nothing to run", "Add files and tick at least one source and one output.")
            return
        try:
            length = parse_time(len_var.get())
        except ValueError:
            messagebox.showerror("Length", "Length must be seconds (e.g. 30 or 12.5) or m:ss (e.g. 1:30).")
            return
        loop, quiet, split = loop_var.get(), quiet_var.get(), split_var.get()
        loop = loop and not split  # parts never wrap round to the start of the file
        if loop and not length:
            messagebox.showerror("Length", "Set a length to loop to.")
            return
        count = None
        if split:
            try:
                count = int(parts_var.get()) if parts_var.get().strip() else None
                assert count is None or count >= 1
            except (ValueError, AssertionError):
                messagebox.showerror("Parts", "Parts must be a whole number of 1 or more (or blank).")
                return
            if not length and not count:
                messagebox.showerror("Split", "Set a length for each part, a number of parts, or both.")
                return
        folder = out_var.get().strip()
        if folder:
            try:
                Path(folder).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Output folder", f"Can't use output folder:\n{e}")
                return
        save_settings()
        jobs, planned = [], set()
        for src, info, rms in items:
            for ch, target, name in plan_jobs(src, rms, sources, targets, out_ext(src, info, mode_var.get())):
                if split:
                    busy(f"Finding parts: {src.name}")
                    segs = split_points(src, info, ch, length, count)
                else:
                    segs = [(0.0, clip_seconds(src, info, ch, length, loop, quiet))]
                for n, (start, secs) in enumerate(segs, 1):
                    nm = f"{Path(name).stem}_part{n:02d}{Path(name).suffix}" if len(segs) > 1 else name
                    dst, k = out_folder(src, folder) / nm, 2
                    while dst in planned or dst.resolve() == src.resolve():  # same-named inputs / never touch originals
                        dst, k = dst.with_name(f"{Path(nm).stem}_{k}{dst.suffix}"), k + 1
                    planned.add(dst)
                    jobs.append((src, info, ch, target, dst, start, secs))
        root.config(cursor="")
        existing = [j for j in jobs if j[4].exists()]
        if existing:
            ans = messagebox.askyesnocancel(
                "Files exist", f"{len(existing)} output file(s) already exist.\nYes = overwrite, No = skip them.")
            if ans is None:
                return
            if not ans:
                jobs = [j for j in jobs if not j[4].exists()]
        done, failed = 0, []
        for i, (src, info, ch, target, dst, start, secs) in enumerate(jobs, 1):
            busy(f"Writing {i}/{len(jobs)}: {dst.name}")
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                made.append(route(src, dst, info, ch, target, mode_var.get(), secs, loop, start))
                done += 1
            except Exception as e:
                failed.append(f"{dst.name}: {e}")
        root.config(cursor="")
        where = (f"in {folder}, one subfolder per source folder" if folder
                 else f'in a "{OUT_SUBDIR}" folder beside each input')
        status.config(text=f"Done: {done} file(s) written ({where})" + (f", {len(failed)} failed" if failed else ""))
        msg = f"Wrote {done} file(s)\n{where}"
        if failed:
            messagebox.showerror("Done with errors", msg + "\n\nFailed:\n" + "\n".join(failed[:20]))
        else:
            messagebox.showinfo("Done", msg)

    for text, cmd, tip in (("Add files...", add_files, "Audio or video files"),
                           ("Add folder...", add_folder, "Every audio/video file in a folder"),
                           ("Remove selected", remove_selected, "Del"), ("Clear all", clear, "")):
        b = ttk.Button(side, text=text, command=cmd, width=16)
        b.pack(pady=2, fill="x")
        if tip:
            Tip(b, tip)
    ttk.Button(outf, text="Browse...", command=browse_out).pack(side="left", padx=(8, 0))
    ttk.Button(outf, text="Open", command=open_out).pack(side="left", padx=(6, 0))
    ttk.Button(runbar, text="Run", command=run, style="Accent.TButton", width=12).pack(side="left")
    status.pack(side="left", fill="x", expand=True, padx=12)

    def file_menu(e):
        it = lst.identify_row(e.y)
        if it and it not in lst.selection():
            lst.selection_set(it)
        if lst.selection():
            src = items[int(lst.selection()[0])][0]
            ui_menu(lst, e, [("Play file", lambda: os.startfile(src)),
                             ("Open file's folder", lambda: os.startfile(src.parent)), None,
                             ("Remove   Del", remove_selected)])
    lst.bind("<Button-3>", file_menu)
    ui_keys(page, {"<Delete>": remove_selected, "<Control-a>": lambda: lst.selection_set(lst.get_children())})

    def group(title, vars_, text_for):
        row = ttk.Frame(sett)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=title, width=16).pack(side="left")
        all_var = tk.BooleanVar(value=all(v.get() for v in vars_.values()))

        def toggle_all():
            on = all_var.get()  # read once: setting each box re-syncs all_var mid-loop
            for v in vars_.values():
                v.set(on)
        ttk.Checkbutton(row, text="All", variable=all_var, command=toggle_all).pack(side="left")
        for key, v in vars_.items():
            ttk.Checkbutton(row, text=text_for(key), variable=v).pack(side="left", padx=8)
            v.trace_add("write", lambda *_: (all_var.set(all(x.get() for x in vars_.values())), refresh()))

    group("Source channel", src_vars, lambda s: s)
    group("Output to", tgt_vars, str.capitalize)
    row = ttk.Frame(sett)
    row.pack(fill="x", pady=3)
    ttk.Label(row, text="Output type", width=16).pack(side="left")
    shown = tk.StringVar(value=label_of[mode_var.get()])
    ttk.Combobox(row, textvariable=shown, values=tuple(OUTPUT_TYPES), state="readonly", width=34).pack(side="left")
    shown.trace_add("write", lambda *_: mode_var.set(OUTPUT_TYPES[shown.get()]))
    mode_var.trace_add("write", refresh)

    row = ttk.Frame(sett)
    row.pack(fill="x", pady=3)
    ttk.Label(row, text="Length", width=16).pack(side="left")
    ttk.Entry(row, textvariable=len_var, width=9).pack(side="left")
    len_hint = ttk.Label(row, width=40, style="Hint.TLabel")
    len_hint.pack(side="left", padx=8)
    loop_cb = ttk.Checkbutton(row, text="Loop to fill length", variable=loop_var)
    loop_cb.pack(side="left", padx=(12, 4))
    quiet_cb = ttk.Checkbutton(row, variable=quiet_var)
    quiet_cb.pack(side="left", padx=8)

    row = ttk.Frame(sett)
    row.pack(fill="x", pady=3)
    ttk.Label(row, text="Split", width=16).pack(side="left")
    ttk.Checkbutton(row, text="Split each file into parts", variable=split_var).pack(side="left")
    parts_lbl = ttk.Label(row, text="Parts")
    parts_lbl.pack(side="left", padx=(16, 0))
    parts_entry = ttk.Entry(row, textvariable=parts_var, width=5)
    parts_entry.pack(side="left", padx=6)
    split_hint = ttk.Label(row, style="Hint.TLabel")
    split_hint.pack(side="left")
    user_quiet = [quiet_var.get()]  # the user's own quiet choice, put back when Split is turned off

    def on_split(*_):
        on = split_var.get()
        if on:
            user_quiet[0] = quiet_var.get()
            quiet_var.set(True)  # parts are always cut at silences
        else:
            quiet_var.set(user_quiet[0])
        loop_cb.config(state="disabled" if on else "normal")  # parts never loop
        quiet_cb.config(state="disabled" if on else "normal",
                        text="Cut in the middle of silences (always on when splitting)" if on
                        else f"End at a quiet spot (up to {QUIET_WINDOW:g} s early)")
        parts_lbl.config(state="normal" if on else "disabled")
        parts_entry.config(state="normal" if on else "disabled")
        len_hint.config(text="per part, seconds or m:ss (blank = use Parts)" if on
                        else "seconds or m:ss (blank = full length)")
        split_hint.config(text="blank = as many as fit; with no Length: this many equal parts" if on
                          else "cuts each file at silences into parts of about Length")
        refresh()
    split_var.trace_add("write", on_split)
    on_split()

    restarting = []  # Restart in the Setup tab: close as usual, then start again

    def restart():
        restarting[:] = [True]
        on_close()
    setup_tab(setup_page, cfg, {"out_dir": out_var, "rec": recorder["vars"]["folder"],
                                "vts": vtube["vars"]["assets"]}, restart)

    # linked computers: a strip at the top of each tool - which computer it works on, files from Channel Mirror
    # (here or there), sending the tool's work there, and opening that computer's Stream Deck / VTube Studio
    def need(x, what):
        if not x:
            raise ValueError(what)
        return x

    def open_deck(peer):
        hub["act"](peer, "opening its Stream Deck...")
        hub["run"](lambda: peer_browse(peer, hub["me"](), port=None), lambda r: hub["act"](peer, f"couldn't open it: {r}")
                   if isinstance(r, Exception) else (hub["act"](peer, "Stream Deck open"),
                                                     ui_remote_deck(root, hub, peer, r, editor)))

    def open_vts(peer):
        hub["act"](peer, "opening its VTube Studio...")
        hub["run"](lambda: peer_browse(peer, hub["me"]()), lambda r: hub["act"](peer, f"couldn't open it: {r}")
                   if isinstance(r, Exception) else (hub["act"](peer, "VTube Studio open"),
                                                     ui_remote_vts(root, hub, peer, r)))

    def recordings():
        picked = ui_library(rec_page, hub, (".mp4",), "Recordings to send")
        return ("files", need(picked, "pick a recording"), {}) if picked else None
    bars = {"mirror": ui_linked_bar(page, hub, add=load, exts=AUDIO_EXT + VIDEO_EXT, send=lambda: (
        "mirror", need([x[0] for x in items], "add files first"), {"settings": {
            "sources": chosen()[0], "targets": chosen()[1], "output_type": mode_var.get(), "length": len_var.get().strip(),
            "loop": loop_var.get(), "quiet": quiet_var.get(), "split": split_var.get(), "parts": parts_var.get().strip()}})),
            "soundboard": ui_linked_bar(sd_page, hub, add=sd_save.add, exts=LINK_AUDIO, send=lambda: (
                "soundboard", [x["path"] for x in need(sd_save.sounds, "add sounds first")], sb_spec(sd_save.sounds))),
            "recorder": ui_linked_bar(rec_page, hub, send=recordings, extra=(
                ("Record there", lambda pr: hub["send"](pr, "record", [], {"action": "start"})),
                ("Stop there", lambda pr: hub["send"](pr, "record", [], {"action": "stop"})))),
            "vts": ui_linked_bar(vts_page, hub, add=vtube["add"], exts=VTS_EXT, extra=(
                ("Open its VTube Studio...", open_vts),), send=lambda: (
                "vts", need(list(vtube["files"]), "add backgrounds first"), {
                    "model": vtube["vars"]["model"].get(), **({"hotkeys": True} if vts_setup.get() else {})})),
            "music": ui_linked_bar(mus_page, hub, add=music["add"], exts=LINK_AUDIO, send=lambda: (
                "music", need(music["files"](), "add songs first"), {"playlist": peer_name(music["name"](), 60)}))}
    bars["transcribe"] = ui_linked_bar(tr_page, hub, add=transcriber["add"], exts=AUDIO_EXT + VIDEO_EXT)
    if editor:
        bars["editor"] = ui_linked_bar(ed_page, hub, add=editor["put_files"], exts=LINK_AUDIO,
                                       extra=(("Open its Stream Deck...", open_deck),))
        bars["import"] = ui_linked_bar(imp_page, hub, add=importer["add"], exts=LINK_AUDIO, send=lambda: (
            "import", need(list(importer["files"]), "add sounds first"), {}))
        bars["mover"] = ui_linked_bar(mv_page, hub, extra=(("Open its Stream Deck...", open_deck),))
    def sb_sounds(rows):
        return [{"file": i, "key": x["key"], "title": str(x["title"])[:60], "mode": x["mode"], "fade": x["fade"],
                 "fade_len": int(x["fade_len"]), "volume": int(x["volume"])} for i, x in enumerate(rows)]

    def sb_spec(rows):  # the soundboard's sounds as they go to a linked computer (installed there: ticked below)
        return {"sounds": sb_sounds(rows), **({"install": True, "name": peer_name(sd_save.name(), 60) or "Soundboard"}
                                              if sb_install.get() else {})}
    sb_install = tk.BooleanVar(value=False)
    ttk.Checkbutton(bars["soundboard"]["bar"], text="install it there", variable=sb_install).pack(
        side="left", padx=(6, 0), before=bars["soundboard"]["note"])
    vts_setup = tk.BooleanVar(value=False)
    ttk.Checkbutton(bars["vts"]["bar"], text="set them up there (hotkeys, keys)", variable=vts_setup).pack(
        side="left", padx=(6, 0), before=bars["vts"]["note"])
    # right-click "Send to <linked PC>" on the tabs' file lists: the selected files, with that tab's proposal
    def sb_picked():
        rows = [sd_save.sounds[i] for i in sd_save.picked()]
        return ("soundboard", [x["path"] for x in rows], sb_spec(rows)) if rows else None
    sd_save.more = lambda: ui_send_items(hub, sb_picked)
    picked = lambda tv, of: [of[int(i)] for i in tv.selection()]
    if editor:
        ui_send_menu(importer["list"], hub, lambda: ("import", picked(importer["list"], importer["files"]), {}))
    ui_send_menu(vtube["list"], hub, lambda: ("vts", picked(vtube["list"], vtube["files"]), {
        "model": vtube["vars"]["model"].get(), **({"hotkeys": True} if vts_setup.get() else {})}))
    ui_send_menu(recorder["list"], hub, lambda: ("files", [Path(i) for i in recorder["list"].selection()], {}))
    ui_send_menu(music["tree"], hub, lambda: ("music", picked(music["tree"], music["files"]()), {
        "playlist": peer_name(music["name"](), 60)}))
    recorder["state"].update(peers=hub["peers"], vts_dir=lambda: (
        Path(vtube["vars"]["assets"].get()) / "Backgrounds" if vtube["vars"]["assets"].get() else None),
        to_vts_tab=lambda out: vtube["add"]([out]),
        send_vts=lambda name, out: [hub["send"](pr, "vts", [out], {"apply": True})
                                    for pr in hub["peers"]() if pr["name"] == name][:1])

    names = [nb.tab(t, "text") for t in nb.tabs()]
    last = cfg.get("tab", 0)  # the tab's name; a number from 2.1 and older (their tabs had no Music player)
    if isinstance(last, int):
        old = [n for n in names if n != "Music player"]
        last = old[last] if 0 <= last < len(old) else names[0]
    nb.select(names.index(last) if last in names else 0)

    def on_close():
        if editor and editor["saving"]():  # a send is still running: close when it's done
            root.title(f"Channel Mirror {VERSION} - finishing sending to Stream Deck...")
            return root.after(300, on_close)
        if editor and editor["pending"]():
            n = len(editor["pending"]())
            ans = messagebox.askyesnocancel("Stream Deck changes not sent", f"{n} edited Stream Deck page(s) haven't "
                                            "been sent to Stream Deck yet.\n\nSend them now before closing?\n(No = "
                                            "throw the changes away)")
            if ans is None:
                return restarting.clear()
            if ans:
                editor["save"](auto=True)

                def wait():
                    if editor["saving"]():
                        return root.after(300, wait)
                    if not editor["pending"]():  # sent; on failure the error was shown and the window stays
                        close_now()
                    else:
                        restarting.clear()
                return wait()
        close_now()

    def close_now():
        recorder["stop_now"]()  # a recording still running is finished properly first
        recorder["save"]()
        vtube["save"]()
        music["stop"]()  # sharing and playing stop
        obs["stop"]()
        linker["save"]()
        linker["stop"]()
        if handover:
            handover.shutdown()
        sd_save()
        cfg["geometry"] = root.geometry() if root.state() == "normal" else cfg.get("geometry", "")
        cfg["tab"] = nb.tab(nb.select(), "text")  # by name: adding a tab doesn't move it
        save_settings()
        root.destroy()
        if restarting:
            subprocess.Popen(app_command(), close_fds=True)
    root.protocol("WM_DELETE_WINDOW", on_close)
    # files/folders dropped on the exe or sent via right-click "Send to" arrive as arguments
    clicked = link_args(sys.argv[1:])  # opened by a link: that link only, nothing else from its command line
    if clicked:
        root.after(600, linker["open_link"], clicked)
    # files / folders dropped on the exe; words that aren't a real path are skipped quietly (no error pop-up)
    dropped = [] if clicked else [a for a in sys.argv[1:] if not a.startswith("--") and Path(a).exists()]
    if link_to_peer(sys.argv[1:]) and not clicked:  # Send to > Channel Mirror (linked computers): pick where
        root.after(1500, to_peer, link_to_peer(dropped + [LINK_TO_PEER]))
    elif dropped:
        root.after(100, load, media_files(dropped))
    root.mainloop()


def uninstall_cli():
    """Windows Settings > Apps > Uninstall runs `ChannelMirror.exe --uninstall` (--quiet: no questions)."""
    if "--quiet" in sys.argv:
        return uninstall()
    import tkinter as tk
    from tkinter import messagebox
    tk.Tk().withdraw()
    if messagebox.askyesno("Uninstall Channel Mirror", "Remove Channel Mirror from this computer?"):
        uninstall(data=messagebox.askyesno(
            "Uninstall Channel Mirror", f"Also delete your settings and the downloaded ffmpeg?\n{FFMPEG_DIR.parent}"))
        messagebox.showinfo("Uninstall Channel Mirror", "Channel Mirror was removed.")
