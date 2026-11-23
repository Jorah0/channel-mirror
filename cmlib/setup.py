"""Setup: where things are on this PC (found automatically, or picked and kept in the settings)."""
import os
import shutil
import sys
from pathlib import Path
from .core import MAIN, set_shared, shared
from .core import FFMPEG_DIR
from .vts import vts_assets


# --- Setup tab: where things are on this PC (found automatically, or picked by the user and kept in the settings) ---
PATH_START = os.environ.get("PATH", "")  # before an ffmpeg folder picked in the Setup tab is put in front


SETUP_GLOBALS = {"sd_dir": "SD_DIR", "sd_exe": "SD_EXE", "vts": "VTS_ASSETS", "inbox": "LINK_INBOX",
                 "sd_backups": "SD_BACKUPS", "vts_backups": "VTS_BACKUPS"}


SETUP_AUTO = {k: shared(v) for k, v in SETUP_GLOBALS.items()}  # as found at start, before any choice is applied


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
            set_shared(SETUP_GLOBALS[key], Path(value))


def setup_reset(key):
    """Back to finding it automatically (Auto in the Setup tab)."""
    if key == "ffmpeg":
        os.environ["PATH"] = PATH_START
    elif key in SETUP_GLOBALS:
        set_shared(SETUP_GLOBALS[key], SETUP_AUTO[key])


def app_command():
    """The command that starts this app again (Restart in the Setup tab): the exe, or python + this script."""
    keep = [a for a in sys.argv[1:] if a == "--portable"]
    return ([sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(MAIN)]) + keep


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
