"""Links: channelmirror:// links on this PC, and sending files between devices on the home network."""
import subprocess
from pathlib import Path
from .core import AUDIO_EXT, FFMPEG_DIR, NO_WINDOW, VIDEO_EXT


# --- links: channelmirror:// links on this PC, and sending files between devices on the home network ---
LINK_SCHEME = "channelmirror"


LINK_KEY = r"Software\Classes\channelmirror"


LINK_TARGETS = {"import": "Stream Deck keys (Import to folders)", "vts": "VTube Studio backgrounds",
                "soundboard": "Stream Deck soundboard (new profile)", "mirror": "Channel Mirror (split channels)",
                "files": "Just keep the files (Incoming folder)", "music": "Music player (a playlist)"}


LINK_EXT = tuple(dict.fromkeys(AUDIO_EXT + VIDEO_EXT + (".png", ".jpg", ".jpeg", ".gif")))


LINK_PORT, LINK_HANDOVER = 8765, 47613  # network pairing port; this PC only: a link handed to the open app


LINK_MAX = 2 * 1024 ** 3  # per file


LINK_INBOX = FFMPEG_DIR.parent / "Incoming"


def link_make(target, files=(), urls=()):
    """A channelmirror:// link that opens the app with these files (paths on this PC) / web addresses for target."""
    from urllib.parse import urlencode
    q = [("to", target)] + [("file", str(Path(f))) for f in files] + [("url", u) for u in urls]
    return f"{LINK_SCHEME}://open?{urlencode(q)}"


def link_parse(link):
    """{"to", "files": [Path], "urls": [str]} from a channelmirror:// link; ValueError for anything else."""
    from urllib.parse import parse_qs, urlsplit
    u = urlsplit(str(link).strip())
    if u.scheme.lower() != LINK_SCHEME:
        raise ValueError(f"Not a {LINK_SCHEME}:// link")
    q = parse_qs(u.query)
    to = (q.get("to") or [""])[0]
    if to not in LINK_TARGETS:
        raise ValueError(f"Unknown destination '{to}' (one of: {', '.join(LINK_TARGETS)})")
    import re
    raw = q.get("file", [])
    if any(not re.match(r"^[A-Za-z]:[\\/]", f) for f in raw):  # a drive on this PC - never a network share
        raise ValueError("Files in a link need their full path on this PC (like C:\\Sounds\\a.mp3)")
    files = [Path(f) for f in raw]
    if any(f.suffix.lower() not in LINK_EXT for f in files):
        raise ValueError("Links only carry sound, video and picture files")
    urls = q.get("url", [])
    if len(files) > 200 or len(urls) > 20:
        raise ValueError("Too many files in one link")
    if any(urlsplit(x).scheme.lower() not in ("http", "https") for x in urls):
        raise ValueError("Only http / https addresses can be downloaded")
    return {"to": to, "files": files, "urls": urls}


def link_args(argv):
    """The channelmirror:// link the app was started with (the first one), or None. When there is one, nothing else
    on the command line is used - a link can't add start-up options or files of its own."""
    return next((a for a in argv if str(a).lower().startswith(f"{LINK_SCHEME}:")), None)


LINK_TO_PEER = "--to-linked"  # Explorer's Send to > Channel Mirror (linked computers): send them to a linked PC


def link_to_peer(argv):
    """Started from Send to > Channel Mirror (linked computers): the text handed to the open app (the flag, then one
    file / folder per line), else None. Nothing is sent from it without picking the computer and pressing Send."""
    if LINK_TO_PEER not in argv:
        return None
    return "\n".join([LINK_TO_PEER] + [str(a) for a in argv if not str(a).startswith("--")])


def link_register(exe, key=LINK_KEY):
    """Make channelmirror:// links open this exe (per user, no admin)."""
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:Channel Mirror link")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{Path(exe)}" "%1"')


def link_registered(key=LINK_KEY):
    """The command channelmirror:// links run, or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key + r"\shell\open\command") as k:
            return winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None


def link_unregister(key=LINK_KEY):
    import winreg
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key + sub)
        except OSError:
            pass


def link_safe_name(name):
    """A received file's name made safe: no folders, no characters Windows won't take, an allowed type only."""
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1].strip().strip(".")
    stem, dot, ext = base.rpartition(".")
    if not dot or not stem or f".{ext.lower()}" not in LINK_EXT:
        raise ValueError(f"'{name}' isn't a sound, video or picture file")
    import re
    stem = "".join(c if c.isalnum() or c in " -_()[]" else "_" for c in stem)[:120]
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)", stem.strip()):  # Windows device names
        stem = "_" + stem
    return f"{stem}.{ext.lower()}"


def link_private(ip):
    """True for addresses on a home network or this PC (the only ones allowed to connect)."""
    import ipaddress
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    this_net = a.version == 4 and a in ipaddress.ip_network("0.0.0.0/8")  # "this network": not a real device
    return a.is_loopback or (a.is_private and not (a.is_link_local or a.is_reserved or a.is_unspecified
                                                   or a.is_multicast or this_net))


def link_public_network():
    """True when Windows has a connected network marked Public (cafe / hotel Wi-Fi): receiving isn't safe there."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-NetConnectionProfile).NetworkCategory"],
                           capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        return "public" in r.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def link_noproxy():
    """A URL opener that never goes through a proxy and never follows a redirect (this PC / the home network only:
    an answer can't send the request, signed headers and all, somewhere else)."""
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)


def link_lan_ip():
    """This PC's address on the home network (for the pairing link)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))  # nothing is sent: this only picks the network interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


LINK_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,
initial-scale=1"><title>Send to Channel Mirror</title><style>body{font:16px Segoe UI,sans-serif;max-width:560px;
margin:24px auto;padding:0 16px;background:#f3f4f6;color:#1f2937}h1{font-size:22px}label{display:block;margin:14px 0
4px;font-weight:600}select,input,button{font:inherit;width:100%;padding:8px;box-sizing:border-box}button{margin-top:18px;
background:#2563eb;color:#fff;border:0;border-radius:6px;padding:12px}#log{margin-top:14px;white-space:pre-wrap}
</style></head><body><h1>Send to Channel Mirror</h1><p>Files go to the PC running Channel Mirror; they're placed only
after it's accepted there.</p><label>Files (sounds, videos, pictures)</label><input id="f" type="file" multiple>
<label>Where they go</label><select id="t">__TARGETS__</select><label>This device's name</label>
<input id="n" value="My phone"><button id="go">Send</button><div id="log"></div><script>
const code="__CODE__", log=m=>document.getElementById('log').textContent=m;
document.getElementById('go').onclick=async()=>{const fs=[...document.getElementById('f').files];if(!fs.length)
return log('Pick files first.');const t=document.getElementById('t').value,b=Date.now().toString(36),
n=encodeURIComponent(document.getElementById('n').value);let i=0;for(const f of fs){log('Sending '+(++i)+' of '
+fs.length+': '+f.name);const r=await fetch('/upload?code='+code+'&batch='+b+'&target='+t+'&name='+
encodeURIComponent(f.name),{method:'POST',body:f});if(!r.ok)return log('Not sent: '+await r.text())}
const r=await fetch('/done?code='+code+'&batch='+b+'&target='+t+'&from='+n,{method:'POST'});
log(r.ok?'Sent '+fs.length+' file(s). Accept them on the PC.':'Not sent: '+await r.text())};</script></body></html>"""


def link_pair_url(ip, port, code):
    return f"http://{ip}:{port}/?code={code}"


def link_send(pair, files, target, device):
    """Send files to another Channel Mirror (its pairing link); returns how many were sent. Raises OSError /
    ValueError with the reason (wrong code, not a home-network address, a file it won't take...)."""
    import time
    import urllib.request
    from urllib.parse import parse_qs, urlsplit
    u = urlsplit(pair.strip())
    code = (parse_qs(u.query).get("code") or [""])[0]
    if u.scheme != "http" or not u.hostname or not code:
        raise ValueError("That isn't a pairing link (it looks like http://192.168.x.x:8765/?code=123456)")
    if not link_private(u.hostname):
        raise ValueError("Pairing links only work on the home network")
    from urllib.parse import urlencode
    base, batch, web = f"http://{u.netloc}", f"{int(time.time() * 1000):x}", link_noproxy()
    for f in map(Path, files):
        link_safe_name(f.name)  # refused here already if the other side wouldn't take it
        with open(f, "rb") as fh:
            q = urlencode({"code": code, "batch": batch, "target": target, "name": f.name})
            web.open(urllib.request.Request(f"{base}/upload?{q}", data=fh, method="POST",
                                            headers={"Content-Length": str(f.stat().st_size)}), timeout=60).read()
    q = urlencode({"code": code, "batch": batch, "target": target, "from": device})
    web.open(urllib.request.Request(f"{base}/done?{q}", data=b"", method="POST"), timeout=30).read()
    return len(files)
