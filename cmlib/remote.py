"""Phone remote: a web app this PC serves to paired phones / tablets (home network, or anywhere through Tailscale)."""
import json
import re
import threading
import time
from pathlib import Path
from .core import NO_WINDOW
from .link import link_lan_ip, link_private
from .obs import _num, _one, obs_check
from .peers import PAIR_Q, pair_code, pair_offer, pair_point, pair_pub, pair_secret, \
    peer_name, peer_sign

REMOTE_PORT = 8770
REMOTE_SKEW = 60  # seconds a phone's request may be off (it keeps to the PC's clock from every signed answer)
REMOTE_TAILSCALE = ("100.64.0.0/10", "fd7a:115c:a1e0::/48")  # the addresses Tailscale gives devices


def remote_ok(ip):
    """True for an address the phone remote answers: the home network / this PC (link_private) or Tailscale."""
    import ipaddress
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:  # ::ffff:a.b.c.d is judged as a.b.c.d
        a = a.ipv4_mapped
    return link_private(str(a)) or any(a in ipaddress.ip_network(n) for n in REMOTE_TAILSCALE)


def remote_tailnet(ip):
    """True for a Tailscale address."""
    import ipaddress
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    return any(a in ipaddress.ip_network(n) for n in REMOTE_TAILSCALE)


def remote_hosts():
    """Where the remote listens: this PC's home-network address and its Tailscale ones - never every adapter."""
    import socket
    out = [link_lan_ip()]
    try:
        out += [sa[0] for *_, sa in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                if remote_tailnet(sa[0])]
    except OSError:
        pass
    return list(dict.fromkeys(a for a in out if remote_ok(a)))


def tailscale_info():
    """{"ip", "name"} of this PC on Tailscale, from its command line when it's installed ({} otherwise - Tailscale is
    never required; the remote also finds its address by itself)."""
    import os
    import shutil
    import subprocess
    exe = next((str(p) for p in [Path(os.environ.get(v) or d) / "Tailscale" / "tailscale.exe" for v, d in (
        ("ProgramFiles", "C:/Program Files"), ("ProgramFiles(x86)", "C:/Program Files (x86)"))] if p.is_file()), "")
    if not exe:  # installed elsewhere: on PATH - but never one in the folder it was started from
        import sys
        exe = shutil.which("tailscale") or ""
        if exe and Path(exe).resolve().parent in (Path.cwd().resolve(), Path(sys.executable).resolve().parent):
            exe = ""
    out = {}
    if not exe:
        return out
    try:
        r = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW)
        ip = (r.stdout.split() or [""])[0]
        if remote_tailnet(ip):
            out["ip"] = ip
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=5,
                           creationflags=NO_WINDOW)
        name = str(json.loads(r.stdout or "{}").get("Self", {}).get("DNSName", "")).rstrip(".").lower()
        if re.fullmatch(r"[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63}){1,6}", name):
            out["name"] = name
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        pass
    return out


# --- QR codes (byte mode, error correction M, versions 1-10): the pairing link as a picture the phone's camera reads
QR_M = {1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
        6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
        10: (26, [(4, 43), (1, 44)])}  # version -> (EC codewords per block, [(blocks, data codewords each)])


def _gf():
    exp, log, x = [0] * 512, [0] * 256, 1
    for i in range(255):
        exp[i], log[x] = x, i
        x = (x << 1) ^ (0x11D if x & 0x80 else 0)
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_EXP, _LOG = _gf()


def qr_ecc(data, n):
    """Reed-Solomon: the n error correction codewords for data (GF(256), x^8+x^4+x^3+x^2+1)."""
    gen = [1]
    for i in range(n):  # (x - a^0)(x - a^1)...(x - a^(n-1))
        gen = [a ^ (_EXP[_LOG[b] + i] if b else 0) for a, b in zip(gen + [0], [0] + gen)]
    rem = list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j in range(1, n + 1):
                if gen[j]:
                    rem[i + j] ^= _EXP[_LOG[gen[j]] + _LOG[c]]
    return rem[len(data):]


def qr_matrix(text):
    """The QR code for text (UTF-8 bytes): rows of True = dark, no quiet zone. ValueError when it's too long."""
    data = str(text).encode()
    ver = next((v for v, (_, g) in QR_M.items() if 4 + (8 if v < 10 else 16) + 8 * len(data)
                <= 8 * sum(b * d for b, d in g)), None)
    if ver is None:
        raise ValueError("too long for a QR code here")
    ec, groups = QR_M[ver]
    cap = sum(b * d for b, d in groups)
    bits = "0100" + format(len(data), "08b" if ver < 10 else "016b") + "".join(format(b, "08b") for b in data)
    bits += "0" * min(4, cap * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    words = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    words += [(0xEC, 0x11)[i % 2] for i in range(cap - len(words))]
    blocks, at = [], 0
    for b, d in groups:
        for _ in range(b):
            blocks.append(words[at:at + d])
            at += d
    eccs = [qr_ecc(b, ec) for b in blocks]
    stream = [b[i] for i in range(max(map(len, blocks))) for b in blocks if i < len(b)]
    stream += [e[i] for i in range(ec) for e in eccs]
    n = 17 + 4 * ver
    m = [[False] * n for _ in range(n)]
    fixed = [[False] * n for _ in range(n)]

    def put(r, c, dark):
        m[r][c], fixed[r][c] = dark, True
    for i in range(n):  # timing patterns
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cr, cc in ((3, 3), (3, n - 4), (n - 4, 3)):  # finders and their light borders
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                if 0 <= cr + dr < n and 0 <= cc + dc < n:
                    put(cr + dr, cc + dc, max(abs(dr), abs(dc)) not in (2, 4))
    pos = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
           9: [6, 26, 46], 10: [6, 28, 50]}[ver]
    for r in pos:
        for c in pos:
            if (r, c) not in ((6, 6), (6, n - 7), (n - 7, 6)):
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        put(r + dr, c + dc, max(abs(dr), abs(dc)) != 1)
    for i in range(9):  # format information's places (filled in below; the timing modules stay), the dark module
        if i != 6:
            put(8, i, False)
            put(i, 8, False)
    for i in range(8):
        put(8, n - 1 - i, False)
        put(n - 1 - i, 8, False)
    put(n - 8, 8, True)
    if ver >= 7:  # version information
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        vb = ver << 12 | rem
        for i in range(18):
            a, b, dark = n - 11 + i % 3, i // 3, bool(vb >> i & 1)
            put(a, b, dark)
            put(b, a, dark)
    i, total, right = 0, len(stream) * 8, n - 1
    while right >= 1:  # the codewords, two columns at a time, zig-zag up and down
        if right == 6:
            right = 5
        for vert in range(n):
            for j in range(2):
                c = right - j
                r = n - 1 - vert if (right + 1) & 2 == 0 else vert
                if not fixed[r][c]:
                    m[r][c] = i < total and bool(stream[i >> 3] >> (7 - (i & 7)) & 1)
                    i += 1
        right -= 2
    masks = (lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
             lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
             lambda r, c: r * c % 2 + r * c % 3 == 0, lambda r, c: (r * c % 2 + r * c % 3) % 2 == 0,
             lambda r, c: ((r + c) % 2 + r * c % 3) % 2 == 0)

    def formatted(k):
        out = [row[:] for row in m]
        for r in range(n):
            for c in range(n):
                if not fixed[r][c] and masks[k](r, c):
                    out[r][c] = not out[r][c]
        data_ = k  # error correction M = 00
        rem_ = data_
        for _ in range(10):
            rem_ = (rem_ << 1) ^ ((rem_ >> 9) * 0x537)
        fb = (data_ << 10 | rem_) ^ 0x5412
        for i_ in range(15):
            dark = bool(fb >> i_ & 1)
            if i_ < 8:  # first copy: down column 8 (skipping the timing row), then along row 8
                out[i_ if i_ < 6 else i_ + 1][8] = dark
                out[8][n - 1 - i_] = dark  # second copy: row 8 from the right, then column 8 at the bottom
            else:
                out[8][7 if i_ == 8 else 14 - i_] = dark
                out[n - 15 + i_][8] = dark
        return out

    def penalty(g):
        p = 0
        lines = g + [list(col) for col in zip(*g)]
        for line in lines:  # runs of five or more
            run = 1
            for a, b in zip(line, line[1:]):
                run = run + 1 if a == b else 1
                p += 3 if run == 5 else 1 if run > 5 else 0
            s = "".join("1" if x else "0" for x in [False] * 4 + line + [False] * 4)
            p += 40 * (len(re.findall("(?=10111010000)", s)) + len(re.findall("(?=00001011101)", s)))
        p += 3 * sum(g[r][c] == g[r][c + 1] == g[r + 1][c] == g[r + 1][c + 1] for r in range(n - 1)
                     for c in range(n - 1))
        dark = sum(map(sum, g))
        return p + 10 * ((abs(dark * 20 - n * n * 10) + n * n - 1) // (n * n) - 1)
    return min((formatted(k) for k in range(8)), key=penalty)


def qr_png(matrix, scale=6, quiet=4):
    """The QR code as PNG bytes: black on white (whatever the theme - cameras want it), a quiet zone round it."""
    import numpy as np
    from .ui import _png
    a = np.pad(np.array(matrix, dtype=bool), quiet)
    a = np.repeat(np.repeat(a, scale, 0), scale, 1)
    rgb = np.where(a[..., None], 0, 255).astype(np.uint8).repeat(3, 2)
    return _png(np.concatenate([rgb, np.full(a.shape + (1,), 255, np.uint8)], 2))


def remote_icon(size):
    """The web app's icon as PNG bytes: the accent colour, a phone with a sound wave on it."""
    from .ui import _box, _dot, _paint, _png
    import numpy as np
    s = min(size, 192)  # painted up to 192 px (4x4 samples each), then scaled up whole pixels
    pic = _paint(s, s, [(_box(s / 2, s / 2, s / 2, s / 2, s * 0.22), "#0f6cbd"),
                        (_box(s / 2, s / 2, s * 0.2, s * 0.32, s * 0.06), "#ffffff"),
                        (_box(s / 2, s / 2, s * 0.15, s * 0.25, s * 0.02), "#0f6cbd"),
                        (_dot(s / 2, s * 0.43, s * 0.07), "#ffffff"),
                        (_box(s / 2, s * 0.6, s * 0.03, s * 0.08, s * 0.015), "#ffffff")])
    k = -(-size // s)
    return _png(np.repeat(np.repeat(pic, k, 0), k, 1)[:size, :size])


# --- the crypto the web app does in JavaScript, with the same answers: SHA-256, HMAC-SHA256, SPAKE2 (peers.pair_*),
# request signatures (peers.peer_sign). The drive test runs the JavaScript in a real browser against these.
REMOTE_X = (int("1d2c3b4a59687786" * 30, 16), int("a1b2c3d4e5f60718" * 30, 16))  # fixed exponents for the vectors


def remote_vectors():
    """Inputs and answers both sides must agree on (no randomness): {name: value} - hex strings."""
    import hashlib
    import hmac
    code, ida = "12345678", "00112233445566778899aabbccddeeff"
    xa, xb = (x % (PAIR_Q - 1) + 1 for x in REMOTE_X)
    pa, pb = pair_pub(code, "A", xa), pair_pub(code, "B", xb)
    secret, proof_a, proof_b = pair_secret(code, "A", xa, pa, pb, ida)
    return {"sha_abc": hashlib.sha256(b"abc").hexdigest(), "sha_long": hashlib.sha256(b"a" * 200).hexdigest(),
            "hmac_fox": hmac.new(b"key", b"The quick brown fox jumps over the lazy dog", hashlib.sha256).hexdigest(),
            "sign": peer_sign("0f" * 32, "POST", "/api", 1700000000, "ab" * 16, hashlib.sha256(b"{}").hexdigest()),
            "point_a": f"{pair_point('A'):x}", "code_w": f"{pair_code(code):x}", "code": code, "id_a": ida,
            "x_a": f"{xa:x}", "x_b": f"{xb:x}", "pub_a": f"{pa:x}", "pub_b": f"{pb:x}", "secret": secret,
            "proof_a": proof_a, "proof_b": proof_b}


# --- what a paired phone may ask: a fixed list, every argument checked (OBS commands: obs_check's own list)
def _id(x):
    if not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", x):
        raise ValueError("Not an id")
    return x


def _rev(x):
    if not isinstance(x, str) or not re.fullmatch(r"[0-9a-f]{16}", x):
        raise ValueError("Not a deck version")
    return x


REMOTE_OBS = ("state", "scene", "item", "mute", "volume", "media", "output")  # no add_feed / feed_* from a phone
REMOTE_COMMANDS = {
    "state": {}, "deck": {}, "deck.stop": {},
    "deck.play": {"id": _num(0, 999), "rev": _rev, "to": _one("feed", "here", "both")},
    "obs": {"cmd": _one(*REMOTE_OBS), "args": lambda x: x},  # then obs_check(cmd, args)
    "music.list": {"list": _num(0, 999)}, "music.play": {"list": _num(0, 999), "song": _num(0, 99999)},
    "music.pause": {}, "music.resume": {}, "music.next": {}, "music.prev": {}, "music.stop": {},
    "music.seek": {"secs": _num(0, 86400)}, "music.volume": {"percent": _num(0, 100)},
    "rec.start": {}, "rec.stop": {}, "vts.bg": {"id": _id}}


def remote_check(cmd, args):
    """A phone's command checked against its strict form -> its arguments (ValueError saying what's wrong)."""
    if not isinstance(cmd, str) or cmd not in REMOTE_COMMANDS:
        raise ValueError(f"Not something the phone remote does: {str(cmd)[:30]!r}")
    form = REMOTE_COMMANDS[cmd]
    if not isinstance(args, dict) or set(args) != set(form):
        raise ValueError(f"'{cmd}' takes exactly: {', '.join(form) or 'nothing'}")
    out = {k: form[k](args[k]) for k in form}
    if cmd == "obs":
        out["args"] = obs_check(out["cmd"], args["args"])
    return out


class RemoteServer:
    """The phone remote's web server (plain http; see README for what that means): the web app's files to anyone on
    an allowed address (remote_ok - it's only the pairing page until a phone is paired), POST /pair/start and
    /pair/finish (SPAKE2 with the one-time code from open_pairing(); then ask(info) - this PC's user allows it or not),
    and POST /api: {"cmd", "args"} signed by a paired phone (HMAC-SHA256 with its own key over method, path, time, a
    one-time nonce and the body's hash; replies are signed back). devices() -> {id: key} (a removed phone is gone at
    once); run(id, cmd, args) answers a checked command (remote_check), from the server's thread.
    Refused: anything signed before the second this server started (so a recorded request can't be played again after
    the app restarts; nonces = the used ones, kept across turning it off and on) or more than REMOTE_SKEW s off, a nonce already used, more than RATE requests per PER s from one phone; TRIES wrong
    signatures / codes a minute from one address (TRIES_ALL from anywhere) shut that kind out for a minute.
    One listener per host in hosts (never 0.0.0.0), the same port; port 0 picks a free one (self.port)."""

    TRIES, TRIES_ALL, RATE, PER, BODY, CODE_SECS, CODE_STARTS, CONNS, PER_IP = 5, 30, 40, 10.0, 16384, 300, 3, 32, 6

    def __init__(self, hosts, port, devices, run, ask, name="", nonces=None):
        import hashlib
        import hmac
        import secrets
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from .remote_app import remote_files
        server, files = self, remote_files()
        self.devices, self.run, self.ask, self.name = devices, run, ask, name
        self.lock, self.fails, self.hits, self.sessions = threading.Lock(), {}, {}, {}
        self.nonces = {} if nonces is None else nonces  # (kept by the page: turning it off and on keeps them)
        self.code, self.started = None, int(time.time())  # (code, until, starts left)
        hex32, hexpub = re.compile(r"[0-9a-f]{32}"), re.compile(r"[0-9a-f]{1,512}")

        def tidy(now):
            for k in [k for k, t in server.nonces.items() if now - t > 2 * REMOTE_SKEW]:
                del server.nonces[k]
            for k in [k for k, s in server.sessions.items() if s[0] < now]:
                del server.sessions[k]
            for d, keep in ((server.fails, 60), (server.hits, server.PER)):
                for k in list(d):
                    d[k] = [t for t in d[k] if now - t < keep]
                    if not d[k]:
                        del d[k]

        def failed(kind, ip, now):  # under the lock
            for who in (ip, "*"):
                server.fails.setdefault((kind, who), []).append(now)

        def shut(kind, ip):  # under the lock, after tidy
            return (len(server.fails.get((kind, ip), [])) >= server.TRIES
                    or len(server.fails.get((kind, "*"), [])) >= server.TRIES_ALL)

        class Handler(BaseHTTPRequestHandler):
            timeout = 15  # a stalled phone is dropped

            def setup(self):  # the request (headers and body) must arrive within 20 s, however slowly it drips
                super().setup()
                self.deadline = threading.Timer(20, self.cut)
                self.deadline.daemon = True
                self.deadline.start()

            def cut(self):
                try:
                    self.connection.shutdown(2)
                except OSError:
                    pass

            def finish(self):
                self.deadline.cancel()
                super().finish()
            server_version, sys_version = "ChannelMirror", ""

            def log_message(self, *a):
                pass

            def reply(self, status, body, kind="text/plain; charset=utf-8", sign=None, cache="no-store", extra=()):
                body = body.encode() if isinstance(body, str) else body
                self.send_response(status)
                for k, v in (("Content-Type", kind), ("Content-Length", str(len(body))), ("Cache-Control", cache),
                             ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
                             ("X-Frame-Options", "DENY"), ("Content-Security-Policy",
                              "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; "
                              "form-action 'none'"), *extra):
                    self.send_header(k, v)
                if sign:  # (key, path, nonce): the phone checks the answer came from this PC
                    self.send_header("X-Sig", peer_sign(sign[0], "REPLY", sign[1], 0, sign[2],
                                                        hashlib.sha256(body).hexdigest()))
                self.end_headers()
                self.wfile.write(body)

            def read(self, limit):
                size = int(self.headers.get("Content-Length", -1))
                if not 0 <= size <= limit:
                    raise ValueError("too big" if size > limit else "no size given")
                data = self.rfile.read(size)
                if len(data) != size:
                    raise ValueError("it didn't arrive whole")
                self.deadline.cancel()  # all here: answering may take longer (the PC's user allowing a phone)
                return data

            def fields(self, data, want):
                d = json.loads(data or b"{}")
                if not isinstance(d, dict) or set(d) != set(want):
                    raise ValueError("not a request")
                return d

            def do_GET(self):
                self.deadline.cancel()
                if not remote_ok(self.client_address[0]):
                    return self.reply(403, "Only your own devices (home network or Tailscale) can open this.")
                f = files.get(self.path)
                if not f:
                    return self.reply(404, "Not found")
                self.reply(200, f[1], f[0], cache="no-cache")

            def do_POST(self):
                ip = self.client_address[0]
                if not remote_ok(ip):
                    return self.reply(403, "Only your own devices (home network or Tailscale) can open this.")
                try:
                    if self.path == "/api":
                        return self.api(ip)
                    if self.path in ("/pair/start", "/pair/finish"):
                        return self.pair(ip)
                except (ValueError, TypeError, KeyError, RecursionError) as e:
                    return self.reply(400, f"Not accepted: {str(e)[:200]}")
                self.reply(404, "Not found")

            def pair(self, ip):
                now = time.time()
                with server.lock:
                    tidy(now)
                    if shut("code", ip):
                        return self.reply(429, "Too many tries - wait a minute, then pair again.")
                if self.path == "/pair/start":
                    d = self.fields(self.read(4096), ("id", "name", "pub"))
                    if not (hex32.fullmatch(str(d["id"])) and hexpub.fullmatch(str(d["pub"]))):
                        raise ValueError("not a pairing request")
                    with server.lock:  # each start is one guess at the code: CODE_STARTS per code, then it's gone
                        c = server.code
                        if not c or c[1] < now or c[2] <= 0 or len(server.sessions) >= 8:
                            failed("code", ip, now)
                            return self.reply(403, "No pairing is open on the PC - press Pair a phone there (the "
                                                   "code works once, for 5 minutes).")
                        server.code = (c[0], c[1], c[2] - 1)
                        failed("code", ip, now)  # counted like a wrong one: a burst of guesses is shut out
                    y, pub_b = pair_offer(c[0], "B")
                    key, proof_a, proof_b = pair_secret(c[0], "B", y, int(d["pub"], 16), pub_b, d["id"])
                    sid = secrets.token_hex(16)
                    with server.lock:
                        server.sessions[sid] = (now + 60, ip, proof_a, c[0], {
                            "id": d["id"], "name": peer_name(d["name"], 40) or "Phone", "key": key, "ip": ip})
                    return self.reply(200, json.dumps({"session": sid, "pub": f"{pub_b:x}", "proof": proof_b}),
                                      "application/json")
                d, nonce = self.fields(self.read(4096), ("session", "proof")), self.headers.get("X-Nonce", "")
                if not hex32.fullmatch(nonce):
                    raise ValueError("not a pairing request")
                with server.lock:  # only the device that started it can end it, once
                    s = server.sessions.get(str(d["session"]))
                    if s and s[1] == ip:
                        del server.sessions[str(d["session"])]
                    if not s or s[1] != ip or not hmac.compare_digest(str(d["proof"]).encode("utf-8", "replace"),
                                                                     s[2].encode()):
                        failed("code", ip, now)
                        return self.reply(403, "Wrong pairing code - check the 8 digits the PC shows.")
                    if server.code and server.code[0] == s[3]:
                        server.code = None  # used: the next phone needs a new one
                got = server.ask(s[4])
                if not got:
                    return self.reply(403, "Not allowed on the PC.")
                self.reply(200, json.dumps({"name": peer_name(server.name) or "Channel Mirror", "now": int(
                    time.time())}), "application/json", sign=(s[4]["key"], self.path, nonce))

            def api(self, ip):
                h, now = self.headers, time.time()
                with server.lock:
                    tidy(now)
                    if shut("sig", ip):
                        return self.reply(429, "Too many refused requests - wait a minute.")
                dev, nonce, bh = h.get("X-Dev", ""), h.get("X-Nonce", ""), h.get("X-Body", "")
                key = server.devices().get(dev) if hex32.fullmatch(dev) else None
                try:
                    t = int(h.get("X-Time", ""))
                    data = self.read(server.BODY)
                except ValueError:
                    t, data = None, None
                if (not key or t is None or not hex32.fullmatch(nonce) or not re.fullmatch(r"[0-9a-f]{64}", bh)
                        or not hmac.compare_digest(h.get("X-Sig", "").encode("utf-8", "replace"),
                                                   peer_sign(key, "POST", "/api", t, nonce, bh).encode())
                        or not hmac.compare_digest(hashlib.sha256(data).hexdigest().encode(), bh.encode())):
                    with server.lock:
                        failed("sig", ip, now)
                    return self.reply(401, json.dumps({"unpaired": True, "error": "This phone isn't paired with "
                                                       "Channel Mirror (or was removed there) - pair it again."}),
                                      "application/json")
                if abs(now - t) > REMOTE_SKEW or t < server.started:  # the phone takes the PC's time - signed, so
                    return self.reply(409, json.dumps({"now": int(now)}), "application/json",  # an answer made up
                                      sign=(key, "/api", nonce))  # by someone else can't move its clock
                with server.lock:
                    if (dev, nonce) in server.nonces:
                        failed("sig", ip, now)
                        return self.reply(403, "That request was already used.")
                    server.nonces[(dev, nonce)] = now
                    hits = server.hits.setdefault(dev, [])
                    busy = len(hits) >= server.RATE
                    if not busy:
                        hits.append(now)
                sign = (key, "/api", nonce)
                if busy:
                    return self.reply(200, json.dumps({"ok": False, "busy": True, "error": "Too many at once - "
                                                       "slow down a moment."}), "application/json", sign=sign)
                try:
                    d = self.fields(data, ("cmd", "args"))
                    args = remote_check(d["cmd"], d["args"])
                    out = {"ok": True, **(server.run(dev, d["cmd"], args) or {})}
                except Exception as e:  # refused or failed: said, never half-done silently
                    out = {"ok": False, "error": str(e)[:300] or type(e).__name__}
                out["now"] = int(time.time())
                self.reply(200, json.dumps(out), "application/json", sign=sign)

        class Http(ThreadingHTTPServer):
            daemon_threads, allow_reuse_address = True, False
            slots = threading.BoundedSemaphore(self.CONNS)  # at most CONNS requests at once, PER_IP from one
            per_ip, ip_lock = {}, threading.Lock()  # address: more are dropped

            def process_request(self, req, addr):
                with self.ip_lock:
                    mine = self.per_ip.get(addr[0], 0)
                    if mine >= server.PER_IP or not self.slots.acquire(blocking=False):
                        return self.shutdown_request(req)
                    self.per_ip[addr[0]] = mine + 1
                try:
                    super().process_request(req, addr)
                except Exception:
                    self.done(addr)
                    raise

            def done(self, addr):
                with self.ip_lock:
                    self.per_ip[addr[0]] -= 1
                    if not self.per_ip[addr[0]]:
                        del self.per_ip[addr[0]]
                self.slots.release()

            def process_request_thread(self, req, addr):
                try:
                    super().process_request_thread(req, addr)
                finally:
                    self.done(addr)
        self.httpds, self.hosts, why = [], [], None
        for h in dict.fromkeys(hosts):
            if not remote_ok(h) or h in ("0.0.0.0", "::"):  # never every adapter, never a public address
                continue
            try:
                httpd = Http((h, port), Handler)
            except OSError as e:  # an address that's gone (Tailscale off): the others still work
                why = why or e
                continue
            port = httpd.server_address[1]  # the rest on the same port
            self.httpds.append(httpd)
            self.hosts.append(h)
        if not self.httpds:
            raise why or OSError("no address to listen on")
        self.port = port
        for httpd in self.httpds:
            threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def open_pairing(self):
        """A new one-time pairing code (8 digits, CODE_SECS seconds, CODE_STARTS tries); any older one stops working."""
        import secrets
        with self.lock:
            self.code = (f"{secrets.randbelow(10 ** 8):08d}", time.time() + self.CODE_SECS, self.CODE_STARTS)
            return self.code[0]

    def close_pairing(self):
        with self.lock:
            self.code = None

    def stop(self):
        for httpd in self.httpds:
            httpd.shutdown()
            httpd.server_close()
        self.httpds = []


def remote_url(host, port):
    return f"http://{f'[{host}]' if ':' in host else host}:{int(port)}/"

