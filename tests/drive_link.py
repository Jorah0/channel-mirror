"""The Link tab in the main window: receive (listening on this PC only, so no firewall prompt; a Public network asks
first) and send to it from the Send section, accept (the file lands in its tab) / decline (the received copy is
deleted), a new code (the old link stops working), Stop; channelmirror:// links opened from the tab (a file on this
PC, a web address, a bad link); a link handed over to the open app lands in the Import tab. The accept prompt is
answered by a stub (cm.ui_incoming); temp folders and settings (harness); Stream Deck is never written."""
import functools
import http.server
import json
import shutil
import socket
import threading
import urllib.request
import wave
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import ttk

import harness
from harness import App, walk

real_serve = harness.cm.link_handover_serve  # the harness turns the hand-over port off; this test runs it on a free one
app = App()
cm = app.cm
asked, answers = [], []
cm.ui_incoming = lambda parent, files, target, source: (asked.append((list(files), target, source)),
                                                         answers.pop(0) if answers else target)[1]
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
cm.link_handover_serve = lambda on_link, port_=None: real_serve(on_link, port)

snd = app.tmp / "clip.wav"
with wave.open(str(snd), "wb") as w:
    w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000), w.writeframes(np.zeros(800, "<i2").tobytes())
# a Stream Deck profile, so the Import to folders tab can take files (a synthetic one, in the harness's temp folder)
prof = cm.SD_DIR / "ProfilesV3" / "P1.sdProfile"
(prof / "Profiles" / "PAGE1").mkdir(parents=True)
(prof / "manifest.json").write_text(json.dumps({"Device": {"Model": "20GBA9901", "UUID": "dev"}, "Name": "Test",
                                                "Pages": {"Current": "page1", "Default": "x", "Pages": ["page1"]}}))
(prof / "Profiles" / "PAGE1" / "manifest.json").write_text(json.dumps({"Controllers": [{"Type": "Keypad", "Actions": {
    "4,2": cm.sd_stop_key()}}]}))
cm.sd_connected = lambda: set()  # no USB query

app.start()
bg = app.tmp / "bg.png"
tk.PhotoImage(master=app.root, width=8, height=8).write(str(bg), format="png")  # a VTube Studio background
page = app.tab("Link")
lk = app.api("link")
v = lk["vars"]


def btn(text, within=page):
    return app.button(text, within)


def shown():
    return app.nb.tab(app.nb.select(), "text")


def import_rows():
    imp = app.tab("Import to folders")
    tree = next(w for w in walk(imp) if isinstance(w, ttk.Treeview))
    return [tree.item(i, "values")[1] for i in tree.get_children()]


def check(*why):
    assert not app.errors and not app.boxes, (why, app.errors, app.boxes)


# receive: on a network Windows calls Public it asks first (No = not started); then on this PC only
cm.link_public_network = lambda: True
app.yes.append(False)
v["port"].set("0")
btn("Start receiving").invoke()
assert lk["state"]["server"] is None and "Public" in app.asked[-1][2], app.asked
cm.link_public_network = lambda: False
btn("Start receiving").invoke()
assert lk["state"]["server"] and v["pair"].get().startswith("http://127.0.0.1:"), (v["pair"].get(), app.errors)
code = v["code"].get()
assert v["pair"].get().endswith(f"?code={code}") and len(code) == 8
assert btn("Stop receiving")  # the button says what it does now
print("start receiving ok (a Public network asks first):", v["pair"].get())

# send to it from the Send section: accepted -> into the VTube Studio backgrounds tab, kept in Incoming\Received
v["dest"].set(v["pair"].get())
v["send_to"].set(cm.LINK_TARGETS["vts"])
app.picks.append([bg])
next(b for b in walk(page) if isinstance(b, ttk.Button) and b.cget("text") == "Add files..."
     and b.master.master.cget("text").startswith("Send")).invoke()
btn("Send").invoke()
vts = app.api("vts")
assert app.wait(lambda: vts["files"], 15), (app.errors, asked, app.boxes)
check("send -> accept")
got = Path(vts["files"][0])
assert asked[0][1] == "vts" and got.name == "bg.png" and got.read_bytes() == bg.read_bytes(), (asked, got)
assert got.is_relative_to(cm.LINK_INBOX / "Received")  # accepted copies kept for good
assert not any((cm.LINK_INBOX / "pending").rglob("bg.png"))
assert shown() == "VTube Studio backgrounds"
print("send -> receive -> accept -> VTube Studio backgrounds tab ok:", asked[0][2])

# declined: the received copy is deleted, nothing reaches a tab
page = app.tab("Link")
answers.append(None)
btn("Send").invoke()
assert app.wait(lambda: len(asked) == 2, 15), (app.errors, app.boxes)
check("decline")
assert not Path(asked[1][0][0]).exists() and len(vts["files"]) == 1 and shown() == "Link"
print("decline deletes the received copy ok")

# a new code: the old link stops working; Stop clears what's waiting
old = v["pair"].get()
btn("New code").invoke()
assert v["code"].get() != code and v["pair"].get() != old
try:
    cm.link_send(old, [snd], "vts", "x")
    raise AssertionError("old code still works")
except OSError:
    pass
btn("Stop receiving").invoke()
assert lk["state"]["server"] is None and not (cm.LINK_INBOX / "pending").exists()
assert btn("Start receiving")
print("new code + stop ok")


def open_link(text):
    """Paste a link into the tab's OPEN A LINK box and press Open."""
    e = next(x for x in walk(page) if isinstance(x, ttk.Entry) and str(x.cget("textvariable")) == str(v["open"]))
    e.delete(0, "end")
    e.insert(0, text)
    next(b for b in e.master.winfo_children() if isinstance(b, ttk.Button) and b.cget("text") == "Open").invoke()
    app.pump(0.1)


# channelmirror:// links: a file on this PC -> the soundboard tab
sb = app.api("soundboard")
open_link(cm.link_make("soundboard", [snd]))
assert app.wait(lambda: sb.sounds, 10) and [Path(x["path"]) for x in sb.sounds] == [snd], sb.sounds
assert asked[-1][1] == "soundboard" and shown() == "Stream Deck soundboard"
check("file link")
# a web address (served here; the real download refuses this PC's address, so it's swapped for a copy)
page = app.tab("Link")
web = app.tmp / "web"
web.mkdir()
shutil.copy2(snd, web / "from the web.wav")
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(web)))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{httpd.server_address[1]}/from%20the%20web.wav"
real_fetch = cm.link_fetch


def fetch(u, folder):
    Path(folder).mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(u, timeout=5) as r:  # really downloaded, from the test's own server
        (Path(folder) / "from the web.wav").write_bytes(r.read())
    return Path(folder) / "from the web.wav"


cm.link_fetch = fetch
n_asked = len(app.asked)
open_link(cm.link_make("import", urls=[url]))
assert app.wait(lambda: shown() == "Import to folders", 15), (app.errors, app.boxes, lk["status"]())
assert "Download?" in app.asked[n_asked][1] and asked[-1][1] == "import"  # asked before downloading
assert "from the web.wav" in import_rows(), import_rows()
landed = next(f for f in cm.LINK_INBOX.rglob("from the web.wav"))
assert landed.is_relative_to(cm.LINK_INBOX / "Received") and landed.read_bytes() == snd.read_bytes()
try:
    real_fetch(url, app.tmp / "x")
    raise AssertionError("downloaded from this PC")
except ValueError:
    pass
httpd.shutdown()
check("web link")
# a bad link: a message in the tab, nothing else
page = app.tab("Link")
n = len(asked)
open_link("channelmirror://open?to=nope")
assert len(asked) == n and lk["status"]().startswith("Not a link"), lk["status"]()
check("bad link")
print("links (file -> soundboard, download -> import, bad) ok")

# a link handed over to the open app (as a second Channel Mirror does) lands in the Import tab once accepted
app.tab("Setup")
req = urllib.request.Request(f"http://127.0.0.1:{port}/link", data=cm.link_make("import", [snd]).encode(),
                             method="POST", headers={"X-Token": cm.link_token()})
assert urllib.request.urlopen(req, timeout=5).status == 200
assert app.wait(lambda: shown() == "Import to folders", 10), shown()
assert "clip.wav" in import_rows() and asked[-1][1] == "import", import_rows()
bad = urllib.request.Request(f"http://127.0.0.1:{port}/link", data=b"x", method="POST", headers={"X-Token": "no"})
try:
    urllib.request.urlopen(bad, timeout=5)
    raise AssertionError("a link without the token was taken")
except urllib.error.HTTPError as e:
    assert e.code == 403
assert app.tabs()[-4:] == ["Link", "Linked computers", "Phone remote", "Setup"], app.tabs()  # Setup is the last tab
print("hand-over to the open app -> Import tab ok")

saved = app.close()
assert "code" not in saved["link"] and saved["link"]["dest"] == old, saved["link"]  # the code is never saved
print("drive link ok")
