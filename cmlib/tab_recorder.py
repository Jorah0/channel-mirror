"""The recorder tab."""
import os
from pathlib import Path
from .core import NO_WINDOW
from .recorder import (
    REC_DEST,
    REC_PEER,
    rec_area,
    rec_command,
    rec_from_app,
    rec_monitors,
    rec_name,
    rec_overlay,
    rec_to_app,
)
from .ui import UI, ui_background


def recorder_tab(page, cfg):
    """The Screen recorder tab: record an area of a monitor (set in pixels, or dragged on screen) to a video file in a
    chosen folder, until Stop. A click-through outline marks the area on screen and a small Record / Stop control
    floats beside it; neither shows up in the video, and everything else on screen stays usable.
    Returns {"save", "stop_now"} for the window's close."""
    import subprocess as sp
    import tempfile
    import time
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    rc = cfg.setdefault("recorder", {})
    mons = rec_monitors()
    labels = [m[0] for m in mons]
    num = lambda label: label.split(":")[0].replace(" (main)", "")  # "Monitor 2", whichever is the main one
    want = rc.get("monitor", "")
    st = {"proc": None, "outline": None, "float": None, "shown": False}
    v = {"mon": tk.StringVar(value=next((l for l in labels if num(l) == num(want)), labels[0])),
         "x": tk.StringVar(value=str(rc.get("x", 0))), "y": tk.StringVar(value=str(rc.get("y", 0))),
         "w": tk.StringVar(value=str(rc.get("w", 1280))), "h": tk.StringVar(value=str(rc.get("h", 720))),
         "fps": tk.StringVar(value=str(rc.get("fps", 30))), "mouse": tk.BooleanVar(value=rc.get("mouse", True)),
         "folder": tk.StringVar(value=rc.get("folder") or str(Path.home() / "Videos" / "Channel Mirror recordings")),
         "name": tk.StringVar(value=rc.get("name", "Recording")),
         "outline": tk.BooleanVar(value=rc.get("outline", True)), "float": tk.BooleanVar(value=rc.get("float", True)),
         "hide": tk.BooleanVar(value=rc.get("hide", False)),
         "dest": tk.StringVar(value=rc.get("dest") or REC_DEST[0]), "to_vts": tk.BooleanVar(value=rc.get("to_vts", False))}
    body = ttk.Frame(page, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Pick a monitor and the part of it to record (type it in pixels, or drag it on screen). The "
                         "outline shows exactly what's recorded; clicks go straight through it, and the outline and "
                         "the floating Record / Stop button never appear in the video.", style="Hint.TLabel",
              wraplength=1000, justify="left").pack(anchor="w", pady=(0, 10))

    # what to record
    wf = ttk.LabelFrame(body, text="1. What to record")
    wf.pack(fill="x")
    r = ttk.Frame(wf)
    r.pack(fill="x")
    ttk.Label(r, text="Monitor").pack(side="left")
    mon_cb = ttk.Combobox(r, textvariable=v["mon"], values=labels, state="readonly", width=44,
                          postcommand=lambda: refresh_monitors())
    mon_cb.pack(side="left", padx=6)
    r2 = ttk.Frame(wf)
    r2.pack(fill="x", pady=(8, 0))
    for key, text in (("x", "X (from the left)"), ("y", "Y (from the top)"), ("w", "Width"), ("h", "Height")):
        f = ttk.Frame(r2)
        f.pack(side="left", padx=(0, 12))
        ttk.Label(f, text=text.upper(), style="Field.TLabel").pack(anchor="w")
        ttk.Spinbox(f, textvariable=v[key], from_=0, to=20000, increment=10, width=8).pack(anchor="w")
    bf = ttk.Frame(r2)
    bf.pack(side="left", anchor="s")
    area_l = ttk.Label(wf, style="Hint.TLabel")
    area_l.pack(anchor="w", pady=(6, 0))
    r3 = ttk.Frame(wf)
    r3.pack(fill="x", pady=(6, 0))
    ttk.Checkbutton(r3, text="Show the outline on screen", variable=v["outline"]).pack(side="left")
    ttk.Checkbutton(r3, text="Floating Record / Stop button beside it", variable=v["float"]).pack(side="left", padx=14)

    # how and where
    hf = ttk.LabelFrame(body, text="2. How, and where it's saved")
    hf.pack(fill="x", pady=(12, 0))
    r4 = ttk.Frame(hf)
    r4.pack(fill="x")
    ttk.Label(r4, text="Frames per second").pack(side="left")
    ttk.Combobox(r4, textvariable=v["fps"], values=("15", "24", "30", "60"), width=5).pack(side="left", padx=6)
    ttk.Checkbutton(r4, text="Show the mouse pointer", variable=v["mouse"]).pack(side="left", padx=14)
    ttk.Checkbutton(r4, text="Minimize Channel Mirror while recording", variable=v["hide"]).pack(side="left")
    r5 = ttk.Frame(hf)
    r5.pack(fill="x", pady=(8, 0))
    ttk.Label(r5, text="Save to folder").pack(side="left")
    ttk.Entry(r5, textvariable=v["folder"], width=60).pack(side="left", padx=6, fill="x", expand=True)
    ttk.Button(r5, text="Browse...", style="Tool.TButton", command=lambda: v["folder"].set(
        filedialog.askdirectory(parent=page, title="Save recordings to", initialdir=v["folder"].get() or None)
        or v["folder"].get())).pack(side="left")
    ttk.Button(r5, text="Open folder", style="Tool.TButton", command=lambda: open_folder()).pack(side="left", padx=6)
    r5b = ttk.Frame(hf)
    r5b.pack(fill="x", pady=(6, 0))
    ttk.Label(r5b, text="Recordings go to").pack(side="left")
    dest_cb = ttk.Combobox(r5b, textvariable=v["dest"], state="readonly", width=38,
                           postcommand=lambda: dest_cb.config(values=dests()))
    dest_cb.pack(side="left", padx=6)
    ttk.Checkbutton(r5b, text="Also put it in the VTube Studio tab (for a hotkey / key)", variable=v["to_vts"]).pack(
        side="left", padx=8)

    def dests():
        """Where a finished recording goes: the folder above, VTube Studio's backgrounds here, or on a linked
        computer (sent there when it's done; placed once accepted there)."""
        return list(REC_DEST) + [REC_PEER + p["name"] for p in st.get("peers", list)()]
    r6 = ttk.Frame(hf)
    r6.pack(fill="x", pady=(8, 0))
    ttk.Label(r6, text="File name").pack(side="left")
    ttk.Entry(r6, textvariable=v["name"], width=24).pack(side="left", padx=6)
    ttk.Label(r6, text="+ the date and time, .mp4", style="Hint.TLabel").pack(side="left")

    # record
    rf = ttk.Frame(body)
    rf.pack(fill="x", pady=(14, 0))
    rec_b = ttk.Button(rf, text="Record", style="Accent.TButton", width=16)
    rec_b.pack(side="left")
    time_l = ttk.Label(rf, font=("Segoe UI", 14, "bold"), width=10)
    time_l.pack(side="left", padx=12)
    status = ttk.Label(rf, style="Status.TLabel", anchor="w", wraplength=760, justify="left")
    status.pack(side="left", fill="x", expand=True)
    lf = ttk.LabelFrame(body, text="Recordings this session (double-click to play)")
    lf.pack(fill="both", expand=True, pady=(12, 0))
    tv = ttk.Treeview(lf, columns=("file", "length", "size", "folder"), show="headings", height=5)
    for c, h, w_ in (("file", "File", 300), ("length", "Length", 80), ("size", "Size", 80), ("folder", "Folder", 400)):
        tv.heading(c, text=h)
        tv.column(c, width=w_, stretch=c in ("file", "folder"))
    tv.pack(fill="both", expand=True)
    tv.bind("<Double-1>", lambda e: tv.focus() and os.startfile(tv.focus()))

    def mon():
        if st["proc"] is not None:  # while recording: the monitor it's recording
            return st["rec_mon"]
        return next((m for m in mons if m[0] == v["mon"].get()), mons[0])

    def refresh_monitors():
        """Monitors plugged in / out or rescaled since: the list again, the same monitor kept by number."""
        if st["proc"] is not None:
            return
        mons[:] = rec_monitors()
        mon_cb.config(values=[m[0] for m in mons])
        if v["mon"].get() not in [m[0] for m in mons]:
            v["mon"].set(next((m[0] for m in mons if num(m[0]) == num(v["mon"].get())), mons[0][0]))

    def area():
        if st["proc"] is not None:  # while recording: the area it's recording, whatever is typed meanwhile
            return st["rec_area"]
        return rec_area(mon(), v["x"].get(), v["y"].get(), v["w"].get(), v["h"].get())

    def app_rect(x, y, w, h):
        """Real desktop pixels -> this app's window geometry string."""
        (ax, ay), (bx, by) = rec_to_app(mon(), x, y), rec_to_app(mon(), x + w, y + h)
        return ax, ay, bx - ax, by - ay

    def place():
        """Show / move / hide the outline and the floating button to match the area and state."""
        try:
            x, y, w, h = area()
            area_l.config(text=f"Records {w} x {h} pixels at {x - mon()[1]},{y - mon()[2]} on {mon()[0].split(':')[0]}"
                               f" (desktop {x},{y}). Sizes are rounded down to even numbers.")
            ok = True
        except ValueError as e:
            area_l.config(text=str(e))
            ok = False
        recording = st["proc"] is not None
        show = ok and (st["shown"] or recording)
        _, mx, my, mw, mh, _ = mon()
        if show and v["outline"].get():
            ol = st["outline"]
            if ol is None or not ol.winfo_exists():
                ol = st["outline"] = tk.Toplevel(page)
                ol.overrideredirect(True)
                ol.attributes("-topmost", True)
                ol.configure(bg="#010203")
                ol.attributes("-transparentcolor", "#010203")
                ol.canvas = tk.Canvas(ol, bg="#010203", highlightthickness=0)
                ol.canvas.pack(fill="both", expand=True)
                if not rec_overlay(ol):
                    status.config(text="Note: this Windows can't leave the outline out of recordings - it sits "
                                       "just outside the area, but the floating button may show if it's inside.")
            pad = 4  # the line sits just outside the recorded pixels (and is left out of the video anyway)
            ox, oy = max(mx, x - pad), max(my, y - pad)
            ow, oh = min(mx + mw, x + w + pad) - ox, min(my + mh, y + h + pad) - oy
            ax, ay, aw, ah = app_rect(ox, oy, ow, oh)
            ol.geometry(f"{aw}x{ah}+{ax}+{ay}")
            ol.canvas.delete("all")
            colour = "#ef4444" if recording else "#f59e0b"
            ol.canvas.create_rectangle(2, 2, aw - 2, ah - 2, outline=colour, width=3)
            ol.deiconify()
        elif st["outline"] is not None and st["outline"].winfo_exists():
            st["outline"].withdraw()
        if show and v["float"].get():
            fl = st["float"]
            if fl is None or not fl.winfo_exists():
                fl = st["float"] = tk.Toplevel(page)
                fl.overrideredirect(True)
                fl.attributes("-topmost", True)
                fl.configure(bg=UI["panel"], highlightbackground=UI["border"], highlightthickness=1)
                fl.btn = tk.Button(fl, command=toggle, font=("Segoe UI", 10, "bold"), relief="flat", padx=10)
                fl.btn.pack(side="left", padx=4, pady=4)
                fl.lbl = tk.Label(fl, bg=UI["panel"], font=("Segoe UI", 10), width=7, cursor="fleur")
                fl.lbl.pack(side="left", padx=(0, 6))
                fl.lbl.bind("<ButtonPress-1>", lambda e: st.update(drag=(e.x_root - fl.winfo_x(), e.y_root - fl.winfo_y())))
                fl.lbl.bind("<B1-Motion>", lambda e: (fl.geometry(f"+{e.x_root - st['drag'][0]}+"
                                                                  f"{e.y_root - st['drag'][1]}"), st.update(moved=True)))
                rec_overlay(fl, clickthrough=False)
                st["moved"] = False
            fl.btn.config(text="■ Stop" if recording else "● Record", bg="#ef4444" if recording else UI["accent"],
                          fg=UI["on_accent"], activebackground="#b91c1c" if recording else UI["accent2"])
            if not st.get("moved"):  # above the area's top-right corner, or inside it when there's no room
                fl.update_idletasks()
                fw, fh = fl.winfo_reqwidth(), fl.winfo_reqheight()
                ax, ay, aw, ah = app_rect(x, y, w, h)
                (mnx, mny) = rec_to_app(mon(), mx, my)
                top = ay - fh - 8 if ay - fh - 8 >= mny else ay + 8
                fl.geometry(f"+{max(mnx, ax + aw - fw)}+{top}")
            fl.deiconify()
        elif st["float"] is not None and st["float"].winfo_exists():
            st["float"].withdraw()

    def drag_area():
        """A see-through layer over the chosen monitor: drag the area to record (Esc cancels)."""
        if st["proc"]:
            return
        m = mon()
        ax, ay, aw, ah = m[5]
        win = tk.Toplevel(page)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.35)
        win.geometry(f"{aw}x{ah}+{ax}+{ay}")
        cv = tk.Canvas(win, bg="#000000", highlightthickness=0, cursor="crosshair")
        cv.pack(fill="both", expand=True)
        cv.create_text(aw // 2, 40, text="Drag the area to record  -  Esc cancels", fill="#ffffff",
                       font=("Segoe UI", 16, "bold"))
        box = {}

        def press(e):
            box["a"] = (e.x, e.y)
            box["r"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#f59e0b", width=3, fill="#ffffff")

        def motion(e):
            if "r" in box:
                cv.coords(box["r"], *box["a"], e.x, e.y)

        def release(e):
            if "a" not in box:
                return
            (x0, y0), (x1, y1) = box["a"], (e.x, e.y)
            win.destroy()
            p0 = rec_from_app(m, ax + min(x0, x1), ay + min(y0, y1))
            p1 = rec_from_app(m, ax + max(x0, x1), ay + max(y0, y1))
            if p1[0] - p0[0] < 16 or p1[1] - p0[1] < 16:
                return status.config(text="That area is too small - drag a bigger one.")
            st["moved"] = False
            v["x"].set(str(p0[0] - m[1]))
            v["y"].set(str(p0[1] - m[2]))
            v["w"].set(str(p1[0] - p0[0]))
            v["h"].set(str(p1[1] - p0[1]))
            status.config(text="Area set. Press Record when you're ready.")
        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", motion)
        cv.bind("<ButtonRelease-1>", release)
        win.bind("<Escape>", lambda e: win.destroy())
        win.focus_force()

    def whole():
        st["moved"] = False
        v["x"].set("0"), v["y"].set("0"), v["w"].set(str(mon()[3])), v["h"].set(str(mon()[4]))
    for text, cmd in (("Drag the area on screen...", drag_area), ("Whole monitor", whole)):
        ttk.Button(bf, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 6))

    def open_folder():
        f = Path(v["folder"].get().strip() or ".")
        if f.is_dir():
            os.startfile(f)
        else:
            status.config(text="That folder doesn't exist yet - it's made when the first recording is saved.")

    def start():
        refresh_monitors()
        try:
            a = area()
            fps = max(1, min(120, int(v["fps"].get())))
        except ValueError as e:
            return messagebox.showerror("Record", str(e) if "pixel" in str(e) or "area" in str(e).lower()
                                        else "Frames per second is a whole number.", parent=page)
        folder = Path(v["folder"].get().strip() or Path.home() / "Videos" / "Channel Mirror recordings")
        route = v["dest"].get()
        if route == REC_DEST[1]:  # straight into VTube Studio's backgrounds (a new name: nothing is overwritten)
            vd = st.get("vts_dir", lambda: None)()
            if not vd or not Path(vd).parent.is_dir():
                return messagebox.showerror("Record", "VTube Studio's folder wasn't found on this PC. Pick it in the "
                                            "Setup tab (VTube Studio), then record again.", parent=page)
            folder = Path(vd)
        elif route.startswith(REC_PEER) and not any(REC_PEER + p["name"] == route for p in st.get("peers", list)()):
            return messagebox.showerror("Record", f"{route[len(REC_PEER):]} isn't linked any more - pick where the "
                                        "recording goes.", parent=page)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return messagebox.showerror("Record", f"Can't use that folder:\n{e}", parent=page)
        out = rec_name(folder, v["name"].get(), time.strftime("%Y-%m-%d %H-%M-%S"))
        n = 2
        while out.exists():  # two started in the same second: keep both
            out = out.with_name(f"{out.stem.rsplit(' (', 1)[0]} ({n}).mp4")
            n += 1
        err = tempfile.TemporaryFile()
        try:
            proc = sp.Popen(rec_command(a, fps, out, v["mouse"].get()), stdin=sp.PIPE, stdout=sp.DEVNULL,
                            stderr=err, creationflags=NO_WINDOW)
        except OSError as e:
            err.close()
            return messagebox.showerror("Record", f"Couldn't start ffmpeg:\n{e}", parent=page)
        st.update(proc=proc, out=out, t0=time.time(), err=err, rec_mon=mon(), rec_area=a, route=route)
        rec_b.config(text="Stop")
        status.config(text=f"Recording {a[2]} x {a[3]} to {out}")
        save()
        place()
        if v["hide"].get():
            page.winfo_toplevel().iconify()
        tick()

    def tick():
        proc = st["proc"]
        if proc is None or st.get("stopping"):  # Stop pressed: the finish comes from stop()
            return
        secs = int(time.time() - st["t0"])
        text = f"{secs // 60}:{secs % 60:02d}"
        time_l.config(text=text, foreground="#ef4444")
        if st["float"] is not None and st["float"].winfo_exists():
            st["float"].lbl.config(text=text)
        if proc.poll() is not None:  # ffmpeg stopped by itself: something went wrong
            finish(proc.returncode or 1)
            return
        page.after(500, tick)

    def stop():
        proc = st["proc"]
        if proc is None:
            return
        st["stopping"] = True
        rec_b.state(["disabled"])
        status.config(text="Finishing the file...")
        try:
            proc.stdin.write(b"q")  # ffmpeg's own key for "stop and finish the file"
            proc.stdin.flush()
        except OSError:
            pass

        def wait():
            try:
                return proc.wait(timeout=20)
            except sp.TimeoutExpired:
                proc.kill()
                return proc.wait()
        ui_background(page, wait, finish)

    def finish(res, failed=None):
        if st["proc"] is None:  # already finished
            return
        out, secs = st["out"], int(time.time() - st["t0"])
        try:
            st["err"].seek(0)
            said = st["err"].read().decode(errors="replace").strip()[-600:]
            st["err"].close()
        except (OSError, ValueError):
            said = ""
        if failed is None and isinstance(res, int) and res != 0:
            failed = said or f"ffmpeg ended with code {res}"
        st.update(proc=None, stopping=False)
        rec_b.state(["!disabled"])
        rec_b.config(text="Record")
        time_l.config(foreground=UI["text"])
        place()
        if v["hide"].get():
            page.winfo_toplevel().deiconify()
        if not out.is_file() or out.stat().st_size == 0:
            status.config(text=f"Recording failed: {failed or said or 'no video was written'}")
            return messagebox.showerror("Record", failed or said or "No video was written.", parent=page)
        if failed:  # cut short, but what was recorded is kept (and plays)
            status.config(text=f"Recording stopped early: {failed}. What was recorded is saved: {out}")
            messagebox.showwarning("Record", f"The recording stopped early:\n{failed}\n\nWhat was recorded is "
                                   f"saved:\n{out}", parent=page)
        mb = out.stat().st_size / 1e6
        tv.insert("", 0, iid=str(out), values=(out.name, f"{secs // 60}:{secs % 60:02d}", f"{mb:.1f} MB", out.parent))
        if not failed:
            status.config(text=f"Saved {out}  ({mb:.1f} MB)")
        done_with(out)

    def done_with(out):
        """A finished recording to where it was meant to go, and to whoever asked for it."""
        route = st.pop("route", "")
        if route.startswith(REC_PEER) and st.get("send_vts"):
            st["send_vts"](route[len(REC_PEER):], out)
            status.config(text=f"Saved {out.name}; sending it to {route[len(REC_PEER):]}'s VTube Studio backgrounds "
                               "(placed there once accepted there).")
        if v["to_vts"].get() and st.get("to_vts_tab"):
            st["to_vts_tab"](out)
        for f in st.pop("then", []):
            f(out)

    def toggle():
        stop() if st["proc"] else start()
    rec_b.config(command=toggle)

    def stop_now():
        """The app is closing: finish the file properly before it goes."""
        proc = st["proc"]
        if proc:
            try:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.wait(timeout=20)
            except (OSError, sp.TimeoutExpired):
                proc.kill()
            st["proc"] = None

    def save():
        rc.update({k: x.get() for k, x in v.items() if k != "mon"}, monitor=v["mon"].get())

    def on_map(shown):
        st["shown"] = shown
        place()
    page.bind("<Map>", lambda e: e.widget is page and on_map(True))
    page.bind("<Unmap>", lambda e: e.widget is page and on_map(False))
    for x in v.values():
        x.trace_add("write", lambda *_: place())
    v["mon"].trace_add("write", lambda *_: st.update(moved=False))
    place()
    return {"save": save, "stop_now": stop_now, "start": start, "stop": stop, "vars": v, "state": st,
            "done_with": done_with, "list": tv}
