"""The Screen recorder tab in the main window, on both real monitors (they run at different scalings), checked to the
exact pixel. On each monitor: a test pattern is drawn in real pixels (pattern_window.py); the area is picked from the
tab's own controls (monitor list, the on-screen drag, typed values); the outline must sit exactly around it and be
left out of anything captured, even a capture that covers it; Record / Stop from the floating button; the saved file
must be exactly the area's size and show exactly the pattern (its 1-pixel border on the frame's edges, nothing of the
magenta around it, corners the right way round). Then: odd sizes, typing while recording, a recording killed mid-way
(still plays), two recordings in the same second, settings kept on close. Recordings go to a temp folder."""
import ctypes
import ctypes.wintypes
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from harness import App, walk
from pattern_window import CORNERS, MAGENTA, pattern

import numpy as np
from tkinter import ttk

HERE = Path(__file__).resolve().parent
recs = Path(tempfile.mkdtemp(prefix="cm_rec_"))
app = App({"recorder": {"folder": str(recs), "name": "Test clip", "fps": 15, "mouse": False}})
cm = app.cm
app.start()
page = app.tab("Screen recorder")
rec = app.api("recorder")
v, st = rec["vars"], rec["state"]
PAD = 4  # the outline sits this many pixels outside the recorded area


def entry(var):
    return next(e for e in walk(page) if isinstance(e, ttk.Entry) and not isinstance(e, ttk.Combobox)
                and str(e.cget("textvariable")) == str(var))


def type_in(var, text):
    e = entry(var)
    e.delete(0, "end")
    e.insert(0, str(text))
    app.pump(0.05)


def pick_monitor(label):
    cb = next(c for c in walk(page) if isinstance(c, ttk.Combobox) and str(c.cget("textvariable")) == str(v["mon"]))
    cb.set(label)
    cb.event_generate("<<ComboboxSelected>>")
    app.pump(0.2)


def records_label():
    return [str(lb.cget("text")) for lb in walk(page) if isinstance(lb, ttk.Label)
            and str(lb.cget("text")).startswith("Records ")]


def grab(x, y, w, h):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "gdigrab", "-draw_mouse", "0", "-offset_x", str(x),
                          "-offset_y", str(y), "-video_size", f"{w}x{h}", "-i", "desktop", "-frames:v", "1", "-f",
                          "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


def frames(f, w, h, times):
    out = []
    for t in times:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(f), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        out.append(np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(int))
    return out


def real_rect(win):
    """Where Windows really shows a window, in desktop pixels (left, top, right, bottom): asked of Windows itself,
    not worked out through the app's own sums."""
    app.pump(0.05)
    r = ctypes.wintypes.RECT()
    cm.rec_pm(ctypes.windll.user32.GetWindowRect, int(win.wm_frame(), 16), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def outline_real(mon):
    return real_rect(st["outline"])


def wait_stopped(secs=30):
    assert app.wait(lambda: st["proc"] is None, secs), "the recording didn't finish"


def check_video(f, w, h, label):
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                                      "-show_entries", "stream=width,height,nb_read_frames:format=duration",
                                      "-of", "json", str(f)], capture_output=True, text=True).stdout)
    s = info["streams"][0]
    assert (s["width"], s["height"]) == (w, h), (label, s)
    want = pattern(w, h).astype(int)
    for i, fr in enumerate(frames(f, w, h, (0.4, 1.0, 1.6))):
        diff = np.abs(fr - want).mean()
        # the 1-pixel border is the frame's very first / last row and column (1 pixel off = magenta or black there)
        edge_ok = all(e.mean() > 200 for e in (fr[0], fr[-1], fr[:, 0], fr[:, -1]))
        inner_ok = all(x.mean() < 60 for x in (fr[2, 12:-12], fr[-3, 12:-12], fr[12:-12, 2], fr[12:-12, -3]))
        cross_ok = int(np.argmax(fr[20:-20, 10:-10].mean((0, 2)))) + 10 == w // 2 and \
            int(np.argmax(fr[10:-10, 20:-20].mean((1, 2)))) + 10 == h // 2
        corner = {k: fr[ys, xs].mean((0, 1)) for k, (ys, xs) in (("tl", (slice(3, 7), slice(3, 7))),
                                                                 ("tr", (slice(3, 7), slice(w - 7, w - 3))),
                                                                 ("bl", (slice(h - 7, h - 3), slice(3, 7))),
                                                                 ("br", (slice(h - 7, h - 3), slice(w - 7, w - 3))))}
        corners_ok = all(np.abs(corner[k] - CORNERS[k]).max() < 60 for k in CORNERS)
        magenta = int(((np.abs(fr - MAGENTA) < 60).all(-1)).sum())
        print(f"  {label} frame {i}: mean diff {diff:.1f}, border on the edges {edge_ok}, inside black {inner_ok}, "
              f"cross at the centre {cross_ok}, corners {corners_ok}, magenta pixels {magenta}")
        assert diff < 6 and edge_ok and inner_ok and cross_ok and corners_ok and magenta == 0, label
    return float(info["format"]["duration"]), int(s["nb_read_frames"])


for n, mon in enumerate(cm.rec_monitors()):
    short = mon[0].split(":")[0]
    w, h = 400, 300
    # a spot where the test pattern is really visible: another program's window (e.g. a hardware-accelerated
    # Discord) can cover even a topmost window, so try a few places (monitor-relative, odd offsets on purpose)
    for ax, ay in ((301, 251), (mon[3] - 751, 251), (301, mon[4] - 601), (mon[3] - 751, mon[4] - 601)):
        gx, gy = mon[1] + ax, mon[2] + ay  # the same, on the desktop (real pixels)
        pat = subprocess.Popen([sys.executable, str(HERE / "pattern_window.py"), str(gx), str(gy), str(w), str(h)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert pat.stdout.readline().startswith("ready")
        time.sleep(0.4)
        if (grab(gx, gy, w, h) == pattern(w, h)).all():
            break
        pat.stdin.close()
        pat.wait(10)
    else:
        raise AssertionError(f"{short}: every test spot is covered by another program's window - move it and re-run")
    print(f"{short}: test spot {ax},{ay}")
    pick_monitor(mon[0])
    assert v["mon"].get() == mon[0]

    # 1. drag the area on screen (the see-through layer over that monitor), corner to corner
    app.button("Drag", page, startswith=True).invoke()
    app.pump(0.2)
    layer = next(t for t in app.windows() if float(t.attributes("-alpha")) < 1)
    cv = layer.winfo_children()[0]
    assert real_rect(layer) == (mon[1], mon[2], mon[1] + mon[3], mon[2] + mon[4]), real_rect(layer)
    lx, ly = mon[1], mon[2]  # the layer covers the monitor, in real pixels
    (sx, sy), (ex, ey) = (gx, gy), (gx + w, gy + h)
    cv.event_generate("<ButtonPress-1>", x=sx - lx, y=sy - ly)
    cv.event_generate("<B1-Motion>", x=(sx + ex) // 2 - lx, y=(sy + ey) // 2 - ly)
    cv.event_generate("<B1-Motion>", x=ex - lx, y=ey - ly)
    cv.event_generate("<ButtonRelease-1>", x=ex - lx, y=ey - ly)
    app.pump(0.2)
    got = tuple(int(v[k].get()) for k in "xywh")
    print(f"{short}: dragged {got}, wanted {(ax, ay, w, h)}")
    assert got == (ax, ay, w, h), got

    # 2. typed exactly; the tab says what it records; the outline sits exactly PAD pixels around it
    for k, val in zip("xywh", (ax, ay, w, h)):
        type_in(v[k], val)
    said = records_label()
    assert said and said[0].startswith(f"Records {w} x {h} pixels at {ax},{ay}"), said
    o = outline_real(mon)
    want = (gx - PAD, gy - PAD, gx + w + PAD, gy + h + PAD)
    print(f"{short}: outline {o}, wanted {want}")
    assert max(abs(a - b) for a, b in zip(o, want)) <= 1, (o, want)

    # 3. the outline and the floating button are left out of every capture, even one that covers them
    for win in (st["outline"], st["float"]):
        aff = ctypes.c_uint()
        ctypes.windll.user32.GetWindowDisplayAffinity(int(win.wm_frame(), 16), ctypes.byref(aff))
        assert aff.value == 0x11, aff.value  # WDA_EXCLUDEFROMCAPTURE
    around = grab(gx - 12, gy - 12, w + 24, h + 24)  # the margin around the area, where the outline is drawn
    ring = np.concatenate([around[:12].reshape(-1, 3), around[-12:].reshape(-1, 3),
                           around[:, :12].reshape(-1, 3), around[:, -12:].reshape(-1, 3)])
    outline_px = int((~(ring == MAGENTA).all(-1)).sum())
    print(f"{short}: a capture over the outline sees only the magenta under it (other pixels: {outline_px})")
    assert outline_px == 0, outline_px
    assert (around[12:-12, 12:-12] == pattern(w, h)).all(), "the area itself isn't exactly the pattern"

    # 4. Record / Stop from the floating button; the file is the area, exactly
    fl = st["float"]
    before = set(recs.glob("*.mp4"))
    fl.btn.invoke()
    assert st["proc"] is not None and fl.btn.cget("text").startswith("■")
    app.pump(2.2)
    assert ":" in fl.lbl.cget("text")
    fl.btn.invoke()
    wait_stopped()
    new = sorted(set(recs.glob("*.mp4")) - before)
    assert len(new) == 1 and new[0].name.startswith("Test clip "), new
    assert not app.boxes and not app.errors, (app.boxes, app.errors)
    dur, nfr = check_video(new[0], w, h, short)
    print(f"{short}: saved {new[0].name}, {w}x{h}, {dur:.1f} s, {nfr} frames")
    assert 1.5 < dur < 4 and nfr >= 20, (dur, nfr)
    assert fl.btn.cget("text").startswith("●") and st["out"] == new[0]
    assert any(new[0].name in str(lb.cget("text")) for lb in walk(page) if isinstance(lb, ttk.Label))  # "Saved ..."

    # 5. an odd size records the even size below it, and the outline + the tab say exactly that
    if n == 0:
        type_in(v["w"], w + 1)
        type_in(v["h"], h + 1)
        said = records_label()
        assert said and said[0].startswith(f"Records {w} x {h} pixels"), said
        o = outline_real(mon)
        assert max(abs(a - b) for a, b in zip(o, want)) <= 1, (o, want)
        type_in(v["w"], w)
        type_in(v["h"], h)
    pat.stdin.close()
    pat.wait(10)

# 6. typing while recording doesn't move the outline; a killed recording still plays and is reported;
#    two recordings in the same second don't overwrite each other (the tab's own Record / Stop button this time)
mon = cm.rec_monitors()[0]
pick_monitor(mon[0])
for k, val in zip("xywh", (100, 100, 320, 240)):
    type_in(v[k], val)
rec_b = app.button("Record", page)
rec_b.invoke()
first = st["out"]
app.pump(0.5)
geo = st["outline"].geometry()
type_in(v["x"], 50)
assert st["outline"].geometry() == geo, (geo, st["outline"].geometry())
app.pump(2.8)
st["proc"].kill()  # like a crash / Task Manager
wait_stopped()
assert any("stopped early" in b[2] for b in app.boxes), app.boxes
app.boxes.clear()
played = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                         "stream=nb_read_frames", "-of", "csv=p=0", str(first)], capture_output=True, text=True)
print("killed after 3.3 s, frames that play:", played.stdout.strip())
assert played.stdout.strip().isdigit() and int(played.stdout.strip()) >= 30  # at most ~0.5 s lost (+ ffmpeg's start)
type_in(v["x"], 100)
real_strftime = time.strftime
time.strftime = lambda fmt, *a: first.stem.split(" ", 2)[-1] if "%Y" in fmt else real_strftime(fmt, *a)
try:
    rec_b.invoke()
    second = st["out"]
finally:
    time.strftime = real_strftime
app.pump(1.0)
app.button("Stop", page).invoke()
wait_stopped()
print("same second:", first.name, "|", second.name)
assert second != first and second.name.endswith("(2).mp4") and first.is_file() and second.is_file()

# 7. the window's close button keeps the settings
saved = app.close()
assert saved["recorder"]["w"] == "320" and saved["recorder"]["monitor"] == mon[0] and saved["tab"] == "Screen recorder"
shutil.rmtree(recs, ignore_errors=True)
print("recorder tab ok: exact to the pixel on every monitor, outline never captured")
