"""Secrets in the settings, in the main window: pair secrets and the OBS password are sealed with Windows DPAPI.
One kept in plain text by an older version is sealed in the settings file as the app starts (and still works); one
that can't be read on this PC (another Windows user / PC, damaged) shows as needing to be linked again (the OBS
password field empty) and is kept as it was (until a new one is typed). Temp settings (harness); no real OBS or linked computer is reached."""
import json
import socket
import time

from harness import App

with socket.socket() as s:  # a port nobody listens on: the "linked computers" here are never reached
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
day = time.time() - 86400  # linked yesterday
plain = {"id": "e" * 32, "name": "Old PC", "host": "127.0.0.1", "port": dead, "secret": "ab" * 32, "since": day}
gone = {"id": "f" * 32, "name": "Other user", "host": "127.0.0.1", "port": dead, "secret": "dpapi:AAAAAAAA",
        "since": day}
app = App({"link": {"peers": [plain, gone]}, "obs": {"password": "dpapi:AAAAAAAA"}})
cm = app.cm
app.start()
lk, obs = app.api("link"), app.api("obs")
on_disk = {p["id"]: p for p in json.loads(cm.SETTINGS.read_text())["link"]["peers"]}
old = on_disk["e" * 32]["secret"]
assert old.startswith("dpapi:") and "ab" * 32 not in old and cm.secret_read(old) == "ab" * 32, on_disk
assert on_disk["f" * 32] == gone, on_disk  # can't be read here: kept exactly as it was
live = {p["id"]: p for p in lk["hub"]["peers"]()}
assert live["e" * 32]["secret"] == "ab" * 32 and cm.peer_days_left(live["e" * 32]) == 29, live
assert not live["f" * 32]["secret"] and not cm.peer_days_left(live["f" * 32]), live
app.tab("Linked computers")
assert app.wait(lambda: lk["tree"].exists("f" * 32), 5)
assert "link again" in lk["tree"].item("f" * 32, "values")[2], lk["tree"].item("f" * 32, "values")
assert "link it again" in lk["hub"]["label"](live["f" * 32])
print("pair secrets: an old plain one sealed at start (still works), an unreadable one shown as 'link again'")
assert obs["vars"]["password"].get() == "" and "can't be read" in obs["vars"]["conn"].get(), obs["vars"]["conn"].get()
print("OBS password that can't be read: the field is empty, and it says so")
saved = app.close()
peers = {p["id"]: p for p in saved["link"]["peers"]}
assert cm.secret_read(peers["e" * 32]["secret"]) == "ab" * 32 and peers["f" * 32] == gone, peers
assert "ab" * 32 not in json.dumps(saved) and saved["obs"]["password"] == "dpapi:AAAAAAAA", saved["obs"]  # not wiped
print("drive secrets ok")
