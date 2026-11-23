"""Transcriber: speech in any video / audio file -> timed voice lines, through ffmpeg's whisper filter (whisper.cpp)."""
import hashlib
import json
import os
import re
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from .core import FFMPEG_DIR, NO_WINDOW
from .mirror import probe


# beside the downloaded ffmpeg: %LOCALAPPDATA%\ChannelMirror\whisper
WHISPER_DIR = FFMPEG_DIR.parent / "whisper"


# the official whisper.cpp models; nothing else is ever fetched (the name only picks one of these)
# (each repo at a fixed commit, so the files can't change under the checksums below)
WHISPER_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-{}.bin"
VAD_URL = "https://huggingface.co/ggml-org/whisper-vad/resolve/9ffd54a1e1ee413ddf265af9913beaf518d1639b/ggml-{}.bin"


# name -> (bytes, SHA-256): Hugging Face's LFS record of each file (its README lists the same files' SHA-1s)
WHISPER_MODELS = {
    "tiny": (77691713, "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21"),
    "tiny.en": (77704715, "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f"),
    "base": (147951465, "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"),
    "base.en": (147964211, "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002"),
    "small": (487601967, "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"),
    "small.en": (487614201, "c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"),
    "medium": (1533763059, "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208"),
    "medium.en": (1533774781, "cc37e93478338ec7700281a7ac30a10128929eb8f427dda2e865faa8f6da4356"),
    "large-v3-turbo": (1624555275, "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"),
}
WHISPER_DEFAULT = "small"


# Silero voice detection (optional): long silences are skipped instead of transcribed
VAD_MODELS = {"silero-v5.1.2": (885098, "29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf")}
VAD_MODEL = "silero-v5.1.2"


# dropdown label -> whisper's language code
WHISPER_LANGS = {"Auto-detect": "auto", "English": "en", "Spanish": "es", "French": "fr", "German": "de",
                 "Italian": "it", "Portuguese": "pt", "Dutch": "nl", "Polish": "pl", "Swedish": "sv",
                 "Norwegian": "no", "Danish": "da", "Finnish": "fi", "Russian": "ru", "Ukrainian": "uk", "Turkish": "tr",
                 "Greek": "el", "Arabic": "ar", "Hebrew": "he", "Hindi": "hi", "Indonesian": "id", "Vietnamese": "vi",
                 "Thai": "th", "Chinese": "zh", "Japanese": "ja", "Korean": "ko"}


# output checkboxes: key -> extension
DOC_FORMATS = {"docx": ".docx", "pdf": ".pdf", "srt": ".srt", "txt": ".txt"}


class Cancelled(Exception):
    pass


def whisper_ok(ffmpeg="ffmpeg"):
    """Does this ffmpeg have the whisper filter (8.0+, built with whisper.cpp)?"""
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-h", "filter=whisper"], capture_output=True, text=True,
                             errors="replace", timeout=20, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "whisper AVOptions" in out.stdout


def model_file(name, table=None, folder=None):
    table = WHISPER_MODELS if table is None else table
    if name not in table:  # only a pinned name ever becomes a path or a URL
        raise ValueError(f"Unknown model '{name}'")
    return Path(folder or WHISPER_DIR) / f"ggml-{name}.bin"


def model_ready(name, table=None, folder=None):
    """Downloaded and the right size (the checksum was checked when it arrived)."""
    f = model_file(name, table, folder)
    return f.is_file() and f.stat().st_size == (table or WHISPER_MODELS)[name][0]


def model_download(name, progress=print, cancel=None, table=None, url=WHISPER_URL, folder=None):
    """Fetch a pinned model into folder: into a .part file first (resumed from where a cancelled / broken download
    stopped, when the server allows), its size and SHA-256 checked, then renamed into place. cancel: an Event ->
    Cancelled (the .part is kept for next time). Returns the model's path."""
    table = WHISPER_MODELS if table is None else table
    dest = model_file(name, table, folder)
    size, sha = table[name]
    if model_ready(name, table, folder):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.is_file() else 0
    if have >= size:  # a whole one that was never checked: fetched again
        part.unlink()
        have = 0
    h = hashlib.sha256()
    req = urllib.request.Request(url.format(name), headers={"User-Agent": "ChannelMirror"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    try:
        r = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code != 416 or not have:
            raise
        part.unlink()  # the server can't continue that .part: start again from nothing
        return model_download(name, progress, cancel, table, url, folder)
    with r:
        if have and r.status == 206 and r.headers.get("Content-Range", "").startswith(f"bytes {have}-"):
            with open(part, "rb") as old:
                while chunk := old.read(1 << 20):
                    h.update(chunk)
            mode = "ab"
        else:  # no resume from this server: start again
            have, mode = 0, "wb"
        got = have
        with open(part, mode) as out:
            while chunk := r.read(1 << 16):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                got += len(chunk)
                if got > size:
                    break
                out.write(chunk)
                h.update(chunk)
                progress(f"Downloading the {name} model... {got >> 20} of {size >> 20} MB", got / size)
    if got < size:  # the connection ended early: the .part stays, the next try carries on from it
        raise RuntimeError(f"the {name} model download was cut off at {got >> 20} of {size >> 20} MB; start again to "
                           "continue it")
    if got != size or h.hexdigest() != sha:  # damaged or too long: never kept
        part.unlink()
        raise RuntimeError(f"the {name} model download is damaged (size or checksum wrong); please try again")
    os.replace(part, dest)
    return dest


def _esc(value):
    """A value for a filter option inside a filtergraph: escaped for the option parser, then for the graph."""
    v = re.sub(r"([\\':])", r"\\\1", str(value))
    return re.sub(r"([\\'\[\],;])", r"\\\1", v)


def whisper_command(src, model, dest, lang="auto", gpu=True, vad=None, ffmpeg="ffmpeg"):
    """ffmpeg reads src's first audio track as it goes (hours are fine: streamed, never loaded whole), resamples it
    to 16 kHz mono for whisper, and whisper writes its voice lines to dest as JSON; progress comes on stdout."""
    opts = [f"model={_esc(Path(model).as_posix())}", f"language={_esc(lang)}", f"use_gpu={int(bool(gpu))}",
            "format=json", f"destination={_esc(Path(dest).as_posix())}"]
    # whisper hears 30 s at a time: the whole window per pass is both fastest and most accurate. ponytail: the voice
    # detection of ffmpeg 8.1's filter re-reads its whole queue on every frame, so with it the queue stays at the
    # filter's 3 s (measured on a 55 s clip, tiny.en, RTX 4090: 1.5 s without it, 26 s with it; 274 s at 30 s)
    opts.append(f"vad_model={_esc(Path(vad).as_posix())}" if vad else "queue=30")
    return [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-v", "error", "-progress", "pipe:1", "-i", str(src),
            "-map", "0:a:0", "-vn", "-af", "aresample=16000,aformat=channel_layouts=mono,whisper=" + ":".join(opts),
            "-f", "null", "-"]


def whisper_parse(text):
    """The filter's JSON output -> [(start s, end s, text)]. It writes one object per voice line, one per line
    ({"start": ms, "end": ms, "text": ...}); a JSON array of the same is read too. Blank lines are dropped."""
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        items = json.loads(text)
    else:
        items = [json.loads(line.rstrip(",")) for line in text.splitlines() if line.strip().strip(",[]")]
    out = []
    for x in items:
        t = " ".join(str(x.get("text", "")).split())
        if t:
            out.append((float(x.get("start", 0)) / 1000, float(x.get("end", 0)) / 1000, t))
    return out


def srt_parse(text):
    """SubRip text -> [(start s, end s, text)]."""
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)[^\n]*\n(.*)", block, re.S)
        if m:
            g = [int(x) for x in m.groups()[:8]]
            out.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
                        " ".join(m.group(9).split())))
    return out


def stamp(secs, ms=False):
    """Seconds -> hh:mm:ss (hh:mm:ss,mmm for subtitles)."""
    t = max(0, round(secs * 1000))
    s = f"{t // 3600000:02d}:{t // 60000 % 60:02d}:{t // 1000 % 60:02d}"
    return s + f",{t % 1000:03d}" if ms else s


def srt_text(segments):
    return "".join(f"{i}\n{stamp(a, True)} --> {stamp(b, True)}\n{t}\n\n" for i, (a, b, t) in enumerate(segments, 1))


def txt_text(title, segments):
    return f"{title}\n\n" + "".join(f"[{stamp(a)}]  {t}\n" for a, _, t in segments)


def media_seconds(path):
    """A file's length (0 when ffprobe can't tell); ValueError when it has no audio track at all."""
    probe(path)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
    try:
        return float(json.loads(out.stdout or "{}").get("format", {}).get("duration") or 0)
    except ValueError:
        return 0.0


def transcribe(src, model, lang="auto", gpu=True, vad=None, progress=None, cancel=None, info=None):
    """One file -> [(start s, end s, text)]. progress(fraction) as ffmpeg goes; cancel: an Event (-> Cancelled, ffmpeg
    stopped at once). On the GPU first when asked; when that run fails, again on the CPU. Errors: ValueError (no
    audio), RuntimeError (ffmpeg said why). info (a dict) gets "gpu": whether the graphics card did it."""
    import tempfile
    total = media_seconds(src)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "lines.json"
        for use_gpu in ([True, False] if gpu else [False]):
            dest.unlink(missing_ok=True)
            said = _run(whisper_command(src, model, dest, lang, use_gpu, vad), total, progress, cancel)
            if said is None:
                if info is not None:
                    info["gpu"] = use_gpu
                return whisper_parse(dest.read_text(encoding="utf-8", errors="replace") if dest.exists() else "")
        raise RuntimeError(said or "ffmpeg stopped without saying why")


def _run(cmd, total, progress, cancel):
    """Run one ffmpeg; None when it finished, else what it said."""
    import tempfile
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL,
                                creationflags=NO_WINDOW)
        if cancel is not None:
            cancel.proc = proc  # the app closing kills it straight from there
        stop = threading.Event()

        def watch():  # Cancel stops ffmpeg straight away, even while it's busy and printing nothing
            while not stop.wait(0.2):
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    return
        threading.Thread(target=watch, daemon=True).start()
        try:
            for line in proc.stdout:
                k, _, v = line.decode(errors="replace").strip().partition("=")
                if k == "out_time_us" and v.isdigit() and total and progress:
                    progress(min(1.0, int(v) / 1e6 / total))
            code = proc.wait()
        finally:
            stop.set()
            if proc.poll() is None:  # never left running behind an error
                proc.kill()
                proc.wait()
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if code == 0:
            return None
        err.seek(0)
        return err.read().decode(errors="replace").strip()[-600:] or f"ffmpeg ended with code {code}"


def transcript_paths(src, folder=None, formats=DOC_FORMATS, taken=None):
    """Where one file's transcript goes: beside it (or in folder), "<name> transcript.<ext>" - never over a subtitle
    or text file the video already has. taken: paths given out already this run (two files of one name: "(2)")."""
    src = Path(src)
    base = Path(folder) if folder else src.parent
    n, out = 1, None
    while out is None or (taken is not None and set(out.values()) & taken):
        stem = src.stem if n == 1 else f"{src.stem} ({n})"
        out = {k: base / f"{stem} transcript{DOC_FORMATS[k]}" for k in formats}
        n += 1
    if taken is not None:
        taken.update(out.values())
    return out


def write_transcript(src, segments, folder=None, formats=DOC_FORMATS, fonts=None, taken=None):
    """The chosen documents for one file -> {format: path}. Each is written whole to a temp name, then renamed
    (a transcript made before for the same file is replaced)."""
    from .docs import docx_write, pdf_write
    title = Path(src).stem
    lines = [(stamp(a), t) for a, _, t in segments] or [("--:--:--", "No speech was found in this file.")]
    out = transcript_paths(src, folder, formats, taken)
    next(iter(out.values())).parent.mkdir(parents=True, exist_ok=True)
    for k, path in out.items():
        tmp = path.with_name(path.name + ".part")
        try:
            if k == "docx":
                docx_write(tmp, title, lines)
            elif k == "pdf":
                pdf_write(tmp, title, lines, fonts=fonts)
            else:
                tmp.write_text(srt_text(segments) if k == "srt" else txt_text(title, segments), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    return out
