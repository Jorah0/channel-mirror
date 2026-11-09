"""Channel Mirror - pick source channel(s) (auto = loudest, or L/R) and route each to Left, Right and/or Both.

Every channel that is not a target is silent in the output. Source files are never modified.
Output names: "<name>_<left|right|both><ext>", or "<name>_from<L|R>_<target><ext>" when several sources are ticked.
Needs: numpy, plus ffmpeg + ffprobe on PATH (any format ffmpeg reads: wav, mp3, flac, m4a, ...).

    python channel_mirror.py             # open the menu window
    python channel_mirror.py --selftest  # quick end-to-end check
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

FRAMES_PER_READ = 1 << 18
SOURCES = ("Auto (loudest)", "L", "R")
TARGETS = {"Both": "both", "Left": "left", "Right": "right"}
AUDIO_EXT = (".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma")


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-of", "json",
         "-show_entries", "stream=codec_name,channels,channel_layout,bit_rate", str(path)],
        capture_output=True, text=True)
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
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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


def out_name(src, target, from_=None):
    return f"{src.stem}{f'_from{from_}' if from_ else ''}_{target}{src.suffix}"


def plan_jobs(src, rms, sources, targets):
    """Every (source x target) combo as (channel, target, output name); combos resolving to the same channel are merged."""
    names = labels(len(rms))
    jobs, seen = [], set()
    for s in sources:
        ch, _ = pick_source(rms, s)
        for t in targets:
            if (ch, t) not in seen:
                seen.add((ch, t))
                jobs.append((ch, t, out_name(src, t, names[ch] if len(sources) > 1 else None)))
    return jobs


def route(src, dst, info, ch, target):
    """Write dst with input channel `ch` on the target channel(s) ("left"/"right"/"both"); all others silent."""
    n = int(info["channels"])
    out_n, layout = (2, "stereo") if n <= 2 else (n, info.get("channel_layout") or f"{n}c")
    outs = {"left": [0], "right": [1], "both": range(out_n)}[target]
    pan = f"pan={layout}|" + "|".join(f"c{i}=c{ch}" for i in outs)  # unlisted output channels = silence
    base = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:v", "copy", "-af", pan]
    keep = ["-c:a", info["codec_name"]] + (["-b:a", info["bit_rate"]] if info.get("bit_rate") else [])
    # ponytail: if the source codec has no encoder (e.g. wmapro), fall back to ffmpeg's default for the extension
    for extra in (keep, []):
        r = subprocess.run(base + extra + [str(dst)], capture_output=True, text=True)
        if r.returncode == 0:
            return
    raise RuntimeError(f"ffmpeg failed writing {Path(dst).name}:\n{r.stderr.strip()[-500:]}")


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox

    items = []  # (path, info, rms)
    root = tk.Tk()
    root.title("Channel Mirror")
    root.geometry("960x420")

    bar = tk.Frame(root)
    bar.pack(fill="x", padx=8, pady=(6, 0))
    opts = tk.Frame(root)
    opts.pack(fill="x", padx=8, pady=6)
    lst = tk.Listbox(root, font=("Consolas", 10))
    lst.pack(fill="both", expand=True, padx=8)
    status = tk.Label(root, anchor="w", text="Add audio files or a folder to analyze.")
    status.pack(fill="x", padx=8, pady=4)

    src_vars = {s: tk.BooleanVar(value=s.startswith("Auto")) for s in SOURCES}
    tgt_vars = {t: tk.BooleanVar(value=t == "both") for t in TARGETS.values()}

    def chosen():
        return [s for s, v in src_vars.items() if v.get()], [t for t, v in tgt_vars.items() if v.get()]

    def refresh(*_):
        lst.delete(0, "end")
        sources, targets = chosen()
        for src, _, rms in items:
            names = labels(len(rms))
            levels = "  ".join(f"{nm} {v:6.1f} dB" for nm, v in zip(names, db(rms)))
            jobs = plan_jobs(src, rms, sources, targets)
            outs = ", ".join(j[2] for j in jobs) or "(nothing selected)"
            lst.insert("end", f"{src.name}  |  {levels}  |  loudest {names[int(np.argmax(rms))]}  |  {len(jobs)} out: {outs}")
        status.config(text=f"{len(items)} file(s), {sum(len(plan_jobs(p, r, sources, targets)) for p, _, r in items)} output(s) planned.")

    def busy(msg):
        status.config(text=msg)
        root.config(cursor="watch")
        root.update()  # ponytail: work runs on the UI thread; move to a thread if huge batches freeze it too long

    def load(paths):
        have = {p for p, _, _ in items}
        for i, p in enumerate(paths, 1):
            p = Path(p)
            if p in have:
                continue
            busy(f"Analyzing {i}/{len(paths)}: {p.name}...")
            try:
                info, rms, _ = analyze(p)
                items.append((p, info, rms))
            except Exception as e:
                messagebox.showerror("Analyze failed", str(e))
        root.config(cursor="")
        refresh()

    def add_files():
        load(filedialog.askopenfilenames(title="Select audio files", filetypes=[
            ("Audio", " ".join(f"*{e}" for e in AUDIO_EXT)), ("All files", "*.*")]))

    def add_folder():
        folder = filedialog.askdirectory(title="Add every audio file in folder")
        if folder:
            load(sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in AUDIO_EXT))

    def clear():
        items.clear()
        refresh()

    def save():
        sources, targets = chosen()
        if not items or not sources or not targets:
            messagebox.showinfo("Nothing to save", "Add files and tick at least one source and one output.")
            return
        folder = filedialog.askdirectory(title="Save output files to...", initialdir=items[0][0].parent)
        if not folder:
            return
        jobs, planned = [], set()
        for src, info, rms in items:
            for ch, target, name in plan_jobs(src, rms, sources, targets):
                dst, k = Path(folder) / name, 2
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
                route(src, dst, info, ch, target)
                done += 1
            except Exception as e:
                failed.append(f"{dst.name}: {e}")
        root.config(cursor="")
        status.config(text=f"Saved {done} file(s) to {folder}" + (f", {len(failed)} failed" if failed else ""))
        msg = f"Saved {done} file(s) to:\n{folder}"
        if failed:
            messagebox.showerror("Done with errors", msg + "\n\nFailed:\n" + "\n".join(failed[:20]))
        else:
            messagebox.showinfo("Done", msg)

    for text, cmd in (("Add files...", add_files), ("Add folder...", add_folder), ("Save output files...", save),
                      ("Clear", clear), ("Quit", root.destroy)):
        tk.Button(bar, text=text, command=cmd, width=18 if "Save" in text else 12).pack(side="left", padx=3)

    def group(title, vars_, text_for):
        tk.Label(opts, text=title).pack(side="left")
        all_var = tk.BooleanVar(value=all(v.get() for v in vars_.values()))
        def toggle_all():
            on = all_var.get()  # read once: setting each box re-syncs all_var mid-loop
            for v in vars_.values():
                v.set(on)
        tk.Checkbutton(opts, text="All", variable=all_var, command=toggle_all).pack(side="left")
        for key, v in vars_.items():
            tk.Checkbutton(opts, text=text_for(key), variable=v).pack(side="left")
            v.trace_add("write", lambda *_: (all_var.set(all(x.get() for x in vars_.values())), refresh()))
        tk.Frame(opts, width=24).pack(side="left")

    group("Source:", src_vars, lambda s: s)
    group("Output to:", tgt_vars, str.capitalize)
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
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else gui()
