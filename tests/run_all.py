"""Channel Mirror's one verify command:  python tests/run_all.py  [names...]   (needs ffmpeg/ffprobe on PATH)

Runs the selftest, pyflakes (when installed), every UI drive (tests/drive_*.py: the real app, driven by script, on
temp copies - your settings, Stream Deck and VTube Studio are never written, servers only on 127.0.0.1, no sound out
loud) and the layout audit (every control on screen, light + dark, small + large window). Give names (e.g. `music
link`) to run only those drives. Exit code 0 = all passed; a failing check's last lines are shown."""
import importlib.util
import re
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PY = sys.executable
only = sys.argv[1:]
checks = []  # (name, command, time limit, extra environment)
if not only:
    checks.append(("selftest", [PY, str(REPO / "channel_mirror.py"), "--selftest"], 900, {}))
    if importlib.util.find_spec("pyflakes"):
        checks.append(("pyflakes", [PY, "-m", "pyflakes", "channel_mirror.py", "cmlib", "tests"], 120, {}))
    else:
        print("pyflakes not installed: skipped (pip install pyflakes)")
for d in sorted(HERE.glob("drive_*.py")):
    if not only or d.stem[6:] in only:
        # transcribe: real speech recognition (and the first run downloads its model); emulator: an Android emulator
        # booted from scratch - more time, still bounded
        checks.append((f"drive {d.stem[6:]}", [PY, "-u", str(d), str(REPO)],
                       1200 if d.stem in ("drive_transcribe", "drive_emulator") else 600, {}))
if not only:
    for theme in ("light", "dark"):
        for size in (("1100", "720", "1.3333"), ("1650", "1080"), ("1650", "1080", "1.3333")):  # 1.3333 = 100 %
            checks.append((f"layout {theme} {size[0]}x{size[1]}{' 100%' if size[2:] else ''}",
                           [PY, "-u", str(HERE / "layout_audit.py"), str(REPO), *size], 600, {"CM_THEME": theme}))
failed = []
# main window only: a UI test opens the whole app (harness.App / cm.gui()) and works through its tabs and menus; it
# never builds a tab or dialog on its own or makes its own Tk window (wrapping a builder to keep its handles is fine)
SOLO = re.compile(r"(?<![\w\"'])(?:cm\.(?:\w+_tab|ui_(?:theme|new_key_dialog|key_dialog|bulk_dialog|pick_sounds|"
                  r"remote_deck|remote_vts|library|incoming|proposal|linked_bar|sound_form|level_report|send_linked))|tk\.Tk)\(")
if not only:
    solo = {d.name: [n for n, line in enumerate(d.read_text(encoding="utf-8").splitlines(), 1) if SOLO.search(line)]
            for d in [*HERE.glob("drive_*.py"), HERE / "rec_verify.py", HERE / "crosspc_peer.py"] if d.exists()}
    solo = {k: v for k, v in solo.items() if v}
    print(f"{'PASS' if not solo else 'FAIL'}  {'main window only':26}        "
          + ("every UI test works through the main window" if not solo else f"builds UI on its own: {solo}"))
    if solo:
        failed.append("main window only")
for name, cmd, limit, env in checks:
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env={**os.environ, "CM_TEST_TIMEOUT": str(limit - 30),
                                                                  **env})
    try:
        out, code = p.communicate(timeout=limit)[0].strip(), p.returncode
    except subprocess.TimeoutExpired:  # stuck: stop it and everything it started (ffmpeg, a second app, windows)
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        out, code = (p.communicate()[0] or "").strip() + f"\ntimed out after {limit} s: stopped", "timeout"
    last = out.splitlines()[-1] if out else ""
    ok = code == 0
    print(f"{'PASS' if ok else 'FAIL'}  {name:26} {time.time() - t0:5.0f} s  {last[:110]}", flush=True)
    if not ok:
        failed.append(name)
        print("      " + "\n      ".join(out.splitlines()[-12:]))
print(f"\n{len(checks) - len(failed)}/{len(checks)} passed" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
sys.exit(1 if failed else 0)
