"""Linked computers: two Channel Mirrors paired for PEER_DAYS days; signed requests, proposals."""
import json
import os
import shutil
from pathlib import Path
from .core import AUDIO_EXT, FFMPEG_DIR, OUTPUT_TYPES, SOURCES, TARGETS, VIDEO_EXT
from .mirror import natural, parse_time
from .deck import (
    SD_FADES,
    SD_FOLDER,
    SD_KINDS,
    SD_MODES,
    SD_PARENT,
    SD_PLAY,
    SD_STOP,
    sd_add_sounds,
    sd_clone_folders,
    sd_images,
    sd_kind,
    sd_plays_like,
    sd_renew,
    sd_sounds,
    sd_title,
    sd_wrap,
)
from .vts import SD_VTS_HOTKEY, VTS_EXT
from .link import (
    LINK_HANDOVER,
    LINK_MAX,
    LINK_PAGE,
    LINK_PORT,
    LINK_TARGETS,
    link_lan_ip,
    link_noproxy,
    link_private,
    link_safe_name,
)
from .obs import obs_check


class LinkServer:
    """Receives files from other devices on the home network: an upload page (GET /?code=), POST /upload (one file,
    streamed to the holding folder), POST /done (the batch is complete: on_batch(info) is called, from the server's
    thread). Every request needs the pairing code and a home-network address; only sound / video / picture files,
    up to LINK_MAX each. host="0.0.0.0" listens on the network; port 0 picks a free port (self.port).
    Linked computers (peers() -> {pair id: (secret, verified at)}): POST /pair?code= (the other PC asks to link;
    ask("pair", info) answers - its user decides), then /peer/... requests signed with the pair secret instead of
    the code: hello, browse, fetch + file (read), upload + done (a proposal: on_batch with "peer" and "spec"),
    renew, unlink, result, obs (an OBS command of the fixed list: ask("obs") answers it at once, on this thread - the
    PC decides whether that computer may). ask(kind, info) is called from the server's thread and returns a dict or None.
    A link older than PEER_DAYS (by this PC's clock) is refused. A UDP question on the same port finds this PC for
    a linked computer whose address changed (answered only with the pair secret).
    Pairing (POST /pair/start, /pair/finish) proves the code without sending it and agrees on the secret (SPAKE2).
    nonces = a file that keeps the signed requests already taken, so a recording of one isn't taken again after a
    restart. Reads (browse / fetch / library) are answered from memory for READ_CACHE s, READS a minute per linked
    computer at most. Wrong codes and refused signatures are counted apart, per address and from anywhere."""

    MAX_BATCHES, MAX_FILES, MAX_PENDING, KEEP = 5, 200, 4 * 1024 ** 3, 15 * 60  # waiting batches / bytes / secs
    READ_CACHE, READS, TRIES, TRIES_ALL = 3, 30, 5, 30  # s; reads a minute per linked PC; failures a minute per
    # address / from anywhere (of each kind: wrong codes, refused signatures) before that kind is shut out

    def __init__(self, port, code, inbox, on_batch, host=None, peers=None, ask=None, name="", nonces=None):
        import hashlib
        import hmac
        import re
        import secrets
        import socket
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import parse_qs, urlsplit
        from .core import atomic_write
        server = self
        self.code, self.inbox, self.batches = str(code), Path(inbox), {}
        self.lock, self.fails, self.started, self.sizes = threading.Lock(), {}, {}, {}
        self.peers, self.ask, self.name, self.clock = peers or (lambda: {}), ask, name, time.time
        self.nonces, self.offers, self.pairing, self.reads, self.hits = {}, {}, {}, {}, {}
        self.nonce_file, self.not_before, self.exposed = Path(nonces) if nonces else None, 0, None
        try:  # requests taken before a restart stay taken
            for p, n, t in json.loads(self.nonce_file.read_text()) if self.nonce_file else []:
                if time.time() - float(t) <= 2 * PEER_SKEW:
                    self.nonces[(str(p), str(n))] = float(t)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):  # can't tell which were taken: none signed before now is
            self.not_before = int(time.time())
        host = link_lan_ip() if host is None else host  # the home-network address only, not every adapter
        hex32, hex64, pub = re.compile(r"[0-9a-f]{32}"), re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{1,512}")

        def tidy(now):
            """Batches never finished within KEEP seconds are deleted; used nonces, old offers, pairing tries, reads
            and failures are forgotten."""
            for b in [b for b, t0 in server.started.items() if now - t0 > server.KEEP]:
                for f in server.batches.pop(b, []):
                    Path(f).unlink(missing_ok=True)
                server.started.pop(b, None)
                server.sizes.pop(b, None)
            for k in [k for k, t0 in server.nonces.items() if now - t0 > 2 * PEER_SKEW]:
                del server.nonces[k]
            for k in [k for k, o in server.offers.items() if o[1] < now]:
                del server.offers[k]
            for k in [k for k, s in server.pairing.items() if s[0] < now]:
                del server.pairing[k]
            for k in [k for k, r in server.reads.items() if now - r[0] >= server.READ_CACHE]:
                del server.reads[k]
            for d in (server.fails, server.hits):
                for k in list(d):
                    d[k] = [t for t in d[k] if now - t < 60]
                    if not d[k]:
                        del d[k]

        def failed(kind, ip, now):  # under server.lock
            for who in (ip, "*"):
                server.fails.setdefault((kind, who), []).append(now)

        def shut(kind, ip):  # under server.lock, after tidy
            return (len(server.fails.get((kind, ip), [])) >= server.TRIES
                    or len(server.fails.get((kind, "*"), [])) >= server.TRIES_ALL)

        class Handler(BaseHTTPRequestHandler):
            timeout = 30  # a stalled sender is dropped
            auth = None  # (pair id, secret, nonce) of a signed request from a linked computer: replies are signed

            def log_message(self, *a):  # quiet
                pass

            def reply(self, status, text, kind="text/plain; charset=utf-8", data=None):
                body = text.encode() if data is None else data
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                if self.auth:
                    self.send_header("X-Sig", peer_sign(self.auth[1], "REPLY", self.path, 0, self.auth[2],
                                                        hashlib.sha256(body).hexdigest()))
                self.end_headers()
                self.wfile.write(body)

            def json(self, obj):
                self.reply(200, "", "application/json", json.dumps(obj).encode())

            def body(self, limit):
                """The request's body (up to limit bytes), as JSON; a signed request's must match its hash."""
                size = int(self.headers.get("Content-Length", -1))
                if not 0 <= size <= limit:
                    raise ValueError("too big" if size > limit else "no size given")
                data = self.rfile.read(size)
                if len(data) != size or (self.auth and not hmac.compare_digest(
                        hashlib.sha256(data).hexdigest().encode(), self.headers.get("X-Body", "").encode())):
                    raise ValueError("it didn't arrive whole")
                d = json.loads(data or b"{}")
                if not isinstance(d, dict):
                    raise ValueError("not a request")
                return d

            def verify(self, now):
                """None when this is a signed request from a linked computer whose link is still good; else why."""
                h, no = self.headers, "Not a linked computer - link them in the Linked computers tab."
                pid, nonce, bh = h.get("X-Peer", ""), h.get("X-Nonce", ""), h.get("X-Body", "")
                entry = server.peers().get(pid)
                if not entry or not hex32.fullmatch(nonce) or not hex64.fullmatch(bh):
                    return no
                secret, since = entry
                try:
                    t = int(h.get("X-Time", ""))
                except ValueError:
                    return no
                if not hmac.compare_digest(h.get("X-Sig", "").encode("utf-8", "replace"),
                                           peer_sign(secret, self.command, self.path, t, nonce, bh).encode()):
                    return no
                if abs(now - t) > PEER_SKEW:
                    return "The two computers' clocks are more than 5 minutes apart - set the right time."
                if t < server.not_before:
                    return "That computer restarted just now - try again."
                if server.clock() - float(since) > PEER_DAYS * 86400:  # by this PC's own clock
                    return "This link has expired - verify it again (link the computers again in the Linked computers tab)."
                with server.lock:
                    if (pid, nonce) in server.nonces:
                        return "That request was already used."
                    server.nonces[(pid, nonce)] = now
                    if server.nonce_file:  # kept on disk first: taken once, even across a restart
                        try:
                            atomic_write(server.nonce_file, json.dumps([[p, n, t] for (p, n), t in
                                                                        server.nonces.items()]))
                        except OSError:
                            return "This PC couldn't note that request (is its disk full?) - try again."
                self.auth = (pid, secret, nonce)
                return None

            def check(self):
                u = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                ip, now = self.client_address[0], time.time()
                kind = "sig" if u.path.startswith("/peer/") else "code"  # counted apart: one never shuts out the other
                with server.lock:
                    tidy(now)
                    locked = shut(kind, ip)
                why = None
                if not link_private(ip):
                    self.reply(403, "Only devices on this home network can send.")
                elif locked:
                    self.reply(429, "Too many wrong codes - wait a minute, then use the link Channel Mirror shows."
                               if kind == "code" else "Too many refused requests - wait a minute, then try again.")
                elif kind == "sig":
                    why = self.verify(now)
                    if not why:
                        p = q.get("port", "")
                        if p.isdigit() and 0 < int(p) < 65536 and server.ask:  # where it can be reached now
                            server.ask("seen", {"id": self.auth[0], "host": ip, "port": int(p)})
                        return u.path, q
                elif u.path in ("/pair/start", "/pair/finish"):
                    return u.path, q  # the code is proved there, never sent
                elif not hmac.compare_digest(q.get("code", "").encode("utf-8", "replace"), server.code.encode()):
                    why = "Wrong pairing code - open the link Channel Mirror shows."
                else:
                    server.exposed = server.code  # it crossed the network in plain text: no longer good to link
                    return u.path, q
                if why:
                    with server.lock:  # TRIES wrong from one device, or TRIES_ALL from anywhere: shut out a minute
                        failed(kind, ip, now)
                    self.reply(403, why)
                return None, None

            def do_GET(self):
                path, q = self.check()
                if path == "/":
                    opts = "".join(f'<option value="{k}">{v}</option>' for k, v in LINK_TARGETS.items())
                    self.reply(200, LINK_PAGE.replace("__TARGETS__", opts).replace("__CODE__", server.code),
                               "text/html; charset=utf-8")
                elif path == "/peer/hello":
                    self.json({"name": server.name or "Channel Mirror"})
                elif path in ("/peer/browse", "/peer/fetch", "/peer/library"):
                    info = {"peer": self.auth[0]}
                    if path == "/peer/fetch":
                        try:
                            info.update(profile=q.get("profile", ""), page=int(q.get("page", "")),
                                        page_name=q.get("page_name", ""), keys=[k for k in q.get("keys", "").split(
                                            ";") if re.fullmatch(r"\d{1,2},\d{1,2}", k)][:200])
                        except ValueError:
                            return self.reply(400, "Bad request")
                    key, now = (self.auth[0], path) if path != "/peer/fetch" else None, time.time()  # fetch: new offers
                    with server.lock:  # the same read again at once: from memory; a few a minute per linked PC
                        kept = server.reads.get(key)
                        hits = server.hits.setdefault(self.auth[0], [])
                        busy = not kept and len(hits) >= server.READS
                        if not kept and not busy:
                            hits.append(now)
                    if busy:
                        return self.reply(429, "Too many reads from that computer - wait a moment, then try again.")
                    if kept:
                        return self.json(kept[1])
                    got = server.ask(path[6:], info) if server.ask else None
                    if got is None:
                        return self.reply(503, "That computer is busy (a question is open there) - try again.")
                    if key:
                        with server.lock:
                            server.reads[key] = (now, got)
                    self.json(got)
                elif path == "/peer/file":  # a file a fetch offered to this linked computer, and only to it
                    with server.lock:
                        o = server.offers.get(q.get("token", ""))
                    if not o or o[2] != self.auth[0] or not Path(o[0]).is_file():
                        return self.reply(404, "Not found")
                    sha = hashlib.sha256()
                    with open(o[0], "rb") as f:
                        while chunk := f.read(1 << 20):
                            sha.update(chunk)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(Path(o[0]).stat().st_size))
                    self.send_header("X-Sig", peer_sign(self.auth[1], "REPLY", self.path, 0, self.auth[2],
                                                        sha.hexdigest()))
                    self.end_headers()
                    with open(o[0], "rb") as f:
                        shutil.copyfileobj(f, self.wfile, 1 << 20)
                elif path:
                    self.reply(404, "Unknown request")

            def do_POST(self):
                path, q = self.check()
                if not path:
                    return
                peer = self.auth[0] if self.auth else None
                try:
                    if path == "/pair":  # an older Channel Mirror (it sent its secret over the network)
                        raise ValueError("that computer's Channel Mirror is older - update it there to link")
                    if path == "/pair/start":  # the other PC asks to link: SPAKE2 with the code, one guess per try
                        d, ip = self.body(4096), self.client_address[0]
                        if set(d) - {"id", "name", "port", "pub"}:
                            raise ValueError("unknown field")
                        if not (hex32.fullmatch(str(d.get("id", ""))) and pub.fullmatch(str(d.get("pub", "")))
                                and type(d.get("port")) is int and 0 < d["port"] < 65536):
                            raise ValueError("not a pairing request")
                        with server.lock:  # checked and counted at once: a burst of tries can't slip past
                            if shut("code", ip) or len(server.pairing) >= 8:
                                return self.reply(429, "Too many tries to link - wait a minute, then try again.")
                            failed("code", ip, time.time())  # a try at the code: its answer tells the asker
                            code = server.code
                        if code == server.exposed:  # a device's upload page sent it in plain text
                            return self.reply(403, "That pairing code was used by a device on the network - press "
                                                   "New code on that PC, then link with the new link.")
                        y, pub_b = pair_offer(code, "B")
                        secret, proof_a, proof_b = pair_secret(code, "B", y, int(d["pub"], 16), pub_b, d["id"])
                        sid = secrets.token_hex(16)
                        with server.lock:
                            server.pairing[sid] = (time.time() + 60, ip, proof_a, {
                                "id": d["id"], "name": peer_name(d.get("name")) or ip, "host": ip, "port": d["port"],
                                "secret": secret})
                        return self.json({"session": sid, "pub": f"{pub_b:x}", "proof": proof_b})
                    if path == "/pair/finish":  # it proved the code too: now this PC's user is asked
                        d, nonce = self.body(4096), self.headers.get("X-Nonce", "")
                        if set(d) - {"session", "proof"} or not hex32.fullmatch(nonce):
                            raise ValueError("not a pairing request")
                        ip = self.client_address[0]
                        with server.lock:  # only the device that started it can end it (once)
                            s = server.pairing.get(str(d.get("session", "")))
                            if s and s[1] == ip:
                                del server.pairing[str(d["session"])]
                            if not s or s[1] != ip or not hmac.compare_digest(
                                    str(d.get("proof", "")).encode("utf-8", "replace"), s[2].encode()):
                                failed("code", ip, time.time())
                                s = None
                        if not s:
                            return self.reply(403, "Wrong pairing code - open the link Channel Mirror shows.")
                        got = server.ask("pair", s[3]) if server.ask else None
                        if got is None:
                            return self.reply(403, "Not accepted on that computer.")
                        self.auth = (s[3]["id"], s[3]["secret"], nonce)  # the answer proves it has the same secret
                        return self.json(got)
                    if path == "/peer/obs":
                        d = self.body(65536)
                        if set(d) - {"cmd", "args"}:
                            raise ValueError("unknown field")
                        args = obs_check(d.get("cmd"), d.get("args"))  # the fixed list, each argument checked
                        got = server.ask("obs", {"peer": peer, "cmd": d["cmd"], "args": args}) if server.ask else None
                        if got is None:
                            return self.reply(503, "OBS can't be controlled on that computer.")
                        return self.json(got)
                    if path in ("/peer/renew", "/peer/unlink", "/peer/result"):
                        d = self.body(4096)
                        if path == "/peer/renew" and "secret" in d:  # an older Channel Mirror sends the secret itself
                            raise ValueError("that computer's Channel Mirror is older - update it there to renew")
                        if set(d) - {"/peer/renew": {"pub"}, "/peer/unlink": set(),
                                     "/peer/result": {"batch", "ok", "note"}}[path]:
                            raise ValueError("unknown field")
                        if path == "/peer/renew":  # a new secret agreed with the old one (never sent)
                            if not pub.fullmatch(str(d.get("pub", ""))):
                                raise ValueError("not a renewal")
                            y, pub_b = pair_offer(self.auth[1], "B")
                            new = pair_secret(self.auth[1], "B", y, int(d["pub"], 16), pub_b, peer)[0]
                            got = server.ask("renew", {"id": peer, "secret": new,
                                                       "host": self.client_address[0]}) if server.ask else None
                            if got is None:
                                return self.reply(403, "Not renewed on that computer.")
                            return self.json(dict(got, pub=f"{pub_b:x}"))  # signed with the secret it came with
                        if path == "/peer/result":
                            d = {"batch": str(d.get("batch", ""))[:40], "ok": bool(d.get("ok")),
                                 "note": peer_name(d.get("note", ""), 200)}
                        else:
                            d = {}
                        if server.ask:
                            server.ask(path[6:], {"id": peer, **d})
                        return self.reply(200, "ok")
                    if path == "/peer/done":
                        d = self.body(PEER_JSON)
                        if set(d) - {"target", "spec", "files"}:
                            raise ValueError("unknown field")
                        n = d.get("files")
                        if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= server.MAX_FILES:
                            raise ValueError("bad file count")
                        spec = peer_proposal(d.get("target"), d.get("spec"), n)
                        mine = "".join(c for c in q.get("batch", "") if c.isalnum())[:40]
                        batch = "p" + peer[:8] + mine
                        with server.lock:
                            files = server.batches.pop(batch, [])
                            server.started.pop(batch, None)
                            server.sizes.pop(batch, None)
                        try:
                            if len(files) != n:
                                raise ValueError("not every file arrived")
                            peer_check_files(d["target"], spec, files)  # types and real content, here
                        except ValueError:
                            for f in files:
                                Path(f).unlink(missing_ok=True)
                            raise
                        self.reply(200, "ok")
                        return on_batch({"batch": mine, "target": d["target"], "files": files, "from": peer,
                                         "peer": peer, "spec": spec, "address": self.client_address[0],
                                         "time": time.strftime("%H:%M:%S")})
                except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as e:
                    return self.reply(400, f"Not accepted: {str(e)[:300]}")
                batch = "".join(c for c in q.get("batch", "") if c.isalnum())[:40]
                if not batch or (not peer and q.get("target") not in LINK_TARGETS):
                    return self.reply(400, "Missing batch or destination")
                if peer:
                    batch = "p" + peer[:8] + batch  # its own batches: another device can't add to them
                if path in ("/upload", "/peer/upload"):
                    try:
                        if peer and any(c in q.get("name", "") for c in r"\/:"):
                            raise ValueError("a file name can't be a path")
                        name = link_safe_name(q.get("name", ""))
                        size = int(self.headers.get("Content-Length", -1))
                        if not 0 <= size <= LINK_MAX:
                            raise ValueError("too big" if size > LINK_MAX else "no size given")
                    except ValueError as e:
                        return self.reply(400, f"Not accepted: {e}")
                    with server.lock:  # limits on what may wait here for an answer
                        if batch not in server.batches and len(server.batches) >= server.MAX_BATCHES:
                            return self.reply(429, "Busy - accept or decline what's waiting on the PC first")
                        if len(server.batches.get(batch, [])) >= server.MAX_FILES:
                            return self.reply(400, "Too many files in one go")
                        if sum(server.sizes.values()) + size > server.MAX_PENDING:
                            return self.reply(429, "Too much waiting to be accepted")
                        server.inbox.mkdir(parents=True, exist_ok=True)
                        if shutil.disk_usage(server.inbox).free < size + 1024 ** 3:
                            return self.reply(507, "Not enough free disk space on the PC")
                        server.batches.setdefault(batch, [])
                        server.started.setdefault(batch, time.time())
                        server.sizes[batch] = server.sizes.get(batch, 0) + size
                    folder = server.inbox / f"b{batch}"  # never a Windows device name
                    folder.mkdir(parents=True, exist_ok=True)
                    n = 1
                    while True:  # a new file only: two uploads of the same name can't overwrite each other
                        dst = folder / (name if n == 1 else f"{Path(name).stem} ({n}){Path(name).suffix}")
                        try:
                            out = open(dst, "xb")
                            break
                        except FileExistsError:
                            n += 1
                    left, sha = size, hashlib.sha256()
                    try:
                        with out:
                            while left:
                                chunk = self.rfile.read(min(left, 1 << 20))
                                if not chunk:
                                    break
                                sha.update(chunk)
                                out.write(chunk)
                                left -= len(chunk)
                    except OSError:
                        left = left or 1
                    if left or (peer and not hmac.compare_digest(sha.hexdigest().encode(),
                                                                 self.headers.get("X-Body", "").encode())):
                        dst.unlink(missing_ok=True)
                        return self.reply(400, "The file didn't arrive whole")
                    with server.lock:
                        server.batches.setdefault(batch, []).append(dst)
                    return self.reply(200, "ok")
                if path == "/done" and not peer:
                    with server.lock:
                        files = server.batches.pop(batch, [])
                        server.started.pop(batch, None)
                        server.sizes.pop(batch, None)
                    if not files:
                        return self.reply(400, "Nothing arrived in that batch")
                    bad = []
                    for f in files:
                        try:
                            link_check_file(f)  # its content really is a sound / video / picture of that type
                        except (ValueError, OSError) as e:
                            bad.append(str(e))
                    if bad:
                        for f in files:
                            Path(f).unlink(missing_ok=True)
                        return self.reply(400, "Not accepted: " + "; ".join(bad[:10]))
                    self.reply(200, "ok")
                    who = "".join(c for c in q.get("from", "") if c.isprintable())[:60] or self.client_address[0]
                    on_batch({"batch": batch, "target": q["target"], "files": files, "from": who,
                              "address": self.client_address[0], "time": time.strftime("%H:%M:%S")})
                    return
                self.reply(404, "Unknown request")
        ThreadingHTTPServer.allow_reuse_address = False
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.udp = None
        if peers is not None:  # "where are you?" from a linked computer whose address for this PC is out of date
            try:
                self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp.bind((host, self.port))
                threading.Thread(target=self._answer, daemon=True).start()
            except OSError:
                self.udp = None

    def _answer(self):
        import hmac
        while True:
            try:
                data, (ip, p) = self.udp.recvfrom(512)
            except OSError:  # Windows: an asker gone (reset), a packet too big (10040)... - keep answering
                if self.udp.fileno() == -1:  # closed: the server stopped
                    return
                continue
            w = data.decode(errors="replace").split()
            if not link_private(ip) or len(w) != 4 or w[0] != "CMWHO":
                continue
            entry = self.peers().get(w[1])
            if not entry or self.clock() - float(entry[1]) > PEER_DAYS * 86400:
                continue
            if hmac.compare_digest(w[3].encode("utf-8", "replace"),
                                   peer_sign(entry[0], "WHO", w[1], 0, w[2], "").encode()):
                try:
                    self.udp.sendto(f"CMHERE {self.port} {peer_sign(entry[0], 'HERE', w[1], self.port, w[2], '')}"
                                    .encode(), (ip, p))
                except OSError:
                    pass

    def offer(self, path, peer, secs=600):
        """Let one linked computer download this file (a key it's copying) for a while; the token it uses."""
        import secrets
        import time
        token = secrets.token_hex(16)
        with self.lock:
            self.offers[token] = (Path(path), time.time() + secs, peer)
        return token

    def stop(self):
        """Stop listening; whatever arrived and wasn't accepted is deleted."""
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.udp:
            self.udp.close()
        shutil.rmtree(self.inbox, ignore_errors=True)


# --- linked computers: two Channel Mirrors paired once (pairing code + accepted on both), for PEER_DAYS days.
# Every request between them is signed with the pair secret (HMAC-SHA256 over method, path, time, a one-time nonce
# and the body's hash; replies are signed back), so the secret itself never crosses the network after pairing.
# What one sends the other is a proposal: shown there, and applied only when someone accepts it there.
PEER_DAYS, PEER_SKEW, PEER_ASK = 30, 300, 120  # link lifetime; clock difference allowed (s); wait for an answer (s)


PEER_JSON, PEER_REPLY = 1 << 20, 32 << 20  # largest proposal / reply


PEER_TARGETS = ("import", "vts", "soundboard", "mirror", "files", "edit", "record", "music", "obs")


PEER_SAFE = {SD_PLAY, SD_STOP, SD_FOLDER, SD_PARENT, SD_VTS_HOTKEY, *(u for u in SD_KINDS.values() if u)}


def peer_safe(obj, under=""):
    """The action kinds a key (and everything inside it) carried over the link uses; ValueError if any isn't on
    the allowed list: sounds, Stop audio, Multi / Random Actions, folders, VTube Studio hotkeys. Nothing that can run
    a program, open a website, type or press keys ever arrives from another computer."""
    names = set()
    if isinstance(obj, dict) and under == "Plugin" and set(obj) <= {"Name", "UUID", "Version"}:
        return names  # the plugin's own label (name / id / version), not an action
    if isinstance(obj, dict):
        if "UUID" in obj:
            if obj["UUID"] not in PEER_SAFE:
                raise ValueError(f"A '{peer_name(obj.get('Name') or obj['UUID'])}' key can't come over the link "
                                 "(only sounds, Stop audio, Multi / Random Actions, folders and VTube Studio hotkeys)")
            names.add(peer_name(obj.get("Name") or obj["UUID"]))
        for k, v in obj.items():
            names |= peer_safe(v, k)
    elif isinstance(obj, list):
        for v in obj:
            names |= peer_safe(v, under)
    return names


def peer_images(obj):
    """Every Image a key (or page) names, whatever it looks like (sd_images keeps only plausible ones)."""
    out = set()
    if isinstance(obj, dict):
        for st_ in obj.get("States") if isinstance(obj.get("States"), list) else []:
            if isinstance(st_, dict) and st_.get("Image"):
                out.add(str(st_["Image"]))
        for v in obj.values():
            out |= peer_images(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= peer_images(v)
    return out


def peer_icon_ok(rel):
    """A key icon that may cross the link: a plain picture name inside the page's Images folder."""
    import re
    m = re.fullmatch(r"Images/([\w\- ][\w.\- ]{0,79})\.(png|jpg|jpeg|gif)", str(rel))
    return bool(m) and ".." not in m.group(1) and not re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)", m.group(1).strip())


def peer_plays(obj):
    """How many Play Audio actions are anywhere inside obj."""
    if isinstance(obj, dict):
        return (obj.get("UUID") == SD_PLAY) + sum(peer_plays(v) for v in obj.values())
    return sum(peer_plays(v) for v in obj) if isinstance(obj, list) else 0


def peer_carried(action, pages):
    """Every Play Audio action in a carried key and its folder pages, in one fixed order (sender and receiver agree
    which arriving file each one plays)."""
    out = list(sd_sounds(action))
    for pid in sorted(pages):
        kp = next((c.get("Actions") or {} for c in pages[pid].get("Controllers") or [] if c.get("Type") == "Keypad"),
                  {})
        for k in sorted(kp):
            out += sd_sounds(kp[k])
    return out


def peer_sign(secret, method, target, t, nonce, body_hash):
    """The signature of one request (or reply) between linked computers."""
    import hashlib
    import hmac
    msg = f"{method}\n{target}\n{int(t)}\n{nonce}\n{body_hash}".encode("utf-8", "replace")
    return hmac.new(str(secret).encode(), msg, hashlib.sha256).hexdigest()


# Pairing never sends the code or the secret: both PCs prove they know the code and agree on the secret with SPAKE2
# (RFC 9382's shape) in RFC 3526's 2048-bit MODP group - someone listening learns nothing, and someone in the middle
# without the code gets one guess per try (and the tries are counted). Renewing does the same keyed by the old secret.
PAIR_P = int("FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3"
             "CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5"
             "AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356"
             "208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3BE39E772C180E86039B2783A2EC07A28F"
             "B5C55DF06F4C52C9DE2BCBF6955817183995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFFFFFFFFFF", 16)
PAIR_Q = (PAIR_P - 1) // 2  # prime: 2 generates the subgroup of this order


def pair_point(role):
    """SPAKE2's M (role A) / N (role B): an element of the subgroup whose logarithm nobody knows (a hash, squared)."""
    import hashlib
    h = b"".join(hashlib.sha256(f"channel-mirror pair point {role} {i}".encode()).digest() for i in range(8))
    return pow(int.from_bytes(h, "big") % PAIR_P, 2, PAIR_P)


def pair_code(code):
    import hashlib
    return int.from_bytes(hashlib.sha256(f"channel-mirror pair code\n{code}".encode()).digest(), "big") % PAIR_Q


def pair_offer(code, role):
    """This side's (secret exponent, public value) for role "A" (asks) or "B" (answers); code = what both know."""
    import secrets
    x = secrets.randbelow(PAIR_Q - 1) + 1
    return x, pow(2, x, PAIR_P) * pow(pair_point(role), pair_code(code), PAIR_P) % PAIR_P


def pair_secret(code, role, x, pub_a, pub_b, id_a):
    """(pair secret, proof A, proof B): the same on both sides only when both used the same code (HKDF-SHA256 over
    the whole exchange). ValueError when the other side's value isn't an element of the group."""
    import hashlib
    import hmac
    other, w = int(pub_b if role == "A" else pub_a), pair_code(code)
    if not 1 < other < PAIR_P - 1 or pow(other, PAIR_Q, PAIR_P) != 1:
        raise ValueError("That isn't a pairing answer")
    k = pow(other * pow(pow(pair_point("B" if role == "A" else "A"), w, PAIR_P), -1, PAIR_P) % PAIR_P, x, PAIR_P)
    if k == 1:
        raise ValueError("That isn't a pairing answer")
    seen = hashlib.sha256(f"{id_a}\n{int(pub_a):x}\n{int(pub_b):x}\n{k:x}\n{w:x}".encode()).digest()
    prk = hmac.new(b"channel-mirror pair v2", seen, hashlib.sha256).digest()  # HKDF extract, then one block each
    return tuple(hmac.new(prk, info + b"\x01", hashlib.sha256).hexdigest() for info in (b"secret", b"A", b"B"))


def peer_headers(me, secret, method, target, body_hash, t=None):
    """Headers for one signed request from this PC (pair id me)."""
    import secrets
    import time
    t, nonce = int(time.time()) if t is None else int(t), secrets.token_hex(16)
    return {"X-Peer": me, "X-Time": str(t), "X-Nonce": nonce, "X-Body": body_hash,
            "X-Sig": peer_sign(secret, method, target, t, nonce, body_hash)}


def peer_days_left(peer, now=None):
    """Whole days the link to a linked computer still has (0 = expired: pair again)."""
    import math
    import time
    left = float(peer.get("since", 0)) + PEER_DAYS * 86400 - (time.time() if now is None else now)
    return max(0, math.ceil(left / 86400))


def peer_until(peer):
    import time
    return time.strftime("%d %b %Y", time.localtime(float(peer.get("since", 0)) + PEER_DAYS * 86400))


def peer_name(text, limit=60):
    return "".join(c for c in str(text) if c.isprintable())[:limit].strip()


def peer_call(peer, me, method, path, body=b"", fh=None, size=None, body_hash=None, port=None, timeout=30,
              save=None):
    """One signed request to a linked computer (no proxy, home network only); its reply, checked to be signed with
    the pair secret. save = a file to stream the reply into (checked before it's kept). Raises OSError with the
    other side's reason."""
    import hashlib
    import hmac
    import urllib.request
    from urllib.error import HTTPError
    host = str(peer.get("host", ""))
    if not link_private(host):
        raise ValueError("Linked computers must be on the home network")
    if port:
        path += ("&" if "?" in path else "?") + f"port={int(port)}"
    if body_hash is None:
        body_hash = hashlib.sha256(body).hexdigest()
    h = peer_headers(me, peer["secret"], method, path, body_hash)
    if method == "POST":
        h["Content-Length"] = str(size if fh is not None else len(body))
    req = urllib.request.Request(f"http://{f'[{host}]' if ':' in host else host}:{int(peer['port'])}{path}",
                                 data=(fh if fh is not None else body) if method == "POST" else None,
                                 method=method, headers=h)
    try:
        with link_noproxy().open(req, timeout=timeout) as r:
            sig = r.headers.get("X-Sig", "")
            if save is None:
                out = r.read(PEER_REPLY + 1)
                if len(out) > PEER_REPLY:
                    raise ValueError("The reply was too big")
                got = hashlib.sha256(out).hexdigest()
            else:
                sha, n = hashlib.sha256(), 0
                with open(save, "xb") as f:
                    while chunk := r.read(1 << 20):
                        n += len(chunk)
                        if n > LINK_MAX:
                            break
                        sha.update(chunk)
                        f.write(chunk)
                out, got = save, sha.hexdigest()
    except HTTPError as e:
        raise OSError(f"{peer.get('name') or host}: {e.read(300).decode(errors='replace') or e.reason}") from None
    if save is not None and n > LINK_MAX:
        Path(save).unlink(missing_ok=True)
        raise ValueError("The file was too big")
    if not hmac.compare_digest(sig.encode("utf-8", "replace"),
                               peer_sign(peer["secret"], "REPLY", path, 0, h["X-Nonce"], got).encode()):
        if save is not None:
            Path(save).unlink(missing_ok=True)
        raise OSError("The reply wasn't signed by the linked computer")
    return out


def peer_pair(pair, me, name, port):
    """Pair this PC (pair id me, called name, receiving on port) with the Channel Mirror whose pairing link this is.
    That PC asks its user first. Returns the linked computer {id, name, host, port, secret, since}.
    Neither the code nor the secret crosses the network: both PCs prove the code and agree on the secret (SPAKE2)."""
    import hashlib
    import hmac
    import re
    import secrets
    import time
    import urllib.request
    from urllib.error import HTTPError
    from urllib.parse import parse_qs, urlsplit
    u = urlsplit(str(pair).strip())
    code = (parse_qs(u.query).get("code") or [""])[0]
    if u.scheme != "http" or not u.hostname or not code:
        raise ValueError("That isn't a pairing link (it looks like http://192.168.x.x:8765/?code=12345678)")
    if not link_private(u.hostname):
        raise ValueError("Pairing links only work on the home network")

    def post(path, d, nonce=""):
        body = json.dumps(d).encode()
        req = urllib.request.Request(f"http://{u.netloc}{path}", data=body, method="POST", headers={
            "Content-Length": str(len(body)), **({"X-Nonce": nonce} if nonce else {})})
        try:
            with link_noproxy().open(req, timeout=PEER_ASK + 30) as r:
                out, sig = r.read(4096), r.headers.get("X-Sig", "")
        except HTTPError as e:
            why = e.read(300).decode(errors="replace") or e.reason
            if path == "/pair/start" and "Wrong pairing code" in why:  # it still wants the code sent: older
                why = "That PC's Channel Mirror is older - update it there, then link again."
            raise OSError(why) from None
        try:
            d = json.loads(out)
        except ValueError:
            d = None
        if not isinstance(d, dict):
            raise OSError("The other computer's answer isn't a pairing answer")
        return d, out, sig
    x, pub_a = pair_offer(code, "A")
    d, _, _ = post("/pair/start", {"id": me, "name": peer_name(name), "port": int(port), "pub": f"{pub_a:x}"})
    try:
        secret, proof_a, proof_b = pair_secret(code, "A", x, pub_a, int(str(d.get("pub")), 16), me)
    except ValueError:
        raise OSError("The other computer's answer isn't a pairing answer") from None
    if not hmac.compare_digest(str(d.get("proof", "")).encode("utf-8", "replace"), proof_b.encode()):
        raise OSError("Wrong pairing code - copy the pairing link again from the other PC.")
    nonce = secrets.token_hex(16)
    d, out, sig = post("/pair/finish", {"session": str(d.get("session", "")), "proof": proof_a}, nonce)
    if not hmac.compare_digest(sig.encode("utf-8", "replace"), peer_sign(
            secret, "REPLY", "/pair/finish", 0, nonce, hashlib.sha256(out).hexdigest()).encode()):
        raise OSError("The other computer's answer wasn't signed with the new link")
    if not re.fullmatch(r"[0-9a-f]{32}", str(d.get("id", ""))):
        raise OSError("The other computer sent a bad pair id")
    return {"id": d["id"], "name": peer_name(d.get("name")) or u.hostname, "host": u.hostname,
            "port": u.port or 80, "secret": secret, "since": time.time()}


def peer_hello(peer, me, port=None, timeout=5):
    """The linked computer's own name if it's online and still linked; raises OSError otherwise."""
    return peer_name(json.loads(peer_call(peer, me, "GET", "/peer/hello", port=port, timeout=timeout)).get("name"))


def peer_browse(peer, me, port=None):
    """Its Stream Deck devices and profiles (pages, keys: names and sound file names only) and VTube Studio models."""
    return json.loads(peer_call(peer, me, "GET", "/peer/browse", port=port, timeout=PEER_ASK))


def peer_send(peer, me, files, target, spec, port=None, progress=None, batch=None):
    """Send a proposal: files (in order: proposals point at them by number) + what they're for. Waits there to be
    accepted. progress(i, n) after each file. Returns how many files went."""
    import hashlib
    import secrets
    from urllib.parse import urlencode
    peer_check_files(target, peer_proposal(target, spec, len(files)), files)  # refused here already if the other
    # side wouldn't take it; what goes is the proposal as given (the other side checks it again itself)
    batch = batch or secrets.token_hex(8)
    for i, f in enumerate(map(Path, files)):
        name = link_safe_name(f.name)
        sha = hashlib.sha256()
        with open(f, "rb") as fh:
            while chunk := fh.read(1 << 20):
                sha.update(chunk)
        with open(f, "rb") as fh:
            peer_call(peer, me, "POST", "/peer/upload?" + urlencode({"batch": batch, "name": name}), fh=fh,
                      size=f.stat().st_size, body_hash=sha.hexdigest(), port=port, timeout=120)
        if progress:
            progress(i + 1, len(files))
    peer_call(peer, me, "POST", f"/peer/done?batch={batch}", json.dumps(
        {"target": target, "spec": spec, "files": len(files)}).encode(), port=port)
    return len(files)


def peer_renew(peer, me, port=None):
    """Verify the link again (the other PC asks its user): a new secret (agreed with the old one, never sent) and a
    fresh PEER_DAYS days. The new peer."""
    import time
    x, pub_a = pair_offer(peer["secret"], "A")
    r = json.loads(peer_call(peer, me, "POST", "/peer/renew", json.dumps({"pub": f"{pub_a:x}"}).encode(), port=port,
                             timeout=PEER_ASK + 30))  # its answer is signed with the old secret
    try:
        new = pair_secret(peer["secret"], "A", x, pub_a, int(str(r.get("pub")), 16), me)[0]
    except (ValueError, AttributeError):
        raise OSError("The other computer's answer isn't a renewal (is its Channel Mirror older?)") from None
    return dict(peer, secret=new, since=time.time())


def peer_unlink(peer, me):
    """Tell the linked computer it's unlinked (it forgets this PC)."""
    peer_call(peer, me, "POST", "/peer/unlink", b"{}", timeout=5)


def peer_result(peer, me, batch, ok, note=""):
    """Tell the sender what happened to its proposal here: accepted or declined."""
    peer_call(peer, me, "POST", "/peer/result", json.dumps(
        {"batch": str(batch)[:40], "ok": bool(ok), "note": peer_name(note, 200)}).encode(), timeout=5)


def peer_obs(peer, me, cmd, args=None, timeout=15):
    """An OBS command run on the linked computer's OBS (it must allow this PC there) -> its result; OSError saying
    why not."""
    r = json.loads(peer_call(peer, me, "POST", "/peer/obs", json.dumps({"cmd": cmd, "args": args or {}}).encode(),
                             timeout=timeout))
    if not isinstance(r, dict) or not r.get("ok"):
        raise OSError(f"{peer.get('name') or 'The linked computer'}: {peer_name((r or {}).get('error', ''), 300)}")
    return r.get("result") or {}


def peer_fetch(peer, me, profile, page, page_name, keys):
    """Read keys from a linked computer's page (to copy them here): {"actions": {key: action}, "files": [{"name",
    "token"}], "sounds": {key: [file number per sound]}, "icons": {key: {"Images/x.png": file number}}}."""
    from urllib.parse import urlencode
    q = urlencode({"profile": profile, "page": int(page), "page_name": page_name, "keys": ";".join(keys)})
    return json.loads(peer_call(peer, me, "GET", f"/peer/fetch?{q}", timeout=PEER_ASK))


def peer_library(peer, me):
    """What the linked computer offers to pick from (its outputs, recordings, received files, backgrounds, sounds on
    keys): {group: [{"name", "size", "token"}]}; each picked one is fetched with peer_download."""
    return json.loads(peer_call(peer, me, "GET", "/peer/library", timeout=PEER_ASK))


def peer_pack(acts, by_id, read, page_dir):
    """Keys of this PC packed to go over the link (Key mover / copy to a linked computer): {key: {"action", "pages"
    (its folder pages, folders in folders too), "sounds": [path per carried sound], "icons": {rel: path}}} - the
    key's own icons as "Images/x.png", those of keys inside its folder pages as "<page id>/Images/x.png".
    by_id = {page id: page file} of the profile; read(page file) -> its json. Raises ValueError for a key that may
    not go (a kind outside the allowed list, or a sound file that's missing / not a real sound). acts are
    changed (sound paths become names): pass copies."""
    import copy
    out = {}
    for k, a in acts.items():
        tree = {}

        def walk(x):
            pid = str((x.get("Settings") or {}).get("ProfileUUID", "")).lower()
            if x.get("UUID") != SD_FOLDER or pid in tree or pid not in by_id:
                return
            tree[pid] = copy.deepcopy(read(by_id[pid]))
            for c in tree[pid].get("Controllers") or []:
                for b in (c.get("Actions") or {}).values():
                    if b:
                        walk(b)
        walk(a)
        peer_safe(a)
        peer_safe(tree)
        sounds = [Path(s.get("Settings", {}).get("path", "")) for s in peer_carried(a, tree)]
        for s in peer_carried(a, tree):  # only the name goes: where it lives on this PC is nobody else's business
            s["Settings"]["path"] = Path(s["Settings"].get("path", "")).name
        for f in sounds:
            if not f.is_file():
                raise ValueError(f"{f.name}: the sound file is missing")
            link_check_file(f, LINK_AUDIO)
        icons = {}
        for pre, obj, where in [("", a, Path(page_dir))] + [(f"{pid}/", pg, Path(by_id[pid]).parent)
                                                            for pid, pg in tree.items()]:
            for rel in sd_images(obj):
                f = where / rel
                try:
                    if not peer_icon_ok(rel) or not f.resolve().is_relative_to(where.resolve()):
                        continue  # only icons in the page's own Images folder ever go
                    icons[pre + rel] = link_check_file(f, LINK_IMAGES)
                except (ValueError, OSError):
                    pass  # a missing / odd icon: the key goes without it
        out[k] = {"action": a, "pages": tree, "sounds": sounds, "icons": icons}
    return out


def peer_put_ops(packed, places, page, page_name):
    """packed keys (peer_pack) -> (put changes for a proposal, the files they point at, in order)."""
    files, ops = [], []

    def num(f):
        files.append(f)
        return len(files) - 1
    for k, to in places.items():
        if to and k in packed:
            p = packed[k]
            ops.append({"op": "put", "page": page, "page_name": page_name, "key": to, "action": p["action"],
                        "pages": p["pages"], "sounds": [num(f) for f in p["sounds"]],
                        "icons": {r: num(f) for r, f in p["icons"].items()}})
    return ops, files


def library_items(groups, exts=None, query=""):
    """What the "From Channel Mirror..." picker lists: [(group, path, exists)] from {group: [paths]} - only the
    types the tool takes, each file once per group, in natural order, the names matching the search."""
    q, out = str(query).strip().lower(), []
    for g, paths in groups.items():
        seen = set()
        for p in sorted(map(Path, paths), key=natural):
            if p in seen or (exts and p.suffix.lower() not in exts) or (q and q not in p.name.lower()):
                continue
            seen.add(p)
            out.append((g, p, p.is_file()))
    return out


def link_default_target(files):
    """Where files sent to a linked computer go unless chosen otherwise: pictures -> VTube Studio backgrounds, sounds
    -> Import to folders, mp4s (recordings) -> kept as files, other videos -> Channel Mirror."""
    ext = {Path(f).suffix.lower() for f in files}
    if ext and ext <= {".png", ".jpg", ".jpeg"}:
        return "vts"
    if ext and ext <= set(AUDIO_EXT):
        return "import"
    return "files" if ext == {".mp4"} else "mirror"


def library_files(folder, exts, limit=2000):
    """The files of these types in a folder (and the folders inside it), up to limit."""
    out = []
    try:
        for p in Path(folder).rglob("*"):
            if p.suffix.lower() in exts and p.is_file():
                out.append(p)
                if len(out) >= limit:
                    break
    except OSError:
        pass
    return out


def peer_download(peer, me, token, dst):
    """One file a fetch offered, into dst (a new file); checked against the linked computer's signature."""
    from urllib.parse import quote
    return peer_call(peer, me, "GET", f"/peer/file?token={quote(str(token), safe='')}", save=dst, timeout=120)


def peer_find(peer, me, addrs=None, timeout=2.0):
    """Look for a linked computer whose address changed: a UDP question on the home network that only it can answer
    (with the pair secret). (address, port) or None."""
    import hmac
    import secrets
    import socket
    import time
    nonce = secrets.token_hex(16)
    msg = f"CMWHO {me} {nonce} {peer_sign(peer['secret'], 'WHO', me, 0, nonce, '')}".encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for a in addrs or [("255.255.255.255", int(peer.get("port") or LINK_PORT)), ("255.255.255.255", LINK_PORT)]:
            try:
                s.sendto(msg, a)
            except OSError:
                pass
        end = time.time() + timeout
        while time.time() < end:
            s.settimeout(max(0.05, end - time.time()))
            try:
                data, (ip, _) = s.recvfrom(512)
            except socket.timeout:
                break
            except OSError:  # Windows: another address we asked had nobody there (reset) - wait for the right one
                continue
            p = data.decode(errors="replace").split()
            if len(p) == 3 and p[0] == "CMHERE" and p[1].isdigit() and link_private(ip) and hmac.compare_digest(
                    p[2].encode(), peer_sign(peer["secret"], "HERE", me, int(p[1]), nonce, "").encode()):
                return ip, int(p[1])
    finally:
        s.close()
    return None


LINK_SIGS = {  # what a file of each type over the link must start with (its real content, not just its name)
    "riff": lambda h: h[:4] == b"RIFF" and h[8:12] == b"WAVE", "avi": lambda h: h[:4] == b"RIFF" and h[8:12] == b"AVI ",
    "mpa": lambda h: h[:3] == b"ID3" or (len(h) > 1 and h[0] == 0xFF and h[1] & 0xE0 == 0xE0),
    "flac": lambda h: h[:4] == b"fLaC" or h[:3] == b"ID3", "ogg": lambda h: h[:4] == b"OggS",
    "iso": lambda h: h[4:8] == b"ftyp", "aiff": lambda h: h[:4] == b"FORM" and h[8:12] in (b"AIFF", b"AIFC"),
    "asf": lambda h: h[:16] == bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c"),
    "ebml": lambda h: h[:4] == b"\x1aE\xdf\xa3", "flv": lambda h: h[:3] == b"FLV",
    "mpg": lambda h: h[:4] in (b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3"), "ts": lambda h: h[:1] == b"G" or h[4:5] == b"G",
    "caf": lambda h: h[:4] == b"caff", "amr": lambda h: h[:5] == b"#!AMR", "au": lambda h: h[:4] == b".snd",
    "png": lambda h: h[:8] == b"\x89PNG\r\n\x1a\n", "jpg": lambda h: h[:3] == b"\xff\xd8\xff",
    "gif": lambda h: h[:6] in (b"GIF87a", b"GIF89a"), "rf64": lambda h: h[:4] in (b"RF64", b"riff"),
    "wv": lambda h: h[:4] == b"wvpk", "ape": lambda h: h[:4] == b"MAC "}


LINK_TYPES = {".wav": "riff", ".mp3": "mpa", ".mp2": "mpa", ".aac": "mpa", ".flac": "flac", ".ogg": "ogg",
              ".oga": "ogg", ".opus": "ogg", ".spx": "ogg", ".ogv": "ogg", ".m4a": "iso", ".m4b": "iso",
              ".mp4": "iso", ".mov": "iso", ".m4v": "iso", ".3gp": "iso", ".3g2": "iso", ".f4v": "iso",
              ".aiff": "aiff", ".aif": "aiff", ".aifc": "aiff", ".wma": "asf", ".wmv": "asf", ".asf": "asf",
              ".mka": "ebml", ".mkv": "ebml", ".webm": "ebml", ".avi": "avi", ".flv": "flv", ".mpg": "mpg",
              ".mpeg": "mpg", ".ts": "ts", ".mts": "ts", ".m2ts": "ts", ".caf": "caf", ".amr": "amr", ".au": "au",
              ".snd": "au", ".w64": "rf64", ".rf64": "rf64", ".wv": "wv", ".ape": "ape", ".png": "png", ".jpg": "jpg",
              ".jpeg": "jpg", ".gif": "gif"}


LINK_AUDIO = tuple(e for e in AUDIO_EXT if e in LINK_TYPES)


LINK_IMAGES = (".png", ".jpg", ".jpeg", ".gif")


LINK_CAP = {"audio": 500 * 1024 ** 2, "image": 20 * 1024 ** 2, "video": LINK_MAX}


PEER_FILES = {"soundboard": LINK_AUDIO, "import": LINK_AUDIO, "edit": LINK_AUDIO, "files": (".mp4",), "record": (),
              "mirror": LINK_AUDIO + tuple(e for e in VIDEO_EXT if e in LINK_TYPES), "vts": VTS_EXT, "music": LINK_AUDIO,
              "obs": LINK_AUDIO + tuple(e for e in VIDEO_EXT if e in LINK_TYPES) + LINK_IMAGES}


def link_check_file(path, allowed=None):
    """Refuse (ValueError, naming the file and why) a file whose type isn't allowed here, whose content isn't really
    that type (checked from its first bytes), or that's bigger than its type may be."""
    f = Path(path)
    ext = f.suffix.lower()
    if ext not in LINK_TYPES or (allowed is not None and ext not in allowed):
        raise ValueError(f"{f.name}: {ext or 'no type'} files don't go there")
    with open(f, "rb") as fh:
        head = fh.read(32)
    if not LINK_SIGS[LINK_TYPES[ext]](head):
        raise ValueError(f"{f.name}: its content isn't a {ext} file")
    kind = "image" if ext in LINK_IMAGES else "audio" if ext in AUDIO_EXT else "video"
    if f.stat().st_size > LINK_CAP[kind]:
        raise ValueError(f"{f.name}: too big for a {kind} file ({f.stat().st_size // 1024 ** 2} MB)")
    return f


def peer_check_files(target, spec, files):
    """Every file of a proposal is of a type its destination uses (keys: sounds, plus icons with their key) and
    really is that type; ValueError naming each refused file and why."""
    allowed = [PEER_FILES[target]] * len(files)
    sounds = {i for o in spec.get("ops") or [] for i in o.get("sounds", []) + o.get("files", [])}
    for o in spec.get("ops") or []:
        for i in o.get("icons", {}).values():
            if i in sounds:
                raise ValueError("One file can't be both a sound and an icon")
            allowed[i] = LINK_IMAGES
    bad = []
    for f, ok in zip(files, allowed):
        try:
            link_check_file(f, ok)
        except (ValueError, OSError) as e:
            bad.append(str(e))
    if bad:
        raise ValueError("; ".join(bad[:10]) + (f" (and {len(bad) - 10} more)" if len(bad) > 10 else ""))


def peer_proposal(target, spec, n):
    """A proposal checked against its strict form (ValueError otherwise, saying what's wrong): a known destination,
    known fields only, each of the right type and length. n = files that come with it; a proposal points at them by
    number - paths are never part of one (the receiving PC decides where things go), and every file is used."""
    import re
    if target not in PEER_TARGETS or not isinstance(spec, dict):
        raise ValueError(f"Unknown request '{peer_name(target, 30)}'")
    used = set()

    def only(d, *fields):
        if not isinstance(d, dict):
            raise ValueError("A part of the proposal isn't the right shape")
        extra = [k for k in d if k not in fields]
        if extra:
            raise ValueError(f"Unknown field '{peer_name(extra[0], 30)}' in the proposal")
        return d

    def text(x, limit=200, empty=True, path_ok=True):
        if not isinstance(x, str) or not x.isprintable() or (not empty and not x.strip()):
            raise ValueError("A name in the proposal isn't plain text")
        if len(x) > limit:
            raise ValueError(f"A name in the proposal is too long ({len(x)} characters, {limit} at most)")
        if not path_ok and re.search(r"[\\/:]", x):
            raise ValueError("A name in the proposal looks like a path")
        return x

    def num(x, lo, hi):
        if not isinstance(x, int) or isinstance(x, bool) or not lo <= x <= hi:
            raise ValueError("A number in the proposal is out of range")
        return x

    def flag(x):
        if not isinstance(x, bool):
            raise ValueError("A yes / no in the proposal isn't yes or no")
        return x

    def key(x):
        if not isinstance(x, str) or not re.fullmatch(r"\d{1,2},\d{1,2}", x):
            raise ValueError("A key in the proposal isn't a key")
        return x

    def file(i):
        used.add(num(i, 0, n - 1))
        return i

    def files(x, limit=200):
        if not isinstance(x, list) or not 0 < len(x) <= limit:
            raise ValueError("A key in the proposal has no files")
        return [file(i) for i in x]

    def done(out):
        if len(used) != n and target in ("edit", "soundboard"):
            raise ValueError("Files came that the proposal doesn't use")
        if target == "record" and n:
            raise ValueError("Files can't come with a recording request")
        return out
    if target == "obs":  # files for OBS there: one into a source it has, or new sources in one of its scenes
        only(spec, "input", "scene", "name")
        if spec.get("input") is not None:
            if set(spec) != {"input"} or n != 1:
                raise ValueError("One file goes into an OBS source")
            return done({"input": text(spec["input"], 256, False)})
        if set(spec) != {"scene", "name"} or not 0 < n <= 20:
            raise ValueError("New OBS sources need a scene and a name (20 files at most)")
        return done({"scene": text(spec["scene"], 256, False), "name": text(spec["name"], 200, False)})
    if target in ("import", "files", "mirror", "vts", "record", "music"):
        if target in ("import", "files"):
            return done(only(spec) and {})
        if target == "music":  # songs for its Music player, as a new playlist with this name (or the one open)
            only(spec, "playlist")
            return done({"playlist": text(spec["playlist"], 60, False, False)} if spec.get("playlist") else {})
        if target == "record":
            only(spec, "action")
            if spec.get("action") not in ("start", "stop"):
                raise ValueError("A recording can only be started or stopped")
            return done({"action": spec["action"]})
        if target == "vts":
            only(spec, "model", "hotkeys", "apply")
            out = {"model": text(spec["model"], 200, path_ok=False)} if spec.get("model") else {}
            out.update({k: flag(spec[k]) for k in ("hotkeys", "apply") if k in spec})
            return done(out)
        s, out = only(spec, "settings").get("settings") or {}, {}
        only(s, "sources", "targets", "output_type", "length", "loop", "quiet", "split", "parts")
        for k, ok in (("sources", SOURCES), ("targets", tuple(TARGETS.values()))):
            if k in s:
                if not isinstance(s[k], list) or len(s[k]) > len(ok) or any(x not in ok for x in s[k]):
                    raise ValueError(f"Unknown {k[:-1]} in the settings")
                out[k] = s[k]
        if "output_type" in s:
            if s["output_type"] not in OUTPUT_TYPES.values():
                raise ValueError("Unknown output type")
            out["output_type"] = s["output_type"]
        if "length" in s:
            parse_time(text(s["length"], 20))
            out["length"] = s["length"]
        out.update({k: flag(s[k]) for k in ("loop", "quiet", "split") if k in s})
        if "parts" in s:
            if not re.fullmatch(r"\d{0,4}", text(s["parts"], 4)):
                raise ValueError("Parts must be a number")
            out["parts"] = s["parts"]
        return done({"settings": out})
    if target == "soundboard":  # sounds for its soundboard tab; install = then into its Stream Deck as a new profile
        snd = only(spec, "sounds", "install", "name").get("sounds")
        if not isinstance(snd, list) or not 0 < len(snd) <= 1000:
            raise ValueError("No sounds in the proposal")
        out = []
        for s in snd:
            only(s, "file", "key", "title", "mode", "fade", "fade_len", "volume")
            if s.get("mode", SD_MODES[0]) not in SD_MODES or s.get("fade", SD_FADES[0]) not in SD_FADES:
                raise ValueError("Unknown playback setting in the proposal")
            out.append({"file": file(s.get("file")), "key": key(s["key"]) if s.get("key") else "",
                        "title": text(s.get("title", ""), 60), "mode": s.get("mode", SD_MODES[0]),
                        "fade": s.get("fade", SD_FADES[0]), "fade_len": num(s.get("fade_len", 1), 0, 60),
                        "volume": num(s.get("volume", 100), 0, 100)})
        if "name" in spec and spec.get("install") is not True:
            raise ValueError("A profile name only comes with installing it")
        if not flag(spec.get("install", False)):
            return done({"sounds": out})
        return done({"sounds": out, "install": True, "name": text(spec.get("name") or "Soundboard", 60, False, False)})
    # edit: changes to keys on one profile there
    ops = only(spec, "profile", "ops").get("ops")
    if not isinstance(ops, list) or not 0 < len(ops) <= 500:
        raise ValueError("No changes in the proposal")
    out = []
    fields = {"sounds": ("files", "title"), "title": ("title",), "clear": (), "put": ("action", "pages", "sounds",
                                                                                         "icons")}
    for o in ops:
        if not isinstance(o, dict) or o.get("op") not in fields:
            raise ValueError(f"Unknown change '{peer_name(o.get('op') if isinstance(o, dict) else o, 30)}'")
        only(o, "op", "page", "page_name", "key", *fields[o["op"]])
        c = {"op": o["op"], "page": num(o.get("page"), 0, 9999), "page_name": text(o.get("page_name"), 200, False),
             "key": key(o.get("key"))}
        if o["op"] == "sounds":
            c.update(files=files(o.get("files")), title=text(o.get("title", ""), 60))
        elif o["op"] == "title":
            c["title"] = text(o.get("title"), 60)
        elif o["op"] == "put":  # a whole key copied from the other PC (Key mover): sounds, icons, folder pages
            a, pages = o.get("action"), o.get("pages") or {}
            if (not isinstance(a, dict) or not isinstance(pages, dict) or len(json.dumps([a, pages])) > 2_000_000
                    or any(not re.fullmatch(r"[\w-]{1,64}", str(k)) or not isinstance(v, dict)
                           for k, v in pages.items())):
                raise ValueError("That key can't be carried over the link (too big, or not a key)")
            if a.get("UUID") == SD_PARENT:
                raise ValueError("A folder's back key stays where it is")
            acts = [a] + [x for pg in pages.values() for c in pg.get("Controllers") or [] if isinstance(c, dict)
                          for x in (c.get("Actions") or {}).values() if x]
            if any(not isinstance(x, dict) or "UUID" not in x for x in acts):
                raise ValueError("That key isn't a Stream Deck key")
            kinds = peer_safe(a) | peer_safe(pages)  # checked here, on the receiving side
            if any(not peer_icon_ok(r) for r in peer_images(a) | peer_images(pages)):
                raise ValueError("A key's icon isn't a plain picture name in its Images folder")
            if peer_plays([a, pages]) != len(peer_carried(a, pages)):
                raise ValueError("A sound inside that key isn't where a key's sounds go")
            snd = o.get("sounds") or []
            if not isinstance(snd, list) or len(snd) != len(peer_carried(a, pages)):
                raise ValueError("A key's sounds didn't come with it")
            icons, pl = o.get("icons") or {}, {str(k).lower(): v for k, v in pages.items()}
            if not isinstance(icons, dict):
                raise ValueError("A key's icon isn't one it shows")

            def icon(r):  # the key's own "Images/x.png", or "<page id>/Images/x.png" of a key on one of its folder pages
                pid, _, rel = ("", "", r) if r.startswith("Images/") else r.partition("/")
                pid = pid.lower()
                if not peer_icon_ok(rel) or (pid and pid not in pl) or rel not in sd_images(pl[pid] if pid else a):
                    raise ValueError("A key's icon isn't one it shows")
                return f"{pid}/{rel}" if pid else rel
            c.update(action=a, pages=pl, kinds=sorted(kinds), sounds=[file(i) for i in snd],
                     icons={icon(r): file(i) for r, i in icons.items()})
        out.append(c)
    return done({"profile": text(spec.get("profile"), 200, False), "ops": out})


def peer_summary(target, spec, files):
    """Plain lines for the accept prompt: what the proposal would do here."""
    names = [Path(f).name for f in files]
    if target == "edit":
        ops = spec["ops"]
        where = list(dict.fromkeys(o["page_name"] for o in ops))
        out = [f"{len({(o['page'], o['key']) for o in ops})} key(s) on {spec['profile']}, {', '.join(where)}:"]
        for o in ops:
            c, r = (int(x) + 1 for x in o["key"].split(","))
            k = f"  {o['page_name'] + ' ' if len(where) > 1 else ''}key {c},{r}: "
            if o["op"] == "sounds":
                fs = [names[i] for i in o["files"]]
                out.append(k + f"{len(fs)} sound(s) ({', '.join(fs[:4])}{' ...' if len(fs) > 4 else ''})" +
                           (f", named '{o['title']}'" if o["title"] else ""))
            elif o["op"] == "title":
                out.append(k + f"name it '{o['title']}'")
            elif o["op"] == "put":
                fp = (f", {len(o['pages'])} folder page(s)" if o["pages"] else "") + (
                    f", {len(o['icons'])} icon(s)" if o["icons"] else "")
                out.append(k + f"a copied key: {sd_title(o['action']) or sd_kind(o['action'])} ({len(o['sounds'])} "
                               f"sound(s){fp}) - uses: {', '.join(o['kinds'])}")
            else:
                out.append(k + "clear it")
        return out + ["Then it's sent to Stream Deck here (closed and reopened for a moment; a backup first)."]
    if target == "record":
        return [f"{'Start' if spec['action'] == 'start' else 'Stop'} a recording on this PC (the Screen recorder "
                "tab's area and settings)."]
    if target == "obs":
        return [f"{len(files)} file(s) for OBS: {', '.join(names[:6])}" + (" ..." if len(names) > 6 else ""),
                f"Into the OBS source '{spec['input']}'" if spec.get("input") else
                f"As new source(s) named '{spec['name']}' in the OBS scene '{spec['scene']}'",
                "They're kept in the Incoming / Received folder on this PC; OBS shows them from there."]
    out = [f"{len(files)} file(s) for {LINK_TARGETS.get(target, target)}: {', '.join(names[:6])}"
           + (" ..." if len(names) > 6 else "")]
    if spec.get("model"):
        out.append(f"VTube Studio model: {spec['model']}" + (" - added to VTube Studio straight away" if
                                                              spec.get("apply") else ""))
    if spec.get("hotkeys"):
        out.append("Then this PC's VTube Studio tab sets them up: copied into its Backgrounds, a Change Background "
                   f"hotkey each on the model {spec.get('model') or 'picked here'} (if this PC has it, else the one "
                   "picked here) and a Stream Deck key each - it will close and reopen VTube Studio for a moment if "
                   "it's running (the model file is backed up first).")
    if spec.get("sounds"):
        out.append(f"{len(spec['sounds'])} sound(s) with their keys and playback settings")
    if spec.get("install"):
        out.append(f"Then installed into Stream Deck here as a new profile '{spec['name']}' (this PC's deck): Stream "
                   "Deck closes and reopens for a moment, a backup first.")
    if spec.get("playlist"):
        out.append(f"As a new playlist: {spec['playlist']}")
    s = spec.get("settings") or {}
    if s:
        out.append("Settings: " + ", ".join(f"{k} {'/'.join(v) if isinstance(v, list) else v}" for k, v in s.items()))
    return out


def peer_apply(kp, ops, files, new_page=None):
    """Apply a proposal's key changes to one page's key map (only ever called after it was accepted here).
    new_page(page id, json) receives the folder pages a carried folder key brings (copied, with new ids)."""
    import copy

    def title(a, t):
        if not a.get("States"):
            a["States"] = [{}]
        for x in a["States"]:
            x["Title"] = t
    for o in ops:
        k = o["key"]
        if o["op"] == "clear":
            kp.pop(k, None)
        elif o["op"] == "title":
            if kp.get(k):
                title(kp[k], o["title"])
        elif o["op"] == "put":
            a, pages = sd_renew(copy.deepcopy(o["action"])), copy.deepcopy(o.get("pages") or {})
            for s, i in zip(peer_carried(a, pages), o["sounds"]):
                s.setdefault("Settings", {})["path"] = str(files[i])  # where it arrived here, never a path from there
            for pid, pg in sd_clone_folders(a, pages).items():  # its own new folder pages here
                if new_page:
                    new_page(pid, pg)
            kp[k] = a
        else:
            paths, a = [files[i] for i in o["files"]], kp.get(k)
            if a and sd_sounds(a):
                kp[k] = sd_add_sounds(a, sd_plays_like(paths, sd_sounds(a)[0]), "Random Action")
            else:
                plays = sd_plays_like(paths)
                kp[k] = plays[0] if len(plays) == 1 else sd_wrap("Random Action", o["title"], plays)
            if o["title"]:
                title(kp[k], o["title"])
    return kp


def peer_key(a):
    """A key as a linked computer sees it when browsing: its name, kind and sound file names (no paths)."""
    return {"title": sd_title(a), "kind": sd_kind(a), "sounds": [Path(s.get("Settings", {}).get("path", "")).name
                                                                for s in sd_sounds(a)]}


def link_token():
    """The secret the open app and a newly clicked link share (so other programs can't hand links over)."""
    import secrets
    f = FFMPEG_DIR.parent / "link.token"
    try:
        t = f.read_text().strip()
        if len(t) >= 32:
            return t
    except OSError:
        pass
    f.parent.mkdir(parents=True, exist_ok=True)
    t = secrets.token_hex(24)
    tmp = f.with_name(f"link.token.{secrets.token_hex(4)}")
    tmp.write_text(t)
    os.replace(tmp, f)  # never half-written
    return f.read_text().strip()


def link_handover(link, port=LINK_HANDOVER):
    """Give a clicked channelmirror:// link to the Channel Mirror that's already open; False if none is."""
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/link", data=str(link).encode(), method="POST",
                                     headers={"X-Token": link_token()})
        return link_noproxy().open(req, timeout=3).status == 200
    except OSError:
        return False


def link_handover_serve(on_link, port=LINK_HANDOVER):
    """While the app is open: take links handed over by link_handover (this PC only, with the token).
    on_link(text) is called from the server's thread. Returns the server (shutdown() to stop) or None if taken."""
    import hmac
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    token = link_token()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                size = 0
            ok = (self.path == "/link" and hmac.compare_digest(
                self.headers.get("X-Token", "").encode("utf-8", "replace"), token.encode()) and 0 < size < 100_000)
            if ok:
                on_link(self.rfile.read(int(self.headers["Content-Length"])).decode(errors="replace"))
            self.send_response(200 if ok else 403)
            self.end_headers()
    try:
        ThreadingHTTPServer.allow_reuse_address = False
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:  # another copy has it
        return None
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def link_fetch(url, folder):
    """Download a web address from a link into folder (a sound / video / picture, up to LINK_MAX); the file."""
    import socket
    import urllib.request
    from urllib.parse import unquote, urlsplit

    def public(u):
        p = urlsplit(u)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ValueError("only http / https downloads")
        for *_, addr in socket.getaddrinfo(p.hostname, p.port or 443):
            if link_private(addr[0]) or addr[0].startswith(("169.254.", "0.", "fe80")):
                raise ValueError(f"{p.hostname} is on this PC / network - links only download from the internet")

    class Check(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            public(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    public(url)
    name = link_safe_name(unquote(urlsplit(url).path.rsplit("/", 1)[-1]))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / name
    req = urllib.request.Request(url, headers={"User-Agent": "ChannelMirror"})
    with urllib.request.build_opener(Check).open(req, timeout=60) as r, open(dst, "wb") as out:
        got = 0
        while chunk := r.read(1 << 20):
            got += len(chunk)
            if got > LINK_MAX:
                raise ValueError("too big")
            out.write(chunk)
    return dst
