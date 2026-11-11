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


_win_outputs: list = []


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


# --- UI toolkit: theme, tooltips, menus, key grid, cell editing, dialogs (stdlib tkinter only) ---
UI = {"bg": "#f3f4f6", "panel": "#ffffff", "border": "#d1d5db", "text": "#1f2937", "muted": "#6b7280",
      "accent": "#2563eb", "accent2": "#1d4ed8", "sound": "#d1fae5", "missing": "#fee2e2", "other": "#e5e7eb",
      "auto": "#e0e7ff", "empty": "#ffffff", "font": ("Segoe UI", 10), "small": ("Segoe UI", 8)}


def ui_theme(root):
    """One light theme for every widget: ttk styles plus matching defaults for the classic tk widgets."""
    from tkinter import ttk
    c = UI
    root.configure(bg=c["bg"])
    for pat, val in (("*Background", c["bg"]), ("*Foreground", c["text"]), ("*Font", "{Segoe UI} 10"),
                     ("*Listbox.background", c["panel"]), ("*Text.background", c["panel"]),
                     ("*selectBackground", c["accent"]), ("*selectForeground", "#ffffff"),
                     ("*Scale.highlightThickness", 0), ("*Scale.troughColor", c["border"]),
                     ("*Scale.sliderRelief", "flat"), ("*Scale.borderWidth", 0), ("*Scale.activeBackground", c["accent"]),
                     ("*TCombobox*Listbox.background", c["panel"]), ("*TCombobox*Listbox.font", "{Segoe UI} 10"),
                     ("*Menu.background", c["panel"]), ("*Menu.activeBackground", c["accent"]),
                     ("*Menu.activeForeground", "#ffffff"), ("*Menu.relief", "flat")):
        root.option_add(pat, val)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=c["bg"], foreground=c["text"], font=c["font"], bordercolor=c["border"],
                lightcolor=c["bg"], darkcolor=c["bg"], troughcolor=c["border"], focuscolor=c["accent"])
    s.configure("TButton", padding=(10, 4), background="#e8ebf0")
    s.map("TButton", background=[("pressed", "#d1d6de"), ("active", "#dde2e9"), ("disabled", c["bg"])])
    s.configure("Accent.TButton", background=c["accent"], foreground="#ffffff", font=("Segoe UI", 10, "bold"),
                padding=(16, 6))
    s.map("Accent.TButton", background=[("pressed", c["accent2"]), ("active", c["accent2"]), ("disabled", "#9db7f0")],
          foreground=[("disabled", "#eef2ff")])
    s.configure("Tool.TButton", padding=(8, 2), width=0)
    s.configure("Toolbutton", padding=(12, 7), anchor="w", background=c["bg"])
    s.map("Toolbutton", background=[("selected", c["accent"]), ("active", "#dde2e9")],
          foreground=[("selected", "#ffffff")])
    s.configure("TLabelframe", background=c["bg"], bordercolor=c["border"], relief="solid", padding=10)
    s.configure("TLabelframe.Label", background=c["bg"], foreground=c["text"], font=("Segoe UI", 10, "bold"))
    s.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(10, 6, 10, 0))
    s.configure("TNotebook.Tab", padding=(18, 7), background="#e5e8ed")
    s.map("TNotebook.Tab", background=[("selected", c["panel"])], expand=[("selected", (1, 1, 1, 0))])
    from tkinter import font as tkfont
    line = tkfont.Font(root=root, family="Segoe UI", size=10).metrics("linespace")  # scales with Windows DPI
    s.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], rowheight=line + 8,
                bordercolor=c["border"])
    for w in ("TCheckbutton", "TRadiobutton"):
        s.configure(w, indicatorbackground=c["panel"], indicatorforeground=c["accent"], indicatormargin=(0, 0, 6, 0))
        s.map(w, background=[("disabled", c["bg"]), ("active", c["bg"])],
              indicatorbackground=[("disabled", c["bg"]), ("pressed", c["border"])])
    s.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", "#ffffff")])
    s.configure("Treeview.Heading", background="#eceff3", font=("Segoe UI", 9, "bold"), padding=(6, 4), relief="flat")
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(w, fieldbackground=c["panel"], padding=3)
    s.map("TCombobox", fieldbackground=[("readonly", c["panel"])])
    s.configure("Hint.TLabel", foreground=c["muted"], font=("Segoe UI", 9))
    s.configure("Field.TLabel", foreground=c["muted"], font=("Segoe UI", 8, "bold"))
    s.configure("Status.TLabel", padding=(2, 4))
    s.configure("Header.TFrame", background=c["panel"])
    s.configure("Header.TLabel", background=c["panel"])
    s.configure("HeadTitle.TLabel", background=c["panel"], font=("Segoe UI", 15, "bold"))
    s.configure("HeadSub.TLabel", background=c["panel"], foreground=c["muted"])


class Tip:
    """Hover help for a widget; text may be a function so it can describe the widget's current state."""

    def __init__(self, widget, text):
        self.w, self.text, self.win, self.job = widget, text, None, None
        widget.bind("<Enter>", lambda e: self.later(), add="+")
        widget.bind("<Leave>", lambda e: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda e: self.hide(), add="+")

    def later(self):
        self.hide()
        self.job = self.w.after(500, self.show)

    def show(self):
        import tkinter as tk
        text = self.text() if callable(self.text) else self.text
        if not text or not self.w.winfo_exists():
            return
        self.win = tk.Toplevel(self.w)
        self.win.wm_overrideredirect(True)
        self.win.wm_geometry(f"+{self.w.winfo_rootx() + 12}+{self.w.winfo_rooty() + self.w.winfo_height() + 4}")
        tk.Label(self.win, text=text, justify="left", bg="#111827", fg="#f9fafb", font=("Segoe UI", 9),
                 padx=8, pady=5, wraplength=420).pack()

    def hide(self):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.win:
            self.win.destroy()
            self.win = None


def ui_menu(widget, event, items):
    """Right-click menu. items: (label, command) pairs, None = separator, command None = greyed out."""
    import tkinter as tk
    m = tk.Menu(widget, tearoff=0)
    for it in items:
        if it is None:
            m.add_separator()
        else:
            m.add_command(label=it[0], command=it[1] or (lambda: None), state="normal" if it[1] else "disabled")
    try:
        m.tk_popup(event.x_root, event.y_root)
    finally:
        m.grab_release()


def ui_busy_focus(widget):
    """True while the user is typing somewhere (keyboard shortcuts then leave the keys alone)."""
    try:
        cls = widget.tk.call("winfo", "class", widget.tk.call("focus"))
    except Exception:
        return False
    return cls in ("Entry", "TEntry", "Text", "TCombobox", "TSpinbox", "Spinbox")


def ui_keys(page, bindings):
    """Keyboard shortcuts that only act while this tab is showing and nobody is typing."""
    top = page.winfo_toplevel()
    for seq, fn in bindings.items():
        def handler(e, fn=fn):
            if page.winfo_ismapped() and not ui_busy_focus(page):
                fn()
                return "break"
        for s in {seq, seq[:-2] + seq[-2].upper() + ">"} if seq.startswith("<Control-") else {seq}:
            top.bind(s, handler, add="+")


class DeckGrid:
    """A Stream Deck key grid of flat tiles. tile(pos) -> (text, bg, fg) with pos = "col,row" counted from 0.
    Click / double-click / right-click call back with (pos, event); dragging one key onto another calls
    on_drop(src, dst); tip(pos) gives hover text; key_at() lets other widgets drop things onto keys."""

    def __init__(self, parent, tile, on_click=None, on_double=None, on_menu=None, on_drop=None, tip=None):
        import tkinter as tk
        self.frame = tk.Frame(parent, bg=UI["bg"])
        self.tile, self.on_click, self.on_double, self.on_menu, self.on_drop, self.tip = (
            tile, on_click, on_double, on_menu, on_drop, tip)
        self.tiles, self.size, self.drag = {}, None, {}

    def draw(self, cols, rows):
        import tkinter as tk
        if self.size != (cols, rows):  # tiles are kept between draws so double-clicks register
            for w in self.frame.winfo_children():
                w.destroy()
            self.tiles, self.size = {}, (cols, rows)
            for r in range(rows):
                for c in range(cols):
                    pos = f"{c},{r}"
                    w = tk.Label(self.frame, width=12, height=3, font=UI["small"], wraplength=96, justify="center",
                                 bd=0, highlightthickness=2, cursor="hand2")
                    w.grid(row=r, column=c, padx=3, pady=3)
                    w.bind("<ButtonPress-1>", lambda e, p=pos: self.drag.update(src=p, x=e.x_root, y=e.y_root))
                    w.bind("<B1-Motion>", self._motion)
                    w.bind("<ButtonRelease-1>", lambda e, p=pos: self._release(e, p))
                    w.bind("<Double-Button-1>", lambda e, p=pos: self.on_double and self.on_double(p, e))
                    w.bind("<Button-3>", lambda e, p=pos: self.on_menu and self.on_menu(p, e))
                    if self.tip:
                        Tip(w, lambda p=pos: self.tip(p))
                    self.tiles[pos] = w
        for pos, w in self.tiles.items():
            text, bg, fg = self.tile(pos)
            w.config(text=text, bg=bg, fg=fg,
                     highlightbackground=UI["accent2"] if bg == UI["accent"] else UI["border"])

    def _motion(self, e):
        d = self.drag
        if d and not d.get("moved") and abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) > 8:
            d["moved"] = True
            self.tiles[d["src"]].config(cursor="fleur")

    def _release(self, e, pos):
        d, self.drag = self.drag, {}
        if d.get("moved"):
            self.tiles[d["src"]].config(cursor="hand2")
            dst = self.key_at(e.x_root, e.y_root)
            if dst and dst != d["src"] and self.on_drop:
                self.on_drop(d["src"], dst)
        elif self.on_click:
            self.on_click(pos, e)

    def key_at(self, x, y):
        w = self.frame.winfo_containing(x, y)
        return next((p for p, t in self.tiles.items() if t is w), None)


def ui_cell_edit(tree, item, col, value, done, values=None, editable=False):
    """Edit one Treeview cell in place: an entry (or a dropdown when values are given) over the cell.
    Enter / picking a value / clicking away keeps it, Esc cancels; done(text) receives the new value."""
    import tkinter as tk
    from tkinter import ttk
    box = tree.bbox(item, col)
    if not box:
        return
    var = tk.StringVar(value=value)
    ed = (ttk.Combobox(tree, textvariable=var, values=values, state="normal" if editable else "readonly")
          if values is not None else ttk.Entry(tree, textvariable=var))
    ed.place(x=box[0], y=box[1], width=max(box[2], 120), height=box[3])
    ed.focus_set()
    if values is None:
        ed.select_range(0, "end")
    over = []

    def finish(keep):
        if not over:
            over.append(1)
            val = var.get()
            ed.destroy()
            if keep and val != value:
                done(val)

    def away(_):  # the dropdown list is a child of the combobox: moving focus there isn't "clicking away"
        ed.after(80, lambda: ed.winfo_exists() and not str(ed.tk.call("focus")).startswith(str(ed)) and finish(True))
    ed.bind("<Return>", lambda e: finish(True))
    ed.bind("<Escape>", lambda e: finish(False))
    ed.bind("<FocusOut>", away)
    if values is not None and not editable:
        ed.bind("<<ComboboxSelected>>", lambda e: finish(True))
        ed.after(10, lambda: ed.tk.call("ttk::combobox::Post", ed))


def ui_volume(parent, var, length=150):
    """0-100 slider with the number beside it."""
    from tkinter import ttk
    f = ttk.Frame(parent)
    ttk.Scale(f, from_=0, to=100, variable=var, length=length,
              command=lambda x: var.set(round(float(x)))).pack(side="left")
    ttk.Label(f, textvariable=var, width=4, anchor="e").pack(side="left")
    return f


def ui_sound_form(parent, v):
    """Action / fade / fade length / volume / output fields (labels above) bound to the tk variables in v."""
    from tkinter import ttk
    f = ttk.Frame(parent)
    out = ttk.Combobox(f, textvariable=v["output"], width=34)
    out.config(postcommand=lambda: out.config(values=sd_output_choices()))
    fields = (("ACTION", ttk.Combobox(f, textvariable=v["mode"], values=SD_MODES, state="readonly", width=15)),
              ("FADE", ttk.Combobox(f, textvariable=v["fade"], values=SD_FADES, state="readonly", width=14)),
              ("FADE LENGTH (S)", ttk.Combobox(f, textvariable=v["fade_len"], values=("1", "2", "3", "4", "5"),
                                               state="readonly", width=5)),
              ("VOLUME", ui_volume(f, v["volume"])),
              ("OUTPUT DEVICE", out))
    for i, (label, w) in enumerate(fields):
        ttk.Label(f, text=label, style="Field.TLabel").grid(row=0, column=i, sticky="w", padx=(0, 14))
        w.grid(row=1, column=i, sticky="sw", padx=(0, 14))
    Tip(out, "Devices Stream Deck has saved itself are listed first (exact); Windows device names follow.")
    return f


def ui_key_dialog(parent, action):
    """Edit one key in its own window: name and look, plus every sound on it (file, playback, fade, volume,
    output). Sounds can be added to a key (a single sound becomes a Random / Multi Action) or removed from one.
    Returns the edited copy, or None when cancelled."""
    import copy
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk
    kinds = {u for u in SD_KINDS.values() if u}
    work, result = [copy.deepcopy(action)], [None]
    states = action.get("States") or [{}]
    st0 = states[min(int(action.get("State") or 0), len(states) - 1)]
    win = tk.Toplevel(parent)
    win.title(f"Edit key - {sd_title(action).replace(chr(10), ' ') or sd_kind(action)}")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    kind_lbl = ttk.Label(body, style="Hint.TLabel")
    kind_lbl.pack(anchor="w", pady=(0, 8))

    look = ttk.LabelFrame(body, text="Name and look")
    look.pack(fill="x")
    ttk.Label(look, text="NAME (Enter = new line)", style="Field.TLabel").grid(row=0, column=0, sticky="w")
    name = tk.Text(look, height=3, width=24, relief="solid", bd=1, highlightthickness=0, wrap="none", undo=True)
    name.insert("1.0", st0.get("Title") or "")
    name.grid(row=1, column=0, rowspan=3, sticky="nw", padx=(0, 16))
    show = tk.BooleanVar(value=st0.get("ShowTitle", True))
    size = tk.StringVar(value=str(st0.get("FontSize", "")))
    align = tk.StringVar(value=st0.get("TitleAlignment") or "bottom")
    color = tk.StringVar(value=st0.get("TitleColor") or "")
    ttk.Checkbutton(look, text="Show name on the key", variable=show).grid(row=1, column=1, columnspan=3, sticky="w")
    for col, (label, w) in enumerate((
            ("FONT SIZE", ttk.Combobox(look, textvariable=size, values=("", "7", "8", "9", "10", "11", "12", "14",
                                                                        "16", "18", "20", "24"), width=5)),
            ("POSITION", ttk.Combobox(look, textvariable=align, values=("top", "middle", "bottom"), state="readonly",
                                      width=8))), 1):
        ttk.Label(look, text=label, style="Field.TLabel").grid(row=2, column=col, sticky="w", padx=(0, 12))
        w.grid(row=3, column=col, sticky="w", padx=(0, 12))
    ttk.Label(look, text="COLOUR", style="Field.TLabel").grid(row=2, column=3, sticky="w")
    cbox = ttk.Frame(look)
    cbox.grid(row=3, column=3, sticky="w")
    swatch = tk.Label(cbox, width=3, bg=color.get() or "#ffffff", relief="solid", bd=1)
    swatch.pack(side="left", padx=(0, 6))

    def pick_color():
        c = colorchooser.askcolor(color.get() or "#ffffff", parent=win, title="Name colour")[1]
        if c:
            color.set(c)
            swatch.config(bg=c)
    ttk.Button(cbox, text="Pick...", style="Tool.TButton", command=pick_color).pack(side="left")

    has_sounds = bool(sd_sounds(action)) or action.get("UUID") in kinds
    if has_sounds:
        sf = ttk.LabelFrame(body, text="Sounds on this key")
        sf.pack(fill="both", expand=True, pady=(12, 0))
        cols = ("file", "mode", "fade", "volume", "output")
        tv = ttk.Treeview(sf, columns=cols, show="headings", height=6, selectmode="browse")
        for c, h, w in zip(cols, ("File", "Action", "Fade", "Volume", "Output"), (240, 110, 130, 60, 200)):
            tv.heading(c, text=h)
            tv.column(c, width=w, stretch=c in ("file", "output"))
        tv.pack(fill="both", expand=True)
        v = {"path": tk.StringVar(), "mode": tk.StringVar(), "fade": tk.StringVar(), "fade_len": tk.StringVar(),
             "volume": tk.IntVar(value=100), "output": tk.StringVar()}
        fr = ttk.Frame(sf)
        fr.pack(fill="x", pady=(10, 4))
        ttk.Label(fr, text="FILE", style="Field.TLabel").pack(anchor="w")
        ttk.Entry(fr, textvariable=v["path"], width=70).pack(side="left", fill="x", expand=True)
        ui_sound_form(sf, v).pack(fill="x", pady=4)
        btns = ttk.Frame(sf)
        btns.pack(fill="x", pady=(6, 0))
        loading, cur = [False], [None]
        pick = lambda t, i: t[i] if isinstance(i, int) and 0 <= i < len(t) else t[0]

        def row_of(s):
            se = s.get("Settings", {})
            ok = Path(se.get("path", "")).is_file()
            return (Path(se.get("path", "")).name + ("" if ok else "  (missing)"), pick(SD_MODES, se.get("actionType")),
                    pick(SD_FADES, se.get("fadeType")) + (f" {se.get('fadeLen', 1)}s" if se.get("fadeType") else ""),
                    se.get("volume", 100), se.get("outputType") or "default")

        def fill(select=0):
            tv.delete(*tv.get_children())
            for i, s in enumerate(sd_sounds(work[0])):
                tv.insert("", "end", iid=str(i), values=row_of(s))
            kind_lbl.config(text=f"Type: {sd_kind(work[0])}   -   select a sound to change it; changes apply as you "
                                 "make them and are kept when you press OK")
            if tv.get_children():
                tv.selection_set(str(min(select, len(tv.get_children()) - 1)))

        def on_sel(_=None):
            sel = tv.selection()
            if not sel:
                return
            cur[0] = sd_sounds(work[0])[int(sel[0])]
            se = cur[0].setdefault("Settings", {})
            loading[0] = True
            v["path"].set(se.get("path", ""))
            v["mode"].set(pick(SD_MODES, se.get("actionType")))
            v["fade"].set(pick(SD_FADES, se.get("fadeType")))
            v["fade_len"].set(str(se.get("fadeLen", 1)))
            v["volume"].set(int(se.get("volume", 100)))
            v["output"].set(se.get("outputType") or SD_DEFAULT_OUT)
            loading[0] = False

        def on_var(*_):
            if loading[0] or not cur[0]:
                return
            try:
                vol = int(v["volume"].get())
            except (tk.TclError, ValueError):
                return
            cur[0].setdefault("Settings", {})["path"] = v["path"].get().strip()
            sd_set_sound([cur[0]], v["mode"].get(), v["fade"].get(), v["fade_len"].get(), vol, output=v["output"].get())
            if tv.selection():
                tv.item(tv.selection()[0], values=row_of(cur[0]))
        for var in v.values():
            var.trace_add("write", on_var)
        tv.bind("<<TreeviewSelect>>", on_sel)

        def inner():
            a = work[0]
            if a.get("UUID") in kinds:
                if not a.get("Actions"):
                    a["Actions"] = [{"Actions": []}]
                return a["Actions"][0].setdefault("Actions", [])
            return None

        def add_sounds():
            files = filedialog.askopenfilenames(parent=win, title="Add sounds to this key", filetypes=[
                ("Audio", " ".join(f"*{e}" for e in AUDIO_EXT)), ("All files", "*.*")])
            if not files:
                return
            base = (cur[0] or {}).get("Settings", {})
            plays = [sd_play(f, Path(f).stem[:20], pick(SD_MODES, base.get("actionType")),
                             pick(SD_FADES, base.get("fadeType")), base.get("fadeLen", 1), base.get("volume", 100),
                             base.get("outputType", "")) for f in files]
            lst = inner()
            if lst is None:  # a single sound: becomes a Random or Multi Action holding it and the new ones
                ans = messagebox.askyesnocancel("Add sounds", "This key plays one sound. Turn it into a Random Action "
                                                "(one random sound per press)?\n\nNo = Multi Action (all play together)",
                                                parent=win)
                if ans is None:
                    return
                old = work[0]
                work[0] = sd_wrap("Random Action" if ans else "Multi Action", sd_title(old), [old] + plays)
                work[0]["States"] = copy.deepcopy(old.get("States") or [{}])
            else:
                lst.extend(plays)
            fill(len(sd_sounds(work[0])) - 1)

        def reorder(step):
            lst, s = inner(), cur[0]
            i = next((n for n, x in enumerate(lst or []) if x is s), None)
            if i is None:
                return
            if step == 0:
                if len(lst) < 2:
                    return messagebox.showinfo("Remove", "A key needs at least one sound.", parent=win)
                del lst[i]
                return fill(i)
            j = i + step
            if 0 <= j < len(lst):
                lst[i], lst[j] = lst[j], lst[i]
                fill(j)

        def preview():
            if cur[0] and Path(cur[0]["Settings"].get("path", "")).is_file():
                os.startfile(cur[0]["Settings"]["path"])

        def browse():
            f = filedialog.askopenfilename(parent=win, title="Sound file", filetypes=[
                ("Audio", " ".join(f"*{e}" for e in AUDIO_EXT)), ("All files", "*.*")])
            if f:
                v["path"].set(str(Path(f)))
        ttk.Button(fr, text="Browse...", style="Tool.TButton", command=browse).pack(side="left", padx=(6, 0))
        ttk.Button(fr, text="Preview", style="Tool.TButton", command=preview).pack(side="left", padx=(6, 0))
        for text, cmd in (("Add sounds...", add_sounds), ("Remove sound", lambda: reorder(0)),
                          ("Move up", lambda: reorder(-1)), ("Move down", lambda: reorder(1))):
            ttk.Button(btns, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 6))
        fill()
    else:
        kind_lbl.config(text=f"Type: {sd_kind(action)}   -   this key isn't a sound; its name and look can be edited")

    def ok():
        a = work[0]
        if not a.get("States"):
            a["States"] = [{}]
        for s in a["States"]:
            s["Title"] = name.get("1.0", "end-1c")
            if "ShowTitle" in s or show.get() != st0.get("ShowTitle", True):  # untouched defaults stay unwritten
                s["ShowTitle"] = show.get()
            if "TitleAlignment" in s or align.get() != (st0.get("TitleAlignment") or "bottom"):
                s["TitleAlignment"] = align.get()
            if size.get().strip().isdigit():
                s["FontSize"] = int(size.get())
            if color.get():
                s["TitleColor"] = color.get()
        result[0] = a
        win.destroy()
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(14, 0))
    ttk.Button(bar, text="OK", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.update_idletasks()
    p = parent.winfo_toplevel()
    win.geometry(f"+{p.winfo_rootx() + max(0, (p.winfo_width() - win.winfo_width()) // 2)}"
                 f"+{p.winfo_rooty() + max(0, (p.winfo_height() - win.winfo_height()) // 3)}")
    win.grab_set()
    win.wait_window()
    return result[0]


GOAL_HELP = {
    "Set them up for a purpose": "One click sets the action, fade and (for some) volume to suit what the sounds are for.",
    "Playback and fade": "Change how a press plays the sound. Keep = leave that setting as it is.",
    "Volume": "Set, nudge or even out the volume of every sound on the selected keys.",
    "Output device": "Sets every sound on the selected keys, including all sounds inside a Multi or Random Action "
                     "(Jump to Multi / Random at the top picks one). Devices Stream Deck has saved itself are listed "
                     "first and are exact. If a key still plays on the default output with a Windows name, set one "
                     "key's output inside Stream Deck once, then pick the value that appears at the top here.",
    "Key names and look": "Rename keys in bulk and change how their names look. Double-click a key to edit one.",
    "Arrange keys": "You can also drag keys on the grid to move or swap them, and right-click a key for more.",
    "Fix missing sound files": "Points broken sound keys (red) at a file with the same name anywhere in this folder "
                               "- handy for profiles copied from another computer.",
}


def sd_editor_tab(page):
    """Edit the buttons of profiles already in the local Stream Deck app: select keys, use a tool, save."""
    import copy
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk

    if not (SD_DIR / "ProfilesV3").is_dir():
        ttk.Label(page, text="No local Stream Deck install found (looked in %APPDATA%\\Elgato\\StreamDeck).\n"
                             "Install the Stream Deck app, then reopen Channel Mirror.", justify="left"
                  ).pack(padx=20, pady=20, anchor="w")
        return
    plugged = sd_connected()
    kinds = {u for u in SD_KINDS.values() if u}  # Multi Action / Random Action ids
    grids = {v[1]: v[2:] for v in sd_devices(plugged=plugged).values()}  # device id -> (cols, rows)
    profs = {}
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
    hist = {"undo": [], "redo": [], "clip": None}

    # toolbar
    bar = ttk.Frame(page, padding=(10, 10, 10, 4))
    bar.pack(fill="x")
    prof_v, page_v, multi_v, multi_map = tk.StringVar(value=labels_[0] if labels_ else ""), tk.StringVar(), \
        tk.StringVar(), {}
    ttk.Label(bar, text="Profile").pack(side="left")
    ttk.Combobox(bar, textvariable=prof_v, values=labels_, state="readonly", width=40).pack(side="left", padx=(6, 14))
    ttk.Label(bar, text="Page").pack(side="left")
    page_cb = ttk.Combobox(bar, textvariable=page_v, state="readonly", width=16)
    page_cb.pack(side="left", padx=(6, 14))
    ttk.Label(bar, text="Jump to Multi / Random").pack(side="left")
    multi_cb = ttk.Combobox(bar, textvariable=multi_v, state="readonly", width=44)
    multi_cb.pack(side="left", padx=6)
    save_btn = ttk.Button(bar, text="Save to Stream Deck", style="Accent.TButton")
    save_btn.pack(side="right")
    tbtn = {}
    for name, text, tip in (("revert", "Revert", "Throw away every unsaved change (can be undone)"),
                            ("redo", "Redo", "Ctrl+Y"), ("undo", "Undo", "Ctrl+Z")):
        tbtn[name] = ttk.Button(bar, text=text, style="Tool.TButton")
        tbtn[name].pack(side="right", padx=(0, 6))
        Tip(tbtn[name], tip)

    panes = ttk.PanedWindow(page, orient="horizontal")
    panes.pack(fill="both", expand=True, padx=10, pady=6)
    left = ttk.LabelFrame(panes, text="Keys")
    right = ttk.LabelFrame(panes, text="Tools for the selected keys")
    panes.add(left, weight=3)
    panes.add(right, weight=2)
    status = ttk.Label(page, style="Status.TLabel", anchor="w",
                       text="Pick a profile and page. Click keys to select them (Ctrl+click adds).")
    status.pack(fill="x", padx=12, pady=(0, 8))

    # left: selection buttons, the deck, legend, details
    sb = ttk.Frame(left)
    sb.pack(fill="x")
    ttk.Label(sb, text="Select", style="Hint.TLabel").pack(side="left", padx=(0, 6))
    for text, test, tip in (("Sounds", lambda a: bool(sd_sounds(a)), "Every key that plays a sound"),
                            ("Missing", lambda a: bool(sd_missing(a)), "Sound keys whose file can't be found"),
                            ("Multi / Random", lambda a: bool(a) and a.get("UUID") in kinds, "Multi and Random Actions"),
                            ("All", bool, "Every key in use (Ctrl+A)"), ("None", lambda a: False, "Esc")):
        b = ttk.Button(sb, text=text, style="Tool.TButton", command=lambda t=test: select(t))
        b.pack(side="left", padx=(0, 4))
        Tip(b, tip)

    def tile(pos):
        a, on = keys_now().get(pos), pos in st["sel"]
        c, r_ = map(int, pos.split(","))
        bg = (UI["accent"] if on else UI["missing"] if a and sd_missing(a) else UI["sound"] if a and sd_sounds(a)
              else UI["other"] if a else UI["empty"])
        fg = "#ffffff" if on else UI["text"] if a else UI["muted"]
        if not a:
            return f"{c + 1},{r_ + 1}", bg, fg
        return f"{(sd_title(a).replace(chr(10), ' ') or '-')[:22]}\n{sd_kind(a)[:16]}", bg, fg

    def tip_for(pos):
        a = keys_now().get(pos)
        c, r_ = map(int, pos.split(","))
        if not a:
            return f"Empty key {c + 1},{r_ + 1}\nDouble-click to add a sound key; right-click for more."
        lines = [f"Key {c + 1},{r_ + 1}: {sd_title(a).replace(chr(10), ' ') or '(no name)'}  -  {sd_kind(a)}"]
        for s in sd_sounds(a)[:10]:
            se = s.get("Settings", {})
            miss = "" if Path(se.get("path", "")).is_file() else "   MISSING"
            lines.append(f"  - {Path(se.get('path', '')).name}  ({SD_MODES[se.get('actionType', 0)] if se.get('actionType', 0) < 4 else '?'}"
                         f", vol {se.get('volume', '?')}){miss}")
        if len(sd_sounds(a)) > 10:
            lines.append(f"  ...and {len(sd_sounds(a)) - 10} more")
        return "\n".join(lines + ["Double-click to edit; drag to move; right-click for more."])

    def click(pos, e):
        if e.state & 0x0005:  # Ctrl / Shift: add or remove
            st["sel"].remove(pos) if pos in st["sel"] else st["sel"].append(pos)
        else:
            st["sel"] = [] if st["sel"] == [pos] else [pos]
        draw()

    deck = DeckGrid(left, tile, on_click=click, on_double=lambda p, e: (edit_key(p) if keys_now().get(p)
                                                                        else new_key(p)),
                    on_menu=lambda p, e: key_menu(p, e), on_drop=lambda a, b: drop(a, b), tip=tip_for)
    deck.frame.pack(pady=(10, 6))
    legend = ttk.Frame(left)
    legend.pack(fill="x")
    for color, text in ((UI["sound"], "sound"), (UI["missing"], "file missing"), (UI["other"], "other action"),
                        (UI["accent"], "selected")):
        tk.Label(legend, bg=color, width=2, relief="solid", bd=1).pack(side="left")
        ttk.Label(legend, text=text, style="Hint.TLabel").pack(side="left", padx=(4, 14))
    ttk.Label(legend, text="Drag = move/swap  -  Double-click = edit  -  Right-click = more",
              style="Hint.TLabel").pack(side="right")
    dcols = ("key", "name", "type", "mode", "fade", "volume", "output", "file")
    dt = ttk.Frame(left)
    dt.pack(fill="both", expand=True, pady=(8, 0))
    details = ttk.Treeview(dt, columns=dcols, show="headings", height=4, selectmode="browse")
    for c, h, w in zip(dcols, ("Key", "Name", "Type", "Action", "Fade", "Vol", "Output", "File"),
                       (45, 120, 90, 105, 120, 45, 130, 200)):
        details.heading(c, text=h)
        details.column(c, width=w, stretch=c in ("name", "file", "output"))
    dys = ttk.Scrollbar(dt, command=details.yview)
    details.config(yscrollcommand=dys.set)
    dys.pack(side="right", fill="y")
    details.pack(fill="both", expand=True)
    ttk.Label(left, text="Double-click a cell above to change it; double-click File to pick another file.",
              style="Hint.TLabel").pack(anchor="w", pady=(4, 0))

    # right: tool list + options
    goals = tuple(GOAL_HELP)
    goal_v = tk.StringVar(value=goals[0])
    tools = ttk.Frame(right)
    tools.pack(side="left", fill="y", padx=(0, 12))
    for g in goals:
        ttk.Radiobutton(tools, text=g, value=g, variable=goal_v, style="Toolbutton").pack(fill="x", pady=1)
    opts = ttk.Frame(right)
    opts.pack(side="left", fill="both", expand=True)
    help_lbl = ttk.Label(opts, style="Hint.TLabel", wraplength=420, justify="left")
    help_lbl.pack(fill="x", pady=(0, 8))
    holder = ttk.Frame(opts)
    holder.pack(fill="both", expand=True)
    apply_btn = ttk.Button(opts, text="Apply", style="Accent.TButton")
    apply_btn.pack(anchor="e", pady=(8, 0))
    frames = {g: ttk.Frame(holder) for g in goals}
    o = {}

    def row(g, label, make):
        fr = ttk.Frame(frames[g])
        fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=16).pack(side="left")
        make(fr)
        return fr

    def combo(g, key, label, values, width=30):
        o[key] = tk.StringVar(value=values[0])
        row(g, label, lambda fr: ttk.Combobox(fr, textvariable=o[key], values=values, state="readonly",
                                               width=width).pack(side="left"))

    def entry(g, key, label, value="", width=24):
        o[key] = tk.StringVar(value=value)
        row(g, label, lambda fr: ttk.Entry(fr, textvariable=o[key], width=width).pack(side="left"))

    g = goals[0]
    combo(g, "goal", "Purpose", tuple(SD_GOALS), 42)
    goal_desc = ttk.Label(frames[g], style="Hint.TLabel")
    goal_desc.pack(fill="x", pady=(4, 0))
    o["goal"].trace_add("write", lambda *_: goal_desc.config(text="Sets: {} / {} {}s{}".format(
        *SD_GOALS[o["goal"].get()][:3],
        f" / volume {SD_GOALS[o['goal'].get()][3]}" if SD_GOALS[o["goal"].get()][3] is not None else "")))
    o["goal"].set(o["goal"].get())
    g = goals[1]
    combo(g, "mode", "Action", ("Keep",) + SD_MODES)
    combo(g, "fade", "Fade", ("Keep",) + SD_FADES)
    combo(g, "fade_len", "Fade length (s)", ("Keep", "1", "2", "3", "4", "5"), 8)
    g = goals[2]
    o["vol_how"], o["vol"], o["step"] = tk.StringVar(value="set"), tk.IntVar(value=80), tk.IntVar(value=-10)
    for how, text, make in (("set", "Set to", lambda fr: ui_volume(fr, o["vol"], 180).pack(side="left")),
                            ("step", "Change by (+/-)", lambda fr: ttk.Spinbox(fr, textvariable=o["step"], from_=-100,
                                                                              to=100, width=6).pack(side="left")),
                            ("match", "Match loudness", lambda fr: ttk.Label(
                                fr, text="measures each file; louder ones are turned down to the quietest",
                                style="Hint.TLabel").pack(side="left"))):
        fr = ttk.Frame(frames[g])
        fr.pack(fill="x", pady=4)
        ttk.Radiobutton(fr, text=text, variable=o["vol_how"], value=how, width=16).pack(side="left")
        make(fr)
    g = goals[3]
    o["output"] = tk.StringVar(value=SD_DEFAULT_OUT)

    def out_box(fr):
        cb = ttk.Combobox(fr, textvariable=o["output"], width=48)
        cb.config(postcommand=lambda: cb.config(values=sd_output_choices()))
        cb.pack(side="left")
    row(g, "Output device", out_box)
    g = goals[4]
    combo(g, "source", "Name from", ("Keep", "File name", "Folder name", "Number", "Clear"))
    entry(g, "prefix", "Add before")
    entry(g, "suffix", "Add after")
    entry(g, "find", "Replace text")
    entry(g, "repl", "   with")
    combo(g, "show", "Show name", ("Keep", "Show", "Hide"), 10)
    combo(g, "size", "Font size", ("Keep", "7", "8", "9", "10", "12", "14", "16", "18"), 10)
    combo(g, "align", "Name position", ("Keep", "top", "middle", "bottom"), 10)
    o["color"] = tk.StringVar(value="")

    def color_row(fr):
        sw = tk.Label(fr, width=3, bg=UI["panel"], relief="solid", bd=1)

        def pick():
            c = colorchooser.askcolor(o["color"].get() or "#ffffff", title="Name colour")[1]
            if c:
                o["color"].set(c)
                sw.config(bg=c, text="")
        sw.pack(side="left", padx=(0, 6))
        ttk.Button(fr, text="Pick...", style="Tool.TButton", command=pick).pack(side="left")
        ttk.Button(fr, text="Keep", style="Tool.TButton",
                   command=lambda: (o["color"].set(""), sw.config(bg=UI["panel"]))).pack(side="left", padx=4)
    row(g, "Name colour", color_row)
    g = goals[5]
    o["arr"], o["slot"], o["ctitle"] = tk.StringVar(value="combine"), tk.StringVar(value="1,1"), tk.StringVar()
    o["ckind"] = tk.StringVar(value="Random Action")
    for how, text, extra in (
            ("combine", "Combine selected into one",
             lambda fr: (ttk.Combobox(fr, textvariable=o["ckind"], values=("Random Action", "Multi Action"),
                                      state="readonly", width=14).pack(side="left", padx=(0, 6)),
                         ttk.Label(fr, text="named").pack(side="left"),
                         ttk.Entry(fr, textvariable=o["ctitle"], width=14).pack(side="left", padx=6))),
            ("split", "Split Multi / Random keys into single keys", lambda fr: None),
            ("move", "Move the selected key to (col,row)",
             lambda fr: ttk.Entry(fr, textvariable=o["slot"], width=6).pack(side="left")),
            ("stop", "Add a 'Stop all audio' key at (col,row)",
             lambda fr: ttk.Entry(fr, textvariable=o["slot"], width=6).pack(side="left")),
            ("delete", "Delete the selected keys", lambda fr: None)):
        fr = ttk.Frame(frames[g])
        fr.pack(fill="x", pady=4)
        ttk.Radiobutton(fr, text=text, variable=o["arr"], value=how).pack(side="left", padx=(0, 8))
        extra(fr)
    g = goals[6]
    entry(g, "folder", "Search folder", str(Path.home() / "Music"), 40)
    row(g, "", lambda fr: ttk.Button(fr, text="Browse...", style="Tool.TButton", command=lambda: o["folder"].set(
        filedialog.askdirectory(title="Folder that holds the sounds") or o["folder"].get())).pack(side="left"))

    def on_goal(*_):
        for f in frames.values():
            f.pack_forget()
        frames[goal_v.get()].pack(fill="both", expand=True)
        help_lbl.config(text=GOAL_HELP[goal_v.get()])
    goal_v.trace_add("write", on_goal)
    on_goal()

    # state helpers
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
        cols, rows = grids.get(m.get("Device", {}).get("UUID", ""), (5, 3))
        for k in keys_now():
            c, r_ = map(int, k.split(","))
            cols, rows = max(cols, c + 1), max(rows, r_ + 1)
        return cols, rows

    def snap():
        return copy.deepcopy(edits), list(st["sel"])

    def commit(before, msg):
        """Record an edit for undo and show it."""
        hist["undo"].append(before)
        del hist["undo"][:-60]
        hist["redo"].clear()
        status.config(text=f"{msg}. Not saved yet - Save to Stream Deck (Ctrl+S) writes it, Ctrl+Z undoes it.")
        list_multis()
        draw()

    def restore(frm, to, msg):
        if not hist[frm]:
            return
        hist[to].append(snap())
        e, sel = hist[frm].pop()
        edits.clear()
        edits.update(e)
        st["sel"] = sel
        status.config(text=msg)
        list_multis()
        draw()

    def kp_edit():
        return sd_keypad(cur_page())

    def draw():
        if st["page"]:
            deck.draw(*size())
        details.delete(*details.get_children())
        kp = keys_now()
        for k in st["sel"]:
            a = kp.get(k)
            c, r_ = map(int, k.split(","))
            key = f"{c + 1},{r_ + 1}"
            if not a:
                details.insert("", "end", iid=f"e|{k}", values=(key, "(empty)", "", "", "", "", "", ""))
                continue
            snds = sd_sounds(a)
            if a.get("UUID") != SD_PLAY:
                details.insert("", "end", iid=f"k|{k}", values=(key, sd_title(a).replace("\n", " "), sd_kind(a),
                                                               "", "", "", "", ""))
            for i, s in enumerate(snds):
                se = s.get("Settings", {})
                miss = "" if Path(se.get("path", "")).is_file() else "  (missing)"
                fade = (SD_FADES[se.get("fadeType", 0)] if se.get("fadeType", 0) < 4 else "?") + (
                    f" {se.get('fadeLen', 1)}s" if se.get("fadeType") else "")
                single = a.get("UUID") == SD_PLAY
                details.insert("", "end", iid=f"s|{k}|{i}", values=(
                    key if single else "", sd_title(a).replace("\n", " ") if single else "",
                    "Sound" if single else "  sound", SD_MODES[se.get("actionType", 0)] if se.get("actionType", 0) < 4
                    else "?", fade, se.get("volume", "?"), se.get("outputType") or "default",
                    Path(se.get("path", "")).name + miss))
        dirty = sum(1 for p in edits if edits[p] != json.loads(p.read_text(encoding="utf-8")))
        save_btn.config(text=f"Save to Stream Deck ({dirty} page{'s' * (dirty != 1)} changed)" if dirty
                        else "Save to Stream Deck")
        used = sum(1 for k in st["sel"] if kp.get(k))
        apply_btn.config(text=f"Apply to {used} key{'s' * (used != 1)}" if used else "Apply")
        tbtn["undo"].state(["!disabled"] if hist["undo"] else ["disabled"])
        tbtn["redo"].state(["!disabled"] if hist["redo"] else ["disabled"])

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
                page_v.set(label)
            st["sel"] = [k]
            draw()
            status.config(text=f"Selected {multi_v.get()}. Choose a tool on the right (e.g. Output device) and Apply.")

    def on_page(*_):
        names = list(page_cb.cget("values"))
        st["page"] = st["pages"][names.index(page_v.get())] if page_v.get() in names else None
        st["sel"] = []
        draw()

    def slot(text):
        c, r_ = sd_key(text, *size())
        return f"{c},{r_}"

    # key actions (grid, menus, shortcuts)
    def edit_key(pos):
        st["sel"] = [pos]
        draw()
        a = keys_now().get(pos)
        new = ui_key_dialog(page, a) if a else None
        if new is not None and new != a:
            before = snap()
            kp_edit()[pos] = new
            commit(before, f"Edited key {pos_label(pos)}")

    def new_key(pos):
        files = filedialog.askopenfilenames(title=f"Sound(s) for key {pos_label(pos)}", filetypes=[
            ("Audio", " ".join(f"*{e}" for e in AUDIO_EXT)), ("All files", "*.*")])
        if not files:
            return
        plays = [sd_play(Path(f), Path(f).stem[:20]) for f in files]
        if len(plays) == 1:
            act = plays[0]
        else:
            ans = messagebox.askyesnocancel("New key", f"{len(plays)} sounds: make a Random Action (one random sound "
                                            "per press)?\n\nNo = Multi Action (all play together)")
            if ans is None:
                return
            act = sd_wrap("Random Action" if ans else "Multi Action", Path(files[0]).parent.name[:20], plays)
        before = snap()
        kp_edit()[pos] = act
        st["sel"] = [pos]
        commit(before, f"New sound key at {pos_label(pos)}")

    def pos_label(pos):
        c, r_ = map(int, pos.split(","))
        return f"{c + 1},{r_ + 1}"

    def drop(src, dst):
        before = snap()
        sd_move(kp_edit(), src, dst)
        st["sel"] = [dst]
        commit(before, f"Moved key {pos_label(src)} to {pos_label(dst)} (anything there swapped places)")

    def copy_key():
        a = next((keys_now()[k] for k in st["sel"] if keys_now().get(k)), None)
        if a:
            hist["clip"] = copy.deepcopy(a)
            status.config(text=f"Copied '{sd_title(a).replace(chr(10), ' ') or sd_kind(a)}'. Select a key "
                               "(any page or profile) and paste with Ctrl+V or right-click.")

    def paste_key(pos=None):
        if not hist["clip"] or not st["page"]:
            return
        pos = pos or (st["sel"][0] if len(st["sel"]) == 1 else next(iter(sd_free(keys_now(), *size())), None))
        if not pos:
            return messagebox.showinfo("Paste", "No free key on this page; select the key to paste onto.")
        if keys_now().get(pos) and not messagebox.askyesno("Paste", f"Replace key {pos_label(pos)}?"):
            return
        before = snap()
        kp_edit()[pos] = sd_renew(copy.deepcopy(hist["clip"]))
        st["sel"] = [pos]
        commit(before, f"Pasted onto key {pos_label(pos)}")

    def delete_keys(keys):
        keys = [k for k in keys if keys_now().get(k)]
        if keys and messagebox.askyesno("Delete keys", f"Delete {len(keys)} key(s) from this page?"):
            before = snap()
            for k in keys:
                kp_edit().pop(k, None)
            st["sel"] = []
            commit(before, f"Deleted {len(keys)} key(s)")

    def preview(pos):
        for s in sd_sounds(keys_now().get(pos)):
            if Path(s["Settings"].get("path", "")).is_file():
                return os.startfile(s["Settings"]["path"])
        status.config(text="That key has no sound file that can be played.")

    def combine(kind):
        keys = [k for k in st["sel"] if keys_now().get(k)]
        before = snap()
        try:
            sd_combine(kp_edit(), keys, kind, "")
        except ValueError as e:
            edits.clear(), edits.update(before[0])
            return messagebox.showerror("Combine", str(e))
        st["sel"] = [keys[0]]
        commit(before, f"Combined {len(keys)} keys into a {kind}")

    def split(pos):
        before = snap()
        try:
            n = sd_split(kp_edit(), pos, *size())
        except ValueError as e:
            edits.clear(), edits.update(before[0])
            return messagebox.showerror("Split", str(e))
        commit(before, f"Split into {n} single sound keys")

    def stop_key(pos):
        before = snap()
        kp_edit()[pos] = sd_stop_key()
        commit(before, f"Added a Stop Audio key at {pos_label(pos)}")

    def key_menu(pos, e):
        if pos not in st["sel"]:
            st["sel"] = [pos]
            draw()
        a = keys_now().get(pos)
        multi_sel = [k for k in st["sel"] if keys_now().get(k) and sd_sounds(keys_now()[k])]
        if a:
            items = [("Edit key...", lambda: edit_key(pos)),
                     ("Preview sound", (lambda: preview(pos)) if sd_sounds(a) else None), None,
                     ("Copy key   Ctrl+C", copy_key), ("Paste here   Ctrl+V", (lambda: paste_key(pos))
                                                       if hist["clip"] else None), None,
                     ("Combine selected into a Random Action", (lambda: combine("Random Action"))
                      if len(multi_sel) > 1 else None),
                     ("Combine selected into a Multi Action", (lambda: combine("Multi Action"))
                      if len(multi_sel) > 1 else None),
                     ("Split into single keys", (lambda: split(pos)) if len(sd_sounds(a)) > 1 else None), None,
                     ("Delete key   Del", lambda: delete_keys(st["sel"]))]
        else:
            items = [("New sound key...", lambda: new_key(pos)),
                     ("Add 'Stop all audio' key here", lambda: stop_key(pos)),
                     ("Paste here   Ctrl+V", (lambda: paste_key(pos)) if hist["clip"] else None)]
        ui_menu(deck.frame, e, items)

    def edit_cell(e):
        item, col = details.identify_row(e.y), details.identify_column(e.x)
        if not item or not col:
            return
        name = dcols[int(col[1:]) - 1]
        kind, k, *idx = item.split("|")
        if kind == "e":
            return new_key(k)
        a = keys_now().get(k)
        s = sd_sounds(a)[int(idx[0])] if kind == "s" else None
        se = (s or {}).get("Settings", {})
        if name in ("key", "type"):
            return edit_key(k)

        def done(val, field=name):
            before = snap()
            live = kp_edit()[k]
            snd = sd_sounds(live)[int(idx[0])] if kind == "s" else None
            try:
                if field == "name":
                    if not live.get("States"):
                        live["States"] = [{}]
                    for x in live["States"]:
                        x["Title"] = val
                elif field == "mode":
                    sd_set_sound([snd], mode=val)
                elif field == "fade":
                    sd_set_sound([snd], fade=val)
                elif field == "volume":
                    vol = int(val)
                    assert 0 <= vol <= 100
                    sd_set_sound([snd], volume=vol)
                elif field == "output":
                    sd_set_sound([snd], output=val)
            except (ValueError, AssertionError):
                return messagebox.showerror("Volume", "Volume is a whole number from 0 to 100.")
            commit(before, f"Changed {field} on key {pos_label(k)}")
        if name == "name" and (kind == "k" or a.get("UUID") == SD_PLAY):
            ui_cell_edit(details, item, col, sd_title(a), done)
        elif s is None:
            return
        elif name == "mode":
            ui_cell_edit(details, item, col, details.set(item, col), done, SD_MODES)
        elif name == "fade":
            ui_cell_edit(details, item, col, SD_FADES[se.get("fadeType", 0)] if se.get("fadeType", 0) < 4 else "",
                         done, SD_FADES)
        elif name == "volume":
            ui_cell_edit(details, item, col, str(se.get("volume", 100)), done)
        elif name == "output":
            ui_cell_edit(details, item, col, se.get("outputType") or SD_DEFAULT_OUT, done, sd_output_choices(), True)
        elif name == "file":
            f = filedialog.askopenfilename(title="Sound file", initialdir=str(Path(se.get("path", "")).parent)
                                           if Path(se.get("path", "")).parent.is_dir() else None,
                                           filetypes=[("Audio", " ".join(f"*{x}" for x in AUDIO_EXT)),
                                                      ("All files", "*.*")])
            if f:
                before = snap()
                sd_sounds(kp_edit()[k])[int(idx[0])]["Settings"]["path"] = str(Path(f))
                commit(before, f"Changed the file on key {pos_label(k)}")
    details.bind("<Double-Button-1>", edit_cell)

    def apply():
        if not st["page"]:
            return
        kp = keys_now()
        sel = [k for k in st["sel"] if kp.get(k)]
        g = goal_v.get()
        if not sel and not (g == "Arrange keys" and o["arr"].get() == "stop"):
            return messagebox.showinfo("Select keys", "Click keys on the grid (or use the Select buttons) first.")
        if not [s for k in sel for s in sd_sounds(kp[k])] and g in goals[:4]:
            return messagebox.showinfo("No sounds", "The selected key(s) hold no Play Audio actions "
                                       "(e.g. a hotkey macro), so there's nothing to change.")
        before = snap()
        kp = kp_edit()
        sounds = [s for k in sel for s in sd_sounds(kp[k])]
        keep = lambda x: None if x == "Keep" else x
        try:
            if g == goals[0]:
                mode, fade, secs, vol = SD_GOALS[o["goal"].get()]
                sd_set_sound(sounds, mode, fade, secs, vol)
                msg = f"{len(sounds)} sound(s) set up for: {o['goal'].get()}"
            elif g == goals[1]:
                sd_set_sound(sounds, keep(o["mode"].get()), keep(o["fade"].get()), keep(o["fade_len"].get()))
                msg = f"Playback changed on {len(sounds)} sound(s)"
            elif g == goals[2]:
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
            elif g == goals[3]:
                sd_set_sound(sounds, output=o["output"].get())
                msg = (f"Output set to {sd_out(o['output'].get()) or 'the default device'} on {len(sounds)} "
                       f"sound(s) in {len(sel)} key(s)")
            elif g == goals[4]:
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
            elif g == goals[5]:
                how = o["arr"].get()
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
                    n = sum(sd_split(kp, k, *size()) for k in sel if len(sd_sounds(kp.get(k))) > 1)
                    msg = f"Split into {n} single sound keys"
                elif how == "stop":
                    k = slot(o["slot"].get())
                    if kp.get(k) and not messagebox.askyesno("Replace key", "That key is in use. Replace it?"):
                        raise LookupError
                    kp[k] = sd_stop_key()
                    msg = "Added a Stop Audio key"
                else:
                    if not messagebox.askyesno("Delete keys", f"Delete {len(sel)} key(s) from this page?"):
                        raise LookupError
                    for k in sel:
                        kp.pop(k, None)
                    st["sel"] = []
                    msg = f"Deleted {len(sel)} key(s)"
            else:
                if not Path(o["folder"].get()).is_dir():
                    raise ValueError("Pick the folder that holds your sounds.")
                status.config(text="Searching...")
                page.update()
                fixed, still = sd_relink(sounds, o["folder"].get())
                msg = f"Fixed {fixed} missing sound(s); {still} still missing"
        except (ValueError, LookupError) as e:
            edits.clear()
            edits.update(before[0])  # nothing half-done
            st["sel"] = before[1]
            draw()
            if isinstance(e, ValueError):
                messagebox.showerror("Can't do that", str(e))
            return
        commit(before, msg)

    def revert():
        if edits:
            before = snap()
            edits.clear()
            st["sel"] = []
            commit(before, "All unsaved changes thrown away")

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
        try:
            backup = sd_save(changed, {p.parents[2] for p in changed})
        except OSError as e:
            return messagebox.showerror("Save", f"Couldn't write the profile:\n{e}")
        sd_start()
        edits.clear()
        hist["undo"].clear()
        hist["redo"].clear()
        status.config(text=f"Saved {len(changed)} page(s); Stream Deck reopened. Backup: {backup}")
        list_multis()
        draw()

    apply_btn.config(command=apply)
    save_btn.config(command=save)
    tbtn["undo"].config(command=lambda: restore("undo", "redo", "Undone."))
    tbtn["redo"].config(command=lambda: restore("redo", "undo", "Redone."))
    tbtn["revert"].config(command=revert)
    ui_keys(page, {"<Control-z>": lambda: restore("undo", "redo", "Undone."),
                   "<Control-y>": lambda: restore("redo", "undo", "Redone."), "<Control-s>": save,
                   "<Control-c>": copy_key, "<Control-v>": paste_key, "<Delete>": lambda: delete_keys(st["sel"]),
                   "<Control-a>": lambda: select(bool), "<Escape>": lambda: select(lambda a: False)})
    prof_v.trace_add("write", on_prof)
    multi_v.trace_add("write", on_multi)
    page_v.trace_add("write", on_page)
    on_prof()


def streamdeck_tab(page, cfg, made):
    """The Stream Deck sub-app. made = files the Channel Mirror tab wrote this session. Returns a save() for cfg."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    sc = cfg.setdefault("streamdeck", {})
    sounds, keys = [], {}  # keys: 'col,row' (from 1) -> {"kind", "title"}
    cur = tk.StringVar(value="1,1")  # the deck key being edited
    st = {"lay": {}}
    audio_pat = " ".join(f"*{e}" for e in AUDIO_EXT)
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
    ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=12)
    ttk.Label(bar, text="Device").pack(side="left")
    ttk.Combobox(bar, textvariable=k["device"], values=tuple(devices), state="readonly", width=40).pack(
        side="left", padx=6)
    ttk.Label(bar, text="Columns").pack(side="left", padx=(8, 0))
    ttk.Spinbox(bar, textvariable=k["cols"], from_=1, to=16, width=3).pack(side="left", padx=4)
    ttk.Label(bar, text="Rows").pack(side="left")
    ttk.Spinbox(bar, textvariable=k["rows"], from_=1, to=16, width=3).pack(side="left", padx=4)
    ttk.Label(bar, text="Profile name").pack(side="left", padx=(12, 0))
    ttk.Entry(bar, textvariable=k["profile"], width=18).pack(side="left", padx=6)

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
    for c, h, w in zip(cols, ("Name", "Key", "Action", "Fade", "Vol", "Output", "File"), (130, 50, 105, 120, 45, 110, 240)):
        tree.heading(c, text=h)
        tree.column(c, width=w, stretch=c in ("file", "title"))
    ys = ttk.Scrollbar(tl, command=tree.yview)
    tree.config(yscrollcommand=ys.set)
    ys.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    tools = ttk.Frame(box)
    tools.pack(fill="x", pady=(8, 0))
    ttk.Label(box, text="Drag sounds onto a key to map them  -  double-click a cell to change it  -  right-click "
                        "for more  -  Del removes", style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

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
                        s["volume"], sd_out(s["output"]) or "default", s["path"]))
        tree.selection_set([i for i in sel if tree.exists(i)])
        draw()

    def draw():
        c_n, r_n = deck_size()
        try:
            st["lay"] = {f"{c + 1},{r + 1}": x for (c, r), x in sd_layout(sounds, keys, c_n, r_n).items()}
            status_note = ""
        except ValueError as e:
            st["lay"], status_note = {}, str(e)  # mid-edit conflict; shown, and Send reports it too
        kgrid.draw(c_n, r_n)
        if status_note:
            status.config(text=status_note)

    def tile(p0):
        pos = one(p0)
        kind, title, group = st["lay"].get(pos, ("", "", []))
        auto = bool(group) and not group[0]["key"]
        if pos == cur.get():
            bg, fg = UI["accent"], "#ffffff"
        else:
            bg, fg = (UI["auto"] if auto else UI["sound"] if group else UI["empty"]), (UI["text"] if group else UI["muted"])
        if not group:
            return pos, bg, fg
        label = "auto" if auto else kind.split()[0]
        return f"{title[:22]}\n{label}" + (f" x{len(group)}" if len(group) > 1 else ""), bg, fg

    def tip_for(pos):
        kind, title, group = st["lay"].get(pos, ("", "", []))
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
        status.config(text=f"Added {added} sound(s)" + (f" to key {key}" if key else "") + ".")
        return added

    def folder_sounds(title):
        f = filedialog.askdirectory(title=title)
        return [q for q in media_files([f]) if q.suffix.lower() in AUDIO_EXT] if f else []

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
            title_v.set(Path(files[0]).parent.name[:20])
        status.config(text=f"Key {pos}: {len(files)} sound(s) from {Path(files[0]).parent}")

    def files_to_key(pos=None):
        pos = pos or cur.get()
        pick_key(pos)
        files = filedialog.askopenfilenames(title=f"Sounds for key {pos}",
                                            filetypes=[("Audio", audio_pat), ("All files", "*.*")])
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
            if name == "key":
                val = val.strip()
                if val.lower() == "auto":
                    val = ""
                try:
                    sd_key(val, *deck_size())
                except ValueError as err:
                    return messagebox.showerror("Key", str(err))
                return assign([int(item)], val) if val else (s.update(key=""), show())
            if name == "volume":
                try:
                    val = int(val)
                    assert 0 <= val <= 100
                except (ValueError, AssertionError):
                    return messagebox.showerror("Volume", "Volume is a whole number from 0 to 100.")
            s["title" if name == "title" else name] = val
            show()
        if name == "mode":
            ui_cell_edit(tree, item, col, s["mode"], done, SD_MODES)
        elif name == "fade":
            ui_cell_edit(tree, item, col, s["fade"], done, SD_FADES)
        elif name == "output":
            ui_cell_edit(tree, item, col, s["output"] or SD_DEFAULT_OUT, done, sd_output_choices(), True)
        else:
            ui_cell_edit(tree, item, col, str(s[name] or ("auto" if name == "key" else "")), done)
    tree.bind("<Double-Button-1>", edit_cell)

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
                          (f"Remove {len(sel)} sound(s)   Del", remove)])
    tree.bind("<Button-3>", tree_menu)
    drag = {}

    def tpress(e):
        it = tree.identify_row(e.y)
        drag.clear()
        drag.update(x=e.x_root, y=e.y_root, item=it)
        if it and it in tree.selection() and not e.state & 0x0005:
            return "break"  # keep a multi-selection so it can be dragged as a group

    def tmotion(e):
        if drag.get("item") and abs(e.x_root - drag["x"]) + abs(e.y_root - drag["y"]) > 8:
            drag["moved"] = True
            tree.config(cursor="fleur")

    def trelease(e):
        tree.config(cursor="")
        d = dict(drag)
        drag.clear()
        if d.get("moved"):
            pos = kgrid.key_at(e.x_root, e.y_root)
            if pos:
                assign(picked(), one(pos))
        elif d.get("item") and len(tree.selection()) > 1 and not e.state & 0x0005 and d["item"] in tree.selection():
            tree.selection_set(d["item"])
    tree.bind("<ButtonPress-1>", tpress)
    tree.bind("<B1-Motion>", tmotion)
    tree.bind("<ButtonRelease-1>", trelease)

    def on_device(*_):
        _, _, c, r_ = devices[k["device"].get()]
        k["cols"].set(c), k["rows"].set(r_)

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

    for text, cmd, tip in (("Add files...", lambda: add(filedialog.askopenfilenames(
                                title="Select sounds", filetypes=[("Audio", audio_pat), ("All files", "*.*")])),
                            "Pick sound files"),
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
    for text, cmd in (("Add folder...", folder_to_key), ("Add files...", files_to_key),
                      ("Selected sounds here", lambda: assign(picked(), cur.get()) if picked() else
                       messagebox.showinfo("Assign", "Select sounds in the list first.")),
                      ("Clear key", clear_key)):
        ttk.Button(kbtns, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 4), expand=True,
                                                                             fill="x")
    apply_btn.config(command=apply)
    ttk.Button(runbar, text="Send to Stream Deck", style="Accent.TButton", command=send).pack(side="left")
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
    root.minsize(1100, 720)
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
    page, sd_page, ed_page = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
    nb.add(page, text="Channel Mirror")
    nb.add(sd_page, text="Stream Deck soundboard")
    nb.add(ed_page, text="Stream Deck editor")
    made = []  # files written this session, offered to the Stream Deck tab
    sd_save = streamdeck_tab(sd_page, cfg, made)
    sd_editor_tab(ed_page)
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

    try:
        nb.select(int(cfg.get("tab", 0)))
    except (tk.TclError, ValueError):
        pass

    def on_close():
        sd_save()
        cfg["geometry"] = root.geometry() if root.state() == "normal" else cfg.get("geometry", "")
        cfg["tab"] = nb.index(nb.select())
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
