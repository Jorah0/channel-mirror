"""Music player: playlists, the playback engine, local output and the stream / overlay OBS opens."""
import json
import numpy as np
import os
import subprocess
from pathlib import Path
from .core import AUDIO_EXT, FFMPEG_DIR, NO_WINDOW, VIDEO_EXT
from .mirror import clean_name
from .link import link_lan_ip, link_private
from .peers import peer_name


# --- music player: playlists, one endless real-time PCM stream (songs, silence between them and while paused) that
# goes to this PC's speakers (waveOut) and to OBS on the home network (an MP3 stream + a now-playing overlay) ---
MUSIC_RATE = 48000


MUSIC_BLOCK = MUSIC_RATE // 50 * 4  # 20 ms of 16-bit stereo


MUSIC_PORT, MUSIC_LISTENERS = 8766, 8  # the OBS links' port; streams at once (each OBS / browser listening is one)


MUSIC_EXT = AUDIO_EXT + VIDEO_EXT  # a video's sound plays too


MUSIC_REPEAT = {"Repeat off": "off", "Repeat one": "one", "Repeat all": "all"}


MUSIC_DEFAULT_OUT = "(Windows default output)"


MUSIC_NOW = FFMPEG_DIR.parent / "Now playing.txt"  # for an OBS Text source on this PC (read from file)


def music_local(f):
    r"""True for a file on this PC's own drives (C:\...): never a network share (\\server\..., or /\server\... - Windows
    would log on to it, sending the user's credentials), a device path or a drive-relative path."""
    import re
    return bool(re.match(r"[A-Za-z]:\\(?![\\/])", os.path.normpath(str(f))))


def music_title(song):
    """What a playlist shows for a song ({"path", "title"}): its own title (from a playlist file), else its name."""
    return song.get("title") or clean_name(Path(song["path"]).stem, 80)


def music_add(songs, items):
    """Add (file, title) pairs to a playlist's songs; a file already in it isn't added twice. How many were added."""
    seen, n = {os.path.normcase(str(Path(s["path"]))) for s in songs}, 0
    for f, title in items:
        k = os.path.normcase(str(Path(f)))
        if k not in seen and music_local(f):
            seen.add(k)
            songs.append({"path": str(Path(f)), "title": " ".join(str(title or "").split())[:200]})
            n += 1
    return n


def music_move(items, idxs, step):
    """Move the items at idxs one place up (step -1) or down (1), together; one at the edge stays. (items, new idxs)."""
    items, out, taken = list(items), [], set()
    for i in sorted(set(idxs), reverse=step > 0):
        j = i + step
        if 0 <= j < len(items) and j not in taken:
            items[i], items[j] = items[j], items[i]
            i = j
        taken.add(i)
        out.append(i)
    return items, sorted(out)


def music_order(n, first=None, shuffle=False):
    """The order a playlist of n songs plays in: as listed, or shuffled with song `first` (playing now) first."""
    import random
    if not shuffle:
        return list(range(n))
    rest = [i for i in range(n) if i != first]
    random.shuffle(rest)
    return ([first] if first is not None and 0 <= first < n else []) + rest


def music_next(order, cur, repeat="off", step=1, auto=False):
    """The song after (step 1) / before (-1) song cur, following order: None past the end (repeat "off").
    auto = the song ended by itself: "one" plays it again (Next / Previous still move on). Previous at the first song
    is that song again."""
    if not order:
        return None
    if auto and repeat == "one" and cur in order:
        return cur
    pos = (order.index(cur) if cur in order else -1) + step
    if 0 <= pos < len(order):
        return order[pos]
    if repeat in ("all", "one"):
        return order[pos % len(order)]
    return order[0] if step < 0 else None


def m3u_read(path):
    """[(file, title)] from an .m3u / .m3u8 playlist (UTF-8, or Windows' own code page for old ones): a relative entry
    is found from the playlist's folder, #EXTINF gives its title ("" without one). Web addresses, network shares
    and anything that isn't a sound / video file are skipped: a playlist from anywhere only ever names files here."""
    import re
    import urllib.parse
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("mbcs" if os.name == "nt" else "latin-1", errors="replace")
    out, title = [], ""
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith("#EXTINF:"):
            title = s.split(",", 1)[1].strip() if "," in s else ""
            continue
        if not s or s.startswith("#"):
            continue
        if s.lower().startswith("file:///"):
            s = urllib.parse.unquote(s[8:])
            if not re.match(r"[A-Za-z]:[\\/]", s):
                s = "//"  # a file:// address on another computer: skipped below
        if s.startswith(("\\\\", "//")) or re.match(r"[A-Za-z][A-Za-z0-9+.-]+:|[A-Za-z]:(?![\\/])", s):
            title = ""  # a network share, a web address (or other scheme), a drive-relative path: never opened
            continue
        f = Path(os.path.normpath(s if re.match(r"[A-Za-z]:[\\/]", s) else Path(path).parent / s))
        if f.suffix.lower() in MUSIC_EXT and music_local(f):  # (\/server/x.mp3 is a share too)
            out.append((f, title))
        title = ""
    return out


def m3u_write(path, songs):
    """Write [(file, title)] as an .m3u / .m3u8 playlist (UTF-8, #EXTINF titles): files inside the playlist's folder
    as relative paths (the folder can move), others as full paths."""
    base, lines = Path(path).resolve().parent, ["#EXTM3U"]
    for f, title in songs:
        f = Path(f).resolve()
        try:
            entry = str(f.relative_to(base))
        except ValueError:
            entry = str(f)
        lines += [f"#EXTINF:-1,{' '.join(str(title or clean_name(f.stem, 80)).split())}", entry]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def music_length(path):
    """A song's length in seconds (0 when ffprobe can't tell)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-show_entries", "format=duration",
                        "-of", "csv=p=0", f"file:{path}"], capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        return max(0.0, float(r.stdout.strip()))
    except ValueError:
        return 0.0


def music_block(data, volume):
    """One MUSIC_BLOCK of PCM: data, padded with silence when short, at volume 0-100 (a square curve: 50 is a
    quarter of the level, which sounds about half as loud)."""
    a = np.zeros(MUSIC_BLOCK // 2, "<i2")
    n = min(len(data), MUSIC_BLOCK) // 2
    a[:n] = np.frombuffer(data[:n * 2], "<i2")
    if volume < 100:
        a = (a * (max(0, volume) / 100) ** 2).astype("<i2")  # a factor <= 1: never out of range
    return a.tobytes()


class MusicEngine:
    """Plays songs as one endless stream in real time: the current song decoded by ffmpeg (MUSIC_RATE Hz, 16-bit
    stereo), silence while paused, stopped, between songs or while a song is starting. Every 20 ms block goes, at
    the volume, to each sink (set_sink(name, f(bytes))). on_end() is called from the engine's thread when a song
    plays to its end."""

    def __init__(self, on_end=None):
        import threading
        self.lock, self.sinks, self.on_end = threading.Lock(), {}, on_end
        self.song, self.dec, self.q, self.start, self.done = None, None, None, 0.0, 0
        self.paused, self.volume, self.quit = False, 100, False
        threading.Thread(target=self._run, daemon=True).start()

    def set_sink(self, name, fn):
        with self.lock:
            if fn:
                self.sinks[name] = fn
            else:
                self.sinks.pop(name, None)

    def play(self, path, at=0.0, paused=False):
        """Start a song at `at` seconds (whatever was playing stops)."""
        p, q, reader = music_decode(path, at, lambda q: self.q is q)
        with self.lock:
            self._kill()
            self.song, self.dec, self.q, self.start, self.done, self.paused = Path(path), p, q, float(at), 0, paused
        reader.start()

    def seek(self, secs):
        if self.song:
            self.play(self.song, secs, self.paused)

    def pause(self, on):
        with self.lock:
            self.paused = bool(on)

    def stop(self):
        with self.lock:
            self._kill()

    def position(self):
        """Seconds into the song now playing (0 when none)."""
        with self.lock:
            return self.start + self.done / (MUSIC_RATE * 4) if self.song else 0.0

    def close(self):
        self.quit = True
        self.stop()

    def _kill(self):  # with the lock held
        if self.dec:
            try:
                self.dec.kill()
            except OSError:
                pass
        self.song, self.dec, self.q, self.start, self.done = None, None, None, 0.0, 0

    def _block(self):
        """The next 20 ms: the song's, or silence."""
        import queue
        with self.lock:
            q, paused, vol = self.q, self.paused, self.volume
        data, ended = b"", False
        if q is not None and not paused:
            try:
                data = q.get_nowait()
            except queue.Empty:
                data = b""  # still starting: silence meanwhile, the stream never waits
            with self.lock:
                if self.q is not q:
                    data = b""
                elif data is None:
                    self._kill()
                    data, ended = b"", True
                else:
                    self.done += len(data)
        if ended and self.on_end:
            self.on_end()
        return music_block(data, vol)

    def _run(self):
        import time
        t0, n = time.perf_counter(), 0
        while not self.quit:
            if self.q is None and not self.sinks:  # no song, nobody listening: no 50 Hz of silence all day
                time.sleep(0.1)
                t0, n = time.perf_counter(), 0
                continue
            block = self._block()
            with self.lock:
                sinks = list(self.sinks.values())
            for s in sinks:
                try:
                    s(block)
                except Exception:  # a sink closing meanwhile: the others still get it
                    pass
            n += 1
            wait = t0 + n * 0.02 - time.perf_counter()
            if wait < -0.2:  # far behind (the PC was busy): carry on from now, no burst to catch up
                t0, n = time.perf_counter(), 0
            elif wait > 0:
                time.sleep(wait)


def music_decode(path, at, alive):
    """ffmpeg decoding a file from `at` seconds (MUSIC_RATE Hz, 16-bit stereo) into a queue of MUSIC_BLOCKs, half a
    second ahead (a whole song never sits in memory), None at its end, for as long as alive(queue).
    -> (the ffmpeg process, the queue, the reader thread - start it once the queue is where alive() looks)."""
    import queue
    import threading
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, float(at)):.3f}",
                          "-protocol_whitelist", "file", "-i", f"file:{path}", "-vn", "-sn", "-dn", "-f", "s16le",
                          "-ac", "2", "-ar", str(MUSIC_RATE), "pipe:1"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         creationflags=NO_WINDOW)
    q = queue.Queue(25)

    def put(x):
        while True:
            try:
                return q.put(x, timeout=0.2)
            except queue.Full:
                if not alive(q):  # stopped meanwhile
                    return

    def read():
        try:
            while alive(q):
                b = p.stdout.read(MUSIC_BLOCK)
                if b:
                    put(b)
                if len(b) < MUSIC_BLOCK:
                    break
        except (OSError, ValueError):
            pass
        put(None)  # the end of the file
    return p, q, threading.Thread(target=read, daemon=True)


class SoundFeed(MusicEngine):
    """The soundboard feed: sounds Channel Mirror plays (from the OBS tab, or a linked computer allowed to) mixed into
    one endless stream like the music one - several at once, silence between them, so OBS never drops it.
    play(path, volume) from any thread; stop() ends every sound. Sinks as MusicEngine's (set_sink)."""
    MAX = 16  # sounds at once: one more ends the oldest

    def __init__(self):
        self.voices = []  # [queue, ffmpeg, gain, name]
        super().__init__()

    def play(self, path, volume=100):
        v = [None, None, (max(0, min(100, volume)) / 100) ** 2, Path(path).name]
        p, q, reader = music_decode(path, 0, lambda q: any(x is v for x in self.voices))
        v[:2] = q, p
        with self.lock:
            while len(self.voices) >= self.MAX:
                self._end(self.voices[0])
            self.voices.append(v)
        reader.start()

    def playing(self):
        with self.lock:
            return [v[3] for v in self.voices]

    def stop(self):
        with self.lock:
            for v in list(self.voices):
                self._end(v)

    def _end(self, v):  # with the lock held
        self.voices[:] = [x for x in self.voices if x is not v]
        try:
            v[1].kill()
        except OSError:
            pass

    def _block(self):
        import queue
        with self.lock:
            voices, vol = list(self.voices), self.volume
        mix = None
        for v in voices:
            try:
                data = v[0].get_nowait()
            except queue.Empty:
                continue  # starting: it joins in when its sound comes
            if data is None:
                with self.lock:
                    self._end(v)
                continue
            a = np.frombuffer(music_block(data, 100), "<i2") * v[2]
            mix = a if mix is None else mix + a
        if mix is None:
            return music_block(b"", 100)
        return np.clip(mix * (max(0, vol) / 100) ** 2, -32768, 32767).astype("<i2").tobytes()


def music_devices():
    """This PC's playback devices, as Windows' waveOut names them (cut at 31 characters)."""
    import ctypes
    from ctypes import wintypes

    class Caps(ctypes.Structure):
        _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                    ("szPname", wintypes.WCHAR * 32), ("dwFormats", wintypes.DWORD), ("wChannels", wintypes.WORD),
                    ("wReserved1", wintypes.WORD), ("dwSupport", wintypes.DWORD)]
    out = []
    try:
        w = ctypes.windll.winmm
        for i in range(w.waveOutGetNumDevs()):
            c = Caps()
            if w.waveOutGetDevCapsW(ctypes.c_size_t(i), ctypes.byref(c), ctypes.sizeof(c)) == 0:
                out.append(c.szPname)
    except (AttributeError, OSError):
        pass
    return out


class MusicOut:
    """Listening on this PC: MUSIC_BLOCKs to a playback device (a name from music_devices(); anything else = Windows'
    default) through the waveOut API. A block that finds every buffer still playing is dropped: the stream's clock and
    the sound card's never quite agree, and a tiny skip beats a delay that keeps growing."""
    N = 8  # buffers of 20 ms

    def __init__(self, device=""):
        import ctypes
        import threading
        from ctypes import wintypes

        class Fmt(ctypes.Structure):
            _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                        ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                        ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]

        class Hdr(ctypes.Structure):
            _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                        ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t), ("dwFlags", wintypes.DWORD),
                        ("dwLoops", wintypes.DWORD), ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]
        self.ct, self.lock, self.closed, self.i = ctypes, threading.Lock(), False, 0
        w = self.w = ctypes.windll.winmm
        w.waveOutOpen.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.UINT, ctypes.POINTER(Fmt), ctypes.c_size_t,
                                  ctypes.c_size_t, wintypes.DWORD]
        for f in (w.waveOutPrepareHeader, w.waveOutUnprepareHeader, w.waveOutWrite):
            f.argtypes = [wintypes.HANDLE, ctypes.POINTER(Hdr), wintypes.UINT]
        for f in (w.waveOutReset, w.waveOutClose):
            f.argtypes = [wintypes.HANDLE]
        names = music_devices()
        self.h = wintypes.HANDLE()
        r = w.waveOutOpen(ctypes.byref(self.h), names.index(device) if device in names else 0xFFFFFFFF,  # WAVE_MAPPER
                          ctypes.byref(Fmt(1, 2, MUSIC_RATE, MUSIC_RATE * 4, 4, 16, 0)), 0, 0, 0)
        if r:
            raise OSError(f"The playback device couldn't be opened (waveOut error {r})")
        self.bufs = [ctypes.create_string_buffer(MUSIC_BLOCK) for _ in range(self.N)]
        self.hdrs = [Hdr() for _ in range(self.N)]
        for _ in range(3):  # 60 ms in hand, so a late block doesn't click
            self.write(bytes(MUSIC_BLOCK))

    def write(self, data):
        with self.lock:
            if self.closed:
                return
            h, size = self.hdrs[self.i], self.ct.sizeof(self.hdrs[self.i])
            if h.dwFlags & 2:  # WHDR_PREPARED
                if not h.dwFlags & 1:  # not WHDR_DONE: still playing - this block is dropped
                    return
                self.w.waveOutUnprepareHeader(self.h, self.ct.byref(h), size)
            data = data[:MUSIC_BLOCK]
            self.ct.memmove(self.bufs[self.i], data, len(data))
            h.lpData, h.dwBufferLength, h.dwFlags = self.ct.addressof(self.bufs[self.i]), len(data), 0
            self.w.waveOutPrepareHeader(self.h, self.ct.byref(h), size)
            self.w.waveOutWrite(self.h, self.ct.byref(h), size)
            self.i = (self.i + 1) % self.N

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.w.waveOutReset(self.h)
            for h in self.hdrs:
                if h.dwFlags & 2:
                    self.w.waveOutUnprepareHeader(self.h, self.ct.byref(h), self.ct.sizeof(h))
            self.w.waveOutClose(self.h)


def music_route(path, token):
    """Which of the music server's pages a request path asks for: "stream", "now" (the overlay) or "json" - or None
    (the wrong token, or anything else: the server answers 404 either way)."""
    import hmac
    import re
    from urllib.parse import urlsplit
    if not str(path).startswith("/music/"):
        return None
    m = re.fullmatch(r"/music/([0-9a-f]{32})/(stream\.mp3|now|now\.json)", urlsplit(str(path)).path)
    if not m or not re.fullmatch(r"[0-9a-f]{32}", str(token)) or not hmac.compare_digest(m[1], str(token)):
        return None
    return {"stream.mp3": "stream", "now": "now", "now.json": "json"}[m[2]]


MUSIC_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Now playing</title><style>
html,body{margin:0;background:transparent;overflow:hidden}#np{display:none;padding:14px 20px;color:#fff;
font:600 34px 'Segoe UI',sans-serif;text-shadow:0 2px 6px rgba(0,0,0,.8)}#pl{font-size:20px;font-weight:400;opacity:.85}
</style></head><body><div id="np"><div id="t"></div><div id="pl"></div></div><script>
async function tick(){try{const d=await (await fetch('now.json',{cache:'no-store'})).json();
document.getElementById('t').textContent=d.title||'';document.getElementById('pl').textContent=d.playlist||'';
document.getElementById('np').style.display=d.title?'block':'none'}catch(e){}setTimeout(tick,1000)}tick()
</script></body></html>"""


class MusicServer:
    """The music for OBS on the home network, read-only: GET /music/<token>/stream.mp3 (one endless MP3 stream of what
    feed() gets: MUSIC_RATE Hz 16-bit stereo, the silences included, so it never ends), /now (a now-playing overlay
    for a Browser Source) and /now.json (now(): the song's title, the playlist, playing or not - names, never paths).
    LinkServer's rules: it listens on the home-network address only (host=None), answers home-network devices only,
    and a wrong token or anything else is 404. Up to MUSIC_LISTENERS streams at once; a listener that can't keep up
    is dropped. port 0 picks a free port (self.port)."""

    def __init__(self, port, token, now, host=None):
        import queue
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        server = self
        self.token, self.now, self.lock, self.listeners = str(token), now, threading.Lock(), set()
        self.host = link_lan_ip() if host is None else host
        self.enc = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-f", "s16le", "-ar", str(MUSIC_RATE), "-ac",
                                     "2", "-i", "pipe:0", "-c:a", "mp3", "-b:a", "192k", "-f", "mp3", "-flush_packets",
                                     "1", "pipe:1"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, bufsize=0, creationflags=NO_WINDOW)
        try:
            self.enc.wait(0.3)
            raise OSError("ffmpeg can't make an MP3 stream on this PC")
        except subprocess.TimeoutExpired:
            pass  # running

        class Handler(BaseHTTPRequestHandler):
            timeout = 30  # a listener that stops taking the stream is dropped

            def log_message(self, *a):  # quiet
                pass

            def head(self, status, kind, size=None):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                if size is not None:
                    self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                                                            "style-src 'unsafe-inline'; connect-src 'self'")
                self.end_headers()

            def reply(self, status, body, kind="text/plain; charset=utf-8"):
                self.head(status, kind, len(body))
                self.wfile.write(body)

            def do_GET(self):
                if not link_private(self.client_address[0]):
                    return self.reply(403, b"Only devices on this home network can listen.")
                tok = server.token
                what = music_route(self.path, tok)
                if what is None:
                    return self.reply(404, b"Not found")
                if what == "now":
                    return self.reply(200, MUSIC_PAGE.encode(), "text/html; charset=utf-8")
                if what == "json":
                    try:
                        n = server.now() or {}
                    except Exception:
                        n = {}
                    n = {"title": peer_name(n.get("title", ""), 200), "playlist": peer_name(n.get("playlist", ""), 200),
                         "playing": bool(n.get("playing"))}
                    return self.reply(200, json.dumps(n).encode(), "application/json")
                q = queue.Queue(256)  # small pieces as they come (4 MB at most)
                with server.lock:
                    full = tok != server.token or len(server.listeners) >= MUSIC_LISTENERS  # (a new link
                    if not full:  # made this moment: not on the old one)
                        server.listeners.add(q)
                if full:
                    return self.reply(503, b"Too many listening already")
                try:
                    self.head(200, "audio/mpeg")
                    while (chunk := q.get(timeout=10)) is not None:
                        self.wfile.write(chunk)
                except (OSError, queue.Empty):
                    pass
                finally:
                    with server.lock:
                        server.listeners.discard(q)
        ThreadingHTTPServer.allow_reuse_address = False
        try:
            self.httpd = ThreadingHTTPServer((self.host, port), Handler)
        except Exception:
            self.enc.kill()
            raise
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        threading.Thread(target=self._pump, daemon=True).start()

    def feed(self, pcm):
        try:
            self.enc.stdin.write(pcm)
        except (OSError, ValueError, AttributeError):
            pass  # stopping

    def _pump(self):
        """The encoder's MP3 to every listener."""
        import queue
        while True:
            try:
                chunk = self.enc.stdout.read(16384)  # a raw pipe: what's there now, up to this
            except (OSError, ValueError):
                chunk = b""
            with self.lock:
                ls = list(self.listeners)
            for q in ls:
                try:
                    q.put_nowait(chunk or None)
                except queue.Full:  # too slow to keep up: dropped (it plays what it has, then its connection ends)
                    with self.lock:
                        self.listeners.discard(q)
            if not chunk:
                return

    def retoken(self, token):
        """A new link: the old one stops working, and whoever listens with it is cut off."""
        import queue
        with self.lock:
            self.token = str(token)
            for q in self.listeners:
                with q.mutex:  # what it hasn't sent yet goes too: cut off now
                    q.queue.clear()
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
            self.listeners.clear()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.retoken("")
        try:
            self.enc.stdin.close()
        except OSError:
            pass
        self.enc.kill()


def music_now_file(text, path=None):
    """The song playing now into a text file (an OBS Text source on this PC reads it); written whole or not at all."""
    f = Path(path or MUSIC_NOW)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".writing")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass  # OBS reading it this moment: the next song writes it again
