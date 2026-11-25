"""Stream Deck: soundboard profiles to import, and editing the profiles installed in the Stream Deck app."""
import json
import numpy as np
import os
import subprocess
from pathlib import Path
from .core import FFMPEG_DIR, NO_WINDOW
from .mirror import clean_name, probe


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
    try:
        while chunk := proc.stdout.read(blk * n * 4 * 250):
            a = np.frombuffer(chunk, "<f4").reshape(-1, n)
            k = len(a) // blk
            if k:
                ms.append((a[:k * blk].astype(np.float64).reshape(k, blk, n) ** 2).mean(1))
    except BaseException:  # never leave ffmpeg blocked on a full pipe
        proc.kill()
        proc.wait()
        raise
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
            t = clean_name(path.stem if len(snds) == 1 else path.parent.name)
        elif source == "Folder name" and path:
            t = clean_name(path.parent.name)
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
            s["States"][0]["Title"] = clean_name(Path(s.get("Settings", {}).get("path", "")).stem)
        kp[k] = s
    return len(plays)


def sd_stop_key():
    return {"ActionID": sd_uid(), "LinkedTitle": True, "Name": "Stop Audio", "Plugin": dict(SD_SOUNDBOARD),
            "Resources": None, "Settings": {}, "State": 0, "States": [{"Title": "STOP"}], "UUID": SD_STOP}


def sd_plays_like(files, like=None):
    """A Play Audio action per file, named after it, with the playback settings of `like` (a Play Audio action)."""
    se = (like or {}).get("Settings", {})
    pick = lambda t, i: t[i] if isinstance(i, int) and 0 <= i < len(t) else t[0]
    return [sd_play(f, clean_name(Path(f).stem), pick(SD_MODES, se.get("actionType")), pick(SD_FADES, se.get("fadeType")),
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


def sd_folder_map(old, new, old_pages, new_pages, out=None):
    """{new page id: source page id} for a folder key and its copy made by sd_clone_folders (same shape, new ids):
    which source page each new folder page copies (to give it that page's icons)."""
    out = {} if out is None else out
    pid = lambda a: str((a.get("Settings") or {}).get("ProfileUUID", "")).lower() if isinstance(a, dict) else ""
    po, pn = pid(old), pid(new)
    pages_n = {str(k).lower(): k for k in new_pages}
    if old.get("UUID") != SD_FOLDER or po not in old_pages or pn not in pages_n or pages_n[pn] in out:
        return out
    out[pages_n[pn]] = po
    keys = lambda pg: next((c.get("Actions") or {} for c in pg.get("Controllers") or [] if c.get("Type") == "Keypad"),
                           {})
    ko, kn = keys(old_pages[po]), keys(new_pages[pages_n[pn]])
    for k, a in ko.items():
        if a and kn.get(k):
            sd_folder_map(a, kn[k], old_pages, new_pages, out)
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
        tmp = Path(path).with_name(Path(path).name + ".writing")
        if isinstance(data, bytes):  # a key's icon copied with it
            tmp.write_bytes(data)
        else:
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        for i in range(20):  # whole or not at all: the editor may be reading the old one this moment
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if i == 19:
                    raise
                time.sleep(0.05)
    return zpath


def sd_install(name, device, sounds, keys, sd_dir=None, folders=None):
    """{file: json} that puts a new soundboard profile straight into Stream Deck's profile folder (no import prompt).
    Installed profiles play from each sound's own path, so no audio is copied. folders: see sd_profile_files."""
    files, _ = sd_profile_files(name, device, sounds, keys, folders)
    root = (sd_dir or SD_DIR) / "ProfilesV3"
    return {root / arc.split("/", 1)[1]: data for arc, data in files.items() if arc.startswith("Profiles/")}
