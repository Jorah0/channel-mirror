"""The transcribe tab."""
import os
from .core import AUDIO_EXT, VIDEO_EXT
from .mirror import media_files
from .ui import ui_empty
from .transcribe import (
    DOC_FORMATS,
    VAD_MODEL,
    VAD_MODELS,
    VAD_URL,
    WHISPER_DEFAULT,
    WHISPER_LANGS,
    WHISPER_MODELS,
    WHISPER_URL,
    Cancelled,
    model_download,
    model_file,
    model_ready,
    transcribe,
    whisper_ok,
    write_transcript,
)


FORMAT_TEXT = {"docx": "Word (.docx)", "pdf": "PDF", "srt": "Subtitles (.srt)", "txt": "Text (.txt)"}


def transcribe_tab(page, cfg):
    """The Transcribe tab: videos / audio files (or whole folders) -> what's said in them, as a Word document, a PDF,
    subtitles and plain text with a timestamp per voice line, through ffmpeg's whisper filter on this PC (nothing is
    uploaded). Returns {"add", "start", "cancel", "vars", "state", "list", "items"}."""
    import queue
    import threading
    import time
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    tc = cfg.setdefault("transcribe", {})
    v = {"model": tk.StringVar(value=tc.get("model") if tc.get("model") in WHISPER_MODELS else WHISPER_DEFAULT),
         "lang": tk.StringVar(value=tc.get("lang") if tc.get("lang") in WHISPER_LANGS else "Auto-detect"),
         "gpu": tk.BooleanVar(value=tc.get("gpu", True)), "vad": tk.BooleanVar(value=tc.get("vad", False)),
         "folder": tk.StringVar(value=tc.get("folder", "")),
         **{k: tk.BooleanVar(value=k in tc.get("formats", ["docx", "pdf", "srt", "txt"])) for k in DOC_FORMATS}}
    items = []  # {"path", "iid", "out": {format: path}}
    st = {"busy": False, "cancel": None, "engine": None}
    q = queue.Queue()

    body = ttk.Frame(page, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Turn what's said in videos and recordings into a document: every voice line with its time. "
                         "It all runs on this PC (whisper speech recognition inside ffmpeg) - nothing is uploaded. Long "
                         "videos are fine; they're read as they go.", style="Hint.TLabel", wraplength=1000,
              justify="left").pack(anchor="w", pady=(0, 10))

    # 1. files
    ff = ttk.LabelFrame(body, text="1. Videos and recordings (a folder: every file in it, in name order)")
    ff.pack(fill="both", expand=True)
    side = ttk.Frame(ff)
    side.pack(side="right", fill="y", padx=(10, 0))
    box = ttk.Frame(ff)
    box.pack(side="left", fill="both", expand=True)
    cols = ("file", "status", "result")
    tv = ttk.Treeview(box, columns=cols, show="headings", height=6)
    ui_empty(tv, "No files yet. Add videos or audio files to transcribe.")
    for c, h, w in zip(cols, ("File", "Status", "Saved as"), (300, 200, 420)):
        tv.heading(c, text=h)
        tv.column(c, width=w, stretch=c != "status")
    ys = ttk.Scrollbar(box, command=tv.yview)
    tv.config(yscrollcommand=ys.set)
    ys.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)

    def add(paths):
        have = {str(it["path"]) for it in items}
        for p in media_files(paths):
            if p.is_file() and str(p) not in have:
                have.add(str(p))
                iid = tv.insert("", "end", values=(p.name, "waiting", ""))
                items.append({"path": p, "iid": iid, "out": {}})
        show_status()

    def add_files():
        add(filedialog.askopenfilenames(parent=page, title="Videos or recordings to transcribe", filetypes=[
            ("Video and audio", " ".join("*" + e for e in VIDEO_EXT + AUDIO_EXT)), ("All files", "*.*")]))

    def add_folder():
        d = filedialog.askdirectory(parent=page, title="A folder of videos or recordings")
        if d:
            add([d])

    def remove():
        if st["busy"]:
            return
        for iid in tv.selection():
            tv.delete(iid)
        items[:] = [it for it in items if tv.exists(it["iid"])]
        show_status()

    def clear():
        if not st["busy"]:
            tv.delete(*tv.get_children())
            items.clear()
            show_status()
    for text, cmd in (("Add files...", add_files), ("Add folder...", add_folder), ("Remove", remove),
                      ("Clear", clear)):
        ttk.Button(side, text=text, command=cmd).pack(fill="x", pady=(0, 6))

    # 2. speech recognition
    sf = ttk.LabelFrame(body, text="2. Speech recognition")
    sf.pack(fill="x", pady=(12, 0))
    r = ttk.Frame(sf)
    r.pack(fill="x")
    ttk.Label(r, text="Model").pack(side="left")
    ttk.Combobox(r, textvariable=v["model"], values=list(WHISPER_MODELS), state="readonly", width=16).pack(
        side="left", padx=6)
    model_l = ttk.Label(r, style="Hint.TLabel")
    model_l.pack(side="left", padx=(0, 14))
    ttk.Label(r, text="Language").pack(side="left")
    ttk.Combobox(r, textvariable=v["lang"], values=list(WHISPER_LANGS), state="readonly", width=14).pack(
        side="left", padx=6)
    r2 = ttk.Frame(sf)
    r2.pack(fill="x", pady=(8, 0))
    ttk.Checkbutton(r2, text="Use the graphics card (much faster; the processor takes over if it can't)",
                    variable=v["gpu"]).pack(side="left")
    ttk.Checkbutton(r2, text="Voice detection (skips silence, but much slower)", variable=v["vad"]).pack(side="left", padx=14)
    engine_l = ttk.Label(sf, style="Hint.TLabel", wraplength=1000, justify="left")
    engine_l.pack(anchor="w", pady=(6, 0))

    # 3. output
    of = ttk.LabelFrame(body, text="3. Documents (named after each file: \"<name> transcript\")")
    of.pack(fill="x", pady=(12, 0))
    r3 = ttk.Frame(of)
    r3.pack(fill="x")
    for k in DOC_FORMATS:
        ttk.Checkbutton(r3, text=FORMAT_TEXT[k], variable=v[k]).pack(side="left", padx=(0, 14))
    r4 = ttk.Frame(of)
    r4.pack(fill="x", pady=(8, 0))
    ttk.Label(r4, text="Save to folder").pack(side="left")
    ttk.Entry(r4, textvariable=v["folder"], width=60).pack(side="left", padx=6, fill="x", expand=True)
    ttk.Button(r4, text="Browse...", style="Tool.TButton", command=lambda: v["folder"].set(
        filedialog.askdirectory(parent=page, title="Save transcripts to", initialdir=v["folder"].get() or None)
        or v["folder"].get())).pack(side="left")
    ttk.Label(r4, text="blank = beside each file", style="Hint.TLabel").pack(side="left", padx=6)

    # run
    rf = ttk.Frame(body)
    rf.pack(fill="x", pady=(14, 0))
    start_b = ttk.Button(rf, text="Start", style="Accent.TButton", width=12)
    start_b.pack(side="left")
    cancel_b = ttk.Button(rf, text="Cancel", width=10, state="disabled")
    cancel_b.pack(side="left", padx=6)
    ttk.Button(rf, text="Open result", command=lambda: open_result()).pack(side="left", padx=(6, 0))
    ttk.Button(rf, text="Open folder", command=lambda: open_result(folder=True)).pack(side="left", padx=6)
    status = ttk.Label(rf, style="Status.TLabel", anchor="w", wraplength=700, justify="left")
    status.pack(side="left", fill="x", expand=True, padx=8)

    def show_status(text=None):
        if text is None:
            n = sum(tv.set(it["iid"], "status").startswith("done") for it in items)
            text = (f"{len(items)} file(s), {n} done." if items else "Add videos, recordings or a folder to begin.")
        status.config(text=text)

    def show_model(*_):
        name = v["model"].get()
        size = WHISPER_MODELS[name][0] / 1e6
        model_l.config(text=f"{size:,.0f} MB" + (", English only" if name.endswith(".en") else "")
                       + (", downloaded" if model_ready(name) else ", downloaded the first time it's used"))

    def save(*_):
        tc.update({k: x.get() for k, x in v.items() if k not in DOC_FORMATS},
                  formats=[k for k in DOC_FORMATS if v[k].get()])
    for x in v.values():
        x.trace_add("write", save)
    v["model"].trace_add("write", show_model)
    show_model()
    show_status()

    def engine():
        if st["engine"] is None:
            st["engine"] = whisper_ok()
            engine_l.config(text="" if st["engine"] else
                            "This PC's ffmpeg can't transcribe: it has no whisper filter (it needs ffmpeg 8 or newer, "
                            "built with whisper). Install a newer ffmpeg (e.g. the gyan.dev \"full\" build), or delete "
                            "the old one and let Channel Mirror download ffmpeg again, then restart Channel Mirror.")
        return st["engine"]

    def selected():
        sel = tv.selection() or tv.focus()
        sel = sel[0] if isinstance(sel, tuple) and sel else sel
        it = next((it for it in items if it["iid"] == sel), None)
        return it or next((it for it in reversed(items) if it["out"]), None)

    def open_result(folder=False):
        it = selected()
        if not it or not it["out"]:
            return show_status("Nothing transcribed yet - pick a finished file.")
        f = next(iter(it["out"].values()))
        os.startfile(f.parent if folder else f)
    tv.bind("<Double-1>", lambda e: open_result())

    def start():
        if st["busy"]:
            return
        todo = [it for it in items if not tv.set(it["iid"], "status").startswith("done")]
        formats = [k for k in DOC_FORMATS if v[k].get()]
        if not todo:
            return show_status("Add videos or recordings first." if not items else "Everything here is done.")
        if not formats:
            return messagebox.showerror("Transcribe", "Tick at least one kind of document to write.", parent=page)
        if not engine():
            return messagebox.showerror("Transcribe", engine_l.cget("text"), parent=page)
        name, lang = v["model"].get(), WHISPER_LANGS[v["lang"].get()]
        if name.endswith(".en"):
            if lang not in ("auto", "en"):
                return messagebox.showerror("Transcribe", f"The {name} model only understands English - pick a model "
                                            "without .en for other languages.", parent=page)
            lang = "en"
        folder = v["folder"].get().strip() or None
        need = [(name, WHISPER_MODELS)] if not model_ready(name) else []
        if v["vad"].get() and not model_ready(VAD_MODEL, VAD_MODELS):
            need.append((VAD_MODEL, VAD_MODELS))
        if need:
            mb = sum(t[n][0] for n, t in need) / 1e6
            what = " and ".join(("the voice detection model" if t is VAD_MODELS else f"the {n} speech model")
                                for n, t in need)
            if not messagebox.askyesno("Download speech model", f"{what[0].upper() + what[1:]} isn't on this PC yet. "
                                       f"Download it now ({mb:,.1f} MB, once) from the whisper.cpp project on Hugging "
                                       "Face?", parent=page):
                return show_status("Not started: the speech model is needed first.")
        cancel = threading.Event()
        st.update(busy=True, cancel=cancel)
        start_b.state(["disabled"])
        cancel_b.state(["!disabled"])
        for it in todo:
            tv.set(it["iid"], "status", "waiting")
        threading.Thread(target=work, daemon=True, args=(todo, name, lang, v["gpu"].get(), v["vad"].get(), folder,
                                                         formats, need, cancel)).start()
        poll()

    def work(todo, name, lang, gpu, vad, folder, formats, need, cancel):
        """The worker thread: downloads, then each file in turn; everything it says goes through q."""
        try:
            last = [0.0]

            def said(msg, frac=None):
                if time.time() - last[0] > 0.25:
                    last[0] = time.time()
                    q.put(("status", msg))
            for n, table in need:
                model_download(n, said, cancel, table, VAD_URL if table is VAD_MODELS else WHISPER_URL)
            q.put(("model",))
            model, vad_m = model_file(name), model_file(VAD_MODEL, VAD_MODELS) if vad else None
        except Cancelled:
            return q.put(("end", "Cancelled."))
        except Exception as e:  # anything at all: the tab must never stay stuck on "busy"
            return q.put(("end", f"The speech model couldn't be downloaded: {e}"))
        done = failed = 0
        taken = set()  # two files of the same name (to one folder): their transcripts both kept
        t0 = time.time()
        for it in todo:
            q.put(("row", it, "transcribing 0%", ""))
            seen = [-1]

            def progress(frac, it=it):
                pct = int(frac * 100)
                if pct != seen[0]:
                    seen[0] = pct
                    q.put(("row", it, f"transcribing {pct}%", ""))
            info = {}
            try:
                segs = transcribe(it["path"], model, lang, gpu, vad_m, progress, cancel, info=info)
                out = write_transcript(it["path"], segs, folder, formats, taken=taken)
            except Cancelled:
                q.put(("row", it, "cancelled", ""))
                return q.put(("end", f"Cancelled. {done} done, {failed} failed."))
            except ValueError as e:
                failed += 1
                q.put(("row", it, "failed: no audio in it" if "No readable audio" in str(e) else "failed", str(e)))
                continue
            except Exception as e:  # ffmpeg failed, a disk / font problem: this file fails, the rest go on
                failed += 1
                q.put(("row", it, "failed", str(e).splitlines()[-1] if str(e).strip() else "ffmpeg failed"))
                continue
            done += 1
            it["out"] = out
            note = "" if info.get("gpu", gpu) == gpu else ", on the processor"
            q.put(("row", it, f"done ({len(segs)} lines{note})", ", ".join(p.name for p in out.values())))
        q.put(("end", f"Finished in {time.time() - t0:.0f} s: {done} done" + (f", {failed} failed" if failed else "")
                      + "."))

    def poll():
        try:
            while True:
                msg = q.get_nowait()
                if msg[0] == "status":
                    show_status(msg[1])
                elif msg[0] == "model":
                    show_model()
                elif msg[0] == "row":
                    _, it, text, result = msg
                    if tv.exists(it["iid"]):
                        tv.set(it["iid"], "status", text)
                        tv.set(it["iid"], "result", result)
                        if text.startswith("transcribing"):
                            show_status(f"{it['path'].name}: {text}")
                elif msg[0] == "end":
                    st.update(busy=False, cancel=None)
                    start_b.state(["!disabled"])
                    cancel_b.state(["disabled"])
                    for it in items:
                        if tv.set(it["iid"], "status").startswith("transcribing"):
                            tv.set(it["iid"], "status", "waiting")
                    return show_status(msg[1])
        except queue.Empty:
            pass
        page.after(150, poll)

    def cancel_now():
        if st["cancel"] is not None:
            st["cancel"].set()
            show_status("Cancelling...")
    start_b.config(command=start)
    cancel_b.config(command=cancel_now)

    def closing(e):
        """The app is closing: a running ffmpeg is stopped now, not left working in the background."""
        c = st["cancel"]
        if e.widget is page and c is not None:
            c.set()
            if getattr(c, "proc", None) is not None and c.proc.poll() is None:
                c.proc.kill()
    page.bind("<Destroy>", closing, add="+")
    return {"add": add, "start": start, "cancel": cancel_now, "vars": v, "state": st, "list": tv, "items": items}
