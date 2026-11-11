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
# used for the file picker / folder scan; any other file ffmpeg finds audio in also works ("All files", drag-drop)
AUDIO_EXT = (".wav", ".mp3", ".flac", ".m4a", ".m4b", ".aac", ".ogg", ".oga", ".opus", ".spx", ".aiff", ".aif",
             ".aifc", ".wma", ".alac", ".ape", ".wv", ".mka", ".ac3", ".eac3", ".dts", ".amr", ".au", ".snd",
             ".caf", ".mp2", ".mpc", ".tta", ".tak", ".shn", ".dsf", ".dff", ".w64", ".rf64", ".voc", ".gsm", ".ra")
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".mts",
             ".m2ts", ".3gp", ".3g2", ".vob", ".ogv", ".asf", ".rm", ".rmvb", ".f4v", ".mxf", ".divx", ".dv")
# dropdown label -> mode: "same", "audio" (audio only, source codec) or an output extension
OUTPUT_TYPES = {"Same as input (videos keep video)": "same", "Audio only (match source codec)": "audio",
                "WAV": "wav", "MP3": "mp3", "FLAC": "flac", "M4A (AAC)": "m4a", "OGG (Vorbis)": "ogg",
                "OPUS": "opus", "AIFF": "aiff", "MP4 (video + audio)": "mp4", "MKV (video + audio)": "mkv",
                "MOV (video + audio)": "mov"}
VIDEO_OUT = ("mp4", "mkv", "mov")
ENCODER_OPTS = {"mp3": ["-q:a", "2"], "ogg": ["-q:a", "6"], "opus": ["-b:a", "160k"],
                "m4a": ["-b:a", "192k"], "mp4": ["-b:a", "192k"], "mov": ["-b:a", "192k"]}
# audio-only output from a video: container per audio codec; pcm_* -> .wav, anything else -> .mka (holds any codec)
AUDIO_ONLY_EXT = {"aac": ".m4a", "alac": ".m4a", "mp3": ".mp3", "opus": ".opus", "vorbis": ".ogg",
                  "flac": ".flac", "ac3": ".ac3", "eac3": ".eac3"}
SETTINGS = Path.home() / ".channel_mirror.json"
# ponytail: pythonw has no console, so keep ffmpeg/ffprobe from flashing one per file
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# the packaged ChannelMirror.exe also finds ffmpeg.exe / ffprobe.exe placed next to it
if getattr(sys, "frozen", False):
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
# first-run setup downloads ffmpeg here when it isn't installed; always on PATH so later starts find it
FFMPEG_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ChannelMirror" / "ffmpeg"
FFMPEG_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"  # the build ffmpeg.org links for Windows
os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(FFMPEG_DIR)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))  # _MEIPASS = unpacked exe bundle


def download_ffmpeg(progress=print, url=FFMPEG_ZIP, dest=FFMPEG_DIR):
    """Download the ffmpeg zip, check it against its published .sha256, and put ffmpeg.exe + ffprobe.exe in dest."""
    import hashlib
    import tempfile
    import urllib.request
    import zipfile

    with urllib.request.urlopen(url + ".sha256", timeout=30) as r:
        want = r.read().decode().split()[0].lower()
    h = hashlib.sha256()
    with tempfile.TemporaryFile() as tmp:
        with urllib.request.urlopen(url, timeout=30) as r:
            total, got = int(r.headers.get("Content-Length") or 0), 0
            while chunk := r.read(1 << 16):
                tmp.write(chunk)
                h.update(chunk)
                got += len(chunk)
                progress(f"Downloading ffmpeg... {got >> 20} MB" + (f" of {total >> 20} MB" if total else ""))
        if h.hexdigest() != want:
            raise RuntimeError("the download is damaged (checksum mismatch); please try again")
        progress("Unpacking ffmpeg...")
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp) as z:
            for name in ("ffmpeg.exe", "ffprobe.exe"):
                member = next((m for m in z.namelist() if m.endswith("/bin/" + name)), None)
                if not member:
                    raise RuntimeError(f"{name} is missing from the download")
                part = dest / (name + ".part")  # never leave a half-written exe under the real name
                part.write_bytes(z.read(member))
                os.replace(part, dest / name)


# --- self-install: the one ChannelMirror.exe is also its own installer / updater / uninstaller ---
VERSION = "2.0"
APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / "ChannelMirror"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ChannelMirror"


def shortcut_paths():
    """Where install() puts shortcuts: {"start", "desktop", "sendto"} -> .lnk path (per user, no admin needed)."""
    import winreg
    roaming = Path(os.environ.get("APPDATA") or Path.home())
    try:  # the real Desktop (often moved into OneDrive)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            desktop = Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))
    except OSError:
        desktop = Path.home() / "Desktop"
    return {"start": roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Channel Mirror.lnk",
            "desktop": desktop / "Channel Mirror.lnk",
            "sendto": roaming / "Microsoft" / "Windows" / "SendTo" / "Channel Mirror.lnk"}


def make_shortcut(lnk, target):
    q = lambda p: str(p).replace("'", "''")  # PowerShell single-quote escaping
    lnk.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');$s.TargetPath='{q(target)}';"
                        f"$s.WorkingDirectory='{q(Path(target).parent)}';$s.IconLocation='{q(target)},0';$s.Save()"],
                       capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
    if r.returncode or not lnk.exists():
        raise OSError(f"Couldn't create shortcut {lnk.name}: {r.stderr.strip()[-300:]}")


def install(src, app_dir=APP_DIR, links=None, reg_key=UNINSTALL_KEY):
    """Copy the exe into app_dir, add the given shortcuts, register with Windows "Installed apps" (per user).
    Running it again over an older copy is the update. Returns the installed exe."""
    import winreg
    app_dir.mkdir(parents=True, exist_ok=True)
    exe = app_dir / "ChannelMirror.exe"
    if Path(src).resolve() != exe.resolve():
        shutil.copy2(src, exe)
    for lnk in (links or {}).values():
        make_shortcut(lnk, exe)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_key) as k:
        for name, val in (("DisplayName", "Channel Mirror"), ("DisplayVersion", VERSION), ("Publisher", "Jorah0"),
                          ("DisplayIcon", f"{exe},0"), ("InstallLocation", str(app_dir)),
                          ("UninstallString", f'"{exe}" --uninstall'), ("QuietUninstallString", f'"{exe}" --uninstall --quiet')):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        for name, val in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", exe.stat().st_size // 1024)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, val)
    return exe


def installed(reg_key=UNINSTALL_KEY):
    """The installed exe, or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_key) as k:
            exe = Path(winreg.QueryValueEx(k, "InstallLocation")[0]) / "ChannelMirror.exe"
        return exe if exe.exists() else None
    except OSError:
        return None


def uninstall(app_dir=APP_DIR, links=None, reg_key=UNINSTALL_KEY, data=False):
    """Remove shortcuts, the Windows entry and the program folder (deleted once this process exits, since a
    running exe can't delete itself). data=True also removes settings and the downloaded ffmpeg."""
    import winreg
    for lnk in (links or shortcut_paths()).values():
        Path(lnk).unlink(missing_ok=True)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_key)
    except OSError:
        pass
    gone = [app_dir] + ([FFMPEG_DIR.parent] if data else [])
    if data:
        SETTINGS.unlink(missing_ok=True)
    running = getattr(sys, "frozen", False) and Path(sys.executable).resolve().is_relative_to(app_dir.resolve())
    if running:
        # ponytail: a detached cmd waits ~3 s for this exe to exit, then deletes the folders
        rm = " & ".join(f'rmdir /s /q "{d}"' for d in gone)
        subprocess.Popen(f'cmd /c ping -n 4 127.0.0.1 >nul & {rm}', creationflags=NO_WINDOW | 0x00000008,
                         close_fds=True)  # 0x8 = DETACHED_PROCESS
    else:
        for d in gone:
            shutil.rmtree(d, ignore_errors=True)


def offer_install(root, cfg):
    """Frozen exe started from outside the install folder (a download): offer to install / update it.
    Returns True when the installed copy was started and this one should quit."""
    import tkinter as tk
    from tkinter import messagebox
    here = Path(sys.executable).resolve()
    if not getattr(sys, "frozen", False) or here.parent == APP_DIR.resolve() or "--portable" in sys.argv:
        return False
    have = installed()
    if not have and cfg.get("portable"):
        return False  # the user chose "just run it" before
    root.title("Channel Mirror - install")
    frame = tk.Frame(root, padx=28, pady=22)
    frame.pack()
    try:
        img = tk.PhotoImage(file=str(BUNDLE / "icon.png"))
        tk.Label(frame, image=img).pack()
        frame.img = img
    except tk.TclError:
        pass
    tk.Label(frame, text=f"Channel Mirror {VERSION}", font=("Segoe UI", 14, "bold")).pack(pady=(10, 6))
    tk.Label(frame, justify="left", wraplength=440, text=(
        f"An installed copy was found. Update it with this version?\n\n{have}" if have else
        "Install Channel Mirror on this computer? It goes in your user folder (no admin rights needed), "
        f"gets a Start menu entry and an uninstaller in Windows Settings > Apps.\n\n{APP_DIR}")).pack()
    opts = {"desktop": tk.BooleanVar(value=True), "sendto": tk.BooleanVar(value=True)}
    tk.Checkbutton(frame, text="Desktop shortcut", variable=opts["desktop"]).pack(anchor="w", pady=(10, 0))
    tk.Checkbutton(frame, text='Right-click "Send to > Channel Mirror" for files and folders',
                   variable=opts["sendto"]).pack(anchor="w")
    result = tk.StringVar()
    bar = tk.Frame(frame)
    bar.pack(pady=(16, 0))
    tk.Button(bar, text="Update" if have else "Install", width=14, font=("Segoe UI", 10, "bold"),
              command=lambda: result.set("install")).pack(side="left", padx=6)
    tk.Button(bar, text="Just run it", width=12, command=lambda: result.set("run")).pack(side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", lambda: result.set("run"))
    root.wait_variable(result)
    frame.destroy()
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    if result.get() != "install":
        cfg["portable"] = True
        try:
            SETTINGS.write_text(json.dumps(cfg))
        except OSError:
            pass
        return False
    paths = shortcut_paths()
    links = {k: p for k, p in paths.items() if k == "start" or opts[k].get()}
    try:
        for k, p in paths.items():  # unticked on an update = take that shortcut away
            if k not in links:
                p.unlink(missing_ok=True)
        exe = install(here, links=links)
    except (OSError, subprocess.SubprocessError) as e:
        messagebox.showerror("Install", f"Couldn't install:\n{e}\n\nIf Channel Mirror is open, close it and try again.")
        return False
    subprocess.Popen([str(exe), *[a for a in sys.argv[1:] if a != "--portable"]], close_fds=True)
    return True


def first_run_setup(root):
    """Shown in the main window when ffmpeg isn't found: offer to download it. True once ffmpeg is usable."""
    import tkinter as tk

    root.title("Channel Mirror - first-time setup")
    frame = tk.Frame(root, padx=28, pady=22)
    frame.pack()
    try:
        img = tk.PhotoImage(file=str(BUNDLE / "icon.png"))
        tk.Label(frame, image=img).pack()
        frame.img = img  # keep a reference or Tk drops the picture
    except tk.TclError:
        pass
    tk.Label(frame, text="Welcome to Channel Mirror", font=("Segoe UI", 14, "bold")).pack(pady=(10, 6))
    msg = tk.Label(frame, justify="left", wraplength=440, text=(
        "Channel Mirror uses ffmpeg (free) to read and write audio and video, and it isn't installed yet.\n\n"
        "Install it now? About 110 MB is downloaded from gyan.dev (the Windows build linked from ffmpeg.org), "
        f"checked, and saved to:\n{FFMPEG_DIR}\n\nThis only happens once."))
    msg.pack()
    bar = tk.Frame(frame)
    bar.pack(pady=(16, 0))
    result = tk.StringVar()
    quit_ = lambda: result.set("quit")

    def install():
        go.config(state="disabled")
        stop.config(state="disabled")
        root.protocol("WM_DELETE_WINDOW", lambda: None)  # don't close mid-download
        try:
            download_ffmpeg(lambda m: (msg.config(text=m), root.update()))
            if shutil.which("ffmpeg") and shutil.which("ffprobe"):
                result.set("ok")
                return
            raise RuntimeError("ffmpeg was unpacked but can't be found")
        except Exception as e:
            msg.config(text=f"Couldn't install ffmpeg:\n{e}\n\nCheck your internet connection and try again, or install it "
                            "yourself:  winget install Gyan.FFmpeg  (or put ffmpeg.exe and ffprobe.exe next to "
                            "ChannelMirror.exe), then start Channel Mirror again.")
            go.config(state="normal", text="Try again")
            stop.config(state="normal")
            root.protocol("WM_DELETE_WINDOW", quit_)

    go = tk.Button(bar, text="Install ffmpeg", command=install, width=16, font=("Segoe UI", 10, "bold"))
    go.pack(side="left", padx=6)
    stop = tk.Button(bar, text="Quit", command=quit_, width=10)
    stop.pack(side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", quit_)
    root.wait_variable(result)
    frame.destroy()
    return result.get() == "ok"


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-of", "json",
         "-show_entries", "stream=codec_name,channels,channel_layout,bit_rate,sample_rate", str(path)],
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
    info["duration"] = frames / int(info["sample_rate"])
    return info, np.sqrt(sq / max(frames, 1)), peak


QUIET_WINDOW = 3.0  # seconds before the requested length searched for a quiet place to end
FADE = 0.02  # seconds of fade-out on every cut, so even a cut at a quiet spot can't click
SILENCE = 10 ** (-50 / 20)  # a 20 ms block below -50 dBFS is silence


def parse_time(text):
    """'90', '1:30' or '1:02:03.5' -> seconds; blank -> None. Raises ValueError for anything else."""
    text = text.strip()
    if not text:
        return None
    secs = sum(float(p) * 60 ** i for i, p in enumerate(reversed(text.split(":"))))
    if secs <= 0:
        raise ValueError(text)
    return secs


def levels(src, info, ch, at, secs, loop=False):
    """(RMS of each ~20 ms block of channel `ch`, `secs` seconds from `at`; block length in seconds).
    With loop the window wraps past the end of the file back to its start (maybe several times)."""
    def decode(a, s):
        return np.frombuffer(subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-i", str(src), "-t", f"{s:.3f}", "-map", "0:a:0",
             "-af", f"pan=mono|c0=c{ch}", "-f", "f32le", "-acodec", "pcm_f32le", "-"],
            capture_output=True, creationflags=NO_WINDOW).stdout, "<f4")

    dur = info.get("duration") or 0
    if loop and dur:
        parts, a, left = [], at % dur, secs
        while left > 1e-3:
            take = min(left, dur - a)
            parts.append(decode(a, take))
            left, a = left - take, 0.0
        x = np.concatenate(parts)
    else:
        x = decode(at, secs)
    sr = int(info["sample_rate"])
    blk = max(sr // 50, 1)
    n = len(x) // blk
    return np.sqrt((x[:n * blk].reshape(n, blk).astype(np.float64) ** 2).mean(1)), blk / sr


def clip_seconds(src, info, ch, length, loop=False, quiet=False, at=0.0):
    """Seconds to write from `at` (None = to the end). quiet: cut in the middle of the last quiet stretch of
    channel `ch` that starts in the QUIET_WINDOW s (at most half the length) before the requested end, instead of
    cutting mid-sound. Quiet = silence, or within ~3.5 dB of the quietest moment there. With loop, the file repeats."""
    dur = info.get("duration") or 0
    if not length or (not loop and dur and at + length >= dur):
        return None
    if not quiet:
        return length
    w = min(QUIET_WINDOW, length / 2)  # never search the first half, so a part can't shrink to nothing
    start = at + length - w
    # look w/2 past the requested end too, to see where a silence straddling it ends
    level, b = levels(src, info, ch, start, w * 1.5, loop)
    k = min(round(w / b), len(level))  # blocks before the requested end
    if not k:
        return length
    q = level <= max(level[:k].min() * 1.5, SILENCE)
    i = k - 1 - int(np.argmax(q[k - 1::-1]))  # last quiet block at or before the requested end
    lo, hi = i, i
    while lo > 0 and q[lo - 1]:
        lo -= 1
    while hi + 1 < len(q) and q[hi + 1]:
        hi += 1
    # ponytail: a silence longer than the search window is measured only where it's inside it
    return start - at + (lo + hi + 1) / 2 * b


def edges(src, info, ch):
    """(start, end) of the file trimmed to the middle of any silence it starts / ends with (else 0 / duration)."""
    dur = info.get("duration") or 0
    w = min(QUIET_WINDOW, dur / 2)
    head, b = levels(src, info, ch, 0.0, w)
    loud = np.flatnonzero(head > SILENCE)
    start = (loud[0] if len(loud) else len(head)) / 2 * b
    tail, b = levels(src, info, ch, dur - w, w)
    loud = np.flatnonzero(tail > SILENCE)
    m = len(tail) - 1 - loud[-1] if len(loud) else len(tail)  # silent blocks at the very end
    return start, dur - w + (len(tail) - m / 2) * b if m else dur


def split_points(src, info, ch, length=None, count=None):
    """Consecutive (start, seconds) parts of the file (seconds None = to the end of the file). Never loops.
    length: parts of ~length, through the whole file or only the first `count` of them. No length: `count`
    roughly equal parts. Every cut is in the middle of a quiet stretch (see clip_seconds), and the first part
    starts / last part ends in the middle of any silence the file starts / ends with."""
    dur = info.get("duration") or 0
    first, end = edges(src, info, ch)
    segs, at = [], first
    while end - at > FADE and (not count or len(segs) < count):
        # equal parts aim each cut at k/count of the file, so early cuts don't pile onto the last part
        want = length or first + (end - first) * (len(segs) + 1) / count - at
        if at + want >= end - 1e-6:  # the rest fits: last part runs to the end (or its trailing silence)
            segs.append((at, None if end >= dur else end - at))
            break
        secs = min(clip_seconds(src, info, ch, want, quiet=True, at=at), end - at)
        segs.append((at, secs))
        at += secs
    return segs


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-10))


def labels(n):
    return ["M"] if n == 1 else ["L", "R"] if n == 2 else [f"ch{i + 1}" for i in range(n)]


def pick_source(rms, choice):
    """Return (channel index, was_auto). Manual L/R on a mono file falls back to its only channel."""
    if choice.startswith("Auto"):
        return int(np.argmax(rms)), True
    return min("LR".index(choice), len(rms) - 1), False


def out_ext(src, info, mode):
    """Extension for the output: the source's own ("same"), one matching the audio codec ("audio"), or the chosen one."""
    if mode == "same" or (mode == "audio" and src.suffix.lower() in AUDIO_EXT):
        return src.suffix
    if mode == "audio":
        codec = info["codec_name"]
        return ".wav" if codec.startswith("pcm_") else AUDIO_ONLY_EXT.get(codec, ".mka")
    return "." + mode


def out_name(src, target, from_=None, ext=None):
    return f"{src.stem}{f'_from{from_}' if from_ else ''}_{target}{ext or src.suffix}"


OUT_SUBDIR = "Channel Mirror output"


def out_folder(src, base=""):
    """Group outputs by where the source came from: <base>/<source folder name>/, or with no base,
    a "Channel Mirror output" folder inside the source's own folder."""
    # ponytail: two source folders with the same name share one folder under <base>; clashing names get _2, _3...
    return Path(base) / src.parent.name if base else src.parent / OUT_SUBDIR


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


def route(src, dst, info, ch, target, mode="same", seconds=None, loop=False, start=0.0):
    """Write dst with input channel `ch` on the target channel(s) ("left"/"right"/"both"); all others silent.
    mode: "same" (videos keep their video, copied), "audio" (audio only, source codec) or an OUTPUT_TYPES extension.
    seconds: cut to this length (short fade-out); loop: repeat the input to fill `seconds`.
    start: begin this far into the file (short fade-in), for split parts.
    If that format can't be written, falls back to .mkv (video) / .flac (audio). Returns the path written."""
    n = int(info["channels"])
    out_n, layout = (2, "stereo") if n <= 2 else (n, info.get("channel_layout") or f"{n}c")
    outs = {"left": [0], "right": [1], "both": range(out_n)}[target]
    pan = f"pan={layout}|" + "|".join(f"c{i}=c{ch}" for i in outs)  # unlisted output channels = silence
    pre, cut = [], []
    if seconds:
        pre = ["-stream_loop", "-1"] if loop else []
        # ponytail: copied video can only stop on a keyframe, so its last frame may run a moment past the audio
        cut = ["-t", f"{seconds:.3f}"]
        pan += f",afade=t=out:st={max(seconds - FADE, 0):.3f}:d={FADE}"
    if start:
        # ponytail: copied video can only start on a keyframe too, so a part's picture may begin a moment early
        pre += ["-ss", f"{start:.3f}"]
        pan += f",afade=t=in:d={FADE}"
    audio_src = src.suffix.lower() in AUDIO_EXT
    video = mode in VIDEO_OUT or (mode == "same" and not audio_src)  # unknown extensions count as video: 0:V? is optional
    if mode == "same" and audio_src:
        maps = [["-c:v", "copy"]]  # ffmpeg's default mapping keeps cover art only where the format allows it
    elif video:  # same audio track analyze() measured; real video only (0:V skips cover art); copy, else re-encode
        maps = [["-map", "0:V?", "-map", "0:a:0", "-c:v", "copy"], ["-map", "0:V?", "-map", "0:a:0"]]
    else:
        maps = [["-map", "0:a:0"]]
    keep = ["-c:a", info["codec_name"]] + (["-b:a", info["bit_rate"]] if info.get("bit_rate") else [])
    enc = ENCODER_OPTS.get(mode, [])
    # ponytail: try the source codec first where the container may hold it, else ffmpeg's encoder for the extension
    codecs = [enc] if mode not in ("same", "audio") and not video else [keep, enc]
    for m in maps:
        for a in codecs:
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", *pre, "-i", str(src), *m, "-af", pan, *cut, *a,
                                "-strict", "-2", str(dst)], capture_output=True, text=True, creationflags=NO_WINDOW)
            if r.returncode == 0:
                return dst
    Path(dst).unlink(missing_ok=True)  # don't leave a half-written file
    fallback = "mkv" if video else "flac"
    if Path(dst).suffix.lower() != "." + fallback:
        # ponytail: format can't hold this (6ch into mp3, read-only .ape, ...); fallback file overwrites without asking
        return route(src, Path(dst).with_suffix("." + fallback), info, ch, target, fallback, seconds, loop, start)
    raise RuntimeError(f"ffmpeg failed writing {Path(dst).name}:\n{r.stderr.strip()[-500:]}")


def media_files(paths):
    """Files stay as given; folders become every audio/video file directly inside them."""
    out = []
    for p in map(Path, paths):
        out += sorted(q for q in p.iterdir() if q.suffix.lower() in AUDIO_EXT + VIDEO_EXT) if p.is_dir() else [p]
    return out


# --- Stream Deck soundboard: sounds -> Play Audio actions in an importable .streamDeckProfile ---
# ponytail: index in each tuple = the number Stream Deck saves (actionType / fadeType), in its own dropdown order;
# if an imported key shows the wrong mode, reorder here
SD_MODES = ("Play / Stop", "Play / Overlap", "Play / Restart", "Loop / Stop")
SD_FADES = ("No Fade", "Fade In", "Fade Out", "Fade In & Out")
SD_KINDS = {"Single sound": None,
            "Multi Action": "com.elgato.streamdeck.multiactions.routine",  # every sound on the key fires at once
            "Random Action": "com.elgato.streamdeck.multiactions.random"}  # one random sound per press
SD_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "Elgato" / "StreamDeck"
SD_OUT = FFMPEG_DIR.parent / "Stream Deck profiles"
SD_BACKUPS = FFMPEG_DIR.parent / "Stream Deck backups"
SD_EXE = Path(os.environ.get("ProgramFiles") or "C:/Program Files") / "Elgato" / "StreamDeck" / "StreamDeck.exe"
SD_PLAY = "com.elgato.streamdeck.soundboard.playaudio"
SD_STOP = "com.elgato.streamdeck.soundboard.stopaudioplay"
SD_SOUNDBOARD = {"Name": "Soundboard", "UUID": "com.elgato.streamdeck.soundboard", "Version": "1.0"}
# what the sound is for -> (action, fade, fade seconds, volume or None = keep)
SD_GOALS = {
    "Reaction / spammable (every press overlaps)": ("Play / Overlap", "No Fade", 1, None),
    "Stinger / one-shot (press restarts it)": ("Play / Restart", "No Fade", 1, None),
    "Toggle clip (press again to stop, soft stop)": ("Play / Stop", "Fade Out", 1, None),
    "Background music (loops, smooth start and stop)": ("Loop / Stop", "Fade In & Out", 3, None),
    "Ambience bed (quiet loop, slow fades)": ("Loop / Stop", "Fade In & Out", 5, 35),
    "Intro / outro music (plays through, fades)": ("Play / Stop", "Fade In & Out", 2, None),
    "Voice line / announcement (clean, full volume)": ("Play / Restart", "No Fade", 1, 100),
}


def sd_connected():
    """USB instance ids of plugged-in devices (upper case), e.g. USB\\VID_0FD9&PID_0084\\A00WA4121LT9RJ."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-PnpDevice -PresentOnly).InstanceId"],
                           capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        return set(r.stdout.upper().split())
    except (OSError, subprocess.SubprocessError):
        return set()


def sd_devices(sd_dir=SD_DIR, plugged=None):
    """Stream Decks found in the user's own profiles, connected ones first:
    {label: (model, device id, cols, rows)}. Device ids look like @(1)[vendor/product/serial] (USB ids, decimal)."""
    plugged = sd_connected() if plugged is None else plugged
    found = {}
    for top in sorted((sd_dir / "ProfilesV3").glob("*.sdProfile/manifest.json")):
        try:
            prof = json.loads(top.read_text(encoding="utf-8"))
            dev = prof["Device"]
            cols = rows = 0
            # ponytail: grid = furthest key any page uses; the Columns/Rows boxes fix it when a deck is half-used
            for page in top.parent.glob("Profiles/*/manifest.json"):
                for c in json.loads(page.read_text(encoding="utf-8")).get("Controllers") or []:
                    for pos in (c.get("Actions") or {}) if c.get("Type") == "Keypad" else ():
                        x, y = map(int, pos.split(","))
                        cols, rows = max(cols, x + 1), max(rows, y + 1)
        except (OSError, ValueError, KeyError, AttributeError):
            continue
        did = dev.get("UUID", "")
        old = found.get(did)
        if cols and (not old or cols * rows > old[3] * old[4]):
            found[did] = (dev.get("Model", ""), prof.get("Name", ""), did, cols, rows)
    out = {}
    for model, pname, did, cols, rows in found.values():
        try:
            vid, pid, serial = did[did.index("[") + 1:did.rindex("]")].split("/")
            on = f"USB\\VID_{int(vid):04X}&PID_{int(pid):04X}\\{serial.upper()}" in plugged
        except ValueError:
            on = False
        out[f"{'[connected] ' if on else ''}{model} {cols}x{rows} (e.g. profile '{pname}')"] = (model, did, cols, rows)
    return dict(sorted(out.items(), key=lambda kv: not kv[0].startswith("[connected]")))


def sd_key(text, cols, rows):
    """'column,row' counted from 1 (top-left = 1,1) -> Stream Deck's 0-based (col, row); blank -> None."""
    if not str(text).strip():
        return None
    try:
        c, r = (int(v) for v in str(text).split(","))
    except ValueError:
        raise ValueError(f"Key '{text}' must be column,row like 2,1") from None
    if not (1 <= c <= cols and 1 <= r <= rows):
        raise ValueError(f"Key {text} is outside the {cols} x {rows} deck")
    return c - 1, r - 1


def sd_layout(sounds, keys, cols, rows):
    """{(col, row): (kind, title, [sounds])}. Sounds sharing a "key" ('col,row') go on that key as one action;
    keys = {'col,row': {"kind": SD_KINDS name, "title": key name}}. Sounds with no key each get the next free
    key (left to right, top to bottom) as a single sound."""
    out = {}
    for s in sounds:
        k = sd_key(s.get("key", ""), cols, rows)
        if k:
            out.setdefault(k, []).append(s)
    for pos, group in out.items():
        cfg = keys.get(f"{pos[0] + 1},{pos[1] + 1}", {})
        kind = cfg.get("kind", "Single sound")
        if kind == "Single sound" and len(group) > 1:
            raise ValueError(f"Key {pos[0] + 1},{pos[1] + 1} has {len(group)} sounds: make it a Multi or Random Action")
        out[pos] = (kind, cfg.get("title") or (group[0]["title"] if len(group) == 1 else kind), group)
    free = (p for p in ((c, r) for r in range(rows) for c in range(cols)) if p not in out)
    for s in sounds:
        if not sd_key(s.get("key", ""), cols, rows):
            p = next(free, None)
            if p is None:
                raise ValueError(f"Not enough free keys on the {cols} x {rows} deck for the unmapped sounds")
            out[p] = ("Single sound", s["title"], [s])
    return out


def sd_uid():
    import uuid
    return str(uuid.uuid4())


def sd_play(path, title="", mode=SD_MODES[0], fade=SD_FADES[0], fade_len=1, volume=100, output="", rid=None):
    """A Play Audio action. rid = bundled-audio id (export files only; installed profiles play from path)."""
    return {"ActionID": sd_uid(), "LinkedTitle": True, "Name": "Play Audio", "Plugin": dict(SD_SOUNDBOARD),
            "Resources": {"file": rid} if rid else None,
            "Settings": {"actionType": SD_MODES.index(mode), "fadeLen": int(fade_len), "fadeType": SD_FADES.index(fade),
                         "outputType": sd_out(output), "path": str(path), "volume": int(volume)},
            "State": 0, "States": [{"Title": title}], "UUID": SD_PLAY}


def sd_renew(action):
    """Give an action (and everything nested in it) fresh ActionIDs, so a pasted copy is its own key."""
    if isinstance(action, dict):
        if "ActionID" in action:
            action["ActionID"] = sd_uid()
        for v in action.values():
            sd_renew(v)
    elif isinstance(action, list):
        for v in action:
            sd_renew(v)
    return action


def sd_wrap(kind, title, plays):
    """A Multi Action / Random Action key holding the given actions."""
    # ponytail: Random Action assumed to nest like Multi Action (no Random key in any local profile to copy)
    return {"ActionID": sd_uid(), "Actions": [{"Actions": plays}], "LinkedTitle": True, "Name": kind,
            "Plugin": {"Name": "Multi Action", "UUID": "com.elgato.streamdeck.multiactions", "Version": "1.0"},
            "Resources": None, "Settings": {}, "State": 0, "States": [{"Title": title}], "UUID": SD_KINDS[kind]}


def sd_profile_files(name, device, sounds, keys):
    """({archive path: json}, {audio path: resource id}) for a one-page profile, in Stream Deck's export layout."""
    model, dev_id, cols, rows = device
    new = sd_uid
    page, home, prof, res = new(), new(), new(), {}

    def play(s):
        path = str(Path(s["path"]).resolve())
        return sd_play(path, s["title"], s["mode"], s["fade"], s["fade_len"], s["volume"], s.get("output"),
                       res.setdefault(path, new()))

    actions = {}
    for (c, r), (kind, title, group) in sd_layout(sounds, keys, cols, rows).items():
        if SD_KINDS[kind]:
            act = sd_wrap(kind, title, [play(s) for s in group])
        else:
            act = play(group[0])
            act["States"] = [{"Title": title}]
        actions[f"{c},{r}"] = act
    base = f"Profiles/{prof.upper()}.sdProfile"
    files = {
        "package.json": {"AppVersion": "7.3.0", "DeviceModel": model, "DeviceSettings": None, "FormatVersion": 1,
                         "OSType": "Windows", "OSVersion": "10.0", "RequiredPlugins": [
                             "com.elgato.streamdeck.soundboard", "com.elgato.streamdeck.multiactions"]},
        f"{base}/manifest.json": {"Device": {"Model": model, "UUID": dev_id}, "Name": name, "Version": "3.0",
                                  "Pages": {"Current": page, "Default": home, "Pages": [page]}},
        f"{base}/Profiles/{page.upper()}/manifest.json": {"Controllers": [{"Actions": actions, "Type": "Keypad"}],
                                                          "Icon": "", "Name": name},
        f"{base}/Profiles/{home.upper()}/manifest.json": {"Controllers": [{"Actions": {}, "Type": "Keypad"}],
                                                          "Icon": "", "Name": ""},
        "Resources/manifest.json": {"resources": {rid: {"file": f"{rid}/{Path(p).name}"} for p, rid in res.items()}},
    }
    return files, res


def sd_profile(dst, name, device, sounds, keys):
    """Write a .streamDeckProfile (the Stream Deck app's own export format, audio files bundled inside).
    sounds: dicts with path, title, key, mode (SD_MODES), fade (SD_FADES), fade_len (s), volume (0-100), output."""
    import zipfile
    files, res = sd_profile_files(name, device, sounds, keys)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, data in files.items():
            z.writestr(arc, json.dumps(data, indent=1))
        for p, rid in res.items():
            z.write(p, f"Resources/{rid}/{Path(p).name}")
    return Path(dst)


# --- editing the profiles already installed in the local Stream Deck app ---
def sd_profiles(sd_dir=SD_DIR):
    """[(profile folder, its manifest)] for every installed profile."""
    out = []
    for top in sorted((sd_dir / "ProfilesV3").glob("*.sdProfile/manifest.json")):
        try:
            out.append((top.parent, json.loads(top.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            pass
    return out


def sd_pages(folder, manifest):
    """[(label, page manifest file)]: the profile's pages in Stream Deck's order ("Page 1"...), then the pages
    behind folder keys ("Folder: <key name>"), which live beside them but aren't in the page list."""
    pages = {p.parent.name.lower(): p for p in (folder / "Profiles").glob("*/manifest.json")}
    listed = [i.lower() for i in (manifest.get("Pages") or {}).get("Pages") or [] if i.lower() in pages]
    names = {}
    for p in pages.values():  # folder keys point at their page through Settings.ProfileUUID
        try:
            for c in json.loads(p.read_text(encoding="utf-8")).get("Controllers") or []:
                for a in (c.get("Actions") or {}).values():
                    pid = str((a.get("Settings") or {}).get("ProfileUUID", "")).lower()
                    if a.get("UUID") == "com.elgato.streamdeck.profile.openchild" and pid in pages:
                        names[pid] = sd_title(a).replace("\n", " ") or pid[:8]
        except (OSError, ValueError, AttributeError):
            pass
    return ([(f"Page {n}", pages[i]) for n, i in enumerate(listed, 1)]
            + sorted((f"Folder: {nm}", pages[i]) for i, nm in names.items() if i not in listed))


def sd_keypad(page):
    """The page's {"col,row": action} key map (0-based, Stream Deck's own), created if missing."""
    ctrls = page.setdefault("Controllers", [])
    kp = next((c for c in ctrls if c.get("Type") == "Keypad"), None)
    if kp is None:
        kp = {"Type": "Keypad"}
        ctrls.append(kp)
    if not kp.get("Actions"):
        kp["Actions"] = {}
    return kp["Actions"]


def sd_sounds(action):
    """Every Play Audio action on a key, also inside Multi / Random / Key Logic / stacks."""
    if not isinstance(action, dict):
        return []
    if action.get("UUID") == SD_PLAY:
        return [action]
    return [s for a in action.get("Actions") or [] for s in sd_sounds(a)]


def sd_kind(action):
    """Short label for a key: Sound / Multi x3 / Random x5 / Stop / the action's own name."""
    n = len(sd_sounds(action))
    u = action.get("UUID", "")
    if u == SD_PLAY:
        return "Sound"
    if u == SD_STOP:
        return "Stop audio"
    for kind, uid in SD_KINDS.items():
        if uid and u == uid:
            return f"{kind.split()[0]} x{n}"
    return action.get("Name") or u.rsplit(".", 1)[-1]


def sd_title(action):
    st = action.get("States") or [{}]
    return st[min(int(action.get("State") or 0), len(st) - 1)].get("Title") or ""


def sd_missing(action):
    return [s for s in sd_sounds(action) if not Path(s.get("Settings", {}).get("path", "")).is_file()]


def sd_set_sound(sounds, mode=None, fade=None, fade_len=None, volume=None, step=None, output=None):
    """Change Play Audio settings; None = leave as is. step = add to the current volume (-100..100)."""
    for s in sounds:
        st = s.setdefault("Settings", {})
        if mode:
            st["actionType"] = SD_MODES.index(mode)
        if fade:
            st["fadeType"] = SD_FADES.index(fade)
        if fade_len:
            st["fadeLen"] = int(fade_len)
        if volume is not None:
            st["volume"] = int(volume)
        if step:
            st["volume"] = max(0, min(100, int(st.get("volume", 100)) + int(step)))
        if output is not None:
            st["outputType"] = sd_out(output)


def sd_match_loudness(sounds, level_db):
    """Even out loudness: louder files get turned down so every sound plays as loud as the quietest one does now.
    level_db: {path: loudest channel RMS in dB}; sounds without a level are left alone."""
    import math
    # ponytail: treats Stream Deck's volume as a linear gain; good enough to even a soundboard out by ear
    now = {id(s): level_db[s["Settings"]["path"]] + 20 * math.log10(max(int(s["Settings"].get("volume", 100)), 1) / 100)
           for s in sounds if s.get("Settings", {}).get("path") in level_db}
    if not now:
        return 0
    target = min(now.values())
    for s in sounds:
        if id(s) in now:
            s["Settings"]["volume"] = max(1, min(100, round(100 * 10 ** ((target - level_db[s["Settings"]["path"]]) / 20))))
    return len(now)


def sd_label(action, source="Keep", prefix="", suffix="", find="", repl="", style=None, number=0):
    """Rename a key. source: Keep / File name / Folder name / Number / Clear; style: Stream Deck title fields
    (ShowTitle, FontSize, TitleAlignment, TitleColor)."""
    snds = sd_sounds(action)
    path = Path(snds[0]["Settings"].get("path", "")) if snds else None
    for st in action.setdefault("States", [{}]) or [{}]:
        t = st.get("Title") or ""
        if source == "File name" and path:
            t = path.stem if len(snds) == 1 else path.parent.name
        elif source == "Folder name" and path:
            t = path.parent.name
        elif source == "Number":
            t = str(number)
        elif source == "Clear":
            t = ""
        if find:
            t = t.replace(find, repl)
        st["Title"] = prefix + t + suffix
        st.update(style or {})


def sd_free(kp, cols, rows):
    return [f"{c},{r}" for r in range(rows) for c in range(cols) if f"{c},{r}" not in kp]


def sd_move(kp, src, dst):
    """Move a key; whatever was on dst swaps to src."""
    a, b = kp.pop(src, None), kp.pop(dst, None)
    if a:
        kp[dst] = a
    if b:
        kp[src] = b


def sd_combine(kp, keys, kind, title):
    """All sounds on the given keys become one Multi / Random Action on the first key; the other keys are emptied."""
    plays = [s for k in keys for s in sd_sounds(kp.get(k))]
    other = [k for k in keys if kp.get(k) and not sd_sounds(kp[k])]
    if other or not plays:
        raise ValueError("Only keys with sounds can be combined" + (f" ({', '.join(other)} has none)" if other else ""))
    for k in keys:
        kp.pop(k, None)
    kp[keys[0]] = sd_wrap(kind, title or kind, plays)


def sd_split(kp, key, cols, rows):
    """A Multi / Random / Key Logic key's sounds become single keys: the first stays, the rest take free keys."""
    plays = sd_sounds(kp.get(key))
    free = sd_free(kp, cols, rows)
    if len(plays) - 1 > len(free):
        raise ValueError(f"Key needs {len(plays) - 1} free keys, the page has {len(free)}")
    for k, s in zip([key] + free, plays):
        s.setdefault("States", [{}])
        if not sd_title(s):
            s["States"][0]["Title"] = Path(s.get("Settings", {}).get("path", "")).stem[:20]
        kp[k] = s
    return len(plays)


def sd_stop_key():
    return {"ActionID": sd_uid(), "LinkedTitle": True, "Name": "Stop Audio", "Plugin": dict(SD_SOUNDBOARD),
            "Resources": None, "Settings": {}, "State": 0, "States": [{"Title": "STOP"}], "UUID": SD_STOP}


def sd_relink(sounds, folder):
    """Point sounds whose file is gone at a file with the same name anywhere under folder. -> (fixed, still missing)."""
    found = {}
    for f in Path(folder).rglob("*"):
        found.setdefault(f.name.lower(), f)
    fixed = []
    for s in sounds:
        st = s.setdefault("Settings", {})
        p = st.get("path", "")
        hit = found.get(p.replace("\\", "/").rsplit("/", 1)[-1].lower()) if p and not Path(p).is_file() else None
        if hit:
            st["path"] = str(hit)
            fixed.append(s)
    return len(fixed), sum(not Path(s.get("Settings", {}).get("path", "")).is_file() for s in sounds)


SD_DEFAULT_OUT = "(Stream Deck default output)"


def sd_out(value):
    """Dropdown text -> the outputType Stream Deck stores ("" = its default device)."""
    value = (value or "").strip()
    return "" if value == SD_DEFAULT_OUT else value


def sd_outputs(sd_dir=SD_DIR):
    """Output device values Stream Deck itself has saved on any sound key (its exact format), most used first."""
    import collections
    import re
    seen = collections.Counter()
    for f in (sd_dir / "ProfilesV3").glob("*.sdProfile/Profiles/*/manifest.json"):
        try:
            for m in re.findall(r'"outputType":\s*("(?:[^"\\]|\\.)+")', f.read_text(encoding="utf-8")):
                seen[json.loads(m)] += 1
        except (OSError, ValueError):
            pass
    return [v for v, _ in seen.most_common()]


_win_outputs = []


def sd_output_choices():
    """Dropdown list: default, then values Stream Deck saved itself, then this PC's playback devices."""
    if not _win_outputs:  # ponytail: asked once per run; restart the app after plugging in new speakers
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Get-PnpDevice -Class AudioEndpoint -PresentOnly | Where-Object InstanceId -like "
                                "'SWD\\MMDEVAPI\\{0.0.0.*' | ForEach-Object FriendlyName"],  # {0.0.0 = playback
                               capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
            _win_outputs.extend(sorted({ln.strip() for ln in r.stdout.splitlines() if ln.strip()}))
        except (OSError, subprocess.SubprocessError):
            pass
    known = sd_outputs()
    return [SD_DEFAULT_OUT] + known + [w for w in _win_outputs if w not in known]


def sd_multis(pages):
    """Every Multi / Random Action key: [(page label, key, action)] from [(page label, page json)]."""
    kinds = {u for u in SD_KINDS.values() if u}
    out = []
    for label, pg in pages:
        for c in (pg or {}).get("Controllers") or []:
            if c.get("Type") == "Keypad":
                for k, a in sorted((c.get("Actions") or {}).items(), key=lambda kv: kv[0][::-1]):
                    if a and a.get("UUID") in kinds:
                        out.append((label, k, a))
    return out


def sd_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq StreamDeck.exe", "/NH"], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    return "streamdeck.exe" in r.stdout.lower()


def sd_stop():
    """Close Stream Deck (it rewrites profiles on exit, which would undo our edits)."""
    import time
    for force in ([], ["/F"]):
        subprocess.run(["taskkill", "/IM", "StreamDeck.exe", *force], capture_output=True, creationflags=NO_WINDOW)
        for _ in range(20):
            if not sd_running():
                return True
            time.sleep(0.5)
    return False


def sd_start():
    if SD_EXE.exists():
        subprocess.Popen([str(SD_EXE)], creationflags=NO_WINDOW)


def sd_save(writes, folders, sd_dir=SD_DIR, backups=SD_BACKUPS):
    """Zip each touched profile folder into backups (restore = unzip into ProfilesV3), then write the json files.
    Call while Stream Deck is closed. Returns the backup zip."""
    import time
    import zipfile
    backups.mkdir(parents=True, exist_ok=True)
    zpath = None
    if folders:  # a brand-new profile has nothing to back up
        zpath = backups / f"profiles-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for folder in folders:
                for f in Path(folder).rglob("*"):
                    if f.is_file():
                        z.write(f, f.relative_to(sd_dir / "ProfilesV3"))
    for path, data in writes.items():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")
    return zpath


def sd_install(name, device, sounds, keys, sd_dir=SD_DIR):
    """{file: json} that puts a new soundboard profile straight into Stream Deck's profile folder (no import prompt).
    Installed profiles play from each sound's own path, so no audio is copied."""
    files, _ = sd_profile_files(name, device, sounds, keys)
    root = sd_dir / "ProfilesV3"
    return {root / arc.split("/", 1)[1]: data for arc, data in files.items() if arc.startswith("Profiles/")}


def sd_editor_tab(page):
    """Edit the buttons of profiles already in the local Stream Deck app: select keys, pick a goal, apply, save."""
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk

    pad = {"padx": 10, "pady": 4}
    if not (SD_DIR / "ProfilesV3").is_dir():
        tk.Label(page, text="No local Stream Deck install found (looked in %APPDATA%\\Elgato\\StreamDeck).\n"
                            "Install the Stream Deck app, then reopen Channel Mirror.", justify="left").pack(**pad)
        return
    plugged = sd_connected()
    kinds = {u for u in SD_KINDS.values() if u}  # Multi Action / Random Action ids
    grids = {v[1]: v[2:] for v in sd_devices(plugged=plugged).values()}  # device id -> (cols, rows)
    profs, labels_ = {}, []
    for folder, m in sd_profiles():
        did = m.get("Device", {}).get("UUID", "")
        try:
            vid, pid, serial = did[did.index("[") + 1:did.rindex("]")].split("/")
            on = f"USB\\VID_{int(vid):04X}&PID_{int(pid):04X}\\{serial.upper()}" in plugged
        except ValueError:
            on = False
        lbl = f"{'[connected] ' if on else ''}{m.get('Name') or folder.stem}  ({m.get('Device', {}).get('Model', '?')})"
        n = 2
        while lbl in profs:  # profiles can share a name
            lbl, n = f"{lbl.rsplit(' #', 1)[0]} #{n}", n + 1
        profs[lbl] = (folder, m)
    labels_ = sorted(profs, key=lambda s: (not s.startswith("[connected]"), s.lower()))
    edits = {}  # page manifest path -> edited json (unsaved)
    st = {"pages": [], "page": None, "sel": []}

    left = tk.LabelFrame(page, text=" 1. Pick a profile and page, then click keys to select them ")
    left.pack(side="left", fill="both", **pad)
    right = tk.Frame(page)
    right.pack(side="left", fill="both", expand=True, **pad)
    prof_v, page_v = tk.StringVar(value=labels_[0] if labels_ else ""), tk.StringVar()
    r = tk.Frame(left)
    r.pack(fill="x", padx=6, pady=3)
    tk.Label(r, text="Profile:").pack(side="left")
    ttk.Combobox(r, textvariable=prof_v, values=labels_, state="readonly", width=46).pack(side="left", padx=4)
    r = tk.Frame(left)
    r.pack(fill="x", padx=6, pady=3)
    tk.Label(r, text="Page:").pack(side="left")
    page_cb = ttk.Combobox(r, textvariable=page_v, state="readonly", width=12)
    page_cb.pack(side="left", padx=4)
    for text, cmd in (("Select sound keys", lambda: select(lambda a: bool(sd_sounds(a)))),
                      ("Select missing", lambda: select(lambda a: bool(sd_missing(a)))),
                      ("Select Multi/Random", lambda: select(lambda a: bool(a) and a.get("UUID") in kinds)),
                      ("Select all", lambda: select(bool)),
                      ("Select none", lambda: select(lambda a: False))):
        tk.Button(r, text=text, command=cmd).pack(side="left", padx=2)
    r = tk.Frame(left)
    r.pack(fill="x", padx=6, pady=3)
    tk.Label(r, text="Multi / Random:").pack(side="left")
    multi_v, multi_map = tk.StringVar(), {}
    multi_cb = ttk.Combobox(r, textvariable=multi_v, state="readonly", width=60)
    multi_cb.pack(side="left", padx=4)
    grid = tk.Frame(left)
    grid.pack(padx=6, pady=6)
    tk.Label(left, text="green = sound key, red = sound file missing, grey = other action, blue = selected",
             fg="gray").pack(anchor="w", padx=6)
    info = tk.Listbox(left, height=8, font=("Consolas", 9))
    info.pack(fill="both", expand=True, padx=6, pady=(2, 6))

    # 2. Goal-driven adjustments
    adj = tk.LabelFrame(right, text=" 2. What do you want to do with the selected keys? ")
    adj.pack(fill="both", expand=True)
    goal_v = tk.StringVar(value="Set them up for a purpose")
    goals = ("Set them up for a purpose", "Playback and fade", "Volume", "Output device", "Key names and look",
             "Arrange keys", "Fix missing sound files")
    ttk.Combobox(adj, textvariable=goal_v, values=goals, state="readonly", width=34).pack(anchor="w", padx=6, pady=6)
    frames = {g: tk.Frame(adj) for g in goals}
    o = {}  # option variables

    def row(g, label, widget_fn):
        fr = tk.Frame(frames[g])
        fr.pack(fill="x", padx=6, pady=3)
        tk.Label(fr, text=label, width=18, anchor="w").pack(side="left")
        widget_fn(fr)
        return fr

    def combo(g, key, label, values, first=None):
        o[key] = tk.StringVar(value=first or values[0])
        row(g, label, lambda fr: ttk.Combobox(fr, textvariable=o[key], values=values, state="readonly",
                                               width=40).pack(side="left"))

    def entry(g, key, label, value="", width=24):
        o[key] = tk.StringVar(value=value)
        row(g, label, lambda fr: tk.Entry(fr, textvariable=o[key], width=width).pack(side="left"))

    g = goals[0]
    combo(g, "goal", "Purpose:", tuple(SD_GOALS))
    goal_desc = tk.Label(frames[g], anchor="w", justify="left", fg="gray")
    goal_desc.pack(fill="x", padx=6)
    o["goal"].trace_add("write", lambda *_: goal_desc.config(text="Sets: {} / {} {}s{}".format(
        *SD_GOALS[o["goal"].get()][:3],
        f" / volume {SD_GOALS[o['goal'].get()][3]}" if SD_GOALS[o["goal"].get()][3] is not None else "")))
    o["goal"].set(o["goal"].get())
    g = goals[1]
    combo(g, "mode", "Action:", ("Keep",) + SD_MODES)
    combo(g, "fade", "Fade:", ("Keep",) + SD_FADES)
    combo(g, "fade_len", "Fade length (s):", ("Keep", "1", "2", "3", "4", "5"))
    g = goals[2]
    o["vol_how"] = tk.StringVar(value="set")
    o["vol"], o["step"] = tk.IntVar(value=80), tk.IntVar(value=-10)
    for how, text, w in (("set", "Set to", lambda fr: tk.Scale(fr, variable=o["vol"], from_=0, to=100,
                                                                orient="horizontal", length=160).pack(side="left")),
                         ("step", "Change by (+/-)", lambda fr: tk.Spinbox(fr, textvariable=o["step"], from_=-100,
                                                                           to=100, width=5).pack(side="left")),
                         ("match", "Match loudness", lambda fr: tk.Label(
                             fr, text="measures each file, turns the louder ones down to the quietest", fg="gray"
                         ).pack(side="left"))):
        fr = tk.Frame(frames[g])
        fr.pack(fill="x", padx=6, pady=3)
        tk.Radiobutton(fr, text=text, variable=o["vol_how"], value=how, width=16, anchor="w").pack(side="left")
        w(fr)
    g = goals[3]
    o["output"] = tk.StringVar(value=SD_DEFAULT_OUT)
    ocb = []
    row(g, "Output device:", lambda fr: ocb.append(ttk.Combobox(fr, textvariable=o["output"], width=52)))
    ocb[0].config(postcommand=lambda: ocb[0].config(values=sd_output_choices()))
    ocb[0].pack(side="left")
    tk.Label(frames[g], fg="gray", justify="left", anchor="w", wraplength=540, text=(
        "Every sound on the selected keys is set, including all sounds inside a Multi or Random Action "
        "(use 'Multi / Random' on the left to pick one). Devices Stream Deck has saved itself are listed first "
        "and are exact. Windows device names come after; if a key still plays on the default output with one, "
        "set that key's output once inside Stream Deck, then pick the value that appears at the top here."
    )).pack(fill="x", padx=6)
    g = goals[4]
    combo(g, "source", "Name from:", ("Keep", "File name", "Folder name", "Number", "Clear"))
    entry(g, "prefix", "Add before:")
    entry(g, "suffix", "Add after:")
    entry(g, "find", "Replace text:")
    entry(g, "repl", "  with:")
    combo(g, "show", "Show name:", ("Keep", "Show", "Hide"))
    combo(g, "size", "Font size:", ("Keep", "7", "8", "9", "10", "12", "14", "16", "18"))
    combo(g, "align", "Name position:", ("Keep", "top", "middle", "bottom"))
    o["color"] = tk.StringVar(value="")
    row(g, "Name colour:", lambda fr: (
        tk.Button(fr, text="Pick...", command=lambda: o["color"].set(
            colorchooser.askcolor(title="Key name colour")[1] or o["color"].get())).pack(side="left"),
        tk.Label(fr, textvariable=o["color"]).pack(side="left", padx=4),
        tk.Button(fr, text="Keep", command=lambda: o["color"].set("")).pack(side="left")))
    g = goals[5]
    o["arr"] = tk.StringVar(value="move")
    o["slot"], o["ctitle"] = tk.StringVar(value="1,1"), tk.StringVar()
    o["ckind"] = tk.StringVar(value="Random Action")
    for how, text, extra in (
            ("move", "Move first selected key to (col,row)",
             lambda fr: tk.Entry(fr, textvariable=o["slot"], width=6).pack(side="left")),
            ("combine", "Combine selected into one",
             lambda fr: (ttk.Combobox(fr, textvariable=o["ckind"], values=("Random Action", "Multi Action"),
                                      state="readonly", width=14).pack(side="left"),
                         tk.Label(fr, text=" named ").pack(side="left"),
                         tk.Entry(fr, textvariable=o["ctitle"], width=14).pack(side="left"))),
            ("split", "Split Multi/Random keys into single keys", lambda fr: None),
            ("stop", "Add a 'Stop all audio' key at (col,row)",
             lambda fr: tk.Entry(fr, textvariable=o["slot"], width=6).pack(side="left")),
            ("delete", "Delete selected keys", lambda fr: None)):
        fr = tk.Frame(frames[g])
        fr.pack(fill="x", padx=6, pady=3)
        tk.Radiobutton(fr, text=text, variable=o["arr"], value=how, anchor="w").pack(side="left")
        extra(fr)
    g = goals[6]
    entry(g, "folder", "Search folder:", str(Path.home() / "Music"), 40)
    row(g, "", lambda fr: tk.Button(fr, text="Browse...", command=lambda: o["folder"].set(
        filedialog.askdirectory(title="Folder that holds the sounds") or o["folder"].get())).pack(side="left"))
    tk.Label(frames[g], text="Finds a file with the same name anywhere under the folder and points the key at it.",
             fg="gray").pack(anchor="w", padx=6)

    def on_goal(*_):
        for f in frames.values():
            f.pack_forget()
        frames[goal_v.get()].pack(fill="x", pady=4)
    goal_v.trace_add("write", on_goal)
    on_goal()

    bar = tk.Frame(right)
    bar.pack(fill="x", pady=(6, 0))
    status = tk.Label(right, anchor="w", justify="left", wraplength=560)

    def cur_page():
        p = st["page"]
        if p and p not in edits:
            edits[p] = json.loads(p.read_text(encoding="utf-8"))
        return edits.get(p)

    def keys_now():  # read-only view; sd_keypad() would normalise the json and make the page look edited
        ctrl = next((c for c in (cur_page() or {}).get("Controllers") or [] if c.get("Type") == "Keypad"), {})
        return ctrl.get("Actions") or {}

    def size():
        folder, m = profs[prof_v.get()]
        kp = keys_now()
        cols, rows = grids.get(m.get("Device", {}).get("UUID", ""), (5, 3))
        for k in kp:
            c, r_ = map(int, k.split(","))
            cols, rows = max(cols, c + 1), max(rows, r_ + 1)
        return cols, rows

    def draw():
        for w in grid.winfo_children():
            w.destroy()
        info.delete(0, "end")
        if not st["page"]:
            return
        kp = keys_now()
        cols, rows = size()
        for r_ in range(rows):
            for c in range(cols):
                k = f"{c},{r_}"
                a = kp.get(k)
                on = k in st["sel"]
                bg = ("#2b6cb0" if on else "#fed7d7" if a and sd_missing(a) else "#c6f6d5" if a and sd_sounds(a)
                      else "#e2e8f0" if a else "#ffffff")
                text = f"{sd_title(a)[:10] or '-'}\n{sd_kind(a)[:11]}" if a else f"{c + 1},{r_ + 1}"
                tk.Button(grid, text=text, width=10, height=3, font=("Segoe UI", 8), bg=bg,
                          fg="white" if on else "black", relief="sunken" if on else "raised",
                          command=lambda k=k: toggle(k)).grid(row=r_, column=c, padx=2, pady=2)
        for k in st["sel"]:
            a = kp.get(k)
            c, r_ = map(int, k.split(","))
            info.insert("end", f"{c + 1},{r_ + 1}  {sd_title(a) if a else '(empty)'} - {sd_kind(a) if a else ''}")
            for s in sd_sounds(a):
                se = s.get("Settings", {})
                miss = "" if Path(se.get("path", "")).is_file() else "  MISSING"
                info.insert("end", f"      {SD_MODES[se.get('actionType', 0)] if se.get('actionType', 0) < 4 else '?'}"
                                   f" | {SD_FADES[se.get('fadeType', 0)] if se.get('fadeType', 0) < 4 else '?'}"
                                   f" | vol {se.get('volume', '?')} | out {se.get('outputType') or 'default'}"
                                   f" | {Path(se.get('path', '')).name}{miss}")
        dirty = sum(1 for p in edits if edits[p] != json.loads(p.read_text(encoding="utf-8")))
        save_btn.config(text=f"Save to Stream Deck ({dirty} page(s) changed)" if dirty else "Save to Stream Deck")

    def toggle(k):
        st["sel"].remove(k) if k in st["sel"] else st["sel"].append(k)
        draw()

    def select(test):
        kp = keys_now()
        cols, rows = size()
        st["sel"] = [k for k in (f"{c},{r_}" for r_ in range(rows) for c in range(cols)) if test(kp.get(k))]
        draw()

    def on_prof(*_):
        if prof_v.get() not in profs:
            return
        folder, m = profs[prof_v.get()]
        named = sd_pages(folder, m)
        st["pages"], names = [p for _, p in named], [n for n, _ in named]
        page_cb.config(values=names)
        page_v.set(names[0] if names else "")
        list_multis()

    def list_multis():
        """Fill the Multi / Random picker from every page of the profile (unsaved edits included)."""
        names = list(page_cb.cget("values"))
        pages = [(n, edits.get(p) or json.loads(p.read_text(encoding="utf-8"))) for n, p in zip(names, st["pages"])]
        multi_map.clear()
        for label, k, a in sorted(sd_multis(pages), key=lambda x: not sd_sounds(x[2])):  # sound keys first
            c, r_ = map(int, k.split(","))
            multi_map[f"{label} - key {c + 1},{r_ + 1} - {sd_title(a).replace(chr(10), ' ') or '(no name)'}"
                      f" [{sd_kind(a)}]"] = (label, k)
        multi_cb.config(values=list(multi_map) or ["(no Multi or Random Actions in this profile)"])
        multi_v.set("")

    def on_multi(*_):
        if multi_v.get() in multi_map:
            label, k = multi_map[multi_v.get()]
            if page_v.get() != label:
                page_v.set(label)  # clears the selection
            st["sel"] = [k]
            draw()
            status.config(text=f"Selected {multi_v.get()}. Pick 'Output device' (or any goal) on the right and Apply.")

    def on_page(*_):
        names = list(page_cb.cget("values"))
        st["page"] = st["pages"][names.index(page_v.get())] if page_v.get() in names else None
        st["sel"] = []
        draw()

    def slot(text):
        cols, rows = size()
        c, r_ = sd_key(text, cols, rows)
        return f"{c},{r_}"

    def apply():
        if not st["page"]:
            return
        kp = sd_keypad(cur_page())
        sel = [k for k in st["sel"] if kp.get(k)]
        g = goal_v.get()
        if not sel and not (g == "Arrange keys" and o["arr"].get() == "stop"):
            return messagebox.showinfo("Select keys", "Click keys on the grid (or use the Select buttons) first.")
        sounds = [s for k in sel for s in sd_sounds(kp[k])]
        keep = lambda x: None if x == "Keep" else x
        if not sounds and g in goals[:4]:  # purpose / playback / volume / output only touch Play Audio actions
            return messagebox.showinfo("No sounds", "The selected key(s) hold no Play Audio actions "
                                       "(e.g. a hotkey macro), so there's nothing to change.")
        try:
            if g == "Set them up for a purpose":
                mode, fade, secs, vol = SD_GOALS[o["goal"].get()]
                sd_set_sound(sounds, mode, fade, secs, vol)
                msg = f"{len(sounds)} sound(s) set up for: {o['goal'].get()}"
            elif g == "Playback and fade":
                sd_set_sound(sounds, keep(o["mode"].get()), keep(o["fade"].get()), keep(o["fade_len"].get()))
                msg = f"Playback changed on {len(sounds)} sound(s)"
            elif g == "Volume":
                how = o["vol_how"].get()
                if how == "match":
                    levels = {}
                    for s in sounds:
                        p = s.get("Settings", {}).get("path", "")
                        if p not in levels and Path(p).is_file():
                            status.config(text=f"Measuring {Path(p).name}...")
                            page.update()
                            try:
                                levels[p] = float(np.max(db(analyze(Path(p))[1])))
                            except Exception:
                                pass
                    msg = f"Loudness matched on {sd_match_loudness(sounds, levels)} sound(s)"
                else:
                    sd_set_sound(sounds, volume=o["vol"].get() if how == "set" else None,
                                 step=int(o["step"].get()) if how == "step" else None)
                    msg = f"Volume changed on {len(sounds)} sound(s)"
            elif g == "Output device":
                sd_set_sound(sounds, output=o["output"].get())
                msg = (f"Output set to {sd_out(o['output'].get()) or 'the default device'} on {len(sounds)} "
                       f"sound(s) in {len(sel)} key(s)")
            elif g == "Key names and look":
                style = {}
                if o["show"].get() != "Keep":
                    style["ShowTitle"] = o["show"].get() == "Show"
                if o["size"].get() != "Keep":
                    style["FontSize"] = int(o["size"].get())
                if o["align"].get() != "Keep":
                    style["TitleAlignment"] = o["align"].get()
                if o["color"].get():
                    style["TitleColor"] = o["color"].get()
                for n, k in enumerate(sel, 1):
                    sd_label(kp[k], o["source"].get(), o["prefix"].get(), o["suffix"].get(), o["find"].get(),
                             o["repl"].get(), style, n)
                msg = f"Renamed / restyled {len(sel)} key(s)"
            elif g == "Arrange keys":
                how, cols_rows = o["arr"].get(), size()
                if how == "move":
                    dst = slot(o["slot"].get())
                    sd_move(kp, sel[0], dst)
                    st["sel"] = [dst]
                    msg = "Key moved (anything already there swapped places)"
                elif how == "combine":
                    sd_combine(kp, sel, o["ckind"].get(), o["ctitle"].get().strip())
                    st["sel"] = [sel[0]]
                    msg = f"{len(sounds)} sound(s) combined into a {o['ckind'].get()}"
                elif how == "split":
                    n = sum(sd_split(kp, k, *cols_rows) for k in sel if len(sd_sounds(kp.get(k))) > 1)
                    msg = f"Split into {n} single sound keys"
                elif how == "stop":
                    k = slot(o["slot"].get())
                    if kp.get(k) and not messagebox.askyesno("Replace key", "That key is in use. Replace it?"):
                        return
                    kp[k] = sd_stop_key()
                    msg = "Added a Stop Audio key"
                else:
                    if not messagebox.askyesno("Delete keys", f"Delete {len(sel)} key(s) from this page?"):
                        return
                    for k in sel:
                        kp.pop(k, None)
                    st["sel"] = []
                    msg = f"Deleted {len(sel)} key(s)"
            else:
                if not Path(o["folder"].get()).is_dir():
                    return messagebox.showerror("Folder", "Pick the folder that holds your sounds.")
                status.config(text="Searching...")
                page.update()
                fixed, still = sd_relink(sounds, o["folder"].get())
                msg = f"Fixed {fixed} missing sound(s); {still} still missing"
        except ValueError as e:
            return messagebox.showerror("Can't do that", str(e))
        status.config(text=msg + ". Not saved yet - press Save to Stream Deck.")
        if g == "Arrange keys" or g == "Key names and look":
            list_multis()
        draw()

    def revert():
        edits.clear()
        st["sel"] = []
        status.config(text="All unsaved changes thrown away.")
        list_multis()
        draw()

    def save():
        changed = {p: d for p, d in edits.items() if d != json.loads(p.read_text(encoding="utf-8"))}
        if not changed:
            return status.config(text="Nothing to save.")
        if sd_running():
            if not messagebox.askyesno("Close Stream Deck", "Stream Deck must close while the changes are written "
                                       "(it rewrites its profiles when it exits).\nClose it now and reopen it after?"):
                return
            if not sd_stop():
                return messagebox.showerror("Stream Deck", "Couldn't close Stream Deck. Close it and press Save again.")
        folders = {p.parents[2] for p in changed}
        try:
            backup = sd_save(changed, folders)
        except OSError as e:
            return messagebox.showerror("Save", f"Couldn't write the profile:\n{e}")
        sd_start()
        edits.clear()
        status.config(text=f"Saved {len(changed)} page(s); Stream Deck reopened. Backup: {backup}")
        draw()

    tk.Button(bar, text="Apply", command=apply, width=12, font=("Segoe UI", 10, "bold")).pack(side="left")
    tk.Button(bar, text="Revert unsaved", command=revert, width=14).pack(side="left", padx=6)
    save_btn = tk.Button(bar, text="Save to Stream Deck", command=save, width=34, font=("Segoe UI", 10, "bold"))
    save_btn.pack(side="right")
    status.pack(fill="x", pady=6)
    prof_v.trace_add("write", on_prof)
    multi_v.trace_add("write", on_multi)
    page_v.trace_add("write", on_page)
    on_prof()


def streamdeck_tab(page, cfg, made):
    """The Stream Deck sub-app. made = files the Channel Mirror tab wrote this session. Returns a save() for cfg."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    sc = cfg.setdefault("streamdeck", {})
    sounds, keys = [], {}  # keys: 'col,row' -> {"kind", "title"}
    cur = tk.StringVar(value="1,1")  # the deck key being edited
    pad = {"padx": 10, "pady": 4}
    audio_pat = " ".join(f"*{e}" for e in AUDIO_EXT)
    top = tk.Frame(page)
    top.pack(fill="both", expand=True)

    # 1. Sounds
    box = tk.LabelFrame(top, text=" 1. Sounds (each becomes a Play Audio action) ")
    box.pack(side="left", fill="both", expand=True, **pad)
    side = tk.Frame(box)
    side.pack(side="right", fill="y", padx=6, pady=4)
    cols = ("title", "key", "mode", "fade", "volume", "output", "file")
    heads = ("Name", "Key", "Action", "Fade", "Volume", "Output", "File")
    tree = ttk.Treeview(box, columns=cols, show="headings", height=12)
    for c, h, w in zip(cols, heads, (130, 45, 100, 115, 55, 70, 260)):
        tree.heading(c, text=h)
        tree.column(c, width=w, stretch=c == "file")
    ys = ttk.Scrollbar(box, command=tree.yview)
    tree.config(yscrollcommand=ys.set)
    ys.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)

    # 2. Deck: device, grid of keys, the selected key's action
    deck = tk.LabelFrame(top, text=" 2. Stream Deck keys (click a key) ")
    deck.pack(side="left", fill="y", **pad)
    devices = sd_devices() or {"Stream Deck 5x3": ("20GBA9901", "", 5, 3)}
    k = {"profile": tk.StringVar(value=sc.get("profile", "Soundboard")),
         "device": tk.StringVar(value=sc.get("device") if sc.get("device") in devices else next(iter(devices))),
         "cols": tk.IntVar(value=sc.get("cols", 5)), "rows": tk.IntVar(value=sc.get("rows", 3))}
    r = tk.Frame(deck)
    r.pack(fill="x", padx=6, pady=3)
    tk.Label(r, text="Device:").pack(side="left")
    ttk.Combobox(r, textvariable=k["device"], values=tuple(devices), state="readonly", width=44).pack(side="left", padx=4)
    r = tk.Frame(deck)
    r.pack(fill="x", padx=6, pady=3)
    tk.Label(r, text="Columns:").pack(side="left")
    tk.Spinbox(r, textvariable=k["cols"], from_=1, to=16, width=3).pack(side="left", padx=4)
    tk.Label(r, text="Rows:").pack(side="left")
    tk.Spinbox(r, textvariable=k["rows"], from_=1, to=16, width=3).pack(side="left", padx=4)
    tk.Label(r, text="Profile name:").pack(side="left", padx=(10, 0))
    tk.Entry(r, textvariable=k["profile"], width=16).pack(side="left", padx=4)
    grid = tk.Frame(deck)
    grid.pack(padx=6, pady=6)
    ke = tk.LabelFrame(deck, text=" Selected key ")
    ke.pack(fill="x", padx=6, pady=(0, 6))
    kind_v, title_v = tk.StringVar(value="Single sound"), tk.StringVar()
    r = tk.Frame(ke)
    r.pack(fill="x", padx=6, pady=3)
    tk.Label(r, textvariable=cur, width=5, font=("Segoe UI", 10, "bold")).pack(side="left")
    tk.Label(r, text="Action:").pack(side="left")
    ttk.Combobox(r, textvariable=kind_v, values=tuple(SD_KINDS), state="readonly", width=14).pack(side="left", padx=4)
    tk.Label(r, text="Key name:").pack(side="left", padx=(8, 0))
    tk.Entry(r, textvariable=title_v, width=14).pack(side="left", padx=4)
    kbtns = tk.Frame(ke)
    kbtns.pack(fill="x", padx=6, pady=(0, 4))

    # 3. Per-sound settings
    ed = tk.LabelFrame(page, text=" 3. Sound settings (select sounds in the list, change, then Apply) ")
    ed.pack(fill="x", **pad)
    v = {"title": tk.StringVar(), "mode": tk.StringVar(value=sc.get("mode", SD_MODES[0])),
         "fade": tk.StringVar(value=sc.get("fade", SD_FADES[0])), "fade_len": tk.StringVar(value=sc.get("fade_len", "1")),
         "volume": tk.IntVar(value=sc.get("volume", 100)), "output": tk.StringVar(value=sc.get("output", ""))}
    r = tk.Frame(ed)
    r.pack(fill="x", padx=6, pady=3)
    tk.Label(r, text="Name:").pack(side="left")
    tk.Entry(r, textvariable=v["title"], width=18).pack(side="left", padx=4)
    tk.Label(r, text="Action:").pack(side="left", padx=(10, 0))
    ttk.Combobox(r, textvariable=v["mode"], values=SD_MODES, state="readonly", width=14).pack(side="left", padx=4)
    tk.Label(r, text="Fade:").pack(side="left", padx=(10, 0))
    ttk.Combobox(r, textvariable=v["fade"], values=SD_FADES, state="readonly", width=13).pack(side="left", padx=4)
    tk.Label(r, text="Length (s):").pack(side="left", padx=(10, 0))
    ttk.Combobox(r, textvariable=v["fade_len"], values=("1", "2", "3", "4", "5"), state="readonly",
                 width=3).pack(side="left", padx=4)
    tk.Label(r, text="Volume:").pack(side="left", padx=(10, 0))
    tk.Scale(r, variable=v["volume"], from_=0, to=100, orient="horizontal", length=110).pack(side="left")
    tk.Label(r, text="Output device (blank = default):").pack(side="left", padx=(10, 0))
    out_cb = ttk.Combobox(r, textvariable=v["output"], width=30)
    out_cb.config(postcommand=lambda: out_cb.config(values=sd_output_choices()))
    out_cb.pack(side="left", padx=4)

    bar = tk.Frame(page)
    bar.pack(fill="x", padx=10, pady=(4, 10))
    status = tk.Label(bar, anchor="w", text="Add sounds, click a key, assign them, then Send to Stream Deck.")

    def deck_size():
        try:
            return max(1, int(k["cols"].get())), max(1, int(k["rows"].get()))
        except (tk.TclError, ValueError):
            return 5, 3

    def show():
        tree.delete(*tree.get_children())
        for i, s in enumerate(sounds):
            tree.insert("", "end", iid=str(i), values=(s["title"], s["key"] or "auto", s["mode"],
                        s["fade"] + (f" {s['fade_len']}s" if s["fade"] != SD_FADES[0] else ""),
                        s["volume"], s["output"] or "default", s["path"]))
        draw()

    def draw():
        for w in grid.winfo_children():
            w.destroy()
        c_n, r_n = deck_size()
        try:
            lay = {f"{c + 1},{r + 1}": x for (c, r), x in sd_layout(sounds, keys, c_n, r_n).items()}
        except ValueError:
            lay = {}  # mid-edit conflict; Send reports it
        for r in range(r_n):
            for c in range(c_n):
                pos = f"{c + 1},{r + 1}"
                kind, title, group = lay.get(pos, ("", "", []))
                auto = group and not group[0]["key"]
                text = (f"{title[:10]}\n{'auto' if auto else kind.split()[0]}"
                        + (f" x{len(group)}" if len(group) > 1 else "")) if group else pos
                tk.Button(grid, text=text, width=10, height=3, font=("Segoe UI", 8),
                          relief="sunken" if pos == cur.get() else "raised",
                          bg="#2b6cb0" if pos == cur.get() else ("#c6f6d5" if group and not auto else
                                                                 "#edf2f7" if auto else "#ffffff"),
                          fg="white" if pos == cur.get() else "black",
                          command=lambda p=pos: pick_key(p)).grid(row=r, column=c, padx=2, pady=2)

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

    def add(paths, key=""):
        have = {str(s["path"]): s for s in sounds}
        added = 0
        for p in map(Path, paths):
            if str(p) in have:
                have[str(p)]["key"] = key or have[str(p)]["key"]
            elif p.is_file():
                sounds.append({"path": p, "title": p.stem[:20], "key": key, **{n: v[n].get() for n in
                               ("mode", "fade", "fade_len", "volume", "output")}})  # new sounds take the editor's settings
                added += 1
        show()
        return added

    def folder_sounds(title):
        f = filedialog.askdirectory(title=title)
        return [q for q in media_files([f]) if q.suffix.lower() in AUDIO_EXT] if f else []

    def folder_to_key():
        """Every sound in a folder onto the selected key as one action (Random unless already Multi)."""
        files = folder_sounds(f"Sounds for key {cur.get()}")
        if not files:
            return
        add(files, cur.get())
        if len(files) > 1 and kind_v.get() == "Single sound":
            kind_v.set("Random Action")
        if not title_v.get().strip():
            title_v.set(Path(files[0]).parent.name[:20])
        status.config(text=f"Key {cur.get()}: {len(files)} sound(s) from {Path(files[0]).parent}")

    def files_to_key():
        add(filedialog.askopenfilenames(title=f"Sounds for key {cur.get()}",
                                        filetypes=[("Audio", audio_pat), ("All files", "*.*")]), cur.get())

    def selected_to_key():
        sel = picked()
        if not sel:
            return messagebox.showinfo("Assign", "Select sounds in the list first.")
        for i in sel:
            sounds[i]["key"] = cur.get()
        if len([s for s in sounds if s["key"] == cur.get()]) > 1 and kind_v.get() == "Single sound":
            kind_v.set("Random Action")
        show()

    def clear_key():
        for s in sounds:
            if s["key"] == cur.get():
                s["key"] = ""
        keys.pop(cur.get(), None)
        pick_key(cur.get())
        show()

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
        tree.selection_set([str(i) for i in sel])

    def move(step):
        sel = picked()
        if len(sel) == 1 and 0 <= sel[0] + step < len(sounds):
            i = sel[0]
            sounds[i], sounds[i + step] = sounds[i + step], sounds[i]
            show()
            tree.selection_set(str(i + step))

    def remove():
        for i in sorted(picked(), reverse=True):
            del sounds[i]
        show()

    def unassign():
        for i in picked():
            sounds[i]["key"] = ""
        show()

    def preview():
        sel = picked()
        if sel:
            os.startfile(sounds[sel[0]]["path"])  # ponytail: plays in the default player, not through Stream Deck

    def on_device(*_):
        _, _, c, r = devices[k["device"].get()]
        k["cols"].set(c), k["rows"].set(r)

    def save():
        sc.update({n: x.get() for n, x in k.items()})
        sc.update({n: v[n].get() for n in ("mode", "fade", "fade_len", "volume", "output")}, direct=direct.get())

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
                writes = sd_install(name, (model, dev_id, *deck_size()), sounds, keys)
            except ValueError as e:
                return messagebox.showerror("Mapping", str(e))
            if sd_running():
                if not messagebox.askyesno("Close Stream Deck", "Stream Deck must close to add the profile "
                                           "(it rewrites its profiles when it exits).\nClose it now and reopen it after?"):
                    return
                if not sd_stop():
                    return messagebox.showerror("Stream Deck", "Couldn't close Stream Deck. Close it and try again.")
            try:
                sd_save(writes, [])
            except OSError as e:
                return messagebox.showerror("Profile", f"Couldn't write the profile:\n{e}")
            sd_start()
            return status.config(text=f"Installed profile '{name}' with {len(sounds)} sound(s); Stream Deck reopened. "
                                      "Pick it in Stream Deck's profile list.")
        try:
            out = sd_profile(SD_OUT / f"{safe}.streamDeckProfile", name, (model, dev_id, *deck_size()), sounds, keys)
        except ValueError as e:
            return messagebox.showerror("Mapping", str(e))
        except OSError as e:
            return messagebox.showerror("Profile", f"Couldn't write the profile:\n{e}")
        try:
            os.startfile(out)  # Stream Deck owns .streamDeckProfile: it opens its import prompt
            status.config(text=f"Sent {len(sounds)} sound(s) to Stream Deck - confirm the import there. File: {out}")
        except OSError:
            status.config(text=f"Stream Deck app not found. Profile saved: {out} (double-click it once installed)")

    for text, cmd in (("Add folder to this key...", folder_to_key), ("Add files to this key...", files_to_key),
                      ("Selected sounds -> this key", selected_to_key), ("Clear this key", clear_key)):
        tk.Button(kbtns, text=text, command=cmd).pack(side="left", padx=2, expand=True, fill="x")
    for text, cmd in (("Add files...", lambda: add(filedialog.askopenfilenames(
                          title="Select sounds", filetypes=[("Audio", audio_pat), ("All files", "*.*")]))),
                      ("Add folder...", lambda: add(folder_sounds("Add every sound in folder"))),
                      ("Add Channel Mirror outputs", lambda: add(made) if made else messagebox.showinfo(
                          "No outputs yet", "Run the Channel Mirror tab first; the files it writes show up here.")),
                      ("Preview", preview), ("Move up", lambda: move(-1)), ("Move down", lambda: move(1)),
                      ("Unassign key (auto)", unassign), ("Remove selected", remove),
                      ("Clear all", lambda: (sounds.clear(), keys.clear(), show()))):
        tk.Button(side, text=text, command=cmd, width=24).pack(pady=2)
    tk.Button(ed, text="Apply to selected", command=apply, width=16).pack(anchor="e", padx=6, pady=(0, 6))
    tk.Button(bar, text="Send to Stream Deck", command=send, width=20,
              font=("Segoe UI", 11, "bold")).pack(side="left")
    direct = tk.BooleanVar(value=sc.get("direct", SD_EXE.exists()))
    tk.Checkbutton(bar, text="Install directly (no import prompt; restarts Stream Deck)", variable=direct,
                   state="normal" if SD_EXE.exists() else "disabled").pack(side="left", padx=8)
    status.pack(side="left", fill="x", expand=True, padx=10)
    tree.bind("<<TreeviewSelect>>", on_pick)
    k["device"].trace_add("write", on_device)
    for x in (k["cols"], k["rows"]):
        x.trace_add("write", lambda *_: draw())
    kind_v.trace_add("write", key_changed)
    title_v.trace_add("write", key_changed)
    if "cols" not in sc:
        on_device()
    draw()
    return save


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

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
    if (BUNDLE / "icon.ico").exists():
        root.iconbitmap(default=str(BUNDLE / "icon.ico"))
    if offer_install(root, cfg):  # started the installed copy instead
        root.destroy()
        return
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")) and not first_run_setup(root):
        root.destroy()
        return
    root.title("Channel Mirror")
    pad = {"padx": 10, "pady": 4}
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    page, sd_page = tk.Frame(nb), tk.Frame(nb)
    nb.add(page, text="  Channel Mirror  ")
    nb.add(sd_page, text="  Stream Deck soundboard  ")
    ed_page = tk.Frame(nb)
    nb.add(ed_page, text="  Stream Deck editor  ")
    made = []  # files written this session, offered to the Stream Deck tab
    sd_save = streamdeck_tab(sd_page, cfg, made)
    sd_editor_tab(ed_page)

    # 1. Input files
    inp = tk.LabelFrame(page, text=" 1. Input files ")
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
    sett = tk.LabelFrame(page, text=" 2. Settings ")
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
    outf = tk.LabelFrame(page, text=f' 3. Output folder (blank = a "{OUT_SUBDIR}" folder beside the inputs) ')
    outf.pack(fill="x", **pad)
    out_var = tk.StringVar(value=cfg.get("out_dir", ""))
    tk.Entry(outf, textvariable=out_var).pack(side="left", fill="x", expand=True, padx=6, pady=6)

    runbar = tk.Frame(page)
    runbar.pack(fill="x", padx=10, pady=(4, 10))
    status = tk.Label(runbar, anchor="w", text="Add audio files or a folder to begin.")

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
        lst.delete(0, "end")
        sources, targets = chosen()
        total = 0
        for src, info, rms in items:
            names = labels(len(rms))
            levels = "  ".join(f"{nm} {v:6.1f} dB" for nm, v in zip(names, db(rms)))
            jobs = plan_jobs(src, rms, sources, targets, out_ext(src, info, mode_var.get()))
            total += len(jobs)
            part = "_partNN" if split_var.get() else ""  # part count is only known once Run finds the silences
            outs = ", ".join(f"{Path(j[2]).stem}{part}{Path(j[2]).suffix}" for j in jobs) or "(nothing selected)"
            lst.insert("end", f"{src.name}  |  {levels}  |  loudest {names[int(np.argmax(rms))]}  |  {len(jobs)} out: {outs}")
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
    shown = tk.StringVar(value=label_of[mode_var.get()])
    tk.OptionMenu(row, shown, *OUTPUT_TYPES, command=lambda lbl: mode_var.set(OUTPUT_TYPES[lbl])).pack(side="left", padx=4)
    mode_var.trace_add("write", refresh)

    row = tk.Frame(sett)
    row.pack(fill="x", padx=6, pady=3)
    tk.Label(row, text="Length:", width=16, anchor="w").pack(side="left")
    tk.Entry(row, textvariable=len_var, width=9).pack(side="left", padx=4)
    len_hint = tk.Label(row, width=34, anchor="w")
    len_hint.pack(side="left")
    loop_cb = tk.Checkbutton(row, text="Loop to fill length", variable=loop_var)
    loop_cb.pack(side="left", padx=(12, 4))
    quiet_cb = tk.Checkbutton(row, variable=quiet_var)
    quiet_cb.pack(side="left", padx=4)

    row = tk.Frame(sett)
    row.pack(fill="x", padx=6, pady=3)
    tk.Label(row, text="Split:", width=16, anchor="w").pack(side="left")
    tk.Checkbutton(row, text="Split each file into parts", variable=split_var).pack(side="left")
    parts_lbl = tk.Label(row, text="Parts:")
    parts_lbl.pack(side="left", padx=(12, 0))
    parts_entry = tk.Entry(row, textvariable=parts_var, width=5)
    parts_entry.pack(side="left", padx=4)
    split_hint = tk.Label(row, anchor="w")
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

    def on_close():
        sd_save()
        save_settings()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    # files/folders dropped on the exe or sent via right-click "Send to" arrive as arguments
    dropped = [a for a in sys.argv[1:] if not a.startswith("--")]
    if dropped:
        root.after(100, load, media_files(dropped))
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
        (Path(d) / "notes.txt").write_text("x")
        assert media_files([d, st]) == [mono, st, st]  # folder -> media only, sorted; files pass through
        song = Path("C:/music/album/song.mp3")
        assert out_folder(song) == Path("C:/music/album") / OUT_SUBDIR
        assert out_folder(song, "D:/out") == Path("D:/out/album")
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
        assert out_ext(st, info, "audio") == ".wav"  # audio inputs keep their own extension
        # every output type from a video: video formats keep the picture, audio formats drop it
        for mode, ext, want in (("same", ".mp4", ["audio", "video"]), ("audio", ".m4a", ["audio"]),
                                ("mkv", ".mkv", ["audio", "video"]), ("mov", ".mov", ["audio", "video"]),
                                *((m, "." + m, ["audio"]) for m in ("wav", "mp3", "flac", "m4a", "ogg", "opus",
                                                                       "aiff"))):
            assert out_ext(vid, vinfo, mode) == ext
            dst = route(vid, Path(d) / out_name(vid, "right", ext=ext), vinfo, 0, "right", mode)
            assert dst.suffix == ext and kinds(dst) == want, (dst.name, kinds(dst))
            got = analyze(dst)[1]
            assert got[0] < 1e-4 and abs(got[1] - vrms[0]) < 0.02, (dst.name, got, vrms)

        # any file ffmpeg can read works; an extension ffmpeg can't write falls back to .mkv instead of failing
        odd = Path(d) / "st.xyz"
        odd.write_bytes(st.read_bytes())
        oinfo = analyze(odd)[0]
        dst = route(odd, Path(d) / out_name(odd, "left"), oinfo, 0, "left")
        assert dst.suffix == ".mkv" and kinds(dst) == ["audio"], dst

        # length: exact cut, looping past the end, and ending at the quiet gap instead of mid-tone
        assert parse_time("") is None and parse_time("1:30") == 90 and parse_time("12.5") == 12.5
        assert clip_seconds(st, info, 0, 5) is None  # longer than the file without loop = whole file
        for secs, loop in ((0.5, False), (2.5, True)):
            out = route(st, Path(d) / f"len{secs}.wav", info, 0, "both", "same", secs, loop)
            assert abs(analyze(out)[0]["duration"] - secs) < 0.01, (secs, analyze(out)[0]["duration"])
        gap = Path(d) / "gap.wav"  # tone 0-1 s, silence 1-1.2 s, tone 1.2-2.2 s
        tone = np.concatenate([loud, np.zeros(8820), loud])
        write_wav(gap, [tone, tone])
        ginfo = analyze(gap)[0]
        cut = clip_seconds(gap, ginfo, 0, 2.0, quiet=True)
        assert 1.0 <= cut <= 1.2, cut
        assert clip_seconds(gap, ginfo, 0, 2.0) == 2.0
        cut = clip_seconds(gap, ginfo, 0, 4.4, loop=True, quiet=True)  # 2nd pass's gap sits at 3.2-3.4 s
        assert 3.2 <= cut <= 3.4, cut

        # split: cuts land mid-silence (gap 1.0-1.2 s -> 1.1); no silence at the file's edges = whole file used
        for segs in (split_points(gap, ginfo, 0, 1.5), split_points(gap, ginfo, 0, count=2)):
            assert len(segs) == 2 and segs[0][0] == 0 and abs(segs[1][0] - 1.1) < 0.03 and segs[1][1] is None, segs
        segs = split_points(gap, ginfo, 0, 0.5, 3)  # first 3 parts of <= 0.5 s, even through unbroken sound
        assert len(segs) == 3 and all(0 < s <= 0.5 for _, s in segs), segs
        # silence 0-0.4, tone, silence 1.4-1.6, tone, silence 2.6-3.0: parts run 0.2-1.5 and 1.5-2.8 (silence middles)
        pad = Path(d) / "pad.wav"
        sil = lambda secs: np.zeros(int(44100 * secs))
        ptone = np.concatenate([sil(0.4), loud, sil(0.2), loud, sil(0.4)])
        write_wav(pad, [ptone, ptone])
        pinfo = analyze(pad)[0]
        for segs in (split_points(pad, pinfo, 0, 1.5), split_points(pad, pinfo, 0, count=2)):
            assert np.allclose(segs, [(0.2, 1.3), (1.5, 1.3)], atol=0.03), segs
        for start, secs, want in ((0.5, 0.5, 0.5), (1.1, None, 1.1)):  # a middle part and the last part
            out = route(gap, Path(d) / f"part{start}.wav", ginfo, 0, "both", "same", secs, start=start)
            assert abs(analyze(out)[0]["duration"] - want) < 0.01, (start, analyze(out)[0]["duration"])

        # first-run ffmpeg install: unpacks the two exes from a checksum-verified zip, refuses a damaged one
        import hashlib
        import zipfile
        z = Path(d) / "ff.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("ffmpeg-x/bin/ffmpeg.exe", "A"), zf.writestr("ffmpeg-x/bin/ffprobe.exe", "B")
        good = hashlib.sha256(z.read_bytes()).hexdigest()
        sha = Path(d) / "ff.zip.sha256"
        sha.write_text(good + "  ff.zip\n")
        dest = Path(d) / "ffdl"
        download_ffmpeg(lambda m: None, z.as_uri(), dest)
        assert (dest / "ffmpeg.exe").read_text() == "A" and (dest / "ffprobe.exe").read_text() == "B"
        sha.write_text("0" * 64)
        try:
            download_ffmpeg(lambda m: None, z.as_uri(), Path(d) / "bad")
            raise AssertionError("damaged download was accepted")
        except RuntimeError:
            assert not (Path(d) / "bad").exists()

        # Stream Deck: key parsing, mapping, profile package, device discovery
        assert sd_key("2,3", 5, 3) == (1, 2) and sd_key(" ", 5, 3) is None
        for bad in ("6,1", "x"):
            try:
                sd_key(bad, 5, 3)
                raise AssertionError(bad)
            except ValueError:
                pass
        snd = lambda p, key="": {"path": p, "title": Path(p).stem, "key": key, "mode": "Loop / Stop",
                                 "fade": "Fade In", "fade_len": "2", "volume": 80, "output": ""}
        sounds = [snd(st, "1,1"), snd(mono, "1,1"), snd(gap), snd(pad, "2,1")]
        keys = {"1,1": {"kind": "Random Action", "title": "Folder"}}
        lay = sd_layout(sounds, keys, 2, 2)
        assert lay[(0, 0)][:2] == ("Random Action", "Folder") and len(lay[(0, 0)][2]) == 2
        assert lay[(1, 0)][2][0]["title"] == "pad" and lay[(0, 1)][2][0]["title"] == "gap"  # unmapped -> next free
        for bad_keys, bad_sounds in (({}, sounds), (keys, sounds + [snd(st), snd(st)])):  # 2 on single / deck full
            try:
                sd_layout(bad_sounds, bad_keys, 2, 2)
                raise AssertionError("bad layout accepted")
            except ValueError:
                pass
        prof = sd_profile(Path(d) / "sd" / "t.streamDeckProfile", "T", ("20GBA9901", "@(1)[4057/128/X]", 2, 2),
                          sounds, keys)
        with zipfile.ZipFile(prof) as zf:
            names = zf.namelist()
            top = json.loads(zf.read(next(n for n in names if n.count("/") == 2 and n.endswith("manifest.json"))))
            page = json.loads(zf.read(next(n for n in names if top["Pages"]["Pages"][0].upper() in n)))
            res = json.loads(zf.read("Resources/manifest.json"))["resources"]
            acts = page["Controllers"][0]["Actions"]
            rnd = acts["0,0"]
            assert rnd["UUID"] == SD_KINDS["Random Action"] and rnd["States"][0]["Title"] == "Folder"
            inner = rnd["Actions"][0]["Actions"]
            assert len(inner) == 2 and inner[0]["Settings"] == {
                "actionType": 3, "fadeLen": 2, "fadeType": 1, "outputType": "", "path": str(st.resolve()), "volume": 80}
            assert acts["1,0"]["UUID"].endswith("playaudio") and set(acts) == {"0,0", "1,0", "0,1"}
            assert len(res) == 4 and all(f"Resources/{v['file']}" in names for v in res.values())
            assert top["Device"]["UUID"] == "@(1)[4057/128/X]"
        fake = Path(d) / "SD" / "ProfilesV3" / "A.sdProfile"
        (fake / "Profiles" / "P").mkdir(parents=True)
        (fake / "manifest.json").write_text(json.dumps({"Name": "Mine", "Device": {
            "Model": "20GBA9901", "UUID": "@(1)[4057/128/AB12]"}}))
        (fake / "Profiles" / "P" / "manifest.json").write_text(json.dumps({"Controllers": [
            {"Type": "Keypad", "Actions": {"4,2": {}}}, {"Type": "Encoder", "Actions": {"9,9": {}}}]}))
        devs = sd_devices(Path(d) / "SD", {"USB\\VID_0FD9&PID_0080\\AB12"})
        assert list(devs.values()) == [("20GBA9901", "@(1)[4057/128/AB12]", 5, 3)], devs
        assert next(iter(devs)).startswith("[connected]")

        # editing installed profiles: nested sounds, purpose/volume/label edits, arranging, relink, backup + save
        files, _ = sd_profile_files("E", ("20GBA9901", "x", 2, 2), sounds, keys)
        pg = next(v for a, v in files.items() if a.count("/") == 4 and v.get("Name") == "E")
        kp = sd_keypad(pg)
        assert [len(sd_sounds(kp[k])) for k in ("0,0", "1,0", "0,1")] == [2, 1, 1]
        assert sd_kind(kp["0,0"]) == "Random x2" and sd_kind(kp["1,0"]) == "Sound" and not sd_missing(kp["0,0"])
        allsnd = [s for a in kp.values() for s in sd_sounds(a)]
        sd_set_sound(allsnd, *SD_GOALS["Ambience bed (quiet loop, slow fades)"])
        assert {(s["Settings"]["actionType"], s["Settings"]["fadeType"], s["Settings"]["fadeLen"],
                 s["Settings"]["volume"]) for s in allsnd} == {(3, 3, 5, 35)}
        sd_set_sound(allsnd, step=-50)
        assert {s["Settings"]["volume"] for s in allsnd} == {0}  # clamped
        sd_set_sound(allsnd, volume=100)
        lv = {s["Settings"]["path"]: v for s, v in zip(allsnd, (-10.0, -20.0, -20.0, -26.0))}
        assert sd_match_loudness(allsnd, lv) == 4
        assert [s["Settings"]["volume"] for s in allsnd] == [16, 50, 50, 100]  # -16 dB, -6 dB, -6 dB; quietest (-26 dB) plays at full
        sd_label(kp["1,0"], "File name", "> ", "!", "a", "A", {"FontSize": 14})
        assert kp["1,0"]["States"][0] == {"Title": "> pAd!", "FontSize": 14}
        sd_move(kp, "1,0", "0,1")  # swap
        assert sd_title(kp["0,1"]) == "> pAd!" and sd_title(kp["1,0"]) == "gap"
        sd_combine(kp, ["1,0", "0,1"], "Multi Action", "Both")
        assert sd_kind(kp["1,0"]) == "Multi x2" and "0,1" not in kp
        kp["1,1"] = sd_stop_key()
        try:
            sd_combine(kp, ["1,0", "1,1"], "Random Action", "")
            raise AssertionError("combined a non-sound key")
        except ValueError:
            pass
        assert sd_split(kp, "0,0", 2, 2) == 2 and set(kp) == {"0,0", "0,1", "1,0", "1,1"}
        assert sd_kind(kp["0,1"]) == "Sound" and sd_title(kp["0,1"]) == "mono"
        kp["0,1"]["Settings"]["path"] = "/Users/someone/Downloads/mono.wav"  # a profile copied from a Mac
        assert sd_missing(kp["0,1"]) and sd_relink(sd_sounds(kp["0,1"]), d) == (1, 0)
        assert Path(kp["0,1"]["Settings"]["path"]) == mono
        root = Path(d) / "SD"
        writes = sd_install("New", ("20GBA9901", "x", 2, 2), sounds, keys, root)
        assert all(str(p).startswith(str(root / "ProfilesV3")) for p in writes) and len(writes) == 3
        assert sd_save(writes, [], root, Path(d) / "bk") is None  # nothing old to back up
        got = sd_profiles(root)
        assert sorted(m["Name"] for _, m in got) == ["Mine", "New"]
        new_dir, new_m = next(x for x in got if x[1]["Name"] == "New")
        assert [n for n, _ in sd_pages(new_dir, new_m)] == ["Page 1"]  # the empty default page isn't shown
        pages = [p for _, p in sd_pages(new_dir, new_m)]
        assert len(sd_keypad(json.loads(pages[0].read_text()))) == 3
        sub = pages[0].parents[1] / "ABCD1234" / "manifest.json"  # a folder key on page 1 opens this page
        sub.parent.mkdir()
        sub.write_text("{}")
        p1 = json.loads(pages[0].read_text())
        sd_keypad(p1)["1,1"] = {"UUID": "com.elgato.streamdeck.profile.openchild", "States": [{"Title": "SFX"}],
                                "Settings": {"ProfileUUID": "abcd1234"}}
        pages[0].write_text(json.dumps(p1))
        assert [n for n, _ in sd_pages(new_dir, new_m)] == ["Page 1", "Folder: SFX"]

        # output device: picking a Random/Multi key sets every sound inside it; saved values are offered back
        p1 = json.loads(pages[0].read_text())
        found = sd_multis([("Page 1", p1), ("Folder: SFX", {})])
        assert [(lbl, k, sd_kind(a)) for lbl, k, a in found] == [("Page 1", "0,0", "Random x2")]
        rnd = found[0][2]
        sd_set_sound(sd_sounds(rnd), output="Headphones (Arctis Nova Pro Wireless)")
        assert {s["Settings"]["outputType"] for s in sd_sounds(rnd)} == {"Headphones (Arctis Nova Pro Wireless)"}
        assert sd_keypad(p1)["1,0"]["Settings"]["outputType"] == ""  # other keys untouched
        pages[0].write_text(json.dumps(p1))
        assert sd_outputs(root) == ["Headphones (Arctis Nova Pro Wireless)"]
        sd_set_sound(sd_sounds(rnd), output=SD_DEFAULT_OUT)  # "default" in the dropdown = blank in the profile
        assert {s["Settings"]["outputType"] for s in sd_sounds(rnd)} == {""} and sd_out(" x ") == "x"

        # self-install: copy, shortcuts, Windows uninstall entry, then a clean uninstall (temp dirs + a test key)
        import winreg
        app, key = Path(d) / "app", r"Software\ChannelMirrorSelftest"
        fake_exe = Path(d) / "ChannelMirror-download.exe"
        shutil.copy2(sys.executable, fake_exe)  # any real exe (a shortcut needs a valid icon source)
        links = {"start": Path(d) / "lnk" / "Channel Mirror.lnk"}
        exe = install(fake_exe, app, links, key)
        assert exe == app / "ChannelMirror.exe" and exe.read_bytes() == fake_exe.read_bytes()
        assert links["start"].stat().st_size > 0 and installed(key) == exe
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            assert winreg.QueryValueEx(k, "UninstallString")[0] == f'"{exe}" --uninstall'
        install(fake_exe, app, {}, key)  # again = update, no error
        uninstall(app, links, key)
        assert not app.exists() and not links["start"].exists() and installed(key) is None
        bk = sd_save({pages[0]: {"Controllers": []}}, [new_dir], root, Path(d) / "bk")
        assert json.loads(pages[0].read_text()) == {"Controllers": []}
        with zipfile.ZipFile(bk) as zf:  # the backup holds the page as it was before the write
            old = json.loads(zf.read(str(pages[0].relative_to(root / "ProfilesV3")).replace("\\", "/")))
            assert len(sd_keypad(old)) == 4  # 3 sound keys + the folder key
    print("selftest ok")


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


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--uninstall" in sys.argv:
        uninstall_cli()
    elif "--install" in sys.argv and getattr(sys, "frozen", False):  # silent install for scripts: every shortcut, then done
        install(Path(sys.executable), links=shortcut_paths())
    else:
        gui()
