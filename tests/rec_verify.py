"""Full check of the screen recorder's capture box on the real monitors, through the main window's Screen recorder
tab: drag areas (centre, corners, edges, tiny, reversed), typed values, Whole monitor; the outline must sit just
around the recorded area (real pixels, both scalings), the box drawn while dragging must follow the pointer, and the
floating button must stay on the monitor. (drive_recorder.py checks the recording itself to the pixel.)
Read-only: nothing recorded, settings in a temp file (harness)."""
import ctypes
import ctypes.wintypes
from tkinter import ttk

from harness import App, walk

app = App({"recorder": {}})
cm = app.cm
app.start()
page = app.tab("Screen recorder")
rec = app.api("recorder")
v, st = rec["vars"], rec["state"]
PAD, TOL = 4, 3
bad = []


def type_in(var, text):
    e = next(e for e in walk(page) if isinstance(e, ttk.Entry) and not isinstance(e, ttk.Combobox)
             and str(e.cget("textvariable")) == str(var))
    e.delete(0, "end")
    e.insert(0, str(text))
    app.pump(0.05)


def pick_monitor(label):
    cb = next(c for c in walk(page) if isinstance(c, ttk.Combobox) and str(c.cget("textvariable")) == str(v["mon"]))
    cb.set(label)
    cb.event_generate("<<ComboboxSelected>>")
    app.pump(0.2)
    assert v["mon"].get() == label, v["mon"].get()


def real_rect(win):
    """Where Windows really shows a window, in desktop pixels (left, top, right, bottom): asked of Windows itself,
    not worked out through the app's own sums."""
    app.pump(0.05)
    r = ctypes.wintypes.RECT()
    cm.rec_pm(ctypes.windll.user32.GetWindowRect, int(win.wm_frame(), 16), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def outline_real(mon):
    return real_rect(st["outline"])


def check(label, mon, area):
    ax, ay, aw, ah = area
    _, mx, my, mw, mh = mon
    want = (max(mx, ax - PAD), max(my, ay - PAD), min(mx + mw, ax + aw + PAD), min(my + mh, ay + ah + PAD))
    got = outline_real(mon)
    off = max(abs(a - b) for a, b in zip(got, want))
    fl = st["float"]
    fx, fy = real_rect(fl)[:2]
    float_ok = mx - 5 <= fx <= mx + mw and my - 5 <= fy <= my + mh
    ok = off <= TOL and float_ok and bool(st["outline"].winfo_viewable())
    print(f"{'OK ' if ok else 'BAD'} {label:42} area {area}  outline {got}  off {off}px  button on monitor {float_ok}")
    if not ok:
        bad.append(label)


def drag(mon, x0, y0, x1, y1):
    """Press Drag area on screen, then drag on the see-through layer from (x0,y0) to (x1,y1), monitor-relative real
    pixels -> (the box drawn half-way, where the pointer was then)."""
    app.button("Drag", page, startswith=True).invoke()
    app.pump(0.1)
    layer = next(t for t in app.windows() if float(t.attributes("-alpha")) < 1)
    cv = layer.winfo_children()[0]
    lx, ly = mon[1], mon[2]  # the layer covers the monitor, in real pixels
    pts = [(mon[1] + x, mon[2] + y) for x, y in ((x0, y0), ((x0 + x1) // 2, (y0 + y1) // 2),
                                                                  (x1, y1))]
    cv.event_generate("<ButtonPress-1>", x=pts[0][0] - lx, y=pts[0][1] - ly)
    cv.event_generate("<B1-Motion>", x=pts[1][0] - lx, y=pts[1][1] - ly)
    app.pump()
    live = cv.coords(cv.find_all()[-1])
    cv.event_generate("<B1-Motion>", x=pts[2][0] - lx, y=pts[2][1] - ly)
    cv.event_generate("<ButtonRelease-1>", x=pts[2][0] - lx, y=pts[2][1] - ly)
    app.pump(0.1)
    assert not any(float(t.attributes("-alpha")) < 1 for t in app.windows()), "the drag layer stayed open"
    (ax, ay), (bx, by) = (pts[0][0] - lx, pts[0][1] - ly), (pts[1][0] - lx, pts[1][1] - ly)
    return live, (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))  # a canvas keeps a box's corners in order


for mon in cm.rec_monitors():
    pick_monitor(mon[0])
    mw, mh = mon[3], mon[4]
    short = mon[0].split(":")[0]
    cases = [("centre", (mw // 3, mh // 3, 2 * mw // 3, 2 * mh // 3)),
             ("top-left corner", (0, 0, 400, 300)), ("bottom-right corner", (mw - 400, mh - 300, mw, mh)),
             ("top edge strip", (200, 0, mw - 200, 120)), ("right edge strip", (mw - 150, 100, mw, mh - 100)),
             ("tiny box", (500, 500, 540, 530)), ("dragged up-left (reversed)", (900, 700, 300, 200))]
    for name, (x0, y0, x1, y1) in cases:
        live, expect = drag(mon, x0, y0, x1, y1)
        if not all(abs(a - b) <= 2 for a, b in zip(live, expect)):
            bad.append(f"{short} {name}: the box drawn while dragging didn't follow the pointer {live} vs {expect}")
        area = cm.rec_area(mon, v["x"].get(), v["y"].get(), v["w"].get(), v["h"].get())
        if abs(area[0] - (mon[1] + min(x0, x1))) > 2 or abs(area[1] - (mon[2] + min(y0, y1))) > 2:
            bad.append(f"{short} {name}: area {area} doesn't start where it was drawn ({min(x0, x1)},{min(y0, y1)})")
        check(f"{short} drag {name}", mon, area)
    for vals, name in (((100, 150, 641, 361), "typed values"), ((0, 0, 0, 0), "typed 0x0 = whole monitor")):
        for k_, val in zip("xywh", vals):
            type_in(v[k_], val)
        check(f"{short} {name}", mon, cm.rec_area(mon, *vals))
    app.button("Whole monitor", page).invoke()
    app.pump(0.05)
    check(f"{short} Whole monitor button", mon, cm.rec_area(mon, 0, 0, 0, 0))
app.close()
print("\nRESULT:", "every check passed" if not bad else f"{len(bad)} problem(s):\n  " + "\n  ".join(bad))
assert not bad, bad
print("recorder outline on every monitor ok")
