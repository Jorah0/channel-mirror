"""The setup tab."""
from pathlib import Path
from .setup import SETUP_ITEMS, SETUP_RESTART, setup_apply, setup_auto, setup_check, setup_reset, ui_mode
from .ui import UI, ui_switch


def setup_tab(page, cfg, live, restart):
    """The Setup tab: Appearance (Light / Dark / Follow Windows, switched straight away) and every folder Channel
    Mirror uses - found automatically, or picked here with Browse... and kept in the settings (cfg["paths"]), so
    every tool uses it; Auto goes back to finding it. live: {key: StringVar} for the folders a tab keeps itself
    (output folder, recordings, VTube Studio install); restart() closes the app and opens it again."""
    import tkinter as tk
    from tkinter import filedialog, ttk
    paths = cfg.setdefault("paths", {})
    top = page.winfo_toplevel()
    body = ttk.Frame(page, padding=12)
    body.pack(fill="both", expand=True)

    af = ttk.LabelFrame(body, text="Appearance")
    af.pack(fill="x")
    theme = tk.StringVar(value=cfg.get("theme", "system"))
    for text, val in (("Light", "light"), ("Dark", "dark"), ("Follow Windows", "system")):
        ttk.Radiobutton(af, text=text, variable=theme, value=val).pack(side="left", padx=(0, 18))
    ttk.Label(af, text="Changes straight away.", style="Hint.TLabel").pack(side="left")

    def on_theme(*_):
        cfg["theme"] = theme.get()
        ui_switch(top, theme.get())
    theme.trace_add("write", on_theme)

    def follow():  # Windows switched between light and dark while the app is open
        if cfg.get("theme", "system") == "system" and ui_mode("system") != UI["mode"]:
            ui_switch(top, "system")
        page.after(3000, follow)
    page.after(3000, follow)

    ff = ttk.LabelFrame(body, text="Folders")
    ff.pack(fill="x", pady=(8, 0))
    ff.columnconfigure(1, weight=1)
    ttk.Label(ff, style="Hint.TLabel", text=(
        "Found by themselves. Not found, or kept somewhere else? Pick it with Browse... and every tool uses it. "
        "Auto goes back to finding it.")).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 4))
    rows = {}

    def current(key):
        """(where it is now, picked by the user?)"""
        if key in live:
            val = live[key].get().strip()
            auto = setup_auto(key)
            return (Path(val) if val else auto), bool(val) and Path(val) != auto
        return (Path(paths[key]) if paths.get(key) else setup_auto(key)), bool(paths.get(key))

    def show(key):
        p, picked = current(key)
        r = rows[key]
        state = setup_check(key, p) if p or key != "out_dir" else "auto"
        r["path"].set(str(p) if p else "Next to each file you add" if key == "out_dir" else
                      "Not found - pick it with Browse...")
        text, style = {"found": ("✓ Found", "Good.TLabel"), "auto": ("✓ Ready", "Good.TLabel"),
                       "new": ("Made when first used", "Hint.TLabel"), "missing": ("✗ Not found", "Bad.TLabel")}[state]
        r["status"].config(text=text, style=style)
        r["auto"].config(state="normal" if picked else "disabled")

    def keep(key, value):  # into the settings and the running app ("" = Auto)
        if value:
            paths[key] = str(Path(value))
            setup_apply({key: value})
        else:
            paths.pop(key, None)
            setup_reset(key)

    def set_path(key, value):  # value "" = Auto
        if key in live:  # the tab that uses it shows it too (and keeps it: output folder, recordings)
            auto = setup_auto(key)
            live[key].set(value or ("" if key == "out_dir" or not auto else str(auto)))
        else:
            keep(key, value)
        if key in SETUP_RESTART:
            note.config(text="Restart Channel Mirror so every tab uses the folder you picked.", style="Bad.TLabel")
        show(key)

    def browse(key, name):
        p, _ = current(key)
        start = str(p.parent if key == "sd_exe" and p else p) if p and Path(p).exists() else str(Path.home())
        if key == "sd_exe":
            got = filedialog.askopenfilename(parent=page, title=f"Where is {name}?", initialdir=start,
                                             filetypes=[("Programs", "*.exe"), ("All files", "*.*")])
        else:
            got = filedialog.askdirectory(parent=page, title=f"Pick the {name} folder", initialdir=start)
        if got:
            set_path(key, got)

    for i, (key, name, what) in enumerate(SETUP_ITEMS, start=1):
        lab = ttk.Frame(ff)
        lab.grid(row=i, column=0, sticky="w", padx=(0, 12), pady=2)
        ttk.Label(lab, text=name, style="Name.TLabel").pack(anchor="w")
        ttk.Label(lab, text=what, style="Hint.TLabel").pack(anchor="w")
        rows[key] = {"path": tk.StringVar()}
        ttk.Entry(ff, textvariable=rows[key]["path"], state="readonly").grid(row=i, column=1, sticky="ew", pady=2)
        rows[key]["status"] = ttk.Label(ff, width=20)
        rows[key]["status"].grid(row=i, column=2, sticky="w", padx=(10, 6))
        ttk.Button(ff, text="Browse...", style="Tool.TButton", command=lambda k=key, n=name: browse(k, n)).grid(
            row=i, column=3, padx=(0, 4))
        rows[key]["auto"] = ttk.Button(ff, text="Auto", style="Tool.TButton", command=lambda k=key: set_path(k, ""))
        rows[key]["auto"].grid(row=i, column=4)
        if key == "vts" and key in live:  # picked here or in the VTube Studio tab: kept, and the tab starts from it
            live[key].trace_add("write", lambda *_: keep("vts", current("vts")[0] if current("vts")[1] else ""))
        if key in live:
            live[key].trace_add("write", lambda *_, k=key: show(k))
        show(key)

    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(8, 0))
    ttk.Button(bar, text="Restart now", command=restart).pack(side="right")
    note = ttk.Label(bar, style="Hint.TLabel", wraplength=760, justify="left", text=(
        "Folders you pick are used straight away; for the Stream Deck folder and app, restart Channel Mirror."))
    note.pack(side="left", fill="x", expand=True)
    return {"theme": theme, "rows": rows, "show": show, "note": note}
