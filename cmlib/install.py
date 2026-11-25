"""Self-install: the one ChannelMirror.exe is also its own installer / updater / uninstaller."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from .core import BUNDLE, FFMPEG_DIR, NO_WINDOW, SETTINGS, atomic_write, download_ffmpeg


# --- self-install: the one ChannelMirror.exe is also its own installer / updater / uninstaller ---
VERSION = "2.3"


APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / "ChannelMirror"


UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ChannelMirror"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # programs Windows starts at sign-in (per user)


def startup_get():
    """The command Windows runs at sign-in for Channel Mirror, or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, "ChannelMirror")[0]
    except OSError:
        return None


def startup_set(cmd):
    """Start Channel Mirror when Windows starts: cmd = the command (a list), or None = don't."""
    import winreg
    if cmd:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, "ChannelMirror", 0, winreg.REG_SZ, subprocess.list2cmdline(cmd))
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "ChannelMirror")
        except OSError:
            pass


def shortcut_paths():
    """Where install() puts shortcuts: {"start", "desktop", "sendto", "sendto_peer"} -> .lnk path (per user, no admin
    needed). sendto_peer = Send to > Channel Mirror (linked computers): its files go to a linked computer."""
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
            "sendto": roaming / "Microsoft" / "Windows" / "SendTo" / "Channel Mirror.lnk",
            "sendto_peer": roaming / "Microsoft" / "Windows" / "SendTo" / "Channel Mirror (linked computers).lnk"}


def make_shortcut(lnk, target, args=""):
    q = lambda p: str(p).replace("'", "''")  # PowerShell single-quote escaping
    lnk.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');$s.TargetPath='{q(target)}';"
                        f"$s.Arguments='{q(args)}';$s.WorkingDirectory='{q(Path(target).parent)}';"
                        f"$s.IconLocation='{q(target)},0';$s.Save()"],
                       capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
    if r.returncode or not lnk.exists():
        raise OSError(f"Couldn't create shortcut {lnk.name}: {r.stderr.strip()[-300:]}")


def install(src, app_dir=APP_DIR, links=None, reg_key=UNINSTALL_KEY):
    """Copy the exe into app_dir, add the given shortcuts, register with Windows "Installed apps" (per user).
    Running it again over an older copy is the update. Returns the installed exe."""
    from .link import LINK_TO_PEER, link_register  # a later part: imported when used
    import winreg
    app_dir.mkdir(parents=True, exist_ok=True)
    exe = app_dir / "ChannelMirror.exe"
    if Path(src).resolve() != exe.resolve():
        shutil.copy2(src, exe)
    for k, lnk in (links or {}).items():
        make_shortcut(lnk, exe, LINK_TO_PEER if k == "sendto_peer" else "")  # it opens the linked-PC chooser
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


def uninstall(app_dir=APP_DIR, links=None, reg_key=UNINSTALL_KEY, data=False, data_dir=None):
    """Remove shortcuts, the Windows entry and the program folder (deleted once this process exits, since a
    running exe can't delete itself). data=True also removes settings and the downloaded ffmpeg etc. - but never
    data_dir\\android (the CM Remote release key: lost, installed phones could never be updated again)."""
    from .link import link_registered, link_unregister  # a later part: imported when used
    import winreg
    for lnk in (links or shortcut_paths()).values():
        Path(lnk).unlink(missing_ok=True)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_key)
    except OSError:
        pass
    if reg_key == UNINSTALL_KEY and str(app_dir) in (link_registered() or ""):
        link_unregister()  # links pointed at this install
    if reg_key == UNINSTALL_KEY and str(app_dir) in (startup_get() or ""):
        startup_set(None)  # don't start a removed program at sign-in
    if data:
        SETTINGS.unlink(missing_ok=True)
        data_dir = Path(data_dir or FFMPEG_DIR.parent)  # nothing in it runs now: deleted here, android kept
        for p in (data_dir.iterdir() if data_dir.is_dir() else []):
            if p.name.lower() == "android":
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink(missing_ok=True)
                except OSError:  # in use: left behind, the uninstall still finishes
                    pass
        try:
            data_dir.rmdir()  # only when empty
        except OSError:
            pass
    running = getattr(sys, "frozen", False) and Path(sys.executable).resolve().is_relative_to(app_dir.resolve())
    if running:
        # ponytail: a detached cmd waits ~3 s for this exe to exit, then deletes the folder
        subprocess.Popen(f'cmd /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "{app_dir}"',
                         creationflags=NO_WINDOW | 0x00000008, close_fds=True)  # 0x8 = DETACHED_PROCESS
    else:
        shutil.rmtree(app_dir, ignore_errors=True)


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
    tk.Checkbutton(frame, text='Right-click "Send to > Channel Mirror" (and "...(linked computers)") for files and '
                              'folders',
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
            atomic_write(SETTINGS, json.dumps(cfg))
        except OSError:
            pass
        return False
    paths = shortcut_paths()
    links = {k: p for k, p in paths.items() if k == "start" or opts[k.removesuffix("_peer")].get()}
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
