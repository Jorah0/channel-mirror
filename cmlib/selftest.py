"""python channel_mirror.py --selftest: checks every part without touching real files."""
import json
import numpy as np
import os
import shutil
import subprocess
import sys
from pathlib import Path
from .core import MAIN, set_shared, shared
from .core import FFMPEG_DIR, NO_WINDOW, SOURCES, TARGETS, download_ffmpeg, secret_keep, secret_read, settings_put
from .install import install, installed, shortcut_paths, uninstall
from .mirror import (
    OUT_SUBDIR,
    analyze,
    clean_name,
    clip_seconds,
    media_files,
    natural,
    out_ext,
    out_folder,
    out_name,
    parse_time,
    pick_source,
    plan_jobs,
    probe,
    route,
    sound_folders,
    split_points,
)
from .deck import (
    SD_BACKUPS,
    SD_DEFAULT_OUT,
    SD_DIR,
    SD_FOLDER,
    SD_GOALS,
    SD_KINDS,
    SD_LEVELS,
    SD_MODES,
    SD_OBS_DEFAULT,
    SD_PARENT,
    SD_PLAY,
    _win_outputs,
    sd_add_sounds,
    sd_beside,
    sd_clone_folders,
    sd_folder_map,
    sd_combine,
    sd_devices,
    sd_fill,
    sd_folder,
    sd_folders,
    sd_free,
    sd_images,
    sd_install,
    sd_key,
    sd_keypad,
    sd_kind,
    sd_label,
    sd_layout,
    sd_level_rows,
    sd_listen,
    sd_match_loudness,
    sd_missing,
    sd_move,
    sd_multis,
    sd_order,
    sd_out,
    sd_out_name,
    sd_output_choices,
    sd_outputs,
    sd_pages,
    sd_place,
    sd_play,
    sd_plays_like,
    sd_profile,
    sd_profile_files,
    sd_profiles,
    sd_reachable,
    sd_relink,
    sd_save,
    sd_set_levels,
    sd_set_sound,
    sd_sounds,
    sd_split,
    sd_stop_key,
    sd_title,
    sd_uid,
    sd_win_outputs,
    sd_wrap,
)
from .vts import (
    SD_VTS_HOTKEY,
    VTS_ASSETS,
    VTS_HOTKEY,
    sd_vts_key,
    vts_backups,
    vts_copy,
    vts_files,
    vts_find,
    vts_hotkeys,
    vts_missing,
    vts_models,
)
from .link import (
    LINK_INBOX,
    link_args,
    link_make,
    link_noproxy,
    link_parse,
    link_private,
    link_register,
    link_registered,
    link_safe_name,
    link_send,
    link_to_peer,
    link_unregister,
)
from .peers import (
    LINK_AUDIO,
    LINK_IMAGES,
    LinkServer,
    PAIR_P,
    PEER_DAYS,
    PEER_SKEW,
    library_files,
    library_items,
    link_check_file,
    link_default_target,
    link_handover,
    link_handover_serve,
    pair_offer,
    pair_secret,
    peer_apply,
    peer_browse,
    peer_call,
    peer_carried,
    peer_check_files,
    peer_days_left,
    peer_find,
    peer_headers,
    peer_hello,
    peer_icon_ok,
    peer_key,
    peer_pack,
    peer_pair,
    peer_proposal,
    peer_put_ops,
    peer_renew,
    peer_result,
    peer_send,
    peer_sign,
    peer_summary,
    peer_unlink,
)
from .recorder import rec_area, rec_command, rec_name
from .setup import SETUP_GLOBALS, app_command, setup_apply, setup_auto, setup_check, ui_mode, win_light_theme
from .music import (
    MUSIC_BLOCK,
    MusicEngine,
    MusicServer,
    m3u_read,
    m3u_write,
    music_add,
    music_block,
    music_local,
    music_move,
    music_next,
    music_order,
    music_route,
    music_title,
)
from .ui import UI_DARK, UI_LIGHT
from .ui_link import peer_batches
from .obs import (
    ObsClient,
    ObsError,
    ObsRate,
    obs_auth,
    obs_check,
    obs_feed_url,
    obs_here,
    obs_put_files,
    obs_serve,
    obs_state,
    ws_frame,
    ws_read,
)
from .music import SoundFeed
from .peers import peer_obs


class FakeObs:
    """A stand-in for OBS's websocket server (obs-websocket 5) on 127.0.0.1, for tests only - never the real OBS.
    Scenes "Main" / "BRB" with sources, inputs (audio, media, image, camera), stream / record / virtual camera.
    It answers every request the OBS tab uses (unknown ones are refused, as OBS does), sends events, splits its
    hello into fragments with a ping in between, checks the password (close 4009 when wrong), and plays a stream it
    is given like OBS would: the bytes heard per source are in self.heard. Requests: self.requests (and log, a
    .jsonl file). silent = stop answering requests; kick() drops every connection."""

    def __init__(self, password="", log=None):
        import socket
        import threading
        self.password, self.log, self.lock = password, log, threading.Lock()
        self.requests, self.conns, self.heard, self.silent = [], [], {}, False
        self.scene, self.scenes = "Main", ["Main", "BRB"]
        self.items = {"Main": [{"sceneItemId": 1, "sourceName": "Camera", "sceneItemEnabled": True},
                               {"sceneItemId": 2, "sourceName": "Clip", "sceneItemEnabled": True},
                               {"sceneItemId": 3, "sourceName": "Logo", "sceneItemEnabled": True}],
                      "BRB": [{"sceneItemId": 1, "sourceName": "Logo", "sceneItemEnabled": True}]}
        self.inputs = {"Mic": {"kind": "wasapi_input_capture", "muted": False, "mul": 1.0, "settings": {}},
                       "Desktop Audio": {"kind": "wasapi_output_capture", "muted": False, "mul": 1.0, "settings": {}},
                       "Clip": {"kind": "ffmpeg_source", "muted": False, "mul": 1.0, "settings": {}, "media": "playing"},
                       "Logo": {"kind": "image_source", "settings": {}}, "Camera": {"kind": "dshow_input", "settings": {}}}
        self.outputs = {"stream": False, "record": False, "vcam": False}
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        import threading
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def stop(self):
        self.sock.close()
        self.kick()

    def kick(self):
        import socket
        with self.lock:
            conns, self.conns = self.conns, []
        for c, _ in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()

    def event(self, etype, data):
        for c, lk in list(self.conns):
            try:
                with lk:
                    c.sendall(ws_frame(1, json.dumps({"op": 5, "d": {"eventType": etype, "eventIntent": 1,
                                                                     "eventData": data}}).encode(), mask=False))
            except OSError:
                pass

    def _serve(self, c):
        import base64
        import hashlib
        import secrets
        import threading
        buf, lk = [b""], threading.Lock()

        def recv(n):
            while len(buf[0]) < n:
                got = c.recv(65536)
                if not got:
                    raise OSError("closed")
                buf[0] += got
            out, buf[0] = buf[0][:n], buf[0][n:]
            return out

        def send(op, payload, fin=True):
            with lk:
                c.sendall(bytes([(0x80 if fin else 0) | op]) + ws_frame(op, payload, mask=False)[1:])

        def msg(op, d):
            send(1, json.dumps({"op": op, "d": d}).encode())
        try:
            while b"\r\n\r\n" not in buf[0]:
                buf[0] += c.recv(4096) or b"\r\n\r\n"
            head, buf[0] = buf[0].split(b"\r\n\r\n", 1)
            h = {k.strip().lower(): v.strip() for k, _, v in (x.partition(":") for x in head.decode().split("\r\n")[1:])}
            if "obswebsocket.json" not in h.get("sec-websocket-protocol", ""):
                return c.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            acc = base64.b64encode(hashlib.sha1((h["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
                                                .encode()).digest()).decode()
            c.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {acc}\r\nSec-WebSocket-Protocol: obswebsocket.json\r\n\r\n".encode())
            hello = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1, "obsStudioVersion": "30.2.0"}
            salt, challenge = base64.b64encode(secrets.token_bytes(32)).decode(), base64.b64encode(
                secrets.token_bytes(32)).decode()
            if self.password:
                hello["authentication"] = {"salt": salt, "challenge": challenge}
            raw = json.dumps({"op": 0, "d": hello}).encode()
            send(1, raw[:10], fin=False)  # in three pieces, a ping in between: as a real server may
            send(9, b"are you there")
            send(0, raw[10:20], fin=False)
            send(0, raw[20:])
            pongs, ident = [], False
            while True:
                op, data = ws_read(recv, lambda o, d: pongs.append(d) if o == 10 else None, masked=True)
                if op == 8:
                    return
                m = json.loads(data)
                if m["op"] == 1:
                    if self.password and m["d"].get("authentication") != obs_auth(self.password, salt, challenge):
                        send(8, struct_pack_close(4009, "Authentication failed."))
                        return
                    assert pongs == [b"are you there"], pongs  # the client answered the ping
                    msg(2, {"negotiatedRpcVersion": 1})
                    ident = True
                    with self.lock:
                        self.conns.append((c, lk))
                elif m["op"] == 6 and ident and not self.silent:
                    d = m["d"]
                    ok, resp, events = self._handle(d["requestType"], d.get("requestData") or {})
                    out = {"requestType": d["requestType"], "requestId": d["requestId"],
                           "requestStatus": {"result": ok, "code": 100 if ok else 600, **({} if ok else {"comment": resp})}}
                    if ok:
                        out["responseData"] = resp
                    raw = json.dumps({"op": 7, "d": out}).encode()
                    if d["requestType"] == "GetSceneList":  # a fragmented answer too
                        send(1, raw[:7], fin=False)
                        send(0, raw[7:])
                    else:
                        send(1, raw)
                    for e in events:
                        self.event(*e)
        except (OSError, ValueError, KeyError):
            pass
        finally:
            with self.lock:
                self.conns = [x for x in self.conns if x[0] is not c]
            c.close()

    def _handle(self, t, d):
        with self.lock:
            self.requests.append((t, d))
        if self.log:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(json.dumps([t, d]) + "\n")
        inp = self.inputs.get(d.get("inputName"))
        audio = inp and "muted" in inp
        if t == "GetSceneList":
            return True, {"currentProgramSceneName": self.scene, "scenes": [
                {"sceneName": n, "sceneIndex": i} for i, n in enumerate(reversed(self.scenes))]}, []
        if t == "SetCurrentProgramScene":
            if d.get("sceneName") not in self.scenes:
                return False, "No source was found by the name of `sceneName`.", []
            self.scene = d["sceneName"]
            return True, {}, [("CurrentProgramSceneChanged", {"sceneName": self.scene})]
        if t == "GetSceneItemList":
            return True, {"sceneItems": [dict(i, inputKind=self.inputs.get(i["sourceName"], {}).get("kind"))
                                         for i in self.items.get(d.get("sceneName"), [])]}, []
        if t == "SetSceneItemEnabled":
            it = next((i for i in self.items.get(d.get("sceneName"), []) if i["sceneItemId"] == d.get("sceneItemId")),
                      None)
            if not it:
                return False, "No scene item", []
            it["sceneItemEnabled"] = bool(d["sceneItemEnabled"])
            return True, {}, [("SceneItemEnableStateChanged", {"sceneName": d["sceneName"], "sceneItemId":
                                                                it["sceneItemId"], "sceneItemEnabled": it["sceneItemEnabled"]})]
        if t == "GetInputList":
            return True, {"inputs": [{"inputName": n, "inputKind": i["kind"]} for n, i in self.inputs.items()]}, []
        if t in ("GetInputMute", "GetInputVolume", "SetInputMute", "SetInputVolume") and not audio:
            return False, "The specified input does not support audio.", []
        if t == "GetInputMute":
            return True, {"inputMuted": inp["muted"]}, []
        if t == "GetInputVolume":
            return True, {"inputVolumeMul": inp["mul"], "inputVolumeDb": 0.0}, []
        if t == "SetInputMute":
            inp["muted"] = bool(d["inputMuted"])
            return True, {}, [("InputMuteStateChanged", {"inputName": d["inputName"], "inputMuted": inp["muted"]})]
        if t == "SetInputVolume":
            inp["mul"] = float(d["inputVolumeMul"])
            return True, {}, []
        if t == "GetInputSettings":
            return (True, {"inputKind": inp["kind"], "inputSettings": inp["settings"]}, []) if inp else (
                False, "No input", [])
        if t == "SetInputSettings":
            if not inp:
                return False, "No input", []
            inp["settings"].update(d["inputSettings"])
            return True, {}, []
        if t == "CreateInput":
            if d["inputName"] in self.inputs or d.get("sceneName") not in self.scenes:
                return False, "A source already exists by that input name." if d["inputName"] in self.inputs \
                    else "No scene", []
            new = {"kind": d["inputKind"], "settings": dict(d.get("inputSettings") or {})}
            if d["inputKind"] == "ffmpeg_source":
                new.update(muted=False, mul=1.0, media="playing")
            self.inputs[d["inputName"]] = new
            items = self.items[d["sceneName"]]
            items.append({"sceneItemId": max([i["sceneItemId"] for i in items] + [0]) + 1,
                          "sourceName": d["inputName"], "sceneItemEnabled": True})
            url = new["settings"].get("input") or new["settings"].get("url")
            if url and not new["settings"].get("is_local_file"):
                import threading
                threading.Thread(target=self._play, args=(d["inputName"], url), daemon=True).start()
            return True, {"sceneItemId": items[-1]["sceneItemId"]}, []
        if t == "TriggerMediaInputAction":
            if not inp or "media" not in inp:
                return False, "Not a media input", []
            act = d["mediaAction"].rsplit("_", 1)[-1].lower()
            inp["media"] = {"play": "playing", "pause": "paused", "restart": "playing", "stop": "stopped"}[act]
            return True, {}, []
        if t == "GetMediaInputStatus":
            return (True, {"mediaState": f"OBS_MEDIA_STATE_{inp['media'].upper()}"}, []) if inp and "media" in inp \
                else (False, "Not a media input", [])
        for k, (start, stop_, get) in {"stream": ("StartStream", "StopStream", "GetStreamStatus"),
                                       "record": ("StartRecord", "StopRecord", "GetRecordStatus"),
                                       "vcam": ("StartVirtualCam", "StopVirtualCam", "GetVirtualCamStatus")}.items():
            if t == get:
                return True, {"outputActive": self.outputs[k]}, []
            if t in (start, stop_):
                if self.outputs[k] == (t == start):
                    return False, "The output is already running." if t == start else "The output is not running.", []
                self.outputs[k] = t == start
                return True, {}, [({"stream": "StreamStateChanged", "record": "RecordStateChanged",
                                    "vcam": "VirtualcamStateChanged"}[k], {"outputActive": self.outputs[k]})]
        return False, f"Your request type is not valid: {t}", []

    def _play(self, name, url):
        """Opens a stream like OBS's Media / Browser Source does, keeping what it hears (up to 2 MB)."""
        got = self.heard.setdefault(name, bytearray())
        try:
            with link_noproxy().open(url, timeout=15) as r:
                while len(got) < 2_000_000:
                    b = r.read(4096)
                    if not b:
                        break
                    got += b
        except OSError:
            pass


def relay(port):
    """A TCP relay on 127.0.0.1 to port that keeps everything it carries (.heard): what someone listening on the
    network would see. .close() stops it."""
    import socket
    import threading
    import types
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen(8)
    r = types.SimpleNamespace(heard=[], getsockname=ls.getsockname, close=ls.close)

    def pipe(a, b):
        try:
            while data := a.recv(65536):
                r.heard.append(data)
                b.sendall(data)
        except OSError:
            pass
        finally:
            for s_ in (a, b):
                try:
                    s_.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def serve():
        while True:
            try:
                c, _ = ls.accept()
                u = socket.create_connection(("127.0.0.1", port), timeout=30)
            except OSError:
                return
            for a, b in ((c, u), (u, c)):
                threading.Thread(target=pipe, args=(a, b), daemon=True).start()
    threading.Thread(target=serve, daemon=True).start()
    return r


def struct_pack_close(code, why):
    import struct
    return struct.pack(">H", code) + why.encode()


def selftest():
    import copy
    import tempfile
    import wave

    def write_wav(path, chans):
        pcm = (np.stack(chans, 1) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(len(chans)), w.setsampwidth(2), w.setframerate(44100), w.writeframes(pcm.tobytes())

    t = np.arange(44100) / 44100
    loud, quiet = 0.8 * np.sin(2 * np.pi * 440 * t), 0.05 * np.sin(2 * np.pi * 660 * t)
    with tempfile.TemporaryDirectory() as d:
        st, mono = Path(d) / "st.wav", Path(d) / "mono.wav"
        write_wav(st, [loud, quiet])
        write_wav(mono, [loud])
        (Path(d) / "notes.txt").write_text("x")
        for raw, want in (("air_horn", "Air Horn"), ("bruh-sound-effect", "Bruh Sound Effect"),
                          ("y2mate.com - Oh No No No (128 kbps)", "Oh No No No"), ("AirHorn", "Air Horn"),
                          ("vine boom", "Vine Boom"), ("01 - Intro", "Intro"), ("hello ,world !", "Hello, World!"),
                          ("Taco Bell [Official Audio]", "Taco Bell"), ("my%20clip", "My Clip"),
                          ("MLG", "MLG"), ("iPhone ding", "iPhone ding"), ("don't  stop", "Don't Stop"),
                          ("sad_trombone_extended_version_final", "Sad Trombone"), ("___", "___"), ("2", "2"),
                          ("Air-horn", "Air-horn"), ("a (b) c", "A (B) C")):
            assert clean_name(raw) == want, (raw, clean_name(raw), want)
        assert all(len(clean_name(x * 9)) <= 20 for x in ("ab ", "abcdefgh", "a_b-"))
        assert media_files([d, st]) == [mono, st, st]  # folder -> media only, sorted; files pass through
        song = Path("C:/music/album/song.mp3")
        assert out_folder(song) == Path("C:/music/album") / OUT_SUBDIR
        assert out_folder(song, "D:/out") == Path("D:/out/album")
        info, rms, _ = analyze(st)
        assert pick_source(rms, "Auto (loudest)") == (0, True), rms
        assert pick_source(rms, "R") == (1, False)

        # planning: single source keeps plain names; all sources x all targets = 6 unique files (Auto==L merged)
        assert [j[2] for j in plan_jobs(st, rms, ["R"], ["left"])] == ["st_left.wav"]
        every = plan_jobs(st, rms, list(SOURCES), list(TARGETS.values()))
        assert len(every) == 6 and len({j[2] for j in every}) == 6, every
        assert len(plan_jobs(mono, rms[:1], list(SOURCES), ["both"])) == 1  # mono: all sources are the same channel

        cases = [(st, 0, "both", [rms[0], rms[0]]), (st, 0, "left", [rms[0], 0]),
                 (st, 0, "right", [0, rms[0]]), (st, 1, "left", [rms[1], 0]),
                 (mono, 0, "right", [0, rms[0]])]
        for src, ch, target, want in cases:
            dst = Path(d) / f"out_{ch}_{target}_{src.name}"
            route(src, dst, probe(src), ch, target)
            info2, got, _ = analyze(dst)
            assert info2["channels"] == 2 and info2["codec_name"] == "pcm_s16le", info2
            assert np.allclose(got, want, atol=1e-3), (src.name, ch, target, got, want)
            assert all(g == 0 for g, w in zip(got, want) if w == 0), "cleared channel not fully silent"
        assert np.allclose(analyze(st)[1], rms), "source was modified"

        # video input: "same" keeps the video stream, "audio only" writes an .m4a with no video
        vid = Path(d) / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=1",
                        "-f", "lavfi", "-i", "sine=f=440:d=1", "-f", "lavfi", "-i", "sine=f=660:d=1",
                        "-filter_complex", "[1][2]amerge=inputs=2,pan=stereo|c0=0.8*c0|c1=0.05*c1[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "mpeg4", "-c:a", "aac", str(vid)],
                       check=True, creationflags=NO_WINDOW)
        kinds = lambda p: sorted(s["codec_type"] for s in json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(p)],
            capture_output=True, text=True, creationflags=NO_WINDOW).stdout)["streams"])
        vinfo, vrms, _ = analyze(vid)
        assert int(np.argmax(vrms)) == 0, vrms
        assert out_ext(st, info, "audio") == ".wav"  # audio inputs keep their own extension
        # every output type from a video: video formats keep the picture, audio formats drop it
        for mode, ext, want in (("same", ".mp4", ["audio", "video"]), ("audio", ".m4a", ["audio"]),
                                ("mkv", ".mkv", ["audio", "video"]), ("mov", ".mov", ["audio", "video"]),
                                *((m, "." + m, ["audio"]) for m in ("wav", "mp3", "flac", "m4a", "ogg", "opus",
                                                                       "aiff"))):
            assert out_ext(vid, vinfo, mode) == ext
            dst = route(vid, Path(d) / out_name(vid, "right", ext=ext), vinfo, 0, "right", mode)
            assert dst.suffix == ext and kinds(dst) == want, (dst.name, kinds(dst))
            got = analyze(dst)[1]
            assert got[0] < 1e-4 and abs(got[1] - vrms[0]) < 0.02, (dst.name, got, vrms)

        # any file ffmpeg can read works; an extension ffmpeg can't write falls back to .mkv instead of failing
        odd = Path(d) / "st.xyz"
        odd.write_bytes(st.read_bytes())
        oinfo = analyze(odd)[0]
        dst = route(odd, Path(d) / out_name(odd, "left"), oinfo, 0, "left")
        assert dst.suffix == ".mkv" and kinds(dst) == ["audio"], dst

        # length: exact cut, looping past the end, and ending at the quiet gap instead of mid-tone
        assert parse_time("") is None and parse_time("1:30") == 90 and parse_time("12.5") == 12.5
        assert clip_seconds(st, info, 0, 5) is None  # longer than the file without loop = whole file
        for secs, loop in ((0.5, False), (2.5, True)):
            out = route(st, Path(d) / f"len{secs}.wav", info, 0, "both", "same", secs, loop)
            assert abs(analyze(out)[0]["duration"] - secs) < 0.01, (secs, analyze(out)[0]["duration"])
        gap = Path(d) / "gap.wav"  # tone 0-1 s, silence 1-1.2 s, tone 1.2-2.2 s
        tone = np.concatenate([loud, np.zeros(8820), loud])
        write_wav(gap, [tone, tone])
        ginfo = analyze(gap)[0]
        cut = clip_seconds(gap, ginfo, 0, 2.0, quiet=True)
        assert 1.0 <= cut <= 1.2, cut
        assert clip_seconds(gap, ginfo, 0, 2.0) == 2.0
        cut = clip_seconds(gap, ginfo, 0, 4.4, loop=True, quiet=True)  # 2nd pass's gap sits at 3.2-3.4 s
        assert 3.2 <= cut <= 3.4, cut

        # split: cuts land mid-silence (gap 1.0-1.2 s -> 1.1); no silence at the file's edges = whole file used
        for segs in (split_points(gap, ginfo, 0, 1.5), split_points(gap, ginfo, 0, count=2)):
            assert len(segs) == 2 and segs[0][0] == 0 and abs(segs[1][0] - 1.1) < 0.03 and segs[1][1] is None, segs
        segs = split_points(gap, ginfo, 0, 0.5, 3)  # first 3 parts of <= 0.5 s, even through unbroken sound
        assert len(segs) == 3 and all(0 < s <= 0.5 for _, s in segs), segs
        # silence 0-0.4, tone, silence 1.4-1.6, tone, silence 2.6-3.0: parts run 0.2-1.5 and 1.5-2.8 (silence middles)
        pad = Path(d) / "pad.wav"
        sil = lambda secs: np.zeros(int(44100 * secs))
        ptone = np.concatenate([sil(0.4), loud, sil(0.2), loud, sil(0.4)])
        write_wav(pad, [ptone, ptone])
        pinfo = analyze(pad)[0]
        for segs in (split_points(pad, pinfo, 0, 1.5), split_points(pad, pinfo, 0, count=2)):
            assert np.allclose(segs, [(0.2, 1.3), (1.5, 1.3)], atol=0.03), segs
        for start, secs, want in ((0.5, 0.5, 0.5), (1.1, None, 1.1)):  # a middle part and the last part
            out = route(gap, Path(d) / f"part{start}.wav", ginfo, 0, "both", "same", secs, start=start)
            assert abs(analyze(out)[0]["duration"] - want) < 0.01, (start, analyze(out)[0]["duration"])

        # first-run ffmpeg install: unpacks the two exes from a checksum-verified zip, refuses a damaged one
        import hashlib
        import zipfile
        z = Path(d) / "ff.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("ffmpeg-x/bin/ffmpeg.exe", "A"), zf.writestr("ffmpeg-x/bin/ffprobe.exe", "B")
        good = hashlib.sha256(z.read_bytes()).hexdigest()
        sha = Path(d) / "ff.zip.sha256"
        sha.write_text(good + "  ff.zip\n")
        dest = Path(d) / "ffdl"
        download_ffmpeg(lambda m: None, z.as_uri(), dest)
        assert (dest / "ffmpeg.exe").read_text() == "A" and (dest / "ffprobe.exe").read_text() == "B"
        sha.write_text("0" * 64)
        try:
            download_ffmpeg(lambda m: None, z.as_uri(), Path(d) / "bad")
            raise AssertionError("damaged download was accepted")
        except RuntimeError:
            assert not (Path(d) / "bad").exists()

        # Stream Deck: key parsing, mapping, profile package, device discovery
        assert sd_key("2,3", 5, 3) == (1, 2) and sd_key(" ", 5, 3) is None
        for bad in ("6,1", "x"):
            try:
                sd_key(bad, 5, 3)
                raise AssertionError(bad)
            except ValueError:
                pass
        snd = lambda p, key="": {"path": p, "title": Path(p).stem, "key": key, "mode": "Loop / Stop",
                                 "fade": "Fade In", "fade_len": "2", "volume": 80, "output": ""}
        sounds = [snd(st, "1,1"), snd(mono, "1,1"), snd(gap), snd(pad, "2,1")]
        keys = {"1,1": {"kind": "Random Action", "title": "Folder"}}
        lay = sd_layout(sounds, keys, 2, 2)
        assert lay[(0, 0)][:2] == ("Random Action", "Folder") and len(lay[(0, 0)][2]) == 2
        assert lay[(1, 0)][2][0]["title"] == "pad" and lay[(0, 1)][2][0]["title"] == "gap"  # unmapped -> next free
        for bad_keys, bad_sounds in (({}, sounds), (keys, sounds + [snd(st), snd(st)])):  # 2 on single / deck full
            try:
                sd_layout(bad_sounds, bad_keys, 2, 2)
                raise AssertionError("bad layout accepted")
            except ValueError:
                pass
        prof = sd_profile(Path(d) / "sd" / "t.streamDeckProfile", "T", ("20GBA9901", "@(1)[4057/128/X]", 2, 2),
                          sounds, keys)
        with zipfile.ZipFile(prof) as zf:
            names = zf.namelist()
            top = json.loads(zf.read(next(n for n in names if n.count("/") == 2 and n.endswith("manifest.json"))))
            page = json.loads(zf.read(next(n for n in names if top["Pages"]["Pages"][0].upper() in n)))
            res = json.loads(zf.read("Resources/manifest.json"))["resources"]
            acts = page["Controllers"][0]["Actions"]
            rnd = acts["0,0"]
            assert rnd["UUID"] == SD_KINDS["Random Action"] and rnd["States"][0]["Title"] == "Folder"
            inner = rnd["Actions"][0]["Actions"]
            assert len(inner) == 2 and inner[0]["Settings"] == {
                "actionType": 3, "fadeLen": 2, "fadeType": 1, "outputType": "", "path": str(st.resolve()), "volume": 80}
            assert acts["1,0"]["UUID"].endswith("playaudio") and set(acts) == {"0,0", "1,0", "0,1"}
            assert len(res) == 4 and all(f"Resources/{v['file']}" in names for v in res.values())
            assert top["Device"]["UUID"] == "@(1)[4057/128/X]"
        fake = Path(d) / "SD" / "ProfilesV3" / "A.sdProfile"
        (fake / "Profiles" / "P").mkdir(parents=True)
        (fake / "manifest.json").write_text(json.dumps({"Name": "Mine", "Device": {
            "Model": "20GBA9901", "UUID": "@(1)[4057/128/AB12]"}}))
        (fake / "Profiles" / "P" / "manifest.json").write_text(json.dumps({"Controllers": [
            {"Type": "Keypad", "Actions": {"4,2": {}}}, {"Type": "Encoder", "Actions": {"9,9": {}}}]}))
        devs = sd_devices(Path(d) / "SD", {"USB\\VID_0FD9&PID_0080\\AB12"})
        assert list(devs.values()) == [("20GBA9901", "@(1)[4057/128/AB12]", 5, 3)], devs
        assert next(iter(devs)).startswith("[connected]")

        # editing installed profiles: nested sounds, purpose/volume/label edits, arranging, relink, backup + save
        files, _ = sd_profile_files("E", ("20GBA9901", "x", 2, 2), sounds, keys)
        pg = next(v for a, v in files.items() if a.count("/") == 4 and v.get("Name") == "E")
        kp = sd_keypad(pg)
        assert [len(sd_sounds(kp[k])) for k in ("0,0", "1,0", "0,1")] == [2, 1, 1]
        assert sd_kind(kp["0,0"]) == "Random x2" and sd_kind(kp["1,0"]) == "Sound" and not sd_missing(kp["0,0"])
        allsnd = [s for a in kp.values() for s in sd_sounds(a)]
        sd_set_sound(allsnd, *SD_GOALS["Ambience bed (quiet loop, slow fades)"])
        assert {(s["Settings"]["actionType"], s["Settings"]["fadeType"], s["Settings"]["fadeLen"],
                 s["Settings"]["volume"]) for s in allsnd} == {(3, 3, 5, 35)}
        sd_set_sound(allsnd, step=-50)
        assert {s["Settings"]["volume"] for s in allsnd} == {0}  # clamped
        sd_set_sound(allsnd, volume=100)
        lv = {s["Settings"]["path"]: v for s, v in zip(allsnd, (-10.0, -20.0, -20.0, -26.0))}
        assert sd_match_loudness(allsnd, lv) == 4
        assert [s["Settings"]["volume"] for s in allsnd] == [16, 50, 50, 100]  # -16 dB, -6 dB, -6 dB; quietest (-26 dB) plays at full
        sd_match_loudness(allsnd, lv, SD_LEVELS["effect"])
        assert [s["Settings"]["volume"] for s in allsnd] == [32, 100, 100, 100]  # -10 dB file -> -10 dB; -26 dB can't be boosted
        # listening: silence ignored, loudest channel used, kind detected; tuning by kind, within 2 dB left alone
        a20 = 10 ** (-20 / 20) * np.sqrt(3)  # uniform noise of RMS -20 dBFS
        ph = "2*PI*(150*t-40/(2*PI*0.7)*cos(2*PI*0.7*t))"  # a voice-like buzz gliding 110-190 Hz, in syllables
        buzz = "+".join(f"sin({k}*{ph})/{k}" for k in range(1, 6))
        gen = {"fx.wav": f"aevalsrc='{a20}*(2*random(0)-1)*lt(t,1)|{a20 / 10}*(2*random(1)-1)*lt(t,1)':d=4",
               "vo.wav": f"aevalsrc='0.3*({buzz})*gt(sin(2*PI*3*t),-0.3)':d=3",
               "bed.wav": "aevalsrc='0.08*sin(2*PI*440*t)':d=35"}
        for name, src in gen.items():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src + ":s=44100", str(Path(d) / name)],
                           check=True, creationflags=NO_WINDOW)
        h = {n: sd_listen(Path(d) / n) for n in gen}
        assert abs(h["fx.wav"]["level"] + 20) < 0.5 and h["fx.wav"]["kind"] == "effect", h["fx.wav"]  # not -26 (silence)
        assert h["vo.wav"]["kind"] == "voice" and h["bed.wav"]["kind"] == "music / ambience", h
        snd = [sd_play(Path(d) / n, n) for n in gen] + [sd_play(Path(d) / "gone.wav", "gone")]
        heard = {str(Path(d) / n): v for n, v in h.items()}
        snd[1]["Settings"]["volume"] = round(100 * 10 ** ((-16.5 - h["vo.wav"]["level"]) / 20))  # plays at -16.5: in range
        rows = sd_level_rows(snd, heard)
        assert [r["target"] for r in rows] == [-20.0, -16.0, -30.0, None]
        assert [r["verdict"].split(":")[0] for r in rows] == ["in range", "in range", "too loud", "file missing"], rows
        bed = h["bed.wav"]["level"]  # -25 dB file -> about 56 to land on -30
        assert rows[2]["new"] == round(100 * 10 ** ((-30 - bed) / 20)) and abs(bed + 24.9) < 0.3
        rows = sd_level_rows(snd, heard, "Everything at my music / ambience level")  # one fixed target for all
        assert {r["target"] for r in rows[:3]} == {-30.0} and rows[0]["new"] == 32
        # my own OBS levels replace the defaults; bad values fall back
        assert sd_set_levels({"voice": -12, "effect": "x", "music / ambience": 5}) == {
            "voice": -12.0, "effect": -20.0, "music / ambience": -30.0}
        assert sd_level_rows(snd, heard)[1]["target"] == -12.0
        sd_set_levels(None)
        assert SD_LEVELS == SD_OBS_DEFAULT
        sd_label(kp["1,0"], "File name", "> ", "!", "a", "A", {"FontSize": 14})
        assert kp["1,0"]["States"][0] == {"Title": "> PAd!", "FontSize": 14}
        sd_move(kp, "1,0", "0,1")  # swap
        assert sd_title(kp["0,1"]) == "> PAd!" and sd_title(kp["1,0"]) == "gap"
        sd_combine(kp, ["1,0", "0,1"], "Multi Action", "Both")
        assert sd_kind(kp["1,0"]) == "Multi x2" and "0,1" not in kp
        kp["1,1"] = sd_stop_key()
        try:
            sd_combine(kp, ["1,0", "1,1"], "Random Action", "")
            raise AssertionError("combined a non-sound key")
        except ValueError:
            pass
        assert sd_split(kp, "0,0", 2, 2) == 2 and set(kp) == {"0,0", "0,1", "1,0", "1,1"}
        assert sd_kind(kp["0,1"]) == "Sound" and sd_title(kp["0,1"]) == "mono"
        kp["0,1"]["Settings"]["path"] = "/Users/someone/Downloads/mono.wav"  # a profile copied from a Mac
        assert sd_missing(kp["0,1"]) and sd_relink(sd_sounds(kp["0,1"]), d) == (1, 0)
        assert Path(kp["0,1"]["Settings"]["path"]) == mono
        root = Path(d) / "SD"
        writes = sd_install("New", ("20GBA9901", "x", 2, 2), sounds, keys, root)
        assert all(str(p).startswith(str(root / "ProfilesV3")) for p in writes) and len(writes) == 3
        assert sd_save(writes, [], root, Path(d) / "bk") is None  # nothing old to back up
        got = sd_profiles(root)
        assert sorted(m["Name"] for _, m in got) == ["Mine", "New"]
        new_dir, new_m = next(x for x in got if x[1]["Name"] == "New")
        assert [n for n, _ in sd_pages(new_dir, new_m)] == ["Page 1"]  # the empty default page isn't shown
        pages = [p for _, p in sd_pages(new_dir, new_m)]
        assert len(sd_keypad(json.loads(pages[0].read_text()))) == 3
        sub = pages[0].parents[1] / "ABCD1234" / "manifest.json"  # a folder key on page 1 opens this page
        sub.parent.mkdir()
        sub.write_text("{}")
        p1 = json.loads(pages[0].read_text())
        sd_keypad(p1)["1,1"] = {"UUID": "com.elgato.streamdeck.profile.openchild", "States": [{"Title": "SFX"}],
                                "Settings": {"ProfileUUID": "abcd1234"}}
        pages[0].write_text(json.dumps(p1))
        assert [n for n, _ in sd_pages(new_dir, new_m)] == ["Page 1", "Folder: SFX"]

        # adding sounds to keys that already exist, and new folders filled in order
        assert sorted(["t10.wav", "T2.wav", "t1.wav"], key=natural) == ["t1.wav", "T2.wav", "t10.wav"]
        assert sorted(["1²2.wav", "a.wav"], key=natural)  # superscript digits aren't numbers: no crash
        one = sd_play(st, "st", "Loop / Stop", "Fade In", 3, 40, "")
        more = sd_plays_like([mono, st], one)
        assert [sd_title(x) for x in more] == ["Mono", "St"]  # named after their files, cleaned
        assert {(x["Settings"]["actionType"], x["Settings"]["volume"]) for x in more} == {(3, 40)}
        one["States"][0]["FontSize"] = 9
        rk = sd_add_sounds(one, more[:1], "Random Action")  # a single sound becomes a Random Action, look kept
        assert sd_kind(rk) == "Random x2" and rk["States"] == [{"Title": "st", "FontSize": 9}]
        assert sd_add_sounds(rk, more[1:]) is rk and sd_kind(rk) == "Random x3"  # Random / Multi just grow
        assert [Path(x["Settings"]["path"]).name for x in sd_sounds(rk)] == ["st.wav", "mono.wav", "st.wav"]
        assert sd_free({"0,0": None, "1,0": {}, "0,1": one}, 2, 2) == ["0,0", "1,0", "1,1"]  # saved-empty = free
        kp2 = {"1,0": sd_stop_key()}
        left = sd_fill(kp2, [sd_play(st, f"s{i}") for i in range(4)], 3, 2, start="2,0")
        assert {k: sd_title(a) for k, a in kp2.items() if a["UUID"] == SD_PLAY} == {"2,0": "s0", "0,1": "s1",
                                                                                     "1,1": "s2", "2,1": "s3"}
        assert left == [] and sd_fill(kp2, [one, rk], 3, 2) == [rk] and kp2["0,0"] is one  # full: the rest comes back
        key, pid, fpage, left = sd_folder("Hits", [sd_play(st, f"h{i}") for i in range(3)], 2, 2)
        fkp = sd_keypad(fpage)
        assert key["UUID"] == SD_FOLDER and key["Settings"]["ProfileUUID"] == pid and sd_title(key) == "Hits"
        assert fkp["0,0"]["UUID"] == SD_PARENT and [sd_title(fkp[k]) for k in ("1,0", "0,1", "1,1")] == [
            "h0", "h1", "h2"] and left == []
        assert len(sd_folder("x", [one] * 5, 2, 2)[3]) == 2  # 3 keys after the Parent Folder key
        # more sounds than a folder holds: as many folders as needed, numbered, each page full in order
        many = [sd_play(st, f"m{i}") for i in range(8)]
        chain = sd_folders("Hits", many, 2, 2)
        assert [sd_title(k) for k, _, _ in chain] == ["Hits", "Hits 2", "Hits 3"]
        assert [sd_title(a) for _, _, pg in chain for k, a in sorted(sd_keypad(pg).items(), key=lambda x: sd_order(
            x[0])) if a["UUID"] == SD_PLAY] == [f"m{i}" for i in range(8)]
        assert [sd_title(k) for k, _, _ in sd_folders("SFX", many[:2], 2, 2, 4)] == ["SFX 4"]  # carrying on
        assert [sd_title(k) for k, _, _ in sd_folders("D", many[:7], 2, 2, 2, {"D 2", "D 4"})] == [
            "D 3", "D 5", "D 6"]  # names already on the page are skipped, every time
        assert sd_title(sd_folders("D", many[:1], 2, 2, taken={"D"})[0][0]) == "D 2"
        try:
            sd_folders("x", many, 1, 1)  # a 1-key deck has no room beside the Parent Folder key
            raise AssertionError("looped on a 1x1 deck")
        except ValueError:
            pass
        # a folder of folders: its own sounds first (named after it), then each subfolder's, in name order
        lib = Path(d) / "lib"
        for sub, names in (("10 memes", ["z.wav"]), ("2 drums", ["k10.wav", "k2.wav"]), ("empty", []), ("", ["top.wav"])):
            (lib / sub).mkdir(parents=True, exist_ok=True)
            for n in names:
                shutil.copy2(mono, lib / sub / n)
        (lib / "empty" / "readme.txt").write_text("x")
        assert [(n, [f.name for f in fs]) for n, fs in sound_folders(lib)] == [
            ("lib", ["top.wav"]), ("2 drums", ["k2.wav", "k10.wav"]), ("10 memes", ["z.wav"])]
        # pasting a folder key copies the pages it opens (folders in folders too) under new ids
        inner_key, inner_id, inner_pg, _ = sd_folder("In", [sd_play(st, "deep")], 2, 2)
        outer_key, outer_id, outer_pg, _ = sd_folder("Out", [sd_play(st, "top")], 2, 2)
        sd_keypad(outer_pg)["1,1"] = inner_key
        sd_keypad(inner_pg)["1,1"] = copy.deepcopy(outer_key)  # a loop back out: copied once, not forever
        pasted = copy.deepcopy(outer_key)
        made = sd_clone_folders(pasted, {outer_id: outer_pg, inner_id: inner_pg})
        new_out = pasted["Settings"]["ProfileUUID"]
        assert len(made) == 2 and new_out in made and new_out != outer_id and outer_key["Settings"]["ProfileUUID"] == outer_id
        new_in = sd_keypad(made[new_out])["1,1"]["Settings"]["ProfileUUID"]
        assert new_in in made and new_in != inner_id and sd_title(sd_keypad(made[new_in])["1,0"]) == "deep"
        assert sd_keypad(made[new_out])["1,0"]["ActionID"] != sd_keypad(outer_pg)["1,0"]["ActionID"]  # its own keys
        assert sd_keypad(outer_pg)["1,1"]["Settings"]["ProfileUUID"] == inner_id  # the source is left as it was
        assert sd_clone_folders(sd_stop_key(), {}) == {} and sd_clone_folders(copy.deepcopy(outer_key), {}) == {}
        # the loop key inside the copy points at the copy, not the original; two keys opening one folder share a copy
        assert sd_keypad(made[new_in])["1,1"]["Settings"]["ProfileUUID"] == new_out
        sd_keypad(outer_pg)["0,1"] = copy.deepcopy(inner_key)
        pasted = copy.deepcopy(outer_key)
        made = sd_clone_folders(pasted, {outer_id: outer_pg, inner_id: inner_pg})
        kp_out = sd_keypad(made[pasted["Settings"]["ProfileUUID"]])
        assert len(made) == 2 and kp_out["0,1"]["Settings"]["ProfileUUID"] == kp_out["1,1"]["Settings"]["ProfileUUID"]
        # pages a profile can still open: from pages on disk through folder keys; an unreachable loop is not
        reach = {"a": {"Controllers": [{"Type": "Keypad", "Actions": {"0,0": {"UUID": SD_FOLDER, "Settings": {
            "ProfileUUID": "B"}}}}]}, "b": {},  # ids compared lower-case, as Stream Deck writes them
            "x": {"Controllers": [{"Actions": {"0,0": {"UUID": SD_FOLDER, "Settings": {"ProfileUUID": "y"}}}}]},
            "y": {"Controllers": [{"Actions": {"0,0": {"UUID": SD_FOLDER, "Settings": {"ProfileUUID": "x"}}}}]}}
        assert sd_reachable(["a"], reach) == {"a", "b"}
        (lib / "locked").mkdir()
        real_iterdir = Path.iterdir

        def deny(p):
            if p.name == "locked":
                raise PermissionError(p)
            return real_iterdir(p)
        Path.iterdir = deny
        try:  # e.g. System Volume Information under a drive root: skipped, not a crash
            assert [n for n, _ in sound_folders(lib)] == ["lib", "2 drums", "10 memes"]
        finally:
            Path.iterdir = real_iterdir
        # sounds per folder: fewer than a page holds, the rest carry on into the next folders
        per3 = sd_folders("P", many, 3, 3, per=3)  # a 3x3 page holds 8; 3 per folder -> 3 folders for 8 sounds
        assert [sum(a["UUID"] == SD_PLAY for a in sd_keypad(pg).values()) for _, _, pg in per3] == [3, 3, 2]
        assert sd_folder("x", many, 3, 3, per=2)[3] == many[2:]
        # volume scaled by a percentage, kept within 0-100
        vs = [sd_play(st, volume=v) for v in (80, 50, 100)]
        sd_set_sound(vs, scale=50)
        assert [x["Settings"]["volume"] for x in vs] == [40, 25, 50]
        sd_set_sound(vs, scale=300)
        assert [x["Settings"]["volume"] for x in vs] == [100, 75, 100]
        # a new profile with every sound on its own key, in folders of 2 (the soundboard tab's folder option)
        fsnd = [{"path": st, "title": f"f{i}", "key": "", "mode": "Loop / Stop", "fade": "No Fade", "fade_len": 1,
                 "volume": 90, "output": ""} for i in range(5)]
        files_, res_ = sd_profile_files("Fold", ("20GBA9901", "x", 2, 2), fsnd, {}, folders={"title": "Box", "per": 2})
        pgs = {k: v for k, v in files_.items() if k.endswith("manifest.json") and "Controllers" in v}
        top = next(v for v in pgs.values() if v.get("Name") == "Fold")
        boxes = {k: a for k, a in sd_keypad(top).items()}
        assert [sd_title(boxes[k]) for k in sorted(boxes, key=sd_order)] == ["Box", "Box 2", "Box 3"]
        inner_pages = [pgs[k] for k in pgs if any(a["Settings"]["ProfileUUID"].upper() in k for a in boxes.values())]
        assert sorted(sum(a["UUID"] == SD_PLAY for a in sd_keypad(p).values()) for p in inner_pages) == [1, 2, 2]
        assert all(a["Resources"] for p in inner_pages for a in sd_keypad(p).values() if a["UUID"] == SD_PLAY)
        assert {a["Settings"]["actionType"] for p in inner_pages for a in sd_keypad(p).values()
                if a["UUID"] == SD_PLAY} == {SD_MODES.index("Loop / Stop")}
        try:
            sd_profile_files("F", ("m", "x", 2, 1), fsnd, {}, folders={"title": "B", "per": 1})  # 5 folders, 2 keys
            raise AssertionError("more folders than keys")
        except ValueError:
            pass
        # VTube Studio backgrounds: copied in (same file reused, a different one with the name kept apart), a
        # ChangeBackground hotkey each on the model (existing ones reused), a Stream Deck Trigger Hotkey key each
        vts = Path(d) / "VTS" / "VTube Studio_Data" / "StreamingAssets"
        (vts / "Backgrounds").mkdir(parents=True)
        (vts / "Live2DModels" / "Wolf").mkdir(parents=True)
        model_file = vts / "Live2DModels" / "Wolf" / "Wolf.vtube.json"
        old_hk = dict(VTS_HOTKEY, HotkeyID="a" * 32, File="City", Name="")
        model_file.write_text(json.dumps({"Version": 1, "Name": "Wolf", "ModelID": "m" * 32, "Hotkeys": [old_hk]},
                                         indent=4))
        assert vts_models(vts) == [("Wolf", model_file, "m" * 32)]
        blib = Path(d) / "bgs"
        (blib / "more").mkdir(parents=True)
        (blib / "City.png").write_bytes(b"city")
        (blib / "Room 2.jpg").write_bytes(b"room2")
        (blib / "Room 10.mp4").write_bytes(b"room10")
        (blib / "notes.txt").write_text("x")
        (blib / "more" / "City.png").write_bytes(b"another city")  # same name, different picture
        (vts / "Backgrounds" / "City.png").write_bytes(b"city")  # already in VTube Studio
        picked = vts_files([blib, blib / "more" / "City.png"])
        assert [p.name for p in picked] == ["City.png", "Room 2.jpg", "Room 10.mp4", "City.png"]
        before_bg = sorted(p.name for p in (vts / "Backgrounds").iterdir())
        assert vts_copy(picked, vts / "Backgrounds", dry=True) == ["City", "Room 2", "Room 10", "City (2)"]
        assert sorted(p.name for p in (vts / "Backgrounds").iterdir()) == before_bg  # a dry run copies nothing
        names = vts_copy(picked, vts / "Backgrounds")
        assert names == ["City", "Room 2", "Room 10", "City (2)"]
        assert (vts / "Backgrounds" / "City (2).png").read_bytes() == b"another city"
        assert vts_copy(picked, vts / "Backgrounds") == names  # again: nothing new, same names
        data = json.loads(model_file.read_text())
        ids, added = vts_hotkeys(data, names)
        assert added == 3 and ids["City"] == "a" * 32 and len(set(ids.values())) == 4
        bg_hk = [h for h in data["Hotkeys"] if h["Action"] == "ChangeBackground"]
        assert [h["File"] for h in bg_hk] == ["City", "Room 2", "Room 10", "City (2)"]
        assert all(len(h["HotkeyID"]) == 32 and h["Name"] == h["File"] for h in bg_hk[1:])
        assert vts_hotkeys(data, names) == (ids, 0)  # again: reused, none added
        # hotkeys whose background file isn't in VTube Studio: found by name in other folders (any depth)
        data["Hotkeys"].append(dict(VTS_HOTKEY, HotkeyID="b" * 32, File="(New) Balcony View"))
        data["Hotkeys"].append(dict(VTS_HOTKEY, HotkeyID="c" * 32, File="Gone"))
        assert vts_missing(data, vts / "Backgrounds") == ["(New) Balcony View", "Gone"]
        dl = Path(d) / "Downloads"
        (dl / "deep" / "er").mkdir(parents=True)
        (dl / "deep" / "er" / "(New) Balcony View.MP4").write_bytes(b"balcony")
        (dl / "(New) Balcony View.txt").write_text("not a background")
        assert vts_find(["(New) Balcony View", "Gone"], [dl, Path(d) / "nowhere"]) == {
            "(New) Balcony View": dl / "deep" / "er" / "(New) Balcony View.MP4"}
        vkey = sd_vts_key("m" * 32, ids["Room 2"], "Room 2")
        assert vkey["UUID"] == SD_VTS_HOTKEY and vkey["Settings"] == {
            "modelId": "m" * 32, "hotkeyId": ids["Room 2"], "showName": True} and sd_title(vkey) == "Room 2"
        # links: channelmirror:// links (files / web addresses for a destination), and sending between devices
        lk = link_make("vts", [Path("C:/bg/a b.png")], ["https://x.example/s.mp3"])
        assert lk.startswith("channelmirror://open?") and link_parse(lk) == {
            "to": "vts", "files": [Path("C:/bg/a b.png")], "urls": ["https://x.example/s.mp3"]}
        for bad in ("http://open?to=vts", "channelmirror://open?to=nope&file=C:/a.png",
                    "channelmirror://open?to=vts&file=relative.png", "channelmirror://open?to=vts&url=file:///C:/a"):
            try:
                link_parse(bad)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        assert link_safe_name("..\\..\\Windows\\evil.mp3") == "evil.mp3" and link_safe_name('a:b?.PNG') == "a_b_.png"
        for bad in ("run.exe", "noext", ".."):
            try:
                link_safe_name(bad)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        assert link_private("192.168.1.20") and link_private("10.0.0.5") and link_private("127.0.0.1")
        assert not link_private("8.8.8.8") and not link_private("not an ip")
        for odd in ("169.254.1.1", "240.0.0.1", "0.0.0.1"):  # link-local / reserved: not "the home network"
            assert not link_private(odd), odd
        # security: network-share paths never reach the file system; device names; extra start-up options
        for unc in (r"\\attacker\s\x.mp3", "//attacker/s/x.mp3", r"\\?\C:\a.mp3", r"\\.\C:\a.mp3"):
            try:
                from urllib.parse import quote as _q
                link_parse("channelmirror://open?to=import&file=" + _q(unc))
                raise AssertionError(f"accepted {unc}")
            except ValueError:
                pass
        assert link_safe_name("CON.mp3") == "_CON.mp3" and link_safe_name("lpt1.wav") == "_lpt1.wav"
        assert link_args(["channelmirror://open?to=vts&file=C:/a.png", "--uninstall", "--quiet", "x.mp3"]) == \
            "channelmirror://open?to=vts&file=C:/a.png" and link_args(["--install"]) is None
        test_key = r"Software\Classes\channelmirror-selftest"
        link_register(Path("C:/apps/ChannelMirror.exe"), test_key)
        assert link_registered(test_key) == '"C:\\apps\\ChannelMirror.exe" "%1"'
        link_unregister(test_key)
        assert link_registered(test_key) is None
        # a real send / receive on this PC: right code in, wrong code / file type / path trick out
        batches = []
        srv = LinkServer(0, "123456", Path(d) / "inbox", batches.append, host="127.0.0.1")
        try:
            pair = f"http://127.0.0.1:{srv.port}/?code=123456"
            assert link_send(pair, [mono, st], "vts", "Laptop") == 2
            assert len(batches) == 1 and batches[0]["target"] == "vts" and batches[0]["from"] == "Laptop"
            assert sorted(f.name for f in batches[0]["files"]) == ["mono.wav", "st.wav"]
            assert batches[0]["files"][0].read_bytes() in (mono.read_bytes(), st.read_bytes())
            for bad_pair, files in ((f"http://127.0.0.1:{srv.port}/?code=000000", [mono]),
                                    (pair, [Path(d) / "notes.txt"])):
                try:
                    link_send(bad_pair, files, "vts", "x")
                    raise AssertionError("accepted a bad send")
                except (OSError, ValueError):
                    pass
            assert len(batches) == 1
            import urllib.request
            page = urllib.request.urlopen(pair, timeout=5).read().decode()
            assert "<input" in page and "123456" in page  # the upload page for phones / other PCs
            # guessing the code: after 5 wrong tries this address is shut out for a while, even with the right one
            for _ in range(5):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/?code=999999", timeout=5)
                except OSError:
                    pass
            try:
                urllib.request.urlopen(pair, timeout=5)
                raise AssertionError("not locked out after 5 wrong codes")
            except OSError as e:
                assert "429" in str(e), e
        finally:
            srv.stop()
        assert not (Path(d) / "inbox").exists() or not any((Path(d) / "inbox").iterdir())  # stop clears unaccepted
        handed = []
        hs = link_handover_serve(handed.append, port=0)
        try:
            hp = hs.server_address[1]
            assert link_handover("channelmirror://open?to=vts", hp) and handed == ["channelmirror://open?to=vts"]
            import urllib.request
            try:  # without the token: refused
                urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{hp}/link", data=b"x",
                                                              method="POST"), timeout=3)
                raise AssertionError("took a link without the token")
            except OSError:
                pass
            assert handed == ["channelmirror://open?to=vts"]
        finally:
            hs.shutdown()
        assert not link_handover("channelmirror://open?to=vts", hp)  # nobody listening: the new copy opens itself
        # secrets kept in the settings (pair secrets, the OBS password): sealed with Windows DPAPI for this user only;
        # an old plain value still reads (and is sealed on the next save); one that can't be read is None, not junk
        sealed = secret_keep("pw-" + "x" * 40)
        assert sealed.startswith("dpapi:") and "x" * 40 not in sealed and secret_read(sealed) == "pw-" + "x" * 40
        assert secret_keep("pw") != secret_keep("pw") and secret_read(secret_keep("")) == ""
        assert secret_read("dpapi:" + sealed[6:-8] + "AAAAAAAA") is None and secret_read("dpapi:!!") is None
        assert secret_read("ab" * 32) == "ab" * 32 and secret_read("") == "" and secret_read(None) == ""
        real_settings = shared("SETTINGS")
        set_shared("SETTINGS", Path(d) / "settings.json")
        try:  # one section written now, the rest of the file as it is (never half-written)
            (Path(d) / "settings.json").write_text(json.dumps({"theme": "dark", "link": {"old": 1}}))
            settings_put(link={"peers": []})
            assert json.loads((Path(d) / "settings.json").read_text()) == {"theme": "dark", "link": {"peers": []}}
            assert [f.name for f in Path(d).glob("settings.json*")] == ["settings.json"]
            (Path(d) / "settings.json").write_text("{damaged")  # can't be read: nothing written over it
            try:
                settings_put(link={})
                raise AssertionError("wrote over a settings file it couldn't read")
            except OSError:
                pass
            assert (Path(d) / "settings.json").read_text() == "{damaged"
        finally:
            set_shared("SETTINGS", real_settings)
        # pairing: SPAKE2 over RFC 3526's 2048-bit group - both sides get the same secret only with the same code
        xa, pa_ = pair_offer("11112222", "A")
        xb, pb_ = pair_offer("11112222", "B")
        ka, kb = pair_secret("11112222", "A", xa, pa_, pb_, "a" * 32), pair_secret("11112222", "B", xb, pa_, pb_, "a" * 32)
        assert ka == kb and len(ka[0]) == 64 and ka[1] != ka[2]
        xc, pc_ = pair_offer("11112223", "B")  # a wrong code: nothing in common
        assert pair_secret("11112223", "B", xc, pa_, pc_, "a" * 32)[0] != pair_secret("11112222", "A", xa, pa_, pc_,
                                                                                    "a" * 32)[0]
        for bad in (0, 1, PAIR_P - 1, PAIR_P, 11):  # not an element of the group (11 isn't in 2's subgroup)
            try:
                pair_secret("11112222", "A", xa, pa_, bad, "a" * 32)
                raise AssertionError(f"took {bad} as the other side's value")
            except ValueError:
                pass
        # linked computers: pair once (pairing code + accepted on the other PC), then every request is signed with
        # the pair secret; proposals are checked, carried whole, and applied only by the receiving side
        sig = peer_sign("ab" * 32, "GET", "/peer/hello", 100, "0" * 32, "e" * 64)
        assert len(sig) == 64 and sig != peer_sign("cd" * 32, "GET", "/peer/hello", 100, "0" * 32, "e" * 64)
        assert sig != peer_sign("ab" * 32, "GET", "/peer/browse", 100, "0" * 32, "e" * 64)
        import time
        a_id, b_id = "a" * 32, "b" * 32
        peers_a, peers_b, got_a, got_b, asked, asked_a = {}, {}, [], [], [], []  # pair id -> (secret, verified at)
        listing = {"name": "PC-B", "deck": [{"profile": "Main", "grid": [5, 3], "pages": [{"name": "Page 1", "keys": {
            "0,0": peer_key(sd_play(Path(d) / "secret folder" / "boom.wav", "Boom"))}}]}],
            "vts": {"models": ["Wolf"], "model": "Wolf", "backgrounds": ["sky.png"]}}
        assert listing["deck"][0]["pages"][0]["keys"]["0,0"] == {"title": "Boom", "kind": "Sound", "sounds": ["boom.wav"]}
        answer = [True]

        def ask_b(kind, info):
            asked.append((kind, info))
            if kind == "browse":
                return listing
            if kind in ("pair", "renew") and answer[0]:
                peers_b[info["id"]] = (info["secret"], time.time())
                return {"id": b_id, "name": "PC-B"}
            if kind == "unlink":
                peers_b.pop(info["id"], None)
                return {}
            return None
        srv_a = LinkServer(0, "55556666", Path(d) / "inbox_a", got_a.append, host="127.0.0.1",
                           peers=lambda: dict(peers_a), ask=lambda kind, info: asked_a.append((kind, info)), name="PC-A")
        srv_b = LinkServer(0, "11112222", Path(d) / "inbox_b", got_b.append, host="127.0.0.1",
                           peers=lambda: dict(peers_b), ask=ask_b, name="PC-B", nonces=Path(d) / "b_nonces.json")
        try:
            pair_b = f"http://127.0.0.1:{srv_b.port}/?code=11112222"
            for url, ok in ((f"http://127.0.0.1:{srv_b.port}/?code=00000000", True), (pair_b, False)):
                answer[0] = ok  # a wrong code; the right code but declined on the other PC: not paired
                try:
                    peer_pair(url, a_id, "PC-A", srv_a.port)
                    raise AssertionError("paired without the code / without accepting")
                except OSError:
                    pass
            assert not peers_b
            answer[0] = True
            pb = peer_pair(pair_b, a_id, "PC-A", srv_a.port)
            assert pb["id"] == b_id and pb["name"] == "PC-B" and pb["port"] == srv_b.port and pb["host"] == "127.0.0.1"
            assert len(pb["secret"]) == 64 and peers_b[a_id][0] == pb["secret"] and peer_days_left(pb) == PEER_DAYS
            assert asked[-1][1]["name"] == "PC-A" and asked[-1][1]["port"] == srv_a.port
            peers_a[b_id] = (pb["secret"], pb["since"])
            pa = {"id": a_id, "name": "PC-A", "host": "127.0.0.1", "port": srv_a.port, "secret": pb["secret"],
                  "since": pb["since"]}
            assert peer_hello(pb, a_id) == "PC-B" and peer_hello(pa, b_id) == "PC-A"
            for bad in (dict(pb, secret="00" * 32), dict(pb, id="c" * 32)):  # wrong secret / a PC it never paired
                try:
                    peer_hello(bad, "c" * 32 if bad["id"] != b_id else a_id)
                    raise AssertionError("answered without the pair secret")
                except OSError:
                    pass
            import urllib.request
            web = link_noproxy()
            url = f"http://127.0.0.1:{srv_b.port}/peer/hello"
            for h in ({}, {"code": "11112222"}):  # no signature (the pairing code alone isn't enough): refused
                try:
                    web.open(urllib.request.Request(url + ("?code=11112222" if h else "")), timeout=5)
                    raise AssertionError("answered an unsigned request")
                except OSError:
                    pass
            srv_b.fails.clear()  # the shut-out after 5 wrong tries is tested above
            import hashlib
            h = peer_headers(a_id, pb["secret"], "GET", "/peer/hello", hashlib.sha256(b"").hexdigest())
            assert web.open(urllib.request.Request(url, headers=h), timeout=5).status == 200
            try:  # the same request again (a recording of it): refused
                web.open(urllib.request.Request(url, headers=h), timeout=5)
                raise AssertionError("a replayed request was taken")
            except OSError:
                pass
            old = peer_headers(a_id, pb["secret"], "GET", "/peer/hello", hashlib.sha256(b"").hexdigest(),
                               t=int(time.time()) - PEER_SKEW - 60)
            try:
                web.open(urllib.request.Request(url, headers=old), timeout=5)
                raise AssertionError("an old request was taken")
            except OSError:
                pass
            # ... nor after the other PC restarts: the requests it took are kept on disk until they're too old anyway
            srv_b2 = LinkServer(0, "11112222", Path(d) / "inbox_b2", got_b.append, host="127.0.0.1",
                                peers=lambda: dict(peers_b), ask=ask_b, name="PC-B", nonces=Path(d) / "b_nonces.json")
            try:
                url2 = f"http://127.0.0.1:{srv_b2.port}/peer/hello"
                try:
                    web.open(urllib.request.Request(url2, headers=h), timeout=5)
                    raise AssertionError("a request taken before a restart was taken again after it")
                except OSError as e:
                    assert "already used" in e.read().decode(), e
                assert peer_hello(dict(pb, port=srv_b2.port), a_id) == "PC-B"
            finally:
                srv_b2.stop()
            (Path(d) / "b_nonces.json").write_text("[[damaged")  # can't tell what was taken: older requests refused
            srv_b2 = LinkServer(0, "11112222", Path(d) / "inbox_b2", got_b.append, host="127.0.0.1",
                                peers=lambda: dict(peers_b), ask=ask_b, name="PC-B", nonces=Path(d) / "b_nonces.json")
            try:
                url2 = f"http://127.0.0.1:{srv_b2.port}/peer/hello"
                h2 = peer_headers(a_id, pb["secret"], "GET", "/peer/hello", hashlib.sha256(b"").hexdigest(),
                                  t=int(time.time()) - 30)
                try:
                    web.open(urllib.request.Request(url2, headers=h2), timeout=5)
                    raise AssertionError("took a request older than the restart without its notes")
                except OSError as e:
                    assert "restarted" in e.read().decode(), e
                assert peer_hello(dict(pb, port=srv_b2.port), a_id) == "PC-B"
            finally:
                srv_b2.stop()
            srv_b.fails.clear()
            # wrong codes and bad signatures are counted apart, per address and per kind (each with a cap for
            # everyone): one kind of failure never shuts out the other
            srv_b.fails.clear()
            for _ in range(5):
                try:
                    web.open(f"http://127.0.0.1:{srv_b.port}/?code=99999999", timeout=5)
                except OSError:
                    pass
            try:
                web.open(pair_b, timeout=5)
                raise AssertionError("not shut out after 5 wrong codes")
            except OSError as e:
                assert "429" in str(e), e
            assert peer_hello(pb, a_id) == "PC-B"  # a linked computer from the same address still gets through
            srv_b.fails.clear()
            for _ in range(5):
                try:
                    peer_hello(dict(pb, secret="00" * 32), a_id)
                except OSError:
                    pass
            try:
                peer_hello(pb, a_id)
                raise AssertionError("not shut out after 5 bad signatures")
            except OSError as e:
                assert "Too many" in str(e), e
            assert web.open(pair_b, timeout=5).status == 200  # the pairing code still works from there
            srv_b.fails.clear()
            srv_b.fails[("code", "*")] = [time.time()] * 30  # 30 wrong codes from anywhere: codes shut out for all
            try:
                web.open(pair_b, timeout=5)
                raise AssertionError("not shut out after 30 wrong codes from anywhere")
            except OSError as e:
                assert "429" in str(e), e
            assert peer_hello(pb, a_id) == "PC-B"
            srv_b.fails.clear()
            assert peer_browse(pb, a_id) == listing  # read-only listing, built by the other PC
            # read again at once: answered from a short cache (the other PC isn't asked again); and a few reads a
            # minute per linked computer at most
            n_ = sum(k == "browse" for k, _ in asked)
            assert peer_browse(pb, a_id) == listing and sum(k == "browse" for k, _ in asked) == n_
            srv_b.READ_CACHE, srv_b.READS = 0, 3
            try:
                srv_b.hits.clear()
                for i in range(4):
                    try:
                        peer_browse(pb, a_id)
                        assert i < 3, "read more often than allowed"
                    except OSError as e:
                        assert i == 3 and "Too many" in str(e), (i, e)
                c_id = "c" * 32  # another linked computer still reads
                peers_b[c_id] = ("cd" * 32, time.time())
                assert peer_browse(dict(pb, secret="cd" * 32), c_id) == listing
                del peers_b[c_id]
            finally:
                srv_b.READ_CACHE, srv_b.READS = LinkServer.READ_CACHE, LinkServer.READS
                srv_b.hits.clear()
            # a remote edit: files + what to do with them; nothing applied by the server - only handed on
            spec = {"profile": "Main", "ops": [
                {"op": "sounds", "page": 0, "page_name": "Page 1", "key": "1,0", "files": [0, 1], "title": "Two"},
                {"op": "title", "page": 0, "page_name": "Page 1", "key": "0,0", "title": "BOOM"},
                {"op": "clear", "page": 0, "page_name": "Page 1", "key": "2,0"}]}
            assert peer_send(pb, a_id, [mono, st], "edit", spec) == 2
            t_ = time.time()  # the server answers the sender first, then hands the files on: wait for that
            while not got_b and time.time() - t_ < 5:
                time.sleep(0.02)
            assert len(got_b) == 1 and got_b[0]["peer"] == a_id and got_b[0]["target"] == "edit"
            assert got_b[0]["spec"] == spec and [f.name for f in got_b[0]["files"]] == ["mono.wav", "st.wav"]
            assert got_b[0]["files"][1].read_bytes() == st.read_bytes()
            for bad in ({"model": "Wolf", "extra": "x"}, {"model": "W" * 201}, {"model": r"C:\Users\x"}):
                try:  # an extra / oversized field, a path for a name: refused before anything is sent
                    peer_send(pa, b_id, [], "vts", bad)
                    raise AssertionError(f"sent {bad}")
                except ValueError:
                    pass
            assert peer_send(pa, b_id, [], "vts", {"model": "Wolf"}) == 0  # the other way round
            assert got_a[0]["peer"] == b_id and got_a[0]["spec"] == {"model": "Wolf"} and not got_a[0]["files"]
            body = json.dumps({"target": "edit", "spec": spec, "files": 1}).encode()  # refers to a file not sent
            for b_, hsh in ((body, None), (b'{"target": "vts", "spec": {}, "files": 0}', "0" * 64)):  # bad / tampered
                try:
                    peer_call(pb, a_id, "POST", "/peer/done?batch=zz1", b_, body_hash=hsh)
                    raise AssertionError("took a bad proposal")
                except OSError:
                    pass
            t_ = time.time()  # the server answers the sender first, then hands the files on: wait for that
            while not got_b and time.time() - t_ < 5:
                time.sleep(0.02)
            assert len(got_b) == 1
            # only the files and commands this toolset uses: checked before sending and again where they arrive
            fake, pic = Path(d) / "fake.wav", Path(d) / "pic.png"
            fake.write_bytes(b"MZ" + b"\0" * 100)  # a program renamed .wav
            pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 100)
            snd1 = {"sounds": [{"file": 0, "key": "0,0", "title": "x"}]}
            for fs, tgt, sp in (([fake], "soundboard", snd1), ([pic], "soundboard", snd1), ([mono], "files", {})):
                try:
                    peer_send(pb, a_id, fs, tgt, sp)
                    raise AssertionError(f"sent {fs} to {tgt}")
                except ValueError as e:
                    assert fs[0].name in str(e), e
            assert link_check_file(pic, LINK_IMAGES) == pic and link_check_file(mono, LINK_AUDIO) == mono
            from urllib.parse import urlencode
            with open(fake, "rb") as fh:  # the same, sent anyway: refused where it arrives
                peer_call(pb, a_id, "POST", "/peer/upload?" + urlencode({"batch": "zz2", "name": "fake.wav"}), fh=fh,
                          size=fake.stat().st_size, body_hash=hashlib.sha256(fake.read_bytes()).hexdigest())
            for call in (("POST", "/peer/done?batch=zz2", json.dumps({"target": "soundboard", "spec": snd1,
                                                                       "files": 1}).encode()),
                         ("POST", "/peer/upload?" + urlencode({"batch": "zz3", "name": "..\\evil.wav"}),
                          mono.read_bytes()),  # a path in a file name
                         ("GET", "/peer/run?cmd=calc", b""),  # an unknown command
                         ("POST", "/peer/done?batch=zz4", json.dumps({"target": "shell", "spec": {}, "files": 0}
                                                                     ).encode()),
                         ("POST", "/peer/done?batch=zz5", json.dumps({"target": "files", "spec": {}, "files": 0,
                                                                      "run": "calc"}).encode())):
                try:
                    peer_call(pb, a_id, *call)
                    raise AssertionError(f"took {call[1]}")
                except OSError:
                    pass
            t_ = time.time()  # the server answers the sender first, then hands the files on: wait for that
            while not got_b and time.time() - t_ < 5:
                time.sleep(0.02)
            assert len(got_b) == 1 and not list((Path(d) / "inbox_b").rglob("fake.wav"))
            # the result of a proposal goes back to the sender
            peer_result(pa, b_id, "abc", False, "Declined")
            assert ("result", {"id": b_id, "batch": "abc", "ok": False, "note": "Declined"}) in asked_a
            # 30 days: the receiving side counts from when it verified the link, by its own clock
            t0 = 1_000_000.0
            assert [peer_days_left({"since": t0}, t0 + x * 86400) for x in (0, 0.5, 29.5, 30, 45)] == [30, 30, 1, 0, 0]
            peers_b[a_id] = (pb["secret"], time.time() - (PEER_DAYS + 1) * 86400)
            try:
                peer_hello(pb, a_id)
                raise AssertionError("an expired link still works")
            except OSError as e:
                assert "expired" in str(e), e
            assert peer_find(pb, a_id, [("127.0.0.1", srv_b.port)], 1.0) is None  # nor is it found
            peers_b[a_id] = (pb["secret"], time.time() - 20 * 86400)
            srv_b.clock = lambda: time.time() + 11 * 86400  # its clock says the 30 days are over: refused too
            try:
                peer_hello(pb, a_id)
                raise AssertionError("expiry by the sender's clock alone")
            except OSError as e:
                assert "expired" in str(e), e
            srv_b.clock = time.time
            srv_b.fails.clear()
            # found again where it is now (its address changed): only with the pair secret - and still answering after
            # a packet too big for it (Windows error 10040) and a question to an address with nobody there (reset)
            import socket
            junk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            junk.sendto(b"x" * 2000, ("127.0.0.1", srv_b.port))
            junk.close()
            time.sleep(0.2)
            nobody = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            nobody.bind(("127.0.0.1", 0))
            dead = nobody.getsockname()
            nobody.close()
            assert peer_find(pb, a_id, [dead, ("127.0.0.1", srv_b.port)], 2.0) == ("127.0.0.1", srv_b.port)
            assert peer_find(pb, a_id, [("127.0.0.1", srv_b.port)], 2.0) == ("127.0.0.1", srv_b.port)
            assert peer_find(dict(pb, secret="00" * 32), a_id, [("127.0.0.1", srv_b.port)], 1.0) is None
            # someone listening on the network learns neither the code nor the secret: pairing and renewing agree on
            # it (SPAKE2 with the code; renewing with the old secret), it never crosses the network
            relay_ = relay(srv_b.port)
            try:
                rp = relay_.getsockname()[1]
                try:  # the code was used in plain text (a device's upload page): it can't link until New code
                    peer_pair(f"http://127.0.0.1:{rp}/?code=11112222", "d" * 32, "PC-D", srv_a.port)
                    raise AssertionError("linked with a code that crossed the network")
                except OSError as e:
                    assert "New code" in str(e), e
                srv_b.fails.clear()
                srv_b.code = "33334444"  # New code
                pd = peer_pair(f"http://127.0.0.1:{rp}/?code=33334444", "d" * 32, "PC-D", srv_a.port)
                assert peers_b["d" * 32][0] == pd["secret"] and peer_hello(pd, "d" * 32) == "PC-B"
                del peers_b["d" * 32]
                pb2 = peer_renew(dict(pb, port=rp), a_id)
                pb2["port"] = srv_b.port
                wire = b"".join(relay_.heard)
                assert b"POST /pair/start" in wire and b"/peer/renew" in wire
                for s_ in (b"33334444", pd["secret"].encode(), pb2["secret"].encode(), pb["secret"].encode()):
                    assert s_ not in wire, s_
            finally:
                relay_.close()
            # renew: verified again there, a new secret and 30 fresh days; the old secret stops working
            assert pb2["secret"] != pb["secret"] and peers_b[a_id][0] == pb2["secret"] and peer_days_left(pb2) == 30
            assert time.time() - peers_b[a_id][1] < 60 and peer_hello(pb2, a_id) == "PC-B"
            try:
                peer_hello(pb, a_id)
                raise AssertionError("the old secret still works after renewing")
            except OSError:
                pass
            srv_b.fails.clear()  # the shut-out after 5 wrong tries is tested above
            # unlink: the other side forgets this PC
            peer_unlink(pb2, a_id)
            assert a_id not in peers_b
            try:
                peer_hello(pb2, a_id)
                raise AssertionError("still linked after unlinking")
            except OSError:
                pass

        finally:
            srv_a.stop()
            srv_b.stop()
        for bad in ({"profile": "Main", "ops": [{"op": "sounds", "page": 0, "page_name": "P", "key": "x,0", "files": [0]}]},
                    {"profile": "Main", "ops": [{"op": "melt", "page": 0, "page_name": "P", "key": "0,0"}]},
                    {"profile": "Main", "ops": [{"op": "sounds", "page": 0, "page_name": "P", "key": "0,0", "files": [5]}]},
                    {"profile": "", "ops": []}):
            try:
                peer_proposal("edit", bad, 2)
                raise AssertionError(f"took {bad}")
            except ValueError:
                pass
        mir = {"settings": {"sources": ["L"], "targets": ["left"], "length": "1:30", "split": True, "parts": "3",
                            "output_type": "audio"}}
        assert peer_proposal("mirror", mir, 1) == mir
        for bad in ({"settings": {"length": "soon"}}, {"settings": {"output_type": "exe"}},
                    {"settings": {"sources": ["L", "nope"]}}, {"settings": {"x": 1}}, {"settings": {}, "run": "calc"}):
            try:
                peer_proposal("mirror", bad, 1)
                raise AssertionError(f"took {bad}")
            except ValueError:
                pass
        # keys carried over the link: only sounds, Stop audio, Multi / Random of those, folders, VTube Studio hotkeys
        def act(uuid, name="x", **more):
            return {"ActionID": sd_uid(), "Name": name, "UUID": uuid, "Settings": {}, "States": [{"Title": name}],
                    **more}
        opener = act("com.elgato.streamdeck.system.open", "Open", Settings={"path": "C:\\Windows\\System32\\calc"})
        page_of = lambda *keys: {"Controllers": [{"Type": "Keypad", "Actions": {f"{i},0": k for i, k in enumerate(keys)}}]}
        fold_key = act(SD_FOLDER, "Folder", Settings={"ProfileUUID": "abc-1"})

        def put(a, pages=None, n=None):
            return peer_proposal("edit", {"profile": "Main", "ops": [
                {"op": "put", "page": 0, "page_name": "Page 1", "key": "0,0", "action": a, "pages": pages or {},
                 "sounds": list(range(len(peer_carried(a, pages or {}))))}]}, len(peer_carried(a, pages or {})))
        for bad, pgs in ((opener, None), (act("com.elgato.streamdeck.system.website", "Website"), None),
                           (act("com.elgato.streamdeck.system.hotkey", "Hotkey"), None),
                           (sd_wrap("Multi Action", "m", [sd_play(mono), opener]), None),  # nested in a Multi Action
                           (fold_key, {"abc-1": page_of(sd_play(mono), opener)})):  # inside a carried folder page
            try:
                put(bad, pgs)
                raise AssertionError(f"carried {bad['Name']}")
            except ValueError as e:
                assert "can't come over the link" in str(e), e
        carried = put(fold_key, {"abc-1": page_of(sd_play(mono), sd_wrap("Random Action", "r", [sd_play(st)]), sd_stop_key(),
                                           sd_vts_key("m1", "h1", "Sky"), act(SD_PARENT, "Back"))})
        assert set(carried["ops"][0]["kinds"]) >= {"Play Audio", "Random Action", "Stop Audio", "Trigger Hotkey"}
        assert "Trigger Hotkey" in peer_summary("edit", carried, [mono, st, st])[1]
        # what the security review found: icons outside Images, sounds hidden where they aren't carried, actions
        # tucked under "Plugin" or with no kind, device-name icons - all refused
        sneaky = [dict(sd_play(mono), States=[{"Image": "../../Pictures/me.jpg"}]),
                  dict(sd_play(mono), States=[{"Image": "Images/nul.png"}]),
                  dict(sd_play(mono), Plugin={"Name": "x", "UUID": "y", "Actions": [opener]}),
                  {"Name": "no kind", "Settings": {}}]
        for bad in sneaky:
            try:
                put(bad)
                raise AssertionError(f"carried {bad}")
            except ValueError:
                pass
        hidden = {"abc-1": {"Controllers": [{"Type": "Keypad", "Actions": {}},
                                            {"Type": "Encoder", "Actions": {"0,0": sd_play(r"\\evil\share\x.wav")}}]}}
        try:
            peer_proposal("edit", {"profile": "Main", "ops": [{"op": "put", "page": 0, "page_name": "P", "key": "0,0",
                                                               "action": fold_key, "pages": hidden, "sounds": []}]}, 0)
            raise AssertionError("a sound path from the other PC would have been kept")
        except ValueError:
            pass
        assert peer_icon_ok("Images/star.png") and not peer_icon_ok("Images/../x.png") and not peer_icon_ok("Images/a/b.png")
        try:  # one file can't be both a sound and an icon
            peer_check_files("edit", {"ops": [{"sounds": [0], "icons": {"Images/a.png": 0}}]}, [mono])
            raise AssertionError("one file, two roles")
        except ValueError:
            pass
        made_pages = {}
        kp2 = peer_apply({}, carried["ops"], [mono, st], made_pages.__setitem__)
        new_pid = kp2["0,0"]["Settings"]["ProfileUUID"]
        assert new_pid != "abc-1" and list(made_pages) == [new_pid]  # its own copy of the folder page
        assert [s["Settings"]["path"] for s in peer_carried(kp2["0,0"], made_pages)] == [str(mono), str(st)]
        # the "From Channel Mirror..." picker: only the tool's types, each once, natural order, search, missing marked
        groups = {"Outputs": [Path(d) / "b10.wav", mono, Path(d) / "b2.wav", mono, Path(d) / "notes.txt"], "Keys": [st]}
        assert [(g, p.name, ok) for g, p, ok in library_items(groups, LINK_AUDIO)] == [
            ("Outputs", "b2.wav", False), ("Outputs", "b10.wav", False), ("Outputs", "mono.wav", True), ("Keys", "st.wav", True)]
        assert [p.name for _, p, _ in library_items(groups, LINK_AUDIO, "MON")] == ["mono.wav"]
        assert library_files(d, (".wav",), 2) and len(library_files(d, (".wav",), 2)) == 2
        assert link_default_target([mono]) == "import" and link_default_target([pic]) == "vts" and \
            link_default_target([Path("a.mkv")]) == "mirror" and link_default_target([Path("a.mp4")]) == "files"
        # keys packed to go over the link: sound paths become names (this PC's folders never go), files listed
        src_page = {"0,0": sd_play(mono, "One"), "1,0": opener}
        packed = peer_pack({"0,0": copy.deepcopy(src_page["0,0"])}, {}, lambda p: {}, d)
        assert packed["0,0"]["sounds"] == [mono] and sd_sounds(packed["0,0"]["action"])[0]["Settings"]["path"] == "mono.wav"
        try:
            peer_pack({"1,0": copy.deepcopy(opener)}, {}, lambda p: {}, d)
            raise AssertionError("packed a program-opening key")
        except ValueError:
            pass
        ops_, files_ = peer_put_ops(packed, {"0,0": "2,1"}, 0, "Page 1")
        assert files_ == [mono] and ops_[0]["key"] == "2,1" and ops_[0]["sounds"] == [0]
        assert peer_proposal("edit", {"profile": "Main", "ops": ops_}, 1)["ops"][0]["kinds"] == ["Play Audio"]
        lines = peer_summary("edit", spec, [mono, st])
        assert lines[0] == "3 key(s) on Main, Page 1:" and "2 sound(s)" in lines[1] and "BOOM" in lines[2], lines
        kp = {"0,0": sd_play(mono, "Boom"), "2,0": sd_play(st, "x")}
        peer_apply(kp, spec["ops"], [mono, st])
        assert sd_kind(kp["1,0"]) == "Random x2" and sd_title(kp["1,0"]) == "Two" and "2,0" not in kp
        assert sd_title(kp["0,0"]) == "BOOM" and [s["Settings"]["path"] for s in sd_sounds(kp["1,0"])] == [str(mono), str(st)]
        peer_apply(kp, [{"op": "sounds", "page": 0, "page_name": "P", "key": "0,0", "files": [1], "title": ""}], [mono, st])
        assert sd_kind(kp["0,0"]) == "Random x2" and sd_title(kp["0,0"]) == "BOOM"  # added to the sound already there
        # a soundboard installed into Stream Deck there (its normal send), said so in the accept prompt
        sb = peer_proposal("soundboard", {"sounds": [{"file": 0, "title": "Boom"}], "install": True, "name": "Gig"}, 1)
        assert sb["install"] is True and sb["name"] == "Gig"
        assert any("installed into Stream Deck here" in x and "'Gig'" in x for x in peer_summary("soundboard", sb, [mono]))
        plain = peer_proposal("soundboard", {"sounds": [{"file": 0}]}, 1)
        assert "install" not in plain and not any("installed" in x for x in peer_summary("soundboard", plain, [mono]))
        for bad in ({"install": "yes"}, {"install": True, "name": "C:\\x"}, {"install": True, "name": "x" * 61},
                    {"name": "Gig"}):  # a name only goes with install
            try:
                peer_proposal("soundboard", {"sounds": [{"file": 0}], **bad}, 1)
                raise AssertionError(f"took {bad}")
            except ValueError:
                pass
        # VTube Studio backgrounds set up there by its own VTube Studio tab: the prompt says VTube Studio closes / reopens
        vt = peer_proposal("vts", {"model": "Wolf", "apply": True, "hotkeys": True}, 1)
        lines = peer_summary("vts", vt, [pic])
        assert any("close and reopen VTube Studio" in x and "hotkey" in x for x in lines), lines
        assert not any("reopen" in x for x in peer_summary("vts", peer_proposal("vts", {"apply": True}, 1), [pic]))
        # icons of keys inside a carried folder go too: "<its page id>/Images/x.png", only ones that page shows
        top_d, in_d = Path(d) / "iconprof" / "TOP", Path(d) / "iconprof" / "ABC-1"
        for x, name in ((top_d, "F.png"), (in_d, "S.png")):
            (x / "Images").mkdir(parents=True)
            shutil.copy2(pic, x / "Images" / name)
        fk = dict(copy.deepcopy(fold_key), States=[{"Image": "Images/F.png"}])
        (in_d / "manifest.json").write_text(json.dumps(page_of(dict(sd_play(mono), States=[{"Image": "Images/S.png"}]))))
        pk = peer_pack({"0,0": copy.deepcopy(fk)}, {"abc-1": in_d / "manifest.json"},
                       lambda f: json.loads(Path(f).read_text()), top_d)["0,0"]
        assert pk["icons"] == {"Images/F.png": top_d / "Images" / "F.png",
                               "abc-1/Images/S.png": in_d / "Images" / "S.png"}, pk["icons"]
        ops_, files_ = peer_put_ops({"0,0": pk}, {"0,0": "1,0"}, 0, "Page 1")
        spec_i = peer_proposal("edit", {"profile": "Main", "ops": ops_}, len(files_))
        peer_check_files("edit", spec_i, files_)  # icons are pictures, the sound a sound
        assert set(spec_i["ops"][0]["icons"]) == {"Images/F.png", "abc-1/Images/S.png"}
        for bad in ("zzz/Images/S.png", "abc-1/Images/F.png", "abc-1/../Images/S.png", "abc-1/Images/../S.png",
                    "ABC-1/Images/S.png/x", "/abc-1/Images/S.png"):
            o = dict(ops_[0], icons={bad: ops_[0]["icons"]["abc-1/Images/S.png"]})
            try:
                peer_proposal("edit", {"profile": "Main", "ops": [o]}, len(files_))
                raise AssertionError(f"took the icon {bad}")
            except ValueError:
                pass
        made = {}
        kp3 = peer_apply({}, spec_i["ops"], files_, made.__setitem__)
        new_pid = kp3["1,0"]["Settings"]["ProfileUUID"]
        assert sd_folder_map(spec_i["ops"][0]["action"], kp3["1,0"], spec_i["ops"][0]["pages"], made) == {new_pid: "abc-1"}
        # more than 200 files (the most one proposal carries) go in batches, each pointing at its own files from 0
        assert [len(f) for f, _ in peer_batches("import", {}, [mono] * 450)] == [200, 200, 50]
        parts = peer_batches("soundboard", {"sounds": [{"file": i, "title": f"s{i}"} for i in range(450)],
                                            "install": True, "name": "Gig"}, [Path(f"{i}.wav") for i in range(450)])
        assert [(len(f), s["sounds"][0]["file"], s["name"]) for f, s in parts] == [
            (200, 0, "Gig"), (200, 0, "Gig 2"), (50, 0, "Gig 3")] and parts[2][0][-1] == Path("449.wav")
        assert parts[2][1]["sounds"][-1]["title"] == "s449" and all(peer_proposal("soundboard", s, len(f)) for f, s in parts)
        ed_ops = [{"op": "sounds", "page": 0, "page_name": "P", "key": f"{i},0", "files": list(range(i * 150, i * 150 + 150)),
                   "title": ""} for i in range(3)]
        parts = peer_batches("edit", {"profile": "Main", "ops": ed_ops}, [Path(f"{i}.wav") for i in range(450)])
        assert [len(f) for f, _ in parts] == [150, 150, 150] and parts[1][1]["ops"][0]["files"][0] == 0
        assert parts[1][0][0] == Path("150.wav") and all(peer_proposal("edit", s, len(f)) for f, s in parts)
        try:
            peer_batches("edit", {"profile": "Main", "ops": [dict(ed_ops[0], files=list(range(201)))]}, [mono] * 201)
            raise AssertionError("one key with 201 files went")
        except ValueError:
            pass
        assert peer_batches("record", {"action": "start"}, []) == [([], {"action": "start"})]
        # Explorer's Send to > Channel Mirror (linked computers): its files handed to the open app
        assert link_to_peer(["--to-linked", "C:\\a.wav", "D:\\b"]) == "--to-linked\nC:\\a.wav\nD:\\b"
        assert link_to_peer(["C:\\a.wav"]) is None
        # screen recorder: the area on a monitor -> desktop pixels (even sizes for H.264), and the ffmpeg command
        mon = ("Monitor 1", -2560, 263, 2560, 1440)  # left of the main one, in real pixels
        assert rec_area(mon, 100, 50, 641, 361) == (-2460, 313, 640, 360)
        assert rec_area(mon, 0, 0, 0, 0) == (-2560, 263, 2560, 1440)  # 0 x 0 = the whole monitor
        for bad in ((2500, 0, 100, 100), (-1, 0, 100, 100), (0, 0, 8, 8), ("a", 0, 10, 10)):
            try:
                rec_area(mon, *bad)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        cmd = rec_command((-3740, 445, 640, 360), 30, Path("C:/out/a.mp4"), mouse=False)
        assert cmd[cmd.index("-offset_x") + 1] == "-3740" and cmd[cmd.index("-video_size") + 1] == "640x360"
        assert cmd[cmd.index("-draw_mouse") + 1] == "0" and cmd[-1] == str(Path("C:/out/a.mp4"))
        assert "gdigrab" in cmd and "-framerate" in cmd and cmd[cmd.index("-c:v") + 1] in ("libx264", "mpeg4")
        assert cmd[cmd.index("-g") + 1] == "60" and "frag_keyframe" in cmd[cmd.index("-movflags") + 1]
        # a crash / kill loses at most half a second: a piece of file every 0.5 s, and no frames held back by x264
        assert cmd[cmd.index("-frag_duration") + 1] == "500000"
        assert cmd[cmd.index("-c:v") + 1] != "libx264" or cmd[cmd.index("-tune") + 1] == "zerolatency"
        assert rec_name(Path("C:/v"), "Clip", "2026-11-22 15-04-05") == Path("C:/v/Clip 2026-11-22 15-04-05.mp4")
        assert rec_name(Path("C:/v"), ' bad:/<>name ', "t") == Path("C:/v/bad____name t.mp4")
        # key mover: where copied keys land
        dst = {"1,0": one, "0,1": one}  # a 3x2 deck with two keys in use
        assert sd_place(["0,0", "1,0"], dst, 3, 2, "0,0") == {"0,0": "0,0", "1,0": "2,0"}  # 1,0 in use -> next free
        assert sd_place(["0,0", "1,0"], dst, 3, 2, "0,0", policy="replace") == {"0,0": "0,0", "1,0": "1,0"}
        assert sd_place(["0,0", "1,0"], dst, 3, 2, "0,0", policy="skip") == {"0,0": "0,0", "1,0": None}
        assert sd_place(["2,0", "2,1"], {}, 3, 2, "1,0") == {"2,0": "1,0", "2,1": "1,1"}  # same shape from the anchor
        assert sd_place(["2,0", "2,1"], {}, 3, 2, "2,1") == {"2,0": "2,1", "2,1": "0,0"}  # off the deck -> next free
        assert sd_place(["0,0", "1,0"], {}, 3, 2, "1,1", keep_layout=False) == {"0,0": "1,1", "1,0": "2,1"}
        assert sd_place(["0,0", "1,0"], dst, 3, 2, picks=["2,1", "0,1"]) == {"0,0": "2,1", "1,0": "1,1"}
        assert sd_place(["0,0", "1,0", "2,0"], {"0,0": one, "1,0": one, "2,0": one}, 3, 1) == {
            "0,0": None, "1,0": None, "2,0": None}  # a full deck: nowhere to go
        # icons: the image files a key or page shows (relative to its page folder)
        ik = sd_wrap("Multi Action", "m", [dict(sd_play(st), States=[{"Image": "Images/IN.png"}])])
        ik["States"] = [{"Image": "Images/A.png"}, {"Image": "Images/B.png", "Title": "x"}, {}]
        assert sd_images(ik) == {"Images/A.png", "Images/B.png", "Images/IN.png"}
        assert sd_images({"Controllers": [{"Actions": {"0,0": ik}}]}) == sd_images(ik) and sd_images(one) == set()
        ids = {}
        sd_clone_folders(copy.deepcopy(outer_key), {outer_id: outer_pg, inner_id: inner_pg}, ids=ids)
        assert sorted(ids.values()) == sorted([outer_id, inner_id])  # new page id -> the page it copies
        # writing an icon (bytes) alongside pages
        blob = Path(d) / "SD2" / "x.sdProfile" / "Profiles" / "P" / "Images" / "A.png"
        sd_save({blob: b"\x89PNG", blob.parents[1] / "manifest.json": {"Controllers": []}}, [], Path(d) / "SD2",
                Path(d) / "bk2")
        assert blob.read_bytes() == b"\x89PNG"
        # extra folders go just beside the first one, then on along the rows, then from the top
        assert sd_beside({"1,0": 1, "2,0": 1, "0,1": 1}, "1,0", 3, 2) == ["1,1", "2,1", "0,0"]
        assert sd_beside({"0,0": 1}, "0,0", 3, 1) == ["1,0", "2,0"]
        p1 = json.loads(pages[0].read_text())
        sd_keypad(p1)["0,1"] = key
        newp = new_dir / "Profiles" / pid.upper() / "manifest.json"
        unsaved = {pages[0]: p1, newp: fpage}  # not on disk yet: listed from the unsaved edits
        assert [n for n, _ in sd_pages(new_dir, new_m, unsaved)] == ["Page 1", "Folder: Hits", "Folder: SFX"]
        assert sd_pages(new_dir, new_m, unsaved)[1][1] == newp and not newp.exists()
        twin_key, twin_id, twin_pg, _ = sd_folder("Hits", [], 2, 2)  # a second folder with the same name
        sd_keypad(p1)["1,0"] = twin_key
        unsaved[new_dir / "Profiles" / twin_id.upper() / "manifest.json"] = twin_pg
        labels_ = [n for n, _ in sd_pages(new_dir, new_m, unsaved)]
        assert sorted(labels_) == ["Folder: Hits", "Folder: Hits #2", "Folder: SFX", "Page 1"], labels_
        assert len({p for _, p in sd_pages(new_dir, new_m, unsaved)}) == 4

        # output device: picking a Random/Multi key sets every sound inside it; saved values are offered back
        p1 = json.loads(pages[0].read_text())
        found = sd_multis([("Page 1", p1), ("Folder: SFX", {})])
        assert [(lbl, k, sd_kind(a)) for lbl, k, a in found] == [("Page 1", "0,0", "Random x2")]
        rnd = found[0][2]
        # Stream Deck saves the Windows endpoint id; the app shows names and saves ids
        real = dict(sd_win_outputs())
        _win_outputs.clear()
        _win_outputs.update({"Test Speakers (Selftest Audio)": "{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}"})
        try:
            sd_set_sound(sd_sounds(rnd), output="Test Speakers (Selftest Audio)")
            tid = "{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}"
            assert {s["Settings"]["outputType"] for s in sd_sounds(rnd)} == {tid}
            assert sd_out_name(tid) == "Test Speakers (Selftest Audio)" and sd_out_name("") == "default"
            assert sd_out(tid) == tid and sd_out_name("{0.0.0.00000000}.{gone}") == "{0.0.0.00000000}.{gone}"
            assert sd_keypad(p1)["1,0"]["Settings"]["outputType"] == ""  # other keys untouched
            pages[0].write_text(json.dumps(p1))
            assert sd_outputs(root) == [tid]
            assert sd_output_choices()[:2] == [SD_DEFAULT_OUT, "Test Speakers (Selftest Audio)"]
        finally:
            _win_outputs.clear()
            _win_outputs.update(real)
        # the format Stream Deck itself saved for this PC's devices, where present
        for name, iid in real.items():
            assert iid.startswith("{0.0.0.") and iid == iid.lower() and sd_out(name) == iid, (name, iid)
        sd_set_sound(sd_sounds(rnd), output=SD_DEFAULT_OUT)  # "default" in the dropdown = blank in the profile
        assert {s["Settings"]["outputType"] for s in sd_sounds(rnd)} == {""} and sd_out(" x ") == "x"

        # self-install: copy, shortcuts, Windows uninstall entry, then a clean uninstall (temp dirs + a test key)
        import winreg
        app, key = Path(d) / "app", r"Software\ChannelMirrorSelftest"
        fake_exe = Path(d) / "ChannelMirror-download.exe"
        shutil.copy2(sys.executable, fake_exe)  # any real exe (a shortcut needs a valid icon source)
        # (shortcuts in temp only: the real Start menu / Send to folders are only named, never written)
        assert shortcut_paths()["sendto_peer"].name == "Channel Mirror (linked computers).lnk"
        assert shortcut_paths()["sendto_peer"].parent == shortcut_paths()["sendto"].parent
        links = {"start": Path(d) / "lnk" / "Channel Mirror.lnk",
                 "sendto_peer": Path(d) / "lnk" / "Channel Mirror (linked computers).lnk"}
        exe = install(fake_exe, app, links, key)
        assert exe == app / "ChannelMirror.exe" and exe.read_bytes() == fake_exe.read_bytes()
        assert links["start"].stat().st_size > 0 and installed(key) == exe
        lnk_args = lambda p: subprocess.run(  # what a shortcut runs with (read back through Windows itself)
            ["powershell", "-NoProfile", "-Command", f"(New-Object -ComObject WScript.Shell).CreateShortcut('{p}')"
             ".Arguments"], capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW).stdout.strip()
        assert lnk_args(links["sendto_peer"]) == "--to-linked" and lnk_args(links["start"]) == ""
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            assert winreg.QueryValueEx(k, "UninstallString")[0] == f'"{exe}" --uninstall'
        install(fake_exe, app, {}, key)  # again = update, no error
        uninstall(app, links, key)
        assert not app.exists() and not links["start"].exists() and installed(key) is None
        assert not links["sendto_peer"].exists()  # uninstall takes the linked-computers Send to away too
        bk = sd_save({pages[0]: {"Controllers": []}}, [new_dir], root, Path(d) / "bk")
        assert json.loads(pages[0].read_text()) == {"Controllers": []}
        with zipfile.ZipFile(bk) as zf:  # the backup holds the page as it was before the write
            old = json.loads(zf.read(str(pages[0].relative_to(root / "ProfilesV3")).replace("\\", "/")))
            assert len(sd_keypad(old)) == 4  # 3 sound keys + the folder key

        # music player: .m3u / .m3u8 in and out, playlist order, the real-time PCM stream, the OBS links
        from urllib.error import HTTPError
        mu = Path(d) / "music"
        (mu / "sub").mkdir(parents=True)
        s1, s2 = mu / "sub" / "a song.wav", Path(d) / "elsewhere.wav"
        write_wav(s1, [loud * 0.5, loud * 0.5])  # 1 s
        write_wav(s2, [quiet, quiet])
        pl = mu / "list.m3u8"
        m3u_write(pl, [(s1, "First One"), (s2, "")])
        lines = pl.read_text(encoding="utf-8").splitlines()
        assert lines[:3] == ["#EXTM3U", "#EXTINF:-1,First One", f"sub{os.sep}a song.wav"], lines  # inside: relative
        assert lines[3:] == ["#EXTINF:-1,Elsewhere", str(s2.resolve())], lines  # outside its folder: the full path
        assert [(f.resolve(), t) for f, t in m3u_read(pl)] == [(s1.resolve(), "First One"), (s2.resolve(), "Elsewhere")]
        (mu / "old.m3u").write_bytes("#EXTM3U\r\n#EXTINF:12,Caf\xe9 Song\r\nsub\\a song.wav\r\nhttp://x.example/a.mp3"
                                     "\r\n\\\\server\\share\\b.mp3\r\n//server/c.mp3\r\n# a note\r\n\r\nC:\\none\\b.mp3\r\n"
                                     "notes.txt\r\nfile:///C:/none/c%20d.mp3\r\nsubfile:,,x.mp3\r\nD:e.mp3\r\n"
                                     r"\/evil/s/a.mp3" "\r\n" r"/\evil\s\b.mp3" "\r\n" r"\\?\C:\c.mp3" "\r\n"
                                     .encode("cp1252"))  # an old ANSI playlist from another player
        assert m3u_read(mu / "old.m3u") == [(mu / "sub" / "a song.wav", "Café Song"), (Path("C:/none/b.mp3"), ""),
                                            (Path("C:/none/c d.mp3"), "")], m3u_read(mu / "old.m3u")
        assert music_local(r"C:\a\b.mp3") and music_local("D:/b.mp3") and not music_local("b.mp3")
        for bad in (r"\\srv\s\a.mp3", "//srv/s/a.mp3", r"\/srv/s/a.mp3", r"/\srv\a.mp3", r"\\?\C:\a.mp3",
                    r"\\.\C:\a.mp3", "D:a.mp3"):
            assert not music_local(bad), bad  # network shares (Windows would hand them the user's logon), devices
        assert music_add([], [(r"\\srv\s\a.mp3", "")]) == 0
        songs = []
        assert music_add(songs, [(s1, ""), (s2, "Two"), (Path(str(s1).upper()), "")]) == 2  # the same file once
        assert songs == [{"path": str(s1), "title": ""}, {"path": str(s2), "title": "Two"}]
        assert music_title(songs[0]) == "A Song" and music_title(songs[1]) == "Two"
        assert music_next([0, 1, 2], None) == 0 and music_next([0, 1, 2], 0) == 1 and music_next([0, 1, 2], 2) is None
        assert music_next([0, 1, 2], 2, "all") == 0 and music_next([0, 1, 2], 1, "one", auto=True) == 1
        assert music_next([0, 1, 2], 1, "one") == 2 and music_next([0, 1, 2], 0, step=-1) == 0
        assert music_next([0, 1, 2], 0, "all", step=-1) == 2 and music_next([], None) is None
        assert music_next([2, 0, 1], 0) == 1 and music_next([2, 0, 1], 1) is None  # shuffled: its own order
        o = music_order(6, 4, True)
        assert o[0] == 4 and sorted(o) == list(range(6)) and music_order(3, 1, False) == [0, 1, 2]
        assert music_order(0, None, True) == []
        assert music_move(list("abcde"), [1, 3], -1) == (list("badce"), [0, 2])
        assert music_move(list("abcde"), [0, 4], -1) == (list("abced"), [0, 3])  # the top one stays
        assert music_move(list("abcde"), [3, 4], 1) == (list("abcde"), [3, 4])
        assert music_move(list("abcde"), [0], 1) == (list("bacde"), [1])
        assert peer_proposal("music", {"playlist": "Mix"}, 2) == {"playlist": "Mix"} and peer_proposal("music", {}, 1) == {}
        for bad in ({"playlist": "C:\\x"}, {"playlist": "a\nb"}, {"other": 1}, {"playlist": 5}, {"playlist": "x" * 61}):
            try:
                peer_proposal("music", bad, 1)
                raise AssertionError(bad)
            except ValueError:
                pass
        peer_check_files("music", {}, [s1])  # songs go; anything else doesn't
        (mu / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(32))
        try:
            peer_check_files("music", {}, [mu / "pic.png"])
            raise AssertionError("a picture as a song")
        except ValueError:
            pass
        assert music_block(b"", 100) == bytes(MUSIC_BLOCK)  # nothing to play: a whole block of silence
        one = np.full(MUSIC_BLOCK // 2, 1000, "<i2").tobytes()
        assert np.frombuffer(music_block(one, 50), "<i2").max() == 250 and music_block(one, 0) == bytes(MUSIC_BLOCK)
        short = music_block(one[:100], 100)
        assert short[:100] == one[:100] and short[100:] == bytes(MUSIC_BLOCK - 100)
        got, ends = [], []
        eng = MusicEngine(on_end=lambda: ends.append(time.perf_counter()))
        try:
            eng.set_sink("t", lambda b: got.append((time.perf_counter(), b)))
            eng.play(s1)
            t_ = time.perf_counter()  # silence while ffmpeg starts the song (slow when the PC is busy): wait for sound
            while eng.position() < 0.3 and time.perf_counter() - t_ < 10:
                time.sleep(0.02)
            eng.pause(True)
            time.sleep(0.06)
            n_p, pos = len(got), eng.position()
            time.sleep(0.3)
            assert all(b == bytes(MUSIC_BLOCK) for _, b in got[n_p:]) and len(got) - n_p >= 12  # paused: silence
            assert eng.position() == pos and 0.25 < pos < 0.6, pos
            eng.pause(False)
            t_end = time.perf_counter() + 4
            while not ends and time.perf_counter() < t_end:
                time.sleep(0.02)
            time.sleep(0.3)  # after the song: silence keeps coming
            assert len(ends) == 1 and got[-1][1] == bytes(MUSIC_BLOCK) and eng.song is None
            span = got[-1][0] - got[0][0]
            assert abs(len(got) - 1 - span * 50) <= 6, (len(got), span)  # real time: 50 blocks a second
            heard = sum(any(b) for _, b in got)
            assert 44 <= heard <= 54, heard  # 1 s of song = 50 blocks
            eng.play(s1)
            eng.seek(0.8)
            assert eng.position() >= 0.8 and eng.song == s1
            eng.stop()
            assert eng.song is None and eng.position() == 0
        finally:
            eng.close()
        tok = "ab" * 16
        assert music_route(f"/music/{tok}/stream.mp3", tok) == "stream" and music_route(f"/music/{tok}/now?x=1", tok) == "now"
        assert music_route(f"/music/{tok}/now.json", tok) == "json"
        for bad in (f"/music/{'cd' * 16}/now", f"/music/{tok}/", f"/music/{tok}/../now", "/", f"/music/{tok.upper()}/now",
                    f"/music/{tok}/stream.mp3/x", f"//music/{tok}/now", f"/music/{tok}/now", ""):
            assert music_route(bad, tok if bad != f"/music/{tok}/now" else "") is None, bad
        now = {"title": "First One", "playlist": "Mix", "playing": True}
        srv, eng = MusicServer(0, tok, lambda: dict(now, secret="C:\\x"), host="127.0.0.1"), MusicEngine()
        try:
            eng.set_sink("obs", srv.feed)
            eng.play(s1)
            base, web = f"http://127.0.0.1:{srv.port}/music/{tok}", link_noproxy()
            with web.open(base + "/stream.mp3", timeout=10) as r:
                assert r.headers["Content-Type"] == "audio/mpeg"
                data = b""
                while len(data) < 30000:  # over 1 s: the song, its end, then silence - one stream
                    data += r.read(4096)
                eng.pause(True)
                more = r.read(12000)  # paused: still streaming
            (Path(d) / "got.mp3").write_bytes(data + more)
            assert probe(Path(d) / "got.mp3")["codec_name"] == "mp3"
            assert json.loads(web.open(base + "/now.json", timeout=5).read()) == now  # no paths, nothing else
            assert "now.json" in web.open(base + "/now", timeout=5).read().decode()
            for bad in (f"/music/{'0' * 32}/stream.mp3", "/", f"/music/{tok}/x"):
                try:
                    web.open(f"http://127.0.0.1:{srv.port}{bad}", timeout=5)
                    raise AssertionError(bad)
                except HTTPError as e:
                    assert e.code == 404, (bad, e.code)
            old = base
            srv.retoken("cd" * 16)
            try:
                web.open(old + "/now.json", timeout=5)
                raise AssertionError("old link still works")
            except HTTPError as e:
                assert e.code == 404
        finally:
            eng.close()
            srv.stop()

        obs_selftest(Path(d), write_wav, t)
        transcribe_selftest(Path(d) / "transcribe")
        remote_selftest()

        # Setup tab: Light / Dark / Follow Windows, then each folder's check and the user's own choice of folder
        assert ui_mode("dark") == "dark" and ui_mode("light") == "light" and ui_mode("odd") == "light"
        assert ui_mode("system", lambda: False) == "dark" and ui_mode("system", lambda: True) == "light"
        assert ui_mode("system", lambda: None) == "light"  # Windows' setting unreadable: light
        assert win_light_theme() in (True, False, None)
        for pal in (UI_LIGHT, UI_DARK):
            assert pal.keys() == UI_LIGHT.keys()
            used = [pal[k] for k in ("bg", "panel", "border", "accent", "accent2", "sound", "missing", "other", "auto")]
            assert len(set(used)) == len(used), used  # a colour on screen maps back to one meaning when switching
        s = Path(d) / "setup"
        assert setup_check("sd_dir", s) == "missing" and setup_check("vts", s) == "missing"
        (s / "ProfilesV3" / "X.sdProfile").mkdir(parents=True)
        (s / "ProfilesV3" / "X.sdProfile" / "manifest.json").write_text('{"Name": "X"}')
        (s / "Backgrounds").mkdir(), (s / "Live2DModels").mkdir()
        assert setup_check("sd_dir", s) == "found" and setup_check("vts", s) == "found"
        (s / "ffmpeg.exe").write_bytes(b"")
        assert setup_check("ffmpeg", s) == "missing"  # needs ffprobe too
        (s / "ffprobe.exe").write_bytes(b"")
        assert setup_check("ffmpeg", s) == "found" and setup_check("sd_exe", s / "ffmpeg.exe") == "found"
        assert setup_check("sd_exe", s / "none.exe") == "missing" and setup_check("sd_exe", None) == "missing"
        assert setup_check("inbox", s / "new") == "new" and setup_check("inbox", s) == "found"
        assert setup_auto("vts_backups") == FFMPEG_DIR.parent / "VTube Studio backups"
        keep, path0 = {k: shared(k) for k in SETUP_GLOBALS.values()}, os.environ["PATH"]
        try:
            setup_apply({"sd_dir": str(s), "sd_backups": str(s / "bk"), "ffmpeg": str(s), "inbox": "", "odd": "x"})
            assert SD_DIR == s and SD_BACKUPS == s / "bk" and LINK_INBOX == keep["LINK_INBOX"]  # blank = auto
            assert os.environ["PATH"].split(os.pathsep)[0] == str(s)
            setup_apply({"ffmpeg": str(s)})
            assert os.environ["PATH"].split(os.pathsep).count(str(s)) == 1  # not added twice
            assert [p.name for p, _ in sd_profiles()] == ["X.sdProfile"]  # the chosen folder, looked up at call time
            assert sd_save({s / "a.json": {}}, [s / "ProfilesV3" / "X.sdProfile"]).parent == s / "bk"
            setup_apply({"vts_backups": str(s / "vb"), "vts": str(s)})
            assert vts_backups() == s / "vb" and VTS_ASSETS == s
        finally:
            [set_shared(k_, v_) for k_, v_ in keep.items()]
            os.environ["PATH"] = path0
        assert vts_backups() == FFMPEG_DIR.parent / "VTube Studio backups"
        cmd = app_command()
        assert cmd[0] == sys.executable and (getattr(sys, "frozen", False) or  # the exe restarts itself; from
                                            Path(cmd[1]) == MAIN), cmd  # source: python + script
    print("selftest ok")


def obs_selftest(d, write_wav, t):
    """OBS: websocket frames, the v5 password answer, a client against FakeObs (requests, events, a wrong password,
    reconnecting, no answer), the fixed command list, the trust switch and rate limit (also over a signed link),
    files for OBS, and the soundboard feed mixing its sounds."""
    import time
    from urllib.error import HTTPError
    from urllib.request import Request

    def reader(data):  # recv(n) over bytes
        pos = [0]

        def recv(n):
            if pos[0] + n > len(data):
                raise OSError("short")
            pos[0] += n
            return data[pos[0] - n:pos[0]]
        return recv

    def refused(fn, *a, kind=ValueError):
        try:
            fn(*a)
        except kind:
            return True
        raise AssertionError(f"not refused: {a}")
    # frames: every length form, masked (client) and not (server), fragments with a ping in between
    for n in (0, 1, 125, 126, 65535, 65536, 70000):
        body = bytes(range(256)) * (n // 256) + bytes(n % 256)
        for mask in (True, False):
            f = ws_frame(1, body, mask)
            assert bool(f[1] & 0x80) == mask and len(f) == n + (2 if n < 126 else 4 if n < 65536 else 10) + 4 * mask
            assert ws_read(reader(f), masked=mask) == (1, body), n
    pings = []
    msg = bytes([0x01]) + ws_frame(1, b"hel", False)[1:]  # no FIN: more to come
    msg += ws_frame(9, b"p", False) + bytes([0x00]) + ws_frame(0, b"lo ", False)[1:] + ws_frame(0, b"you", False)
    assert ws_read(reader(msg), lambda o, x: pings.append((o, x))) == (1, b"hello you") and pings == [(9, b"p")]
    close = ws_frame(8, struct_pack_close(4009, "no"), False)
    assert ws_read(reader(close)) == (8, struct_pack_close(4009, "no"))
    for bad in (ws_frame(0, b"x", False),  # a continuation with nothing before it
                bytes([0x01]) + ws_frame(1, b"a", False)[1:] + ws_frame(1, b"b", False),  # a new message mid-way
                bytes([0x09, 0x01]) + b"x",  # a control frame in pieces
                bytes([0x89, 126]) + struct_pack_close(200, ""),  # a control frame too long
                bytes([0xC1, 0x01]) + b"x",  # reserved bits
                bytes([0x83, 0x00])):  # an unknown opcode
        refused(ws_read, reader(bad))
    refused(lambda: ws_read(reader(ws_frame(1, b"x", True)), masked=False))  # a server must not mask
    refused(lambda: ws_read(reader(ws_frame(1, b"x", False)), masked=True))  # a client must
    refused(lambda: ws_read(reader(ws_frame(1, bytes(2000), False)), limit=1000))  # too big
    refused(ws_read, reader(bytes([0x01, 0x00]) + bytes([0x00, 0x00]) * 10001 + ws_frame(0, b"x", False)))  # endless
    # the v5 password answer: the protocol guide's example values (checked with .NET's own SHA-256 / Base64)
    assert obs_auth("supersecretpassword", "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=",
                    "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY=") == "1Ct943GAT+6YQUUX47Ia/ncufilbe6+oD6lY+5kaCu4="

    def wait(cond, secs=8):
        end = time.time() + secs
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.02)
        raise AssertionError("timed out")
    fake = FakeObs("s3cret")
    seen, said, clients = [], [], []
    try:
        bad = ObsClient("127.0.0.1", fake.port, "wrong", on_status=lambda on, x: said.append((on, x)))
        clients.append(bad)
        wait(lambda: said)
        time.sleep(0.3)
        assert said == [(False, bad.error)] and bad.error.startswith("Wrong password") and not bad.connected, said
        refused(bad.request, "GetSceneList", kind=ObsError)  # it stopped trying
        nopw = ObsClient("127.0.0.1", fake.port, "")
        clients.append(nopw)
        wait(lambda: nopw.error)
        assert "asks for a password" in nopw.error
        said.clear()
        c = ObsClient("127.0.0.1", fake.port, "s3cret", on_event=lambda e, x: seen.append((e, x)),
                      on_status=lambda on, x: said.append(on))
        clients.append(c)
        wait(lambda: c.connected)
        assert c.version == "30.2.0" and said == [True]
        s = obs_state(c)
        assert s == {"scene": "Main", "scenes": ["Main", "BRB"], "stream": False, "record": False, "vcam": False,
                     "items": [{"id": 1, "name": "Camera", "on": True}, {"id": 2, "name": "Clip", "on": True},
                               {"id": 3, "name": "Logo", "on": True}],
                     "inputs": [{"name": n, "kind": k, "muted": False, "volume": 100} for n, k in (
                         ("Mic", "wasapi_input_capture"), ("Desktop Audio", "wasapi_output_capture"),
                         ("Clip", "ffmpeg_source"))],
                     "media": [{"name": "Clip", "kind": "ffmpeg_source", "state": "playing"},
                               {"name": "Logo", "kind": "image_source", "state": ""}]}, s

        def here(cmd, a):
            return obs_here(c, cmd, obs_check(cmd, a))
        here("scene", {"scene": "BRB"})
        wait(lambda: ("CurrentProgramSceneChanged", {"sceneName": "BRB"}) in seen)  # its event came
        here("item", {"scene": "Main", "id": 2, "on": False})
        here("mute", {"input": "Mic", "muted": True})
        here("volume", {"input": "Desktop Audio", "percent": 50})
        here("media", {"input": "Clip", "action": "pause"})
        for k in ("stream", "record", "vcam"):
            here("output", {"output": k, "action": "start"})
        s = here("state", {})
        assert s["scene"] == "BRB" and fake.items["Main"][1]["sceneItemEnabled"] is False and s["sounds"] == []
        assert fake.inputs["Mic"]["muted"] and fake.inputs["Desktop Audio"]["mul"] == 0.25
        assert [i["volume"] for i in s["inputs"]] == [100, 50, 100] and s["inputs"][0]["muted"]
        assert s["media"][0]["state"] == "paused" and s["stream"] and s["record"] and s["vcam"]
        refused(here, "output", {"output": "stream", "action": "start"}, kind=ObsError)  # already live
        try:
            here("scene", {"scene": "Nope"})
            raise AssertionError("no such scene")
        except ObsError as e:
            assert "No source" in str(e) and "SetCurrentProgramScene" in str(e)
        url = f"http://127.0.0.1:9/music/{'a' * 32}/stream.mp3"
        here("add_feed", {"scene": "Main", "name": "CM music", "url": url})
        here("add_feed", {"scene": "Main", "name": "CM overlay", "url": f"http://10.0.0.5:1/music/{'a' * 32}/now"})
        assert fake.inputs["CM music"] == {"kind": "ffmpeg_source", "muted": False, "mul": 1.0, "media": "playing",
                                           "settings": {"is_local_file": False, "input": url, "input_format": "mp3",
                                                        "restart_on_activate": False, "close_when_inactive": False}}
        assert fake.inputs["CM overlay"]["kind"] == "browser_source"
        # files for OBS: into a source (the right kind only), or new sources
        pic, clip = d / "obs pic.png", d / "obs clip.wav"
        pic.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(32))
        write_wav(clip, [0.1 * np.sin(2 * np.pi * 300 * t)])
        assert "into 'Logo'" in obs_put_files(c, [pic], {"input": "Logo"})
        assert fake.inputs["Logo"]["settings"] == {"file": str(pic.resolve())}
        obs_put_files(c, [clip], {"input": "Clip"})
        assert fake.inputs["Clip"]["settings"] == {"local_file": str(clip.resolve()), "is_local_file": True}
        refused(obs_put_files, c, [clip], {"input": "Logo"})  # a sound into a picture source
        refused(obs_put_files, c, [pic], {"input": "Mic"})
        obs_put_files(c, [pic, clip], {"scene": "BRB", "name": "Got"})
        assert fake.inputs["Got"]["kind"] == "image_source" and fake.inputs["Got 2"]["kind"] == "ffmpeg_source"
        assert [i["sourceName"] for i in fake.items["BRB"]] == ["Logo", "Got", "Got 2"]
        assert peer_proposal("obs", {"input": "Logo"}, 1) == {"input": "Logo"}
        assert peer_proposal("obs", {"scene": "BRB", "name": "Got"}, 2) == {"scene": "BRB", "name": "Got"}
        for spec, n in (({"input": "Logo"}, 2), ({"input": "Logo", "scene": "BRB"}, 1), ({"scene": "BRB"}, 1),
                        ({"scene": "", "name": "x"}, 1), ({"scene": "BRB", "name": "x"}, 21), ({"path": "C:\\x"}, 1),
                        ({"input": "a\nb"}, 1), ({"scene": "BRB", "name": "x"}, 0)):
            refused(peer_proposal, "obs", spec, n)
        peer_check_files("obs", {}, [pic, clip])
        (d / "obs evil.png").write_bytes(b"MZ" + bytes(40))
        refused(peer_check_files, "obs", {}, [d / "obs evil.png"])  # a program named .png
        # dropped: it comes back by itself; no answer: a timeout, not a hang
        said.clear()
        fake.kick()
        wait(lambda: said[-2:] == [False, True], 10)
        assert obs_state(c)["scene"] == "BRB"
        fake.silent, c.timeout = True, 0.5
        t0 = time.time()
        refused(c.request, "GetSceneList", kind=ObsError)
        assert time.time() - t0 < 2
        fake.silent = False
        # the fixed list: each command's arguments exactly, each of the right type
        assert obs_check("volume", {"input": "Mic", "percent": 0}) == {"input": "Mic", "percent": 0}
        assert obs_check("state", {}) == {}
        for cmd, a in (("CreateInput", {}), ("GetInputSettings", {"inputName": "x"}), (None, {}), ("state", None),
                       ("state", {"x": 1}), ("scene", {}), ("scene", {"scene": ""}), ("scene", {"scene": "a\nb"}),
                       ("scene", {"scene": "x" * 257}), ("scene", {"scene": 5}), ("scene", {"scene": "M", "x": 1}),
                       ("item", {"scene": "M", "id": True, "on": True}), ("item", {"scene": "M", "id": -1, "on": 1}),
                       ("volume", {"input": "Mic", "percent": 101}), ("volume", {"input": "Mic", "percent": 5.5}),
                       ("mute", {"input": "Mic", "muted": "yes"}), ("media", {"input": "C", "action": "next"}),
                       ("output", {"output": "replay", "action": "start"}), ("feed_play", {"sound": ["x"]})):
            refused(obs_check, cmd, a)
        assert obs_feed_url(f"http://192.168.1.20:8767/music/{'f' * 32}/stream.mp3")
        for url in ("https://192.168.1.2:1/music/" + "a" * 32 + "/stream.mp3",  # https, a website, a file, user:pw@,
                    "http://8.8.8.8:80/music/" + "a" * 32 + "/stream.mp3", "file:///C:/x.mp3",  # other paths
                    "http://u:p@10.0.0.1:1/music/" + "a" * 32 + "/now", "http://10.0.0.1:1/music/" + "a" * 32 + "/x",
                    "http://10.0.0.1:1/music/" + "A" * 32 + "/now", "http://10.0.0.1:99999/music/" + "a" * 32 + "/now",
                    "http://evil.example:80/music/" + "a" * 32 + "/now", 5):
            refused(obs_feed_url, url)
            refused(obs_check, "add_feed", {"scene": "Main", "name": "x", "url": url})
        # the trust switch (off unless turned on) and the rate limit
        rate, ran = ObsRate(3, 5.0), []

        def run(cmd, a):
            ran.append(cmd)
            return {"done": cmd}
        peer = {"id": "a" * 32, "name": "PC-A"}
        assert obs_serve(None, "state", {}, run, rate)["ok"] is False
        r = obs_serve(peer, "state", {}, run, rate)
        assert r["ok"] is False and "may not control OBS" in r["error"] and not ran
        assert obs_serve(dict(peer, obs=False), "scene", {"scene": "BRB"}, run, rate)["ok"] is False and not ran
        on = dict(peer, obs=True)
        assert obs_serve(on, "scene", {"scene": "BRB"}, run, rate) == {"ok": True, "result": {"done": "scene"}}
        assert "takes exactly" in obs_serve(on, "scene", {"scene": "BRB", "x": 1}, run, rate)["error"]
        assert "Not an OBS command" in obs_serve(on, "StartStream", {}, run, rate)["error"]
        assert [obs_serve(on, "state", {}, run, rate)["ok"] for _ in range(3)] == [True, True, False]
        assert "Too many" in obs_serve(on, "state", {}, run, rate)["error"] and ran == ["scene", "state", "state"]
        assert obs_serve(dict(on, id="b" * 32), "state", {}, run, rate)["ok"]  # per computer
        assert "may not control" in obs_serve(dict(peer, obs="false"), "state", {}, run, ObsRate())["error"]
        feed_add = {"scene": "Main", "name": "x", "url": f"http://10.0.0.7:8767/music/{'a' * 32}/stream.mp3"}
        assert "its own Channel Mirror links" in obs_serve(dict(on, host="10.0.0.8"), "add_feed", feed_add, run,
                                                           ObsRate())["error"]  # only the asking PC's own stream
        assert obs_serve(dict(on, host="10.0.0.7"), "add_feed", feed_add, run, ObsRate())["ok"]
        assert obs_serve(on, "state", {}, lambda c, a: {}["boom"], ObsRate()) == {"ok": False, "error": "'boom'"}
        ran.remove("add_feed")
        assert rate.ok("a" * 32, time.monotonic() + 6)  # and a moment later it goes again
        # over a signed link: the fixed list is checked before anything; the PC with OBS decides
        a_id, secret = "a" * 32, "ab" * 32
        allowed, got = [False], []

        def ask(kind, info):
            got.append((kind, info))
            pr = dict(peer, obs=allowed[0]) if info.get("peer") == a_id else None
            return obs_serve(pr, info["cmd"], info["args"], lambda cmd, a: obs_here(c, cmd, a), ObsRate())
        srv = LinkServer(0, "12341234", d / "obs_inbox", lambda x: None, host="127.0.0.1",
                         peers=lambda: {a_id: (secret, time.time())}, ask=ask)
        try:
            to = {"id": "b" * 32, "name": "PC-B", "host": "127.0.0.1", "port": srv.port, "secret": secret}
            try:
                peer_obs(to, a_id, "scene", {"scene": "Main"})
                raise AssertionError("ran without May control OBS")
            except OSError as e:
                assert str(e).startswith("PC-B: PC-A may not control OBS here") and fake.scene == "BRB", e
            allowed[0] = True
            assert peer_obs(to, a_id, "scene", {"scene": "Main"}) == {} and fake.scene == "Main"
            assert peer_obs(to, a_id, "state")["scene"] == "Main"
            n = len(got)
            for cmd, a in (("GetInputSettings", {"inputName": "Mic"}), ("scene", {"scene": "Main", "more": 1})):
                try:
                    peer_obs(to, a_id, cmd, a)
                    raise AssertionError("a command off the list went through")
                except OSError as e:
                    assert "Not accepted" in str(e), e
            assert len(got) == n  # refused at the door: never asked
            try:
                peer_obs(dict(to, secret="cd" * 32), a_id, "state")
                raise AssertionError("unsigned")
            except OSError as e:
                assert "Not a linked computer" in str(e)
            try:  # unsigned, straight at the server: refused before anything else
                link_noproxy().open(Request(f"http://127.0.0.1:{srv.port}/peer/obs", data=b'{"cmd": "state"}',
                                            method="POST"), timeout=5)
                raise AssertionError("unsigned request answered")
            except HTTPError as e:
                assert e.code == 403
        finally:
            srv.stop()
    finally:
        for x in clients:
            x.close()
        fake.stop()
    # the soundboard feed: sounds mixed into one endless stream, silence between them
    lo, hi = d / "feed lo.wav", d / "feed hi.wav"
    write_wav(lo, [0.3 * np.sin(2 * np.pi * 400 * t[:22050])])
    write_wav(hi, [0.3 * np.sin(2 * np.pi * 1000 * t[:22050])])
    feed, blocks = SoundFeed(), []
    try:
        feed.set_sink("t", blocks.append)
        time.sleep(0.2)
        assert blocks and all(b == bytes(MUSIC_BLOCK) for b in blocks)  # nothing played: silence, still coming
        n0 = len(blocks)
        assert obs_here(None, "feed_play", {"sound": "feed lo.wav"}, feed, [lo, hi]) == {}
        feed.play(hi, 100)
        refused(obs_here, None, "feed_play", {"sound": "other.wav"}, feed, [lo])  # only the soundboard's, by name
        wait(lambda: sum(any(b) for b in blocks[n0:]) > 10)
        assert sorted(feed.playing()) == ["feed hi.wav", "feed lo.wav"]
        time.sleep(0.1)
        both = np.frombuffer(b"".join(blocks[-8:]), "<i2")[::2].astype(float)
        spec = np.abs(np.fft.rfft(both))
        freqs = np.fft.rfftfreq(len(both), 1 / 48000)

        def peak(hz):
            return spec[np.argmin(abs(freqs - hz))]
        assert peak(400) > 20 * peak(700) and peak(1000) > 20 * peak(700), (peak(400), peak(1000), peak(700))
        wait(lambda: not feed.playing(), 5)
        time.sleep(0.1)
        assert all(b == bytes(MUSIC_BLOCK) for b in blocks[-3:])  # both ended: silence again, the stream goes on
        long_ = d / "feed long.wav"
        write_wav(long_, [0.3 * np.sin(2 * np.pi * 400 * np.tile(t, 4))])
        for _ in range(20):  # more than it mixes at once: the oldest give way, nothing wraps past 16 bits
            feed.play(long_, 100)
        assert len(feed.playing()) == SoundFeed.MAX, feed.playing()
        wait(lambda: sum(any(b) for b in blocks[-5:]) == 5)
        x = np.frombuffer(b"".join(blocks[-5:]), "<i2")
        assert abs(x.astype(int)).max() > 20000  # 16 loud sounds: clipped at the top, never wrapped round
        obs_here(None, "feed_stop", {}, feed, [])
        assert feed.playing() == []
        span = len(blocks)
        time.sleep(0.5)
        assert 18 <= len(blocks) - span <= 32  # real time: 50 blocks a second
    finally:
        feed.close()


def pdf_text(data):
    """The text of each page of a PDF written by docs.pdf_write, read back the way a PDF reader does: through the
    xref table to each page's content, and each font's ToUnicode map from glyphs to characters."""
    import re
    import zlib
    sx = int(re.search(rb"startxref\n(\d+)\n%%EOF\n$", data).group(1))
    objs = {}
    for n, r in enumerate(data[sx:].split(b"\n")[3:], 1):
        if not r.endswith(b" n "):
            break
        at = int(r[:10])
        objs[n] = data[at:data.index(b"\nendobj\n", at)]

    def stream(o):
        return zlib.decompress(o[o.index(b"stream\n") + 7:o.rindex(b"\nendstream")])

    def ref(o, key):
        return objs[int(re.search(key + rb" (\d+) 0 R", o).group(1))]
    maps, pages = {}, []
    for k in re.findall(rb"(\d+) 0 R", re.search(rb"/Kids \[([^\]]*)\]", data).group(1)):
        pg = objs[int(k)]
        for f, n in re.findall(rb"/F(\d+) (\d+) 0 R", pg):
            if f.decode() not in maps:
                cmap = stream(ref(objs[int(n)], rb"/ToUnicode")).decode()
                maps[f.decode()] = {int(g, 16): bytes.fromhex(u).decode("utf-16-be")
                                    for g, u in re.findall(r"<([0-9A-F]{4})> <([0-9A-F]+)>", cmap)}
        text = []
        for part in stream(ref(pg, rb"/Contents")).decode().split("ET"):
            text.append("".join("".join(maps[f].get(int(h[i:i + 4], 16), "?") for i in range(0, len(h), 4))
                                for f, h in re.findall(r"/F(\d+) [\d.]+ Tf <([0-9A-F]*)> Tj", part)))
        pages.append("\n".join(text))
    return pages


def transcribe_selftest(d):
    """Transcriber: the whisper command line (paths escaped for ffmpeg, checked by a real ffmpeg), its JSON / SRT
    read back, the Word and PDF writers (valid structure, hostile text kept as text, every script extractable from
    the PDF through its ToUnicode maps), and model downloads against a fake server on 127.0.0.1 (pinned names only,
    size + SHA-256 checked, resumed, cancelled, never left half-written). No real download, no model needed."""
    import hashlib
    import http.server
    import re
    import struct
    import threading
    import xml.etree.ElementTree as ET
    import zipfile
    import zlib
    import cmlib.transcribe as T
    from .docs import TrueType, docx_write, pdf_write, xml_text
    from .transcribe import (
        VAD_MODELS, VAD_URL, WHISPER_DEFAULT, WHISPER_MODELS, WHISPER_URL, Cancelled, _esc, model_download, model_file,
        model_ready, srt_parse, srt_text, stamp, transcribe, transcript_paths, txt_text, whisper_command, whisper_ok,
        whisper_parse, write_transcript)
    d.mkdir(parents=True, exist_ok=True)

    # the pinned models: official URLs, a size and a SHA-256 each; a name outside the list never becomes a path
    assert re.fullmatch(r"https://huggingface\.co/ggerganov/whisper\.cpp/resolve/[0-9a-f]{40}/ggml-\{\}\.bin", WHISPER_URL)
    assert re.fullmatch(r"https://huggingface\.co/ggml-org/whisper-vad/resolve/[0-9a-f]{40}/ggml-\{\}\.bin", VAD_URL)
    assert WHISPER_DEFAULT == "small" and {"tiny", "tiny.en", "base", "small", "medium", "large-v3-turbo"} <= set(
        WHISPER_MODELS)
    for size, sha in [*WHISPER_MODELS.values(), *VAD_MODELS.values()]:
        assert size > 500_000 and re.fullmatch(r"[0-9a-f]{64}", sha)
    for bad in ("../evil", "tiny/../../x", "", "TINY"):
        try:
            model_file(bad)
            raise AssertionError(bad)
        except ValueError:
            pass

    # the command line: first audio track only, 16 kHz mono into whisper, JSON out, progress on stdout
    weird = d / "it's [a],b;c d"
    weird.mkdir(exist_ok=True)
    cmd = whisper_command("in.mkv", weird / "m.bin", weird / "out.json", "de", True, weird / "v.bin")
    af = cmd[cmd.index("-af") + 1]
    assert cmd[cmd.index("-map") + 1] == "0:a:0" and "-vn" in cmd and cmd[cmd.index("-progress") + 1] == "pipe:1"
    assert af.startswith("aresample=16000,aformat=channel_layouts=mono,whisper=model=") and ":language=de:" in af
    assert ":use_gpu=1:" in af and ":format=json:" in af and ":vad_model=" in af, af
    plain = whisper_command("a", "m", "o", gpu=False)
    plain = plain[plain.index("-af") + 1]
    assert "vad_model" not in plain and plain.endswith(":queue=30") and ":use_gpu=0:" in plain and "queue" not in af
    assert _esc("C:/a'b") == r"C\\:/a\\\'b" and _esc("x,y;[z]") == r"x\,y\;\[z\]"
    # a real ffmpeg takes the escaped path whole (a filter that writes a file, so no model is needed)
    target = weird / "meta, it's [1]; x.txt"  # and the drive's C: (Windows names can't hold a colon)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=0.2", "-af",
                    f"aresample=16000,ametadata=mode=print:file={_esc(target.as_posix())}", "-f", "null", "-"],
                   check=True, capture_output=True, creationflags=NO_WINDOW)
    assert target.is_file(), list(weird.iterdir())  # made under exactly that name (it stays empty: no metadata)
    assert whisper_ok("no-such-ffmpeg-here") is False and isinstance(whisper_ok(), bool)

    # what whisper writes -> voice lines (seconds), and the subtitle / text forms
    raw = ('{"start":2971,"end":5971,"text":" The quick brown fox."}\n{"start":5943,"end":7583,"text":"  "}\n'
           '{"start":3600000,"end":3661500,"text":"jumps\\nover  \\"it\\""}\n')
    segs = whisper_parse(raw)
    assert segs == [(2.971, 5.971, "The quick brown fox."), (3600.0, 3661.5, 'jumps over "it"')], segs
    assert whisper_parse("[" + raw.strip().replace("\n", ",") + "]") == segs and whisper_parse("  \n") == []
    assert stamp(0) == "00:00:00" and stamp(3661.5) == "01:01:01" and stamp(3661.5, True) == "01:01:01,500"
    assert stamp(-1) == "00:00:00" and stamp(360000) == "100:00:00"
    srt = srt_text(segs)
    assert srt.startswith("1\n00:00:02,971 --> 00:00:05,971\nThe quick brown fox.\n\n2\n01:00:00,000 --> ") and \
        srt_parse(srt) == segs and srt_parse(srt.replace("\n", "\r\n")) == segs
    assert txt_text("Talk", segs) == 'Talk\n\n[00:00:02]  The quick brown fox.\n[01:00:00]  jumps over "it"\n'

    # Word: a real package (zip + XML parts Word needs), hostile text stays text, bad XML characters dropped
    hostile = '</w:t></w:r><w:r><w:t>evil & <b> "q" \x00\x01\x1f ok'
    lines = [("00:00:01", "Plain line"), ("00:00:02", hostile), ("01:02:03", "Ünïcødé 中文 עברית 🙂")]
    docx = d / "t.docx"
    docx_write(docx, "Title <&> \x02", lines)
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(docx) as z:
        assert z.testzip() is None and z.namelist()[0] == "[Content_Types].xml"
        assert {"_rels/.rels", "word/document.xml", "docProps/core.xml"} <= set(z.namelist())
        parts = {n: ET.fromstring(z.read(n)) for n in z.namelist()}  # every part is well-formed XML
        types = z.read("[Content_Types].xml").decode()
        assert 'PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.' \
               'wordprocessingml.document.main+xml"' in types
        assert 'Target="word/document.xml"' in z.read("_rels/.rels").decode()
    paras = parts["word/document.xml"].find(f"{w}body").findall(f"{w}p")
    texts = ["".join(t.text or "" for t in p.iter(f"{w}t")) for p in paras]
    assert texts == ["Title <&> ", "[00:00:01]Plain line", '[00:00:02]</w:t></w:r><w:r><w:t>evil & <b> "q"  ok',
                     "[01:02:03]Ünïcødé 中文 עברית 🙂"], texts
    assert xml_text('a<b>&"\x0b\ud800') == "a&lt;b&gt;&amp;&quot;"

    # PDF: structure (xref offsets exact), embedded subset fonts, and every line's text extractable
    many = lines + [(stamp(i * 7), f"Line {i}: Ελληνικά Русский 中文 日本語 한국어 " + "word " * (i % 40))
                    for i in range(150)]
    pdf = d / "t.pdf"
    pdf_write(pdf, "Transcript: Ünï 中文", many)
    b = pdf.read_bytes()
    assert b.startswith(b"%PDF-1.7\n") and b.endswith(b"%%EOF\n")
    sx = int(re.search(rb"startxref\n(\d+)\n%%EOF\n$", b).group(1))
    assert b[sx:sx + 5] == b"xref\n"
    first, count = map(int, re.match(rb"xref\n(\d+) (\d+)\n", b[sx:]).groups())
    rows = b[sx:].split(b"\n")[2:2 + count]
    assert first == 0 and rows[0] == b"0000000000 65535 f " and all(len(r) == 19 for r in rows)
    objs = {}
    for n, r in enumerate(rows[1:], 1):
        at = int(r[:10])
        assert b[at:].startswith(f"{n} 0 obj\n".encode()), n
        objs[n] = b[at:b.index(b"\nendobj\n", at)]
    trailer = b[b.index(b"trailer", sx):]
    assert f"/Size {count}".encode() in trailer
    root = int(re.search(rb"/Root (\d+) 0 R", trailer).group(1))
    assert b"/Type /Catalog" in objs[root]

    def stream(o):
        raw_ = o[o.index(b"stream\n") + 7:o.rindex(b"\nendstream")]
        assert int(re.search(rb"/Length (\d+)", o).group(1)) == len(raw_)
        return zlib.decompress(raw_)
    fonts = {n: o for n, o in objs.items() if b"/Subtype /Type0" in o}
    assert len(fonts) >= 3, len(fonts)  # Arial, plus the CJK and Korean fonts for what Arial doesn't have
    maps = {}
    for n, o in fonts.items():
        assert b"/Encoding /Identity-H" in o
        cid = objs[int(re.search(rb"/DescendantFonts \[(\d+) 0 R\]", o).group(1))]
        assert b"/Subtype /CIDFontType2" in cid and b"/CIDToGIDMap /Identity" in cid and b"/W [" in cid
        desc = objs[int(re.search(rb"/FontDescriptor (\d+) 0 R", cid).group(1))]
        ff = objs[int(re.search(rb"/FontFile2 (\d+) 0 R", desc).group(1))]
        sub = stream(ff)
        assert int(re.search(rb"/Length1 (\d+)", ff).group(1)) == len(sub)
        (d / "sub.ttf").write_bytes(sub)
        tt = TrueType(d / "sub.ttf")  # the embedded subset is a font that loads again
        cmap = stream(objs[int(re.search(rb"/ToUnicode (\d+) 0 R", o).group(1))]).decode()
        assert "begincmap" in cmap and "/CMapName /Adobe-Identity-UCS def" in cmap
        maps[n] = {int(g, 16): bytes.fromhex(u).decode("utf-16-be")
                   for g, u in re.findall(r"<([0-9A-F]{4})> <([0-9A-F]+)>", cmap)}
        loca = tt.table("loca")
        offs = struct.unpack(f">{tt.glyphs + 1}I", loca)
        kept = {g for g in range(tt.glyphs) if offs[g + 1] > offs[g]}
        assert set(maps[n]) - kept <= {g for g in maps[n] if maps[n][g].isspace()}  # every used glyph is there
        assert len(kept) < tt.glyphs // 2  # and only those: a subset
    pages = pdf_text(b)
    assert len(pages) > 3 and pages[0].startswith("Transcript: Ünï 中文"), pages[0][:80]
    assert all(f"Page {i} of {len(pages)}" in p for i, p in enumerate(pages, 1))
    whole = "".join(pages)
    assert "[00:00:01]\nPlain line" in whole and "Ünïcødé 中文 תירבע 🙂" in whole  # Hebrew in drawing order
    assert '</w:t></w:r><w:r><w:t>evil & <b> "q" ok' in whole, whole[:400]  # (spaces run together when wrapped)
    for i in (0, 77, 149):
        assert f"Line {i}: Ελληνικά Русский 中文 日本語 한국어" in whole, i

    # one file's documents: named "<name> transcript", nothing over the video's own .srt, no temp files left
    src = d / "My talk.mp4"
    (d / "My talk.srt").write_text("the video's own subtitles")
    out = write_transcript(src, segs, None, ["docx", "pdf", "srt", "txt"])
    assert {k: p.name for k, p in out.items()} == {"docx": "My talk transcript.docx", "pdf": "My talk transcript.pdf",
                                                   "srt": "My talk transcript.srt", "txt": "My talk transcript.txt"}
    assert (d / "My talk.srt").read_text() == "the video's own subtitles" and not list(d.glob("*.part"))
    assert srt_parse(out["srt"].read_text(encoding="utf-8")) == segs
    assert transcript_paths(src, d / "elsewhere", ["pdf"]) == {"pdf": d / "elsewhere" / "My talk transcript.pdf"}
    taken = set()  # one run: "My talk.mp4" and another folder's "My talk.m4a" into one folder - both kept
    a = transcript_paths(src, d / "one", ["txt", "pdf"], taken)
    b = transcript_paths(d / "x" / "My talk.m4a", d / "one", ["txt", "pdf"], taken)
    assert a["txt"].name == "My talk transcript.txt" and b == {"txt": d / "one" / "My talk (2) transcript.txt",
                                                               "pdf": d / "one" / "My talk (2) transcript.pdf"}, b
    none = write_transcript(src, [], d / "empty", ["txt", "docx"])
    with zipfile.ZipFile(none["docx"]) as z:
        assert b"No speech was found" in z.read("word/document.xml")

    # GPU first; when that run fails, the same file again on the processor; no audio track: a clear ValueError
    wav = d / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=1", str(wav)], check=True,
                   creationflags=NO_WINDOW)
    mute = d / "mute.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=s=64x64:d=1", "-c:v", "mpeg4",
                    str(mute)], check=True, creationflags=NO_WINDOW)
    runs, real_run = [], T._run

    def fake_run(cmd_, total, progress, cancel):
        gpu = ":use_gpu=1:" in cmd_[cmd_.index("-af") + 1]
        runs.append(gpu)
        assert 0.9 < total < 1.2
        if gpu:
            return "ggml_vulkan: no device"
        dest = cmd_[cmd_.index("-af") + 1].split("destination=")[1].split(":queue=")[0].replace("\\", "")
        Path(dest).write_text('{"start":0,"end":900,"text":"hi"}\n', encoding="utf-8")
    T._run = fake_run
    try:
        info = {}
        assert transcribe(wav, "m.bin", info=info) == [(0.0, 0.9, "hi")] and runs == [True, False] and info["gpu"] is False
        runs.clear()
        T._run = lambda *a: "it broke"
        try:
            transcribe(wav, "m.bin", gpu=False)
            raise AssertionError("no error")
        except RuntimeError as e:
            assert str(e) == "it broke"
        try:
            transcribe(mute, "m.bin")
            raise AssertionError("no error")
        except ValueError as e:
            assert "No readable audio" in str(e), e
    finally:
        T._run = real_run

    # downloads, from a fake server here: right size + checksum, resumed with Range, cancelled, refused when wrong
    blob = os.urandom(300_000)
    table = {"fake": (len(blob), hashlib.sha256(blob).hexdigest())}
    srv_state = {"mode": "ok", "ranges": [], "hits": 0}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            srv_state["hits"] += 1
            assert self.path == "/ggml-fake.bin", self.path
            data, start = blob, 0
            rng = self.headers.get("Range")
            srv_state["ranges"].append(rng)
            if srv_state["mode"] == "bad":
                data = blob[:-1] + bytes([blob[-1] ^ 1])
            if srv_state["mode"] == "big":
                data = blob + b"x" * 100_000
            if srv_state["mode"] == "short":  # promises it all, then the connection ends a third of the way in
                self.send_response(200)
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob[:100_000])
                self.close_connection = True
                return
            if rng and srv_state["mode"] == "416":
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                srv_state["mode"] = "ok"
                return
            if rng and srv_state["mode"] == "ok":
                start = int(rng.split("=")[1].rstrip("-"))
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(blob) - 1}/{len(blob)}")
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(data) - start))
            self.end_headers()
            self.wfile.write(data[start:])
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/ggml-{{}}.bin"
    md = d / "models"
    try:
        said = []
        got = model_download("fake", lambda m, f: said.append(f), None, table, url, md)
        assert got == md / "ggml-fake.bin" and got.read_bytes() == blob and model_ready("fake", table, md)
        assert said[-1] == 1.0 and not list(md.glob("*.part")) and srv_state["ranges"] == [None]
        assert model_download("fake", lambda *a: None, None, table, url, md) == got and srv_state["hits"] == 1
        got.unlink()
        part = md / "ggml-fake.bin.part"
        part.write_bytes(blob[:120_000])  # a download cut off earlier: only the rest is fetched
        model_download("fake", lambda *a: None, None, table, url, md)
        assert got.read_bytes() == blob and srv_state["ranges"][-1] == "bytes=120000-" and not part.exists()
        got.unlink()
        srv_state["mode"] = "short"  # cut off: the part is kept (not thrown away), and the next try continues it
        try:
            model_download("fake", lambda *a: None, None, table, url, md)
            raise AssertionError("not cut off")
        except RuntimeError as e:
            assert "cut off" in str(e), e
        assert part.read_bytes() == blob[:100_000] and not got.exists()
        srv_state["mode"] = "ok"
        model_download("fake", lambda *a: None, None, table, url, md)
        assert got.read_bytes() == blob and srv_state["ranges"][-1] == "bytes=100000-"
        got.unlink()
        part.write_bytes(blob[:50_000])
        srv_state["mode"] = "416"  # a .part the server won't continue: started again, not stuck for ever
        model_download("fake", lambda *a: None, None, table, url, md)
        assert got.read_bytes() == blob and srv_state["ranges"][-2:] == ["bytes=50000-", None]
        got.unlink()
        srv_state["mode"] = "norange"  # a server that ignores Range: the whole file again, not a mixed one
        part.write_bytes(b"\0" * 120_000)
        model_download("fake", lambda *a: None, None, table, url, md)
        assert got.read_bytes() == blob
        got.unlink()
        srv_state["mode"] = "ok"
        part.write_bytes(blob)  # a whole .part never checked (stopped at the end): fetched again, not trusted
        model_download("fake", lambda *a: None, None, table, url, md)
        assert got.read_bytes() == blob and srv_state["ranges"][-1] is None
        for mode in ("bad", "big"):  # damaged or too long: refused, nothing left under the model's name
            got.unlink(missing_ok=True)
            srv_state["mode"] = mode
            try:
                model_download("fake", lambda *a: None, None, table, url, md)
                raise AssertionError(mode)
            except RuntimeError as e:
                assert "damaged" in str(e), e
            assert not got.exists() and not part.exists() and not model_ready("fake", table, md)
        part.unlink(missing_ok=True)
        srv_state["mode"] = "ok"
        stop = threading.Event()
        stop.set()
        try:
            model_download("fake", lambda *a: None, stop, table, url, md)
            raise AssertionError("not cancelled")
        except Cancelled:
            pass
        assert not got.exists()
        got.write_bytes(blob[:10])  # a wrong-sized file under the name isn't taken for the model
        assert not model_ready("fake", table, md)
    finally:
        srv.shutdown()
        srv.server_close()
    print("transcribe ok")


class FakeVts:
    """A stand-in for VTube Studio's API (its websocket on 127.0.0.1), for tests only - never the real VTube Studio.
    The model "Wolf" with two background hotkeys and an animation one. allow = what its Allow / Deny answers;
    self.triggered = the hotkeys triggered, self.asked = the token requests."""
    HOTKEYS = [{"name": "Stars", "type": "ChangeBackground", "file": "stars", "hotkeyID": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"},
               {"name": "Rain", "type": "ChangeBackground", "file": "rain", "hotkeyID": "0f1e2d3c4b5a69788796a5b4c3d2e1f0"},
               {"name": "Wave", "type": "TriggerAnimation", "file": "wave.motion3.json", "hotkeyID": "77"}]

    def __init__(self, allow=True):
        import secrets
        import socket
        import threading
        self.allow, self.token, self.triggered, self.asked = allow, "tok-" + secrets.token_hex(8), [], 0
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def stop(self):
        self.sock.close()

    def _accept(self):
        import threading
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        import base64
        import hashlib
        buf = [b""]

        def recv(n):
            while len(buf[0]) < n:
                got = c.recv(65536)
                if not got:
                    raise OSError("closed")
                buf[0] += got
            out, buf[0] = buf[0][:n], buf[0][n:]
            return out
        try:
            while b"\r\n\r\n" not in buf[0]:
                buf[0] += c.recv(4096) or b"\r\n\r\n"
            head, buf[0] = buf[0].split(b"\r\n\r\n", 1)
            h = {k.strip().lower(): v.strip() for k, _, v in (x.partition(":") for x in head.decode().split("\r\n")[1:])}
            acc = base64.b64encode(hashlib.sha1((h["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
                                                .encode()).digest()).decode()
            c.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {acc}\r\n\r\n".encode())
            authed = False
            while True:
                op, data = ws_read(recv, masked=True)
                if op == 8:
                    return
                m = json.loads(data)
                t, d, out = m["messageType"], m.get("data") or {}, None
                if t == "AuthenticationTokenRequest":
                    self.asked += 1
                    out = ("AuthenticationTokenResponse", {"authenticationToken": self.token}) if self.allow else (
                        "APIError", {"errorID": 50, "message": "User has denied API access for your plugin."})
                elif t == "AuthenticationRequest":
                    authed = d.get("authenticationToken") == self.token and d.get("pluginName") == "Channel Mirror"
                    out = ("AuthenticationResponse", {"authenticated": authed, "reason": "ok" if authed else "bad"})
                elif not authed:
                    out = ("APIError", {"errorID": 8, "message": "Plugin not authenticated."})
                elif t == "HotkeysInCurrentModelRequest":
                    out = ("HotkeysInCurrentModelResponse", {"modelLoaded": True, "modelName": "Wolf",
                                                             "modelID": "m1", "availableHotkeys": self.HOTKEYS})
                elif t == "HotkeyTriggerRequest":
                    if d.get("hotkeyID") in [x["hotkeyID"] for x in self.HOTKEYS]:
                        self.triggered.append(d["hotkeyID"])
                        out = ("HotkeyTriggerResponse", {"hotkeyID": d["hotkeyID"]})
                    else:
                        out = ("APIError", {"errorID": 101, "message": "Hotkey not found."})
                else:
                    out = ("APIError", {"errorID": 2, "message": "Unknown request."})
                c.sendall(ws_frame(1, json.dumps({"op": 0}).encode(), mask=False))  # (an unrelated message first)
                c.sendall(ws_frame(1, json.dumps({"apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                                                  "requestID": m["requestID"], "messageType": out[0],
                                                  "data": out[1]}).encode(), mask=False))
        except (OSError, ValueError, KeyError):
            pass
        finally:
            c.close()


def remote_call(port, key, dev, cmd, args=None, t=None, nonce=None, body=None, sig=None):
    """One signed request to a phone remote, as the web app makes it -> (status, headers, parsed reply or text)."""
    import hashlib
    import http.client
    import secrets
    import time
    from .peers import peer_sign
    body = json.dumps({"cmd": cmd, "args": args or {}}).encode() if body is None else body
    t = int(time.time()) if t is None else t
    nonce = nonce or secrets.token_hex(16)
    bh = hashlib.sha256(body).hexdigest()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", "/api", body, {"Content-Type": "application/json", "X-Dev": dev, "X-Time": str(t),
                                     "X-Nonce": nonce, "X-Body": bh,
                                     "X-Sig": sig or peer_sign(key, "POST", "/api", t, nonce, bh)})
    r = c.getresponse()
    data, h = r.read(), dict(r.getheaders())
    c.close()
    if r.status in (200, 409):  # answers to a request signed right: signed back (the clock one too)
        assert h.get("X-Sig") == peer_sign(key, "REPLY", "/api", 0, nonce, hashlib.sha256(data).hexdigest()), h
        return r.status, h, json.loads(data)
    return r.status, h, data.decode(errors="replace")


def remote_update_selftest(devs, run, ask):
    """The Android app's updates over the link: version numbers, the web bundle (each file's SHA-256, the version
    being the hash of that list), the APK - served only to a paired phone, in signed parts, its hash in the signed
    check; the download page link (GET /app.apk) on allowed addresses only."""
    import base64
    import hashlib
    import http.client
    import tempfile
    import cmlib.remote as R
    from .peers import peer_sign
    from .remote_app import remote_files
    # versions: VERSION + a build number -> Android's versionCode / versionName; newer always compares higher
    assert R.remote_apk_version("2.2", 7) == (2020007, "2.2.7") and R.remote_apk_name(2020007) == "2.2.7"
    assert R.remote_apk_version("2.10", 1)[0] > R.remote_apk_version("2.9", 9999)[0]
    assert R.remote_apk_version("3.0", 1)[0] > R.remote_apk_version("2.99", 9999)[0]
    assert R.remote_apk_version("2.2", 8)[0] > R.remote_apk_version("2.2", 7)[0]
    for bad in (("2.2", 0), ("2.2", 10000), ("x", 1), ("2.100", 1), ("2", 1), ("2.2.1", 1)):
        try:
            R.remote_apk_version(*bad)
            raise AssertionError(f"version accepted: {bad}")
        except ValueError:
            pass
    # the web bundle: every file of the web app, its SHA-256; the version is the hash of that list
    files, w = remote_files(), R.remote_web(True)
    assert set(w["files"]) == set(files) and R.remote_web()["version"] == w["version"]
    for p, f in w["files"].items():
        data = base64.b64decode(f["data"])
        assert data == files[p][1] and f["sha256"] == hashlib.sha256(data).hexdigest() and f["type"] == files[p][0]
    man = {p: f["sha256"] for p, f in w["files"].items()}
    assert w["version"] == hashlib.sha256(json.dumps(man, sort_keys=True, separators=(",", ":")).encode()
                                          ).hexdigest()[:16]
    assert "data" not in next(iter(R.remote_web()["files"].values()))
    # what the PC page says about a phone: behind when its APK is older or its screens aren't this PC's
    pc = {"web": w["version"], "apk": 2020007}
    assert not R.remote_app_behind({"web": w["version"], "apk": 2020007}, pc)
    assert R.remote_app_behind({"web": w["version"], "apk": 2020006}, pc)
    assert R.remote_app_behind({"web": "0" * 16, "apk": 2020007}, pc)
    assert not R.remote_app_behind({"web": w["version"], "apk": 2020007}, {"web": w["version"], "apk": 0})
    assert R.remote_app_label(None, pc) == "browser" and R.remote_app_label({"web": "x", "apk": 0}, pc) == "browser"
    assert R.remote_app_label({"web": w["version"], "apk": 2020007}, pc) == "2.2.7"
    assert R.remote_app_label({"web": w["version"], "apk": 2020005}, pc) == "2.2.5 - update available"
    tmp = Path(tempfile.mkdtemp(prefix="cm_apk_"))
    real_dirs = R.APK_DIRS
    try:
        # the bundle as the APK carries it: manifest.json + each file named by its hash
        assert R.remote_export_web(tmp / "web") == w["version"]
        got = json.loads((tmp / "web" / "manifest.json").read_text())
        assert got["version"] == w["version"] and {p: f["sha256"] for p, f in got["files"].items()} == man
        for p, f in got["files"].items():
            assert hashlib.sha256((tmp / "web" / f["sha256"]).read_bytes()).hexdigest() == f["sha256"]
        # no APK built: none offered
        R.APK_DIRS = [tmp / "none"]
        assert R.remote_apk() is None
        apk = os.urandom(R.APK_PART * 2 + 1234)  # three parts
        (tmp / R.APK_NAME).write_bytes(apk)
        (tmp / (R.APK_NAME + ".json")).write_text(json.dumps({"code": 2020009, "name": "2.2.9"}))
        R.APK_DIRS = [tmp / "none", tmp]
        a = R.remote_apk()
        assert a and a["code"] == 2020009 and a["size"] == len(apk) and a["parts"] == 3 and a["cert"] == ""
        (tmp / (R.APK_NAME + ".json")).write_text(json.dumps({"code": 2020009, "name": "2.2.9", "cert": "ab" * 32}))
        assert R.remote_apk()["cert"] == "ab" * 32
        assert a["sha256"] == hashlib.sha256(apk).hexdigest()
        (tmp / "bad").mkdir()
        (tmp / "bad" / R.APK_NAME).write_bytes(b"x")
        (tmp / "bad" / (R.APK_NAME + ".json")).write_text('{"code": "2020009"}')  # damaged: not offered
        R.APK_DIRS = [tmp / "bad"]
        assert R.remote_apk() is None
        R.APK_DIRS = [tmp]
        devs.clear()
        d1, d2, key = "33" * 16, "44" * 16, "ef" * 32
        devs[d1] = key
        told = []
        srv = R.RemoteServer(["127.0.0.1"], 0, lambda: dict(devs),
                             lambda *a: (told.append(a), run(*a))[1], ask, "PC-test")
        try:
            port = srv.port
            # the signed state announces this PC's versions; the check says what's there (and the PC notes the phone's)
            st_, _, out = remote_call(port, key, d1, "state")
            assert st_ == 200 and out["app"] == {"web": w["version"], "apk": 2020009}, out
            st_, _, out = remote_call(port, key, d1, "app.check", {"web": "0" * 16, "apk": 2020001})
            assert st_ == 200 and out["web"] == w["version"] and out["apk"] == {
                "code": 2020009, "name": "2.2.9", "size": len(apk), "sha256": a["sha256"], "parts": 3}, out
            assert told[-1] == (d1, "app.check", {"web": "0" * 16, "apk": 2020001})  # the PC page notes it
            # the web bundle, signed: the reply's signature covers every file and its hash
            nonce = "77" * 16
            st_, h, out = remote_call(port, key, d1, "app.web", nonce=nonce)
            assert st_ == 200 and out["version"] == w["version"] and out["files"] == w["files"]
            body = json.dumps(out).encode()
            tampered = body.replace(b'"data": "', b'"data": "A', 1)
            assert h["X-Sig"] != peer_sign(key, "REPLY", "/api", 0, nonce, hashlib.sha256(tampered).hexdigest())
            # the APK in parts, each signed (remote_call checks), joined = the file, its hash = the one announced
            parts = [remote_call(port, key, d1, "app.apk", {"part": i})[2] for i in range(3)]
            assert all(p["ok"] for p in parts) and base64.b64decode("".join(p["data"] for p in parts)) == apk
            assert remote_call(port, key, d1, "app.apk", {"part": 3})[2]["ok"] is False  # past the end
            for bad in ({"part": -1}, {"part": "0"}, {}, {"part": 0, "x": 1}):
                assert remote_call(port, key, d1, "app.apk", bad)[2]["ok"] is False, bad
            assert remote_call(port, key, d1, "app.check", {"web": "<script>", "apk": 1})[2]["ok"] is False
            # never to a phone that isn't paired (or was removed)
            assert remote_call(port, "00" * 32, d2, "app.apk", {"part": 0})[0] == 401
            assert remote_call(port, "00" * 32, d2, "app.web")[0] == 401
            assert remote_call(port, "00" * 32, d1, "app.check", {"web": "", "apk": 0})[0] == 401
            # the first install: the APK as a download, on the remote's allowed addresses
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/app.apk")
            r = c.getresponse()
            assert r.status == 200 and r.read() == apk
            assert r.getheader("Content-Type") == "application/vnd.android.package-archive"
            assert "attachment" in r.getheader("Content-Disposition")
            c.close()
            real = R.remote_ok
            R.remote_ok = lambda ip: False
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                c.request("GET", "/app.apk")
                assert c.getresponse().status == 403
                c.close()
            finally:
                R.remote_ok = real
            R.APK_DIRS = [tmp / "none"]  # not built: nothing to download, nothing announced
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/app.apk")
            assert c.getresponse().status == 404
            c.close()
            assert remote_call(port, key, d1, "app.check", {"web": "", "apk": 0})[2]["apk"] is None
            assert remote_call(port, key, d1, "app.apk", {"part": 0})[2]["ok"] is False
            assert remote_call(port, key, d1, "state")[2]["app"] == {"web": w["version"], "apk": 0}
        finally:
            srv.stop()
    finally:
        R.APK_DIRS = real_dirs
        shutil.rmtree(tmp, ignore_errors=True)
    print("phone remote app updates: versions, web bundle hashes, signed APK parts to paired phones only, download")


def remote_selftest():
    """The phone remote: the address filter, QR codes (decoded by OpenCV when it's installed), the crypto the web app
    repeats in JavaScript, the command list, the server (pairing, signatures, replay, rate, lock-out, removal), and
    VTube Studio's API against a fake one."""
    import hashlib
    import http.client
    import time
    import cmlib.remote as R
    from .peers import pair_offer, pair_secret, peer_sign
    from .remote import (REMOTE_COMMANDS, RemoteServer, qr_ecc, qr_matrix, qr_png, remote_check, remote_icon,
                         remote_ok, remote_vectors)
    from .remote_app import remote_files
    from .vts import vts_api, vts_backgrounds
    # the address filter: home network, this PC and Tailscale only
    for ip in ("127.0.0.1", "192.168.1.5", "10.0.0.2", "172.16.3.4", "100.64.0.1", "100.101.102.103",
               "100.127.255.254", "fd7a:115c:a1e0::1", "fd7a:115c:a1e0:ab12::99", "::1", "::ffff:192.168.1.5",
               "::ffff:100.64.9.9"):
        assert remote_ok(ip), ip
    for ip in ("8.8.8.8", "1.1.1.1", "100.63.255.255", "100.128.0.1", "169.254.1.1", "0.0.0.0", "224.0.0.1",
               "255.255.255.255", "::ffff:8.8.8.8", "2001:4860:4860::8888", "fe80::1", "::", "", "nonsense",
               "192.168.1.5.evil", "100.64.0.1/10", None):
        assert not remote_ok(ip), ip
    # QR: the standard's own Reed-Solomon example, then codes read back by a real decoder at every version
    assert qr_ecc([16, 32, 12, 86, 97, 128, 236, 17, 236, 17, 236, 17, 236, 17, 236, 17], 10) == [
        165, 36, 212, 193, 237, 54, 199, 135, 44, 85]
    texts = [("http://192.168.1.23:8770/#pair=12345678" * 6)[:n] for n in (1, 14, 26, 42, 62, 84, 106, 122, 152, 180,
                                                                           213)]
    sizes = [len(qr_matrix(x)) for x in texts]
    assert sizes == [21, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57], sizes  # versions 1-10
    try:
        qr_matrix("x" * 214)
        raise AssertionError("too long for version 10 accepted")
    except ValueError:
        pass
    assert qr_png(qr_matrix("hi"), 3)[:8] == b"\x89PNG\r\n\x1a\n"
    try:
        import cv2
    except ImportError:
        cv2 = None
        print("QR codes not decoded: OpenCV isn't installed (pip install opencv-python to check them)")
    if cv2 is not None:
        det = cv2.QRCodeDetector()
        for x in texts + ["http://desktop-x.tail1234.ts.net:8770/#pair=00000001"]:
            a = np.pad(np.array(qr_matrix(x), bool), 4)
            got = det.detectAndDecode(np.where(np.repeat(np.repeat(a, 6, 0), 6, 1), 0, 255).astype(np.uint8))[0]
            assert got == x, (x, got)
        print(f"QR codes: {len(texts) + 1} read back by OpenCV {cv2.__version__} (versions 1-10)")
    # the crypto the web app does in JavaScript: known answers, and both sides of a pairing agree
    vec = remote_vectors()
    assert vec["sha_abc"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert vec["hmac_fox"] == "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
    xb = int(vec["x_b"], 16)
    assert pair_secret(vec["code"], "B", xb, int(vec["pub_a"], 16), int(vec["pub_b"], 16), vec["id_a"]) == (
        vec["secret"], vec["proof_a"], vec["proof_b"])
    assert remote_vectors() == vec  # nothing random in them
    files = remote_files()
    assert set(files) == {"/", "/app.css", "/app.js", "/sw.js", "/manifest.webmanifest", "/icon-180.png",
                          "/icon-192.png", "/icon-512.png"}, set(files)
    assert b"__P__" not in files["/app.js"][1] and b"innerHTML" not in files["/app.js"][1]  # text only, never HTML
    assert len(remote_icon(512)) > 1000 and json.loads(files["/manifest.webmanifest"][1])["display"] == "standalone"
    # the command list: every command and argument checked, nothing else taken
    assert remote_check("deck.play", {"id": 3, "rev": "0123456789abcdef", "to": "both"})["to"] == "both"
    assert remote_check("obs", {"cmd": "scene", "args": {"scene": "BRB"}}) == {"cmd": "scene", "args": {"scene": "BRB"}}
    assert remote_check("music.volume", {"percent": 40}) == {"percent": 40}
    for cmd, args in (("shell", {}), ("deck.play", {"id": 3, "rev": "0123456789abcdef"}),
                      ("deck.play", {"id": True, "rev": "0123456789abcdef", "to": "feed"}),
                      ("deck.play", {"id": 1000, "rev": "0123456789abcdef", "to": "feed"}),
                      ("deck.play", {"id": 1, "rev": "../../x", "to": "feed"}),
                      ("deck.play", {"id": 1, "rev": "0123456789abcdef", "to": "speakers"}),
                      ("obs", {"cmd": "add_feed", "args": {"scene": "a", "name": "b", "url": "http://x"}}),
                      ("obs", {"cmd": "feed_play", "args": {"sound": "a.wav"}}),
                      ("obs", {"cmd": "scene", "args": {"scene": "BRB", "extra": 1}}),
                      ("obs", {"cmd": "volume", "args": {"input": "Mic", "percent": 101}}),
                      ("music.seek", {"secs": -1}), ("music.volume", {"percent": "50"}), ("vts.bg", {"id": "a b"}),
                      ("vts.bg", {"id": "x" * 65}), ("state", {"x": 1}), ("state", []), (None, {})):
        try:
            remote_check(cmd, args)
            raise AssertionError(f"accepted {cmd} {args}")
        except ValueError:
            pass
    assert "state" in REMOTE_COMMANDS and "rec.start" in REMOTE_COMMANDS

    # the server: a phone pairs (SPAKE2 with the one-time code, then this PC allows it), then signed requests only
    devs, ran, answers = {}, [], []

    def run(dev, cmd, args):
        ran.append((dev, cmd, args))
        if cmd == "vts.bg":
            raise ValueError("no VTube Studio here")
        return {"echo": cmd}

    def ask(info):
        ok = answers.pop(0) if answers else False
        if ok:
            devs[info["id"]] = info["key"]
        return {"ok": True} if ok else None

    def post(port, path, d, nonce=""):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", path, json.dumps(d).encode(), {"X-Nonce": nonce} if nonce else {})
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return out

    def phone(port, code, dev):
        """The web app's pairing, in Python -> (status of the finish, key or None)."""
        import secrets
        x, pa = pair_offer(code, "A")
        st_, _, data = post(port, "/pair/start", {"id": dev, "name": "Test\nphone", "pub": f"{pa:x}"})
        if st_ != 200:
            return st_, None
        d = json.loads(data)
        key, proof_a, proof_b = pair_secret(code, "A", x, pa, int(d["pub"], 16), dev)
        nonce = secrets.token_hex(16)
        st_, h, data = post(port, "/pair/finish", {"session": d["session"],
                                                    "proof": proof_a if d["proof"] == proof_b else "0" * 64}, nonce)
        if st_ == 200:
            assert h["X-Sig"] == peer_sign(key, "REPLY", "/pair/finish", 0, nonce, hashlib.sha256(data).hexdigest())
            assert json.loads(data)["name"] == "PC-test"
        return st_, key if st_ == 200 else None
    srv = RemoteServer(["127.0.0.1"], 0, lambda: dict(devs), run, ask, "PC-test")
    try:
        port, d1, d2 = srv.port, "11" * 16, "22" * 16
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/")
        r = c.getresponse()
        assert r.status == 200 and b"Pair this phone" in r.read() and "frame-ancestors 'none'" in r.getheader(
            "Content-Security-Policy") and r.getheader("X-Content-Type-Options") == "nosniff"
        c.request("GET", "/../settings.json")
        r = c.getresponse()
        assert r.status == 404 and r.read()
        c.close()
        assert phone(port, "12345678", d1) == (403, None)  # no pairing open on the PC
        code = srv.open_pairing()
        answers.append(False)
        assert phone(port, code, d1) == (403, None) and d1 not in devs  # refused on the PC
        assert phone(port, code, d1) == (403, None)  # and the code is used up
        code = srv.open_pairing()
        answers.append(True)
        st_, key1 = phone(port, code, d1)
        assert st_ == 200 and devs[d1] == key1 and not answers, st_
        # 4 pairing tries from this address so far (each start is one guess): one more and pairing is shut out
        code = srv.open_pairing()
        assert post(port, "/pair/start", {"id": d2, "name": "x", "pub": "zz"})[0] == 400  # not even a number
        assert phone(port, "00000000", d2) == (429, None)  # a wrong guess: the 5th try - shut out at once
        assert post(port, "/pair/start", {"id": d2, "name": "x", "pub": "05"})[0] == 429
        # a paired phone's signed requests
        st_, _, out = remote_call(port, key1, d1, "state")
        assert st_ == 200 and out["ok"] is True and out["echo"] == "state" and abs(out["now"] - time.time()) < 5
        st_, _, out = remote_call(port, key1, d1, "vts.bg", {"id": "x"})
        assert st_ == 200 and out["ok"] is False and "VTube" in out["error"]  # its failure, signed and said
        st_, _, out = remote_call(port, key1, d1, "obs", {"cmd": "add_feed", "args": {}})
        assert st_ == 200 and out["ok"] is False and ran[-1][1] == "vts.bg"  # refused before running
        n_ran, nonce = len(ran), "ab" * 16
        assert remote_call(port, key1, d1, "deck", nonce=nonce)[0] == 200
        assert remote_call(port, key1, d1, "deck", nonce=nonce)[0] == 403  # the same request again: refused (1)
        assert remote_call(port, key1, d1, "deck", t=int(time.time()) - 400)[0] == 409  # too old
        st_, _, out = remote_call(port, key1, d1, "deck", t=srv.started - 1)  # signed before the server started
        assert st_ == 409 and abs(out["now"] - time.time()) < 5  # the PC's time, signed
        assert remote_call(port, "00" * 32, d2, "state")[0] == 401  # never paired (2)
        assert remote_call(port, "00" * 32, d1, "state")[0] == 401  # a wrong key (3)
        st_, _, text = remote_call(port, key1, d1, "state", body=b'{"cmd": "deck", "args": {}}',
                                   sig=peer_sign(key1, "POST", "/api", int(time.time()), "cd" * 16, "0" * 64),
                                   nonce="cd" * 16)
        assert st_ == 401 and "pair it again" in text  # the body isn't the one signed (4)
        assert len(ran) == n_ran + 1  # none of them ran
        del devs[d1]  # removed on the PC: refused at once (5)
        assert remote_call(port, key1, d1, "state")[0] == 401
        devs[d1] = key1  # 5 refused from this address: shut out for a minute, even when right
        st_, _, text = remote_call(port, key1, d1, "state")
        assert st_ == 429 and "Too many" in text, (st_, text)
        real = R.remote_ok  # outside the allowed addresses: nothing at all
        R.remote_ok = lambda ip: False
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/")
            assert c.getresponse().status == 403
            c.close()
            assert post(port, "/pair/start", {})[0] == 403
        finally:
            R.remote_ok = real
    finally:
        srv.stop()
    # a fresh server: the rate limit per phone; a code good for CODE_STARTS starts only, and only in its time
    devs.clear()
    srv = RemoteServer(["127.0.0.1"], 0, lambda: dict(devs), run, ask, "PC-test")
    try:
        devs[d1] = "cd" * 32
        import socket  # one address holding connections open: PER_IP at most, then dropped; others still served
        held = [socket.create_connection(("127.0.0.1", srv.port), timeout=5) for _ in range(srv.PER_IP)]
        extra = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        try:
            assert extra.recv(10) == b""
        except ConnectionError:
            pass
        extra.close()
        for c_ in held:
            c_.close()
        time.sleep(0.3)
        got = [remote_call(srv.port, devs[d1], d1, "deck")[2].get("busy") for _ in range(srv.RATE + 2)]
        assert not any(got[:srv.RATE]) and all(got[srv.RATE:]), got
        code = srv.open_pairing()
        for _ in range(srv.CODE_STARTS):  # someone guessing (each answer only tells them their one guess was wrong)
            x, pa = pair_offer("99999999", "A")
            assert post(srv.port, "/pair/start", {"id": d2, "name": "x", "pub": f"{pa:x}"})[0] == 200
        answers.append(True)
        assert phone(srv.port, code, d2) == (403, None) and d2 not in devs  # the right code, but its tries are gone
        answers.clear()
    finally:
        srv.stop()
    srv = RemoteServer(["127.0.0.1"], 0, lambda: dict(devs), run, ask, "PC-test")
    try:
        code = srv.open_pairing()
        srv.code = (code, time.time() - 1, 3)  # ran out
        answers.append(True)
        assert phone(srv.port, code, d2) == (403, None) and d2 not in devs
        answers.clear()
    finally:
        srv.stop()
    remote_update_selftest(devs, run, ask)
    # VTube Studio's API (a fake one): allowed once, then background hotkeys listed and triggered
    fake = FakeVts()
    try:
        token = vts_api(fake.port, None, timeout=5)[0]
        assert token == fake.token and fake.asked == 1
        got = vts_backgrounds(fake.port, token)
        assert got["model"] == "Wolf" and [b["name"] for b in got["backgrounds"]] == ["Stars", "Rain"], got
        vts_api(fake.port, token, [("HotkeyTriggerRequest", {"hotkeyID": got["backgrounds"][1]["id"]})])
        assert fake.triggered == [FakeVts.HOTKEYS[1]["hotkeyID"]]
        for bad in ("wrong", ""):
            try:
                vts_backgrounds(fake.port, bad)
                raise AssertionError("a wrong token was taken")
            except OSError as e:
                assert "allow it again" in str(e), e
        fake.allow = False
        try:
            vts_api(fake.port, None, timeout=5)
            raise AssertionError("denied, yet a token")
        except OSError as e:
            assert "denied" in str(e), e
    finally:
        fake.stop()
    try:
        vts_api(fake.port, "x", timeout=2)  # not running
        raise AssertionError("no VTube Studio, yet an answer")
    except OSError as e:
        assert "isn't running" in str(e) or "in time" in str(e), e
    print("phone remote ok")
