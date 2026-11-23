"""The Transcribe tab in the main window, end to end with real speech: a known English sentence spoken by Windows'
own text-to-speech (to a WAV file - nothing plays out loud) is put in a short video with long silences around it,
then transcribed through the tab's own buttons with the smallest model (tiny.en: downloaded once, after the tab asks,
into the app's shared model folder, and kept for later runs). The Word, PDF, subtitle and text documents must hold the
sentence's words at sensible times and nothing in the silence; then on the processor instead of the graphics card, with
voice detection, Cancel half-way through a long recording, a folder of several files (in name order), a video with no
sound (failed, and says why), a wrong language for an English-only model, and the settings kept on close. Everything
it writes goes to temp folders."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

os.environ.setdefault("CM_TEST_TIMEOUT", "1100")  # the harness watchdog: a long, bounded limit (run_all sets its own)
from harness import App, walk  # noqa: E402

from tkinter import ttk  # noqa: E402

SENTENCE = "The quick brown fox jumps over the lazy dog. Channel Mirror turns spoken words into a written document."
WORDS = ("quick", "brown", "jumps", "over", "lazy", "dog", "spoken", "words", "written", "document")
work = Path(tempfile.mkdtemp(prefix="cm_tr_"))
media, out = work / "media", work / "out"
media.mkdir()


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True, capture_output=True, timeout=300)


speech = work / "speech.wav"  # Windows' built-in voice, straight into a file
subprocess.run(["powershell", "-NoProfile", "-Command",
                "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.SetOutputToWaveFile('{speech}'); $s.Speak('{SENTENCE}'); $s.Dispose()"],
               check=True, capture_output=True, timeout=120)
said = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", speech],
                            capture_output=True, text=True).stdout)
LEAD, TAIL = 4.0, 45.0  # silence before and after it (whisper must not "hear" anything there)
clip = media / "Speech clip.mp4"
ff("-f", "lavfi", "-i", "color=c=navy:s=320x240:r=10", "-i", speech, "-filter_complex",
   f"[1:a]adelay={int(LEAD * 1000)}:all=1,apad=pad_dur={TAIL}[a]", "-map", "0:v", "-map", "[a]",
   "-t", LEAD + said + TAIL, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", clip)
mute = media / "No sound.mp4"
ff("-f", "lavfi", "-i", "color=c=red:s=160x120:r=10:d=3", "-c:v", "libx264", "-preset", "ultrafast", mute)
long_ = work / "Long talk.m4a"  # 40 minutes of the sentence over and over: Cancel comes long before the end
ff("-stream_loop", "-1", "-i", speech, "-t", 2400, "-c:a", "aac", "-b:a", "48k", long_)
folder = work / "Several"
folder.mkdir()
for name in ("b 10.mp3", "b 2.mp4", "a 1.wav"):
    if name.endswith(".mp4"):
        ff("-f", "lavfi", "-i", "color=s=160x120:r=5", "-i", speech, "-map", "0:v", "-map", "1:a", "-shortest",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", folder / name)
    else:
        ff("-i", speech, folder / name)
(folder / "notes.txt").write_text("not a recording")

keep = {}
app = App({"transcribe": {"folder": str(out)}})
cm = app.cm
real_tab = cm.transcribe_tab


def keep_tab(*a, **k):  # the tab's own handles (its list and state), to read back what it shows
    keep["api"] = real_tab(*a, **k)
    return keep["api"]


cm.transcribe_tab = keep_tab
app.start()
page = app.tab("Transcribe")
api = keep["api"]
v, tv, items = api["vars"], api["list"], api["items"]
model_was_here = cm.model_ready("tiny.en")


def combo(var, value):
    cb = next(c for c in walk(page) if isinstance(c, ttk.Combobox) and str(c.cget("textvariable")) == str(var))
    assert value in cb.cget("values"), (value, cb.cget("values"))
    cb.set(value)
    cb.event_generate("<<ComboboxSelected>>")
    app.pump(0.1)


def check(text, on):
    cb = next(c for c in walk(page) if isinstance(c, ttk.Checkbutton) and str(c.cget("text")).startswith(text))
    if cb.instate(["selected"]) != on:
        cb.invoke()
    app.pump(0.05)


def status_text():
    return next(str(lb.cget("text")) for lb in walk(page) if isinstance(lb, ttk.Label)
                and str(lb.cget("style")) == "Status.TLabel")


def rows():
    return [(tv.set(i, "file"), tv.set(i, "status"), tv.set(i, "result")) for i in tv.get_children()]


def run(secs=600):
    """Start, and wait (bounded) until the tab says it's finished."""
    app.button("Start", page).invoke()
    assert app.wait(lambda: not api["state"]["busy"], secs), (rows(), status_text())
    app.pump(0.2)


def words_in(text):
    got = set(re.findall(r"[a-z]+", text.lower()))
    return [w for w in WORDS if w in got]


try:
    combo(v["model"], "tiny.en")
    assert v["lang"].get() == "Auto-detect" and v["gpu"].get() and not v["vad"].get()  # graphics card on by default
    for k in ("docx", "pdf", "srt", "txt"):
        assert v[k].get(), k

    # A) one video: the model is asked for (once), then the four documents, named after the video
    app.picks.append([clip])
    app.button("Add files...", page).invoke()
    assert [r[:2] for r in rows()] == [("Speech clip.mp4", "waiting")], rows()
    t0 = time.time()
    run()
    took = time.time() - t0
    asked = [a for a in app.asked if a[1] == "Download speech model"]
    assert len(asked) == (0 if model_was_here else 1) and cm.model_ready("tiny.en"), app.asked
    if asked:
        assert "77.7 MB" in asked[0][2] and "tiny.en" in asked[0][2], asked[0]
    assert rows()[0][1].startswith("done (") and "on the processor" not in rows()[0][1], rows()
    docs = {k: out / f"Speech clip transcript{e}" for k, e in cm.DOC_FORMATS.items()}
    assert rows()[0][2] == ", ".join(p.name for p in docs.values()), rows()
    txt = docs["txt"].read_text(encoding="utf-8")
    srt = cm.srt_parse(docs["srt"].read_text(encoding="utf-8"))
    with zipfile.ZipFile(docs["docx"]) as z:
        assert z.testzip() is None
        word = re.sub(r"<[^>]+>", " ", z.read("word/document.xml").decode())
    from cmlib.selftest import pdf_text
    pdf = "\n".join(pdf_text(docs["pdf"].read_bytes()))
    print("recognised:", " / ".join(t for _, _, t in srt))
    print("timestamps:", [(round(a, 2), round(b, 2)) for a, b, _ in srt], f"(speech at {LEAD:.1f}-{LEAD + said:.1f} s)")
    for name, text in (("txt", txt), ("srt", " ".join(t for _, _, t in srt)), ("docx", word), ("pdf", pdf)):
        assert len(words_in(text)) >= 8, (name, words_in(text), text[:300])
    assert txt.startswith("Speech clip\n\n[00:00:0") and "Speech clip" in pdf and "Speech clip" in word
    assert srt and all(a <= b for a, b, _ in srt) and all(srt[i][0] <= srt[i + 1][0] for i in range(len(srt) - 1))
    assert 0 <= srt[0][0] <= LEAD + 1 and LEAD + said - 2 <= srt[-1][1] <= LEAD + said + 3, srt  # at the speech
    assert not [s for s in srt if s[0] > LEAD + said + 2], srt  # and nothing "heard" in the silence after it
    assert re.search(r"\[00:00:0\d\]", pdf) and "Page 1 of 1" in pdf
    print(f"one video ok: {LEAD + said + TAIL:.0f} s of video in {took:.1f} s (graphics card, tiny.en)")

    # Open result: the document (recorded by the harness, not opened)
    tv.selection_set(tv.get_children()[0])
    app.button("Open result", page).invoke()
    assert app.launched[-1] == str(docs["docx"]), app.launched
    app.button("Open folder", page).invoke()
    assert app.launched[-1] == str(out), app.launched

    # B) the same on the processor (graphics card off), with only the subtitles and text ticked
    for f in docs.values():
        f.unlink()
    app.button("Clear", page).invoke()
    check("Use the graphics card", False)
    check("Word", False)
    check("PDF", False)
    assert not v["gpu"].get() and not v["docx"].get() and not v["pdf"].get()
    app.picks.append([clip])
    app.button("Add files...", page).invoke()
    t0 = time.time()
    run()
    assert rows()[0][1].startswith("done (") and docs["srt"].exists() and docs["txt"].exists(), rows()
    assert not docs["docx"].exists() and not docs["pdf"].exists()
    assert len(words_in(docs["txt"].read_text(encoding="utf-8"))) >= 8
    print(f"processor ok: {time.time() - t0:.1f} s")

    # C) voice detection (its small model is fetched the first time it's ticked, after asking)
    app.button("Clear", page).invoke()
    check("Use the graphics card", True)
    check("Voice detection", True)
    app.picks.append([clip])
    app.button("Add files...", page).invoke()
    t0 = time.time()
    run()
    assert v["gpu"].get() and v["vad"].get() and not v["docx"].get()
    assert rows()[0][1].startswith("done (") and cm.model_ready(cm.VAD_MODEL, cm.VAD_MODELS), rows()
    vad_srt = cm.srt_parse(docs["srt"].read_text(encoding="utf-8"))
    assert len(words_in(" ".join(t for _, _, t in vad_srt))) >= 6, vad_srt
    assert not [s for s in vad_srt if s[0] > LEAD + said + 2], vad_srt
    print(f"voice detection ok: {time.time() - t0:.1f} s:", " / ".join(t for _, _, t in vad_srt))
    check("Voice detection", False)

    # D) Cancel half-way through a 40-minute recording: ffmpeg stopped at once, no documents, the rest still waits
    app.button("Clear", page).invoke()
    app.picks += [[long_], [clip]]
    app.button("Add files...", page).invoke()
    app.button("Add files...", page).invoke()
    app.button("Start", page).invoke()
    assert app.wait(lambda: re.fullmatch(r"transcribing ([1-9]\d?)%", rows()[0][1]), 300), rows()
    pct = rows()[0][1]
    t0 = time.time()
    app.button("Cancel", page).invoke()
    assert app.wait(lambda: not api["state"]["busy"], 15), rows()
    app.pump(0.3)
    assert time.time() - t0 < 5, time.time() - t0
    assert rows()[0][1] == "cancelled" and rows()[1][1] == "waiting" and status_text().startswith("Cancelled"), rows()
    assert not list(out.glob("Long talk*")) and not list(out.glob("*.part")), list(out.iterdir())
    print(f"cancel ok at {pct}: stopped in {time.time() - t0:.1f} s")

    # E) a folder: every recording in it, in name order (other files left out), each with its documents
    app.button("Clear", page).invoke()
    app.picks.append(folder)
    app.button("Add folder...", page).invoke()
    assert [r[0] for r in rows()] == ["a 1.wav", "b 2.mp4", "b 10.mp3"], rows()
    app.picks.append(folder)
    app.button("Add folder...", page).invoke()  # added again: not twice
    assert len(rows()) == 3
    run()
    assert all(r[1].startswith("done (") for r in rows()), rows()
    for stem in ("a 1", "b 2", "b 10"):
        t = (out / f"{stem} transcript.txt").read_text(encoding="utf-8")
        assert t.startswith(stem + "\n") and len(words_in(t)) >= 8, (stem, t)
    assert status_text().startswith("Finished") and "3 done" in status_text(), status_text()
    print("folder ok:", status_text())

    # F) a video with no sound: failed, and the tab says why; the next file still runs
    app.button("Clear", page).invoke()
    app.picks += [[mute], [folder / "a 1.wav"]]
    app.button("Add files...", page).invoke()
    app.button("Add files...", page).invoke()
    run()
    assert rows()[0][1] == "failed: no audio in it" and "No readable audio" in rows()[0][2], rows()
    assert rows()[1][1].startswith("done ("), rows()
    assert "1 done, 1 failed" in status_text() and not list(out.glob("No sound*")), status_text()
    print("no sound ok:", rows()[0][1], "-", rows()[0][2])

    # G) an English-only model with another language: refused, plainly, before anything runs
    app.button("Clear", page).invoke()
    app.picks.append([clip])
    app.button("Add files...", page).invoke()
    combo(v["lang"], "French")
    n = len(app.boxes)
    app.button("Start", page).invoke()
    app.pump(0.2)
    assert app.boxes[n:] and "only understands English" in app.boxes[n][2] and not api["state"]["busy"], app.boxes
    assert rows()[0][1] == "waiting"
    combo(v["lang"], "Auto-detect")
    print("English-only model + French refused ok")
finally:
    saved = app.close()
    shutil.rmtree(work, ignore_errors=True)
tc = saved.get("transcribe", {})
assert tc.get("model") == "tiny.en" and tc.get("folder") == str(out) and tc.get("gpu") is True, tc
assert tc.get("formats") == ["srt", "txt"] and tc.get("vad") is False and tc.get("lang") == "Auto-detect", tc
print("settings kept ok")
print("drive transcribe ok")
sys.exit(0)
