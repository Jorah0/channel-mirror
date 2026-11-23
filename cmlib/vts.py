"""VTube Studio backgrounds: copy files in, a ChangeBackground hotkey each, a Stream Deck key each."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from .core import FFMPEG_DIR, NO_WINDOW
from .mirror import natural
from .deck import sd_uid


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
