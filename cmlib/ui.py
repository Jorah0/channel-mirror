"""UI toolkit: theme, tooltips, menus, key grid, cell editing, sound forms (stdlib tkinter only)."""
import weakref
from pathlib import Path
from .core import AUDIO_EXT
from .mirror import media_files, natural
from .deck import SD_FADES, SD_LEVELS, SD_MODES, SD_OBS_DEFAULT, sd_output_choices, sd_set_levels
from .setup import ui_mode


# --- UI toolkit: theme, tooltips, menus, key grid, cell editing, dialogs (stdlib tkinter only) ---
UI_LIGHT = {"mode": "light", "bg": "#f3f4f6", "panel": "#ffffff", "border": "#d1d5db", "text": "#1f2937",
            "muted": "#6b7280", "dis": "#9ca3af", "accent": "#2563eb", "accent2": "#1d4ed8", "on_accent": "#ffffff",
            "accent_off": "#9db7f0", "accent_off_fg": "#eef2ff", "sound": "#d1fae5", "missing": "#fee2e2",
            "other": "#e5e7eb", "auto": "#e0e7ff", "empty": "#ffffff", "button": "#e8ebf0", "hover": "#dde2e9",
            "press": "#cfd5dd", "tab": "#e6e9ee", "head": "#eef0f3", "bad": "#b91c1c", "warn": "#b45309",
            "good": "#047857", "tip": "#111827", "tip_fg": "#f9fafb",
            "remote": "#6d28d9"}


UI_DARK = {"mode": "dark", "bg": "#1c1e23", "panel": "#25282e", "border": "#3d424b", "text": "#e7e9ec",
           "muted": "#a0a8b3", "dis": "#6b7280", "accent": "#2563eb", "accent2": "#3b7af5", "on_accent": "#ffffff",
           "accent_off": "#2b467e", "accent_off_fg": "#9fb3d9", "sound": "#1e4a39", "missing": "#5a2429",
           "other": "#353a42", "auto": "#2f3768", "empty": "#25282e", "button": "#30343b", "hover": "#3a3f48",
           "press": "#464c57", "tab": "#22252b", "head": "#2c3037", "bad": "#f87171", "warn": "#fbbf24",
           "good": "#34d399", "tip": "#33373f", "tip_fg": "#f3f4f6",
           "remote": "#7c3aed"}


UI = {**UI_LIGHT, "font": ("Segoe UI", 10), "small": ("Segoe UI", 8)}  # the palette in use; ui_switch swaps it


# for a live switch: which widget options hold a background or a text colour, and the palette keys for each
UI_RECOLOUR = {("-background", "-highlightbackground", "-highlightcolor", "-activebackground", "-selectbackground",
                "-troughcolor", "-selectcolor", "-disabledbackground", "-readonlybackground"):
               ("bg", "panel", "border", "accent", "accent2", "sound", "missing", "other", "auto", "empty", "button",
                "hover", "press", "tab", "head", "tip"),
               ("-foreground", "-insertbackground", "-activeforeground", "-disabledforeground", "-selectforeground"):
               ("text", "muted", "dis", "bad", "warn", "good", "tip_fg")}


UI_SWATCH = {"relief": "flat", "bd": 0, "highlightthickness": 1}  # colour boxes: a thin border in the palette's colour


def ui_palette(choice):
    """Put the Light or Dark palette for this Appearance choice into UI (before ui_theme)."""
    UI.update(UI_DARK if ui_mode(choice) == "dark" else UI_LIGHT)


def ui_titlebar(win, redraw=False):
    """Windows title bar to match the palette (dark in dark mode; Windows 10 20H1+ / 11, ignored elsewhere)."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if not hwnd:
            return
        on = ctypes.c_int(UI["mode"] == "dark")
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
        if redraw:  # repaint the frame now (no move / size / z-order / focus change)
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x37)
    except Exception:
        pass


def ui_theme(root):
    """Style every widget from UI (the Light or Dark palette): ttk styles plus matching defaults for the classic tk
    widgets. Running it again restyles every ttk widget on screen (ui_switch does the classic ones)."""
    from tkinter import font as tkfont
    from tkinter import ttk
    c = UI
    root.configure(bg=c["bg"])
    for pat, val in (("*Background", c["bg"]), ("*Foreground", c["text"]), ("*Font", "{Segoe UI} 10"),
                     ("*insertBackground", c["text"]), ("*selectBackground", c["accent"]),
                     ("*selectForeground", c["on_accent"]), ("*activeBackground", c["hover"]),
                     ("*activeForeground", c["text"]), ("*highlightBackground", c["bg"]),
                     ("*highlightColor", c["accent"]), ("*Label.highlightBackground", c["border"]),
                     ("*Listbox.background", c["panel"]),
                     ("*Text.background", c["panel"]), ("*Checkbutton.selectColor", c["panel"]),
                     ("*Button.background", c["button"]), ("*Button.relief", "flat"),
                     ("*Scale.highlightThickness", 0), ("*Scale.troughColor", c["border"]),
                     ("*Scale.sliderRelief", "flat"), ("*Scale.borderWidth", 0), ("*Scale.activeBackground", c["accent"]),
                     ("*TCombobox*Listbox.background", c["panel"]), ("*TCombobox*Listbox.foreground", c["text"]),
                     ("*TCombobox*Listbox.font", "{Segoe UI} 10"), ("*Menu.background", c["panel"]),
                     ("*Menu.foreground", c["text"]), ("*Menu.activeBackground", c["accent"]),
                     ("*Menu.activeForeground", c["on_accent"]), ("*Menu.relief", "flat")):
        root.option_add(pat, val)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=c["bg"], foreground=c["text"], font=c["font"], bordercolor=c["border"],
                lightcolor=c["bg"], darkcolor=c["bg"], troughcolor=c["border"], focuscolor=c["accent"],
                selectbackground=c["accent"], selectforeground=c["on_accent"], fieldbackground=c["panel"],
                insertcolor=c["text"], arrowcolor=c["text"])
    s.map(".", foreground=[("disabled", c["dis"])])

    def flat(base, pressed, active, disabled):  # one colour per state, no 3D bevel
        return ({k: [("pressed", pressed), ("active", active), ("disabled", disabled)]
                 for k in ("background", "lightcolor", "darkcolor")},
                {"background": base, "lightcolor": base, "darkcolor": base})
    maps, conf = flat(c["button"], c["press"], c["hover"], c["bg"])
    s.configure("TButton", padding=(10, 4), **conf)
    s.map("TButton", bordercolor=[("focus", c["accent"])], **maps)
    maps, conf = flat(c["accent"], c["accent2"], c["accent2"], c["accent_off"])
    s.configure("Accent.TButton", foreground=c["on_accent"], bordercolor=c["accent"], font=("Segoe UI", 10, "bold"),
                padding=(16, 6), **conf)
    s.map("Accent.TButton", foreground=[("disabled", c["accent_off_fg"])],
          bordercolor=[("disabled", c["accent_off"]), ("focus", c["accent2"])], **maps)
    s.configure("Tool.TButton", padding=(8, 2), width=0)
    s.configure("Toolbutton", padding=(12, 7), anchor="w", background=c["bg"], lightcolor=c["bg"], darkcolor=c["bg"],
                bordercolor=c["bg"])
    s.map("Toolbutton", **{k: [("selected", c["accent"]), ("active", c["hover"])]
                           for k in ("background", "lightcolor", "darkcolor", "bordercolor")},
          foreground=[("selected", c["on_accent"])])
    s.configure("TLabelframe", background=c["bg"], bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"],
                relief="solid", padding=10)
    s.configure("TLabelframe.Label", background=c["bg"], foreground=c["text"], font=("Segoe UI Semibold", 10))
    s.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(10, 6, 10, 0), bordercolor=c["border"],
                lightcolor=c["bg"], darkcolor=c["bg"])
    s.configure("TNotebook.Tab", padding=(10, 7), background=c["tab"], foreground=c["muted"], bordercolor=c["border"],
                lightcolor=c["tab"], darkcolor=c["tab"])
    s.map("TNotebook.Tab", background=[("selected", c["bg"]), ("active", c["hover"])],
          lightcolor=[("selected", c["bg"]), ("active", c["hover"])], foreground=[("selected", c["text"])],
          expand=[("selected", (1, 1, 1, 0))])
    line = tkfont.Font(root=root, family="Segoe UI", size=10).metrics("linespace")  # scales with Windows DPI
    s.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["text"],
                rowheight=line + 8, bordercolor=c["border"], lightcolor=c["panel"], darkcolor=c["panel"])
    s.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", c["on_accent"])])
    s.configure("Treeview.Heading", background=c["head"], foreground=c["text"], font=("Segoe UI", 9, "bold"),
                padding=(6, 4), relief="flat", bordercolor=c["border"], lightcolor=c["head"], darkcolor=c["head"])
    s.map("Treeview.Heading", **{k: [("active", c["hover"])] for k in ("background", "lightcolor", "darkcolor")})
    for w in ("TCheckbutton", "TRadiobutton"):
        s.configure(w, indicatorbackground=c["panel"], indicatorforeground=c["accent"], indicatormargin=(0, 0, 6, 0),
                    upperbordercolor=c["border"], lowerbordercolor=c["border"])
        s.map(w, background=[("disabled", c["bg"]), ("active", c["bg"])],
              indicatorbackground=[("disabled", c["bg"]), ("pressed", c["border"])],
              upperbordercolor=[("active", c["accent"])], lowerbordercolor=[("active", c["accent"])])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(w, fieldbackground=c["panel"], foreground=c["text"], padding=3, bordercolor=c["border"],
                    lightcolor=c["panel"], darkcolor=c["panel"], insertcolor=c["text"])
        s.map(w, bordercolor=[("focus", c["accent"]), ("hover", c["muted"])], lightcolor=[("focus", c["accent"])],
              fieldbackground=[("readonly", c["bg"] if w == "TEntry" else c["panel"]), ("disabled", c["bg"])])
    for w in ("TCombobox", "TSpinbox"):
        s.configure(w, background=c["button"], arrowcolor=c["text"])
    s.map("TCombobox", background=[("active", c["hover"])], selectbackground=[("readonly", c["panel"])],
          selectforeground=[("readonly", c["text"])])
    s.configure("TScrollbar", background=c["button"], troughcolor=c["bg"], bordercolor=c["bg"],
                lightcolor=c["button"], darkcolor=c["button"], arrowcolor=c["muted"], gripcount=0)
    s.map("TScrollbar", **{k: [("active", c["hover"])] for k in ("background", "lightcolor", "darkcolor")})
    s.configure("TScale", background=c["button"], troughcolor=c["border"], bordercolor=c["border"],
                lightcolor=c["button"], darkcolor=c["button"])
    s.map("TScale", background=[("active", c["hover"])])
    s.configure("TSeparator", background=c["border"])
    s.configure("Hint.TLabel", foreground=c["muted"], font=("Segoe UI", 9))
    s.configure("Field.TLabel", foreground=c["muted"], font=("Segoe UI", 8, "bold"))
    s.configure("Status.TLabel", padding=(2, 4))
    s.configure("Good.TLabel", foreground=c["good"], font=("Segoe UI", 9, "bold"))
    s.configure("Bad.TLabel", foreground=c["bad"], font=("Segoe UI", 9, "bold"))
    s.configure("Name.TLabel", font=("Segoe UI Semibold", 10))
    s.configure("Remote.TLabel", background=c["remote"], foreground="#ffffff", font=("Segoe UI", 10, "bold"),
                padding=(8, 4))  # working on a linked computer: unmistakable, in both themes
    s.configure("Local.TLabel", background=c["head"], foreground=c["text"], font=("Segoe UI", 9, "bold"),
                padding=(6, 3))
    s.configure("Header.TFrame", background=c["panel"])
    s.configure("Header.TLabel", background=c["panel"])
    s.configure("HeadTitle.TLabel", background=c["panel"], foreground=c["text"], font=("Segoe UI", 15, "bold"))
    s.configure("HeadSub.TLabel", background=c["panel"], foreground=c["muted"])
    root.bind_class("Tk", "<Map>", lambda e: ui_titlebar(e.widget))  # each window gets its title bar when shown
    root.bind_class("Toplevel", "<Map>", lambda e: ui_titlebar(e.widget))


def ui_recolour(root, old, new):
    """Classic tk widgets keep the colours they were made with: swap each one that came from the old palette for the
    new palette's colour (ttk widgets follow their styles). Returns the windows (paths) found on the way."""
    tk, maps = root.tk, {}
    for opts, keys in UI_RECOLOUR.items():
        m = {}
        for k in keys:  # the first key wins when two share a colour (panel before empty)
            m.setdefault(old[k].lower(), new[k])
        maps.update(dict.fromkeys(opts, m))
    todo, wins = [str(root)], []
    while todo:
        w = todo.pop()
        try:
            todo += tk.splitlist(tk.call("winfo", "children", w))
            cls = tk.call("winfo", "class", w)
            if cls in ("Tk", "Toplevel"):
                wins.append(w)
            for o in tk.splitlist(tk.call(w, "configure")):
                o = tk.splitlist(o)
                m = maps.get(str(o[0]))
                if m and len(o) == 5 and str(o[4]).lower() in m:
                    tk.call(w, "configure", o[0], m[str(o[4]).lower()])
            if cls == "Treeview":  # row colours (e.g. pages with missing sounds)
                for tag in tk.splitlist(tk.call(w, "tag", "names")):
                    for opt in ("-foreground", "-background"):
                        val = str(tk.call(w, "tag", "configure", tag, opt)).lower()
                        if val in maps[opt]:
                            tk.call(w, "tag", "configure", tag, opt, maps[opt][val])
        except Exception:  # a widget closing meanwhile
            continue
    return wins


def ui_switch(root, choice):
    """Light / Dark / Follow Windows while the app is open: the new palette into UI, every ttk style again, classic
    widgets recoloured, the key grids redrawn (their tiles take colours from UI when drawn), title bars matched."""
    old = dict(UI)
    ui_palette(choice)
    ui_theme(root)
    wins = ui_recolour(root, old, UI)
    for g in list(DeckGrid.shown):
        try:
            if g.size and g.frame.winfo_exists():
                g.draw(*g.size)
        except Exception:
            pass
    for w in wins:
        try:
            ui_titlebar(root.nametowidget(w), redraw=True)
        except Exception:
            pass


class Tip:
    """Hover help for a widget; text may be a function so it can describe the widget's current state."""

    def __init__(self, widget, text):
        self.w, self.text, self.win, self.job = widget, text, None, None
        widget.bind("<Enter>", lambda e: self.later(), add="+")
        widget.bind("<Leave>", lambda e: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda e: self.hide(), add="+")

    def later(self):
        self.hide()
        self.job = self.w.after(500, self.show)

    def show(self):
        import tkinter as tk
        text = self.text() if callable(self.text) else self.text
        if not text or not self.w.winfo_exists():
            return
        self.win = tk.Toplevel(self.w)
        self.win.wm_overrideredirect(True)
        self.win.wm_geometry(f"+{self.w.winfo_rootx() + 12}+{self.w.winfo_rooty() + self.w.winfo_height() + 4}")
        tk.Label(self.win, text=text, justify="left", bg=UI["tip"], fg=UI["tip_fg"], font=("Segoe UI", 9),
                 padx=8, pady=5, wraplength=420, highlightthickness=1, highlightbackground=UI["border"]).pack()

    def hide(self):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.win:
            self.win.destroy()
            self.win = None


def ui_menu(widget, event, items):
    """Right-click menu. items: (label, command) pairs, None = separator, command None = greyed out."""
    import tkinter as tk
    m = tk.Menu(widget, tearoff=0)
    for it in items:
        if it is None:
            m.add_separator()
        else:
            m.add_command(label=it[0], command=it[1] or (lambda: None), state="normal" if it[1] else "disabled")
    try:
        m.tk_popup(event.x_root, event.y_root)
    finally:
        m.grab_release()


def ui_background(widget, work, finish):
    """Run work() on a worker thread and hand its result (or the exception it raised) to finish() back on the
    UI thread, so the window keeps responding during slow jobs like restarting Stream Deck."""
    import queue
    import threading
    q = queue.Queue()

    def run():
        try:
            q.put(work())
        except Exception as e:
            q.put(e)
    threading.Thread(target=run, daemon=True).start()

    def poll():
        try:
            res = q.get_nowait()
        except queue.Empty:
            return widget.after(100, poll)
        finish(res)
    widget.after(100, poll)


def ui_multi_rows(tree, on_double, on_drop=None):
    """Treeview clicks that keep a multi-selection: pressing on a row that's already selected (several are) leaves
    the selection alone, so the rows can be dragged together (on_drop(event) on release) or all edited with a
    double-click (on_double(event)). A plain single click still narrows to that row, once it's clearly not
    the first half of a double-click."""
    st = {}

    def press(e):
        it = tree.identify_row(e.y)
        if st.get("job"):
            tree.after_cancel(st.pop("job"))
        st.update(x=e.x_root, y=e.y_root, item=it, moved=False, keep=False)
        if it and it in tree.selection() and len(tree.selection()) > 1 and not e.state & 0x0005:
            st["keep"] = True
            return "break"

    def motion(e):
        if on_drop and st.get("item") and abs(e.x_root - st["x"]) + abs(e.y_root - st["y"]) > 8:
            st["moved"] = True
            tree.config(cursor="fleur")

    def release(e):
        tree.config(cursor="")
        if st.get("moved"):
            st["moved"] = False
            on_drop(e)
        elif st.get("keep") and st.get("item"):
            st["job"] = tree.after(350, lambda it=st["item"]: tree.exists(it) and tree.selection_set(it))

    def double(e):
        if st.get("job"):
            tree.after_cancel(st.pop("job"))
        on_double(e)
        return "break"  # stop the class binding from narrowing the selection on the second press
    tree.bind("<ButtonPress-1>", press)
    tree.bind("<B1-Motion>", motion)
    tree.bind("<ButtonRelease-1>", release)
    tree.bind("<Double-Button-1>", double)


def ui_busy_focus(widget):
    """True while the user is typing somewhere (keyboard shortcuts then leave the keys alone)."""
    try:
        cls = widget.tk.call("winfo", "class", widget.tk.call("focus"))
    except Exception:
        return False
    return cls in ("Entry", "TEntry", "Text", "TCombobox", "TSpinbox", "Spinbox")


def ui_keys(page, bindings):
    """Keyboard shortcuts that only act while this tab is showing and nobody is typing."""
    top = page.winfo_toplevel()
    for seq, fn in bindings.items():
        def handler(e, fn=fn):
            if page.winfo_ismapped() and not ui_busy_focus(page):
                fn()
                return "break"
        for s in {seq, seq[:-2] + seq[-2].upper() + ">"} if seq.startswith("<Control-") else {seq}:
            top.bind(s, handler, add="+")


class DeckGrid:
    """A Stream Deck key grid of flat tiles. tile(pos) -> (text, bg, fg) with pos = "col,row" counted from 0.
    Click / double-click / right-click call back with (pos, event); dragging one key onto another calls
    on_drop(src, dst); tip(pos) gives hover text; key_at() lets other widgets drop things onto keys."""
    shown = weakref.WeakSet()  # every grid, so a Light / Dark switch can redraw them

    def __init__(self, parent, tile, on_click=None, on_double=None, on_menu=None, on_drop=None, tip=None):
        import tkinter as tk
        DeckGrid.shown.add(self)
        self.frame = tk.Frame(parent, bg=UI["bg"])
        self.tile, self.on_click, self.on_double, self.on_menu, self.on_drop, self.tip = (
            tile, on_click, on_double, on_menu, on_drop, tip)
        self.tiles, self.size, self.drag = {}, None, {}

    def draw(self, cols, rows):
        import tkinter as tk
        if self.size != (cols, rows):  # tiles are kept between draws so double-clicks register
            for w in self.frame.winfo_children():
                w.destroy()
            self.tiles, self.size = {}, (cols, rows)
            for r in range(rows):
                for c in range(cols):
                    pos = f"{c},{r}"
                    w = tk.Label(self.frame, width=12, height=3, font=UI["small"], wraplength=96, justify="center",
                                 bd=0, highlightthickness=2, cursor="hand2")
                    w.grid(row=r, column=c, padx=3, pady=3)
                    w.bind("<ButtonPress-1>", lambda e, p=pos: self.drag.update(src=p, x=e.x_root, y=e.y_root))
                    w.bind("<B1-Motion>", self._motion)
                    w.bind("<ButtonRelease-1>", lambda e, p=pos: self._release(e, p))
                    w.bind("<Double-Button-1>", lambda e, p=pos: (self.drag.update(double=True),  # its release isn't a click
                                                                   self.on_double and self.on_double(p, e)))
                    w.bind("<Button-3>", lambda e, p=pos: self.on_menu and self.on_menu(p, e))
                    if self.tip:
                        Tip(w, lambda p=pos: self.tip(p))
                    self.tiles[pos] = w
        for pos, w in self.tiles.items():
            text, bg, fg = self.tile(pos)
            w.config(text=text, bg=bg, fg=fg,
                     highlightbackground=UI["accent2"] if bg == UI["accent"] else UI["border"])

    def _motion(self, e):
        d = self.drag
        if d and not d.get("moved") and abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) > 8:
            d["moved"] = True
            self.tiles[d["src"]].config(cursor="fleur")

    def _release(self, e, pos):
        d, self.drag = self.drag, {}
        if d.get("double"):  # the release ending a double-click would otherwise unselect the key just opened
            return
        if d.get("moved"):
            self.tiles[d["src"]].config(cursor="hand2")
            dst = self.key_at(e.x_root, e.y_root)
            if dst and dst != d["src"] and self.on_drop:
                self.on_drop(d["src"], dst)
        elif self.on_click:
            self.on_click(pos, e)

    def key_at(self, x, y):
        w = self.frame.winfo_containing(x, y)
        return next((p for p, t in self.tiles.items() if t is w), None)


def ui_cell_edit(tree, item, col, value, done, values=None, editable=False):
    """Edit one Treeview cell in place: an entry (or a dropdown when values are given) over the cell.
    Enter / picking a value / clicking away keeps it, Esc cancels; done(text) receives the new value."""
    import tkinter as tk
    from tkinter import ttk
    box = tree.bbox(item, col)
    if not box:
        return
    var = tk.StringVar(value=value)
    ed = (ttk.Combobox(tree, textvariable=var, values=values, state="normal" if editable else "readonly")
          if values is not None else ttk.Entry(tree, textvariable=var))
    ed.place(x=box[0], y=box[1], width=max(box[2], 120), height=box[3])
    ed.focus_set()
    if values is None:
        ed.select_range(0, "end")
    over = []

    def finish(keep):
        if not over:
            over.append(1)
            val = var.get()
            ed.destroy()
            if keep and val != value:
                done(val)

    def away(_):  # the dropdown list is a child of the combobox: moving focus there isn't "clicking away"
        ed.after(80, lambda: ed.winfo_exists() and not str(ed.tk.call("focus")).startswith(str(ed)) and finish(True))
    # "break": the key is the cell's own - it must not also reach the window's Enter / Esc shortcuts (Edit selected)
    ed.bind("<Return>", lambda e: (finish(True), "break")[1])
    ed.bind("<Escape>", lambda e: (finish(False), "break")[1])
    ed.bind("<FocusOut>", away)
    if values is not None and not editable:
        ed.bind("<<ComboboxSelected>>", lambda e: finish(True))
        ed.after(10, lambda: ed.tk.call("ttk::combobox::Post", ed))


def ui_volume(parent, var, length=150):
    """0-100 slider with the number beside it."""
    from tkinter import ttk
    f = ttk.Frame(parent)
    ttk.Scale(f, from_=0, to=100, variable=var, length=length,
              command=lambda x: var.set(round(float(x)))).pack(side="left")
    ttk.Label(f, textvariable=var, width=4, anchor="e").pack(side="left")
    return f


def ui_sound_form(parent, v):
    """Action / fade / fade length / volume / output fields (labels above) bound to the tk variables in v."""
    from tkinter import ttk
    f = ttk.Frame(parent)
    out = ttk.Combobox(f, textvariable=v["output"], width=34)
    out.config(postcommand=lambda: out.config(values=sd_output_choices()))
    fields = (("ACTION", ttk.Combobox(f, textvariable=v["mode"], values=SD_MODES, state="readonly", width=15)),
              ("FADE", ttk.Combobox(f, textvariable=v["fade"], values=SD_FADES, state="readonly", width=14)),
              ("FADE LENGTH (S)", ttk.Combobox(f, textvariable=v["fade_len"], values=("1", "2", "3", "4", "5"),
                                               state="readonly", width=5)),
              ("VOLUME", ui_volume(f, v["volume"])),
              ("OUTPUT DEVICE", out))
    for i, (label, w) in enumerate(fields):
        ttk.Label(f, text=label, style="Field.TLabel").grid(row=0, column=i, sticky="w", padx=(0, 14))
        w.grid(row=1, column=i, sticky="sw", padx=(0, 14))
    Tip(out, "Shown by name like in Stream Deck; saved as the device id Stream Deck uses.")
    return f


def ui_play_choice(parent, mode):
    """The two everyday ways a sound key plays, as plain choices bound to the Action variable (the Action list keeps
    the other Stream Deck modes)."""
    from tkinter import ttk
    f = ttk.Frame(parent)
    ttk.Label(f, text="EACH SOUND", style="Field.TLabel").pack(side="left", padx=(0, 10))
    for text, m in (("Play once (press again to stop)", "Play / Stop"),
                    ("Loop (repeats until pressed again)", "Loop / Stop")):
        ttk.Radiobutton(f, text=text, variable=mode, value=m).pack(side="left", padx=(0, 14))
    return f


def ui_obs_levels(parent, cfg):
    """Let the user set their own OBS level per kind of sound (saved in cfg["obs_levels"]). True when changed."""
    import tkinter as tk
    from tkinter import messagebox, ttk
    win = tk.Toplevel(parent)
    win.title("My OBS levels")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="How loud each kind of sound should sit in your OBS mix: its average level in dB while it "
                         "plays (0 = full scale, so lower = quieter).\nTo match your mic: talk normally and watch "
                         "your mic in OBS's mixer. The defaults assume it peaks around -10 dB, which averages about "
                         "-16 dB.", style="Hint.TLabel", wraplength=460, justify="left").pack(anchor="w")
    vals = {kind: tk.StringVar(value=f"{SD_LEVELS[kind]:g}") for kind in SD_OBS_DEFAULT}
    grid = ttk.Frame(body)
    grid.pack(anchor="w", pady=12)
    for i, (kind, label) in enumerate((("voice", "Voice lines (as loud as your mic)"),
                                       ("effect", "Alerts and sound effects"),
                                       ("music / ambience", "Music beds and ambience (under your voice)"))):
        ttk.Label(grid, text=label).grid(row=i, column=0, sticky="w", pady=3)
        ttk.Spinbox(grid, textvariable=vals[kind], from_=-60, to=0, increment=1, width=6).grid(row=i, column=1, padx=8)
        ttk.Label(grid, text=f"dB   (default {SD_OBS_DEFAULT[kind]:g})", style="Hint.TLabel").grid(row=i, column=2,
                                                                                            sticky="w")
    res = [False]

    def ok():
        try:
            new = {kind: float(v.get()) for kind, v in vals.items()}
            assert all(-60 <= x <= 0 for x in new.values())
        except (ValueError, AssertionError):
            return messagebox.showerror("My OBS levels", "Each level is a number from -60 to 0 dB.", parent=win)
        res[0] = new != SD_LEVELS
        cfg["obs_levels"] = sd_set_levels(new)
        win.destroy()
    bar = ttk.Frame(body)
    bar.pack(fill="x")
    ttk.Button(bar, text="Reset to defaults", command=lambda: [vals[kd].set(f"{d:g}") for kd, d in
                                                                SD_OBS_DEFAULT.items()]).pack(side="left")
    ttk.Button(bar, text="OK", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.grab_set()
    win.wait_window()
    return res[0]


def sd_levels_text():
    return "  /  ".join(f"{k} {v:g} dB" for k, v in SD_LEVELS.items())


def ui_level_report(parent, rows, names, preset):
    """List each sound's measured level against its target (rows from sd_level_rows; names: {id(sound): key name}).
    Returns True when the user presses Tune to apply the listed changes."""
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(parent)
    win.title("Sound levels")
    win.transient(parent.winfo_toplevel())
    win.configure(bg=UI["bg"])
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    fix = sum(r["new"] is not None for r in rows)
    ok = sum(r["verdict"] == "in range" for r in rows)
    ttk.Label(body, text=f"{len(rows)} sound(s) checked against {preset}: {ok} in range, {fix} to change, "
                         f"{len(rows) - ok - fix} that can't be fixed with volume (too quiet at full, missing or "
                         "silent). Levels are dB, loudest channel, silence left out.",
              style="Hint.TLabel", wraplength=900).pack(anchor="w", pady=(0, 8))
    cols = ("key", "file", "kind", "level", "now", "target", "result")
    tv = ttk.Treeview(body, columns=cols, show="headings", height=min(max(len(rows), 4), 18))
    for c, h, w in zip(cols, ("Key", "File", "Detected as", "File level", "Plays at now", "Target", "Result"),
                       (110, 220, 110, 70, 80, 60, 260)):
        tv.heading(c, text=h)
        tv.column(c, width=w, stretch=c in ("file", "result"))
    f = lambda v: "" if v is None else f"{v:.1f}"
    rank = lambda r: (0 if r["new"] is not None else 1 if r["now"] is not None and r["verdict"] != "in range"
                      else 2 if r["now"] is None else 3)  # changes, can't-fix, missing/silent, fine
    for r in sorted(rows, key=rank):
        se = r["s"].get("Settings", {})
        tv.insert("", "end", values=(names.get(id(r["s"]), ""), Path(se.get("path", "")).name, r["kind"],
                                     f(r["level"]), f(r["now"]), f(r["target"]), r["verdict"]))
    tv.pack(fill="both", expand=True)
    res = [False]
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(12, 0))
    go = ttk.Button(bar, text=f"Tune {fix} sound(s)", style="Accent.TButton",
                    command=lambda: (res.__setitem__(0, True), win.destroy()))
    go.pack(side="right")
    if not fix:
        go.state(["disabled"])
    ttk.Button(bar, text="Close", command=win.destroy).pack(side="right", padx=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.grab_set()
    win.wait_window()
    return res[0]


def ui_pick_sounds(parent, title, folder=False, initialdir=None):
    """Sound files the user picks, in name order (track2 before track10): several files, or with folder=True every
    sound in one folder."""
    from tkinter import filedialog
    if folder:
        f = filedialog.askdirectory(parent=parent, title=title, initialdir=initialdir)
        return [q for q in media_files([f]) if q.suffix.lower() in AUDIO_EXT] if f else []
    return sorted(map(Path, filedialog.askopenfilenames(parent=parent, title=title, initialdir=initialdir, filetypes=[
        ("Audio", " ".join(f"*{e}" for e in AUDIO_EXT)), ("All files", "*.*")])), key=natural)


GOAL_HELP = {
    "Set them up for a purpose": "One click sets the action, fade and (for some) volume to suit what the sounds are for.",
    "Playback and fade": "Change how a press plays the sound. Keep = leave that setting as it is.",
    "Volume": "Set, nudge or even out the volume of every sound on the selected keys.",
    "Output device": "Sets every sound on the selected keys, including all sounds inside a Multi or Random Action "
                     "(Jump to Multi / Random at the top picks one). The list shows the devices by name, as Stream "
                     "Deck does; the app saves each device's Windows id, which is what Stream Deck itself saves.",
    "Key names and look": "Rename keys in bulk and change how their names look. Double-click a key to edit one.",
    "Arrange keys": "You can also drag keys on the grid to move or swap them, and right-click a key for more.",
    "Fix missing sound files": "Points broken sound keys (red) at a file with the same name anywhere in this folder "
                               "- handy for profiles copied from another computer.",
}
