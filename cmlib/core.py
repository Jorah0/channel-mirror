"""Shared basics: file types, settings path, ffmpeg (found or downloaded), helpers every part uses."""
import os
import subprocess
import sys
import threading
from pathlib import Path


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


ROOT = Path(__file__).resolve().parent.parent  # the folder that holds the master file
MAIN = ROOT / "channel_mirror.py"  # the master file: what python runs
BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT))  # _MEIPASS = unpacked exe bundle


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


def atomic_write(path, text):
    """Write a text file whole or not at all (a temp file beside it, then swapped in)."""
    import secrets
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


_SETTINGS_LOCK = threading.Lock()


def settings_put(**sections):
    """Write these sections of the settings now (the rest of the file as it is on disk), never half-written.
    OSError (nothing written) when the file is there but can't be read - it's never replaced by a part of itself."""
    import json
    with _SETTINGS_LOCK:
        try:
            cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except FileNotFoundError:
            cfg = {}
        except ValueError as e:
            raise OSError(f"the settings file can't be read: {e}") from None
        if not isinstance(cfg, dict):
            raise OSError("the settings file can't be read")
        atomic_write(SETTINGS, json.dumps({**cfg, **sections}))


def _dpapi(data, protect):
    """Windows DPAPI (this Windows user only): CryptProtectData / CryptUnprotectData. OSError when it can't."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    try:
        crypt, kernel = ctypes.windll.crypt32, ctypes.windll.kernel32
    except AttributeError:
        raise OSError("DPAPI is Windows only") from None
    bufs = [ctypes.create_string_buffer(b, len(b)) for b in (data, b"ChannelMirror secret")]  # alive until the end
    src, extra = (Blob(len(b), ctypes.cast(b, ctypes.POINTER(ctypes.c_char))) for b in bufs)
    out = Blob()
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    if not fn(ctypes.byref(src), None, ctypes.byref(extra), None, None, 1, ctypes.byref(out)):  # 1 = never ask
        raise OSError("Windows couldn't " + ("protect" if protect else "read") + " the secret")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel.LocalFree(out.pbData)


def secret_keep(text):
    """A secret as the settings keep it: sealed with DPAPI for this Windows user ("dpapi:..."). OSError if it can't be."""
    import base64
    return "dpapi:" + base64.b64encode(_dpapi(str(text).encode(), True)).decode() if text else ""


def secret_read(kept):
    """A secret from the settings: unsealed; an old plain value as it is; None when it can't be read here (another
    user or PC, or damaged)."""
    import base64
    import binascii
    kept = str(kept or "")
    if not kept.startswith("dpapi:"):
        return kept
    try:
        return _dpapi(base64.b64decode(kept[6:], validate=True), False).decode()
    except (OSError, ValueError, binascii.Error):
        return None


def _parts():
    """The loaded parts, and the master file (as a module, or as __main__ when run as a script)."""
    return [m for k, m in list(sys.modules.items()) if k.startswith(__package__ + ".") or k in ("channel_mirror", "__main__")
            and getattr(m, "__file__", None) and Path(m.__file__).resolve() == MAIN]


def shared(name):
    """A module-level setting's current value. The app was one file; each part holds its own copy of the names it
    uses, so settings are read with shared() / changed with set_shared() wherever the app changes them at run time."""
    for m in _parts():
        if name in vars(m):
            return vars(m)[name]
    raise KeyError(name)


def set_shared(name, value):
    """Change a module-level setting in every part that holds it (Setup tab choices; tests swapping a function)."""
    import types
    for m in _parts():
        if name in vars(m):
            types.ModuleType.__setattr__(m, name, value)
