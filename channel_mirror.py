"""Channel Mirror - pick source channel(s) (auto = loudest, or L/R) and route each to Left, Right and/or Both.

Every channel that is not a target is silent in the output. Source files are never modified.
Output names: "<name>_<left|right|both><ext>", or "<name>_from<L|R>_<target><ext>" when several sources are ticked.
Needs: numpy, plus ffmpeg + ffprobe on PATH (any format ffmpeg reads: wav, mp3, flac, m4a, ...).

    pythonw channel_mirror.py            # open the desktop window (no console)
    python channel_mirror.py --selftest  # quick end-to-end check
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

FRAMES_PER_READ = 1 << 18
SOURCES = ("Auto (loudest)", "L", "R")
TARGETS = {"Both": "both", "Left": "left", "Right": "right"}
AUDIO_EXT = (".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma")
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts")
# audio-only output from a video: container per audio codec; pcm_* -> .wav, anything else -> .mka (holds any codec)
AUDIO_ONLY_EXT = {"aac": ".m4a", "alac": ".m4a", "mp3": ".mp3", "opus": ".opus", "vorbis": ".ogg",
                  "flac": ".flac", "ac3": ".ac3", "eac3": ".eac3"}
SETTINGS = Path.home() / ".channel_mirror.json"
# ponytail: pythonw has no console, so keep ffmpeg/ffprobe from flashing one per file
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# the packaged ChannelMirror.exe also finds ffmpeg.exe / ffprobe.exe placed next to it
if getattr(sys, "frozen", False):
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-of", "json",
         "-show_entries", "stream=codec_name,channels,channel_layout,bit_rate", str(path)],
        capture_output=True, text=True, creationflags=NO_WINDOW)
    streams = json.loads(out.stdout or "{}").get("streams")
    if out.returncode or not streams:
        raise ValueError(f"No readable audio stream in {Path(path).name}")
    return streams[0]


def analyze(path):
    """Return (probe info, per-channel RMS, per-channel peak), streamed so big files are fine."""
    info = probe(path)
    n = int(info["channels"])
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    sq, peak, frames = np.zeros(n), np.zeros(n), 0
    while chunk := proc.stdout.read(FRAMES_PER_READ * 4 * n):  # blocks for full frames until EOF
        a = np.frombuffer(chunk, "<f4").reshape(-1, n).astype(np.float64)
        sq += (a * a).sum(0)
        peak = np.maximum(peak, np.abs(a).max(0))
        frames += len(a)
    if proc.wait():
        raise RuntimeError(f"ffmpeg could not decode {Path(path).name}")
    return info, np.sqrt(sq / max(frames, 1)), peak


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-10))


def labels(n):
    return ["M"] if n == 1 else ["L", "R"] if n == 2 else [f"ch{i + 1}" for i in range(n)]


def pick_source(rms, choice):
    """Return (channel index, was_auto). Manual L/R on a mono file falls back to its only channel."""
    if choice.startswith("Auto"):
        return int(np.argmax(rms)), True
    return min("LR".index(choice), len(rms) - 1), False


def out_ext(src, info, audio_only):
    """Extension for the output: the source's own, unless a video is being written as audio only."""
    if not audio_only or src.suffix.lower() in AUDIO_EXT:
        return src.suffix
    codec = info["codec_name"]
    return ".wav" if codec.startswith("pcm_") else AUDIO_ONLY_EXT.get(codec, ".mka")


def out_name(src, target, from_=None, ext=None):
    return f"{src.stem}{f'_from{from_}' if from_ else ''}_{target}{ext or src.suffix}"


def plan_jobs(src, rms, sources, targets, ext=None):
    """Every (source x target) combo as (channel, target, output name); combos resolving to the same channel are merged."""
    names = labels(len(rms))
    jobs, seen = [], set()
    for s in sources:
        ch, _ = pick_source(rms, s)
        for t in targets:
            if (ch, t) not in seen:
                seen.add((ch, t))
                jobs.append((ch, t, out_name(src, t, names[ch] if len(sources) > 1 else None, ext)))
    return jobs


def route(src, dst, info, ch, target, audio_only=False):
    """Write dst with input channel `ch` on the target channel(s) ("left"/"right"/"both"); all others silent.
    Video streams are copied untouched unless audio_only."""
    n = int(info["channels"])
    out_n, layout = (2, "stereo") if n <= 2 else (n, info.get("channel_layout") or f"{n}c")
    outs = {"left": [0], "right": [1], "both": range(out_n)}[target]
    pan = f"pan={layout}|" + "|".join(f"c{i}=c{ch}" for i in outs)  # unlisted output channels = silence
    if audio_only:
        maps = ["-map", "0:a:0"]
    elif src.suffix.lower() in AUDIO_EXT:
        maps = ["-c:v", "copy"]  # audio file: ffmpeg's default mapping keeps cover art only where the format allows it
    else:
        maps = ["-map", "0:v?", "-map", "0:a:0", "-c:v", "copy"]  # same audio track that analyze() measured
    base = ["ffmpeg", "-v", "error", "-y", "-i", str(src), *maps, "-af", pan]
    keep = ["-c:a", info["codec_name"]] + (["-b:a", info["bit_rate"]] if info.get("bit_rate") else [])
    # ponytail: if the source codec has no encoder (e.g. wmapro), fall back to ffmpeg's default for the extension
    for extra in (keep, []):
        r = subprocess.run(base + extra + [str(dst)], capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode == 0:
            return
    raise RuntimeError(f"ffmpeg failed writing {Path(dst).name}:\n{r.stderr.strip()[-500:]}")


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox

    try:
        cfg = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        cfg = {}
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on scaled Windows displays
    except (AttributeError, OSError):
        pass
    items = []  # (path, info, rms)
    root = tk.Tk()
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        root.withdraw()
        messagebox.showerror("Channel Mirror", "ffmpeg and ffprobe were not found.\n\nInstall with:  winget install Gyan.FFmpeg\n"
                             "or put ffmpeg.exe and ffprobe.exe next to ChannelMirror.exe, then start it again.")
        root.destroy()
        return
    root.title("Channel Mirror")
    pad = {"padx": 10, "pady": 4}

    # 1. Input files
    inp = tk.LabelFrame(root, text=" 1. Input files ")
    inp.pack(fill="both", expand=True, **pad)
    side = tk.Frame(inp)
    side.pack(side="right", fill="y", padx=6, pady=4)
    box = tk.Frame(inp)
    box.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
    lst = tk.Listbox(box, font=("Consolas", 10), selectmode="extended", width=110, height=12)
    ys = tk.Scrollbar(box, command=lst.yview)
    xs = tk.Scrollbar(box, orient="horizontal", command=lst.xview)
    lst.config(yscrollcommand=ys.set, xscrollcommand=xs.set)
    ys.pack(side="right", fill="y")
    xs.pack(side="bottom", fill="x")
    lst.pack(fill="both", expand=True)

    # 2. Settings
    sett = tk.LabelFrame(root, text=" 2. Settings ")
    sett.pack(fill="x", **pad)
    src_on, tgt_on = cfg.get("sources", ["Auto (loudest)"]), cfg.get("targets", ["both"])
    src_vars = {s: tk.BooleanVar(value=s in src_on) for s in SOURCES}
    tgt_vars = {t: tk.BooleanVar(value=t in tgt_on) for t in TARGETS.values()}
    mode_var = tk.StringVar(value="audio" if cfg.get("output_type") == "audio" else "same")

    def audio_only():
        return mode_var.get() == "audio"

    # 3. Output folder
    outf = tk.LabelFrame(root, text=" 3. Output folder (blank = next to each input file) ")
    outf.pack(fill="x", **pad)
    out_var = tk.StringVar(value=cfg.get("out_dir", ""))
    tk.Entry(outf, textvariable=out_var).pack(side="left", fill="x", expand=True, padx=6, pady=6)

    runbar = tk.Frame(root)
    runbar.pack(fill="x", padx=10, pady=(4, 10))
    status = tk.Label(runbar, anchor="w", text="Add audio files or a folder to begin.")

    def chosen():
        return [s for s, v in src_vars.items() if v.get()], [t for t, v in tgt_vars.items() if v.get()]

    def save_settings():
        sources, targets = chosen()
        try:
            SETTINGS.write_text(json.dumps({"sources": sources, "targets": targets, "out_dir": out_var.get().strip(),
                                            "output_type": mode_var.get()}))
        except OSError:
            pass  # settings are a convenience; never block the user over them

    def refresh(*_):
        lst.delete(0, "end")
        sources, targets = chosen()
        total = 0
        for src, info, rms in items:
            names = labels(len(rms))
            levels = "  ".join(f"{nm} {v:6.1f} dB" for nm, v in zip(names, db(rms)))
            jobs = plan_jobs(src, rms, sources, targets, out_ext(src, info, audio_only()))
            total += len(jobs)
            outs = ", ".join(j[2] for j in jobs) or "(nothing selected)"
            lst.insert("end", f"{src.name}  |  {levels}  |  loudest {names[int(np.argmax(rms))]}  |  {len(jobs)} out: {outs}")
        status.config(text=f"{len(items)} file(s) loaded, {total} output file(s) will be written.")

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
            load(sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in AUDIO_EXT + VIDEO_EXT))

    def remove_selected():
        for i in reversed(lst.curselection()):
            del items[i]
        refresh()

    def clear():
        items.clear()
        refresh()

    def browse_out():
        folder = filedialog.askdirectory(title="Save output files to...")
        if folder:
            out_var.set(folder)

    def run():
        sources, targets = chosen()
        if not items or not sources or not targets:
            messagebox.showinfo("Nothing to run", "Add files and tick at least one source and one output.")
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
            for ch, target, name in plan_jobs(src, rms, sources, targets, out_ext(src, info, audio_only())):
                dst, k = (Path(folder) if folder else src.parent) / name, 2
                while dst in planned or dst.resolve() == src.resolve():  # same-named inputs / never touch originals
                    dst, k = dst.with_name(f"{Path(name).stem}_{k}{dst.suffix}"), k + 1
                planned.add(dst)
                jobs.append((src, info, ch, target, dst))
        existing = [j for j in jobs if j[4].exists()]
        if existing:
            ans = messagebox.askyesnocancel(
                "Files exist", f"{len(existing)} output file(s) already exist.\nYes = overwrite, No = skip them.")
            if ans is None:
                return
            if not ans:
                jobs = [j for j in jobs if not j[4].exists()]
        done, failed = 0, []
        for i, (src, info, ch, target, dst) in enumerate(jobs, 1):
            busy(f"Writing {i}/{len(jobs)}: {dst.name}")
            try:
                route(src, dst, info, ch, target, audio_only())
                done += 1
            except Exception as e:
                failed.append(f"{dst.name}: {e}")
        root.config(cursor="")
        where = folder or "next to each input file"
        status.config(text=f"Done: {done} file(s) written ({where})" + (f", {len(failed)} failed" if failed else ""))
        msg = f"Wrote {done} file(s)\n{where}"
        if failed:
            messagebox.showerror("Done with errors", msg + "\n\nFailed:\n" + "\n".join(failed[:20]))
        else:
            messagebox.showinfo("Done", msg)

    for text, cmd in (("Add files...", add_files), ("Add folder...", add_folder),
                      ("Remove selected", remove_selected), ("Clear all", clear)):
        tk.Button(side, text=text, command=cmd, width=16).pack(pady=2)
    tk.Button(outf, text="Browse...", command=browse_out, width=12).pack(side="left", padx=(0, 6))
    tk.Button(runbar, text="Run", command=run, width=14, font=("Segoe UI", 11, "bold")).pack(side="left")
    status.pack(side="left", fill="x", expand=True, padx=10)

    def group(title, vars_, text_for):
        row = tk.Frame(sett)
        row.pack(fill="x", padx=6, pady=3)
        tk.Label(row, text=title, width=16, anchor="w").pack(side="left")
        all_var = tk.BooleanVar(value=all(v.get() for v in vars_.values()))

        def toggle_all():
            on = all_var.get()  # read once: setting each box re-syncs all_var mid-loop
            for v in vars_.values():
                v.set(on)
        tk.Checkbutton(row, text="All", variable=all_var, command=toggle_all).pack(side="left")
        for key, v in vars_.items():
            tk.Checkbutton(row, text=text_for(key), variable=v).pack(side="left", padx=4)
            v.trace_add("write", lambda *_: (all_var.set(all(x.get() for x in vars_.values())), refresh()))

    group("Source channel:", src_vars, lambda s: s)
    group("Output to:", tgt_vars, str.capitalize)
    row = tk.Frame(sett)
    row.pack(fill="x", padx=6, pady=3)
    tk.Label(row, text="Output type:", width=16, anchor="w").pack(side="left")
    for value, text in (("same", "Same as input (videos keep their video)"), ("audio", "Audio only")):
        tk.Radiobutton(row, text=text, variable=mode_var, value=value).pack(side="left", padx=4)
    mode_var.trace_add("write", refresh)

    def on_close():
        save_settings()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def selftest():
    import tempfile
    import wave

    def write_wav(path, chans):
        pcm = (np.stack(chans, 1) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(len(chans)), w.setsampwidth(2), w.setframerate(44100), w.writeframes(pcm.tobytes())

    t = np.arange(44100) / 44100
    loud, quiet = 0.8 * np.sin(2 * np.pi * 440 * t), 0.05 * np.sin(2 * np.pi * 660 * t)
    with tempfile.TemporaryDirectory() as d:
        st, mono = Path(d) / "st.wav", Path(d) / "mono.wav"
        write_wav(st, [loud, quiet])
        write_wav(mono, [loud])
        info, rms, _ = analyze(st)
        assert pick_source(rms, "Auto (loudest)") == (0, True), rms
        assert pick_source(rms, "R") == (1, False)

        # planning: single source keeps plain names; all sources x all targets = 6 unique files (Auto==L merged)
        assert [j[2] for j in plan_jobs(st, rms, ["R"], ["left"])] == ["st_left.wav"]
        every = plan_jobs(st, rms, list(SOURCES), list(TARGETS.values()))
        assert len(every) == 6 and len({j[2] for j in every}) == 6, every
        assert len(plan_jobs(mono, rms[:1], list(SOURCES), ["both"])) == 1  # mono: all sources are the same channel

        cases = [(st, 0, "both", [rms[0], rms[0]]), (st, 0, "left", [rms[0], 0]),
                 (st, 0, "right", [0, rms[0]]), (st, 1, "left", [rms[1], 0]),
                 (mono, 0, "right", [0, rms[0]])]
        for src, ch, target, want in cases:
            dst = Path(d) / f"out_{ch}_{target}_{src.name}"
            route(src, dst, probe(src), ch, target)
            info2, got, _ = analyze(dst)
            assert info2["channels"] == 2 and info2["codec_name"] == "pcm_s16le", info2
            assert np.allclose(got, want, atol=1e-3), (src.name, ch, target, got, want)
            assert all(g == 0 for g, w in zip(got, want) if w == 0), "cleared channel not fully silent"
        assert np.allclose(analyze(st)[1], rms), "source was modified"

        # video input: "same" keeps the video stream, "audio only" writes an .m4a with no video
        vid = Path(d) / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=1",
                        "-f", "lavfi", "-i", "sine=f=440:d=1", "-f", "lavfi", "-i", "sine=f=660:d=1",
                        "-filter_complex", "[1][2]amerge=inputs=2,pan=stereo|c0=0.8*c0|c1=0.05*c1[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "mpeg4", "-c:a", "aac", str(vid)],
                       check=True, creationflags=NO_WINDOW)
        kinds = lambda p: sorted(s["codec_type"] for s in json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(p)],
            capture_output=True, text=True, creationflags=NO_WINDOW).stdout)["streams"])
        vinfo, vrms, _ = analyze(vid)
        assert int(np.argmax(vrms)) == 0, vrms
        assert out_ext(st, info, True) == ".wav"  # audio inputs keep their own extension
        for only, ext, want in ((False, ".mp4", ["audio", "video"]), (True, ".m4a", ["audio"])):
            assert out_ext(vid, vinfo, only) == ext
            dst = Path(d) / out_name(vid, "right", ext=ext)
            route(vid, dst, vinfo, 0, "right", only)
            assert kinds(dst) == want, (dst.name, kinds(dst))
            got = analyze(dst)[1]
            assert got[0] < 1e-4 and abs(got[1] - vrms[0]) < 0.01, (dst.name, got, vrms)
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else gui()
