"""UI toolkit: theme, tooltips, menus, key grid, cell editing, sound forms (stdlib tkinter only)."""
import weakref
from pathlib import Path
from .core import AUDIO_EXT
from .mirror import media_files, natural
from .deck import SD_FADES, SD_LEVELS, SD_MODES, SD_OBS_DEFAULT, sd_output_choices, sd_set_levels
from .setup import ui_mode


# --- UI toolkit: design system (colour tokens, type scale, spacing), theme, tooltips, menus, key grid, cell editing
# Colour tokens, light and dark. Surfaces, lowest first: side (sidebar, status bar) < bg (pages) < panel (fields,
# lists); sel = the selected sidebar item, nav_hover = a sidebar item under the mouse, stripe = every other list row.
# line = card borders and dividers, border = control borders. Text: text, muted (secondary), dis (disabled); every
# text colour keeps 4.5:1 contrast or more on the surfaces it's used on. One accent (accent2 = its hover / pressed);
# good / warn / bad = success / warning / danger; remote = working on a linked computer (white text on it).
# sound / missing / other / auto / empty = Stream Deck key tiles.
UI_LIGHT = {"mode": "light", "side": "#eef0f3", "bg": "#f8f9fb", "panel": "#ffffff", "line": "#d9dde3",
            "border": "#c3c8cf", "text": "#1a1c1f", "muted": "#5b6169", "dis": "#8a9099", "accent": "#0f6cbd",
            "accent2": "#115ea3", "on_accent": "#ffffff", "accent_off": "#a9c7e6", "accent_off_fg": "#f2f7fc",
            "sel": "#e1e7f1", "nav_hover": "#e5e8ec", "stripe": "#f6f7f9", "sound": "#dcf3e6", "missing": "#fde2e1",
            "other": "#e8eaee", "auto": "#e2e8f7", "empty": "#ffffff", "button": "#fefefe", "hover": "#f1f3f5",
            "press": "#e6e9ed", "tab": "#eef0f2", "head": "#f3f4f6", "bad": "#c42b1c", "warn": "#9d5d00",
            "good": "#0f7b0f", "tip": "#1f2328", "tip_fg": "#f5f6f8", "remote": "#6d28d9"}


UI_DARK = {"mode": "dark", "side": "#191a1d", "bg": "#202124", "panel": "#2a2b2f", "line": "#404349",
           "border": "#4c4f56", "text": "#ebecef", "muted": "#a3a7af", "dis": "#7c8089", "accent": "#2a73c9",
           "accent2": "#2466b3", "on_accent": "#ffffff", "accent_off": "#2a3f5c", "accent_off_fg": "#8ea6c4",
           "sel": "#2c323d", "nav_hover": "#232529", "stripe": "#2e2f34", "sound": "#1d4434", "missing": "#55262a",
           "other": "#36383d", "auto": "#2c3561", "empty": "#2a2b2f", "button": "#2f3135", "hover": "#383a3f",
           "press": "#292b2f", "tab": "#1b1c1f", "head": "#2d2f33", "bad": "#ff99a4", "warn": "#fce100",
           "good": "#6ccb5f", "tip": "#3a3c41", "tip_fg": "#f3f4f6", "remote": "#7c3aed"}


# the palette in use (ui_switch swaps it) + the type scale and display zoom (ui_fonts fills them in)
UI = {**UI_LIGHT, "font": ("Segoe UI", 10), "small": ("Segoe UI", 8), "zoom": 1.0}


# icons: glyphs of the Segoe Fluent Icons font (Segoe MDL2 Assets on Windows 10) - no image files
ICON = {"mirror": "", "soundboard": "", "editor": "", "import": "", "mover": "",
        "recorder": "", "vts": "", "music": "", "obs": "", "transcribe": "",
        "link": "", "peers": "", "setup": "", "menu": "", "ok": "", "warn": "",
        "error": "", "info": "", "volume": "", "sync": "", "phone": ""}


# for a live switch: which widget options hold a background or a text colour, and the palette keys for each
UI_RECOLOUR = {("-background", "-highlightbackground", "-highlightcolor", "-activebackground", "-selectbackground",
                "-troughcolor", "-selectcolor", "-disabledbackground", "-readonlybackground"):
               ("bg", "panel", "border", "accent", "accent2", "sound", "missing", "other", "auto", "empty", "button",
                "hover", "press", "tab", "head", "tip", "stripe"),
               ("-foreground", "-insertbackground", "-activeforeground", "-disabledforeground", "-selectforeground"):
               ("text", "muted", "dis", "bad", "warn", "good", "tip_fg")}


UI_SWATCH = {"relief": "flat", "bd": 0, "highlightthickness": 1}  # colour boxes: a thin border in the palette's colour


def px(n):
    """n pixels of the 8 px spacing grid (4, 8, 12, 16, 24...) at this display's scaling (ui_fonts measures it)."""
    return round(n * UI["zoom"])


def ui_palette(choice):
    """Put the Light or Dark palette for this Appearance choice into UI (before ui_theme)."""
    UI.update(UI_DARK if ui_mode(choice) == "dark" else UI_LIGHT)


def ui_fonts(root):
    """The type scale (Windows 11's Segoe UI Variable when installed, else Segoe UI) and the display zoom, into UI:
    font = body, small, caption, strong = body semibold, label = form captions, section = card titles,
    title = page titles, mono = numbers and paths, icon / icon_small = Fluent icon glyphs."""
    from tkinter import font as tkfont
    have = set(tkfont.families(root))

    def pick(*names):
        return next((n for n in names if n in have), names[-1])
    text, semi = pick("Segoe UI Variable Text", "Segoe UI"), pick("Segoe UI Variable Text Semibold", "Segoe UI Semibold")
    icon = pick("Segoe Fluent Icons", "Segoe MDL2 Assets")
    UI.update(font=(text, 10), small=(text, 8), caption=(text, 9), strong=(semi, 10), label=(semi, 8),
              section=(semi, 11), title=(pick("Segoe UI Variable Display Semib", "Segoe UI Semibold"), 16),
              mono=(pick("Cascadia Mono", "Consolas"), 10), icon=(icon, 12), icon_small=(icon, 10),
              zoom=max(1.0, root.winfo_fpixels("1p") / (96 / 72)))


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


def _png(a):
    """RGBA uint8 array -> PNG file bytes (stdlib zlib + struct)."""
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    h, w = a.shape[:2]
    raw = b"".join(b"\0" + a[y].tobytes() for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _paint(w, h, shapes):
    """An anti-aliased RGBA image: shapes = [(sdf(x, y) -> distance, "#rrggbb"), ...] painted in order (4 x 4
    samples a pixel; inside = distance <= 0)."""
    import numpy as np
    y, x = (np.mgrid[0:h * 4, 0:w * 4] + 0.5) / 4
    rgb, alpha = np.zeros((h, w, 3)), np.zeros((h, w, 1))
    for sdf, col in shapes:
        a = (sdf(x, y) <= 0).reshape(h, 4, w, 4).mean((1, 3))[..., None]
        rgb = np.array([int(col[i:i + 2], 16) for i in (1, 3, 5)]) / 255 * a + rgb * (1 - a)  # premultiplied "over"
        alpha = a + alpha * (1 - a)
    out = np.concatenate([rgb / np.maximum(alpha, 1e-9), alpha], 2)
    return (out * 255 + 0.5).astype(np.uint8)


def _box(cx, cy, hw, hh, r):
    """Rounded rectangle: centre, half width / height, corner radius."""
    import numpy as np
    return lambda x, y: (np.hypot(np.maximum(abs(x - cx) - hw + r, 0), np.maximum(abs(y - cy) - hh + r, 0))
                         + np.minimum(np.maximum(abs(x - cx) - hw + r, abs(y - cy) - hh + r), 0) - r)


def _dot(cx, cy, r):
    import numpy as np
    return lambda x, y: np.hypot(x - cx, y - cy) - r


def _tick(n, t):
    """A check mark across an n-pixel box, t thick."""
    import numpy as np
    pts = [(0.28 * n, 0.52 * n), (0.43 * n, 0.67 * n), (0.73 * n, 0.36 * n)]

    def sdf(x, y):
        d = None
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            h = np.clip(((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2), 0, 1)
            e = np.hypot(x - ax - h * (bx - ax), y - ay - h * (by - ay))
            d = e if d is None else np.minimum(d, e)
        return d - t / 2
    return sdf


_IMG: dict = {}  # ttk element images by name; repainted in place on a Light / Dark switch


def _images(root):
    """Check box, radio button and slider pictures in the palette's colours (Fluent shapes, scaled to the display)."""
    import base64
    import tkinter as tk
    c, n, t = UI, px(18), max(1.0, UI["zoom"])
    m, k, g = n / 2, px(20), n + px(8)  # box centre; slider thumb size; check / radio picture width (gap to the text)

    def box(grow, col):
        return _box(m, m, m - 0.5 - grow, m - 0.5 - grow, px(4) - grow), col

    def dot(r, col, ctr=m):
        return _dot(ctr, ctr, r), col
    pics = {}
    for name, edge, fill in (("off", c["muted"], c["panel"]), ("off_hov", c["text"], c["hover"]),
                             ("off_dis", c["dis"], c["bg"])):
        pics["chk_" + name] = (g, n, [box(0, edge), box(t, fill)])
        pics["rad_" + name] = (g, n, [dot(m - 0.5, edge), dot(m - 0.5 - t, fill)])
    for name, fill, mark in (("on", c["accent"], c["on_accent"]), ("on_hov", c["accent2"], c["on_accent"]),
                             ("on_dis", c["dis"], c["bg"])):
        pics["chk_" + name] = (g, n, [box(0, fill), (_tick(n, 1.6 * t), mark)])
        pics["rad_" + name] = (g, n, [dot(m - 0.5, fill), dot(0.22 * n + (name == "on_hov") * t / 2, mark)])
    for name, inner, r in (("", c["accent"], 0.25), ("_hov", c["accent2"], 0.3), ("_dis", c["dis"], 0.25)):
        pics["thumb" + name] = (k, k, [dot(k / 2 - 0.5, c["border"], k / 2), dot(k / 2 - 0.5 - t, c["panel"], k / 2),
                                       dot(r * k, inner, k / 2)])
    pics["trough"] = (px(24), k, [(_box(px(12), k / 2, px(12) - 0.5, px(2), px(2)), c["border"])])
    for name, (w, h, shapes) in pics.items():
        data = base64.b64encode(_png(_paint(w, h, shapes)))
        if name in _IMG and _IMG[name].tk is root.tk:
            _IMG[name].configure(data=data)
        else:  # the first time, or a new main window (Restart in the Setup tab)
            _IMG[name] = tk.PhotoImage(master=root, name="cm_" + name, data=data)


def ui_theme(root):
    """Style every widget from UI (the Light or Dark palette) and the type scale: ttk styles plus matching defaults
    for the classic tk widgets. Running it again restyles every ttk widget on screen (ui_switch does the classic
    ones)."""
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk
    ui_fonts(root)
    c = UI
    body = "{%s} 10" % c["font"][0]
    root.configure(bg=c["bg"])
    # fonts for the classic tk widgets and ttk's text fields only: a "*Font" for all would also set every ttk.Label's
    # own font, which beats its style's (titles, hints, captions)
    for cls in ("Label", "Button", "Checkbutton", "Radiobutton", "Entry", "Text", "Listbox", "Spinbox", "Message",
                "Labelframe", "Menubutton", "Scale", "TEntry", "TCombobox", "TSpinbox"):
        root.option_add(f"*{cls}.Font", body)
    for pat, val in (("*Background", c["bg"]), ("*Foreground", c["text"]),
                     ("*insertBackground", c["text"]), ("*selectBackground", c["accent"]),
                     ("*selectForeground", c["on_accent"]), ("*activeBackground", c["hover"]),
                     ("*activeForeground", c["text"]), ("*highlightBackground", c["bg"]),
                     ("*highlightColor", c["accent"]), ("*Label.highlightBackground", c["border"]),
                     ("*Listbox.background", c["panel"]), ("*Listbox.relief", "flat"),
                     ("*Text.background", c["panel"]), ("*Checkbutton.selectColor", c["panel"]),
                     ("*Button.background", c["button"]), ("*Button.relief", "flat"),
                     ("*Scale.highlightThickness", 0), ("*Scale.troughColor", c["border"]),
                     ("*Scale.sliderRelief", "flat"), ("*Scale.borderWidth", 0), ("*Scale.activeBackground", c["accent"]),
                     ("*TCombobox*Listbox.background", c["panel"]), ("*TCombobox*Listbox.foreground", c["text"]),
                     ("*TCombobox*Listbox.font", body), ("*TCombobox*Listbox.borderWidth", 0),
                     ("*Menu.background", c["panel"]), ("*Menu.foreground", c["text"]), ("*Menu.font", body),
                     ("*Menu.activeBackground", c["accent"]), ("*Menu.activeForeground", c["on_accent"]),
                     ("*Menu.relief", "flat"), ("*Menu.activeBorderWidth", 0)):
        root.option_add(pat, val)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=c["bg"], foreground=c["text"], font=c["font"], bordercolor=c["border"],
                lightcolor=c["bg"], darkcolor=c["bg"], troughcolor=c["line"], focuscolor=c["accent"],
                selectbackground=c["accent"], selectforeground=c["on_accent"], fieldbackground=c["panel"],
                insertcolor=c["text"], arrowcolor=c["muted"])
    s.map(".", foreground=[("disabled", c["dis"])])
    s.map("TLabel", background=[])  # clam greys a disabled label's background

    # buttons: primary (Accent), secondary (TButton; Tool = compact), Ghost (no fill until hovered), Danger
    def flat(base, pressed, active, disabled):  # one colour per state, no 3D bevel
        return ({k: [("pressed", pressed), ("active", active), ("disabled", disabled)]
                 for k in ("background", "lightcolor", "darkcolor")},
                {"background": base, "lightcolor": base, "darkcolor": base})
    maps, conf = flat(c["button"], c["press"], c["hover"], c["bg"])
    s.configure("TButton", padding=(px(12), px(3)), anchor="center", **conf)
    s.map("TButton", bordercolor=[("focus", c["accent"]), ("disabled", c["line"])], **maps)
    s.configure("Tool.TButton", padding=(px(8), px(3)), width=0)
    maps, conf = flat(c["accent"], c["accent2"], c["accent2"], c["accent_off"])
    s.configure("Accent.TButton", foreground=c["on_accent"], bordercolor=c["accent"], font=c["strong"],
                padding=(px(16), px(3)), **conf)
    s.map("Accent.TButton", foreground=[("disabled", c["accent_off_fg"])],
          bordercolor=[("disabled", c["accent_off"]), ("focus", c["text"])], **maps)
    maps, conf = flat(c["bg"], c["press"], c["hover"], c["bg"])
    s.configure("Ghost.TButton", bordercolor=c["bg"], padding=(px(8), px(3)), width=0, **conf)
    s.map("Ghost.TButton", bordercolor=[("focus", c["accent"]), ("active", c["hover"])], **maps)
    for w in ("Danger.TButton", "Danger.Tool.TButton"):
        s.configure(w, foreground=c["bad"])
        s.map(w, **{k: [("pressed", c["missing"]), ("active", c["missing"]), ("disabled", c["bg"])]
                    for k in ("background", "lightcolor", "darkcolor")},
              foreground=[("disabled", c["dis"])], bordercolor=[("focus", c["accent"]), ("active", c["bad"])])
    s.configure("Toolbutton", padding=(px(12), px(7)), anchor="w", background=c["bg"], lightcolor=c["bg"],
                darkcolor=c["bg"], bordercolor=c["bg"])
    s.map("Toolbutton", **{k: [("selected", c["sel"]), ("active", c["hover"])]
                           for k in ("background", "lightcolor", "darkcolor")},
          bordercolor=[("focus", c["accent"]), ("selected", c["sel"]), ("active", c["hover"])],
          foreground=[("selected", c["text"])])

    # cards: titled sections with a soft border
    s.configure("TLabelframe", background=c["bg"], bordercolor=c["line"], lightcolor=c["bg"], darkcolor=c["bg"],
                relief="solid", padding=(px(10), px(6), px(10), px(8)), labelmargins=(px(2), 0, 0, px(4)))
    s.configure("TLabelframe.Label", background=c["bg"], foreground=c["text"], font=c["section"])
    s.configure("TSeparator", background=c["line"])
    s.configure("Line.TFrame", background=c["line"])

    # the page container: the sidebar picks pages, so the main notebook shows no tab strip
    s.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(px(8), px(6), px(8), 0),
                bordercolor=c["line"], lightcolor=c["bg"], darkcolor=c["bg"])
    s.configure("TNotebook.Tab", padding=(px(10), px(6)), background=c["tab"], foreground=c["muted"],
                bordercolor=c["line"], lightcolor=c["tab"], darkcolor=c["tab"])
    s.map("TNotebook.Tab", background=[("selected", c["bg"]), ("active", c["hover"])],
          lightcolor=[("selected", c["bg"]), ("active", c["hover"])], foreground=[("selected", c["text"])])
    s.configure("Pages.TNotebook", background=c["bg"], borderwidth=0, tabmargins=0, padding=0)
    s.layout("Pages.TNotebook", [("Notebook.client", {"sticky": "nswe"})])
    s.layout("Pages.TNotebook.Tab", [])

    # lists: taller rows, quiet headings, every other row shaded (ui_rows), accent selection
    line = tkfont.Font(root=root, font=c["font"]).metrics("linespace")  # scales with Windows DPI
    s.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["text"],
                rowheight=line + px(8), bordercolor=c["line"], lightcolor=c["panel"], darkcolor=c["panel"])
    s.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", c["on_accent"])])
    s.configure("Treeview.Heading", background=c["head"], foreground=c["muted"], font=(c["label"][0], 9),
                padding=(px(8), px(4)), relief="flat", bordercolor=c["line"], lightcolor=c["head"],
                darkcolor=c["head"])
    s.map("Treeview.Heading", **{k: [("active", c["hover"])] for k in ("background", "lightcolor", "darkcolor")},
          foreground=[("active", c["text"])])

    # check boxes, radio buttons and sliders: drawn pictures (ttk image elements) instead of clam's bevels
    _images(root)
    try:
        s.element_create("cm.Check.indicator", "image", "cm_chk_off", ("disabled selected", "cm_chk_on_dis"),
                         ("disabled", "cm_chk_off_dis"), ("active selected", "cm_chk_on_hov"),
                         ("selected", "cm_chk_on"), ("active", "cm_chk_off_hov"), sticky="")
        s.element_create("cm.Radio.indicator", "image", "cm_rad_off", ("disabled selected", "cm_rad_on_dis"),
                         ("disabled", "cm_rad_off_dis"), ("active selected", "cm_rad_on_hov"),
                         ("selected", "cm_rad_on"), ("active", "cm_rad_off_hov"), sticky="")
        s.element_create("cm.Scale.slider", "image", "cm_thumb", ("disabled", "cm_thumb_dis"),
                         ("pressed", "cm_thumb_hov"), ("active", "cm_thumb_hov"), sticky="")
        s.element_create("cm.Hscale.trough", "image", "cm_trough", border=(px(10), 0), padding=0, sticky="ew")
    except tk.TclError:
        pass  # made by the first ui_theme; their pictures were repainted above
    for cls, ind in (("Checkbutton", "cm.Check.indicator"), ("Radiobutton", "cm.Radio.indicator")):
        s.layout("T" + cls, [(f"{cls}.padding", {"sticky": "nswe", "children": [
            (ind, {"side": "left", "sticky": ""}),
            (f"{cls}.focus", {"side": "left", "sticky": "w", "children": [(f"{cls}.label", {"sticky": "nswe"})]})]})])
        s.configure("T" + cls, padding=(0, px(2)), focuscolor=c["accent"])
        s.map("T" + cls, background=[("disabled", c["bg"]), ("active", c["bg"])])
    s.layout("Horizontal.TScale", [("cm.Hscale.trough", {"sticky": "nswe", "children": [
        ("cm.Scale.slider", {"side": "left", "sticky": ""})]})])
    s.configure("TScale", background=c["bg"])

    # fields: one height for entries, dropdowns and spin boxes; an accent border while typing
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(w, fieldbackground=c["panel"], foreground=c["text"], padding=(px(6), px(3)),
                    bordercolor=c["border"], lightcolor=c["panel"], darkcolor=c["panel"], insertcolor=c["text"])
        s.map(w, bordercolor=[("focus", c["accent"]), ("hover", c["muted"])], lightcolor=[("focus", c["accent"])],
              fieldbackground=[("readonly", c["bg"] if w == "TEntry" else c["panel"]), ("disabled", c["bg"])])
    for w in ("TCombobox", "TSpinbox"):
        s.configure(w, background=c["panel"], arrowcolor=c["muted"], arrowsize=px(12))
        s.map(w, background=[("active", c["hover"]), ("disabled", c["bg"])], arrowcolor=[("disabled", c["dis"])])
    s.map("TCombobox", selectbackground=[("readonly", c["panel"])], selectforeground=[("readonly", c["text"])])

    # thin scroll bars without arrow buttons
    for o in ("Vertical", "Horizontal"):
        s.layout(f"{o}.TScrollbar", [(f"{o}.Scrollbar.trough", {"sticky": "nswe", "children": [
            (f"{o}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("TScrollbar", background=c["line"], troughcolor=c["panel"], bordercolor=c["panel"],
                lightcolor=c["line"], darkcolor=c["line"], arrowsize=px(8), gripcount=0)
    s.map("TScrollbar", **{k: [("pressed", c["muted"]), ("active", c["border"])]
                           for k in ("background", "lightcolor", "darkcolor")})

    # text: hints, form captions, status lines (info / success / warning / error), names, numbers, empty lists
    s.configure("Hint.TLabel", foreground=c["muted"], font=c["caption"])
    s.configure("Field.TLabel", foreground=c["muted"], font=c["label"])
    s.configure("Status.TLabel", foreground=c["muted"], padding=(px(2), px(4)))
    s.configure("Good.TLabel", foreground=c["good"], font=c["strong"])
    s.configure("Warn.TLabel", foreground=c["warn"], font=c["strong"])
    s.configure("Bad.TLabel", foreground=c["bad"], font=c["strong"])
    s.configure("Name.TLabel", font=c["strong"])
    s.configure("Mono.TLabel", font=c["mono"])
    s.configure("Empty.TLabel", background=c["panel"], foreground=c["muted"], justify="center", anchor="center")
    # where a tool works: this PC (a quiet chip), a linked computer (purple, unmistakable in both themes)
    s.configure("Remote.TLabel", background=c["remote"], foreground="#ffffff", font=c["strong"],
                padding=(px(10), px(5)))
    s.configure("Local.TLabel", background=c["bg"], foreground=c["muted"], font=c["strong"], padding=(0, px(5), px(6), px(5)))

    # the main window's frame: sidebar, page headers, status bar
    s.configure("Side.TFrame", background=c["side"])
    s.configure("Brand.TLabel", background=c["side"], foreground=c["text"], font=c["section"])
    s.configure("Caption.TLabel", background=c["side"], foreground=c["muted"], font=c["label"])
    for name, bg in (("Nav", c["side"]), ("NavHover", c["nav_hover"]), ("NavOn", c["sel"])):
        s.configure(f"{name}.TFrame", background=bg, bordercolor=bg, relief="solid", borderwidth=1)
        s.configure(f"{name}Focus.TFrame", background=bg, bordercolor=c["accent"], relief="solid", borderwidth=1)
        s.configure(f"{name}.TLabel", background=bg, foreground=c["text"], font=c["font"])  # same width selected
        s.configure(f"{name}Icon.TLabel", background=bg, foreground=c["accent"] if name == "NavOn" else c["muted"],
                    font=c["icon"])
    s.configure("NavBar.TFrame", background=c["accent"])
    maps, conf = flat(c["side"], c["press"], c["nav_hover"], c["side"])
    s.configure("NavToggle.TButton", font=c["icon"], foreground=c["muted"], bordercolor=c["side"],
                padding=(px(8), px(6)), width=0, **conf)
    s.map("NavToggle.TButton", bordercolor=[("focus", c["accent"]), ("active", c["nav_hover"])], **maps)
    s.configure("PageTitle.TLabel", font=c["title"], foreground=c["text"])
    s.configure("PageDesc.TLabel", foreground=c["muted"])
    s.configure("Bar.TFrame", background=c["side"])
    s.configure("Bar.TLabel", background=c["side"], foreground=c["muted"], font=c["caption"])
    for name, fg in (("Off", c["muted"]), ("On", c["good"]), ("Warn", c["warn"]), ("Bad", c["bad"]),
                     ("Remote", c["remote"] if c["mode"] == "light" else "#b794f6")):
        s.configure(f"Bar{name}.TLabel", background=c["side"], foreground=fg, font=c["icon_small"])
    root.bind_class("Tk", "<Map>", lambda e: ui_titlebar(e.widget))  # each window gets its title bar when shown
    root.bind_class("Toplevel", "<Map>", lambda e: ui_titlebar(e.widget))
    ui_rows()


def ui_rows():
    """Every list (ttk.Treeview) shades every other row and shows its empty-state hint (ui_empty) when it has no
    rows: its row changes (insert / delete / move / tags / open) are noticed here once, for all of them."""
    from tkinter import ttk
    if getattr(ttk.Treeview, "_cm_rows", False):
        return
    ttk.Treeview._cm_rows = True

    def soon(tree):
        if not getattr(tree, "_cm_job", None):
            try:
                tree._cm_job = tree.after_idle(lambda: _restripe(tree))
            except Exception:
                pass

    def wrap(name, when=lambda a, k: True):
        real = getattr(ttk.Treeview, name)

        def fn(self, *a, **k):
            out = real(self, *a, **k)
            if when(a, k):
                soon(self)
            return out
        fn._cm_real = real
        setattr(ttk.Treeview, name, fn)
    for name in ("insert", "delete", "move", "detach"):
        wrap(name)
    wrap("item", lambda a, k: "tags" in k or "open" in k)


def _restripe(tree):
    tree._cm_job = None
    try:
        if not tree.winfo_exists():
            return
        from tkinter import ttk
        item = ttk.Treeview.item._cm_real
        tree.tag_configure("odd", background=UI["stripe"])

        def rows(parent):
            for it in tree.get_children(parent):
                yield it
                if item(tree, it, "open"):
                    yield from rows(it)
        n = 0
        for n, it in enumerate(rows(""), 1):
            tags = [t for t in tree.tk.splitlist(item(tree, it, "tags")) if t != "odd"]
            item(tree, it, tags=tags + ["odd"] * (n % 2 == 0))
        hint = getattr(tree, "_cm_empty", None)
        if hint is not None:
            hint.place(relx=0.5, rely=0.5, anchor="center") if not n else hint.place_forget()
    except Exception:  # a list closing meanwhile
        pass


def ui_empty(tree, text):
    """A centred hint inside an empty list (a page's main list), instead of a blank box."""
    from tkinter import ttk
    tree._cm_empty = ttk.Label(tree, text=text, style="Empty.TLabel", justify="center", wraplength=px(520))
    _restripe(tree)


DANGER = {"Remove", "Remove selected", "Clear", "Clear all", "Clear key", "Delete", "Unlink", "Revert"}


def ui_danger(root):
    """Destructive buttons (named in DANGER) in the danger colour, all over the window: one pass once it's built, so
    every tab follows the same rule."""
    from tkinter import ttk
    todo = [root]
    while todo:
        w = todo.pop()
        todo += w.winfo_children()
        if isinstance(w, ttk.Button) and str(w.cget("text")) in DANGER and "Danger" not in str(w.cget("style")):
            w.configure(style="Danger." + (str(w.cget("style")) or "TButton"))


def ui_page(page, title, desc):
    """A page's header: its title and one line on what it's for; a linked-computer strip goes right under it."""
    from tkinter import ttk
    head = ttk.Frame(page, name="head", padding=(10, px(8), 10, 0))  # 10: the tabs' own margin
    head.pack(side="top", fill="x")
    ttk.Label(head, text=title, style="PageTitle.TLabel").pack(side="left")
    ttk.Label(head, text=desc, style="PageDesc.TLabel").pack(side="left", anchor="s", padx=(px(16), 0), pady=(0, px(4)))


def ui_sidebar(root, nb, groups, cfg):
    """The main window's navigation down the left: groups of pages (icon + name; groups = [(caption, [(tab text,
    icon key), ...]), ...], the last group's caption None = at the foot, like Setup). It only picks the notebook's
    pages - the notebook keeps its tabs, their names and order (its tab strip is hidden). Click a page, or Up / Down /
    Home / End while the sidebar has focus, Ctrl+Tab / Ctrl+Shift+Tab anywhere. Narrow windows show icons only; the
    menu button does it on wide ones too (kept in cfg["nav_compact"])."""
    from tkinter import ttk
    side = ttk.Frame(root, style="Side.TFrame", name="sidebar", takefocus=1)
    pages = {nb.tab(t, "text"): t for t in nb.tabs()}
    st = {"hover": None, "compact": None, "focus": False}
    order, items, captions = [], {}, []
    top = ttk.Frame(side, style="Side.TFrame", padding=(px(4), px(8), px(4), px(6)))
    top.pack(fill="x")
    toggle = ttk.Button(top, text=ICON["menu"], style="NavToggle.TButton", takefocus=0,
                        command=lambda: (cfg.__setitem__("nav_compact", not st["compact"]), fit()))
    toggle.pack(side="left")
    Tip(toggle, lambda: "Widen the window to show the page names" if narrow() else
        "Show page names" if st["compact"] else "Icons only")
    brand = ttk.Label(top, text="Channel Mirror", style="Brand.TLabel")
    foot = ttk.Frame(side, style="Side.TFrame", padding=(0, px(4), 0, px(8)))
    foot.pack(side="bottom", fill="x")
    body = ttk.Frame(side, style="Side.TFrame")
    body.pack(fill="both", expand=True)

    def paint(text):
        f, bar, ic, lb = items[text]
        on = nb.select() == pages[text]
        state = "NavOn" if on else "NavHover" if st["hover"] == text else "Nav"
        f.configure(style=f"{state}Focus.TFrame" if on and st["focus"] else f"{state}.TFrame")
        bar.configure(style="NavBar.TFrame" if on else f"{state}.TFrame")
        ic.configure(style=f"{state}Icon.TLabel")
        lb.configure(style=f"{state}.TLabel")

    def show(*_):
        for text in items:
            paint(text)

    def go(text):
        nb.select(pages[text])

    def hover(text, on):
        if on:
            st["hover"] = text
        elif st["hover"] == text:
            f = items[text][0]
            w = f.winfo_containing(*f.winfo_pointerxy())
            if w not in items[text]:
                st["hover"] = None
        show()
    for caption, entries in groups:
        parent = body if caption else foot
        if caption:
            cap = ttk.Label(body, text=caption.upper(), style="Caption.TLabel", padding=(px(16), px(10), 0, px(2)))
            cap.pack(fill="x")
            captions.append((cap, caption.upper(), ttk.Separator(cap)))  # icons only: a short rule instead
        for text, icon in entries:
            f = ttk.Frame(parent, style="Nav.TFrame", class_="NavItem", padding=1)
            bar = ttk.Frame(f, style="Nav.TFrame", width=px(3))
            bar.pack(side="left", fill="y", pady=px(7))
            ic = ttk.Label(f, text=ICON[icon], style="NavIcon.TLabel", padding=(px(8), px(6), px(8), px(6)))
            ic.pack(side="left")
            lb = ttk.Label(f, text=text, style="Nav.TLabel", padding=(0, 0, px(12), 0))
            f.pack(fill="x", padx=px(4), pady=1)
            items[text] = (f, bar, ic, lb)
            order.append(text)
            for w in (f, ic, lb, bar):
                w.bind("<Button-1>", lambda e, t=text: go(t))
                w.bind("<Enter>", lambda e, t=text: hover(t, True))
                w.bind("<Leave>", lambda e, t=text: side.after(15, hover, t, False))
            Tip(ic, lambda t=text: t if st["compact"] else "")

    def step(d, wrap=True):
        cur = next((t for t in order if nb.select() == pages[t]), order[0])
        i = order.index(cur) + d
        go(order[i % len(order)] if wrap else order[max(0, min(len(order) - 1, i))])
        return "break"
    for key, fn in (("<Up>", lambda e: step(-1, False)), ("<Down>", lambda e: step(1, False)),
                    ("<Home>", lambda e: step(-len(order), False)), ("<End>", lambda e: step(len(order), False))):
        side.bind(key, fn)
    for key, d in (("<Control-Tab>", 1), ("<Control-Shift-Tab>", -1)):
        root.bind(key, lambda e, d=d: step(d))
    side.bind("<FocusIn>", lambda e: (st.update(focus=True), show()))
    side.bind("<FocusOut>", lambda e: (st.update(focus=False), show()))
    nb.bind("<<NotebookTabChanged>>", show, add="+")

    def narrow():
        return root.winfo_width() < px(1280)

    def fit():
        compact = narrow() or bool(cfg.get("nav_compact"))
        toggle.state(["disabled" if narrow() else "!disabled"])
        if compact == st["compact"]:
            return
        st["compact"] = compact
        if compact:
            brand.pack_forget()
        else:
            brand.pack(side="left", padx=px(4))
        for f, bar, ic, lb in items.values():
            lb.pack_forget() if compact else lb.pack(side="left", fill="x", expand=True)
        for cap, text, rule in captions:
            cap.configure(text="" if compact else text)
            rule.place(relx=0.5, rely=0.6, anchor="center", relwidth=0.4) if compact else rule.place_forget()
    root.bind("<Configure>", lambda e: e.widget is root and fit(), add="+")
    fit()
    show()
    return side


def ui_statusbar(root, keys, right=""):
    """The window's foot: live state, one item per key (icon + text, coloured by kind; click = its page) and `right`
    at the far right. Returns put(key, icon, text, kind="Off" | "On" | "Warn" | "Bad" | "Remote", page=None);
    text None hides the item."""
    from tkinter import ttk
    bar = ttk.Frame(root, style="Bar.TFrame", padding=(px(12), px(2)), name="statusbar")
    ttk.Label(bar, text=right, style="Bar.TLabel").pack(side="right")
    items, shown, click = {}, [], {}  # type: ignore[var-annotated]
    for k in keys:
        f = ttk.Frame(bar, style="Bar.TFrame", cursor="hand2")
        ic, tx = ttk.Label(f, style="BarOff.TLabel"), ttk.Label(f, style="Bar.TLabel")
        ic.pack(side="left", padx=(0, px(6)))
        tx.pack(side="left")
        for w in (f, ic, tx):
            w.bind("<Button-1>", lambda e, k=k: click.get(k) and click[k]())
        items[k] = (f, ic, tx)

    def put(key, icon, text, kind="Off", page=None):
        f, ic, tx = items[key]
        if text is not None:
            ic.configure(text=ICON[icon], style=f"Bar{kind}.TLabel")
            tx.configure(text=text)
            click[key] = page
        vis = set(shown) - {key} | ({key} if text is not None else set())
        now = [k for k in keys if k in vis]
        if now != shown:
            shown[:] = now
            for k in keys:
                items[k][0].pack_forget()
            for k in shown:
                items[k][0].pack(side="left", padx=(0, px(20)))
    return bar, put


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
        tk.Label(self.win, text=text, justify="left", bg=UI["tip"], fg=UI["tip_fg"], font=UI["caption"],
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
    out = ttk.Combobox(f, textvariable=v["output"], width=28)
    out.config(postcommand=lambda: out.config(values=sd_output_choices()))
    fields = (("ACTION", ttk.Combobox(f, textvariable=v["mode"], values=SD_MODES, state="readonly", width=15)),
              ("FADE", ttk.Combobox(f, textvariable=v["fade"], values=SD_FADES, state="readonly", width=14)),
              ("FADE LENGTH (S)", ttk.Combobox(f, textvariable=v["fade_len"], values=("1", "2", "3", "4", "5"),
                                               state="readonly", width=5)),
              ("VOLUME", ui_volume(f, v["volume"], 120)),
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
