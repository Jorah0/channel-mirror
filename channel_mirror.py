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
import weakref
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
VERSION = "2.2"
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
    if reg_key == UNINSTALL_KEY:  # channelmirror:// links open the installed app (not for the selftest's key)
        link_register(exe)
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
    if reg_key == UNINSTALL_KEY and str(app_dir) in (link_registered() or ""):
        link_unregister()  # links pointed at this install
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


def natural(p):
    """Sort key for file names in Explorer's order: track2 before track10, case ignored."""
    import re
    return [int(t) if t.isdecimal() else t.lower() for t in re.split(r"(\d+)", Path(p).name)]  # not isdigit: "²"


def sound_folders(folder):
    """[(name, sound files)] for a folder of folders: the sounds directly in it (named after it), then each
    subfolder's sounds, in name order. Folders without sounds are left out."""
    root = Path(folder)
    out = []
    for d in [root] + sorted((p for p in root.iterdir() if p.is_dir()), key=natural):
        try:
            fs = [q for q in media_files([d]) if q.suffix.lower() in AUDIO_EXT]
        except OSError:  # e.g. System Volume Information under a drive root: skipped
            continue
        if fs:
            out.append((d.name or d.drive or "Sounds", fs))  # a drive root has no name: "D:"
    return out


def media_files(paths):
    """Files stay as given; folders become every audio/video file directly inside them, in name order."""
    out = []
    for p in map(Path, paths):
        out += sorted((q for q in p.iterdir() if q.suffix.lower() in AUDIO_EXT + VIDEO_EXT), key=natural) \
            if p.is_dir() else [p]
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
SD_FOLDER, SD_PARENT = "com.elgato.streamdeck.profile.openchild", "com.elgato.streamdeck.profile.backtoparent"
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


_plugged: dict = {}


def sd_connected():
    """USB instance ids of plugged-in devices (upper case), e.g. USB\\VID_0FD9&PID_0084\\A00WA4121LT9RJ.
    Asking Windows takes ~2 s, so the answer is reused for a minute."""
    import time
    if _plugged and time.time() - _plugged["at"] < 60:
        return _plugged["ids"]
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-PnpDevice -PresentOnly).InstanceId"],
                           capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        ids = set(r.stdout.upper().split())
    except (OSError, subprocess.SubprocessError):
        ids = set()
    _plugged.update(ids=ids, at=time.time())
    return ids


def sd_devices(sd_dir=None, plugged=None):
    """Stream Decks found in the user's own profiles, connected ones first:
    {label: (model, device id, cols, rows)}. Device ids look like @(1)[vendor/product/serial] (USB ids, decimal)."""
    sd_dir = sd_dir or SD_DIR  # looked up now, so a folder picked in the Setup tab counts
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


def sd_profile_files(name, device, sounds, keys, folders=None):
    """({archive path: json}, {audio path: resource id}) for a one-page profile, in Stream Deck's export layout.
    folders = {"title", "per"}: instead of the key mapping, every sound gets its own key inside folders of `per`
    sounds (title, title 2...), whose folder keys fill the page in order."""
    model, dev_id, cols, rows = device
    new = sd_uid
    page, home, prof, res = new(), new(), new(), {}

    def play(s):
        path = str(Path(s["path"]).resolve())
        return sd_play(path, s["title"], s["mode"], s["fade"], s["fade_len"], s["volume"], s.get("output"),
                       res.setdefault(path, new()))

    actions, sub = {}, {}
    base = f"Profiles/{prof.upper()}.sdProfile"
    if folders:
        chunks = sd_folders(folders.get("title") or "Sounds", [play(s) for s in sounds], cols, rows,
                            per=folders.get("per"))
        if len(chunks) > cols * rows:
            raise ValueError(f"{len(sounds)} sounds need {len(chunks)} folders, but the {cols} x {rows} page has "
                             f"{cols * rows} keys: put more sounds in each folder")
        for k, (key, pid, pg) in zip(sd_free({}, cols, rows), chunks):
            actions[k] = key
            sub[f"{base}/Profiles/{pid.upper()}/manifest.json"] = pg
    else:
        for (c, r), (kind, title, group) in sd_layout(sounds, keys, cols, rows).items():
            if SD_KINDS[kind]:
                act = sd_wrap(kind, title, [play(s) for s in group])
            else:
                act = play(group[0])
                act["States"] = [{"Title": title}]
            actions[f"{c},{r}"] = act
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
        **sub,
    }
    return files, res


def sd_profile(dst, name, device, sounds, keys, folders=None):
    """Write a .streamDeckProfile (the Stream Deck app's own export format, audio files bundled inside).
    sounds: dicts with path, title, key, mode (SD_MODES), fade (SD_FADES), fade_len (s), volume (0-100), output.
    folders: see sd_profile_files."""
    import zipfile
    files, res = sd_profile_files(name, device, sounds, keys, folders)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, data in files.items():
            z.writestr(arc, json.dumps(data, indent=1))
        for p, rid in res.items():
            z.write(p, f"Resources/{rid}/{Path(p).name}")
    return Path(dst)


# --- editing the profiles already installed in the local Stream Deck app ---
def sd_profiles(sd_dir=None):
    """[(profile folder, its manifest)] for every installed profile."""
    sd_dir = sd_dir or SD_DIR
    out = []
    for top in sorted((sd_dir / "ProfilesV3").glob("*.sdProfile/manifest.json")):
        try:
            out.append((top.parent, json.loads(top.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            pass
    return out


def sd_pages(folder, manifest, unsaved=None):
    """[(label, page manifest file)]: the profile's pages in Stream Deck's order ("Page 1"...), then the pages
    behind folder keys ("Folder: <key name>"), which live beside them but aren't in the page list.
    unsaved = {page file: json} edits not written yet (a new folder's page may not exist on disk)."""
    unsaved = unsaved or {}
    pages = {p.parent.name.lower(): p for p in [*(folder / "Profiles").glob("*/manifest.json"), *map(Path, unsaved)]}
    listed = [i.lower() for i in (manifest.get("Pages") or {}).get("Pages") or [] if i.lower() in pages]
    names = {}
    for p in pages.values():  # folder keys point at their page through Settings.ProfileUUID
        try:
            for c in (unsaved.get(p) or json.loads(p.read_text(encoding="utf-8"))).get("Controllers") or []:
                for a in (c.get("Actions") or {}).values():
                    pid = str((a.get("Settings") or {}).get("ProfileUUID", "")).lower()
                    if a and a.get("UUID") == SD_FOLDER and pid in pages:
                        names[pid] = sd_title(a).replace("\n", " ") or pid[:8]
        except (OSError, ValueError, AttributeError):
            pass
    out, seen = [], {}
    for label, p in ([(f"Page {n}", pages[i]) for n, i in enumerate(listed, 1)]
                     + sorted((f"Folder: {nm}", pages[i]) for i, nm in names.items() if i not in listed)):
        seen[label] = seen.get(label, 0) + 1  # two folders can share a name: each label must pick one page
        out.append((label if seen[label] == 1 else f"{label} #{seen[label]}", p))
    return out


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


def sd_set_sound(sounds, mode=None, fade=None, fade_len=None, volume=None, step=None, output=None, scale=None):
    """Change Play Audio settings; None = leave as is. step = add to the current volume (-100..100);
    scale = multiply the current volume by this percentage (50 = half as loud a setting)."""
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
        if scale is not None:
            st["volume"] = max(0, min(100, round(int(st.get("volume", 100)) * float(scale) / 100)))
        if output is not None:
            st["outputType"] = sd_out(output)


# OBS mix targets (RMS dBFS): a mic peaking around -10 in OBS's meter averages about -16; effects sit a bit under the
# voice, music beds well under it. ponytail: RMS stands in for LUFS; close enough for a soundboard
# Target per kind of sound. These are the defaults; the user's own OBS levels (settings "obs_levels") replace them.
SD_OBS_DEFAULT = {"voice": -16.0, "effect": -20.0, "music / ambience": -30.0}
SD_LEVELS = dict(SD_OBS_DEFAULT)
SD_AUTO = "Auto: detect each sound (voice / effect / music)"
SD_TUNE = {SD_AUTO: None, "Everything at my voice level": "voice", "Everything at my effects level": "effect",
           "Everything at my music / ambience level": "music / ambience"}  # Tune choice -> kind (None = detect)
SD_TOL = 2.0  # dB: a sound already playing this close to its target is left as it is


def sd_set_levels(levels):
    """Use the user's OBS levels ({kind: dB}); anything missing or out of range (-60..0) keeps its default."""
    for kind, default in SD_OBS_DEFAULT.items():
        try:
            v = float((levels or {}).get(kind, default))
        except (TypeError, ValueError):
            v = default
        SD_LEVELS[kind] = v if -60 <= v <= 0 else default
    return dict(SD_LEVELS)
_SD_HEARD = {}


def sd_voiced(path, ch=0, sr=16000, fr=640):
    """Does it sound like a voice? Speech is voiced (a pitch, 70-400 Hz) for much of the time and that pitch moves.
    ponytail: two thresholds fitted on a labelled soundboard library; on clips it wasn't fitted on it splits voice
    from effect 70-80% right (misses: growls/grunts heard as effects, ringing hits/howls heard as voice). A misread
    costs 4 dB, which Check levels shows and a fixed preset overrides. Upgrade path: a trained classifier."""
    proc = subprocess.run(["ffmpeg", "-v", "error", "-t", "30", "-i", str(path), "-map", "0:a:0", "-af",
                           f"pan=mono|c0=c{ch}", "-ar", str(sr), "-f", "f32le", "-acodec", "pcm_f32le", "-"],
                          capture_output=True, creationflags=NO_WINDOW)
    x = np.frombuffer(proc.stdout, "<f4").astype(np.float64)
    k = len(x) // fr
    if k < 5:
        return False
    frames = x[:k * fr].reshape(k, fr)
    e = 10 * np.log10(np.maximum((frames ** 2).mean(1), 1e-12))
    if not (e > -50).any():
        return False
    loud = e > 10 * np.log10(np.mean(10 ** (e[e > -50] / 10))) - 20
    lo, hi, win, f0 = sr // 400, sr // 70, np.hanning(fr), []
    for i in np.flatnonzero(loud):
        ac = np.fft.irfft(np.abs(np.fft.rfft((frames[i] - frames[i].mean()) * win, 2 * fr)) ** 2)[:fr]
        if ac[0] > 0:
            lag = lo + int(np.argmax(ac[lo:hi] / ac[0]))
            if ac[lag] / ac[0] > 0.45:
                f0.append(sr / lag)
    if len(f0) < 4 or len(f0) < 0.3 * loud.sum():
        return False
    return float(np.std(12 * np.log2(np.array(f0) / np.median(f0)))) >= 1.5


def sd_listen(path):
    """Listen to a sound file once (cached per file version): {"level": its loudness in dB while it sounds, on its
    loudest channel (the auto source) with silence and quiet tails left out, or None if silent; "secs"; "kind":
    "voice" / "effect" / "music / ambience" (30 s or longer)}."""
    p = Path(path)
    key = (str(p), p.stat().st_mtime_ns)
    if key in _SD_HEARD:
        return _SD_HEARD[key]
    info = probe(p)
    n, sr = int(info["channels"]), int(info["sample_rate"])
    blk = max(sr // 50, 1)  # 20 ms
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:a:0", "-f", "f32le", "-acodec",
                             "pcm_f32le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    ms = []
    while chunk := proc.stdout.read(blk * n * 4 * 250):
        a = np.frombuffer(chunk, "<f4").reshape(-1, n)
        k = len(a) // blk
        if k:
            ms.append((a[:k * blk].astype(np.float64).reshape(k, blk, n) ** 2).mean(1))
    if proc.wait():
        raise RuntimeError(f"ffmpeg could not decode {p.name}")
    ms = np.concatenate(ms) if ms else np.zeros((0, n))
    ch = int(np.argmax(ms.sum(0))) if len(ms) else 0
    e = ms[:, ch]
    edb = 10 * np.log10(np.maximum(e, 1e-12))
    act = edb > -50
    level = None
    if act.sum() >= 5:
        act &= edb > 10 * np.log10(e[act].mean()) - 20  # gate out tails 20 dB under the body of the sound
        level = float(10 * np.log10(e[act].mean()))
    secs = len(e) * blk / sr
    kind = "music / ambience" if secs >= 30 else "voice" if level is not None and sd_voiced(p, ch) else "effect"
    _SD_HEARD[key] = {"level": level, "secs": secs, "kind": kind}
    return _SD_HEARD[key]


def sd_level_rows(sounds, heard, preset=SD_AUTO, tol=SD_TOL):
    """What tuning would do, per sound: {s, kind, level (file dB), now (dB at its volume), target, new (volume or
    None = leave), verdict}. preset: a SD_TUNE choice (SD_AUTO = target by detected kind). heard: {path: sd_listen}."""
    import math
    rows = []
    for s in sounds:
        se = s.get("Settings", {})
        h = heard.get(se.get("path", ""))
        vol = int(se.get("volume", 100))
        r = {"s": s, "kind": h["kind"] if h else "", "level": h and h["level"], "now": None, "target": None,
             "new": None, "verdict": "file missing" if not h else "silent"}
        rows.append(r)
        if not h or h["level"] is None:
            continue
        t = SD_LEVELS[SD_TUNE.get(preset) or h["kind"]]
        now = h["level"] + 20 * math.log10(max(vol, 1) / 100)
        new = max(1, min(100, round(100 * 10 ** ((t - h["level"]) / 20))))
        r.update(now=now, target=t)
        if abs(now - t) <= tol:
            r["verdict"] = "in range"
        elif new == vol:
            r["verdict"] = f"too quiet even at full volume ({t - now:.0f} dB under)"
        else:
            r["new"] = new
            r["verdict"] = (f"too {'loud' if now > t else 'quiet'}: volume {vol} -> {new}"
                            + (f" (still {t - h['level']:.0f} dB under)" if h["level"] < t - tol else ""))
    return rows


def sd_match_loudness(sounds, level_db, target=None):
    """Even out loudness: louder files get turned down so every sound plays as loud as the quietest one does now,
    or, with target (dB RMS, e.g. SD_LEVELS["effect"]), as loud as that. Volume tops out at 100, so files quieter than
    target play at full. level_db: {path: loudest channel RMS in dB}; sounds without a level are left alone."""
    import math
    # Stream Deck's volume is a linear gain: measured on Stream Deck 7.4, volume 50 / 25 / 32 played the same file
    # 6.02 / 12.04 / 9.90 dB quieter than volume 100, exactly 20*log10(volume/100)
    now = {id(s): level_db[s["Settings"]["path"]] + 20 * math.log10(max(int(s["Settings"].get("volume", 100)), 1) / 100)
           for s in sounds if s.get("Settings", {}).get("path") in level_db}
    if not now:
        return 0
    target = min(now.values()) if target is None else target
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
    """Keys with nothing on them, in reading order (a key saved as null / {} is empty too, as the grid shows it)."""
    return [f"{c},{r}" for r in range(rows) for c in range(cols) if not kp.get(f"{c},{r}")]


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


def sd_plays_like(files, like=None):
    """A Play Audio action per file, named after it, with the playback settings of `like` (a Play Audio action)."""
    se = (like or {}).get("Settings", {})
    pick = lambda t, i: t[i] if isinstance(i, int) and 0 <= i < len(t) else t[0]
    return [sd_play(f, Path(f).stem[:20], pick(SD_MODES, se.get("actionType")), pick(SD_FADES, se.get("fadeType")),
                    se.get("fadeLen", 1), se.get("volume", 100), se.get("outputType", "")) for f in files]


def sd_add_sounds(action, plays, kind="Random Action"):
    """A key with these sounds added: a Multi / Random Action takes them at the end (same object returned); a single
    sound becomes a <kind> holding it and then them, keeping its name and look."""
    import copy
    if action.get("UUID") in {u for u in SD_KINDS.values() if u}:
        if not action.get("Actions"):
            action["Actions"] = [{"Actions": []}]
        action["Actions"][0].setdefault("Actions", []).extend(plays)
        return action
    out = sd_wrap(kind, sd_title(action), [action] + list(plays))
    out["States"] = copy.deepcopy(action.get("States") or [{}])
    return out


def sd_fill(kp, plays, cols, rows, start="0,0"):
    """One key per sound, in order, on the free keys from `start` on: left to right, then the next row down (the way
    Stream Deck shows a page). Returns the sounds that didn't fit."""
    free = [k for k in sd_free(kp, cols, rows) if sd_order(k) >= sd_order(start)]
    for k, s in zip(free, plays):
        kp[k] = s
    return list(plays[len(free):])


def sd_order(key):
    """Sort key for 'col,row' keys in reading order: left to right, then the next row down."""
    c, r = map(int, key.split(","))
    return r, c


def sd_beside(kp, origin, cols, rows):
    """The free keys extra folders take: just right of `origin`, on along the rows, then from the top of the page."""
    free = sd_free(kp, cols, rows)
    after = [k for k in free if sd_order(k) > sd_order(origin)]
    return after + [k for k in free if k not in after]


def sd_folder(title, plays, cols, rows, per=None):
    """A new Stream Deck folder: (folder key, its page id, the page json, sounds that didn't fit). The page has the
    Parent Folder key top-left, then one key per sound in order (at most `per` of them, when given).
    The page is saved as Profiles/<ID>/manifest.json."""
    pid = sd_uid()
    kp = {"0,0": {"ActionID": sd_uid(), "LinkedTitle": True, "Name": "Parent Folder", "Resources": None,
                  "Settings": {}, "State": 0, "States": [{}], "UUID": SD_PARENT}}
    per = len(plays) if per is None else max(1, int(per))
    left = sd_fill(kp, plays[:per], cols, rows) + list(plays[per:])
    key = {"ActionID": sd_uid(), "LinkedTitle": True, "Name": "Create Folder",
           "Plugin": {"Name": "Create Folder", "UUID": SD_FOLDER, "Version": "1.0"}, "Resources": None,
           "Settings": {"ProfileUUID": pid}, "State": 0, "States": [{"Title": title}], "UUID": SD_FOLDER}
    return key, pid, {"Controllers": [{"Actions": kp, "Type": "Keypad"}], "Icon": "", "Name": ""}, left


def sd_clone_folders(action, pages, seen=None, ids=None):
    """Give a pasted key its own copies of the folder pages it opens (folders inside folders too), so it neither
    shares them with the original nor points at a page another profile doesn't have. Rewrites the key's
    Settings.ProfileUUID in place. pages = {page id: page json} of the source; returns {new page id: page json}.
    ids, when given, collects {new page id: the source page id} (to copy each page's icons)."""
    import copy
    seen = {} if seen is None else seen  # old id -> its copy's id: each folder copied once, every key to it rewired
    pid = str((action.get("Settings") or {}).get("ProfileUUID", "")).lower()
    if action.get("UUID") != SD_FOLDER or pid not in pages:
        return {}
    if pid in seen:  # a second key to the same folder, or a loop back out: open the copy already made
        action["Settings"]["ProfileUUID"] = seen[pid]
        return {}
    new = seen[pid] = sd_uid()  # reserved before going inside, so a loop finds it
    if ids is not None:
        ids[new] = pid
    page = sd_renew(copy.deepcopy(pages[pid]))
    action["Settings"]["ProfileUUID"] = new
    out = {new: page}
    for c in page.get("Controllers") or []:
        for a in (c.get("Actions") or {}).values():
            if a:
                out.update(sd_clone_folders(a, pages, seen, ids))
    return out


def sd_place(keys, dst_kp, cols, rows, anchor="0,0", picks=(), policy="next", keep_layout=True):
    """Where copied / moved keys land on a page: {source key: target key, or None = left out}.
    picks = target keys chosen in order, used first, one per key (keys in reading order). After them each key goes
    to anchor + its offset from the selection's top-left (keep_layout), or to the next free key from anchor.
    A target that's in use or off the deck: policy "next" = the next free key after it (wrapping to the top),
    "replace" = use it anyway (when on the deck), "skip" = leave that key out."""
    keys = sorted(keys, key=sd_order)
    taken = {k for k, a in dst_kp.items() if a}
    on = lambda k: 0 <= int(k.split(",")[0]) < cols and 0 <= int(k.split(",")[1]) < rows
    c0 = min((int(k.split(",")[0]) for k in keys), default=0)
    r0 = min((int(k.split(",")[1]) for k in keys), default=0)
    ac, ar = map(int, anchor.split(","))
    out = {}
    for i, k in enumerate(keys):
        if i < len(picks):
            want = picks[i]
        elif keep_layout:
            c, r = map(int, k.split(","))
            want = f"{ac + c - c0},{ar + r - r0}"
        else:
            want = None
        if want is not None and on(want) and (want not in taken or policy == "replace"):
            got = want
        elif want is not None and policy == "skip":
            got = None
        else:
            free = sd_free(dict.fromkeys(taken, 1), cols, rows)
            after = [x for x in free if (sd_order(x) > sd_order(want) if want else sd_order(x) >= sd_order(anchor))]
            got = next(iter(after + [x for x in free if x not in after]), None)
        out[k] = got
        if got:
            taken.add(got)
    return out


def sd_images(obj):
    """The icon files ("Images/x.png", relative to the page's folder) a key, a page or anything inside them shows."""
    out = set()
    if isinstance(obj, dict):
        for s in obj.get("States") if isinstance(obj.get("States"), list) else []:
            img = s.get("Image") if isinstance(s, dict) else None
            if isinstance(img, str) and img and ":" not in img and not img.startswith(("/", "\\")):
                out.add(img)
        for v in obj.values():
            out |= sd_images(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= sd_images(v)
    return out


def sd_reachable(roots, pages):
    """Page ids a profile can still open: `roots` and every page reached from them through folder keys.
    pages = {page id (lower-case): page json}."""
    seen, todo = set(), [str(r).lower() for r in roots]
    while todo:
        pid = todo.pop()
        if pid in seen or pid not in pages:
            continue
        seen.add(pid)
        for c in (pages[pid] or {}).get("Controllers") or []:
            for a in (c.get("Actions") or {}).values():
                if a and a.get("UUID") == SD_FOLDER:
                    todo.append(str((a.get("Settings") or {}).get("ProfileUUID", "")).lower())
    return seen


def sd_folders(title, plays, cols, rows, first=1, taken=(), per=None):
    """As many new folders as the sounds need: [(folder key, page id, page json)], each page filled in order.
    Named title, title 2, title 3...; first = the number to start at (to carry on after an existing folder),
    taken = names already in use, skipped; per = sounds per folder (default: as many as a page holds)."""
    if cols * rows < 2:
        raise ValueError("A folder page needs room for at least one sound beside its Parent Folder key")
    out, n, plays = [], first, list(plays)
    name = lambda i: title if i == 1 else f"{title} {i}"
    while plays or not out:
        while name(n) in taken:
            n += 1
        key, pid, page, plays = sd_folder(name(n), plays, cols, rows, per)
        out.append((key, pid, page))
        n += 1
    return out


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
    """Dropdown text -> the outputType Stream Deck stores: "" = its default device; a device name -> that
    device's Windows endpoint id, which is what Stream Deck saves and matches on (checked by picking a device in
    Stream Deck's own Output menu: it saved '{0.0.0.00000000}.{70df09e5-...}', not the name). Ids pass through."""
    value = (value or "").strip()
    if value == SD_DEFAULT_OUT:
        return ""
    return value if value.startswith("{") else sd_win_outputs().get(value, value)


def sd_out_name(value):
    """A saved outputType -> what to show: the device's name, or the raw id when that device isn't connected."""
    if not value:
        return "default"
    return next((n for n, i in sd_win_outputs().items() if i == value.lower()), value)


def sd_outputs(sd_dir=None):
    """Output device values Stream Deck itself has saved on any sound key (its exact format), most used first."""
    sd_dir = sd_dir or SD_DIR
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


_win_outputs: dict = {}  # playback device name -> Windows endpoint id


def sd_win_outputs():
    """This PC's playback devices: {name as Stream Deck lists it: endpoint id as Stream Deck saves it}."""
    if not _win_outputs:  # ponytail: asked once per run; restart the app after plugging in new speakers
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Get-PnpDevice -Class AudioEndpoint -PresentOnly | Where-Object InstanceId -like "
                                "'SWD\\MMDEVAPI\\{0.0.0.*' | ForEach-Object { $_.InstanceId + '|' + $_.FriendlyName }"],
                               capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)  # {0.0.0 = playback
            for line in r.stdout.splitlines():
                iid, _, name = line.strip().partition("|")
                if name and "\\" in iid:  # SWD\MMDEVAPI\{0.0.0.00000000}.{GUID} -> {0.0.0.00000000}.{guid}
                    _win_outputs[name.strip()] = iid.rsplit("\\", 1)[1].lower()
        except (OSError, subprocess.SubprocessError):
            pass
    return _win_outputs


def sd_output_choices():
    """Dropdown list: default, this PC's playback devices by name, then any other device saved in a profile
    (e.g. one not plugged in right now, shown by its id so it can still be picked)."""
    ids = set(sd_win_outputs().values())
    return ([SD_DEFAULT_OUT] + sorted(sd_win_outputs()) +
            [v for v in sd_outputs() if v.lower() not in ids and v not in sd_win_outputs()])


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
        # ponytail: Stream Deck ignores a polite close (it hides in the tray), so that wait is short;
        # it saves each change as it's made, so the forced close loses nothing
        for _ in range(20 if force else 4):
            if not sd_running():
                return True
            time.sleep(0.5)
    return False


def sd_start():
    """Reopen Stream Deck as its own process, so it keeps running whatever happens to this app."""
    if not SD_EXE.exists():
        return
    detached = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([str(SD_EXE)], creationflags=detached | 0x01000000, close_fds=True)  # + break away from job
    except OSError:
        subprocess.Popen([str(SD_EXE)], creationflags=detached, close_fds=True)


def sd_push(writes, folders, sd_dir=None, backups=None):
    """Get edited pages into Stream Deck: close it if it runs (it rewrites its profiles on exit), back up, write,
    read every file back to check it, reopen. Slow (Stream Deck takes seconds to close) - run it off the UI thread.
    Returns the backup zip; raises RuntimeError / OSError when something didn't work."""
    if sd_running() and not sd_stop():
        raise RuntimeError("Couldn't close Stream Deck. Close it yourself and try again.")
    try:
        backup = sd_save(writes, folders, sd_dir, backups)
        bad = [p for p, d in writes.items() if (Path(p).read_bytes() if isinstance(d, bytes) else
                                                json.loads(Path(p).read_text(encoding="utf-8"))) != d]
        if bad:
            raise RuntimeError(f"{len(bad)} page(s) didn't read back as written. Backup: {backup}")
        return backup
    finally:
        sd_start()


def sd_save(writes, folders, sd_dir=None, backups=None):
    """Zip each touched profile folder into backups (restore = unzip into ProfilesV3), then write the json files.
    Call while Stream Deck is closed. Returns the backup zip."""
    sd_dir, backups = Path(sd_dir or SD_DIR), Path(backups or SD_BACKUPS)
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
        if isinstance(data, bytes):  # a key's icon copied with it
            Path(path).write_bytes(data)
        else:
            Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")
    return zpath


def sd_install(name, device, sounds, keys, sd_dir=None, folders=None):
    """{file: json} that puts a new soundboard profile straight into Stream Deck's profile folder (no import prompt).
    Installed profiles play from each sound's own path, so no audio is copied. folders: see sd_profile_files."""
    files, _ = sd_profile_files(name, device, sounds, keys, folders)
    root = (sd_dir or SD_DIR) / "ProfilesV3"
    return {root / arc.split("/", 1)[1]: data for arc, data in files.items() if arc.startswith("Profiles/")}


# --- VTube Studio backgrounds: copy files in, a ChangeBackground hotkey each, a Stream Deck key each ---
VTS_EXT = (".png", ".jpg", ".jpeg", ".mp4")  # what VTube Studio shows as backgrounds (pictures, mp4 video)
VTS_APPID = "1325860"  # VTube Studio on Steam
SD_VTS = {"Name": "VTubeStudio", "UUID": "dev.cazzar.streamdeck.vtubestudio", "Version": "3.1.0"}  # Cazzar's plugin
SD_VTS_HOTKEY = "dev.cazzar.vtubestudio.triggerhotkey"
# a ChangeBackground hotkey as VTube Studio itself saves one (its defaults; HotkeyID / File / Name filled in)
VTS_HOTKEY = {
    "HotkeyID": "", "Name": "", "Action": "ChangeBackground", "File": "", "Folder": "", "AutoCreated": False,
    "Position": {"X": 0.0, "Y": 0.0, "Z": 0.0, "Rotation": 0.0},
    "ColorOverlay": {"On": False, "IsStaticColor": False, "Display": -1, "WindowName": "", "IncludeLeft": False,
                     "IncludeMid": False, "IncludeRight": False, "BaseValue": 0, "OverlayValue": 0, "Smoothing": 0,
                     "IncludeItems": False, "StaticColor": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0}},
    "ColorScreenMultiplyPreset": {"ArtMeshMultiplyAndScreenColors": []},
    "HandGestureSettings": {"GestureLeft": "", "GestureRight": "", "GestureCombinator": "AND",
                            "AllowMirroredGesture": False, "DeactivateExpWhenGestureNotDetected": False,
                            "SecondsUntilDetection": 0.5, "SecondsDetected": 0.0, "PercentDetected": 0.0},
    "LoadModelSettings": {"LoadAtCurrentPosition": True},
    "TwitchTriggers": {
        "Active": False, "CooldownActive": False, "CooldownSeconds": 30.0, "ResetActive": False,
        "HideModelResetDialog": False, "Active_GiftSubTrigger": False, "Active_BitTrigger": False,
        "Active_RedeemTrigger": False, "Active_PowerUpTrigger": False, "Active_TextCommandTrigger": False,
        "Active_SubTrigger": False, "Active_FollowTrigger": False, "Active_RaidTrigger": False,
        "Active_ShoutoutTrigger": False, "Active_AdbreakTrigger": False, "Trigger_TextCommandTrigger": "",
        "Trigger_Redeem_Name": "", "Trigger_Redeem_ID": "", "Trigger_PowerUp_Name": "", "Trigger_PowerUp_ID": "",
        "UseTextTriggerUserTypeRestriction": False,
        "RestrictTextTriggerTo": {"Allowed_You": True, "Allowed_Subs": False, "Allowed_Mods": False,
                                  "Allowed_VIPs": False, "Allowed_Artists": False, "Allowed_UserNames": False,
                                  "UserNames": [], "Allowed_UserIDs": False, "UserIDs": []},
        "AllowRepeatedFollow": False, "Trigger_GiftSubTrigger": {"Min": 1.0, "Max": 100.0},
        "Trigger_BitTrigger": {"Min": 100.0, "Max": 3000.0}},
    "Triggers": {"Trigger1": "", "Trigger2": "", "Trigger3": "", "ScreenButton": -1},
    "SoundConfig": {"SoundActive": False, "StopWhenInactive": False, "StopFadeOutSeconds": 2.0, "SoundSlots": []},
    "IsGlobal": True, "IsActive": True, "Minimized": False, "StopsOnLastFrame": False, "DeactivateAfterKeyUp": False,
    "OnlyLoadOneRandomItem": False, "DeactivateAfterSeconds": False, "DeactivateAfterSecondsAmount": 10.0,
    "FadeSecondsAmount": 0.5, "OnScreenHotkeyColor": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}}


VTS_ASSETS = None  # the install picked in the Setup tab (None = found in the Steam libraries)
VTS_BACKUPS = None  # where model files are backed up (None = beside the downloaded ffmpeg)


def vts_backups():
    """Folder for a copy of each model file before Channel Mirror adds hotkeys to it."""
    return Path(VTS_BACKUPS) if VTS_BACKUPS else FFMPEG_DIR.parent / "VTube Studio backups"


def vts_assets():
    """VTube Studio's StreamingAssets folders, from every Steam library on this PC (usually one)."""
    import re
    steam = Path(os.environ.get("ProgramFiles(x86)") or "C:/Program Files (x86)") / "Steam"
    libs = [steam]
    try:
        vdf = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        libs += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf)]
    except OSError:
        pass
    out = []
    for lib in libs:
        a = lib / "steamapps" / "common" / "VTube Studio" / "VTube Studio_Data" / "StreamingAssets"
        if a.is_dir() and a not in out:
            out.append(a)
    return out


def vts_models(assets):
    """[(name, its .vtube.json file, ModelID)] of the models in a StreamingAssets folder, by name."""
    out = []
    for f in sorted((Path(assets) / "Live2DModels").rglob("*.vtube.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
            out.append((d.get("Name") or f.name[:-len(".vtube.json")], f, d.get("ModelID", "")))
        except (OSError, ValueError):
            pass
    dup = {n for n, _, _ in out if sum(1 for m in out if m[0] == n) > 1}
    out = [(f"{n} ({f.parent.name})" if n in dup else n, f, mid) for n, f, mid in out]  # same name: say which
    return sorted(out, key=lambda m: natural(m[0]))


def vts_last_model(assets):
    """The name of the model VTube Studio loaded last (its model_history.json), or "" if unknown."""
    try:
        h = json.loads((Path(assets) / "Config" / "model_history.json").read_text(encoding="utf-8-sig"))
        f = Path(h["HistoryMainModels"][0]["ModelFilePath"])
        return next((n for n, mf, _ in vts_models(assets) if mf.resolve() == f.resolve()), "")
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return ""


def vts_files(paths):
    """The background files among picked files / folders (a folder: the files directly in it, in name order)."""
    out = []
    for p in map(Path, paths):
        for f in (sorted((q for q in p.iterdir() if q.is_file()), key=natural) if p.is_dir() else [p]):
            if f.suffix.lower() in VTS_EXT and f.is_file():
                out.append(f)
    return out


def vts_copy(files, bg_dir, dry=False):
    """Copy backgrounds into VTube Studio's Backgrounds folder; returns the name each is known by there (its file name
    without extension, which hotkeys refer to). A file already there is reused; a different file with the same name
    is kept apart as "name (2)" - nothing in the folder is ever overwritten. dry = only work out the names."""
    import filecmp
    bg_dir = Path(bg_dir)
    if not dry:
        bg_dir.mkdir(parents=True, exist_ok=True)
    there = [(q.stem, q) for q in bg_dir.iterdir() if q.is_file()] if bg_dir.is_dir() else []  # (name, its file)
    names = []
    for f in map(Path, files):
        n = 1
        while True:
            name = f.stem if n == 1 else f"{f.stem} ({n})"
            same = [q for nm, q in there if nm.lower() == name.lower()]
            if any(q.stat().st_size == f.stat().st_size and filecmp.cmp(q, f, shallow=False) for q in same):
                break  # this very file is there already (or goes in earlier in this batch)
            if not same:
                dst = bg_dir / f"{name}{f.suffix.lower()}"
                if not dry:
                    shutil.copy2(f, dst)
                there.append((name, f if dry else dst))
                break
            n += 1
        names.append(name)
    return names


def vts_hotkeys(model, names):
    """A ChangeBackground hotkey on the model (its .vtube.json data, changed in place) for each background name;
    one that already exists for a name is reused. Returns ({name: HotkeyID}, how many were added)."""
    import copy
    import uuid
    hk = model.setdefault("Hotkeys", [])
    have = {h.get("File"): h.get("HotkeyID") for h in hk if h.get("Action") == "ChangeBackground"}
    ids, added = {}, 0
    for name in names:
        if name not in have:
            h = copy.deepcopy(VTS_HOTKEY)
            h.update(HotkeyID=uuid.uuid4().hex, File=name, Name=name)
            hk.append(h)
            have[name] = h["HotkeyID"]
            added += 1
        ids[name] = have[name]
    return ids, added


def sd_vts_key(model_id, hotkey_id, title):
    """A Stream Deck key (Cazzar's VTube Studio plugin) that triggers that VTube Studio hotkey."""
    return {"ActionID": sd_uid(), "LinkedTitle": True, "Name": "Trigger Hotkey", "Plugin": dict(SD_VTS),
            "Resources": None, "Settings": {"modelId": model_id, "hotkeyId": hotkey_id, "showName": True},
            "State": 0, "States": [{"Title": title}], "UUID": SD_VTS_HOTKEY}


def vts_missing(model, bg_dir):
    """The backgrounds the model's Change Background hotkeys name that aren't in the Backgrounds folder."""
    bg_dir = Path(bg_dir)
    there = {q.stem.lower() for q in bg_dir.iterdir() if q.is_file()} if bg_dir.is_dir() else set()
    return sorted({h["File"] for h in model.get("Hotkeys") or [] if h.get("Action") == "ChangeBackground"
                   and h.get("File") and h["File"].lower() not in there}, key=natural)


def vts_find(names, folders):
    """{name: file} for background names found in these folders (and every folder inside them; ones that can't be
    read are skipped): a png / jpg / mp4 whose file name without extension is the name, any case. First found wins."""
    want = {n.lower(): n for n in names}
    found = {}
    for folder in folders:
        for top, dirs, fs in os.walk(folder, onerror=lambda e: None):
            dirs.sort(key=natural)
            for f in sorted(fs, key=natural):
                p = Path(top) / f
                n = want.get(p.stem.lower())
                if n and n not in found and p.suffix.lower() in VTS_EXT:
                    found[n] = p
    return found


def vts_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq VTube Studio.exe", "/NH"], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    return "vtube studio.exe" in r.stdout.lower()


# --- links: channelmirror:// links on this PC, and sending files between devices on the home network ---
LINK_SCHEME = "channelmirror"
LINK_KEY = r"Software\Classes\channelmirror"
LINK_TARGETS = {"import": "Stream Deck keys (Import to folders)", "vts": "VTube Studio backgrounds",
                "soundboard": "Stream Deck soundboard (new profile)", "mirror": "Channel Mirror (split channels)"}
LINK_EXT = tuple(dict.fromkeys(AUDIO_EXT + VIDEO_EXT + (".png", ".jpg", ".jpeg", ".gif")))
LINK_PORT, LINK_HANDOVER = 8765, 47613  # network pairing port; this PC only: a link handed to the open app
LINK_MAX = 2 * 1024 ** 3  # per file
LINK_INBOX = FFMPEG_DIR.parent / "Incoming"


def link_make(target, files=(), urls=()):
    """A channelmirror:// link that opens the app with these files (paths on this PC) / web addresses for target."""
    from urllib.parse import urlencode
    q = [("to", target)] + [("file", str(Path(f))) for f in files] + [("url", u) for u in urls]
    return f"{LINK_SCHEME}://open?{urlencode(q)}"


def link_parse(link):
    """{"to", "files": [Path], "urls": [str]} from a channelmirror:// link; ValueError for anything else."""
    from urllib.parse import parse_qs, urlsplit
    u = urlsplit(str(link).strip())
    if u.scheme.lower() != LINK_SCHEME:
        raise ValueError(f"Not a {LINK_SCHEME}:// link")
    q = parse_qs(u.query)
    to = (q.get("to") or [""])[0]
    if to not in LINK_TARGETS:
        raise ValueError(f"Unknown destination '{to}' (one of: {', '.join(LINK_TARGETS)})")
    import re
    raw = q.get("file", [])
    if any(not re.match(r"^[A-Za-z]:[\\/]", f) for f in raw):  # a drive on this PC - never a network share
        raise ValueError("Files in a link need their full path on this PC (like C:\\Sounds\\a.mp3)")
    files = [Path(f) for f in raw]
    if any(f.suffix.lower() not in LINK_EXT for f in files):
        raise ValueError("Links only carry sound, video and picture files")
    urls = q.get("url", [])
    if len(files) > 200 or len(urls) > 20:
        raise ValueError("Too many files in one link")
    if any(urlsplit(x).scheme.lower() not in ("http", "https") for x in urls):
        raise ValueError("Only http / https addresses can be downloaded")
    return {"to": to, "files": files, "urls": urls}


def link_args(argv):
    """The channelmirror:// link the app was started with (the first one), or None. When there is one, nothing else
    on the command line is used - a link can't add start-up options or files of its own."""
    return next((a for a in argv if str(a).lower().startswith(f"{LINK_SCHEME}:")), None)


def link_register(exe, key=LINK_KEY):
    """Make channelmirror:// links open this exe (per user, no admin)."""
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:Channel Mirror link")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{Path(exe)}" "%1"')


def link_registered(key=LINK_KEY):
    """The command channelmirror:// links run, or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key + r"\shell\open\command") as k:
            return winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None


def link_unregister(key=LINK_KEY):
    import winreg
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key + sub)
        except OSError:
            pass


def link_safe_name(name):
    """A received file's name made safe: no folders, no characters Windows won't take, an allowed type only."""
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1].strip().strip(".")
    stem, dot, ext = base.rpartition(".")
    if not dot or not stem or f".{ext.lower()}" not in LINK_EXT:
        raise ValueError(f"'{name}' isn't a sound, video or picture file")
    import re
    stem = "".join(c if c.isalnum() or c in " -_()[]" else "_" for c in stem)[:120]
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)", stem.strip()):  # Windows device names
        stem = "_" + stem
    return f"{stem}.{ext.lower()}"


def link_private(ip):
    """True for addresses on a home network or this PC (the only ones allowed to connect)."""
    import ipaddress
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    this_net = a.version == 4 and a in ipaddress.ip_network("0.0.0.0/8")  # "this network": not a real device
    return a.is_loopback or (a.is_private and not (a.is_link_local or a.is_reserved or a.is_unspecified
                                                   or a.is_multicast or this_net))


def link_public_network():
    """True when Windows has a connected network marked Public (cafe / hotel Wi-Fi): receiving isn't safe there."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-NetConnectionProfile).NetworkCategory"],
                           capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        return "public" in r.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def link_noproxy():
    """A URL opener that never goes through a proxy (this PC / the home network only)."""
    import urllib.request
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def link_lan_ip():
    """This PC's address on the home network (for the pairing link)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))  # nothing is sent: this only picks the network interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


LINK_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,
initial-scale=1"><title>Send to Channel Mirror</title><style>body{font:16px Segoe UI,sans-serif;max-width:560px;
margin:24px auto;padding:0 16px;background:#f3f4f6;color:#1f2937}h1{font-size:22px}label{display:block;margin:14px 0
4px;font-weight:600}select,input,button{font:inherit;width:100%;padding:8px;box-sizing:border-box}button{margin-top:18px;
background:#2563eb;color:#fff;border:0;border-radius:6px;padding:12px}#log{margin-top:14px;white-space:pre-wrap}
</style></head><body><h1>Send to Channel Mirror</h1><p>Files go to the PC running Channel Mirror; they're placed only
after it's accepted there.</p><label>Files (sounds, videos, pictures)</label><input id="f" type="file" multiple>
<label>Where they go</label><select id="t">__TARGETS__</select><label>This device's name</label>
<input id="n" value="My phone"><button id="go">Send</button><div id="log"></div><script>
const code="__CODE__", log=m=>document.getElementById('log').textContent=m;
document.getElementById('go').onclick=async()=>{const fs=[...document.getElementById('f').files];if(!fs.length)
return log('Pick files first.');const t=document.getElementById('t').value,b=Date.now().toString(36),
n=encodeURIComponent(document.getElementById('n').value);let i=0;for(const f of fs){log('Sending '+(++i)+' of '
+fs.length+': '+f.name);const r=await fetch('/upload?code='+code+'&batch='+b+'&target='+t+'&name='+
encodeURIComponent(f.name),{method:'POST',body:f});if(!r.ok)return log('Not sent: '+await r.text())}
const r=await fetch('/done?code='+code+'&batch='+b+'&target='+t+'&from='+n,{method:'POST'});
log(r.ok?'Sent '+fs.length+' file(s). Accept them on the PC.':'Not sent: '+await r.text())};</script></body></html>"""


class LinkServer:
    """Receives files from other devices on the home network: an upload page (GET /?code=), POST /upload (one file,
    streamed to the holding folder), POST /done (the batch is complete: on_batch(info) is called, from the server's
    thread). Every request needs the pairing code and a home-network address; only sound / video / picture files,
    up to LINK_MAX each. host="0.0.0.0" listens on the network; port 0 picks a free port (self.port)."""

    MAX_BATCHES, MAX_FILES, MAX_PENDING, KEEP = 5, 200, 4 * 1024 ** 3, 15 * 60  # waiting batches / bytes / secs

    def __init__(self, port, code, inbox, on_batch, host=None):
        import hmac
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import parse_qs, urlsplit
        server = self
        self.code, self.inbox, self.batches = str(code), Path(inbox), {}
        self.lock, self.fails, self.started, self.sizes = threading.Lock(), {}, {}, {}
        host = link_lan_ip() if host is None else host  # the home-network address only, not every adapter

        def tidy(now):
            """Batches never finished within KEEP seconds are deleted."""
            for b in [b for b, t0 in server.started.items() if now - t0 > server.KEEP]:
                for f in server.batches.pop(b, []):
                    Path(f).unlink(missing_ok=True)
                server.started.pop(b, None)
                server.sizes.pop(b, None)

        class Handler(BaseHTTPRequestHandler):
            timeout = 30  # a stalled sender is dropped

            def log_message(self, *a):  # quiet
                pass

            def reply(self, status, text, kind="text/plain; charset=utf-8"):
                body = text.encode()
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def check(self):
                u = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                ip, now = self.client_address[0], time.time()
                with server.lock:
                    tidy(now)
                    n, until = server.fails.get(ip, (0, 0))
                    locked = until > now or server.fails.get("*", (0, 0))[1] > now
                if not link_private(ip):
                    self.reply(403, "Only devices on this home network can send.")
                elif locked:
                    self.reply(429, "Too many wrong codes - wait a minute, then use the link Channel Mirror shows.")
                elif not hmac.compare_digest(q.get("code", "").encode("utf-8", "replace"), server.code.encode()):
                    with server.lock:  # 5 wrong from one device, or 30 from anywhere: shut out for a minute
                        n += 1
                        server.fails[ip] = (n, now + 60 if n >= 5 else until)
                        total = sum(m for k, (m, t) in server.fails.items() if k != "*")
                        if total >= 30:
                            server.fails["*"] = (0, now + 60)
                    self.reply(403, "Wrong pairing code - open the link Channel Mirror shows.")
                else:
                    return u.path, q
                return None, None

            def do_GET(self):
                path, q = self.check()
                if path == "/":
                    opts = "".join(f'<option value="{k}">{v}</option>' for k, v in LINK_TARGETS.items())
                    self.reply(200, LINK_PAGE.replace("__TARGETS__", opts).replace("__CODE__", server.code),
                               "text/html; charset=utf-8")
                elif path:
                    self.reply(404, "Not found")

            def do_POST(self):
                path, q = self.check()
                if not path:
                    return
                batch = "".join(c for c in q.get("batch", "") if c.isalnum())[:40]
                if not batch or q.get("target") not in LINK_TARGETS:
                    return self.reply(400, "Missing batch or destination")
                if path == "/upload":
                    try:
                        name = link_safe_name(q.get("name", ""))
                        size = int(self.headers.get("Content-Length", -1))
                        if not 0 <= size <= LINK_MAX:
                            raise ValueError("too big" if size > LINK_MAX else "no size given")
                    except ValueError as e:
                        return self.reply(400, f"Not accepted: {e}")
                    with server.lock:  # limits on what may wait here for an answer
                        if batch not in server.batches and len(server.batches) >= server.MAX_BATCHES:
                            return self.reply(429, "Busy - accept or decline what's waiting on the PC first")
                        if len(server.batches.get(batch, [])) >= server.MAX_FILES:
                            return self.reply(400, "Too many files in one go")
                        if sum(server.sizes.values()) + size > server.MAX_PENDING:
                            return self.reply(429, "Too much waiting to be accepted")
                        server.inbox.mkdir(parents=True, exist_ok=True)
                        if shutil.disk_usage(server.inbox).free < size + 1024 ** 3:
                            return self.reply(507, "Not enough free disk space on the PC")
                        server.batches.setdefault(batch, [])
                        server.started.setdefault(batch, time.time())
                        server.sizes[batch] = server.sizes.get(batch, 0) + size
                    folder = server.inbox / f"b{batch}"  # never a Windows device name
                    folder.mkdir(parents=True, exist_ok=True)
                    n = 1
                    while True:  # a new file only: two uploads of the same name can't overwrite each other
                        dst = folder / (name if n == 1 else f"{Path(name).stem} ({n}){Path(name).suffix}")
                        try:
                            out = open(dst, "xb")
                            break
                        except FileExistsError:
                            n += 1
                    left = size
                    try:
                        with out:
                            while left:
                                chunk = self.rfile.read(min(left, 1 << 20))
                                if not chunk:
                                    break
                                out.write(chunk)
                                left -= len(chunk)
                    except OSError:
                        left = left or 1
                    if left:
                        dst.unlink(missing_ok=True)
                        return self.reply(400, "The file didn't arrive whole")
                    with server.lock:
                        server.batches.setdefault(batch, []).append(dst)
                    return self.reply(200, "ok")
                if path == "/done":
                    with server.lock:
                        files = server.batches.pop(batch, [])
                        server.started.pop(batch, None)
                        server.sizes.pop(batch, None)
                    if not files:
                        return self.reply(400, "Nothing arrived in that batch")
                    self.reply(200, "ok")
                    who = "".join(c for c in q.get("from", "") if c.isprintable())[:60] or self.client_address[0]
                    on_batch({"batch": batch, "target": q["target"], "files": files, "from": who,
                              "address": self.client_address[0], "time": time.strftime("%H:%M:%S")})
                    return
                self.reply(404, "Not found")
        ThreadingHTTPServer.allow_reuse_address = False
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        """Stop listening; whatever arrived and wasn't accepted is deleted."""
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.inbox, ignore_errors=True)


def link_pair_url(ip, port, code):
    return f"http://{ip}:{port}/?code={code}"


def link_send(pair, files, target, device):
    """Send files to another Channel Mirror (its pairing link); returns how many were sent. Raises OSError /
    ValueError with the reason (wrong code, not a home-network address, a file it won't take...)."""
    import time
    import urllib.request
    from urllib.parse import parse_qs, urlsplit
    u = urlsplit(pair.strip())
    code = (parse_qs(u.query).get("code") or [""])[0]
    if u.scheme != "http" or not u.hostname or not code:
        raise ValueError("That isn't a pairing link (it looks like http://192.168.x.x:8765/?code=123456)")
    if not link_private(u.hostname):
        raise ValueError("Pairing links only work on the home network")
    from urllib.parse import urlencode
    base, batch, web = f"http://{u.netloc}", f"{int(time.time() * 1000):x}", link_noproxy()
    for f in map(Path, files):
        link_safe_name(f.name)  # refused here already if the other side wouldn't take it
        with open(f, "rb") as fh:
            q = urlencode({"code": code, "batch": batch, "target": target, "name": f.name})
            web.open(urllib.request.Request(f"{base}/upload?{q}", data=fh, method="POST",
                                            headers={"Content-Length": str(f.stat().st_size)}), timeout=60).read()
    q = urlencode({"code": code, "batch": batch, "target": target, "from": device})
    web.open(urllib.request.Request(f"{base}/done?{q}", data=b"", method="POST"), timeout=30).read()
    return len(files)


def link_token():
    """The secret the open app and a newly clicked link share (so other programs can't hand links over)."""
    import secrets
    f = FFMPEG_DIR.parent / "link.token"
    try:
        t = f.read_text().strip()
        if len(t) >= 32:
            return t
    except OSError:
        pass
    f.parent.mkdir(parents=True, exist_ok=True)
    t = secrets.token_hex(24)
    tmp = f.with_name(f"link.token.{secrets.token_hex(4)}")
    tmp.write_text(t)
    os.replace(tmp, f)  # never half-written
    return f.read_text().strip()


def link_handover(link, port=LINK_HANDOVER):
    """Give a clicked channelmirror:// link to the Channel Mirror that's already open; False if none is."""
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/link", data=str(link).encode(), method="POST",
                                     headers={"X-Token": link_token()})
        return link_noproxy().open(req, timeout=3).status == 200
    except OSError:
        return False


def link_handover_serve(on_link, port=LINK_HANDOVER):
    """While the app is open: take links handed over by link_handover (this PC only, with the token).
    on_link(text) is called from the server's thread. Returns the server (shutdown() to stop) or None if taken."""
    import hmac
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    token = link_token()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                size = 0
            ok = (self.path == "/link" and hmac.compare_digest(
                self.headers.get("X-Token", "").encode("utf-8", "replace"), token.encode()) and 0 < size < 100_000)
            if ok:
                on_link(self.rfile.read(int(self.headers["Content-Length"])).decode(errors="replace"))
            self.send_response(200 if ok else 403)
            self.end_headers()
    try:
        ThreadingHTTPServer.allow_reuse_address = False
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:  # another copy has it
        return None
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def link_fetch(url, folder):
    """Download a web address from a link into folder (a sound / video / picture, up to LINK_MAX); the file."""
    import socket
    import urllib.request
    from urllib.parse import unquote, urlsplit

    def public(u):
        p = urlsplit(u)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ValueError("only http / https downloads")
        for *_, addr in socket.getaddrinfo(p.hostname, p.port or 443):
            if link_private(addr[0]) or addr[0].startswith(("169.254.", "0.", "fe80")):
                raise ValueError(f"{p.hostname} is on this PC / network - links only download from the internet")

    class Check(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            public(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    public(url)
    name = link_safe_name(unquote(urlsplit(url).path.rsplit("/", 1)[-1]))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / name
    req = urllib.request.Request(url, headers={"User-Agent": "ChannelMirror"})
    with urllib.request.build_opener(Check).open(req, timeout=60) as r, open(dst, "wb") as out:
        got = 0
        while chunk := r.read(1 << 20):
            got += len(chunk)
            if got > LINK_MAX:
                raise ValueError("too big")
            out.write(chunk)
    return dst


# --- screen recorder: an area of a monitor -> a video file, through ffmpeg's Windows screen grabber ---
def rec_monitors():
    """[(label, left, top, width, height, app rect)] of the monitors: real pixels on the desktop (what ffmpeg
    records; the main one at 0,0, others can be negative), left one first. app rect = the same monitor as this
    app's windows see it: the app is "system DPI aware", so a monitor at a different scaling looks bigger/smaller."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32

    class Info(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    def monitors():
        found = {}

        def each(h, _dc, _r, _d):
            mi = Info()
            mi.cbSize = ctypes.sizeof(mi)
            u.GetMonitorInfoW(h, ctypes.byref(mi))
            r = mi.rcMonitor
            found[mi.szDevice] = (r.left, r.top, r.right - r.left, r.bottom - r.top, bool(mi.dwFlags & 1))
            return 1
        proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                  wintypes.LPARAM)(each)
        u.EnumDisplayMonitors(None, None, proc, 0)
        return found
    app = monitors()
    real = app
    try:  # real pixels: this thread per-monitor aware for a moment
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        old = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        if old:
            try:
                real = monitors()
            finally:
                u.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
    except AttributeError:  # older Windows: one scaling for all
        pass
    rows = sorted((r[:4], r[4], app.get(dev, r)[:4]) for dev, r in real.items())
    return [(f"Monitor {i}{' (main)' if main else ''}: {w} x {h} at {x},{y}", x, y, w, h, a)
            for i, ((x, y, w, h), main, a) in enumerate(rows, 1)]


def rec_to_app(mon, x, y):
    """A desktop point in real pixels -> where this app's windows put it (see rec_monitors)."""
    _, mx, my, mw, mh, (ax, ay, aw, ah) = mon
    return round(ax + (x - mx) * aw / mw), round(ay + (y - my) * ah / mh)


def rec_from_app(mon, x, y):
    """A point in this app's window coordinates -> real desktop pixels on that monitor."""
    _, mx, my, mw, mh, (ax, ay, aw, ah) = mon
    return round(mx + (x - ax) * mw / aw), round(my + (y - ay) * mh / ah)


def rec_overlay(win, clickthrough=True):
    """Make a Tk window an overlay: no taskbar button; left out of screen recordings (Windows 10 2004+), so the
    outline and controls never show up in the video; clickthrough = clicks go to what's underneath.
    Returns whether Windows agreed to leave it out of recordings (False before Windows 10 2004)."""
    import ctypes
    u = ctypes.windll.user32
    win.update_idletasks()
    hwnd = int(win.wm_frame(), 16)
    GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80000, 0x20, 0x80, 0x40000
    style = (u.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW | WS_EX_LAYERED) & ~WS_EX_APPWINDOW
    u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT if clickthrough else style)
    return bool(u.SetWindowDisplayAffinity(hwnd, 0x11))  # WDA_EXCLUDEFROMCAPTURE


def rec_area(mon, x, y, w, h):
    """An area given relative to a monitor (pixels from its top-left) -> (left, top, width, height) on the desktop.
    0 x 0 = the whole monitor. Sizes are rounded down to even numbers (H.264 needs them); the area must lie on the
    monitor and be at least 16 x 16. Raises ValueError with a message for the user."""
    ml, mt, mw, mh = mon[1:5]
    try:
        x, y, w, h = (int(str(v).strip() or 0) for v in (x, y, w, h))
    except ValueError:
        raise ValueError("X, Y, width and height are whole numbers of pixels.") from None
    if w == 0 and h == 0:
        x, y, w, h = 0, 0, mw, mh
    w, h = w - w % 2, h - h % 2
    if w < 16 or h < 16:
        raise ValueError("The area must be at least 16 x 16 pixels.")
    if x < 0 or y < 0 or x + w > mw or y + h > mh:
        raise ValueError(f"The area {x},{y} {w} x {h} goes off the monitor ({mw} x {mh}).")
    return ml + x, mt + y, w, h


_rec_codec: list = []  # the encoder picked, found once


def rec_codec():
    """libx264 when this ffmpeg has it (small, plays everywhere), else plain MPEG-4."""
    if not _rec_codec:
        try:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True,
                               creationflags=NO_WINDOW)
            _rec_codec.append("libx264" if " libx264 " in r.stdout else "mpeg4")
        except OSError:
            _rec_codec.append("mpeg4")
    return _rec_codec[0]


def rec_command(area, fps, out, mouse=True):
    """The ffmpeg command recording that desktop area until 'q' arrives on its stdin."""
    x, y, w, h = area
    enc = (["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
           if rec_codec() == "libx264" else ["-c:v", "mpeg4", "-q:v", "3"])
    enc += ["-g", str(max(2, int(fps) * 2))]  # a keyframe (and so a finished piece of file) every 2 s
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "gdigrab", "-framerate", str(int(fps)),
            "-draw_mouse", "1" if mouse else "0", "-offset_x", str(x), "-offset_y", str(y), "-video_size",
            f"{w}x{h}", "-i", "desktop", *enc,
            # written in self-contained pieces: a recording cut off (crash, killed) still plays, and Stop is instant
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-flush_packets", "1", str(out)]


def rec_name(folder, prefix, stamp):
    """The file a recording goes to: <folder>/<prefix> <date time>.mp4 (characters Windows won't take become _)."""
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in str(prefix).strip()) or "Recording"
    return Path(folder) / f"{safe} {stamp}.mp4"


# --- Setup tab: where things are on this PC (found automatically, or picked by the user and kept in the settings) ---
PATH_START = os.environ.get("PATH", "")  # before an ffmpeg folder picked in the Setup tab is put in front
SETUP_GLOBALS = {"sd_dir": "SD_DIR", "sd_exe": "SD_EXE", "vts": "VTS_ASSETS", "inbox": "LINK_INBOX",
                 "sd_backups": "SD_BACKUPS", "vts_backups": "VTS_BACKUPS"}
SETUP_AUTO = {k: globals()[v] for k, v in SETUP_GLOBALS.items()}  # as found at start, before any choice is applied
SETUP_ITEMS = (  # key, name, what it's for
    ("sd_dir", "Stream Deck profiles", "The Stream Deck app's profiles (has ProfilesV3 inside)"),
    ("sd_exe", "Stream Deck app", "StreamDeck.exe - reopened after your keys are saved"),
    ("vts", "VTube Studio", "Its StreamingAssets folder (Backgrounds, Live2DModels)"),
    ("ffmpeg", "ffmpeg", "Folder with ffmpeg.exe and ffprobe.exe (audio and video)"),
    ("out_dir", "Channel Mirror output", "Where the Channel Mirror tab saves its files"),
    ("rec", "Screen recordings", "Where the Screen recorder saves its videos"),
    ("inbox", "Received files", "Files sent from your phone or another PC (Link tab)"),
    ("sd_backups", "Stream Deck backups", "A copy of each profile, saved before it's changed"),
    ("vts_backups", "VTube Studio backups", "A copy of your model's settings, before hotkeys are added"))
SETUP_RESTART = {"sd_dir", "sd_exe"}  # read while the tabs are built: the open window needs a restart for these


def setup_auto(key):
    """Where a location is when nobody picked one: found on this PC, or the built-in default (None = not found;
    for the output folder None means next to each input file)."""
    if key == "vts":
        found = vts_assets()
        return found[0] if found else None
    if key == "ffmpeg":
        exe = shutil.which("ffmpeg", path=PATH_START)
        return Path(exe).parent if exe else None
    if key == "vts_backups":
        return FFMPEG_DIR.parent / "VTube Studio backups"
    if key == "rec":
        return Path.home() / "Videos" / "Channel Mirror recordings"
    return SETUP_AUTO.get(key)


def setup_check(key, p):
    """'found', 'missing', or 'new' (a folder that isn't there yet: it's made the first time something is saved)."""
    if not p:
        return "missing"
    p = Path(p)
    inside = {"sd_dir": ("ProfilesV3",), "vts": ("Backgrounds", "Live2DModels")}
    if key == "sd_exe":
        ok = p.is_file()
    elif key == "ffmpeg":
        ok = all((p / f"{n}.exe").is_file() or (p / n).is_file() for n in ("ffmpeg", "ffprobe"))
    elif key in inside:
        ok = all((p / n).is_dir() for n in inside[key])
    else:
        return "found" if p.is_dir() else "new"
    return "found" if ok else "missing"


def setup_apply(paths):
    """Use the locations picked in the Setup tab ({key: path}; blank = found automatically). Runs at start-up before
    the tabs are built; the Stream Deck / VTube Studio / Link functions look these globals up each time they run."""
    for key, value in (paths or {}).items():
        if not value:
            continue
        if key == "ffmpeg":  # first on PATH, so this ffmpeg wins over any other
            here = os.path.normcase(str(Path(value)))
            rest = [q for q in os.environ.get("PATH", "").split(os.pathsep) if q and os.path.normcase(q) != here]
            os.environ["PATH"] = os.pathsep.join([str(Path(value))] + rest)
        elif key in SETUP_GLOBALS:
            globals()[SETUP_GLOBALS[key]] = Path(value)


def setup_reset(key):
    """Back to finding it automatically (Auto in the Setup tab)."""
    if key == "ffmpeg":
        os.environ["PATH"] = PATH_START
    elif key in SETUP_GLOBALS:
        globals()[SETUP_GLOBALS[key]] = SETUP_AUTO[key]


def app_command():
    """The command that starts this app again (Restart in the Setup tab): the exe, or python + this script."""
    keep = [a for a in sys.argv[1:] if a == "--portable"]
    return ([sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]) + keep


def win_light_theme():
    """Windows' app colour setting: True = light, False = dark, None = couldn't read it."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0])
    except (OSError, ImportError):
        return None


def ui_mode(choice, light=win_light_theme):
    """'light' or 'dark' for the Appearance choice: 'light', 'dark' or 'system' (follow Windows)."""
    if choice == "system":
        return "dark" if light() is False else "light"
    return "dark" if choice == "dark" else "light"


# --- UI toolkit: theme, tooltips, menus, key grid, cell editing, dialogs (stdlib tkinter only) ---
UI_LIGHT = {"mode": "light", "bg": "#f3f4f6", "panel": "#ffffff", "border": "#d1d5db", "text": "#1f2937",
            "muted": "#6b7280", "dis": "#9ca3af", "accent": "#2563eb", "accent2": "#1d4ed8", "on_accent": "#ffffff",
            "accent_off": "#9db7f0", "accent_off_fg": "#eef2ff", "sound": "#d1fae5", "missing": "#fee2e2",
            "other": "#e5e7eb", "auto": "#e0e7ff", "empty": "#ffffff", "button": "#e8ebf0", "hover": "#dde2e9",
            "press": "#cfd5dd", "tab": "#e6e9ee", "head": "#eef0f3", "bad": "#b91c1c", "warn": "#b45309",
            "good": "#047857", "tip": "#111827", "tip_fg": "#f9fafb"}
UI_DARK = {"mode": "dark", "bg": "#1c1e23", "panel": "#25282e", "border": "#3d424b", "text": "#e7e9ec",
           "muted": "#a0a8b3", "dis": "#6b7280", "accent": "#2563eb", "accent2": "#3b7af5", "on_accent": "#ffffff",
           "accent_off": "#2b467e", "accent_off_fg": "#9fb3d9", "sound": "#1e4a39", "missing": "#5a2429",
           "other": "#353a42", "auto": "#2f3768", "empty": "#25282e", "button": "#30343b", "hover": "#3a3f48",
           "press": "#464c57", "tab": "#22252b", "head": "#2c3037", "bad": "#f87171", "warn": "#fbbf24",
           "good": "#34d399", "tip": "#33373f", "tip_fg": "#f3f4f6"}
UI = {**UI_LIGHT, "font": ("Segoe UI", 10), "small": ("Segoe UI", 8)}  # the palette in use; ui_switch swaps it
# for a live switch: which widget options hold a background or a text colour, and the palette keys for each
UI_RECOLOUR = {("-background", "-highlightbackground", "-highlightcolor", "-activebackground", "-selectbackground",
                "-troughcolor", "-selectcolor", "-disabledbackground", "-readonlybackground"):
               ("bg", "panel", "border", "accent", "accent2", "sound", "missing", "other", "auto", "empty", "button",
                "hover", "press", "tab", "head", "tip"),
               ("-foreground", "-insertbackground", "-activeforeground", "-disabledforeground", "-selectforeground"):
               ("text", "muted", "dis", "bad", "warn", "good", "tip_fg")}


UI_SWATCH = {"relief": "flat", "bd": 0, "highlightthickness": 1}  # colour boxes: a thin border in the palette's colour


def ui_palette(choice):
    """Put the Light or Dark palette for this Appearance choice into UI (before ui_theme)."""
    UI.update(UI_DARK if ui_mode(choice) == "dark" else UI_LIGHT)


def ui_titlebar(win, redraw=False):
    """Windows title bar to match the palette (dark in dark mode; Windows 10 20H1+ / 11, ignored elsewhere)."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if not hwnd:
            return
        on = ctypes.c_int(UI["mode"] == "dark")
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
        if redraw:  # repaint the frame now (no move / size / z-order / focus change)
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x37)
    except Exception:
        pass


def ui_theme(root):
    """Style every widget from UI (the Light or Dark palette): ttk styles plus matching defaults for the classic tk
    widgets. Running it again restyles every ttk widget on screen (ui_switch does the classic ones)."""
    from tkinter import font as tkfont
    from tkinter import ttk
    c = UI
    root.configure(bg=c["bg"])
    for pat, val in (("*Background", c["bg"]), ("*Foreground", c["text"]), ("*Font", "{Segoe UI} 10"),
                     ("*insertBackground", c["text"]), ("*selectBackground", c["accent"]),
                     ("*selectForeground", c["on_accent"]), ("*activeBackground", c["hover"]),
                     ("*activeForeground", c["text"]), ("*highlightBackground", c["bg"]),
                     ("*highlightColor", c["accent"]), ("*Label.highlightBackground", c["border"]),
                     ("*Listbox.background", c["panel"]),
                     ("*Text.background", c["panel"]), ("*Checkbutton.selectColor", c["panel"]),
                     ("*Button.background", c["button"]), ("*Button.relief", "flat"),
                     ("*Scale.highlightThickness", 0), ("*Scale.troughColor", c["border"]),
                     ("*Scale.sliderRelief", "flat"), ("*Scale.borderWidth", 0), ("*Scale.activeBackground", c["accent"]),
                     ("*TCombobox*Listbox.background", c["panel"]), ("*TCombobox*Listbox.foreground", c["text"]),
                     ("*TCombobox*Listbox.font", "{Segoe UI} 10"), ("*Menu.background", c["panel"]),
                     ("*Menu.foreground", c["text"]), ("*Menu.activeBackground", c["accent"]),
                     ("*Menu.activeForeground", c["on_accent"]), ("*Menu.relief", "flat")):
        root.option_add(pat, val)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=c["bg"], foreground=c["text"], font=c["font"], bordercolor=c["border"],
                lightcolor=c["bg"], darkcolor=c["bg"], troughcolor=c["border"], focuscolor=c["accent"],
                selectbackground=c["accent"], selectforeground=c["on_accent"], fieldbackground=c["panel"],
                insertcolor=c["text"], arrowcolor=c["text"])
    s.map(".", foreground=[("disabled", c["dis"])])

    def flat(base, pressed, active, disabled):  # one colour per state, no 3D bevel
        return ({k: [("pressed", pressed), ("active", active), ("disabled", disabled)]
                 for k in ("background", "lightcolor", "darkcolor")},
                {"background": base, "lightcolor": base, "darkcolor": base})
    maps, conf = flat(c["button"], c["press"], c["hover"], c["bg"])
    s.configure("TButton", padding=(10, 4), **conf)
    s.map("TButton", bordercolor=[("focus", c["accent"])], **maps)
    maps, conf = flat(c["accent"], c["accent2"], c["accent2"], c["accent_off"])
    s.configure("Accent.TButton", foreground=c["on_accent"], bordercolor=c["accent"], font=("Segoe UI", 10, "bold"),
                padding=(16, 6), **conf)
    s.map("Accent.TButton", foreground=[("disabled", c["accent_off_fg"])],
          bordercolor=[("disabled", c["accent_off"]), ("focus", c["accent2"])], **maps)
    s.configure("Tool.TButton", padding=(8, 2), width=0)
    s.configure("Toolbutton", padding=(12, 7), anchor="w", background=c["bg"], lightcolor=c["bg"], darkcolor=c["bg"],
                bordercolor=c["bg"])
    s.map("Toolbutton", **{k: [("selected", c["accent"]), ("active", c["hover"])]
                           for k in ("background", "lightcolor", "darkcolor", "bordercolor")},
          foreground=[("selected", c["on_accent"])])
    s.configure("TLabelframe", background=c["bg"], bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"],
                relief="solid", padding=10)
    s.configure("TLabelframe.Label", background=c["bg"], foreground=c["text"], font=("Segoe UI Semibold", 10))
    s.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(10, 6, 10, 0), bordercolor=c["border"],
                lightcolor=c["bg"], darkcolor=c["bg"])
    s.configure("TNotebook.Tab", padding=(10, 7), background=c["tab"], foreground=c["muted"], bordercolor=c["border"],
                lightcolor=c["tab"], darkcolor=c["tab"])
    s.map("TNotebook.Tab", background=[("selected", c["bg"]), ("active", c["hover"])],
          lightcolor=[("selected", c["bg"]), ("active", c["hover"])], foreground=[("selected", c["text"])],
          expand=[("selected", (1, 1, 1, 0))])
    line = tkfont.Font(root=root, family="Segoe UI", size=10).metrics("linespace")  # scales with Windows DPI
    s.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["text"],
                rowheight=line + 8, bordercolor=c["border"], lightcolor=c["panel"], darkcolor=c["panel"])
    s.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", c["on_accent"])])
    s.configure("Treeview.Heading", background=c["head"], foreground=c["text"], font=("Segoe UI", 9, "bold"),
                padding=(6, 4), relief="flat", bordercolor=c["border"], lightcolor=c["head"], darkcolor=c["head"])
    s.map("Treeview.Heading", **{k: [("active", c["hover"])] for k in ("background", "lightcolor", "darkcolor")})
    for w in ("TCheckbutton", "TRadiobutton"):
        s.configure(w, indicatorbackground=c["panel"], indicatorforeground=c["accent"], indicatormargin=(0, 0, 6, 0),
                    upperbordercolor=c["border"], lowerbordercolor=c["border"])
        s.map(w, background=[("disabled", c["bg"]), ("active", c["bg"])],
              indicatorbackground=[("disabled", c["bg"]), ("pressed", c["border"])],
              upperbordercolor=[("active", c["accent"])], lowerbordercolor=[("active", c["accent"])])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(w, fieldbackground=c["panel"], foreground=c["text"], padding=3, bordercolor=c["border"],
                    lightcolor=c["panel"], darkcolor=c["panel"], insertcolor=c["text"])
        s.map(w, bordercolor=[("focus", c["accent"]), ("hover", c["muted"])], lightcolor=[("focus", c["accent"])],
              fieldbackground=[("readonly", c["bg"] if w == "TEntry" else c["panel"]), ("disabled", c["bg"])])
    for w in ("TCombobox", "TSpinbox"):
        s.configure(w, background=c["button"], arrowcolor=c["text"])
    s.map("TCombobox", background=[("active", c["hover"])], selectbackground=[("readonly", c["panel"])],
          selectforeground=[("readonly", c["text"])])
    s.configure("TScrollbar", background=c["button"], troughcolor=c["bg"], bordercolor=c["bg"],
                lightcolor=c["button"], darkcolor=c["button"], arrowcolor=c["muted"], gripcount=0)
    s.map("TScrollbar", **{k: [("active", c["hover"])] for k in ("background", "lightcolor", "darkcolor")})
    s.configure("TScale", background=c["button"], troughcolor=c["border"], bordercolor=c["border"],
                lightcolor=c["button"], darkcolor=c["button"])
    s.map("TScale", background=[("active", c["hover"])])
    s.configure("TSeparator", background=c["border"])
    s.configure("Hint.TLabel", foreground=c["muted"], font=("Segoe UI", 9))
    s.configure("Field.TLabel", foreground=c["muted"], font=("Segoe UI", 8, "bold"))
    s.configure("Status.TLabel", padding=(2, 4))
    s.configure("Good.TLabel", foreground=c["good"], font=("Segoe UI", 9, "bold"))
    s.configure("Bad.TLabel", foreground=c["bad"], font=("Segoe UI", 9, "bold"))
    s.configure("Name.TLabel", font=("Segoe UI Semibold", 10))
    s.configure("Header.TFrame", background=c["panel"])
    s.configure("Header.TLabel", background=c["panel"])
    s.configure("HeadTitle.TLabel", background=c["panel"], foreground=c["text"], font=("Segoe UI", 15, "bold"))
    s.configure("HeadSub.TLabel", background=c["panel"], foreground=c["muted"])
    root.bind_class("Tk", "<Map>", lambda e: ui_titlebar(e.widget))  # each window gets its title bar when shown
    root.bind_class("Toplevel", "<Map>", lambda e: ui_titlebar(e.widget))


def ui_recolour(root, old, new):
    """Classic tk widgets keep the colours they were made with: swap each one that came from the old palette for the
    new palette's colour (ttk widgets follow their styles). Returns the windows (paths) found on the way."""
    tk, maps = root.tk, {}
    for opts, keys in UI_RECOLOUR.items():
        m = {}
        for k in keys:  # the first key wins when two share a colour (panel before empty)
            m.setdefault(old[k].lower(), new[k])
        maps.update(dict.fromkeys(opts, m))
    todo, wins = [str(root)], []
    while todo:
        w = todo.pop()
        try:
            todo += tk.splitlist(tk.call("winfo", "children", w))
            cls = tk.call("winfo", "class", w)
            if cls in ("Tk", "Toplevel"):
                wins.append(w)
            for o in tk.splitlist(tk.call(w, "configure")):
                o = tk.splitlist(o)
                m = maps.get(str(o[0]))
                if m and len(o) == 5 and str(o[4]).lower() in m:
                    tk.call(w, "configure", o[0], m[str(o[4]).lower()])
            if cls == "Treeview":  # row colours (e.g. pages with missing sounds)
                for tag in tk.splitlist(tk.call(w, "tag", "names")):
                    for opt in ("-foreground", "-background"):
                        val = str(tk.call(w, "tag", "configure", tag, opt)).lower()
                        if val in maps[opt]:
                            tk.call(w, "tag", "configure", tag, opt, maps[opt][val])
        except Exception:  # a widget closing meanwhile
            continue
    return wins


def ui_switch(root, choice):
    """Light / Dark / Follow Windows while the app is open: the new palette into UI, every ttk style again, classic
    widgets recoloured, the key grids redrawn (their tiles take colours from UI when drawn), title bars matched."""
    old = dict(UI)
    ui_palette(choice)
    ui_theme(root)
    wins = ui_recolour(root, old, UI)
    for g in list(DeckGrid.shown):
        try:
            if g.size and g.frame.winfo_exists():
                g.draw(*g.size)
        except Exception:
            pass
    for w in wins:
        try:
            ui_titlebar(root.nametowidget(w), redraw=True)
        except Exception:
            pass


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
        tk.Label(self.win, text=text, justify="left", bg=UI["tip"], fg=UI["tip_fg"], font=("Segoe UI", 9),
                 padx=8, pady=5, wraplength=420, highlightthickness=1, highlightbackground=UI["border"]).pack()

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


def ui_background(widget, work, finish):
    """Run work() on a worker thread and hand its result (or the exception it raised) to finish() back on the
    UI thread, so the window keeps responding during slow jobs like restarting Stream Deck."""
    import queue
    import threading
    q = queue.Queue()

    def run():
        try:
            q.put(work())
        except Exception as e:
            q.put(e)
    threading.Thread(target=run, daemon=True).start()

    def poll():
        try:
            res = q.get_nowait()
        except queue.Empty:
            return widget.after(100, poll)
        finish(res)
    widget.after(100, poll)


def ui_multi_rows(tree, on_double, on_drop=None):
    """Treeview clicks that keep a multi-selection: pressing on a row that's already selected (several are) leaves
    the selection alone, so the rows can be dragged together (on_drop(event) on release) or all edited with a
    double-click (on_double(event)). A plain single click still narrows to that row, once it's clearly not
    the first half of a double-click."""
    st = {}

    def press(e):
        it = tree.identify_row(e.y)
        if st.get("job"):
            tree.after_cancel(st.pop("job"))
        st.update(x=e.x_root, y=e.y_root, item=it, moved=False, keep=False)
        if it and it in tree.selection() and len(tree.selection()) > 1 and not e.state & 0x0005:
            st["keep"] = True
            return "break"

    def motion(e):
        if on_drop and st.get("item") and abs(e.x_root - st["x"]) + abs(e.y_root - st["y"]) > 8:
            st["moved"] = True
            tree.config(cursor="fleur")

    def release(e):
        tree.config(cursor="")
        if st.get("moved"):
            st["moved"] = False
            on_drop(e)
        elif st.get("keep") and st.get("item"):
            st["job"] = tree.after(350, lambda it=st["item"]: tree.exists(it) and tree.selection_set(it))

    def double(e):
        if st.get("job"):
            tree.after_cancel(st.pop("job"))
        on_double(e)
        return "break"  # stop the class binding from narrowing the selection on the second press
    tree.bind("<ButtonPress-1>", press)
    tree.bind("<B1-Motion>", motion)
    tree.bind("<ButtonRelease-1>", release)
    tree.bind("<Double-Button-1>", double)


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
    shown = weakref.WeakSet()  # every grid, so a Light / Dark switch can redraw them

    def __init__(self, parent, tile, on_click=None, on_double=None, on_menu=None, on_drop=None, tip=None):
        import tkinter as tk
        DeckGrid.shown.add(self)
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
                    w.bind("<Double-Button-1>", lambda e, p=pos: (self.drag.update(double=True),  # its release isn't a click
                                                                   self.on_double and self.on_double(p, e)))
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
        if d.get("double"):  # the release ending a double-click would otherwise unselect the key just opened
            return
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
    Tip(out, "Shown by name like in Stream Deck; saved as the device id Stream Deck uses.")
    return f


def ui_play_choice(parent, mode):
    """The two everyday ways a sound key plays, as plain choices bound to the Action variable (the Action list keeps
    the other Stream Deck modes)."""
    from tkinter import ttk
    f = ttk.Frame(parent)
    ttk.Label(f, text="EACH SOUND", style="Field.TLabel").pack(side="left", padx=(0, 10))
    for text, m in (("Play once (press again to stop)", "Play / Stop"),
                    ("Loop (repeats until pressed again)", "Loop / Stop")):
        ttk.Radiobutton(f, text=text, variable=mode, value=m).pack(side="left", padx=(0, 14))
    return f


def ui_obs_levels(parent, cfg):
    """Let the user set their own OBS level per kind of sound (saved in cfg["obs_levels"]). True when changed."""
    import tkinter as tk
    from tkinter import messagebox, ttk
    win = tk.Toplevel(parent)
    win.title("My OBS levels")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="How loud each kind of sound should sit in your OBS mix: its average level in dB while it "
                         "plays (0 = full scale, so lower = quieter).\nTo match your mic: talk normally and watch "
                         "your mic in OBS's mixer. The defaults assume it peaks around -10 dB, which averages about "
                         "-16 dB.", style="Hint.TLabel", wraplength=460, justify="left").pack(anchor="w")
    vals = {kind: tk.StringVar(value=f"{SD_LEVELS[kind]:g}") for kind in SD_OBS_DEFAULT}
    grid = ttk.Frame(body)
    grid.pack(anchor="w", pady=12)
    for i, (kind, label) in enumerate((("voice", "Voice lines (as loud as your mic)"),
                                       ("effect", "Alerts and sound effects"),
                                       ("music / ambience", "Music beds and ambience (under your voice)"))):
        ttk.Label(grid, text=label).grid(row=i, column=0, sticky="w", pady=3)
        ttk.Spinbox(grid, textvariable=vals[kind], from_=-60, to=0, increment=1, width=6).grid(row=i, column=1, padx=8)
        ttk.Label(grid, text=f"dB   (default {SD_OBS_DEFAULT[kind]:g})", style="Hint.TLabel").grid(row=i, column=2,
                                                                                            sticky="w")
    res = [False]

    def ok():
        try:
            new = {kind: float(v.get()) for kind, v in vals.items()}
            assert all(-60 <= x <= 0 for x in new.values())
        except (ValueError, AssertionError):
            return messagebox.showerror("My OBS levels", "Each level is a number from -60 to 0 dB.", parent=win)
        res[0] = new != SD_LEVELS
        cfg["obs_levels"] = sd_set_levels(new)
        win.destroy()
    bar = ttk.Frame(body)
    bar.pack(fill="x")
    ttk.Button(bar, text="Reset to defaults", command=lambda: [vals[kd].set(f"{d:g}") for kd, d in
                                                                SD_OBS_DEFAULT.items()]).pack(side="left")
    ttk.Button(bar, text="OK", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.grab_set()
    win.wait_window()
    return res[0]


def sd_levels_text():
    return "  /  ".join(f"{k} {v:g} dB" for k, v in SD_LEVELS.items())


def ui_level_report(parent, rows, names, preset):
    """List each sound's measured level against its target (rows from sd_level_rows; names: {id(sound): key name}).
    Returns True when the user presses Tune to apply the listed changes."""
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(parent)
    win.title("Sound levels")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    fix = sum(r["new"] is not None for r in rows)
    ok = sum(r["verdict"] == "in range" for r in rows)
    ttk.Label(body, text=f"{len(rows)} sound(s) checked against {preset}: {ok} in range, {fix} to change, "
                         f"{len(rows) - ok - fix} that can't be fixed with volume (too quiet at full, missing or "
                         "silent). Levels are dB, loudest channel, silence left out.",
              style="Hint.TLabel", wraplength=900).pack(anchor="w", pady=(0, 8))
    cols = ("key", "file", "kind", "level", "now", "target", "result")
    tv = ttk.Treeview(body, columns=cols, show="headings", height=min(max(len(rows), 4), 18))
    for c, h, w in zip(cols, ("Key", "File", "Detected as", "File level", "Plays at now", "Target", "Result"),
                       (110, 220, 110, 70, 80, 60, 260)):
        tv.heading(c, text=h)
        tv.column(c, width=w, stretch=c in ("file", "result"))
    f = lambda v: "" if v is None else f"{v:.1f}"
    rank = lambda r: (0 if r["new"] is not None else 1 if r["now"] is not None and r["verdict"] != "in range"
                      else 2 if r["now"] is None else 3)  # changes, can't-fix, missing/silent, fine
    for r in sorted(rows, key=rank):
        se = r["s"].get("Settings", {})
        tv.insert("", "end", values=(names.get(id(r["s"]), ""), Path(se.get("path", "")).name, r["kind"],
                                     f(r["level"]), f(r["now"]), f(r["target"]), r["verdict"]))
    tv.pack(fill="both", expand=True)
    res = [False]
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(12, 0))
    go = ttk.Button(bar, text=f"Tune {fix} sound(s)", style="Accent.TButton",
                    command=lambda: (res.__setitem__(0, True), win.destroy()))
    go.pack(side="right")
    if not fix:
        go.state(["disabled"])
    ttk.Button(bar, text="Close", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.grab_set()
    win.wait_window()
    return res[0]


def ui_pick_sounds(parent, title, folder=False, initialdir=None):
    """Sound files the user picks, in name order (track2 before track10): several files, or with folder=True every
    sound in one folder."""
    from tkinter import filedialog
    if folder:
        f = filedialog.askdirectory(parent=parent, title=title, initialdir=initialdir)
        return [q for q in media_files([f]) if q.suffix.lower() in AUDIO_EXT] if f else []
    return sorted(map(Path, filedialog.askopenfilenames(parent=parent, title=title, initialdir=initialdir, filetypes=[
        ("Audio", " ".join(f"*{e}" for e in AUDIO_EXT)), ("All files", "*.*")])), key=natural)


def import_tab(page, cfg, made, deck):
    """The Import to folders tab. Sounds (files, a folder, the Channel Mirror tab's outputs) each get their own key,
    playing once or on a loop, in folders of N. The folder keys go on the keys picked in order, on any page of any
    profile (keys in use can't be picked); folders beyond the picks take the free keys after the last pick. Volume: as
    set, tuned to my OBS levels and/or scaled by %, with a level check first if wanted. Changes go through the
    editor tab (deck = its shared API): one undo, sent to Stream Deck from there or automatically.
    Returns {"prefill": f(profile label, page file, key)} for the editor's right-click."""
    import tkinter as tk
    from tkinter import messagebox, ttk
    if deck is None:
        ttk.Label(page, text="No local Stream Deck install found.").pack(padx=20, pady=20, anchor="w")
        return {"prefill": lambda *a: None}
    files, picks = [], []
    prof_v = tk.StringVar(value=(deck["profiles"]() or [""])[0])
    win = page
    ctx = {}

    def grid():
        return deck["grid"](prof_v.get()) if prof_v.get() else (5, 3)

    def pages():
        return deck["pages"](prof_v.get()) if prof_v.get() else []

    def page_keys(p):
        return deck["keys"](p) if p else {}
    body = ttk.Frame(page, padding=12)
    body.pack(fill="both", expand=True)
    left, right = ttk.Frame(body), ttk.Frame(body)
    left.pack(side="left", fill="both", expand=True, padx=(0, 12))
    right.pack(side="left", fill="both")

    # 1. sounds
    sf = ttk.LabelFrame(left, text="1. Sounds - each one gets its own key, in this order")
    sf.pack(fill="both", expand=True)
    tv = ttk.Treeview(sf, columns=("n", "file", "folder"), show="headings", height=7)
    for c, h, w in (("n", "#", 36), ("file", "File", 220), ("folder", "From folder", 200)):
        tv.heading(c, text=h)
        tv.column(c, width=w, stretch=c != "n")
    tv.pack(fill="both", expand=True)
    title, per = tk.StringVar(), tk.IntVar(value=max(1, grid()[0] * grid()[1] - 1))
    need_l = ttk.Label(sf, style="Hint.TLabel")

    def cap():
        return max(1, grid()[0] * grid()[1] - 1)

    def per_now():
        try:
            return max(1, min(cap(), int(per.get())))
        except (tk.TclError, ValueError):
            return cap()

    def need():
        return -(-len(files) // per_now()) if files else 0

    def refresh(*_):
        tv.delete(*tv.get_children())
        for i, f in enumerate(files):
            tv.insert("", "end", iid=str(i), values=(i + 1, f.name, f.parent.name))
        need_l.config(text=f"{len(files)} sound(s) -> {need()} folder(s) of up to {per_now()}" if files else
                      "Add sounds to import.")
        if "redraw" in st_:
            st_["redraw"]()

    def add(paths):
        for p in map(Path, paths):
            if p not in files and p.suffix.lower() in AUDIO_EXT and p.is_file():
                files.append(p)
        if files and not title.get().strip():
            title.set(files[0].parent.name[:20])
        refresh()

    def remove():
        for i in sorted(map(int, tv.selection()), reverse=True):
            del files[i]
        refresh()
    st_ = {}
    bf = ttk.Frame(sf)
    bf.pack(fill="x", pady=(6, 0))
    for text, cmd in (("Add files...", lambda: add(ui_pick_sounds(win, "Sounds to import"))),
                      ("Add folder...", lambda: add(ui_pick_sounds(win, "A folder of sounds to import", True))),
                      ("Channel Mirror outputs", lambda: add(made) if made else messagebox.showinfo(
                          "No outputs yet", "Run the Channel Mirror tab first; the files it writes show up here.",
                          parent=win)),
                      ("Remove", remove), ("Clear", lambda: (files.clear(), refresh()))):
        ttk.Button(bf, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 4))
    need_l.pack(anchor="w", pady=(4, 0))

    # 2. how each key plays
    pf = ttk.LabelFrame(left, text="2. How each key plays, and where it sounds")
    pf.pack(fill="x", pady=(10, 0))
    v = {"mode": tk.StringVar(value="Play / Stop"), "fade": tk.StringVar(value=SD_FADES[0]),
         "fade_len": tk.StringVar(value="1"), "volume": tk.IntVar(value=100),
         "output": tk.StringVar(value=SD_DEFAULT_OUT)}
    ui_play_choice(pf, v["mode"]).pack(anchor="w")
    ui_sound_form(pf, v).pack(fill="x", pady=(6, 0))

    # 3. volume
    vf = ttk.LabelFrame(left, text="3. Volume - adjust and check")
    vf.pack(fill="x", pady=(10, 0))
    tune_on, preset, scale = tk.BooleanVar(value=False), tk.StringVar(value=SD_AUTO), tk.IntVar(value=100)
    r1 = ttk.Frame(vf)
    r1.pack(fill="x")
    ttk.Checkbutton(r1, text="Tune each sound to my OBS levels:", variable=tune_on).pack(side="left")
    ttk.Combobox(r1, textvariable=preset, values=list(SD_TUNE), state="readonly", width=38).pack(side="left", padx=6)
    ttk.Button(r1, text="My OBS levels...", style="Tool.TButton",
               command=lambda: ui_obs_levels(win, cfg)).pack(side="left")
    r2 = ttk.Frame(vf)
    r2.pack(fill="x", pady=(6, 0))
    ttk.Label(r2, text="Then scale every volume by").pack(side="left")
    ttk.Spinbox(r2, textvariable=scale, from_=1, to=400, width=5).pack(side="left", padx=6)
    ttk.Label(r2, text="%").pack(side="left")
    ttk.Button(r2, text="Check levels...", style="Tool.TButton", command=lambda: check()).pack(side="left", padx=14)
    ttk.Label(r2, text="listens to each file; Tune in the list switches tuning on", style="Hint.TLabel").pack(
        side="left")
    status = ttk.Label(left, style="Hint.TLabel")
    status.pack(anchor="w", pady=(6, 0))

    def level_rows():
        heard = {}
        for i, f in enumerate(files, 1):
            status.config(text=f"Listening {i}/{len(files)}: {f.name}...")
            win.update()
            try:
                heard[str(f)] = sd_listen(f)
            except Exception:
                pass
        status.config(text="")
        stand = [{"Settings": {"path": str(f), "volume": int(v["volume"].get())}} for f in files]
        return sd_level_rows(stand, heard, preset.get())

    def check():
        if not files:
            return messagebox.showinfo("Check levels", "Add sounds first.", parent=win)
        rows_ = level_rows()
        if ui_level_report(win, rows_, {id(r["s"]): Path(r["s"]["Settings"]["path"]).name for r in rows_},
                           preset.get()):
            tune_on.set(True)

    # 4. folders
    ff = ttk.LabelFrame(right, text="4. Folders")
    ff.pack(fill="x")
    fr = ttk.Frame(ff)
    fr.pack(fill="x")
    ttk.Label(fr, text="Name").pack(side="left")
    ttk.Entry(fr, textvariable=title, width=20).pack(side="left", padx=6)
    fr = ttk.Frame(ff)
    fr.pack(fill="x", pady=(4, 0))
    ttk.Label(fr, text="Sounds per folder").pack(side="left")
    per_box = ttk.Spinbox(fr, textvariable=per, from_=1, to=cap(), width=4)
    per_box.pack(side="left", padx=6)
    cap_l = ttk.Label(ff, style="Hint.TLabel", wraplength=420)
    cap_l.pack(anchor="w")
    per.trace_add("write", refresh)

    # 5. where the folder keys go
    tf = ttk.LabelFrame(right, text="5. Where the folders go")
    tf.pack(fill="both", expand=True, pady=(10, 0))
    ttk.Label(tf, text="Pick a page, then click free keys in order: folder 1, 2, 3... Grey keys are in use and can't "
                       "be picked; click a picked key again to drop it.", style="Hint.TLabel", wraplength=420,
              justify="left").pack(anchor="w")
    pr = ttk.Frame(tf)
    pr.pack(fill="x", pady=(6, 0))
    ttk.Label(pr, text="Profile").pack(side="left")
    ttk.Combobox(pr, textvariable=prof_v, values=deck["profiles"](), state="readonly", width=44).pack(side="left",
                                                                                                    padx=6)
    page_v = tk.StringVar()
    page_cb = ttk.Combobox(tf, textvariable=page_v, state="readonly", width=40)
    page_cb.pack(anchor="w", pady=6)

    def by_label():
        return dict(pages())

    def labels():
        return {p: n for n, p in pages()}

    def size(p):
        c_, r_ = grid()
        for k in page_keys(p):
            x, y = map(int, k.split(","))
            c_, r_ = max(c_, x + 1), max(r_, y + 1)
        return c_, r_

    def cur():
        return by_label().get(page_v.get())

    def tile(pos):
        a = page_keys(cur()).get(pos)
        c, r = map(int, pos.split(","))
        if (cur(), pos) in picks:
            return f"Folder {picks.index((cur(), pos)) + 1}", UI["accent"], UI["on_accent"]
        if a:
            return f"{(sd_title(a).replace(chr(10), ' ') or sd_kind(a))[:16]}\n(in use)", UI["other"], UI["muted"]
        return f"{c + 1},{r + 1}", UI["empty"], UI["muted"]

    def click(pos, _e=None):
        here = (cur(), pos)
        if here in picks:
            picks.remove(here)
        elif page_keys(cur()).get(pos):
            return pick_l.config(text=f"Key {pos} on {page_v.get()} is in use - pick a free (white) key.")
        else:
            picks.append(here)
        redraw()
    kgrid = DeckGrid(tf, tile, on_click=click,
                    tip=lambda pos: "In use: " + (sd_title(page_keys(cur())[pos]).replace(chr(10), " ") or
                                                  sd_kind(page_keys(cur())[pos])) if page_keys(cur()).get(pos)
                    else "Free - click to put the next folder here")
    kgrid.frame.pack(pady=4)
    pick_l = ttk.Label(tf, style="Hint.TLabel", wraplength=420, justify="left")
    pick_l.pack(anchor="w")

    def targets(n):
        """Keys for n folders: the picks, then the free keys after the last pick on its page."""
        spots = list(picks)
        if picks and len(spots) < n:
            p, k = picks[-1]
            taken = {**page_keys(p), **{k2: 1 for p2, k2 in picks if p2 == p}}
            spots += [(p, x) for x in sd_beside(taken, k, *size(p))]
        return spots[:n]

    def redraw():
        if cur():
            kgrid.draw(*size(cur()))
        n = need()
        lines = [f"{i}: {labels().get(p, '?')}, key {'{},{}'.format(*(int(x) + 1 for x in k.split(',')))}"
                 for i, (p, k) in enumerate(picks, 1)]
        if n > len(picks) and picks:
            got = len(targets(n))
            lines.append(f"Folders {len(picks) + 1}-{n} go on the free keys after the last pick" if got >= n else
                         f"Only room for {got} of {n} folders after the last pick - pick more keys or raise "
                         "Sounds per folder")
        elif not picks:
            lines.append("No key picked yet.")
        elif len(picks) > n:
            lines.append(f"{len(picks) - n} more key(s) picked than folders needed; the extra ones stay free.")
        pick_l.config(text="\n".join(lines))
    st_["redraw"] = redraw
    page_v.trace_add("write", lambda *_: redraw())

    def on_profile(*_):
        """Another profile: its pages, its deck size; picks on the old one are dropped."""
        picks.clear()
        page_cb.config(values=[n for n, _ in pages()])
        if page_v.get() not in by_label():
            page_v.set(pages()[0][0] if pages() else "")
        per_box.config(to=cap())
        if per_now() > cap() or not ctx.get("per_set"):  # full folders until the user sets a number
            ctx["mine"] = True
            per.set(cap())
            ctx["mine"] = False
        cap_l.config(text=f"A folder holds up to {cap()} on this deck (one key is its back key). More sounds than "
                          "that = more folders: name, name 2, name 3...")
        refresh()
        redraw()
    prof_v.trace_add("write", on_profile)

    def prune():
        """Drop picks that are in use now (a key put there from another tab) or whose page is gone (undone)."""
        here = set(by_label().values())
        live = [(p, k) for p, k in picks if p in here and not page_keys(p).get(k)]
        dropped = len(picks) - len(live)
        picks[:] = live
        return dropped

    def ok():
        if not files:
            return messagebox.showinfo("Import", "Add the sounds to import first.", parent=win)
        if prune():
            redraw()
            return messagebox.showinfo("Import", "Some picked keys are in use now (or their page is gone), so they "
                                       "were dropped. Check the picks and press Import again.", parent=win)
        n = need()
        spots = targets(n)
        if not picks or len(spots) < n:
            return messagebox.showinfo("Import", f"These {len(files)} sounds need {n} folder(s). Pick a free key "
                                       "for each (any page), or pick one and leave free keys after it.", parent=win)
        base = int(v["volume"].get())
        vols = {f: base for f in files}
        if tune_on.get():
            for f, r in zip(files, level_rows()):
                if r["new"] is not None:
                    vols[f] = r["new"]
        try:
            pct = int(scale.get())
        except (tk.TclError, ValueError):
            pct = 100
        plays = sd_plays_like(files, sd_play("", "", v["mode"].get(), v["fade"].get(), v["fade_len"].get(), base,
                                             v["output"].get()))
        for f, s in zip(files, plays):
            s["Settings"]["volume"] = max(0, min(100, round(vols[f] * pct / 100)))
        name = title.get().strip()[:20] or "Sounds"
        cols, rows = grid()
        on = {p for p, _ in spots}
        taken = {sd_title(a) for p in on for a in page_keys(p).values() if a and a.get("UUID") == SD_FOLDER}
        chunks = sd_folders(name, plays, cols, rows, taken=taken, per=per_now())
        names, folder = labels(), deck["folder"](prof_v.get())

        def put(edit):
            for (p, k), (key, pid, pg) in zip(spots, chunks):
                sd_keypad(edit(p))[k] = key
                edit(folder / "Profiles" / pid.upper() / "manifest.json", pg)
        msg = (f"Imported {len(plays)} sound(s) into {len(chunks)} folder(s): " + ", ".join(
            f"{sd_title(key)} ({names.get(p, '?')}, key {'{},{}'.format(*(int(x) + 1 for x in k.split(',')))})"
            for (p, k), (key, _, _) in zip(spots, chunks)))
        deck["change"](put, msg)
        picks.clear()
        redraw()
        status.config(text=msg + ". Undo is here or in the Stream Deck editor tab; it's sent to Stream Deck from "
                                 "there (or automatically).")
    bar = ttk.Frame(right)
    bar.pack(fill="x", pady=(10, 0))
    ttk.Button(bar, text="Import", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Undo", command=deck["undo"]).pack(side="right", padx=8)

    def prefill(label, page_file, key):
        """From the editor's right-click: this profile and page, this key picked first."""
        if label in deck["profiles"]():
            prof_v.set(label)
        page_v.set(labels().get(page_file, page_v.get()))
        picks.clear()
        if key and not page_keys(page_file).get(key):
            picks.append((page_file, key))
        redraw()
    deck["listeners"].append(lambda: (page_cb.config(values=[n for n, _ in pages()]), prune(), redraw()))
    per.trace_add("write", lambda *_: ctx.get("mine") or ctx.update(per_set=True))
    on_profile()
    return {"prefill": prefill, "add": add}


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


def recorder_tab(page, cfg):
    """The Screen recorder tab: record an area of a monitor (set in pixels, or dragged on screen) to a video file in a
    chosen folder, until Stop. A click-through outline marks the area on screen and a small Record / Stop control
    floats beside it; neither shows up in the video, and everything else on screen stays usable.
    Returns {"save", "stop_now"} for the window's close."""
    import subprocess as sp
    import tempfile
    import time
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    rc = cfg.setdefault("recorder", {})
    mons = rec_monitors()
    labels = [m[0] for m in mons]
    num = lambda label: label.split(":")[0].replace(" (main)", "")  # "Monitor 2", whichever is the main one
    want = rc.get("monitor", "")
    st = {"proc": None, "outline": None, "float": None, "shown": False}
    v = {"mon": tk.StringVar(value=next((l for l in labels if num(l) == num(want)), labels[0])),
         "x": tk.StringVar(value=str(rc.get("x", 0))), "y": tk.StringVar(value=str(rc.get("y", 0))),
         "w": tk.StringVar(value=str(rc.get("w", 1280))), "h": tk.StringVar(value=str(rc.get("h", 720))),
         "fps": tk.StringVar(value=str(rc.get("fps", 30))), "mouse": tk.BooleanVar(value=rc.get("mouse", True)),
         "folder": tk.StringVar(value=rc.get("folder") or str(Path.home() / "Videos" / "Channel Mirror recordings")),
         "name": tk.StringVar(value=rc.get("name", "Recording")),
         "outline": tk.BooleanVar(value=rc.get("outline", True)), "float": tk.BooleanVar(value=rc.get("float", True)),
         "hide": tk.BooleanVar(value=rc.get("hide", False))}
    body = ttk.Frame(page, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Pick a monitor and the part of it to record (type it in pixels, or drag it on screen). The "
                         "outline shows exactly what's recorded; clicks go straight through it, and the outline and "
                         "the floating Record / Stop button never appear in the video.", style="Hint.TLabel",
              wraplength=1000, justify="left").pack(anchor="w", pady=(0, 10))

    # what to record
    wf = ttk.LabelFrame(body, text="1. What to record")
    wf.pack(fill="x")
    r = ttk.Frame(wf)
    r.pack(fill="x")
    ttk.Label(r, text="Monitor").pack(side="left")
    mon_cb = ttk.Combobox(r, textvariable=v["mon"], values=labels, state="readonly", width=44,
                          postcommand=lambda: refresh_monitors())
    mon_cb.pack(side="left", padx=6)
    r2 = ttk.Frame(wf)
    r2.pack(fill="x", pady=(8, 0))
    for key, text in (("x", "X (from the left)"), ("y", "Y (from the top)"), ("w", "Width"), ("h", "Height")):
        f = ttk.Frame(r2)
        f.pack(side="left", padx=(0, 12))
        ttk.Label(f, text=text.upper(), style="Field.TLabel").pack(anchor="w")
        ttk.Spinbox(f, textvariable=v[key], from_=0, to=20000, increment=10, width=8).pack(anchor="w")
    bf = ttk.Frame(r2)
    bf.pack(side="left", anchor="s")
    area_l = ttk.Label(wf, style="Hint.TLabel")
    area_l.pack(anchor="w", pady=(6, 0))
    r3 = ttk.Frame(wf)
    r3.pack(fill="x", pady=(6, 0))
    ttk.Checkbutton(r3, text="Show the outline on screen", variable=v["outline"]).pack(side="left")
    ttk.Checkbutton(r3, text="Floating Record / Stop button beside it", variable=v["float"]).pack(side="left", padx=14)

    # how and where
    hf = ttk.LabelFrame(body, text="2. How, and where it's saved")
    hf.pack(fill="x", pady=(12, 0))
    r4 = ttk.Frame(hf)
    r4.pack(fill="x")
    ttk.Label(r4, text="Frames per second").pack(side="left")
    ttk.Combobox(r4, textvariable=v["fps"], values=("15", "24", "30", "60"), width=5).pack(side="left", padx=6)
    ttk.Checkbutton(r4, text="Show the mouse pointer", variable=v["mouse"]).pack(side="left", padx=14)
    ttk.Checkbutton(r4, text="Minimize Channel Mirror while recording", variable=v["hide"]).pack(side="left")
    r5 = ttk.Frame(hf)
    r5.pack(fill="x", pady=(8, 0))
    ttk.Label(r5, text="Save to folder").pack(side="left")
    ttk.Entry(r5, textvariable=v["folder"], width=60).pack(side="left", padx=6, fill="x", expand=True)
    ttk.Button(r5, text="Browse...", style="Tool.TButton", command=lambda: v["folder"].set(
        filedialog.askdirectory(parent=page, title="Save recordings to", initialdir=v["folder"].get() or None)
        or v["folder"].get())).pack(side="left")
    ttk.Button(r5, text="Open folder", style="Tool.TButton", command=lambda: open_folder()).pack(side="left", padx=6)
    r6 = ttk.Frame(hf)
    r6.pack(fill="x", pady=(8, 0))
    ttk.Label(r6, text="File name").pack(side="left")
    ttk.Entry(r6, textvariable=v["name"], width=24).pack(side="left", padx=6)
    ttk.Label(r6, text="+ the date and time, .mp4", style="Hint.TLabel").pack(side="left")

    # record
    rf = ttk.Frame(body)
    rf.pack(fill="x", pady=(14, 0))
    rec_b = ttk.Button(rf, text="Record", style="Accent.TButton", width=16)
    rec_b.pack(side="left")
    time_l = ttk.Label(rf, font=("Segoe UI", 14, "bold"), width=10)
    time_l.pack(side="left", padx=12)
    status = ttk.Label(rf, style="Status.TLabel", anchor="w", wraplength=760, justify="left")
    status.pack(side="left", fill="x", expand=True)
    lf = ttk.LabelFrame(body, text="Recordings this session (double-click to play)")
    lf.pack(fill="both", expand=True, pady=(12, 0))
    tv = ttk.Treeview(lf, columns=("file", "length", "size", "folder"), show="headings", height=5)
    for c, h, w_ in (("file", "File", 300), ("length", "Length", 80), ("size", "Size", 80), ("folder", "Folder", 400)):
        tv.heading(c, text=h)
        tv.column(c, width=w_, stretch=c in ("file", "folder"))
    tv.pack(fill="both", expand=True)
    tv.bind("<Double-1>", lambda e: tv.focus() and os.startfile(tv.focus()))

    def mon():
        if st["proc"] is not None:  # while recording: the monitor it's recording
            return st["rec_mon"]
        return next((m for m in mons if m[0] == v["mon"].get()), mons[0])

    def refresh_monitors():
        """Monitors plugged in / out or rescaled since: the list again, the same monitor kept by number."""
        if st["proc"] is not None:
            return
        mons[:] = rec_monitors()
        mon_cb.config(values=[m[0] for m in mons])
        if v["mon"].get() not in [m[0] for m in mons]:
            v["mon"].set(next((m[0] for m in mons if num(m[0]) == num(v["mon"].get())), mons[0][0]))

    def area():
        if st["proc"] is not None:  # while recording: the area it's recording, whatever is typed meanwhile
            return st["rec_area"]
        return rec_area(mon(), v["x"].get(), v["y"].get(), v["w"].get(), v["h"].get())

    def app_rect(x, y, w, h):
        """Real desktop pixels -> this app's window geometry string."""
        (ax, ay), (bx, by) = rec_to_app(mon(), x, y), rec_to_app(mon(), x + w, y + h)
        return ax, ay, bx - ax, by - ay

    def place():
        """Show / move / hide the outline and the floating button to match the area and state."""
        try:
            x, y, w, h = area()
            area_l.config(text=f"Records {w} x {h} pixels at {x - mon()[1]},{y - mon()[2]} on {mon()[0].split(':')[0]}"
                               f" (desktop {x},{y}). Sizes are rounded down to even numbers.")
            ok = True
        except ValueError as e:
            area_l.config(text=str(e))
            ok = False
        recording = st["proc"] is not None
        show = ok and (st["shown"] or recording)
        _, mx, my, mw, mh, _ = mon()
        if show and v["outline"].get():
            ol = st["outline"]
            if ol is None or not ol.winfo_exists():
                ol = st["outline"] = tk.Toplevel(page)
                ol.overrideredirect(True)
                ol.attributes("-topmost", True)
                ol.configure(bg="#010203")
                ol.attributes("-transparentcolor", "#010203")
                ol.canvas = tk.Canvas(ol, bg="#010203", highlightthickness=0)
                ol.canvas.pack(fill="both", expand=True)
                if not rec_overlay(ol):
                    status.config(text="Note: this Windows can't leave the outline out of recordings - it sits "
                                       "just outside the area, but the floating button may show if it's inside.")
            pad = 4  # the line sits just outside the recorded pixels (and is left out of the video anyway)
            ox, oy = max(mx, x - pad), max(my, y - pad)
            ow, oh = min(mx + mw, x + w + pad) - ox, min(my + mh, y + h + pad) - oy
            ax, ay, aw, ah = app_rect(ox, oy, ow, oh)
            ol.geometry(f"{aw}x{ah}+{ax}+{ay}")
            ol.canvas.delete("all")
            colour = "#ef4444" if recording else "#f59e0b"
            ol.canvas.create_rectangle(2, 2, aw - 2, ah - 2, outline=colour, width=3)
            ol.deiconify()
        elif st["outline"] is not None and st["outline"].winfo_exists():
            st["outline"].withdraw()
        if show and v["float"].get():
            fl = st["float"]
            if fl is None or not fl.winfo_exists():
                fl = st["float"] = tk.Toplevel(page)
                fl.overrideredirect(True)
                fl.attributes("-topmost", True)
                fl.configure(bg=UI["panel"], highlightbackground=UI["border"], highlightthickness=1)
                fl.btn = tk.Button(fl, command=toggle, font=("Segoe UI", 10, "bold"), relief="flat", padx=10)
                fl.btn.pack(side="left", padx=4, pady=4)
                fl.lbl = tk.Label(fl, bg=UI["panel"], font=("Segoe UI", 10), width=7, cursor="fleur")
                fl.lbl.pack(side="left", padx=(0, 6))
                fl.lbl.bind("<ButtonPress-1>", lambda e: st.update(drag=(e.x_root - fl.winfo_x(), e.y_root - fl.winfo_y())))
                fl.lbl.bind("<B1-Motion>", lambda e: (fl.geometry(f"+{e.x_root - st['drag'][0]}+"
                                                                  f"{e.y_root - st['drag'][1]}"), st.update(moved=True)))
                rec_overlay(fl, clickthrough=False)
                st["moved"] = False
            fl.btn.config(text="■ Stop" if recording else "● Record", bg="#ef4444" if recording else UI["accent"],
                          fg=UI["on_accent"], activebackground="#b91c1c" if recording else UI["accent2"])
            if not st.get("moved"):  # above the area's top-right corner, or inside it when there's no room
                fl.update_idletasks()
                fw, fh = fl.winfo_reqwidth(), fl.winfo_reqheight()
                ax, ay, aw, ah = app_rect(x, y, w, h)
                (mnx, mny) = rec_to_app(mon(), mx, my)
                top = ay - fh - 8 if ay - fh - 8 >= mny else ay + 8
                fl.geometry(f"+{max(mnx, ax + aw - fw)}+{top}")
            fl.deiconify()
        elif st["float"] is not None and st["float"].winfo_exists():
            st["float"].withdraw()

    def drag_area():
        """A see-through layer over the chosen monitor: drag the area to record (Esc cancels)."""
        if st["proc"]:
            return
        m = mon()
        ax, ay, aw, ah = m[5]
        win = tk.Toplevel(page)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.35)
        win.geometry(f"{aw}x{ah}+{ax}+{ay}")
        cv = tk.Canvas(win, bg="#000000", highlightthickness=0, cursor="crosshair")
        cv.pack(fill="both", expand=True)
        cv.create_text(aw // 2, 40, text="Drag the area to record  -  Esc cancels", fill="#ffffff",
                       font=("Segoe UI", 16, "bold"))
        box = {}

        def press(e):
            box["a"] = (e.x, e.y)
            box["r"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#f59e0b", width=3, fill="#ffffff")

        def motion(e):
            if "r" in box:
                cv.coords(box["r"], *box["a"], e.x, e.y)

        def release(e):
            if "a" not in box:
                return
            (x0, y0), (x1, y1) = box["a"], (e.x, e.y)
            win.destroy()
            p0 = rec_from_app(m, ax + min(x0, x1), ay + min(y0, y1))
            p1 = rec_from_app(m, ax + max(x0, x1), ay + max(y0, y1))
            if p1[0] - p0[0] < 16 or p1[1] - p0[1] < 16:
                return status.config(text="That area is too small - drag a bigger one.")
            st["moved"] = False
            v["x"].set(str(p0[0] - m[1]))
            v["y"].set(str(p0[1] - m[2]))
            v["w"].set(str(p1[0] - p0[0]))
            v["h"].set(str(p1[1] - p0[1]))
            status.config(text="Area set. Press Record when you're ready.")
        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", motion)
        cv.bind("<ButtonRelease-1>", release)
        win.bind("<Escape>", lambda e: win.destroy())
        win.focus_force()

    def whole():
        st["moved"] = False
        v["x"].set("0"), v["y"].set("0"), v["w"].set(str(mon()[3])), v["h"].set(str(mon()[4]))
    for text, cmd in (("Drag the area on screen...", drag_area), ("Whole monitor", whole)):
        ttk.Button(bf, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 6))

    def open_folder():
        f = Path(v["folder"].get().strip() or ".")
        if f.is_dir():
            os.startfile(f)
        else:
            status.config(text="That folder doesn't exist yet - it's made when the first recording is saved.")

    def start():
        refresh_monitors()
        try:
            a = area()
            fps = max(1, min(120, int(v["fps"].get())))
        except ValueError as e:
            return messagebox.showerror("Record", str(e) if "pixel" in str(e) or "area" in str(e).lower()
                                        else "Frames per second is a whole number.", parent=page)
        folder = Path(v["folder"].get().strip() or Path.home() / "Videos" / "Channel Mirror recordings")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return messagebox.showerror("Record", f"Can't use that folder:\n{e}", parent=page)
        out = rec_name(folder, v["name"].get(), time.strftime("%Y-%m-%d %H-%M-%S"))
        n = 2
        while out.exists():  # two started in the same second: keep both
            out = out.with_name(f"{out.stem.rsplit(' (', 1)[0]} ({n}).mp4")
            n += 1
        err = tempfile.TemporaryFile()
        try:
            proc = sp.Popen(rec_command(a, fps, out, v["mouse"].get()), stdin=sp.PIPE, stdout=sp.DEVNULL,
                            stderr=err, creationflags=NO_WINDOW)
        except OSError as e:
            err.close()
            return messagebox.showerror("Record", f"Couldn't start ffmpeg:\n{e}", parent=page)
        st.update(proc=proc, out=out, t0=time.time(), err=err, rec_mon=mon(), rec_area=a)
        rec_b.config(text="Stop")
        status.config(text=f"Recording {a[2]} x {a[3]} to {out}")
        save()
        place()
        if v["hide"].get():
            page.winfo_toplevel().iconify()
        tick()

    def tick():
        proc = st["proc"]
        if proc is None or st.get("stopping"):  # Stop pressed: the finish comes from stop()
            return
        secs = int(time.time() - st["t0"])
        text = f"{secs // 60}:{secs % 60:02d}"
        time_l.config(text=text, foreground="#ef4444")
        if st["float"] is not None and st["float"].winfo_exists():
            st["float"].lbl.config(text=text)
        if proc.poll() is not None:  # ffmpeg stopped by itself: something went wrong
            finish(proc.returncode or 1)
            return
        page.after(500, tick)

    def stop():
        proc = st["proc"]
        if proc is None:
            return
        st["stopping"] = True
        rec_b.state(["disabled"])
        status.config(text="Finishing the file...")
        try:
            proc.stdin.write(b"q")  # ffmpeg's own key for "stop and finish the file"
            proc.stdin.flush()
        except OSError:
            pass

        def wait():
            try:
                return proc.wait(timeout=20)
            except sp.TimeoutExpired:
                proc.kill()
                return proc.wait()
        ui_background(page, wait, finish)

    def finish(res, failed=None):
        if st["proc"] is None:  # already finished
            return
        out, secs = st["out"], int(time.time() - st["t0"])
        try:
            st["err"].seek(0)
            said = st["err"].read().decode(errors="replace").strip()[-600:]
            st["err"].close()
        except (OSError, ValueError):
            said = ""
        if failed is None and isinstance(res, int) and res != 0:
            failed = said or f"ffmpeg ended with code {res}"
        st.update(proc=None, stopping=False)
        rec_b.state(["!disabled"])
        rec_b.config(text="Record")
        time_l.config(foreground=UI["text"])
        place()
        if v["hide"].get():
            page.winfo_toplevel().deiconify()
        if not out.is_file() or out.stat().st_size == 0:
            status.config(text=f"Recording failed: {failed or said or 'no video was written'}")
            return messagebox.showerror("Record", failed or said or "No video was written.", parent=page)
        if failed:  # cut short, but what was recorded is kept (and plays)
            status.config(text=f"Recording stopped early: {failed}. What was recorded is saved: {out}")
            messagebox.showwarning("Record", f"The recording stopped early:\n{failed}\n\nWhat was recorded is "
                                   f"saved:\n{out}", parent=page)
        mb = out.stat().st_size / 1e6
        tv.insert("", 0, iid=str(out), values=(out.name, f"{secs // 60}:{secs % 60:02d}", f"{mb:.1f} MB", out.parent))
        if not failed:
            status.config(text=f"Saved {out}  ({mb:.1f} MB)")

    def toggle():
        stop() if st["proc"] else start()
    rec_b.config(command=toggle)

    def stop_now():
        """The app is closing: finish the file properly before it goes."""
        proc = st["proc"]
        if proc:
            try:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.wait(timeout=20)
            except (OSError, sp.TimeoutExpired):
                proc.kill()
            st["proc"] = None

    def save():
        rc.update({k: x.get() for k, x in v.items() if k != "mon"}, monitor=v["mon"].get())

    def on_map(shown):
        st["shown"] = shown
        place()
    page.bind("<Map>", lambda e: e.widget is page and on_map(True))
    page.bind("<Unmap>", lambda e: e.widget is page and on_map(False))
    for x in v.values():
        x.trace_add("write", lambda *_: place())
    v["mon"].trace_add("write", lambda *_: st.update(moved=False))
    place()
    return {"save": save, "stop_now": stop_now, "start": start, "stop": stop, "vars": v, "state": st}


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

    def run():
        if not files:
            return messagebox.showinfo("VTube Studio", "Add the backgrounds first.", parent=page)
        if not bg_dir() or not (bg_dir().parent / "Live2DModels").is_dir():
            return messagebox.showerror("VTube Studio", "Pick VTube Studio's StreamingAssets folder (the one with "
                                        "Backgrounds and Live2DModels in it).", parent=page)
        want_hk, want_keys = v["hotkeys"].get() or v["keys"].get(), v["keys"].get() and deck is not None
        model = next((m for m in models() if m[0] == v["model"].get()), None)
        if want_hk and model is None:
            return messagebox.showinfo("VTube Studio", "Pick the model that gets the hotkeys.", parent=page)
        if want_keys:
            n = need()
            if not picks or len(targets(n)) < n:
                return messagebox.showinfo("VTube Studio", f"These need {n} Stream Deck key(s). Pick where they go "
                                           "(a free key for each, or one with free keys after it).", parent=page)
        # 1. copy
        try:
            names = vts_copy(files, bg_dir())
        except OSError as e:
            return messagebox.showerror("VTube Studio", f"Couldn't copy into {bg_dir()}:\n{e}", parent=page)
        names = list(dict.fromkeys(names))  # the same background twice gets one hotkey / key
        done = [f"copied {len(files)} background(s) into VTube Studio"]
        refresh()
        if not want_hk:
            return status.config(text=done[0].capitalize() + ".")
        # 2. hotkeys: VTube Studio rewrites its model file when it closes, so it's closed while this is written
        reopen = False
        if vts_running():
            if not messagebox.askyesno("VTube Studio", "VTube Studio must close for a moment while the hotkeys are "
                                       "written (it saves its model files when it closes).\nClose it now and "
                                       "reopen it after?", parent=page):
                return status.config(text=done[0].capitalize() + "; hotkeys and keys not made (VTube Studio was "
                                     "left open). Press again when it can close.")
            if not close_vts():
                return status.config(text=done[0].capitalize() + "; VTube Studio didn't close, so no hotkeys were "
                                     "made. Close it yourself and press again.")
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
            return messagebox.showerror("VTube Studio", f"Couldn't add the hotkeys to {mfile.name} (it's unchanged):"
                                        f"\n{e}\n\nThe backgrounds were copied. Model file backups are in {bk}.",
                                        parent=page)
        done.append(f"{added} new hotkey(s) on {model[0]}" + (f" ({len(names) - added} already there)"
                                                               if len(names) > added else ""))
        if reopen:
            done.append("VTube Studio reopened" if start_vts() else "start VTube Studio again yourself")
        # 3. Stream Deck keys
        if want_keys:
            acts = [sd_vts_key(mid, ids[nm], nm[:20]) for nm in names]
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
        save()
        redraw()
        status.config(text="; ".join(done).capitalize() + ".")

    bar = ttk.Frame(right)
    bar.pack(fill="x", pady=(10, 0))
    ttk.Button(bar, text="Copy and set up", style="Accent.TButton", command=run).pack(side="right")
    if deck:
        ttk.Button(bar, text="Undo keys", command=deck["undo"]).pack(side="right", padx=8)

    def save():
        vc.update({k: x.get() for k, x in v.items() if k not in ("prof", "page", "per")}, per=per_n())
    on_assets()
    on_prof()
    return {"save": save, "add": add, "run": run, "vars": v, "picks": picks, "grid": grid, "files": files}


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


def link_tab(page, cfg, deliver):
    """The Link tab. channelmirror:// links on this PC (set up, make, open), receiving files from other devices on
    the home network (a pairing link with a code; every batch is shown here and placed only when accepted), and
    sending files to another Channel Mirror. deliver(target, files) puts accepted files in that tab.
    Returns {"open_link", "stop", "save"}."""
    import queue
    import secrets
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    lc = cfg.setdefault("link", {})
    events = queue.Queue()  # from the server threads to this one
    st = {"server": None}
    v = {"port": tk.StringVar(value=str(lc.get("port", LINK_PORT))),
         "code": tk.StringVar(value=f"{secrets.randbelow(10 ** 8):08d}"),  # new each start, never saved
         "pair": tk.StringVar(), "make_to": tk.StringVar(value=LINK_TARGETS["import"]),
         "made": tk.StringVar(), "open": tk.StringVar(),
         "dest": tk.StringVar(value=lc.get("dest", "")), "send_to": tk.StringVar(value=LINK_TARGETS["import"]),
         "device": tk.StringVar(value=lc.get("device") or os.environ.get("COMPUTERNAME", "My PC"))}
    names = {lab: k for k, lab in LINK_TARGETS.items()}
    make_files, send_files = [], []
    body = ttk.Frame(page, padding=12)
    body.pack(fill="both", expand=True)
    status = ttk.Label(page, style="Status.TLabel", anchor="w", wraplength=1100, justify="left")
    status.pack(fill="x", padx=12, pady=(0, 8))
    left, right = ttk.Frame(body), ttk.Frame(body)
    left.pack(side="left", fill="both", expand=True, padx=(0, 12))
    right.pack(side="left", fill="both", expand=True)

    # links on this PC
    lf = ttk.LabelFrame(left, text="Links on this PC  (channelmirror://...)")
    lf.pack(fill="x")
    ttk.Label(lf, text="Clicking a link (in a browser, Discord, a shortcut...) opens Channel Mirror with its files "
                       "ready for the chosen tab; you accept them first. A link can also carry web addresses: those "
                       "files are downloaded.", style="Hint.TLabel", wraplength=520, justify="left").pack(anchor="w")
    reg_l = ttk.Label(lf)
    reg_l.pack(anchor="w", pady=(6, 0))
    rr = ttk.Frame(lf)
    rr.pack(fill="x", pady=(4, 0))

    def show_reg():
        cmd = link_registered()
        reg_l.config(text=f"Links open: {cmd.split(chr(34))[1] if cmd and chr(34) in cmd else cmd}" if cmd else
                     "Links aren't set up on this PC yet.")

    def set_up():
        exe = installed() or (Path(sys.executable) if getattr(sys, "frozen", False) else None)
        if exe is None:
            return status.config(text="Links need the app installed (or run from ChannelMirror.exe).")
        link_register(exe)
        show_reg()
        status.config(text="channelmirror:// links now open Channel Mirror.")
    ttk.Button(rr, text="Set up links", style="Tool.TButton", command=set_up).pack(side="left")
    ttk.Button(rr, text="Remove", style="Tool.TButton", command=lambda: (link_unregister(), show_reg())).pack(
        side="left", padx=6)
    ttk.Label(lf, text="MAKE A LINK", style="Field.TLabel").pack(anchor="w", pady=(10, 0))
    mr = ttk.Frame(lf)
    mr.pack(fill="x")
    ttk.Combobox(mr, textvariable=v["make_to"], values=list(names), state="readonly", width=34).pack(side="left")

    def add_make():
        make_files.extend(Path(f) for f in filedialog.askopenfilenames(parent=page, title="Files for the link"))
        v["made"].set(link_make(names[v["make_to"].get()], make_files))
    ttk.Button(mr, text="Add files...", style="Tool.TButton", command=add_make).pack(side="left", padx=6)
    ttk.Button(mr, text="Clear", style="Tool.TButton",
               command=lambda: (make_files.clear(), v["made"].set(""))).pack(side="left")
    v["make_to"].trace_add("write", lambda *_: make_files and v["made"].set(
        link_make(names[v["make_to"].get()], make_files)))
    me = ttk.Frame(lf)
    me.pack(fill="x", pady=(4, 0))
    ttk.Entry(me, textvariable=v["made"], width=52).pack(side="left", fill="x", expand=True)
    ttk.Button(me, text="Copy", style="Tool.TButton", command=lambda: copy(v["made"].get())).pack(side="left", padx=4)
    ttk.Label(lf, text="OPEN A LINK", style="Field.TLabel").pack(anchor="w", pady=(10, 0))
    oe = ttk.Frame(lf)
    oe.pack(fill="x", pady=(0, 4))
    ttk.Entry(oe, textvariable=v["open"], width=52).pack(side="left", fill="x", expand=True)
    ttk.Button(oe, text="Open", style="Tool.TButton", command=lambda: open_link(v["open"].get())).pack(
        side="left", padx=4)

    # receive
    rf = ttk.LabelFrame(right, text="Receive from other devices  (home network)")
    rf.pack(fill="x")
    ttk.Label(rf, text="Start, then open the pairing link on the other device (phone, laptop, another PC) - it shows "
                       "a page to send files. Each batch shows here and is placed only when you accept it.",
              style="Hint.TLabel", wraplength=520, justify="left").pack(anchor="w")
    r1 = ttk.Frame(rf)
    r1.pack(fill="x", pady=(6, 0))
    start_b = ttk.Button(r1, text="Start receiving", style="Accent.TButton", command=lambda: toggle())
    start_b.pack(side="left")
    ttk.Label(r1, text="Port").pack(side="left", padx=(12, 0))
    ttk.Spinbox(r1, textvariable=v["port"], from_=1024, to=65535, width=6).pack(side="left", padx=4)
    ttk.Label(r1, text="Code").pack(side="left", padx=(8, 0))
    ttk.Label(r1, textvariable=v["code"], font=("Segoe UI", 12, "bold")).pack(side="left", padx=4)
    ttk.Button(r1, text="New code", style="Tool.TButton", command=lambda: new_code()).pack(side="left", padx=4)
    r2 = ttk.Frame(rf)
    r2.pack(fill="x", pady=(6, 0))
    ttk.Entry(r2, textvariable=v["pair"], width=44, state="readonly").pack(side="left", fill="x", expand=True)
    ttk.Button(r2, text="Copy", style="Tool.TButton", command=lambda: copy(v["pair"].get())).pack(side="left", padx=4)
    recv_l = ttk.Label(rf, style="Hint.TLabel", wraplength=520, justify="left")
    recv_l.pack(anchor="w", pady=(4, 4))

    # send
    sf = ttk.LabelFrame(right, text="Send to another device")
    sf.pack(fill="x", pady=(10, 0))
    ttk.Label(sf, text="Paste the pairing link the other Channel Mirror shows (Receive, Start).", style="Hint.TLabel"
              ).pack(anchor="w")
    ttk.Entry(sf, textvariable=v["dest"], width=52).pack(fill="x", pady=(4, 0))
    s2 = ttk.Frame(sf)
    s2.pack(fill="x", pady=(4, 0))
    ttk.Combobox(s2, textvariable=v["send_to"], values=list(names), state="readonly", width=34).pack(side="left")
    ttk.Label(s2, text="from").pack(side="left", padx=(8, 0))
    ttk.Entry(s2, textvariable=v["device"], width=16).pack(side="left", padx=4)
    s3 = ttk.Frame(sf)
    s3.pack(fill="x", pady=(4, 4))
    send_l = ttk.Label(sf, style="Hint.TLabel")

    def add_send():
        send_files.extend(Path(f) for f in filedialog.askopenfilenames(parent=page, title="Files to send"))
        send_l.config(text=f"{len(send_files)} file(s): " + ", ".join(f.name for f in send_files[:5]) +
                      (" ..." if len(send_files) > 5 else ""))
    ttk.Button(s3, text="Add files...", style="Tool.TButton", command=add_send).pack(side="left")
    ttk.Button(s3, text="Clear", style="Tool.TButton",
               command=lambda: (send_files.clear(), send_l.config(text=""))).pack(side="left", padx=4)
    send_b = ttk.Button(s3, text="Send", style="Accent.TButton", command=lambda: send())
    send_b.pack(side="right")
    send_l.pack(anchor="w")

    def copy(text):
        if text:
            page.clipboard_clear()
            page.clipboard_append(text)
            status.config(text="Copied.")

    def new_code():
        v["code"].set(f"{secrets.randbelow(10 ** 8):08d}")
        if st["server"]:
            st["server"].code = v["code"].get()
            v["pair"].set(link_pair_url(link_lan_ip(), st["server"].port, v["code"].get()))
        save()

    def toggle():
        if st["server"]:
            st["server"].stop()
            st["server"] = None
            start_b.config(text="Start receiving")
            v["pair"].set("")
            recv_l.config(text="Stopped - nothing can be sent to this PC now.")
            return
        if link_public_network() and not messagebox.askyesno(
                "Receive", "Windows has this network marked Public (like cafe or hotel Wi-Fi). Other people on it "
                "could try to send files here.\n\nOnly start on your own home network. Start anyway?", parent=page):
            return
        v["code"].set(f"{secrets.randbelow(10 ** 8):08d}")  # a fresh code every start
        try:
            port = int(v["port"].get())
            st["server"] = LinkServer(port, v["code"].get(), LINK_INBOX / "pending",
                                      lambda info: events.put(("batch", info)))
        except (ValueError, OSError) as e:
            return messagebox.showerror("Receive", f"Couldn't start on port {v['port'].get()}:\n{e}", parent=page)
        start_b.config(text="Stop receiving")
        v["pair"].set(link_pair_url(link_lan_ip(), st["server"].port, v["code"].get()))
        recv_l.config(text="Receiving. Open the pairing link on the other device. It's plain http on your own "
                           "network - only use it at home. (Windows may ask once whether Channel Mirror may use the "
                           "network - allow private networks only.)")
        save()

    def send():
        if not send_files:
            return messagebox.showinfo("Send", "Add the files to send first.", parent=page)
        dest, files, to, dev = v["dest"].get(), list(send_files), names[v["send_to"].get()], v["device"].get()
        send_b.state(["disabled"])
        status.config(text=f"Sending {len(files)} file(s)...")

        def done(res):
            send_b.state(["!disabled"])
            if isinstance(res, Exception):
                status.config(text=f"Not sent: {res}")
                return messagebox.showerror("Send", f"Not sent:\n{res}", parent=page)
            status.config(text=f"Sent {res} file(s) - they're waiting to be accepted on the other device.")
            save()
        ui_background(page, lambda: link_send(dest, files, to, dev), done)

    def arrived(files, target, source):
        """Show what came, then place it (accepted) or delete the received copies (declined). Accepted copies move
        to Incoming\\Received (keys will play them from there); waiting ones are cleared on Stop."""
        to = ui_incoming(page, files, target, source)
        if to:
            import time
            keep = LINK_INBOX / "Received" / time.strftime("%Y-%m-%d %H-%M-%S")
            placed = []
            for f in map(Path, files):
                if f.is_relative_to(LINK_INBOX / "pending"):
                    keep.mkdir(parents=True, exist_ok=True)
                    dst, n = keep / f.name, 2
                    while dst.exists():
                        dst, n = keep / f"{f.stem} ({n}){f.suffix}", n + 1
                    shutil.move(f, dst)
                    f = dst
                placed.append(f)
            files = placed
            deliver(to, files)
            status.config(text=f"Accepted {len(files)} file(s) from {source} into {LINK_TARGETS[to]}.")
        else:
            for f in files:
                if Path(f).is_relative_to(LINK_INBOX):  # only copies that were received, never your own files
                    Path(f).unlink(missing_ok=True)
            status.config(text=f"Declined {len(files)} file(s) from {source}.")

    def open_link(text):
        """A channelmirror:// link: its files (and downloads) shown, then placed once accepted."""
        try:
            lk = link_parse(text)
        except ValueError as e:
            return status.config(text=f"Not a link Channel Mirror can open: {e}")
        files = [f for f in lk["files"] if f.is_file() and f.suffix.lower() in LINK_EXT]
        missing = len(lk["files"]) - len(files)
        if not lk["urls"]:
            if not files:
                return status.config(text="That link has no files that exist on this PC.")
            return arrived(files, lk["to"], "a link from outside the app" +
                           (f" ({missing} file(s) not found)" if missing else ""))
        if not messagebox.askyesno("Download?", "A link wants to download:\n\n" + "\n".join(lk["urls"][:10]) +
                                   ("\n..." if len(lk["urls"]) > 10 else "") + "\n\nDownload them? (You'll see them "
                                   "before anything is placed.)", parent=page):
            return status.config(text="Download skipped.")
        status.config(text=f"Downloading {len(lk['urls'])} file(s) from the link...")
        folder = LINK_INBOX / "pending" / f"link-{secrets.token_hex(4)}"

        def fetched(res):
            if isinstance(res, Exception):
                shutil.rmtree(folder, ignore_errors=True)
                return status.config(text=f"Download failed (nothing kept): {res}")
            arrived(files + res, lk["to"], "a link from outside the app: " + ", ".join(lk["urls"][:3]))
        ui_background(page, lambda: [link_fetch(u, folder) for u in lk["urls"]], fetched)

    def poll():
        try:
            while True:
                kind, x = events.get_nowait()
                try:  # one bad batch / link never stops the ones after it
                    if kind == "batch":
                        recv_l.config(text=f"{x['time']}: {len(x['files'])} file(s) from {x['from']} "
                                           f"({x['address']})")
                        page.winfo_toplevel().deiconify()
                        arrived(x["files"], x["target"], f"{x['from']} ({x['address']}, another device)")
                    else:
                        page.winfo_toplevel().deiconify()
                        open_link(x)
                except Exception as e:
                    status.config(text=f"Couldn't handle what arrived: {e}")
        except queue.Empty:
            pass
        finally:
            page.after(300, poll)

    def save():
        try:
            lc.update(port=int(v["port"].get()))
        except ValueError:
            pass
        lc.pop("code", None)  # the code is never kept
        lc.update(dest=v["dest"].get(), device=v["device"].get())

    def stop():
        if st["server"]:
            st["server"].stop()
            st["server"] = None
    show_reg()
    poll()
    return {"open_link": lambda text: events.put(("link", text)), "stop": stop, "save": save,
            "toggle": toggle, "vars": v, "state": st, "make_files": make_files, "send_files": send_files}


def ui_grow_kind(parent):
    """Asked before a single-sound key takes more sounds: "Random Action", "Multi Action", or None (cancelled)."""
    from tkinter import messagebox
    ans = messagebox.askyesnocancel("Add sounds", "This key plays one sound. Turn it into a Random Action (one random "
                                    "sound per press)?\n\nNo = Multi Action (all play together)", parent=parent)
    return None if ans is None else "Random Action" if ans else "Multi Action"


def ui_new_key_dialog(parent, files, kinds=None):
    """Make keys from files: pick what they become and the settings every sound gets. kinds = the choices
    (default: Single sound for one file, Random / Multi Action for several; also "Folder" and "One key per sound").
    Returns (kind, name, [Play Audio actions]), or None when cancelled."""
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(parent)
    win.title(f"New key - {len(files)} sound(s)")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="\n".join(Path(f).name for f in files[:8]) + (f"\n... and {len(files) - 8} more"
              if len(files) > 8 else ""), style="Hint.TLabel").pack(anchor="w")
    kinds = kinds or (("Single sound",) if len(files) == 1 else ("Random Action", "Multi Action"))
    hints = {"Single sound": "plays it", "Random Action": "one random sound per press",
             "Multi Action": "all play together", "Folder": "a folder key; inside, one key per sound in this order",
             "One key per sound": "on the free keys, in this order",
             "Folder per subfolder": "named after it; inside, one key per sound in name order"}
    kind = tk.StringVar(value=kinds[0])
    kf = ttk.Frame(body)
    kf.pack(fill="x", pady=(10, 0))
    for k in kinds:
        ttk.Radiobutton(kf, text=f"{k} ({hints[k]})", variable=kind, value=k).pack(anchor="w")
    name = tk.StringVar(value=(Path(files[0]).stem if kinds == ("Single sound",) else Path(files[0]).parent.name)[:20])
    if not {"One key per sound", "Folder per subfolder"} & set(kinds):  # named after their files / folders
        ttk.Label(body, text="NAME", style="Field.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Entry(body, textvariable=name, width=24).pack(anchor="w")
    v = {"mode": tk.StringVar(value=SD_MODES[0]), "fade": tk.StringVar(value=SD_FADES[0]),
         "fade_len": tk.StringVar(value="1"), "volume": tk.IntVar(value=100),
         "output": tk.StringVar(value=SD_DEFAULT_OUT)}
    ui_play_choice(body, v["mode"]).pack(anchor="w", pady=(12, 0))
    ttk.Label(body, text="EVERY SOUND GETS", style="Field.TLabel").pack(anchor="w", pady=(10, 0))
    ui_sound_form(body, v).pack(fill="x", pady=4)
    result = [None]

    def ok():
        single = kind.get() == "Single sound"
        plays = [sd_play(Path(f), name.get() if single else Path(f).stem[:20], v["mode"].get(), v["fade"].get(),
                         v["fade_len"].get(), int(v["volume"].get()), v["output"].get()) for f in files]
        result[0] = (kind.get(), name.get(), plays)
        win.destroy()
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(14, 0))
    ttk.Button(bar, text="Create", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.grab_set()
    win.wait_window()
    return result[0]


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
    name = tk.Text(look, height=3, width=24, relief="flat", bd=0, highlightthickness=1, wrap="none", undo=True,
                   highlightbackground=UI["border"], highlightcolor=UI["accent"])
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
    swatch = tk.Label(cbox, width=3, bg=color.get() or UI["panel"], **UI_SWATCH)
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
                    se.get("volume", 100), sd_out_name(se.get("outputType")))

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
            v["output"].set(sd_out_name(se["outputType"]) if se.get("outputType") else SD_DEFAULT_OUT)
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

        def add_sounds(folder=False):
            files = ui_pick_sounds(win, "Add every sound in a folder to this key" if folder else
                                   "Add sounds to this key", folder)
            if not files:
                return
            kind = ui_grow_kind(win) if inner() is None else "Random Action"
            if kind:  # new sounds copy the selected sound's playback settings
                work[0] = sd_add_sounds(work[0], sd_plays_like(files, cur[0]), kind)
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
        def apply_all():
            if not cur[0]:
                return
            sd_set_sound(sd_sounds(work[0]), v["mode"].get(), v["fade"].get(), v["fade_len"].get(),
                         int(v["volume"].get()), output=v["output"].get())
            fill(int(tv.selection()[0]) if tv.selection() else 0)
        for text, cmd in (("Add sounds...", add_sounds), ("Add folder...", lambda: add_sounds(True)),
                          ("Apply to all sounds", apply_all),
                          ("Remove sound", lambda: reorder(0)),
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


def ui_bulk_dialog(parent, actions):
    """Edit many keys at once. Each field starts on the value the keys share, or Keep when they differ; only
    fields moved off their starting value are applied. Returns the changes as a dict, or None when cancelled:
    title, mode, fade, fade_len, volume, output (sounds) and style (Stream Deck title fields)."""
    import tkinter as tk
    from tkinter import colorchooser, messagebox, ttk
    keep = "Keep (mixed)"
    sounds = [s for a in actions for s in sd_sounds(a)]
    se = [s.get("Settings", {}) for s in sounds]
    states = [(a.get("States") or [{}])[0] for a in actions]
    pick = lambda t, i: t[i] if isinstance(i, int) and 0 <= i < len(t) else t[0]
    same = lambda vals, other=keep: vals[0] if vals and all(x == vals[0] for x in vals) else other
    start = {"title": same([sd_title(a) for a in actions], ""),
             "show": same(["Show" if x.get("ShowTitle", True) else "Hide" for x in states]),
             "size": same([str(x.get("FontSize", "")) for x in states]) or keep,
             "align": same([x.get("TitleAlignment") or "bottom" for x in states]),
             "mode": same([pick(SD_MODES, x.get("actionType")) for x in se]),
             "fade": same([pick(SD_FADES, x.get("fadeType")) for x in se]),
             "fade_len": same([str(x.get("fadeLen", 1)) for x in se]),
             "volume": same([str(x.get("volume", 100)) for x in se]),
             "output": same([sd_out_name(x["outputType"]) if x.get("outputType") else SD_DEFAULT_OUT for x in se])}
    v = {k: tk.StringVar(value=val) for k, val in start.items()}
    color, result = tk.StringVar(), [None]
    win = tk.Toplevel(parent)
    win.title(f"Edit {len(actions)} keys together")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, style="Hint.TLabel", text=f"{len(actions)} keys, {len(sounds)} sounds. Fields showing "
              f"'{keep}' differ between the keys and are left alone unless you change them.").pack(anchor="w")

    def grid(frame, rows):
        for r, (label, w) in enumerate(rows):
            ttk.Label(frame, text=label, width=16).grid(row=r, column=0, sticky="w", pady=3)
            w.grid(row=r, column=1, sticky="w", pady=3)
    kf = ttk.LabelFrame(body, text="Keys")
    kf.pack(fill="x", pady=(10, 0))
    cf = ttk.Frame(kf)
    sw = tk.Label(cf, width=3, bg=UI["panel"], **UI_SWATCH)
    sw.pack(side="left", padx=(0, 6))

    def pick_color():
        c = colorchooser.askcolor("#ffffff", parent=win, title="Name colour")[1]
        if c:
            color.set(c)
            sw.config(bg=c)
    ttk.Button(cf, text="Pick...", style="Tool.TButton", command=pick_color).pack(side="left")
    combo = lambda frame, key, values, width=18, ro=True: ttk.Combobox(
        frame, textvariable=v[key], values=(keep,) + tuple(values), state="readonly" if ro else "normal", width=width)
    grid(kf, (("Name", ttk.Entry(kf, textvariable=v["title"], width=28)),
              ("Show name", combo(kf, "show", ("Show", "Hide"))),
              ("Font size", combo(kf, "size", ("7", "8", "9", "10", "11", "12", "14", "16", "18", "20", "24"))),
              ("Name position", combo(kf, "align", ("top", "middle", "bottom"))),
              ("Name colour", cf)))
    if start["title"] == "" and len({sd_title(a) for a in actions}) > 1:
        ttk.Label(kf, text="(names differ - leave blank to keep each key's own name)", style="Hint.TLabel").grid(
            row=0, column=2, sticky="w", padx=6)
    sf = ttk.LabelFrame(body, text="Sounds on these keys")
    sf.pack(fill="x", pady=(10, 0))
    if sounds:
        out = combo(sf, "output", (), 44, ro=False)
        out.config(postcommand=lambda: out.config(values=(keep,) + tuple(sd_output_choices())))
        grid(sf, (("Action", combo(sf, "mode", SD_MODES)), ("Fade", combo(sf, "fade", SD_FADES)),
                  ("Fade length (s)", combo(sf, "fade_len", ("1", "2", "3", "4", "5"), 14)),
                  ("Volume (0-100)", combo(sf, "volume", [str(n) for n in range(0, 101, 10)], 14, ro=False)),
                  ("Output device", out)))
    else:
        ttk.Label(sf, text="None of these keys plays a sound.", style="Hint.TLabel").pack(anchor="w")

    def ok():
        ch = {k: x.get().strip() for k, x in v.items()
              if x.get().strip() != start[k] and x.get().strip() != keep and (k != "title" or x.get().strip())}
        if "volume" in ch:
            try:
                ch["volume"] = int(ch["volume"])
                assert 0 <= ch["volume"] <= 100
            except (ValueError, AssertionError):
                return messagebox.showerror("Volume", "Volume is a whole number from 0 to 100.", parent=win)
        style = {}
        if "show" in ch:
            style["ShowTitle"] = ch.pop("show") == "Show"
        if "size" in ch:
            style["FontSize"] = int(ch.pop("size"))
        if "align" in ch:
            style["TitleAlignment"] = ch.pop("align")
        if color.get():
            style["TitleColor"] = color.get()
        if style:
            ch["style"] = style
        result[0] = ch
        win.destroy()
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(14, 0))
    ttk.Button(bar, text=f"Apply to {len(actions)} keys", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.bind("<Return>", lambda e: ok())
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
                     "(Jump to Multi / Random at the top picks one). The list shows the devices by name, as Stream "
                     "Deck does; the app saves each device's Windows id, which is what Stream Deck itself saves.",
    "Key names and look": "Rename keys in bulk and change how their names look. Double-click a key to edit one.",
    "Arrange keys": "You can also drag keys on the grid to move or swap them, and right-click a key for more.",
    "Fix missing sound files": "Points broken sound keys (red) at a file with the same name anywhere in this folder "
                               "- handy for profiles copied from another computer.",
}


def sd_editor_tab(page, cfg, made=()):
    """Edit the buttons of profiles already in the local Stream Deck app: select keys, use a tool, save.
    made = files the Channel Mirror tab wrote this session (offered by the import window).
    Returns {pending, save, saving} so the window can send unsent changes when it closes; None without Stream Deck."""
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
    blobs = {}  # icon file -> bytes, copied with keys; written with the next send
    listeners, hooks = [], {}  # other tabs redrawn after each change; hooks["import"] opens the import tab
    st = {"pages": [], "named": [], "idx": None, "page": None, "sel": [], "back": []}
    hist = {"undo": [], "redo": [], "clip": None}
    FOLDER, PARENT = SD_FOLDER, SD_PARENT

    # toolbar
    bar = ttk.Frame(page, padding=(10, 10, 10, 4))
    bar.pack(fill="x")
    prof_v, multi_v, multi_map = tk.StringVar(value=labels_[0] if labels_ else ""), tk.StringVar(), {}
    ttk.Label(bar, text="Profile").pack(side="left")
    ttk.Combobox(bar, textvariable=prof_v, values=labels_, state="readonly", width=36).pack(side="left", padx=(6, 14))
    ttk.Label(bar, text="Jump to Multi / Random").pack(side="left")
    multi_cb = ttk.Combobox(bar, textvariable=multi_v, state="readonly", width=36)
    multi_cb.pack(side="left", padx=6)
    bar2 = ttk.Frame(page, padding=(10, 0, 10, 4))  # its own row, so it stays on screen in a small window
    bar2.pack(fill="x")
    save_btn = ttk.Button(bar2, text="Save to Stream Deck", style="Accent.TButton")
    save_btn.pack(side="left")
    auto_v = tk.BooleanVar(value=cfg.get("sd_autosend", True))
    auto_v.trace_add("write", lambda *_: (cfg.update(sd_autosend=auto_v.get()), changed()))
    ab = ttk.Checkbutton(bar2, text="Send changes automatically", variable=auto_v)
    ab.pack(side="left", padx=(10, 0))
    Tip(ab, "Each change goes to Stream Deck about 1.5 s after you stop editing. Stream Deck closes and reopens "
            "for a few seconds to take it. Off = changes wait for Save to Stream Deck (Ctrl+S).")
    tbtn = {}
    for name, text, tip in (("revert", "Revert", "Throw away every unsaved change (can be undone)"),
                            ("redo", "Redo", "Ctrl+Y"), ("undo", "Undo", "Ctrl+Z")):
        tbtn[name] = ttk.Button(bar2, text=text, style="Tool.TButton")
        tbtn[name].pack(side="right", padx=(6, 0))
        Tip(tbtn[name], tip)
    unsent_l = ttk.Label(bar2, font=("Segoe UI", 9, "bold"))
    unsent_l.pack(side="left", padx=(12, 0))

    panes = ttk.PanedWindow(page, orient="horizontal")
    panes.pack(fill="both", expand=True, padx=10, pady=6)
    pages_f = ttk.LabelFrame(panes, text="Pages")
    left = ttk.LabelFrame(panes, text="Keys")
    right = ttk.LabelFrame(panes, text="Tools for the selected keys")
    panes.add(pages_f, weight=1)
    panes.add(left, weight=3)
    panes.add(right, weight=2)
    status = ttk.Label(page, style="Status.TLabel", anchor="w",
                       text="Pick a profile and page. Click keys to select them (Ctrl+click adds).")
    status.pack(fill="x", padx=12, pady=(0, 8))

    # pages: list with per-page counts, prev / next, jump to problems, folder back
    nav = ttk.Frame(pages_f)
    nav.pack(fill="x")
    prev_b = ttk.Button(nav, text="< Prev", style="Tool.TButton", command=lambda: go_page(st["idx"] - 1))
    next_b = ttk.Button(nav, text="Next >", style="Tool.TButton", command=lambda: go_page(st["idx"] + 1))
    prev_b.pack(side="left")
    next_b.pack(side="left", padx=4)
    count_l = ttk.Label(nav, style="Hint.TLabel")
    count_l.pack(side="left", padx=6)
    Tip(prev_b, "Previous page (PgUp)")
    Tip(next_b, "Next page (PgDn)")
    pcols = ("page", "keys", "sounds", "missing")
    ptv = ttk.Treeview(pages_f, columns=pcols, show="headings", selectmode="browse", height=8)
    for c, h, w in zip(pcols, ("Page", "Keys", "Sounds", "Missing"), (150, 45, 55, 60)):
        ptv.heading(c, text=h)
        ptv.column(c, width=w, stretch=c == "page", anchor="w" if c == "page" else "center")
    ptv.tag_configure("missing", foreground=UI["bad"])
    ptv.tag_configure("edited", font=("Segoe UI", 10, "bold"))
    ptv.pack(fill="both", expand=True, pady=6)
    nav2 = ttk.Frame(pages_f)
    nav2.pack(fill="x")
    issue_b = ttk.Button(nav2, text="Next page with missing sounds", style="Tool.TButton",
                         command=lambda: next_issue())
    issue_b.pack(fill="x")
    back_b = ttk.Button(nav2, text="Back (out of folder)", style="Tool.TButton", command=lambda: go_back())
    back_b.pack(fill="x", pady=(4, 0))
    Tip(back_b, "Alt+Left. Also: double-click the Parent Folder key")
    ttk.Label(pages_f, text="Red = has missing sound files\nBold * = unsaved changes\nDouble-click a folder key "
                            "to open it", style="Hint.TLabel", justify="left").pack(anchor="w", pady=(6, 0))

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
    sb2 = ttk.Frame(left)
    sb2.pack(fill="x", pady=(4, 0))
    eb = ttk.Button(sb2, text="Edit selected...", style="Tool.TButton", command=lambda: bulk_edit())
    eb.pack(side="left")
    ib = ttk.Button(sb2, text="Import sounds into folders...", style="Tool.TButton", command=lambda: import_sounds())
    ib.pack(side="left", padx=(6, 0))
    Tip(ib, "Each sound its own key (play once or loop), in folders of N; you pick the keys the folders go on, on any "
            "page, and see which keys are in use. Volume, levels and output too.")
    Tip(eb, "Edit every selected key in one window (Ctrl+E / Enter)")

    def tile(pos):
        a, on = keys_now().get(pos), pos in st["sel"]
        c, r_ = map(int, pos.split(","))
        bg = (UI["accent"] if on else UI["missing"] if a and sd_missing(a) else UI["sound"] if a and sd_sounds(a)
              else UI["other"] if a else UI["empty"])
        fg = UI["on_accent"] if on else UI["text"] if a else UI["muted"]
        if not a:
            return f"{c + 1},{r_ + 1}", bg, fg
        return f"{(sd_title(a).replace(chr(10), ' ') or '-')[:22]}\n{sd_kind(a)[:16]}", bg, fg

    def tip_for(pos):
        a = keys_now().get(pos)
        c, r_ = map(int, pos.split(","))
        if not a:
            return (f"Empty key {c + 1},{r_ + 1}\nDouble-click to add a sound key; right-click for a new folder of "
                    "sounds, or to fill the free keys from here in order.")
        lines = [f"Key {c + 1},{r_ + 1}: {sd_title(a).replace(chr(10), ' ') or '(no name)'}  -  {sd_kind(a)}"]
        for s in sd_sounds(a)[:10]:
            se = s.get("Settings", {})
            miss = "" if Path(se.get("path", "")).is_file() else "   MISSING"
            lines.append(f"  - {Path(se.get('path', '')).name}  ({SD_MODES[se.get('actionType', 0)] if se.get('actionType', 0) < 4 else '?'}"
                         f", vol {se.get('volume', '?')}){miss}")
        if len(sd_sounds(a)) > 10:
            lines.append(f"  ...and {len(sd_sounds(a)) - 10} more")
        how = ("Double-click to open this folder" if a.get("UUID") == FOLDER else
               "Double-click to go back out of the folder" if a.get("UUID") == PARENT else "Double-click to edit")
        return "\n".join(lines + [f"{how}; drag to move; right-click for more."])

    def click(pos, e):
        if e.state & 0x0001 and st.get("anchor"):  # Shift: the rectangle from the last clicked key
            c1, r1 = map(int, st["anchor"].split(","))
            c2, r2 = map(int, pos.split(","))
            st["sel"] = [f"{c},{r_}" for r_ in range(min(r1, r2), max(r1, r2) + 1)
                         for c in range(min(c1, c2), max(c1, c2) + 1)]
        else:
            if e.state & 0x0004:  # Ctrl: add or remove one key
                st["sel"].remove(pos) if pos in st["sel"] else st["sel"].append(pos)
            else:
                st["sel"] = [] if st["sel"] == [pos] else [pos]
            st["anchor"] = pos
        draw()

    def double(pos):
        a = keys_now().get(pos)
        if a and a.get("UUID") == FOLDER:
            return open_folder(pos)
        if a and a.get("UUID") == PARENT:
            return go_back()
        return edit_key(pos) if a else new_key(pos)

    deck = DeckGrid(left, tile, on_click=click, on_double=lambda p, e: double(p),
                    on_menu=lambda p, e: key_menu(p, e), on_drop=lambda a, b: drop(a, b), tip=tip_for)
    deck.frame.pack(pady=(10, 6))
    legend = ttk.Frame(left)
    legend.pack(fill="x")
    for color, text in ((UI["sound"], "sound"), (UI["missing"], "file missing"), (UI["other"], "other action"),
                        (UI["accent"], "selected")):
        tk.Label(legend, bg=color, width=2, **UI_SWATCH).pack(side="left")
        ttk.Label(legend, text=text, style="Hint.TLabel").pack(side="left", padx=(4, 14))
    ttk.Label(legend, text="Ctrl/Shift+click = select several  -  Drag = move/swap  -  Double-click = edit",
              style="Hint.TLabel").pack(side="right")
    dcols = ("key", "name", "type", "mode", "fade", "volume", "output", "file")
    dt = ttk.Frame(left)
    dt.pack(fill="both", expand=True, pady=(8, 0))
    details = ttk.Treeview(dt, columns=dcols, show="headings", height=4, selectmode="extended")
    for c, h, w in zip(dcols, ("Key", "Name", "Type", "Action", "Fade", "Vol", "Output", "File"),
                       (40, 90, 70, 90, 95, 40, 100, 140)):  # they stretch; small starting widths fit small windows
        details.heading(c, text=h)
        details.column(c, width=w, stretch=c in ("name", "file", "output"))
    dys = ttk.Scrollbar(dt, command=details.yview)
    details.config(yscrollcommand=dys.set)
    dys.pack(side="right", fill="y")
    details.pack(fill="both", expand=True)
    ttk.Label(left, text="Double-click a cell to change it - select several rows first to change them all at once.",
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
    SCOPES = ("Selected keys (a folder = every sound inside it)", "Every sound key on this page",
              "Every sound key in this profile (all pages)")
    scope_v = tk.StringVar(value=SCOPES[0])
    arow = ttk.Frame(opts)
    arow.pack(fill="x", pady=(8, 0))
    ttk.Label(arow, text="Apply to").pack(side="left")
    ttk.Combobox(arow, textvariable=scope_v, values=SCOPES, state="readonly", width=34).pack(side="left", padx=6)
    arow2 = ttk.Frame(opts)  # its own row: always on screen
    arow2.pack(fill="x", pady=(6, 0))
    apply_btn = ttk.Button(arow2, text="Apply", style="Accent.TButton")
    apply_btn.pack(side="right")
    frames = {g: ttk.Frame(holder) for g in goals}
    o = {}

    def row(g, label, make):
        fr = ttk.Frame(frames[g])
        fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=14).pack(side="left")
        make(fr)
        return fr

    def combo(g, key, label, values, width=22):
        o[key] = tk.StringVar(value=values[0])
        row(g, label, lambda fr: ttk.Combobox(fr, textvariable=o[key], values=values, state="readonly",
                                               width=width).pack(side="left"))

    def entry(g, key, label, value="", width=24):
        o[key] = tk.StringVar(value=value)
        row(g, label, lambda fr: ttk.Entry(fr, textvariable=o[key], width=width).pack(side="left"))

    g = goals[0]
    combo(g, "goal", "Purpose", tuple(SD_GOALS), 34)
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
    o["scale"] = tk.IntVar(value=80)
    o["tune"] = tk.StringVar(value=SD_AUTO)

    sd_set_levels(cfg.get("obs_levels"))

    def tune_box(fr):
        ttk.Combobox(fr, textvariable=o["tune"], values=list(SD_TUNE), state="readonly", width=34).pack(side="left")
        fr2 = ttk.Frame(fr.master)  # under it: the levels and the button to change them
        fr2.pack(fill="x", padx=(120, 0))
        lv = ttk.Label(fr2, text=f"{sd_levels_text()}; within {SD_TOL:.0f} dB is left alone", style="Hint.TLabel",
                       wraplength=300, justify="left")
        ttk.Button(fr2, text="My OBS levels...", style="Tool.TButton", command=lambda: ui_obs_levels(page, cfg) and lv.config(
            text=f"{sd_levels_text()}; within {SD_TOL:.0f} dB is left alone")).pack(side="left", padx=(0, 8))
        lv.pack(side="left")
        lv.bind("<Map>", lambda e: lv.config(text=f"{sd_levels_text()}; within {SD_TOL:.0f} dB is left alone"))
    for how, text, make in (("set", "Set to", lambda fr: ui_volume(fr, o["vol"], 180).pack(side="left")),
                            ("step", "Change by (+/-)", lambda fr: ttk.Spinbox(fr, textvariable=o["step"], from_=-100,
                                                                              to=100, width=6).pack(side="left")),
                            ("scale", "Scale by %", lambda fr: (
                                ttk.Spinbox(fr, textvariable=o["scale"], from_=1, to=400, width=6).pack(side="left"),
                                ttk.Label(fr, text="keeps them in proportion: 50 = half each volume setting, 150 = "
                                                   "half as much again (100 at most)", style="Hint.TLabel").pack(
                                    side="left", padx=6))),
                            ("match", "Match loudness", lambda fr: ttk.Label(
                                fr, text="measures each file; louder ones are turned down to the quietest",
                                style="Hint.TLabel").pack(side="left")),
                            ("tune", "Tune to level", tune_box),
                            ("check", "Check levels", lambda fr: ttk.Label(
                                fr, text="listens to each sound and lists where it sits; changes nothing until you "
                                         "press Tune in the list", style="Hint.TLabel").pack(side="left"))):
        fr = ttk.Frame(frames[g])
        fr.pack(fill="x", pady=4)
        ttk.Radiobutton(fr, text=text, variable=o["vol_how"], value=how, width=16).pack(side="left")
        make(fr)
    g = goals[3]
    o["output"] = tk.StringVar(value=SD_DEFAULT_OUT)

    def out_box(fr):
        cb = ttk.Combobox(fr, textvariable=o["output"], width=34)
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
        sw = tk.Label(fr, width=3, bg=UI["panel"], **UI_SWATCH)

        def pick():
            c = colorchooser.askcolor(o["color"].get() or "#ffffff", title="Name colour")[1]
            if c:
                o["color"].set(c)
                sw.config(bg=c, text="")
        sw.pack(side="left", padx=(0, 6))
        ttk.Button(fr, text="Pick...", style="Tool.TButton", command=pick).pack(side="left")
        st_["swatch"] = sw
    st_ = {}
    row(g, "Name colour", color_row)
    row(g, "", lambda fr: ttk.Button(fr, text="Keep", style="Tool.TButton", command=lambda: (
        o["color"].set(""), st_["swatch"].config(bg=UI["panel"]))).pack(side="left"))  # under Pick: fits small windows
    g = goals[5]
    o["arr"], o["slot"], o["ctitle"] = tk.StringVar(value="combine"), tk.StringVar(value="1,1"), tk.StringVar()
    o["ckind"] = tk.StringVar(value="Random Action")
    for how, text, extra in (
            ("combine", "Combine selected into one",
             lambda fr: (ttk.Combobox(fr, textvariable=o["ckind"], values=("Random Action", "Multi Action"),
                                      state="readonly", width=13).pack(anchor="w"),
                         (lambda f2: (f2.pack(anchor="w", pady=(3, 0)),  # the name on the line under it
                                      ttk.Label(f2, text="named").pack(side="left"),
                                      ttk.Entry(f2, textvariable=o["ctitle"], width=14).pack(side="left", padx=6)
                                      ))(ttk.Frame(fr)))),
            ("split", "Split Multi / Random keys into single keys", lambda fr: None),
            ("move", "Move the selected key to (col,row)",
             lambda fr: ttk.Entry(fr, textvariable=o["slot"], width=6).pack(side="left")),
            ("stop", "Add a 'Stop all audio' key at (col,row)",
             lambda fr: ttk.Entry(fr, textvariable=o["slot"], width=6).pack(side="left")),
            ("delete", "Delete the selected keys", lambda fr: None)):
        fr = ttk.Frame(frames[g])
        fr.pack(fill="x", pady=3)
        ttk.Radiobutton(fr, text=text, variable=o["arr"], value=how).pack(anchor="w")
        sub = ttk.Frame(fr)  # its box / choices under it, so they stay on screen in a narrow window
        sub.pack(fill="x", padx=(26, 0))
        extra(sub)
    g = goals[6]
    entry(g, "folder", "Search folder", str(Path.home() / "Music"), 30)
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
    def disk(p):
        """The page as Stream Deck has it; None for a new folder's page that hasn't been sent yet."""
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def cur_page():
        p = st["page"]
        if p and p not in edits:
            edits[p] = disk(p) or {}
        return edits.get(p)

    def keys_now():  # read-only view; sd_keypad() would normalise the json and make the page look edited
        ctrl = next((c for c in (cur_page() or {}).get("Controllers") or [] if c.get("Type") == "Keypad"), {})
        return ctrl.get("Actions") or {}

    def dev_grid():
        return grids.get(profs[prof_v.get()][1].get("Device", {}).get("UUID", ""), (5, 3))

    def size():
        cols, rows = dev_grid()
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
        status.config(text=f"{msg}. " + ("Sending to Stream Deck in a moment..." if auto_v.get() else
                                         "Not sent yet - Save to Stream Deck (Ctrl+S) sends it; Ctrl+Z undoes it."))
        reload_pages()
        refresh_lists()
        draw()
        changed()
        for f in listeners:
            f()

    def restore(frm, to, msg):
        if not hist[frm]:
            return
        hist[to].append(snap())
        e, sel = hist[frm].pop()
        edits.clear()
        edits.update(e)
        st["sel"] = sel
        status.config(text=msg)
        reload_pages()
        refresh_lists()
        draw()
        changed()
        for f in listeners:
            f()

    def reload_pages():
        """Page list again after an edit: a new folder's page appears (unsent), an undone one goes."""
        folder, m = profs[prof_v.get()]
        # a new folder's page whose key was deleted or replaced before sending (and the folders inside it): nothing
        # can open it any more, so it isn't sent. Undo brings it back with its key.
        new = [p for p in edits if p.parents[2] == folder and not p.is_file()]
        if new:
            every = {p.parent.name.lower(): p for p in [*(folder / "Profiles").glob("*/manifest.json"), *new]}

            def read(p):
                try:
                    return page_json(p)
                except (OSError, ValueError):
                    return {}
            live = sd_reachable([i for i, p in every.items() if p.is_file()], {i: read(p) for i, p in every.items()})
            for p in new:
                if p.parent.name.lower() not in live:
                    del edits[p]
        st["named"] = sd_pages(folder, m, {p: d for p, d in edits.items() if p.parents[2] == folder})
        st["pages"] = [p for _, p in st["named"]]
        if st["page"] in st["pages"]:
            st["idx"] = st["pages"].index(st["page"])
        else:  # callers redraw the lists next
            st.update(idx=0 if st["pages"] else None, page=st["pages"][0] if st["pages"] else None, sel=[])

    def changed():
        """With auto-send on, send to Stream Deck shortly after the last change (one restart per burst of edits)."""
        if st.get("job"):
            page.after_cancel(st["job"])
            st["job"] = None
        if auto_v.get() and pending():
            st["job"] = page.after(1500, lambda: save(auto=True))

    def pending():
        """Pages whose edits haven't reached Stream Deck yet: {page file: json}."""
        return {p: d for p, d in edits.items() if d != disk(p)}

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
                    else "?", fade, se.get("volume", "?"), sd_out_name(se.get("outputType")),
                    Path(se.get("path", "")).name + miss))
        dirty = len(pending())
        save_btn.config(text=f"Save to Stream Deck ({dirty} page{'s' * (dirty != 1)} changed)" if dirty
                        else "Save to Stream Deck")
        unsent_l.config(text=f"{dirty} page{'s' * (dirty != 1)} not sent to Stream Deck yet" if dirty else
                        "Stream Deck is up to date")
        unsent_l.config(foreground=UI["warn"] if dirty else UI["good"])
        used = sum(1 for k in st["sel"] if kp.get(k))
        apply_btn.config(text="Apply" if scope_v.get() != SCOPES[0] or not used else
                         f"Apply to {used} key{'s' * (used != 1)}")
        n, i = len(st["named"]), st["idx"]
        prev_b.state(["!disabled"] if i else ["disabled"])
        next_b.state(["!disabled"] if i is not None and i < n - 1 else ["disabled"])
        back_b.state(["!disabled"] if st["back"] or parent_of_page() is not None else ["disabled"])
        count_l.config(text=f"{st['named'][i][0]}  ({i + 1} of {n})" if i is not None else "no pages")
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
        st.update(idx=None, page=None, sel=[], back=[])
        reload_pages()
        st.update(idx=None, page=None)  # go_page(0) below opens the first page
        refresh_lists()
        go_page(0)

    def page_json(p):
        return edits.get(p) or disk(p) or {}

    def page_keys(p):
        ctrl = next((c for c in page_json(p).get("Controllers") or [] if c.get("Type") == "Keypad"), {})
        return ctrl.get("Actions") or {}

    def page_stats(p):
        acts = [a for a in page_keys(p).values() if a]
        return len(acts), sum(len(sd_sounds(a)) for a in acts), sum(len(sd_missing(a)) for a in acts)

    def refresh_lists():
        list_multis()
        ptv.delete(*ptv.get_children())
        for i, (name, p) in enumerate(st["named"]):
            k, snd, miss = page_stats(p)
            edited = p in edits and edits[p] != disk(p)
            ptv.insert("", "end", iid=str(i), values=(name + (" *" if edited else ""), k, snd, miss or ""),
                       tags=(("missing",) if miss else ()) + (("edited",) if edited else ()))
        if st["idx"] is not None:
            ptv.selection_set(str(st["idx"]))

    def go_page(i, remember=False):
        if not st["named"]:
            st.update(idx=None, page=None, sel=[])
            status.config(text="This profile has no pages.")
            return draw()
        i = max(0, min(int(i), len(st["named"]) - 1))
        if i != st["idx"]:
            if remember and st["page"] is not None:
                st["back"].append(st["page"])  # a page, not its index: new folders shift the indexes
            st.update(idx=i, page=st["named"][i][1], sel=[])
        if ptv.selection() != (str(i),):  # re-selecting fires <<TreeviewSelect>> -> go_page again: an endless loop
            ptv.selection_set(str(i))
        ptv.see(str(i))
        draw()

    def parent_of_page():
        """Index of the page holding the folder key that opens the current page (None on top-level pages)."""
        if not st["page"]:
            return None
        me = st["page"].parent.name.lower()
        for i, (_, p) in enumerate(st["named"]):
            for a in page_keys(p).values():
                if a and a.get("UUID") == FOLDER and str((a.get("Settings") or {}).get("ProfileUUID", "")).lower() == me:
                    return i
        return None

    def open_folder(pos):
        pid = str((keys_now()[pos].get("Settings") or {}).get("ProfileUUID", "")).lower()
        i = next((i for i, (_, p) in enumerate(st["named"]) if p.parent.name.lower() == pid), None)
        if i is None:
            return status.config(text="That folder's page isn't in this profile.")
        go_page(i, remember=True)
        status.config(text=f"Opened {st['named'][i][0]}. Back (Alt+Left) or the Parent Folder key returns.")

    def go_back():
        p = st["back"].pop() if st["back"] else None
        i = st["pages"].index(p) if p in st["pages"] else parent_of_page()
        if i is not None:
            go_page(i)

    def next_issue():
        n = len(st["named"])
        for step in range(1, n + 1):
            i = ((st["idx"] or 0) + step) % n
            if page_stats(st["named"][i][1])[2]:
                go_page(i)
                select(lambda a: bool(sd_missing(a)))
                return status.config(text=f"{st['named'][i][0]}: the red keys have missing files. Try the "
                                          "'Fix missing sound files' tool, or double-click File in the list.")
        status.config(text="No page in this profile has missing sound files.")

    def list_multis():
        pages = [(n, page_json(p)) for n, p in st["named"]]
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
            go_page([n for n, _ in st["named"]].index(label))
            st["sel"] = [k]
            draw()
            status.config(text=f"Selected {multi_v.get()}. Choose a tool on the right (e.g. Output device) and Apply.")


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
        files = ui_pick_sounds(page, f"Sound(s) for key {pos_label(pos)}",
                               initialdir=cfg.get("out_dir") or None)  # where Channel Mirror saved its generated files
        got = ui_new_key_dialog(page, files) if files else None
        if not got:
            return
        kind, name, plays = got
        before = snap()
        kp_edit()[pos] = plays[0] if kind == "Single sound" else sd_wrap(kind, name, plays)
        st["sel"] = [pos]
        commit(before, f"New sound key at {pos_label(pos)}")

    def add_to_key(pos, folder=False):
        """More sounds on a sound / Random / Multi key; they copy its first sound's playback settings."""
        a = keys_now().get(pos)
        files = ui_pick_sounds(page, f"{'A folder of sounds' if folder else 'Sounds'} to add to key {pos_label(pos)}",
                               folder)
        kind = (ui_grow_kind(page) if a.get("UUID") == SD_PLAY else "Random Action") if files else None
        if not kind:
            return
        before = snap()
        kp_edit()[pos] = sd_add_sounds(kp_edit()[pos], sd_plays_like(files, sd_sounds(a)[0] if sd_sounds(a) else None),
                                       kind)
        st["sel"] = [pos]
        commit(before, f"Added {len(files)} sound(s) to key {pos_label(pos)} ({sd_kind(kp_edit()[pos])})")

    def fit(files, free, where):
        """The files that fit in `free` places, after asking when some don't; [] = cancelled."""
        if len(files) <= free or (free and messagebox.askyesno(
                "Not enough keys", f"{where} has room for {free} of these {len(files)} sounds.\n"
                f"Add the first {free} ({Path(files[0]).name} ... {Path(files[free - 1]).name})?")):
            return files[:free]
        if not free:
            messagebox.showinfo("Not enough keys", f"{where} has no room for more sounds.")
        return []

    def folder_page(a):
        """The page file a folder key opens (None if it isn't in this profile)."""
        pid = str((a.get("Settings") or {}).get("ProfileUUID", "")).lower()
        return next((p for p in st["pages"] if p.parent.name.lower() == pid), None)

    def folder_names():
        """Names of the folder keys on this page, which new folders must not repeat."""
        return {sd_title(b) for b in keys_now().values() if b and b.get("UUID") == FOLDER}

    def add_folders(chunks, spots):
        """New folders (from sd_folders) onto these keys of this page, their pages into the unsent edits."""
        for spot, (key, pid, pg) in zip(spots, chunks):
            edits[profs[prof_v.get()][0] / "Profiles" / pid.upper() / "manifest.json"] = pg
            kp_edit()[spot] = key
        return spots[:len(chunks)]

    def inside(pairs, seen=None):
        """[(keypad, key)] with each folder key swapped for every sound key inside it (folders in folders too).
        Loads those pages into the edits, so an undo covers them."""
        seen = set() if seen is None else seen
        out = []
        for kp, k in pairs:
            a = kp[k]
            if a.get("UUID") != FOLDER:
                out.append((kp, k))
                continue
            p = folder_page(a)
            if p is None or p in seen:
                continue
            seen.add(p)
            if p not in edits:
                edits[p] = disk(p) or {}
            # read-only lookup: sd_keypad() would add an empty keypad to a bare page and make it look edited
            sub = next((c for c in edits[p].get("Controllers") or [] if c.get("Type") == "Keypad"), {}).get(
                "Actions") or {}
            out += inside([(sub, x) for x, b in sub.items() if b and (sd_sounds(b) or b.get("UUID") == FOLDER)],
                          seen)
        return out

    def fill_page(target, start, folder, where):
        """Sounds onto a page (this one, or a folder key's), one key each, on the free keys from `start` in order."""
        files = ui_pick_sounds(page, f"{'A folder of sounds' if folder else 'Sounds'} for {where}", folder)
        if not files:
            return
        cols, rows = dev_grid()
        if target == st["page"]:
            cols, rows = size()
        kp = sd_keypad(copy.deepcopy(page_json(target)))
        files = fit(files, len(files) - len(sd_fill(kp, files, cols, rows, start)), where)
        got = ui_new_key_dialog(page, files, ("One key per sound",)) if files else None
        if not got:
            return
        before = snap()
        if target not in edits:
            edits[target] = disk(target) or {}
        sd_fill(sd_keypad(edits[target]), got[2], cols, rows, start)
        commit(before, f"Added {len(files)} sound key(s) to {where}, in order")

    def fill_folder(pos, folder=False):
        """Sounds into a folder key's page, one key each in order; what doesn't fit carries over into new folders
        (title 2, title 3...) just beside it, or on the next free keys of this page."""
        a = keys_now()[pos]
        title = sd_title(a).replace("\n", " ").strip() or "Sounds"
        target = folder_page(a)
        if target is None:
            return status.config(text="That folder's page isn't in this profile.")
        files = ui_pick_sounds(page, f"{'A folder of sounds' if folder else 'Sounds'} for folder '{title}'", folder)
        if not files:
            return
        cols, rows = dev_grid()
        room = len(sd_free(sd_keypad(copy.deepcopy(page_json(target))), cols, rows))
        spots = sd_beside(keys_now(), pos, *size())
        files = fit(files, room + max(0, cols * rows - 1) * len(spots), f"Folder '{title}' and the free keys beside it")
        got = ui_new_key_dialog(page, files, ("One key per sound",)) if files else None
        if not got:
            return
        before = snap()
        if target not in edits:
            edits[target] = disk(target) or {}
        rest = sd_fill(sd_keypad(edits[target]), got[2], cols, rows)
        made = add_folders(sd_folders(title, rest, cols, rows, 2, folder_names()), spots) if rest else []
        st["sel"] = [pos] + made
        commit(before, f"Added {len(files)} sound(s) to folder '{title}'" + (
            f"; {len(rest)} carried over into {len(made)} new folder(s) at key(s) "
            f"{', '.join(map(pos_label, made))}" if made else ""))

    def import_sounds(pos=None):
        """Open the Import to folders tab on this profile and page, with this key picked first."""
        if hooks.get("import"):
            hooks["import"](prof_v.get(), st["page"], pos)

    def folder_per_subfolder(pos):
        """Mass import from a folder of folders: a Stream Deck folder per subfolder (and one for sounds loose in the
        picked folder), named after it; full ones carry over into "<name> 2"... Placed from this key, each one
        beside the last, or on the next free keys."""
        d = filedialog.askdirectory(parent=page, title="A folder of sound folders - one Stream Deck folder each")
        groups = sound_folders(d) if d else []
        if d and not groups:
            return messagebox.showinfo("Import", "No sound files in that folder or its subfolders.")
        cols, rows = dev_grid()
        if not groups:
            return
        if cols * rows < 2:
            return messagebox.showinfo("Import", "This deck has no room in a folder beside its Parent Folder key.")
        cap = cols * rows - 1
        spots = [pos] + sd_beside({**keys_now(), pos: True}, pos, *size())
        need = sum(-(-len(fs) // cap) for _, fs in groups)
        if need > len(spots) and not messagebox.askyesno(
                "Not enough keys", f"These {sum(len(fs) for _, fs in groups)} sounds need {need} folders ({cap} "
                f"sounds each); this page has room for {len(spots)}.\nMake the first {len(spots)}?"):
            return
        got = ui_new_key_dialog(page, [f for _, fs in groups for f in fs], ("Folder per subfolder",))
        if not got:
            return
        plays, taken, chunks = list(got[2]), folder_names(), []
        for name, fs in groups:
            mine, plays = plays[:len(fs)], plays[len(fs):]
            chunks += sd_folders(name[:20], mine, cols, rows, taken=taken)
            taken |= {sd_title(k) for k, _, _ in chunks}
        before = snap()
        made = add_folders(chunks, spots)
        placed = sum(1 for _, _, pg in chunks[:len(made)] for a in sd_keypad(pg).values() if a["UUID"] == SD_PLAY)
        left = len(got[2]) - placed
        st["sel"] = made
        commit(before, f"{len(made)} new folder(s), {placed} sound(s), at key(s) {', '.join(map(pos_label, made))}"
                       + (f"; {left} sound(s) didn't fit on this page and weren't added" if left else ""))

    def new_folder(pos, folder=False):
        """New folder keys from here, as many as the sounds need: the first on this key, the rest just beside it (or
        on the next free keys). Each page: the Parent Folder key, then one key per sound in order."""
        files = ui_pick_sounds(page, f"{'A folder of sounds' if folder else 'Sounds'} for new folder(s) at key "
                                     f"{pos_label(pos)}", folder)
        if not files:
            return
        cols, rows = dev_grid()
        if cols * rows < 2:
            return messagebox.showinfo("New folder", "This deck has no room in a folder beside its Parent Folder key.")
        spots = [pos] + sd_beside({**keys_now(), pos: True}, pos, *size())
        files = fit(files, (cols * rows - 1) * len(spots), f"This page ({cols * rows - 1} sounds per folder)")
        got = ui_new_key_dialog(page, files, ("Folder",)) if files else None
        if not got:
            return
        before = snap()
        chunks = sd_folders(got[1].strip() or "Sounds", got[2], cols, rows, taken=folder_names())
        made = add_folders(chunks, spots)
        st["sel"] = made
        commit(before, f"{len(made)} new folder(s) '{sd_title(chunks[0][0])}' at key(s) "
                       f"{', '.join(map(pos_label, made))} with "
                       f"{len(files)} sound(s) in order - double-click one to open it")

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
            hist["clip_dirs"] = {}
            hist["clip_pages"] = folder_tree(a, {}, hist["clip_dirs"])  # a folder key takes what's inside it along
            hist["clip_src"] = st["page"].parent  # where its icons are
            status.config(text=f"Copied '{sd_title(a).replace(chr(10), ' ') or sd_kind(a)}'. Select a key "
                               "(any page or profile) and paste with Ctrl+V or right-click.")

    def folder_tree(a, out, dirs=None):
        """{page id: page json} copies of every page a folder key leads to, folders in folders too; dirs collects
        {page id: its folder} (for the icons)."""
        p = folder_page(a) if a.get("UUID") == FOLDER else None
        if p is not None and p.parent.name.lower() not in out:
            out[p.parent.name.lower()] = pg = copy.deepcopy(page_json(p))
            if dirs is not None:
                dirs[p.parent.name.lower()] = p.parent
            for c in pg.get("Controllers") or []:
                for b in (c.get("Actions") or {}).values():
                    if b:
                        folder_tree(b, out, dirs)
        return out

    def icons(src_dir, dst_dir, obj):
        """Queue the icon files obj shows, from its page folder to the new one (written with the next send)."""
        if src_dir and Path(src_dir) != Path(dst_dir):
            for rel in sd_images(obj):
                f = Path(src_dir) / rel
                if f.is_file():
                    blobs[Path(dst_dir) / rel] = f.read_bytes()

    def paste_key(pos=None):
        if not hist["clip"] or not st["page"]:
            return
        pos = pos or (st["sel"][0] if len(st["sel"]) == 1 else next(iter(sd_free(keys_now(), *size())), None))
        if not pos:
            return messagebox.showinfo("Paste", "No free key on this page; select the key to paste onto.")
        if keys_now().get(pos) and not messagebox.askyesno("Paste", f"Replace key {pos_label(pos)}?"):
            return
        before = snap()
        act = sd_renew(copy.deepcopy(hist["clip"]))
        ids = {}
        pages_ = sd_clone_folders(act, hist.get("clip_pages") or {}, ids=ids)  # the folder's own copy, here
        icons(hist.get("clip_src"), st["page"].parent, act)
        for pid, pg in pages_.items():
            dst = profs[prof_v.get()][0] / "Profiles" / pid.upper() / "manifest.json"
            edits[dst] = pg
            icons((hist.get("clip_dirs") or {}).get(ids.get(pid)), dst.parent, pg)
        kp_edit()[pos] = act
        st["sel"] = [pos]
        commit(before, f"Pasted onto key {pos_label(pos)}" + (
            f" with its own copy of {len(pages_)} folder page(s)" if pages_ else ""))

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
        many = [k for k in st["sel"] if keys_now().get(k)]
        if a and len(many) > 1:
            ui_menu(deck.frame, e, [(f"Edit {len(many)} keys together...   Ctrl+E", bulk_edit), None,
                                    ("Combine into a Random Action", (lambda: combine("Random Action"))
                                     if len(multi_sel) > 1 else None),
                                    ("Combine into a Multi Action", (lambda: combine("Multi Action"))
                                     if len(multi_sel) > 1 else None),
                                    ("Copy first key   Ctrl+C", copy_key), None,
                                    (f"Delete {len(many)} keys   Del", lambda: delete_keys(st["sel"]))])
            return
        if a:
            grows = a.get("UUID") == SD_PLAY or a.get("UUID") in kinds
            items = ([("Open folder", lambda: open_folder(pos)),
                      ("Add sound files into this folder...", lambda: fill_folder(pos)),
                      ("Add a folder of sounds into this folder...", lambda: fill_folder(pos, True)),
                      ("Same settings for every sound inside...", lambda: bulk_edit([pos])), None]
                     if a.get("UUID") == FOLDER else
                     [("Go back out of the folder", go_back), None] if a.get("UUID") == PARENT else []) + [
                     ("Edit key...", lambda: edit_key(pos)),
                     ("Add sound files to this key...", (lambda: add_to_key(pos)) if grows else None),
                     ("Add a folder of sounds to this key...", (lambda: add_to_key(pos, True)) if grows else None),
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
                     ("Import sounds into folders (pick keys, any page)...", lambda: import_sounds(pos)),
                     ("New folder(s) of sounds from files...", lambda: new_folder(pos)),
                     ("New folder(s) of sounds from a folder...", lambda: new_folder(pos, True)),
                     ("New folders, one per subfolder (mass import)...", lambda: folder_per_subfolder(pos)), None,
                     ("Fill free keys from here with files...", lambda: fill_page(st["page"], pos, False,
                                                                                  "this page")),
                     ("Fill free keys from here with a folder...", lambda: fill_page(st["page"], pos, True,
                                                                                     "this page")), None,
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
            chosen = details.selection()
            rows = [r for r in chosen if r[0] in "ks"] if item in chosen else [item]  # every selected row
            try:
                vol = int(val) if field == "volume" else None
                assert vol is None or 0 <= vol <= 100
            except (ValueError, AssertionError):
                return messagebox.showerror("Volume", "Volume is a whole number from 0 to 100.")
            before = snap()
            for r in rows:
                rk, rkey, *ridx = r.split("|")
                live = kp_edit()[rkey]
                if field == "name":
                    if rk == "k" or live.get("UUID") == SD_PLAY:
                        if not live.get("States"):
                            live["States"] = [{}]
                        for x in live["States"]:
                            x["Title"] = val
                elif rk == "s":
                    snd = sd_sounds(live)[int(ridx[0])]
                    sd_set_sound([snd], **{"mode": {"mode": val}, "fade": {"fade": val}, "volume": {"volume": vol},
                                           "output": {"output": val}}[field])
            commit(before, f"Changed {field} on {len(rows)} row(s)")
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
            ui_cell_edit(details, item, col, sd_out_name(se["outputType"]) if se.get("outputType") else SD_DEFAULT_OUT,
                         done, sd_output_choices(), True)
        elif name == "file":
            f = filedialog.askopenfilename(title="Sound file", initialdir=str(Path(se.get("path", "")).parent)
                                           if Path(se.get("path", "")).parent.is_dir() else None,
                                           filetypes=[("Audio", " ".join(f"*{x}" for x in AUDIO_EXT)),
                                                      ("All files", "*.*")])
            if f:
                before = snap()
                sd_sounds(kp_edit()[k])[int(idx[0])]["Settings"]["path"] = str(Path(f))
                commit(before, f"Changed the file on key {pos_label(k)}")
    ui_multi_rows(details, edit_cell)

    def targets_for(scope, into=False):
        """[(keypad, key)] the tools act on: the selection, every sound key on this page, or on every page.
        into = a selected folder key stands for every sound key inside it (the sound tools)."""
        if scope == SCOPES[0]:
            kp = kp_edit()
            pairs = [(kp, k) for k in st["sel"] if kp.get(k)]
            return inside(pairs) if into else pairs
        if scope == SCOPES[1]:
            kp = kp_edit()
            return [(kp, k) for k, a in kp.items() if a and sd_sounds(a)]
        out = []
        for _, p in st["named"]:
            if any(a and sd_sounds(a) for a in page_keys(p).values()):
                if p not in edits:
                    edits[p] = disk(p) or {}
                kp = sd_keypad(edits[p])
                out += [(kp, k) for k, a in kp.items() if a and sd_sounds(a)]
        return out

    def apply():
        if not st["page"]:
            return
        g, scope = goal_v.get(), scope_v.get()
        if g == goals[5] and scope != SCOPES[0]:
            return messagebox.showinfo("Arrange keys", "Arranging works on the selected keys of this page - set "
                                       "'Apply to' to 'Selected keys'.")
        if scope == SCOPES[0] and not any(keys_now().get(k) for k in st["sel"]) and not (
                g == goals[5] and o["arr"].get() == "stop"):
            return messagebox.showinfo("Select keys", "Click keys on the grid (Ctrl / Shift+click for several), use "
                                       "the Select buttons, or set 'Apply to' to a whole page or the profile.")
        # loads the pages first, so undo restores them too; names / arranging act on the selected keys themselves
        targets = targets_for(scope, into=g not in goals[4:6])
        before = snap()
        kp = kp_edit()
        sel = [k for k in st["sel"] if kp.get(k)]
        sounds = [s for kpx, k in targets for s in sd_sounds(kpx[k])]
        if not sounds and g in goals[:4]:
            edits.clear()
            edits.update(before[0])
            return messagebox.showinfo("No sounds", "There are no Play Audio actions there (e.g. only hotkey "
                                       "macros or empty folders), so there's nothing to change.")
        deep = sum(1 for kpx, _ in targets if kpx is not kp)
        where = {SCOPES[0]: f"{len(targets)} selected key(s)" + (f" ({deep} inside folders)" if deep else ""),
                 SCOPES[1]: f"{len(targets)} key(s) on this page",
                 SCOPES[2]: f"{len(targets)} key(s) across the profile"}[scope]
        keep = lambda x: None if x == "Keep" else x
        try:
            if g == goals[0]:
                mode, fade, secs, vol = SD_GOALS[o["goal"].get()]
                sd_set_sound(sounds, mode, fade, secs, vol)
                msg = f"{len(sounds)} sound(s) on {where} set up for: {o['goal'].get()}"
            elif g == goals[1]:
                sd_set_sound(sounds, keep(o["mode"].get()), keep(o["fade"].get()), keep(o["fade_len"].get()))
                msg = f"Playback changed on {len(sounds)} sound(s), {where}"
            elif g == goals[2]:
                how = o["vol_how"].get()
                if how in ("match", "tune", "check"):
                    heard = {}
                    paths = {s.get("Settings", {}).get("path", "") for s in sounds}
                    for i, p in enumerate(sorted(p for p in paths if Path(p).is_file()), 1):
                        status.config(text=f"Listening {i}/{len(paths)}: {Path(p).name}...")
                        page.update()
                        try:
                            heard[p] = sd_listen(p)
                        except Exception:
                            pass
                    rows = sd_level_rows(sounds, heard, o["tune"].get())
                    if how == "check":
                        names = {id(s): sd_title(kpx[k]).replace("\n", " ") or k for kpx, k in targets
                                 for s in sd_sounds(kpx[k])}
                        status.config(text=f"Listened to {len(heard)} file(s) on {where}.")
                        if not ui_level_report(page, rows, names, o["tune"].get()):
                            raise LookupError  # only looked: nothing changed
                        how = "tune"
                    if how == "match":
                        levels = {p: h["level"] for p, h in heard.items() if h["level"] is not None}
                        msg = f"Loudness matched on {sd_match_loudness(sounds, levels)} sound(s), {where}"
                    else:
                        for r in rows:
                            if r["new"] is not None:
                                r["s"]["Settings"]["volume"] = r["new"]
                        n = lambda test: sum(1 for r in rows if test(r))
                        msg = (f"Tuned {n(lambda r: r['new'] is not None)} sound(s) to {o['tune'].get()}, {where}; "
                               f"{n(lambda r: r['verdict'] == 'in range')} already in range"
                               + (f"; {k} too quiet even at full volume" if (k := n(
                                   lambda r: r['verdict'].startswith('too quiet even'))) else "")
                               + (f"; {k} missing or silent" if (k := n(lambda r: r['now'] is None)) else ""))
                else:
                    sd_set_sound(sounds, volume=o["vol"].get() if how == "set" else None,
                                 step=int(o["step"].get()) if how == "step" else None,
                                 scale=int(o["scale"].get()) if how == "scale" else None)
                    msg = f"Volume changed on {len(sounds)} sound(s), {where}"
            elif g == goals[3]:
                sd_set_sound(sounds, output=o["output"].get())
                msg = (f"Output set to {sd_out_name(sd_out(o['output'].get()))} on {len(sounds)} "
                       f"sound(s), {where}")
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
                for n, (kpx, k) in enumerate(targets, 1):
                    sd_label(kpx[k], o["source"].get(), o["prefix"].get(), o["suffix"].get(), o["find"].get(),
                             o["repl"].get(), style, n)
                msg = f"Renamed / restyled {where}"
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
                msg = f"Fixed {fixed} missing sound(s) on {where}; {still} still missing"
        except (ValueError, LookupError) as e:
            edits.clear()
            edits.update(before[0])  # nothing half-done
            st["sel"] = before[1]
            draw()
            if isinstance(e, ValueError):
                messagebox.showerror("Can't do that", str(e))
            return
        commit(before, msg)

    def bulk_edit(keys=None):
        """Several keys in one window (one key opens the normal Edit key window)."""
        keys = [k for k in (keys or st["sel"]) if keys_now().get(k)]
        if not keys:
            return messagebox.showinfo("Edit keys", "Select the keys to edit first (Ctrl / Shift+click for several).")
        if len(keys) == 1 and keys_now()[keys[0]].get("UUID") != FOLDER:
            return edit_key(keys[0])
        kp = kp_edit()
        acts = [kp[k] for k in keys]
        inner = [kpx[k] for kpx, k in inside([(kp, k) for k in keys]) if kpx is not kp]  # keys inside folders
        ch = ui_bulk_dialog(page, acts + inner)
        if not ch:
            return
        before = snap()
        sd_set_sound([s for a in acts + inner for s in sd_sounds(a)], ch.get("mode"), ch.get("fade"),
                     ch.get("fade_len"), ch.get("volume"), output=ch.get("output"))
        for a in acts:
            if "title" in ch or ch.get("style"):
                if not a.get("States"):
                    a["States"] = [{}]
                for x in a["States"]:
                    if "title" in ch:
                        x["Title"] = ch["title"]
                    x.update(ch.get("style") or {})
        commit(before, f"Edited {len(keys)} key(s) together" + (
            f", and the sounds on {len(inner)} key(s) inside the folder(s)" if inner else ""))

    def revert():
        if edits:
            before = snap()
            edits.clear()
            st["sel"] = []
            commit(before, "All unsaved changes thrown away")

    def save(auto=False):
        """Send every changed page to Stream Deck: close it (it rewrites its profiles on exit and would undo
        ours), back up, write, read back to check, reopen. auto = no question first (auto-send / app closing)."""
        st["job"] = None
        if st.get("saving"):  # a send is running; go again when it's done
            st["again"] = True
            return
        todo = copy.deepcopy(pending())  # a snapshot: editing can carry on while it's written
        icons = {f: b for f, b in blobs.items()  # only for pages that exist or are being sent (not undone ones)
                 if f.parents[1] / "manifest.json" in edits or (f.parents[1] / "manifest.json").is_file()}
        if not todo and not icons:
            return status.config(text="Nothing to send - Stream Deck already has every change.")
        if not auto and sd_running() and not messagebox.askyesno(
                "Close Stream Deck", "Stream Deck must close for a moment while the changes are written "
                "(it rewrites its profiles when it exits).\nClose it now and reopen it after?"):
            return
        st["saving"] = True
        save_btn.state(["disabled"])
        status.config(text=f"Sending {len(todo)} page(s) to Stream Deck - it closes and reopens for a few seconds; "
                           "you can keep working...")

        def finish(res):
            st["saving"] = False
            save_btn.state(["!disabled"])
            if isinstance(res, Exception):
                status.config(text=f"Sending failed: {res}")
                messagebox.showerror("Send to Stream Deck", str(res))
            else:  # edits stay as they are (now equal to the files), so undo keeps working across sends
                for f in icons:
                    blobs.pop(f, None)
                status.config(text=f"Sent {len(todo)} page(s) to Stream Deck and checked they were written; "
                                   f"Stream Deck reopened. Backup: {res}")
            refresh_lists()
            draw()
            if st.pop("again", False) or (auto_v.get() and pending()):
                changed()
        ui_background(page, lambda: sd_push({**todo, **icons}, {p.parents[2] for p in todo}), finish)

    apply_btn.config(command=apply)
    save_btn.config(command=save)
    tbtn["undo"].config(command=lambda: restore("undo", "redo", "Undone."))
    tbtn["redo"].config(command=lambda: restore("redo", "undo", "Redone."))
    tbtn["revert"].config(command=revert)
    ui_keys(page, {"<Control-z>": lambda: restore("undo", "redo", "Undone."),
                   "<Control-y>": lambda: restore("redo", "undo", "Redone."), "<Control-s>": save,
                   "<Control-c>": copy_key, "<Control-v>": paste_key, "<Delete>": lambda: delete_keys(st["sel"]),
                   "<Control-a>": lambda: select(bool), "<Escape>": lambda: select(lambda a: False),
                   "<Prior>": lambda: go_page((st["idx"] or 0) - 1), "<Next>": lambda: go_page((st["idx"] or 0) + 1),
                   "<Alt-Left>": go_back, "<Control-e>": lambda: bulk_edit(), "<Return>": lambda: bulk_edit()})
    scope_v.trace_add("write", lambda *_: draw())
    ptv.bind("<<TreeviewSelect>>", lambda e: ptv.selection() and go_page(int(ptv.selection()[0])))
    prof_v.trace_add("write", on_prof)
    multi_v.trace_add("write", on_multi)
    on_prof()
    def change(fn, msg):
        """For the other tabs: run fn(edit) as one undoable change, then show it. edit(page file) -> its json to
        change (loaded on first use); edit(page file, json) puts a new page. Raises (and undoes) on error."""
        before = snap()

        def edit(p, new=None):
            if new is not None:
                edits[p] = new
            elif p not in edits:
                edits[p] = disk(p) or {}
            return edits[p]
        try:
            fn(edit)
        except Exception:
            edits.clear()
            edits.update(before[0])
            raise
        commit(before, msg)

    def profile_pages(label):
        folder, m = profs[label]
        return sd_pages(folder, m, {p: d for p, d in edits.items() if p.parents[2] == folder})

    return {"pending": pending, "save": save, "saving": lambda: bool(st.get("saving")),
            # shared with the Import to folders and Key mover tabs (one set of unsent edits, one undo)
            "profiles": lambda: list(labels_), "pages": profile_pages, "keys": page_keys, "change": change,
            "grid": lambda label: grids.get(profs[label][1].get("Device", {}).get("UUID", ""), (5, 3)),
            "folder": lambda label: profs[label][0], "icons": icons, "page": page_json,
            "undo": lambda: restore("undo", "redo", "Undone."), "listeners": listeners, "hooks": hooks,
            "current": lambda: (prof_v.get(), st["page"]), "status": lambda: status.cget("text")}


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
                new.append({"path": p, "title": p.stem[:20], "key": key, **{n: v[n].get() for n in
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
            title_v.set(Path(files[0]).parent.name[:20])
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
                          (f"Remove {len(sel)} sound(s)   Del", remove)])
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
            status.config(text="Installing the profile - Stream Deck closes and reopens for a few seconds...")
            send_btn.state(["disabled"])

            def finish(res):
                send_btn.state(["!disabled"])
                if isinstance(res, Exception):
                    status.config(text=f"Installing failed: {res}")
                    return messagebox.showerror("Send to Stream Deck", str(res))
                status.config(text=f"Installed profile '{name}' with {len(sounds)} sound(s) and checked it was "
                                   "written; Stream Deck reopened. Pick it in Stream Deck's profile list.")
            return ui_background(page, lambda: sd_push(writes, []), finish)
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
    return save


def setup_tab(page, cfg, live, restart):
    """The Setup tab: Appearance (Light / Dark / Follow Windows, switched straight away) and every folder Channel
    Mirror uses - found automatically, or picked here with Browse... and kept in the settings (cfg["paths"]), so
    every tool uses it; Auto goes back to finding it. live: {key: StringVar} for the folders a tab keeps itself
    (output folder, recordings, VTube Studio install); restart() closes the app and opens it again."""
    import tkinter as tk
    from tkinter import filedialog, ttk
    paths = cfg.setdefault("paths", {})
    top = page.winfo_toplevel()
    body = ttk.Frame(page, padding=12)
    body.pack(fill="both", expand=True)

    af = ttk.LabelFrame(body, text="Appearance")
    af.pack(fill="x")
    theme = tk.StringVar(value=cfg.get("theme", "system"))
    for text, val in (("Light", "light"), ("Dark", "dark"), ("Follow Windows", "system")):
        ttk.Radiobutton(af, text=text, variable=theme, value=val).pack(side="left", padx=(0, 18))
    ttk.Label(af, text="Changes straight away.", style="Hint.TLabel").pack(side="left")

    def on_theme(*_):
        cfg["theme"] = theme.get()
        ui_switch(top, theme.get())
    theme.trace_add("write", on_theme)

    def follow():  # Windows switched between light and dark while the app is open
        if cfg.get("theme", "system") == "system" and ui_mode("system") != UI["mode"]:
            ui_switch(top, "system")
        page.after(3000, follow)
    page.after(3000, follow)

    ff = ttk.LabelFrame(body, text="Folders")
    ff.pack(fill="x", pady=(8, 0))
    ff.columnconfigure(1, weight=1)
    ttk.Label(ff, style="Hint.TLabel", text=(
        "Found by themselves. Not found, or kept somewhere else? Pick it with Browse... and every tool uses it. "
        "Auto goes back to finding it.")).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 4))
    rows = {}

    def current(key):
        """(where it is now, picked by the user?)"""
        if key in live:
            val = live[key].get().strip()
            auto = setup_auto(key)
            return (Path(val) if val else auto), bool(val) and Path(val) != auto
        return (Path(paths[key]) if paths.get(key) else setup_auto(key)), bool(paths.get(key))

    def show(key):
        p, picked = current(key)
        r = rows[key]
        state = setup_check(key, p) if p or key != "out_dir" else "auto"
        r["path"].set(str(p) if p else "Next to each file you add" if key == "out_dir" else
                      "Not found - pick it with Browse...")
        text, style = {"found": ("✓ Found", "Good.TLabel"), "auto": ("✓ Ready", "Good.TLabel"),
                       "new": ("Made when first used", "Hint.TLabel"), "missing": ("✗ Not found", "Bad.TLabel")}[state]
        r["status"].config(text=text, style=style)
        r["auto"].config(state="normal" if picked else "disabled")

    def keep(key, value):  # into the settings and the running app ("" = Auto)
        if value:
            paths[key] = str(Path(value))
            setup_apply({key: value})
        else:
            paths.pop(key, None)
            setup_reset(key)

    def set_path(key, value):  # value "" = Auto
        if key in live:  # the tab that uses it shows it too (and keeps it: output folder, recordings)
            auto = setup_auto(key)
            live[key].set(value or ("" if key == "out_dir" or not auto else str(auto)))
        else:
            keep(key, value)
        if key in SETUP_RESTART:
            note.config(text="Restart Channel Mirror so every tab uses the folder you picked.", style="Bad.TLabel")
        show(key)

    def browse(key, name):
        p, _ = current(key)
        start = str(p.parent if key == "sd_exe" and p else p) if p and Path(p).exists() else str(Path.home())
        if key == "sd_exe":
            got = filedialog.askopenfilename(parent=page, title=f"Where is {name}?", initialdir=start,
                                             filetypes=[("Programs", "*.exe"), ("All files", "*.*")])
        else:
            got = filedialog.askdirectory(parent=page, title=f"Pick the {name} folder", initialdir=start)
        if got:
            set_path(key, got)

    for i, (key, name, what) in enumerate(SETUP_ITEMS, start=1):
        lab = ttk.Frame(ff)
        lab.grid(row=i, column=0, sticky="w", padx=(0, 12), pady=2)
        ttk.Label(lab, text=name, style="Name.TLabel").pack(anchor="w")
        ttk.Label(lab, text=what, style="Hint.TLabel").pack(anchor="w")
        rows[key] = {"path": tk.StringVar()}
        ttk.Entry(ff, textvariable=rows[key]["path"], state="readonly").grid(row=i, column=1, sticky="ew", pady=2)
        rows[key]["status"] = ttk.Label(ff, width=20)
        rows[key]["status"].grid(row=i, column=2, sticky="w", padx=(10, 6))
        ttk.Button(ff, text="Browse...", style="Tool.TButton", command=lambda k=key, n=name: browse(k, n)).grid(
            row=i, column=3, padx=(0, 4))
        rows[key]["auto"] = ttk.Button(ff, text="Auto", style="Tool.TButton", command=lambda k=key: set_path(k, ""))
        rows[key]["auto"].grid(row=i, column=4)
        if key == "vts" and key in live:  # picked here or in the VTube Studio tab: kept, and the tab starts from it
            live[key].trace_add("write", lambda *_: keep("vts", current("vts")[0] if current("vts")[1] else ""))
        if key in live:
            live[key].trace_add("write", lambda *_, k=key: show(k))
        show(key)

    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(8, 0))
    ttk.Button(bar, text="Restart now", command=restart).pack(side="right")
    note = ttk.Label(bar, style="Hint.TLabel", wraplength=760, justify="left", text=(
        "Folders you pick are used straight away; for the Stream Deck folder and app, restart Channel Mirror."))
    note.pack(side="left", fill="x", expand=True)
    return {"theme": theme, "rows": rows, "show": show, "note": note}


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
    page, sd_page, ed_page, imp_page, mv_page, rec_page, vts_page, link_page, setup_page = (
        ttk.Frame(nb) for _ in range(9))
    nb.add(page, text="Channel Mirror")
    nb.add(sd_page, text="Stream Deck soundboard")
    nb.add(ed_page, text="Stream Deck editor")
    nb.add(imp_page, text="Import to folders")
    nb.add(mv_page, text="Key mover")
    nb.add(rec_page, text="Screen recorder")
    nb.add(vts_page, text="VTube Studio backgrounds")
    nb.add(link_page, text="Link")
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

    def deliver(target, files):
        """Accepted files (from another device or a link) into the tab they're meant for."""
        files = [Path(f) for f in files]
        if target == "import":
            importer["add"](files)
            nb.select(imp_page)
        elif target == "vts":
            vtube["add"](files)
            nb.select(vts_page)
        elif target == "soundboard":
            sd_save.add(files)
            nb.select(sd_page)
        else:
            load([f for f in files if f.suffix.lower() in AUDIO_EXT + VIDEO_EXT])
            nb.select(page)
    linker = link_tab(link_page, cfg, deliver)
    handover = link_handover_serve(linker["open_link"])  # links clicked while the app is open come here
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

    try:
        nb.select(int(cfg.get("tab", 0)))
    except (tk.TclError, ValueError):
        pass

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
        linker["save"]()
        linker["stop"]()
        if handover:
            handover.shutdown()
        sd_save()
        cfg["geometry"] = root.geometry() if root.state() == "normal" else cfg.get("geometry", "")
        cfg["tab"] = nb.index(nb.select())
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
    if dropped:
        root.after(100, load, media_files(dropped))
    root.mainloop()


def selftest():
    import copy
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
        sd_match_loudness(allsnd, lv, SD_LEVELS["effect"])
        assert [s["Settings"]["volume"] for s in allsnd] == [32, 100, 100, 100]  # -10 dB file -> -10 dB; -26 dB can't be boosted
        # listening: silence ignored, loudest channel used, kind detected; tuning by kind, within 2 dB left alone
        a20 = 10 ** (-20 / 20) * np.sqrt(3)  # uniform noise of RMS -20 dBFS
        ph = "2*PI*(150*t-40/(2*PI*0.7)*cos(2*PI*0.7*t))"  # a voice-like buzz gliding 110-190 Hz, in syllables
        buzz = "+".join(f"sin({k}*{ph})/{k}" for k in range(1, 6))
        gen = {"fx.wav": f"aevalsrc='{a20}*(2*random(0)-1)*lt(t,1)|{a20 / 10}*(2*random(1)-1)*lt(t,1)':d=4",
               "vo.wav": f"aevalsrc='0.3*({buzz})*gt(sin(2*PI*3*t),-0.3)':d=3",
               "bed.wav": "aevalsrc='0.08*sin(2*PI*440*t)':d=35"}
        for name, src in gen.items():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src + ":s=44100", str(Path(d) / name)],
                           check=True, creationflags=NO_WINDOW)
        h = {n: sd_listen(Path(d) / n) for n in gen}
        assert abs(h["fx.wav"]["level"] + 20) < 0.5 and h["fx.wav"]["kind"] == "effect", h["fx.wav"]  # not -26 (silence)
        assert h["vo.wav"]["kind"] == "voice" and h["bed.wav"]["kind"] == "music / ambience", h
        snd = [sd_play(Path(d) / n, n) for n in gen] + [sd_play(Path(d) / "gone.wav", "gone")]
        heard = {str(Path(d) / n): v for n, v in h.items()}
        snd[1]["Settings"]["volume"] = round(100 * 10 ** ((-16.5 - h["vo.wav"]["level"]) / 20))  # plays at -16.5: in range
        rows = sd_level_rows(snd, heard)
        assert [r["target"] for r in rows] == [-20.0, -16.0, -30.0, None]
        assert [r["verdict"].split(":")[0] for r in rows] == ["in range", "in range", "too loud", "file missing"], rows
        bed = h["bed.wav"]["level"]  # -25 dB file -> about 56 to land on -30
        assert rows[2]["new"] == round(100 * 10 ** ((-30 - bed) / 20)) and abs(bed + 24.9) < 0.3
        rows = sd_level_rows(snd, heard, "Everything at my music / ambience level")  # one fixed target for all
        assert {r["target"] for r in rows[:3]} == {-30.0} and rows[0]["new"] == 32
        # my own OBS levels replace the defaults; bad values fall back
        assert sd_set_levels({"voice": -12, "effect": "x", "music / ambience": 5}) == {
            "voice": -12.0, "effect": -20.0, "music / ambience": -30.0}
        assert sd_level_rows(snd, heard)[1]["target"] == -12.0
        sd_set_levels(None)
        assert SD_LEVELS == SD_OBS_DEFAULT
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

        # adding sounds to keys that already exist, and new folders filled in order
        assert sorted(["t10.wav", "T2.wav", "t1.wav"], key=natural) == ["t1.wav", "T2.wav", "t10.wav"]
        assert sorted(["1²2.wav", "a.wav"], key=natural)  # superscript digits aren't numbers: no crash
        one = sd_play(st, "st", "Loop / Stop", "Fade In", 3, 40, "")
        more = sd_plays_like([mono, st], one)
        assert [sd_title(x) for x in more] == ["mono", "st"]
        assert {(x["Settings"]["actionType"], x["Settings"]["volume"]) for x in more} == {(3, 40)}
        one["States"][0]["FontSize"] = 9
        rk = sd_add_sounds(one, more[:1], "Random Action")  # a single sound becomes a Random Action, look kept
        assert sd_kind(rk) == "Random x2" and rk["States"] == [{"Title": "st", "FontSize": 9}]
        assert sd_add_sounds(rk, more[1:]) is rk and sd_kind(rk) == "Random x3"  # Random / Multi just grow
        assert [Path(x["Settings"]["path"]).name for x in sd_sounds(rk)] == ["st.wav", "mono.wav", "st.wav"]
        assert sd_free({"0,0": None, "1,0": {}, "0,1": one}, 2, 2) == ["0,0", "1,0", "1,1"]  # saved-empty = free
        kp2 = {"1,0": sd_stop_key()}
        left = sd_fill(kp2, [sd_play(st, f"s{i}") for i in range(4)], 3, 2, start="2,0")
        assert {k: sd_title(a) for k, a in kp2.items() if a["UUID"] == SD_PLAY} == {"2,0": "s0", "0,1": "s1",
                                                                                     "1,1": "s2", "2,1": "s3"}
        assert left == [] and sd_fill(kp2, [one, rk], 3, 2) == [rk] and kp2["0,0"] is one  # full: the rest comes back
        key, pid, fpage, left = sd_folder("Hits", [sd_play(st, f"h{i}") for i in range(3)], 2, 2)
        fkp = sd_keypad(fpage)
        assert key["UUID"] == SD_FOLDER and key["Settings"]["ProfileUUID"] == pid and sd_title(key) == "Hits"
        assert fkp["0,0"]["UUID"] == SD_PARENT and [sd_title(fkp[k]) for k in ("1,0", "0,1", "1,1")] == [
            "h0", "h1", "h2"] and left == []
        assert len(sd_folder("x", [one] * 5, 2, 2)[3]) == 2  # 3 keys after the Parent Folder key
        # more sounds than a folder holds: as many folders as needed, numbered, each page full in order
        many = [sd_play(st, f"m{i}") for i in range(8)]
        chain = sd_folders("Hits", many, 2, 2)
        assert [sd_title(k) for k, _, _ in chain] == ["Hits", "Hits 2", "Hits 3"]
        assert [sd_title(a) for _, _, pg in chain for k, a in sorted(sd_keypad(pg).items(), key=lambda x: sd_order(
            x[0])) if a["UUID"] == SD_PLAY] == [f"m{i}" for i in range(8)]
        assert [sd_title(k) for k, _, _ in sd_folders("SFX", many[:2], 2, 2, 4)] == ["SFX 4"]  # carrying on
        assert [sd_title(k) for k, _, _ in sd_folders("D", many[:7], 2, 2, 2, {"D 2", "D 4"})] == [
            "D 3", "D 5", "D 6"]  # names already on the page are skipped, every time
        assert sd_title(sd_folders("D", many[:1], 2, 2, taken={"D"})[0][0]) == "D 2"
        try:
            sd_folders("x", many, 1, 1)  # a 1-key deck has no room beside the Parent Folder key
            raise AssertionError("looped on a 1x1 deck")
        except ValueError:
            pass
        # a folder of folders: its own sounds first (named after it), then each subfolder's, in name order
        lib = Path(d) / "lib"
        for sub, names in (("10 memes", ["z.wav"]), ("2 drums", ["k10.wav", "k2.wav"]), ("empty", []), ("", ["top.wav"])):
            (lib / sub).mkdir(parents=True, exist_ok=True)
            for n in names:
                shutil.copy2(mono, lib / sub / n)
        (lib / "empty" / "readme.txt").write_text("x")
        assert [(n, [f.name for f in fs]) for n, fs in sound_folders(lib)] == [
            ("lib", ["top.wav"]), ("2 drums", ["k2.wav", "k10.wav"]), ("10 memes", ["z.wav"])]
        # pasting a folder key copies the pages it opens (folders in folders too) under new ids
        inner_key, inner_id, inner_pg, _ = sd_folder("In", [sd_play(st, "deep")], 2, 2)
        outer_key, outer_id, outer_pg, _ = sd_folder("Out", [sd_play(st, "top")], 2, 2)
        sd_keypad(outer_pg)["1,1"] = inner_key
        sd_keypad(inner_pg)["1,1"] = copy.deepcopy(outer_key)  # a loop back out: copied once, not forever
        pasted = copy.deepcopy(outer_key)
        made = sd_clone_folders(pasted, {outer_id: outer_pg, inner_id: inner_pg})
        new_out = pasted["Settings"]["ProfileUUID"]
        assert len(made) == 2 and new_out in made and new_out != outer_id and outer_key["Settings"]["ProfileUUID"] == outer_id
        new_in = sd_keypad(made[new_out])["1,1"]["Settings"]["ProfileUUID"]
        assert new_in in made and new_in != inner_id and sd_title(sd_keypad(made[new_in])["1,0"]) == "deep"
        assert sd_keypad(made[new_out])["1,0"]["ActionID"] != sd_keypad(outer_pg)["1,0"]["ActionID"]  # its own keys
        assert sd_keypad(outer_pg)["1,1"]["Settings"]["ProfileUUID"] == inner_id  # the source is left as it was
        assert sd_clone_folders(sd_stop_key(), {}) == {} and sd_clone_folders(copy.deepcopy(outer_key), {}) == {}
        # the loop key inside the copy points at the copy, not the original; two keys opening one folder share a copy
        assert sd_keypad(made[new_in])["1,1"]["Settings"]["ProfileUUID"] == new_out
        sd_keypad(outer_pg)["0,1"] = copy.deepcopy(inner_key)
        pasted = copy.deepcopy(outer_key)
        made = sd_clone_folders(pasted, {outer_id: outer_pg, inner_id: inner_pg})
        kp_out = sd_keypad(made[pasted["Settings"]["ProfileUUID"]])
        assert len(made) == 2 and kp_out["0,1"]["Settings"]["ProfileUUID"] == kp_out["1,1"]["Settings"]["ProfileUUID"]
        # pages a profile can still open: from pages on disk through folder keys; an unreachable loop is not
        reach = {"a": {"Controllers": [{"Type": "Keypad", "Actions": {"0,0": {"UUID": SD_FOLDER, "Settings": {
            "ProfileUUID": "B"}}}}]}, "b": {},  # ids compared lower-case, as Stream Deck writes them
            "x": {"Controllers": [{"Actions": {"0,0": {"UUID": SD_FOLDER, "Settings": {"ProfileUUID": "y"}}}}]},
            "y": {"Controllers": [{"Actions": {"0,0": {"UUID": SD_FOLDER, "Settings": {"ProfileUUID": "x"}}}}]}}
        assert sd_reachable(["a"], reach) == {"a", "b"}
        (lib / "locked").mkdir()
        real_iterdir = Path.iterdir

        def deny(p):
            if p.name == "locked":
                raise PermissionError(p)
            return real_iterdir(p)
        Path.iterdir = deny
        try:  # e.g. System Volume Information under a drive root: skipped, not a crash
            assert [n for n, _ in sound_folders(lib)] == ["lib", "2 drums", "10 memes"]
        finally:
            Path.iterdir = real_iterdir
        # sounds per folder: fewer than a page holds, the rest carry on into the next folders
        per3 = sd_folders("P", many, 3, 3, per=3)  # a 3x3 page holds 8; 3 per folder -> 3 folders for 8 sounds
        assert [sum(a["UUID"] == SD_PLAY for a in sd_keypad(pg).values()) for _, _, pg in per3] == [3, 3, 2]
        assert sd_folder("x", many, 3, 3, per=2)[3] == many[2:]
        # volume scaled by a percentage, kept within 0-100
        vs = [sd_play(st, volume=v) for v in (80, 50, 100)]
        sd_set_sound(vs, scale=50)
        assert [x["Settings"]["volume"] for x in vs] == [40, 25, 50]
        sd_set_sound(vs, scale=300)
        assert [x["Settings"]["volume"] for x in vs] == [100, 75, 100]
        # a new profile with every sound on its own key, in folders of 2 (the soundboard tab's folder option)
        fsnd = [{"path": st, "title": f"f{i}", "key": "", "mode": "Loop / Stop", "fade": "No Fade", "fade_len": 1,
                 "volume": 90, "output": ""} for i in range(5)]
        files_, res_ = sd_profile_files("Fold", ("20GBA9901", "x", 2, 2), fsnd, {}, folders={"title": "Box", "per": 2})
        pgs = {k: v for k, v in files_.items() if k.endswith("manifest.json") and "Controllers" in v}
        top = next(v for v in pgs.values() if v.get("Name") == "Fold")
        boxes = {k: a for k, a in sd_keypad(top).items()}
        assert [sd_title(boxes[k]) for k in sorted(boxes, key=sd_order)] == ["Box", "Box 2", "Box 3"]
        inner_pages = [pgs[k] for k in pgs if any(a["Settings"]["ProfileUUID"].upper() in k for a in boxes.values())]
        assert sorted(sum(a["UUID"] == SD_PLAY for a in sd_keypad(p).values()) for p in inner_pages) == [1, 2, 2]
        assert all(a["Resources"] for p in inner_pages for a in sd_keypad(p).values() if a["UUID"] == SD_PLAY)
        assert {a["Settings"]["actionType"] for p in inner_pages for a in sd_keypad(p).values()
                if a["UUID"] == SD_PLAY} == {SD_MODES.index("Loop / Stop")}
        try:
            sd_profile_files("F", ("m", "x", 2, 1), fsnd, {}, folders={"title": "B", "per": 1})  # 5 folders, 2 keys
            raise AssertionError("more folders than keys")
        except ValueError:
            pass
        # VTube Studio backgrounds: copied in (same file reused, a different one with the name kept apart), a
        # ChangeBackground hotkey each on the model (existing ones reused), a Stream Deck Trigger Hotkey key each
        vts = Path(d) / "VTS" / "VTube Studio_Data" / "StreamingAssets"
        (vts / "Backgrounds").mkdir(parents=True)
        (vts / "Live2DModels" / "Wolf").mkdir(parents=True)
        model_file = vts / "Live2DModels" / "Wolf" / "Wolf.vtube.json"
        old_hk = dict(VTS_HOTKEY, HotkeyID="a" * 32, File="City", Name="")
        model_file.write_text(json.dumps({"Version": 1, "Name": "Wolf", "ModelID": "m" * 32, "Hotkeys": [old_hk]},
                                         indent=4))
        assert vts_models(vts) == [("Wolf", model_file, "m" * 32)]
        blib = Path(d) / "bgs"
        (blib / "more").mkdir(parents=True)
        (blib / "City.png").write_bytes(b"city")
        (blib / "Room 2.jpg").write_bytes(b"room2")
        (blib / "Room 10.mp4").write_bytes(b"room10")
        (blib / "notes.txt").write_text("x")
        (blib / "more" / "City.png").write_bytes(b"another city")  # same name, different picture
        (vts / "Backgrounds" / "City.png").write_bytes(b"city")  # already in VTube Studio
        picked = vts_files([blib, blib / "more" / "City.png"])
        assert [p.name for p in picked] == ["City.png", "Room 2.jpg", "Room 10.mp4", "City.png"]
        before_bg = sorted(p.name for p in (vts / "Backgrounds").iterdir())
        assert vts_copy(picked, vts / "Backgrounds", dry=True) == ["City", "Room 2", "Room 10", "City (2)"]
        assert sorted(p.name for p in (vts / "Backgrounds").iterdir()) == before_bg  # a dry run copies nothing
        names = vts_copy(picked, vts / "Backgrounds")
        assert names == ["City", "Room 2", "Room 10", "City (2)"]
        assert (vts / "Backgrounds" / "City (2).png").read_bytes() == b"another city"
        assert vts_copy(picked, vts / "Backgrounds") == names  # again: nothing new, same names
        data = json.loads(model_file.read_text())
        ids, added = vts_hotkeys(data, names)
        assert added == 3 and ids["City"] == "a" * 32 and len(set(ids.values())) == 4
        bg_hk = [h for h in data["Hotkeys"] if h["Action"] == "ChangeBackground"]
        assert [h["File"] for h in bg_hk] == ["City", "Room 2", "Room 10", "City (2)"]
        assert all(len(h["HotkeyID"]) == 32 and h["Name"] == h["File"] for h in bg_hk[1:])
        assert vts_hotkeys(data, names) == (ids, 0)  # again: reused, none added
        # hotkeys whose background file isn't in VTube Studio: found by name in other folders (any depth)
        data["Hotkeys"].append(dict(VTS_HOTKEY, HotkeyID="b" * 32, File="(New) Balcony View"))
        data["Hotkeys"].append(dict(VTS_HOTKEY, HotkeyID="c" * 32, File="Gone"))
        assert vts_missing(data, vts / "Backgrounds") == ["(New) Balcony View", "Gone"]
        dl = Path(d) / "Downloads"
        (dl / "deep" / "er").mkdir(parents=True)
        (dl / "deep" / "er" / "(New) Balcony View.MP4").write_bytes(b"balcony")
        (dl / "(New) Balcony View.txt").write_text("not a background")
        assert vts_find(["(New) Balcony View", "Gone"], [dl, Path(d) / "nowhere"]) == {
            "(New) Balcony View": dl / "deep" / "er" / "(New) Balcony View.MP4"}
        vkey = sd_vts_key("m" * 32, ids["Room 2"], "Room 2")
        assert vkey["UUID"] == SD_VTS_HOTKEY and vkey["Settings"] == {
            "modelId": "m" * 32, "hotkeyId": ids["Room 2"], "showName": True} and sd_title(vkey) == "Room 2"
        # links: channelmirror:// links (files / web addresses for a destination), and sending between devices
        lk = link_make("vts", [Path("C:/bg/a b.png")], ["https://x.example/s.mp3"])
        assert lk.startswith("channelmirror://open?") and link_parse(lk) == {
            "to": "vts", "files": [Path("C:/bg/a b.png")], "urls": ["https://x.example/s.mp3"]}
        for bad in ("http://open?to=vts", "channelmirror://open?to=nope&file=C:/a.png",
                    "channelmirror://open?to=vts&file=relative.png", "channelmirror://open?to=vts&url=file:///C:/a"):
            try:
                link_parse(bad)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        assert link_safe_name("..\\..\\Windows\\evil.mp3") == "evil.mp3" and link_safe_name('a:b?.PNG') == "a_b_.png"
        for bad in ("run.exe", "noext", ".."):
            try:
                link_safe_name(bad)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        assert link_private("192.168.1.20") and link_private("10.0.0.5") and link_private("127.0.0.1")
        assert not link_private("8.8.8.8") and not link_private("not an ip")
        for odd in ("169.254.1.1", "240.0.0.1", "0.0.0.1"):  # link-local / reserved: not "the home network"
            assert not link_private(odd), odd
        # security: network-share paths never reach the file system; device names; extra start-up options
        for unc in (r"\\attacker\s\x.mp3", "//attacker/s/x.mp3", r"\\?\C:\a.mp3", r"\\.\C:\a.mp3"):
            try:
                from urllib.parse import quote as _q
                link_parse("channelmirror://open?to=import&file=" + _q(unc))
                raise AssertionError(f"accepted {unc}")
            except ValueError:
                pass
        assert link_safe_name("CON.mp3") == "_CON.mp3" and link_safe_name("lpt1.wav") == "_lpt1.wav"
        assert link_args(["channelmirror://open?to=vts&file=C:/a.png", "--uninstall", "--quiet", "x.mp3"]) == \
            "channelmirror://open?to=vts&file=C:/a.png" and link_args(["--install"]) is None
        test_key = r"Software\Classes\channelmirror-selftest"
        link_register(Path("C:/apps/ChannelMirror.exe"), test_key)
        assert link_registered(test_key) == '"C:\\apps\\ChannelMirror.exe" "%1"'
        link_unregister(test_key)
        assert link_registered(test_key) is None
        # a real send / receive on this PC: right code in, wrong code / file type / path trick out
        batches = []
        srv = LinkServer(0, "123456", Path(d) / "inbox", batches.append, host="127.0.0.1")
        try:
            pair = f"http://127.0.0.1:{srv.port}/?code=123456"
            assert link_send(pair, [mono, st], "vts", "Laptop") == 2
            assert len(batches) == 1 and batches[0]["target"] == "vts" and batches[0]["from"] == "Laptop"
            assert sorted(f.name for f in batches[0]["files"]) == ["mono.wav", "st.wav"]
            assert batches[0]["files"][0].read_bytes() in (mono.read_bytes(), st.read_bytes())
            for bad_pair, files in ((f"http://127.0.0.1:{srv.port}/?code=000000", [mono]),
                                    (pair, [Path(d) / "notes.txt"])):
                try:
                    link_send(bad_pair, files, "vts", "x")
                    raise AssertionError("accepted a bad send")
                except (OSError, ValueError):
                    pass
            assert len(batches) == 1
            import urllib.request
            page = urllib.request.urlopen(pair, timeout=5).read().decode()
            assert "<input" in page and "123456" in page  # the upload page for phones / other PCs
            # guessing the code: after 5 wrong tries this address is shut out for a while, even with the right one
            for _ in range(5):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/?code=999999", timeout=5)
                except OSError:
                    pass
            try:
                urllib.request.urlopen(pair, timeout=5)
                raise AssertionError("not locked out after 5 wrong codes")
            except OSError as e:
                assert "429" in str(e), e
        finally:
            srv.stop()
        assert not (Path(d) / "inbox").exists() or not any((Path(d) / "inbox").iterdir())  # stop clears unaccepted
        handed = []
        hs = link_handover_serve(handed.append, port=0)
        try:
            hp = hs.server_address[1]
            assert link_handover("channelmirror://open?to=vts", hp) and handed == ["channelmirror://open?to=vts"]
            import urllib.request
            try:  # without the token: refused
                urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{hp}/link", data=b"x",
                                                              method="POST"), timeout=3)
                raise AssertionError("took a link without the token")
            except OSError:
                pass
            assert handed == ["channelmirror://open?to=vts"]
        finally:
            hs.shutdown()
        assert not link_handover("channelmirror://open?to=vts", hp)  # nobody listening: the new copy opens itself
        # screen recorder: the area on a monitor -> desktop pixels (even sizes for H.264), and the ffmpeg command
        # a 2560 x 1440 monitor at 100% left of a 150% main one: the app (system DPI aware) sees it 1.5x larger
        mon = ("Monitor 1", -2560, 263, 2560, 1440, (-3840, 395, 3840, 2160))
        assert rec_area(mon, 100, 50, 641, 361) == (-2460, 313, 640, 360)
        assert rec_area(mon, 0, 0, 0, 0) == (-2560, 263, 2560, 1440)  # 0 x 0 = the whole monitor
        assert rec_to_app(mon, -2460, 313) == (-3690, 470) and rec_from_app(mon, -3690, 470) == (-2460, 313)
        main = ("Monitor 2", 0, 0, 3840, 2160, (0, 0, 3840, 2160))
        assert rec_to_app(main, 350, 350) == (350, 350) and rec_from_app(main, 3839, 0) == (3839, 0)
        for bad in ((2500, 0, 100, 100), (-1, 0, 100, 100), (0, 0, 8, 8), ("a", 0, 10, 10)):
            try:
                rec_area(mon, *bad)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        cmd = rec_command((-3740, 445, 640, 360), 30, Path("C:/out/a.mp4"), mouse=False)
        assert cmd[cmd.index("-offset_x") + 1] == "-3740" and cmd[cmd.index("-video_size") + 1] == "640x360"
        assert cmd[cmd.index("-draw_mouse") + 1] == "0" and cmd[-1] == str(Path("C:/out/a.mp4"))
        assert "gdigrab" in cmd and "-framerate" in cmd and cmd[cmd.index("-c:v") + 1] in ("libx264", "mpeg4")
        assert cmd[cmd.index("-g") + 1] == "60" and "frag_keyframe" in cmd[cmd.index("-movflags") + 1]
        assert rec_name(Path("C:/v"), "Clip", "2026-11-22 15-04-05") == Path("C:/v/Clip 2026-11-22 15-04-05.mp4")
        assert rec_name(Path("C:/v"), ' bad:/<>name ', "t") == Path("C:/v/bad____name t.mp4")
        # key mover: where copied keys land
        dst = {"1,0": one, "0,1": one}  # a 3x2 deck with two keys in use
        assert sd_place(["0,0", "1,0"], dst, 3, 2, "0,0") == {"0,0": "0,0", "1,0": "2,0"}  # 1,0 in use -> next free
        assert sd_place(["0,0", "1,0"], dst, 3, 2, "0,0", policy="replace") == {"0,0": "0,0", "1,0": "1,0"}
        assert sd_place(["0,0", "1,0"], dst, 3, 2, "0,0", policy="skip") == {"0,0": "0,0", "1,0": None}
        assert sd_place(["2,0", "2,1"], {}, 3, 2, "1,0") == {"2,0": "1,0", "2,1": "1,1"}  # same shape from the anchor
        assert sd_place(["2,0", "2,1"], {}, 3, 2, "2,1") == {"2,0": "2,1", "2,1": "0,0"}  # off the deck -> next free
        assert sd_place(["0,0", "1,0"], {}, 3, 2, "1,1", keep_layout=False) == {"0,0": "1,1", "1,0": "2,1"}
        assert sd_place(["0,0", "1,0"], dst, 3, 2, picks=["2,1", "0,1"]) == {"0,0": "2,1", "1,0": "1,1"}
        assert sd_place(["0,0", "1,0", "2,0"], {"0,0": one, "1,0": one, "2,0": one}, 3, 1) == {
            "0,0": None, "1,0": None, "2,0": None}  # a full deck: nowhere to go
        # icons: the image files a key or page shows (relative to its page folder)
        ik = sd_wrap("Multi Action", "m", [dict(sd_play(st), States=[{"Image": "Images/IN.png"}])])
        ik["States"] = [{"Image": "Images/A.png"}, {"Image": "Images/B.png", "Title": "x"}, {}]
        assert sd_images(ik) == {"Images/A.png", "Images/B.png", "Images/IN.png"}
        assert sd_images({"Controllers": [{"Actions": {"0,0": ik}}]}) == sd_images(ik) and sd_images(one) == set()
        ids = {}
        sd_clone_folders(copy.deepcopy(outer_key), {outer_id: outer_pg, inner_id: inner_pg}, ids=ids)
        assert sorted(ids.values()) == sorted([outer_id, inner_id])  # new page id -> the page it copies
        # writing an icon (bytes) alongside pages
        blob = Path(d) / "SD2" / "x.sdProfile" / "Profiles" / "P" / "Images" / "A.png"
        sd_save({blob: b"\x89PNG", blob.parents[1] / "manifest.json": {"Controllers": []}}, [], Path(d) / "SD2",
                Path(d) / "bk2")
        assert blob.read_bytes() == b"\x89PNG"
        # extra folders go just beside the first one, then on along the rows, then from the top
        assert sd_beside({"1,0": 1, "2,0": 1, "0,1": 1}, "1,0", 3, 2) == ["1,1", "2,1", "0,0"]
        assert sd_beside({"0,0": 1}, "0,0", 3, 1) == ["1,0", "2,0"]
        p1 = json.loads(pages[0].read_text())
        sd_keypad(p1)["0,1"] = key
        newp = new_dir / "Profiles" / pid.upper() / "manifest.json"
        unsaved = {pages[0]: p1, newp: fpage}  # not on disk yet: listed from the unsaved edits
        assert [n for n, _ in sd_pages(new_dir, new_m, unsaved)] == ["Page 1", "Folder: Hits", "Folder: SFX"]
        assert sd_pages(new_dir, new_m, unsaved)[1][1] == newp and not newp.exists()
        twin_key, twin_id, twin_pg, _ = sd_folder("Hits", [], 2, 2)  # a second folder with the same name
        sd_keypad(p1)["1,0"] = twin_key
        unsaved[new_dir / "Profiles" / twin_id.upper() / "manifest.json"] = twin_pg
        labels_ = [n for n, _ in sd_pages(new_dir, new_m, unsaved)]
        assert sorted(labels_) == ["Folder: Hits", "Folder: Hits #2", "Folder: SFX", "Page 1"], labels_
        assert len({p for _, p in sd_pages(new_dir, new_m, unsaved)}) == 4

        # output device: picking a Random/Multi key sets every sound inside it; saved values are offered back
        p1 = json.loads(pages[0].read_text())
        found = sd_multis([("Page 1", p1), ("Folder: SFX", {})])
        assert [(lbl, k, sd_kind(a)) for lbl, k, a in found] == [("Page 1", "0,0", "Random x2")]
        rnd = found[0][2]
        # Stream Deck saves the Windows endpoint id; the app shows names and saves ids
        real = dict(sd_win_outputs())
        _win_outputs.clear()
        _win_outputs.update({"Test Speakers (Selftest Audio)": "{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}"})
        try:
            sd_set_sound(sd_sounds(rnd), output="Test Speakers (Selftest Audio)")
            tid = "{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}"
            assert {s["Settings"]["outputType"] for s in sd_sounds(rnd)} == {tid}
            assert sd_out_name(tid) == "Test Speakers (Selftest Audio)" and sd_out_name("") == "default"
            assert sd_out(tid) == tid and sd_out_name("{0.0.0.00000000}.{gone}") == "{0.0.0.00000000}.{gone}"
            assert sd_keypad(p1)["1,0"]["Settings"]["outputType"] == ""  # other keys untouched
            pages[0].write_text(json.dumps(p1))
            assert sd_outputs(root) == [tid]
            assert sd_output_choices()[:2] == [SD_DEFAULT_OUT, "Test Speakers (Selftest Audio)"]
        finally:
            _win_outputs.clear()
            _win_outputs.update(real)
        # the format Stream Deck itself saved for this PC's devices, where present
        for name, iid in real.items():
            assert iid.startswith("{0.0.0.") and iid == iid.lower() and sd_out(name) == iid, (name, iid)
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

        # Setup tab: Light / Dark / Follow Windows, then each folder's check and the user's own choice of folder
        assert ui_mode("dark") == "dark" and ui_mode("light") == "light" and ui_mode("odd") == "light"
        assert ui_mode("system", lambda: False) == "dark" and ui_mode("system", lambda: True) == "light"
        assert ui_mode("system", lambda: None) == "light"  # Windows' setting unreadable: light
        assert win_light_theme() in (True, False, None)
        for pal in (UI_LIGHT, UI_DARK):
            assert pal.keys() == UI_LIGHT.keys()
            used = [pal[k] for k in ("bg", "panel", "border", "accent", "accent2", "sound", "missing", "other", "auto")]
            assert len(set(used)) == len(used), used  # a colour on screen maps back to one meaning when switching
        s = Path(d) / "setup"
        assert setup_check("sd_dir", s) == "missing" and setup_check("vts", s) == "missing"
        (s / "ProfilesV3" / "X.sdProfile").mkdir(parents=True)
        (s / "ProfilesV3" / "X.sdProfile" / "manifest.json").write_text('{"Name": "X"}')
        (s / "Backgrounds").mkdir(), (s / "Live2DModels").mkdir()
        assert setup_check("sd_dir", s) == "found" and setup_check("vts", s) == "found"
        (s / "ffmpeg.exe").write_bytes(b"")
        assert setup_check("ffmpeg", s) == "missing"  # needs ffprobe too
        (s / "ffprobe.exe").write_bytes(b"")
        assert setup_check("ffmpeg", s) == "found" and setup_check("sd_exe", s / "ffmpeg.exe") == "found"
        assert setup_check("sd_exe", s / "none.exe") == "missing" and setup_check("sd_exe", None) == "missing"
        assert setup_check("inbox", s / "new") == "new" and setup_check("inbox", s) == "found"
        assert setup_auto("vts_backups") == FFMPEG_DIR.parent / "VTube Studio backups"
        keep, path0 = {k: globals()[k] for k in SETUP_GLOBALS.values()}, os.environ["PATH"]
        try:
            setup_apply({"sd_dir": str(s), "sd_backups": str(s / "bk"), "ffmpeg": str(s), "inbox": "", "odd": "x"})
            assert SD_DIR == s and SD_BACKUPS == s / "bk" and LINK_INBOX == keep["LINK_INBOX"]  # blank = auto
            assert os.environ["PATH"].split(os.pathsep)[0] == str(s)
            setup_apply({"ffmpeg": str(s)})
            assert os.environ["PATH"].split(os.pathsep).count(str(s)) == 1  # not added twice
            assert [p.name for p, _ in sd_profiles()] == ["X.sdProfile"]  # the chosen folder, looked up at call time
            assert sd_save({s / "a.json": {}}, [s / "ProfilesV3" / "X.sdProfile"]).parent == s / "bk"
            setup_apply({"vts_backups": str(s / "vb"), "vts": str(s)})
            assert vts_backups() == s / "vb" and VTS_ASSETS == s
        finally:
            globals().update(keep)
            os.environ["PATH"] = path0
        assert vts_backups() == FFMPEG_DIR.parent / "VTube Studio backups"
        cmd = app_command()
        assert cmd[0] == sys.executable and (getattr(sys, "frozen", False) or  # the exe restarts itself; from
                                            Path(cmd[1]) == Path(__file__).resolve()), cmd  # source: python + script
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
    _link = link_args(sys.argv[1:])
    if _link:  # opened by a link: no other option on that command line counts (a link can't add --uninstall)
        if not link_handover(_link):
            gui()
    elif "--selftest" in sys.argv:
        selftest()
    elif "--uninstall" in sys.argv:
        uninstall_cli()
    elif "--install" in sys.argv and getattr(sys, "frozen", False):  # silent install for scripts: every shortcut, then done
        install(Path(sys.executable), links=shortcut_paths())
    else:
        gui()
