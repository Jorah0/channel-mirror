"""Screen recorder: an area of a monitor -> a video file, through ffmpeg's Windows screen grabber."""
import subprocess
from pathlib import Path
from .core import NO_WINDOW


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
    # zerolatency: x264 holds no frames back (look-ahead), so what was captured is in the file at once
    enc = (["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-crf", "20", "-pix_fmt", "yuv420p"]
           if rec_codec() == "libx264" else ["-c:v", "mpeg4", "-q:v", "3"])
    enc += ["-g", str(max(2, int(fps) * 2))]  # a keyframe (and so a finished piece of file) every 2 s
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "gdigrab", "-framerate", str(int(fps)),
            "-draw_mouse", "1" if mouse else "0", "-offset_x", str(x), "-offset_y", str(y), "-video_size",
            f"{w}x{h}", "-i", "desktop", *enc,
            # written in self-contained pieces: a recording cut off (crash, killed) still plays, and Stop is instant
            # (a piece at least every 0.5 s: a crash loses half a second at most)
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "500000",
            "-flush_packets", "1", str(out)]


REC_DEST = ("Folder I pick", "VTube Studio backgrounds (this PC)")


REC_PEER = "VTube Studio backgrounds on "  # + a linked computer's name


def rec_name(folder, prefix, stamp):
    """The file a recording goes to: <folder>/<prefix> <date time>.mp4 (characters Windows won't take become _)."""
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in str(prefix).strip()) or "Recording"
    return Path(folder) / f"{safe} {stamp}.mp4"
