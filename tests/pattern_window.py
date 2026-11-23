"""A test target for the screen recorder, drawn in real screen pixels (per-monitor DPI aware: never stretched).

    python pattern_window.py X Y W H [MARGIN]     X, Y, W, H = the area on the desktop, in real pixels

Inside the area: black, a 1-pixel white border on its exact edges, a 1-pixel white cross through (W//2, H//2) and a
coloured 6 x 6 square 2 pixels in from each corner (red top-left, green top-right, blue bottom-left, yellow
bottom-right). Around it, MARGIN pixels of magenta: a recording 1 pixel off shows magenta or a missing border line,
and the recorder's outline (drawn in the margin) shows if it gets into the video. Prints "ready", stays open until
its stdin closes. pattern(W, H) gives the same picture as a numpy array, to compare the video with."""
import sys

import numpy as np

MAGENTA = (255, 0, 255)
CORNERS = {"tl": (255, 0, 0), "tr": (0, 255, 0), "bl": (0, 0, 255), "br": (255, 255, 0)}


def pattern(w, h):
    img = np.zeros((h, w, 3), np.uint8)
    img[0, :] = img[-1, :] = img[:, 0] = img[:, -1] = 255  # the border, on the area's exact edges
    img[h // 2, :] = img[:, w // 2] = 255  # the cross
    for (ys, xs), rgb in zip(((slice(2, 8), slice(2, 8)), (slice(2, 8), slice(w - 8, w - 2)),
                              (slice(h - 8, h - 2), slice(2, 8)), (slice(h - 8, h - 2), slice(w - 8, w - 2))),
                             CORNERS.values()):
        img[ys, xs] = rgb
    return img


if __name__ == "__main__":
    import ctypes
    import threading
    import tkinter as tk
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: real pixels
    x, y, w, h = map(int, sys.argv[1:5])
    m = int(sys.argv[5]) if len(sys.argv) > 5 else 24
    full = np.zeros((h + 2 * m, w + 2 * m, 3), np.uint8)
    full[:, :] = MAGENTA
    full[m:m + h, m:m + w] = pattern(w, h)
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"{w + 2 * m}x{h + 2 * m}+{x - m}+{y - m}")
    ppm = b"P6 %d %d 255\n" % (w + 2 * m, h + 2 * m) + full.tobytes()
    img = tk.PhotoImage(data=ppm, format="PPM")
    tk.Label(root, image=img, bd=0, highlightthickness=0, padx=0, pady=0).place(x=0, y=0)
    root.update()
    print("ready", root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height(), flush=True)
    threading.Thread(target=lambda: (sys.stdin.read(), root.after(0, root.destroy)), daemon=True).start()
    root.mainloop()
