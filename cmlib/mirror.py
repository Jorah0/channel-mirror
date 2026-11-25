"""Channel Mirror itself: analyse a file's channels, route one channel to both / left / right with ffmpeg."""
import json
import numpy as np
import subprocess
from pathlib import Path
from .core import AUDIO_EXT, AUDIO_ONLY_EXT, ENCODER_OPTS, FRAMES_PER_READ, NO_WINDOW, VIDEO_EXT, VIDEO_OUT


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
    try:
        while chunk := proc.stdout.read(FRAMES_PER_READ * 4 * n):  # blocks for full frames until EOF
            a = np.frombuffer(chunk, "<f4").reshape(-1, n).astype(np.float64)
            sq += (a * a).sum(0)
            peak = np.maximum(peak, np.abs(a).max(0))
            frames += len(a)
    except BaseException:  # never leave ffmpeg blocked on a full pipe
        proc.kill()
        proc.wait()
        raise
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


_JUNK = ("kbps|official|lyrics?|audio|video|hq|hd|free download|visuali[sz]er|remaster(?:ed)?|bass boosted|"
         "copyright free|no copyright")


def clean_name(text, limit=20):
    """A key title from a file or folder name: separators (_ %20, or - . in a name with no spaces) become spaces,
    download junk ("y2mate.com - ", "(128 kbps)", "[Official Audio]", "01 - ") goes, punctuation is spaced the
    normal way, an all-lowercase name gets capitals, and a long one is cut at a word, at most `limit` long."""
    import re
    import urllib.parse
    s = urllib.parse.unquote(str(text)).replace("_", " ")
    s = re.sub(r"^\S+\.(?:com|net|org|is|io|cc|co|me|to|app)\s*-\s*", "", s, flags=re.I)  # y2mate.com - ...
    s = re.sub(rf"\s*[(\[][^)\]]*(?:{_JUNK})[^)\]]*[)\]]", "", s, flags=re.I)
    s = re.sub(r"^\d{1,3}\s*[-.)]\s+(?=\S)", "", s)  # a track number: "01 - Intro", "2. Outro"
    if " " not in s.strip():
        if s.count("-") > 1 or "." in s.strip("."):
            s = re.sub(r"[-.]+", " ", s)
        s = re.sub(r"(?<=[a-z]{2})(?=[A-Z][a-z])", " ", s)  # AirHorn -> Air Horn (not iPhone)
    s = re.sub(r"\s+([,.!?;:)\]])", r"\1", s)  # no space before punctuation
    s = re.sub(r"([(\[])\s+", r"\1", s)
    s = re.sub(r"([,!?;])(?=[A-Za-z])", r"\1 ", s)  # one space after it
    s = re.sub(r"\(\s*\)|\[\s*\]", "", s)
    s = " ".join(s.split()).strip(" -,;:")
    if re.search(r"[a-z]", s) and not re.search(r"[A-Z]", s):
        s = re.sub(r"[a-z][a-z']*", lambda m: m[0][0].upper() + m[0][1:], s)
    if len(s) > limit:
        i = s[:limit + 1].rfind(" ")
        s = (s[:i] if i >= limit // 2 else s[:limit]).rstrip(" -_,;:([{")
        for o, c in ("()", "[]"):
            if s.count(o) > s.count(c):
                s = s[:s.rfind(o)].rstrip(" -,;:")
    return s or str(text).strip()[:limit]


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
