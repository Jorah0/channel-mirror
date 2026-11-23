"""The main window's navigation: the sidebar lists every page once (grouped, Setup at the foot), a click opens its
page, Up / Down / Home / End move while it has focus, Ctrl+Tab / Ctrl+Shift+Tab go round (wrapping); a narrow window
shows icons only (the menu button is then off), a wide one names, and the menu button's choice is saved; the status
bar's items open their pages; the page shown is saved by name. Temp settings; nothing outside the app is touched."""
from tkinter import ttk

from harness import App

app = App()
cm = app.cm
app.start()
root, nb = app.root, app.nb
side = root.nametowidget("sidebar")
pages = app.tabs()
items = sorted((w for w in app.walk(side) if w.winfo_class() == "NavItem"), key=lambda w: w.winfo_rooty())  # top down


def name(item):
    return str(item.winfo_children()[2].cget("text"))  # bar, icon, name


def shown():
    return nb.tab(nb.select(), "text")


order = [name(w) for w in items]
assert sorted(order) == sorted(pages) and len(order) == len(pages), order  # every page once
assert order[-1] == "Setup" and order[:3] == ["Channel Mirror", "Music player", "Transcribe"], order
assert pages == ["Channel Mirror", "Stream Deck soundboard", "Stream Deck editor", "Import to folders", "Key mover",
                 "Screen recorder", "VTube Studio backgrounds", "Music player", "OBS", "Transcribe", "Link",
                 "Linked computers", "Phone remote", "Setup"], pages  # the notebook keeps its tabs, names and order
heads = [str(w.cget("text")) for p in pages for w in app.walk(app.tab(p).nametowidget("head"))
         if isinstance(w, ttk.Label) and str(w.cget("style")) == "PageTitle.TLabel"]
assert heads == pages, heads  # each page's header has its title

# a click on an item's icon (all a narrow window shows) opens its page
for w in items:
    icon = w.winfo_children()[1]
    app.click(icon)
    assert shown() == name(w), (shown(), name(w))

# keyboard: the sidebar's own keys while it has focus; Ctrl+Tab anywhere, round the sidebar's order
app.click(items[0].winfo_children()[1])
side.focus_force()
app.pump(0.1)
side.event_generate("<Down>")
assert shown() == order[1], shown()
side.event_generate("<End>")
assert shown() == "Setup", shown()
side.event_generate("<Down>")  # stays at the end
assert shown() == "Setup", shown()
side.event_generate("<Up>")
assert shown() == order[-2], shown()
side.event_generate("<Home>")
assert shown() == order[0], shown()
root.event_generate("<Control-Tab>")
assert shown() == order[1], shown()
root.event_generate("<Control-Shift-Tab>")
root.event_generate("<Control-Shift-Tab>")
assert shown() == "Setup", shown()  # wraps round
nb.select(app.tab("Key mover"))  # selecting a page any other way (as the app does) moves the sidebar along
app.pump(0.1)
assert str(items[order.index("Key mover")].cget("style")).startswith("NavOn"), items[order.index("Key mover")].cget("style")

# narrow window: icons only, the menu button is off; wide: names, and the menu button hides / shows them
toggle = next(b for b in app.walk(side) if isinstance(b, ttk.Button))
labels = [w.winfo_children()[2] for w in items]
root.geometry("400x600")  # held at the minimum size
app.pump(0.4)
assert not any(x.winfo_ismapped() for x in labels) and toggle.instate(["disabled"])
root.geometry(f"{root.winfo_screenwidth() - 100}x{root.winfo_screenheight() - 200}+0+0")
app.pump(0.6)
assert root.winfo_width() >= cm.px(1280), root.winfo_width()
assert all(x.winfo_ismapped() for x in labels) and toggle.instate(["!disabled"])
toggle.invoke()
app.pump(0.3)
assert not any(x.winfo_ismapped() for x in labels)

# status bar: live state, each item opens its page
bar = root.nametowidget("statusbar")
texts = [str(w.cget("text")) for w in app.walk(bar) if isinstance(w, ttk.Label) and w.winfo_ismapped()]
assert "No linked computers" in texts and "OBS not connected" in texts and "Nothing shared with OBS" in texts, texts
assert not any(t == "Recording" for t in texts), texts
obs_item = next(w for w in app.walk(bar) if isinstance(w, ttk.Label) and str(w.cget("text")) == "OBS not connected")
app.click(obs_item)
assert shown() == "OBS", shown()

app.tab("Transcribe")
saved = app.close()
assert saved["tab"] == "Transcribe" and saved["nav_compact"] is True, saved  # by name; icons only kept
print("navigation ok: sidebar (click, keys, Ctrl+Tab, narrow / wide / icons only), status bar, page saved by name")
