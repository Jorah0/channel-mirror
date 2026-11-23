"""OBS: a websocket client for OBS on this PC (obs-websocket 5), and the fixed list of commands Channel Mirror runs there."""
import base64
import hashlib
import json
import os
import re
import socket
import struct
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from .link import link_private


OBS_HOST, OBS_PORT = "127.0.0.1", 4455  # OBS > Tools > WebSocket Server Settings


OBS_FEED_PORT = 8767  # the soundboard feed's link (the music stream's is MUSIC_PORT)


WS_GUID, WS_MAX = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11", 4 << 20  # RFC 6455; the largest message taken


OBS_MEDIA = {a: f"OBS_WEBSOCKET_MEDIA_INPUT_ACTION_{a.upper()}" for a in ("play", "pause", "restart", "stop")}


OBS_OUTPUTS = {"stream": ("StartStream", "StopStream", "GetStreamStatus"),
               "record": ("StartRecord", "StopRecord", "GetRecordStatus"),
               "vcam": ("StartVirtualCam", "StopVirtualCam", "GetVirtualCamStatus")}


OBS_MEDIA_KINDS, OBS_IMAGE_KINDS = ("ffmpeg_source", "vlc_source"), ("image_source",)


OBS_IMAGES = (".png", ".jpg", ".jpeg", ".gif")


def ws_mask(data, key):
    """XOR data with the 4-byte key, repeated (a masked frame's payload, both ways)."""
    n = len(data)
    return (int.from_bytes(data, "big") ^ int.from_bytes((key * (n // 4 + 1))[:n], "big")).to_bytes(n, "big")


def ws_frame(op, payload=b"", mask=True):
    """One whole RFC 6455 frame. A client's frames are masked; a server's never are."""
    n = len(payload)
    head = bytes([0x80 | op, (0x80 if mask else 0) | (n if n < 126 else 126 if n < 65536 else 127)])
    head += struct.pack(">H", n) if 126 <= n < 65536 else struct.pack(">Q", n) if n >= 65536 else b""
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + ws_mask(payload, key)


def ws_read(recv, on_control=None, masked=None, limit=WS_MAX):
    """One whole message -> (opcode, payload); recv(n) returns exactly n bytes. Fragments are joined; a ping / pong
    in between goes to on_control(op, payload); a close is returned as it is (8, payload). masked=True: every frame
    must be masked (a server reading a client), False: none may be. ValueError for anything that breaks the rules."""
    op0, parts, size = None, [], 0
    for _ in range(10000):  # frames for one message (empty fragments / pings forever: refused)
        b0, b1 = recv(2)
        fin, op, n = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
        if b0 & 0x70 or op not in (0, 1, 2, 8, 9, 10):
            raise ValueError("not a websocket frame")
        if masked is not None and bool(b1 & 0x80) != masked:
            raise ValueError("wrongly masked frame")
        if n == 126:
            n = struct.unpack(">H", recv(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", recv(8))[0]
        if op >= 8 and (n > 125 or not fin):
            raise ValueError("bad control frame")
        if (size if op >= 8 else size + n) > limit or n > limit:
            raise ValueError("message too big")
        key = recv(4) if b1 & 0x80 else None
        data = recv(n) if n else b""
        if key:
            data = ws_mask(data, key)
        if op >= 8:
            if op == 8:
                return 8, data
            if on_control:
                on_control(op, data)
            continue
        if (op == 0) == (op0 is None):
            raise ValueError("fragments out of order")
        op0, size = op0 or op, size + n
        parts.append(data)
        if fin:
            return op0, b"".join(parts)
    raise ValueError("too many frames for one message")


def obs_auth(password, salt, challenge):
    """obs-websocket 5's answer to its challenge: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class ObsError(Exception):
    """OBS refused or didn't answer; the text says why (in words a user can act on)."""


class ObsClient:
    """A connection to OBS's websocket server (obs-websocket 5: OBS 28 or later) on this PC. It connects by itself
    and again after a drop (every 1 - 10 s) until close(); a wrong password stops it (self.error says so).
    request(type, data) -> the response's data (ObsError when refused / not connected / no answer in time).
    on_event(type, data) and on_status(connected, text) are called from its thread."""

    def __init__(self, host, port, password="", on_event=None, on_status=None, timeout=5.0):
        self.host, self.port, self.password, self.timeout = str(host), int(port), str(password or ""), timeout
        self.on_event, self.on_status = on_event, on_status
        self.lock, self.waits, self.sock, self.buf = threading.Lock(), {}, None, bytearray()
        self.connected, self.closed, self.error, self.version = False, False, "", ""
        threading.Thread(target=self._keep, daemon=True).start()

    def request(self, rtype, data=None, timeout=None):
        import secrets
        if not self.connected:
            raise ObsError(self.error or "Not connected to OBS")
        rid, ev, box = secrets.token_hex(8), threading.Event(), {}
        self.waits[rid] = (ev, box)
        try:
            self._send(1, json.dumps({"op": 6, "d": {"requestType": rtype, "requestId": rid,
                                                       "requestData": data or {}}}).encode())
            if not ev.wait(timeout or self.timeout):
                raise ObsError(f"OBS didn't answer ({rtype})")
        except OSError as e:
            raise ObsError(f"Lost the connection to OBS: {e}") from None
        finally:
            self.waits.pop(rid, None)
        if "d" not in box:
            raise ObsError("Lost the connection to OBS")
        st = box["d"].get("requestStatus")
        st = st if isinstance(st, dict) else {}
        if st.get("result") is not True:
            raise ObsError(f"OBS: {str(st.get('comment') or 'refused')[:300]} ({rtype}, code {st.get('code')})")
        out = box["d"].get("responseData")
        return out if isinstance(out, dict) else {}

    def close(self):
        self.closed = True
        self._drop()

    # --- the connection, on its own thread ---
    def _status(self, on, text):
        self.connected = on
        if self.on_status:
            self.on_status(on, text)

    def _keep(self):
        delay = 1.0
        while not self.closed:
            try:
                self._connect()
                delay = 1.0
                self.error = ""
                self._status(True, f"Connected to OBS {self.version} on {self.host}:{self.port}")
                self._listen()
                why = "OBS closed the connection"
            except ObsError as e:  # wrong password: trying again won't help
                self.error = str(e)
                self._drop()
                return self._status(False, self.error)
            except Exception as e:  # a drop, or anything odd from that port: never a dead connection left open
                why = str(e)[:200] or type(e).__name__
            self._drop()
            if self.closed:
                return self._status(False, "Disconnected")
            self.error = f"Not connected to OBS ({why}) - trying again..."
            self._status(False, self.error)
            end = time.time() + delay
            while time.time() < end and not self.closed:
                time.sleep(0.1)
            delay = min(delay * 2, 10.0)

    def _recv(self, n):
        while len(self.buf) < n:
            c = self.sock.recv(max(65536, n - len(self.buf)))
            if not c:
                raise OSError("OBS closed the connection")
            self.buf += c
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def _send(self, op, payload):
        with self.lock:
            if not self.sock:
                raise OSError("not connected")
            self.sock.sendall(ws_frame(op, payload))

    def _control(self, op, data):
        if op == 9:  # ping -> pong
            self._send(10, data)

    def _message(self):
        op, data = ws_read(self._recv, self._control, masked=False)
        if op == 8:
            code = struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 1005
            if code == 4009:
                raise ObsError("Wrong password - copy it from OBS > Tools > WebSocket Server Settings > "
                               "Show Connect Info")
            raise OSError(f"OBS closed the connection ({code} {data[2:].decode(errors='replace')[:100]})".strip())
        if op != 1:
            raise ValueError("OBS sent something that isn't text")
        m = json.loads(data)
        if not isinstance(m, dict) or not isinstance(m.get("d"), dict):
            raise ValueError("OBS sent something odd")
        return m.get("op"), m["d"]

    def _connect(self):
        import secrets
        self.buf = bytearray()
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock = s
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        s.sendall((f"GET / HTTP/1.1\r\nHost: {self.host}:{self.port}\r\nUpgrade: websocket\r\nConnection: Upgrade"
                   f"\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                   "Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n").encode())
        while b"\r\n\r\n" not in self.buf:
            if len(self.buf) > 16384:
                raise ValueError("not a websocket server")
            c = s.recv(4096)
            if not c:
                raise OSError("closed before answering")
            self.buf += c
        head, rest = bytes(self.buf).split(b"\r\n\r\n", 1)
        self.buf = bytearray(rest)
        lines = head.decode("latin-1").split("\r\n")
        hdr = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
        want = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if not lines[0].startswith("HTTP/1.1 101") or hdr.get("sec-websocket-accept") != want:
            raise ValueError("that port isn't OBS's websocket server")
        op, d = self._message()
        if op != 0:
            raise ValueError("OBS didn't say hello")
        self.version = str(d.get("obsStudioVersion", ""))[:20]
        ident = {"rpcVersion": 1, "eventSubscriptions": 1 | 4 | 8 | 64 | 128 | 256}  # general .. media inputs
        auth = d.get("authentication")
        if isinstance(auth, dict):
            if not self.password:
                raise ObsError("OBS asks for a password - copy it from OBS > Tools > WebSocket Server Settings > "
                               "Show Connect Info")
            ident["authentication"] = obs_auth(self.password, str(auth.get("salt", "")),
                                               str(auth.get("challenge", "")))
        self._send(1, json.dumps({"op": 1, "d": ident}).encode())
        op, d = self._message()
        if op != 2:
            raise ValueError("OBS didn't accept Channel Mirror")
        s.settimeout(None)  # from now on: waits as long as OBS is quiet (close() ends it)
        self.connected = True

    def _listen(self):
        while not self.closed:
            op, d = self._message()
            if op == 7:
                w = self.waits.get(str(d.get("requestId")))
                if w:
                    w[1]["d"] = d
                    w[0].set()
            elif op == 5 and self.on_event:
                try:
                    self.on_event(str(d.get("eventType", "")), d.get("eventData") or {})
                except Exception:
                    pass

    def _drop(self):
        self.connected = False
        with self.lock:
            s, self.sock = self.sock, None
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()
        for ev, _ in list(self.waits.values()):
            ev.set()  # whoever waits: no answer is coming


# --- the commands: the only things Channel Mirror (and a linked computer allowed to) asks OBS to do ---
def _name(x):
    if not isinstance(x, str) or not x.strip() or len(x) > 256 or not x.isprintable():
        raise ValueError("A name of a scene or source isn't plain text (256 characters at most)")
    return x


def _flag(x):
    if not isinstance(x, bool):
        raise ValueError("A yes / no isn't yes or no")
    return x


def _num(lo, hi):
    def f(x):
        if not isinstance(x, int) or isinstance(x, bool) or not lo <= x <= hi:
            raise ValueError("A number is out of range")
        return x
    return f


def _one(*ok):
    def f(x):
        if x not in ok:
            raise ValueError(f"Not one of: {', '.join(ok)}")
        return x
    return f


def obs_feed_url(x):
    """A link OBS may be pointed at by a linked computer: only a Channel Mirror stream / overlay on the home network
    (http://<home-network address>:<port>/music/<token>/stream.mp3 or /now) - never a file, a website or anything else."""
    m = re.fullmatch(r"http://(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})/music/[0-9a-f]{32}/(stream\.mp3|now)", str(x),
                     re.ASCII)
    if not isinstance(x, str) or not m or not link_private(m[1]) or not 0 < int(m[2]) < 65536:
        raise ValueError("Only a Channel Mirror stream link on the home network can go into OBS")
    return x


OBS_COMMANDS = {  # name -> {argument: its check}; every argument is required, nothing else is taken
    "state": {},
    "scene": {"scene": _name},
    "item": {"scene": _name, "id": _num(0, 2 ** 31), "on": _flag},
    "mute": {"input": _name, "muted": _flag},
    "volume": {"input": _name, "percent": _num(0, 100)},
    "media": {"input": _name, "action": _one(*OBS_MEDIA)},
    "output": {"output": _one(*OBS_OUTPUTS), "action": _one("start", "stop")},
    "add_feed": {"scene": _name, "name": _name, "url": obs_feed_url},
    "feed_play": {"sound": _name},  # the soundboard feed (Channel Mirror's own, not an OBS request)
    "feed_stop": {},
}


def obs_check(cmd, args):
    """A command checked against its strict form -> its arguments (ValueError saying what's wrong otherwise)."""
    if not isinstance(cmd, str) or cmd not in OBS_COMMANDS:
        raise ValueError(f"Not an OBS command Channel Mirror runs: {str(cmd)[:30]!r}")
    form = OBS_COMMANDS[cmd]
    if not isinstance(args, dict) or set(args) != set(form):
        raise ValueError(f"The OBS command '{cmd}' takes exactly: {', '.join(form) or 'nothing'}")
    return {k: form[k](args[k]) for k in form}


def obs_state(client):
    """What the OBS tab shows: scenes (the one on air), the sources in it, audio (mute, volume 0-100), media sources
    and whether it's streaming / recording / the virtual camera is on. Names only."""
    sl = client.request("GetSceneList")
    cur = str(sl.get("currentProgramSceneName") or "")
    out = {"scene": cur, "scenes": [str(s.get("sceneName")) for s in reversed(sl.get("scenes") or [])][:200],
           "items": [], "inputs": [], "media": []}
    if cur:
        out["items"] = [{"id": int(i.get("sceneItemId", 0)), "name": str(i.get("sourceName")),
                         "on": bool(i.get("sceneItemEnabled"))}
                        for i in client.request("GetSceneItemList", {"sceneName": cur}).get("sceneItems") or []][:200]
    for i in (client.request("GetInputList").get("inputs") or [])[:200]:
        name, kind = str(i.get("inputName")), str(i.get("inputKind") or i.get("unversionedInputKind") or "")
        try:
            muted = bool(client.request("GetInputMute", {"inputName": name}).get("inputMuted"))
            mul = float(client.request("GetInputVolume", {"inputName": name}).get("inputVolumeMul") or 0)
            out["inputs"].append({"name": name, "kind": kind, "muted": muted,
                                  "volume": int(round(min(1.0, max(0.0, mul)) ** 0.5 * 100))})
        except (ObsError, ValueError, TypeError):  # no sound (a picture, a camera without audio...)
            pass
        if kind in OBS_MEDIA_KINDS + OBS_IMAGE_KINDS:
            st = ""
            if kind in OBS_MEDIA_KINDS:
                try:
                    st = str(client.request("GetMediaInputStatus", {"inputName": name}).get("mediaState") or "")
                except ObsError:
                    pass
            out["media"].append({"name": name, "kind": kind, "state": st.replace("OBS_MEDIA_STATE_", "").lower()})
    for k, (_, _, get) in OBS_OUTPUTS.items():
        try:
            out[k] = bool(client.request(get).get("outputActive"))
        except ObsError:
            out[k] = False
    return out


def obs_run(client, cmd, args):
    """Run one checked command (obs_check) on OBS -> its result (the state for "state", else {})."""
    a = args
    if cmd == "state":
        return obs_state(client)
    if cmd == "scene":
        client.request("SetCurrentProgramScene", {"sceneName": a["scene"]})
    elif cmd == "item":
        client.request("SetSceneItemEnabled", {"sceneName": a["scene"], "sceneItemId": a["id"],
                                               "sceneItemEnabled": a["on"]})
    elif cmd == "mute":
        client.request("SetInputMute", {"inputName": a["input"], "inputMuted": a["muted"]})
    elif cmd == "volume":  # a square curve, as in the Music player: 50 sounds about half as loud
        client.request("SetInputVolume", {"inputName": a["input"], "inputVolumeMul": (a["percent"] / 100) ** 2})
    elif cmd == "media":
        client.request("TriggerMediaInputAction", {"inputName": a["input"], "mediaAction": OBS_MEDIA[a["action"]]})
    elif cmd == "output":
        client.request(OBS_OUTPUTS[a["output"]][0 if a["action"] == "start" else 1])
    elif cmd == "add_feed":
        if a["url"].endswith("/now"):  # the now-playing overlay: a Browser Source
            kind, settings = "browser_source", {"url": a["url"], "width": 800, "height": 160}
        else:  # an endless stream: a Media Source that isn't a local file
            kind, settings = "ffmpeg_source", {"is_local_file": False, "input": a["url"], "input_format": "mp3",
                                               "restart_on_activate": False, "close_when_inactive": False}
        client.request("CreateInput", {"sceneName": a["scene"], "inputName": a["name"], "inputKind": kind,
                                       "inputSettings": settings, "sceneItemEnabled": True})
    else:
        raise ValueError(f"'{cmd}' isn't an OBS request")
    return {}


def obs_here(client, cmd, args, feed=None, sounds=()):
    """A checked command (obs_check) run on this PC - by the OBS tab, or for a linked computer allowed to: the
    soundboard feed's on the feed (a sound by name from `sounds`, the soundboard's files: never a path from
    anywhere else), the rest on OBS (client; None = not connected). "state" also lists the sounds by name."""
    if cmd == "feed_play":
        f = next((Path(x) for x in sounds if Path(x).name == args["sound"]), None)
        if f is None or not f.is_file():
            raise ValueError(f"No sound '{args['sound']}' on the soundboard here")
        feed.play(f)
        return {}
    if cmd == "feed_stop":
        feed.stop()
        return {}
    if client is None:
        raise ObsError("OBS isn't connected on that PC (its OBS tab: Connect)")
    out = obs_run(client, cmd, args)
    if cmd == "state":
        out["sounds"] = sorted({Path(x).name for x in sounds})[:500]
    return out


def obs_put_files(client, files, spec):
    """Files for OBS into OBS (on this PC: the files are here): {"input": name} - one file into that media / image
    source; {"scene", "name"} - a new source per file in that scene (pictures: Image, else Media). What was done."""
    files = [Path(f).resolve() for f in files]
    if spec.get("input"):
        if len(files) != 1:
            raise ValueError("One file goes into a source")
        kind = str(client.request("GetInputSettings", {"inputName": spec["input"]}).get("inputKind") or "")
        f, img = str(files[0]), files[0].suffix.lower() in OBS_IMAGES
        if kind in OBS_IMAGE_KINDS and img:
            settings = {"file": f}
        elif kind == "ffmpeg_source" and not img:
            settings = {"local_file": f, "is_local_file": True}
        elif kind == "vlc_source" and not img:
            settings = {"playlist": [{"value": f, "hidden": False, "selected": False}]}
        else:
            raise ValueError(f"'{spec['input']}' is a {kind or 'different'} source - "
                             f"{'a picture goes into an Image' if img else 'a sound / video goes into a Media'} source")
        client.request("SetInputSettings", {"inputName": spec["input"], "inputSettings": settings})
        return f"{files[0].name} into '{spec['input']}'"
    names = []
    for i, f in enumerate(files):
        name = spec["name"] if i == 0 else f"{spec['name']} {i + 1}"
        img = f.suffix.lower() in OBS_IMAGES
        client.request("CreateInput", {
            "sceneName": spec["scene"], "inputName": name, "inputKind": "image_source" if img else "ffmpeg_source",
            "inputSettings": {"file": str(f)} if img else {"local_file": str(f), "is_local_file": True},
            "sceneItemEnabled": True})
        names.append(name)
    return f"{len(names)} new source(s) in '{spec['scene']}': {', '.join(names[:5])}"


class ObsRate:
    """At most n commands within `per` seconds from each linked computer (a key held down, a script gone wrong)."""

    def __init__(self, n=20, per=5.0):
        self.n, self.per, self.seen, self.lock = n, per, {}, threading.Lock()

    def ok(self, key, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            t = [x for x in self.seen.get(key, []) if now - x < self.per]
            self.seen[key] = t
            if len(t) >= self.n:
                return False
            t.append(now)
            return True


def obs_serve(peer, cmd, args, run, rate):
    """A linked computer's OBS command (from the link server's thread; its signature and link were checked there):
    run only for a linked computer this PC allows ("May control OBS", off unless turned on here), at most rate allows,
    and only a command of the fixed list. run(cmd, args) does it here. {"ok": True, "result"} or {"ok": False, "error"}."""
    if not peer:
        return {"ok": False, "error": "Not a linked computer"}
    if peer.get("obs") is not True:
        return {"ok": False, "error": f"{peer.get('name', 'That computer')} may not control OBS here - turn on 'May "
                                      "control OBS' for it in the Linked computers tab on the PC with OBS"}
    try:
        args = obs_check(cmd, args)
        if cmd == "add_feed" and urlsplit(args["url"]).hostname != peer.get("host"):
            raise ValueError("A linked computer can only add its own Channel Mirror links to OBS")
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not rate.ok(peer.get("id")):
        return {"ok": False, "error": "Too many OBS commands at once - wait a moment"}
    try:
        return {"ok": True, "result": run(cmd, args)}
    except Exception as e:  # OBS refused, or answered oddly: said, never half-done silently
        return {"ok": False, "error": str(e)[:300] or type(e).__name__}
