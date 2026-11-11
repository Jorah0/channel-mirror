# Channel Mirror: Setup and Operations Guide

This guide covers every part of Channel Mirror: what each piece is, how to install what it needs, and how to
run, test, build, package and release it. For a short user-facing summary, see [README.md](README.md).

**Contents**

1. [What's in the repo](#1-whats-in-the-repo)
2. [Prerequisites](#2-prerequisites)
3. [Running from source](#3-running-from-source)
4. [Running the self-test](#4-running-the-self-test)
5. [Building the executable](#5-building-the-executable)
6. [Installing and distributing the executable](#6-installing-and-distributing-the-executable)
7. [Windows integration (shortcuts, Send to, drag and drop)](#7-windows-integration)
8. [Using the app](#8-using-the-app)
9. [Settings file](#9-settings-file)
10. [How it works (component reference)](#10-how-it-works-component-reference)
11. [Releasing a new version](#11-releasing-a-new-version)
12. [Troubleshooting](#12-troubleshooting)
13. [Quick reference](#13-quick-reference)

---

## 1. What's in the repo

| File | What it is |
|------|------------|
| `channel_mirror.py` | The whole application: audio analysis, channel routing, length/split logic, the Tkinter GUI and the self-test. Kept as one file on purpose. |
| `build.ps1` | PowerShell script that packages the app into a single `dist\ChannelMirror.exe` using PyInstaller. |
| `icon.ico` | App icon (all sizes 16-256 px). Embedded in the exe and bundled inside it so the window title bar uses it too. |
| `icon.png` | The same symbol at 128 px, shown on the first-time setup screen. Bundled into the exe. |
| `README.md` | Short user guide. |
| `SETUP.md` | This document. |
| `.gitignore` | Ignores build output (`build/`, `dist/`, `*.spec`), Python caches and local AI-tooling files. |

Generated, not tracked:

| Path | Created by |
|------|------------|
| `build\`, `ChannelMirror.spec` | PyInstaller intermediate files (`.\build.ps1`) |
| `dist\ChannelMirror.exe` | The finished executable (`.\build.ps1`) |
| `%USERPROFILE%\.channel_mirror.json` | The app, when it saves your settings |
| `%LOCALAPPDATA%\ChannelMirror\ffmpeg\` | The first-time setup screen, when it installs ffmpeg |

External programs the app calls at runtime:

| Program | Used for |
|---------|----------|
| `ffprobe` | Reading each file's audio stream info (codec, channel count, layout, bitrate, sample rate) |
| `ffmpeg` | Decoding audio for analysis, and writing every output file |

---

## 2. Prerequisites

Which ones you need depends on how you run it:

| Need | Run from source | Build the exe | Run the built exe |
|------|:---:|:---:|:---:|
| Windows 10/11 | yes | yes | yes |
| Python 3.10+ (with Tkinter) | yes | yes | no |
| numpy | yes | yes (installed by `build.ps1`) | no |
| PyInstaller | no | yes (installed by `build.ps1`) | no |
| ffmpeg + ffprobe | yes | yes (for the self-test) | yes |

> The code itself is plain Python + Tkinter + numpy and should also run on macOS/Linux from source, but the
> build script, shortcuts and Send to steps below are Windows-only. Tested here with Python 3.14.5,
> numpy 2.4.6, ffmpeg 8.1.1.

### 2.1 Python

Install from [python.org](https://www.python.org/downloads/) or with winget:

```powershell
winget install Python.Python.3.13
```

In the python.org installer, tick **Add python.exe to PATH** and keep **tcl/tk and IDLE** selected (that's
Tkinter, which the GUI needs). Check it:

```powershell
python --version                      # 3.10 or newer
python -c "import tkinter; print('tk ok')"
```

### 2.2 numpy

```powershell
python -m pip install numpy
```

Optional: use a virtual environment so the project's packages stay separate:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # then run every python / build command in this shell
python -m pip install numpy
```

(`.venv` isn't in `.gitignore`; add it there if you use one.)

### 2.3 ffmpeg and ffprobe

Any of these options works. The app checks in this order: next to the exe, on PATH, then
`%LOCALAPPDATA%\ChannelMirror\ffmpeg`.

**Option 0: let the app install it (easiest)**

Just start the app. If ffmpeg isn't found, a **first-time setup** screen (with the app icon) appears instead of
the main window, offering **Install ffmpeg**. It then:

1. downloads the official Windows build ffmpeg.org links to
   (`https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip`, about 110 MB) with progress shown;
2. checks it against the SHA-256 checksum published beside it, and refuses a damaged download;
3. unpacks only `ffmpeg.exe` and `ffprobe.exe` into `%LOCALAPPDATA%\ChannelMirror\ffmpeg`;
4. opens the main window.

It only happens once: on later starts, ffmpeg is found there. No admin rights are needed. If the download fails
(no internet, firewall), the screen says so and offers **Try again**, or install it with one of the options below.
**Quit** closes the app without installing anything. This works both for the exe and when running from source.

**Option A: install system-wide**

```powershell
winget install Gyan.FFmpeg
```

Then **open a new terminal** (PATH only updates for new windows) and check:

```powershell
ffmpeg -version
ffprobe -version
```

**Option B: portable, next to the exe**

Download a Windows build (e.g. the "release essentials" zip from https://www.gyan.dev/ffmpeg/builds/), and copy
`bin\ffmpeg.exe` and `bin\ffprobe.exe` into the same folder as `ChannelMirror.exe`. The packaged exe adds its own
folder to the front of PATH at startup, so it finds them there. This only works for the exe, not when running
from source (from source, they must be on PATH).

---

## 3. Running from source

From the repo folder:

```powershell
pythonw channel_mirror.py             # opens the window, no console
python  channel_mirror.py             # same, but with a console that shows any Python errors
```

Use `python` (not `pythonw`) when something goes wrong: a crash then prints a traceback instead of vanishing.

Load files on startup by passing them as arguments (anything that doesn't start with `--` is treated as an
input file or folder):

```powershell
python channel_mirror.py "C:\music\song.mp3" "C:\music\album"
```

Folders are expanded to every audio/video file directly inside them (not subfolders).

### Command-line options

| Command | Does |
|---------|------|
| `python channel_mirror.py` | Open the GUI |
| `python channel_mirror.py <files/folders...>` | Open the GUI with those inputs loaded |
| `python channel_mirror.py --selftest` | Run the end-to-end self-test, print `selftest ok`, exit |

There's no headless batch mode; processing is done through the GUI.

---

## 4. Running the self-test

```powershell
python channel_mirror.py --selftest
```

Expected output: `selftest ok` (takes a few seconds). Any failure stops with an `AssertionError` showing what
was wrong. Run it before every build and every commit.

It needs ffmpeg/ffprobe on PATH. It works in a temporary folder that's deleted afterwards, so it never touches
your files. It generates its own test media and checks:

- **Folder scanning**: folders expand to media files only, sorted; plain files pass through.
- **Output folders**: default `Channel Mirror output` subfolder, and grouping by source folder under a chosen base.
- **Analysis and source picking**: the loudest channel is detected; manual L/R picks work.
- **Job planning**: output names, and merging duplicate combos (e.g. Auto and L on the same channel; all sources on mono).
- **Routing**: each target (left/right/both) gets the right signal, non-target channels are exactly silent, mono
  input works, and the source file is unchanged.
- **Video input**: every output type from an `.mp4`: video formats keep the picture, audio formats drop it, the
  routed audio is correct.
- **Unknown formats**: a file with an odd extension is still read, and output falls back to `.mkv`.
- **First-time ffmpeg install**: a fake zip + checksum (no network) unpacks the two exes, and a wrong checksum is
  refused without creating anything.
- **Length**: time parsing, exact cuts, looping past the end, and ending at a quiet gap.
- **Splitting**: cuts land in the middle of silences, part counts and lengths, and leading/trailing silence handling.

---

## 5. Building the executable

From the repo folder in PowerShell:

```powershell
python channel_mirror.py --selftest   # make sure it passes first
.\build.ps1
```

Result: `dist\ChannelMirror.exe`, a single file that runs without Python installed.

What `build.ps1` does:

1. `pip install pyinstaller numpy` (quietly; skipped if already installed).
2. Runs PyInstaller with:
   - `--onefile`: everything in one exe.
   - `--windowed`: no console window.
   - `--name ChannelMirror`: output file name.
   - `--icon icon.ico`: the exe's own icon in Explorer.
   - `--add-data "icon.ico;."`: bundles the icon so the running window can show it too.
   - `--add-data "icon.png;."`: bundles the picture shown on the first-time setup screen.
   - `--clean --noconfirm`: fresh build, overwrite the previous one.
3. Prints `Built: <path>\dist\ChannelMirror.exe` on success.

If PowerShell refuses to run the script ("running scripts is disabled on this system"), allow local scripts
for your user once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

or run it for this one time only:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Notes:

- The exe unpacks itself to a temp folder each time it starts, so the first launch takes a second or two.
- ffmpeg is **not** bundled (it would add ~200 MB). The exe offers to download it on first start, or finds it on
  PATH / next to the exe (see [2.3](#23-ffmpeg-and-ffprobe)).
- To change the icon: replace `icon.ico` (keep several sizes, up to 256 px) and regenerate the picture with
  `ffmpeg -y -i icon.ico -map 0:5 icon.png` (stream 5 = the 128 px frame), then rebuild.
- A freshly built, unsigned exe can trigger Windows SmartScreen ("Windows protected your PC"). Click
  **More info → Run anyway**. Some antivirus tools also flag PyInstaller onefile exes; rebuilding or adding an
  exception fixes it.

---

## 6. Installing and distributing the executable

`ChannelMirror.exe` is its own installer. It's one file with Python, numpy and the app inside, so the other PC
needs nothing else.

**On another computer:**

1. Download `ChannelMirror.exe` from the repo's **Releases** page (or copy `dist\ChannelMirror.exe` over).
2. Double-click it. Windows may show "Windows protected your PC" because the exe isn't code-signed. Click
   **More info > Run anyway**.
3. Click **Install**. It goes to `%LOCALAPPDATA%\Programs\ChannelMirror` (per user, no admin rights), with a
   Start menu entry, an optional desktop shortcut, an optional right-click **Send to > Channel Mirror**, and
   an entry in **Settings > Apps > Installed apps**. The installed copy then opens.
4. On a PC without ffmpeg, click **Install ffmpeg** on the next screen (see [2.3](#23-ffmpeg-and-ffprobe)).
   This happens only once.

- **Update:** run a newer `ChannelMirror.exe` the same way and click **Update**. Settings are kept.
- **Uninstall:** go to **Settings > Apps > Installed apps > Channel Mirror > Uninstall**. It asks whether to also
  delete your settings and the downloaded ffmpeg.
- **Just run it (portable):** click **Just run it** on the install screen (it won't ask again on that PC), or
  start it with `--portable`. A portable folder can carry its own ffmpeg:

```text
ChannelMirror  ChannelMirror.exe
  ffmpeg.exe
  ffprobe.exe
```

**Scripted / silent:**

```powershell
.\ChannelMirror.exe --install                  # install with every shortcut, no questions
& "$env:LOCALAPPDATA\Programs\ChannelMirror\ChannelMirror.exe" --uninstall --quiet
```

---

## 7. Windows integration

All of these are one-time PowerShell commands, run **from the repo folder**.

### 7.1 Desktop shortcut to the exe

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Channel Mirror.lnk")
$s.TargetPath = "$PWD\dist\ChannelMirror.exe"; $s.Save()
```

### 7.2 Desktop shortcut that runs from source

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Channel Mirror.lnk")
$s.TargetPath = (Get-Command pythonw).Source; $s.Arguments = "`"$PWD\channel_mirror.py`""; $s.WorkingDirectory = "$PWD"; $s.Save()
```

### 7.3 Right-click → Send to

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\SendTo\Channel Mirror.lnk")
$s.TargetPath = "$PWD\dist\ChannelMirror.exe"; $s.Save()
```

Then in Explorer: select files/folders → right-click → **Send to → Channel Mirror** (on Windows 11, it's under
**Show more options**). To remove it, delete `Channel Mirror.lnk` from `%APPDATA%\Microsoft\Windows\SendTo`.

### 7.4 Drag and drop

Drop files or folders onto `ChannelMirror.exe` or any shortcut to it. The app opens with them loaded. This is
the same mechanism as Send to: Windows passes the paths as command-line arguments.

If you move the exe after making shortcuts, re-run the shortcut commands (shortcuts store absolute paths).

---

## 8. Using the app

The window has four sections, top to bottom.

### 8.1 Input files

- **Add files...**: pick files. The picker filters to known audio/video extensions; choose **All files** to pick
  anything else (any file ffmpeg can find an audio track in works).
- **Add folder...**: adds every audio/video file directly in that folder.
- **Remove selected** / **Clear all**: edit the list (Shift/Ctrl-click to select several).

Each file is analyzed when added. Its row shows per-channel loudness (RMS in dB), which channel is loudest, and
the files it will produce. Files with no audio, or that ffmpeg can't decode, are skipped and listed in one
error dialog. Adding the same file twice is ignored.

Channel names: mono shows `M`, stereo `L`/`R`, more channels `ch1`, `ch2`, ...

### 8.2 Settings

**Source channel** (tick any): which input channel to copy.

- `Auto (loudest)`: the channel with the highest RMS, per file.
- `L`, `R`: that channel. On a mono file, both mean its only channel.
- `All` ticks the whole row.

**Output to** (tick any): where the copied channel goes in the output.

- `Both`: on every output channel.
- `Left` / `Right`: only that side; the other side is silent.

Every channel that isn't a target is completely silent. Mono and stereo inputs produce stereo outputs;
inputs with more channels keep their channel count and layout.

**Output type** (dropdown):

| Choice | Result |
|--------|--------|
| Same as input (videos keep video) | Same format as the input. Video is copied untouched. |
| Audio only (match source codec) | Audio inputs keep their format. Videos: audio saved as `.m4a`/`.mp3`/`.opus`/`.ogg`/`.flac`/`.ac3`/`.eac3`/`.wav` to match the codec, else `.mka`. |
| WAV, MP3, FLAC, M4A (AAC), OGG (Vorbis), OPUS, AIFF | Audio only, in that format. |
| MP4, MKV, MOV (video + audio) | Keeps the video (copied if the container allows, else re-encoded). |

If a format can't hold the result (e.g. 6 channels into MP3), that file is written as `.flac` (audio) or `.mkv`
(video) instead. Encoder quality for re-encoded audio: MP3 VBR `-q:a 2`, OGG `-q:a 6`, OPUS 160k, AAC 192k.
When the format allows it, the source codec and bitrate are kept.

**Length** (seconds like `30` / `12.5`, or `m:ss` / `h:mm:ss`): cut each output to this length with a 20 ms
fade-out so it never clicks. Blank = full length. Longer than the file = whole file.

- **Loop to fill length**: repeat the input until it reaches the length.
- **End at a quiet spot**: end up to 3 s early (never more than half the length) in the middle of the quietest
  stretch, so it doesn't stop mid-sound.

**Split each file into parts**: write several files (`_part01`, `_part02`, ...) instead of one.

| Length | Parts | Result |
|--------|-------|--------|
| set | blank | parts of about that length through the whole file |
| set | N | only the first N parts of that length |
| blank | N | N roughly equal parts |

When splitting, cuts are always at silences (the quiet-spot box is forced on and Loop is disabled): each cut
sits in the middle of the last quiet stretch before the length, so parts run about that long, usually a little
shorter. If the file starts or ends with silence, the first part starts and the last part ends in the middle of
it. Each part fades in and out over 20 ms.

### 8.3 Output folder

- **Blank**: each output goes into a `Channel Mirror output` folder inside its input's folder.
  `C:\music\album\song.mp3` → `C:\music\album\Channel Mirror output\song_left.mp3`
- **Set** (type a path or **Browse...**): one subfolder per source folder.
  `<output>\album\song_left.mp3`

The folder is created if it doesn't exist.

### 8.4 Run

Writes one file per input × source × target (× part). If any outputs already exist, it asks:
**Yes** = overwrite, **No** = skip those, **Cancel** = stop. The status bar shows progress; a dialog reports
the result and any failures.

**Output names**

| Situation | Name |
|-----------|------|
| One source ticked | `song_left.mp3`, `song_right.mp3`, `song_both.mp3` |
| Several sources ticked | `song_fromL_left.mp3`, `song_fromR_both.mp3`, ... |
| Splitting | `song_left_part01.mp3`, `song_left_part02.mp3`, ... |
| Name clash in the same run | `_2`, `_3`, ... appended |

Originals are never modified: an output that would have the same path as its input gets renamed.

The window freezes briefly while working (processing runs on the UI thread). That's expected; let it finish.

---

## 9. Settings file

Settings are saved to `%USERPROFILE%\.channel_mirror.json` when you click **Run** and when you close the
window, and loaded at startup. Example:

```json
{
  "sources": ["Auto (loudest)"],
  "targets": ["both"],
  "out_dir": "",
  "output_type": "same",
  "length": "",
  "loop": false,
  "quiet": false,
  "split": false,
  "parts": ""
}
```

| Key | Meaning |
|-----|---------|
| `sources` | Ticked source channels: `"Auto (loudest)"`, `"L"`, `"R"` |
| `targets` | Ticked outputs: `"both"`, `"left"`, `"right"` |
| `out_dir` | Output folder; empty = beside the inputs |
| `output_type` | `same`, `audio`, `wav`, `mp3`, `flac`, `m4a`, `ogg`, `opus`, `aiff`, `mp4`, `mkv`, `mov` |
| `length` | Length text as typed |
| `loop`, `quiet`, `split` | Checkbox states |
| `parts` | Parts text as typed |

To reset to defaults, delete the file. A broken file is ignored (defaults are used), and a failure to save
never blocks you.

---

## 10. How it works (component reference)

Everything is in `channel_mirror.py`. The flow for one run:

```text
add files ─► media_files ─► analyze (probe + RMS) ─► list row
                                              │
Run ─► plan_jobs ─► split_points / clip_seconds ─► out_folder + names ─► route (ffmpeg) ─► output files
```

### 10.1 Constants

| Name | Purpose |
|------|---------|
| `SOURCES`, `TARGETS` | The checkbox options |
| `AUDIO_EXT`, `VIDEO_EXT` | Extensions for the file picker and folder scans. Inputs with other extensions are still accepted and treated as video-capable. |
| `OUTPUT_TYPES` | Dropdown label → mode |
| `VIDEO_OUT` | Modes that keep video (`mp4`, `mkv`, `mov`) |
| `ENCODER_OPTS` | Quality settings per output format |
| `AUDIO_ONLY_EXT` | Codec → extension for "Audio only" from a video |
| `SETTINGS` | Path of the settings file |
| `QUIET_WINDOW` (3 s) | How far before the requested end to look for a quiet spot |
| `FADE` (20 ms) | Fade length at every cut |
| `SILENCE` (-50 dBFS) | A 20 ms block below this counts as silence |
| `OUT_SUBDIR` | `"Channel Mirror output"` |
| `NO_WINDOW` | Stops ffmpeg flashing a console window from the windowed app |

| `FFMPEG_DIR` | `%LOCALAPPDATA%\ChannelMirror\ffmpeg`, where first-time setup puts ffmpeg; always appended to PATH |
| `FFMPEG_ZIP` | Download URL of the ffmpeg build (its checksum is at the same URL + `.sha256`) |
| `BUNDLE` | Folder holding `icon.ico` / `icon.png`: the unpacked exe bundle, or the script's folder |

When frozen (running as the exe), the exe's folder is prepended to PATH so a portable ffmpeg beside it is found.

### 10.1a First-time setup

- **`download_ffmpeg(progress, url, dest)`**: fetches the checksum, streams the zip to a temp file while hashing
  it, rejects it on a mismatch, then extracts only `bin/ffmpeg.exe` and `bin/ffprobe.exe` into `dest` (each is
  written as `.part` first, then renamed, so a crash never leaves a broken exe).
- **`first_run_setup(root)`**: the welcome screen shown inside the main window when ffmpeg is missing: icon,
  explanation, **Install ffmpeg** / **Quit**, live progress, and **Try again** on failure. Returns `True` once
  ffmpeg is usable; `gui()` then builds the normal window in the same place.

### 10.2 Analysis

- **`probe(path)`**: runs ffprobe on the first audio stream; returns codec, channels, layout, bitrate, sample
  rate. Raises if there is no readable audio.
- **`analyze(path)`**: decodes the first audio stream to 32-bit float through a pipe, in chunks (so huge files use
  little memory), and returns the probe info plus duration, per-channel RMS and per-channel peak.
- **`db(x)`**: amplitude → dB for display.
- **`labels(n)`**: channel names (`M`; `L`,`R`; `ch1`...).

### 10.3 Planning

- **`pick_source(rms, choice)`**: Auto → loudest channel; `L`/`R` → index 0/1 (clamped for mono).
- **`plan_jobs(src, rms, sources, targets, ext)`**: every source × target combination as
  `(channel, target, output name)`, merging combinations that resolve to the same channel.
- **`out_ext(src, info, mode)`**: output extension for the chosen output type.
- **`out_name(...)`**, **`out_folder(src, base)`**: output file name and folder (see [8.3](#83-output-folder)).
- **`media_files(paths)`**: expands folders into their media files.

### 10.4 Length and splitting

- **`parse_time(text)`**: `"90"`, `"1:30"`, `"1:02:03.5"` → seconds; blank → `None`; zero/negative or junk → error.
- **`levels(src, info, ch, at, secs, loop)`**: RMS of one channel in ~20 ms blocks over a time window (wrapping
  past the end of the file when looping).
- **`clip_seconds(...)`**: how many seconds to write. Without quiet mode it's the requested length; with it,
  it finds the last quiet stretch (silence, or within ~3.5 dB of the quietest moment) in the window before the
  requested end, and returns the middle of that stretch.
- **`edges(src, info, ch)`**: where the file's content really starts/ends: the middle of any leading/trailing silence.
- **`split_points(src, info, ch, length, count)`**: the list of `(start, seconds)` parts, each cut chosen with
  `clip_seconds(quiet=True)`. Equal-parts mode aims each cut at k/N of the file so errors don't pile onto the last part.

### 10.5 Writing

- **`route(src, dst, info, ch, target, mode, seconds, loop, start)`**: builds one ffmpeg command:
  - a `pan` filter that puts input channel `ch` on the target output channel(s) and leaves the rest silent;
  - `-ss` + fade-in for a part's start, `-t` + fade-out for its length, `-stream_loop -1` for looping;
  - stream mapping: audio only, or video copied, or video re-encoded;
  - codec: the source codec + bitrate first where the container may hold it, then ffmpeg's default encoder for
    that extension.

  It tries those combinations in order. If none works, it deletes any partial file and retries as `.flac`
  (audio) or `.mkv` (video). If that also fails, it raises with ffmpeg's error message.

  Known limit: copied video can only start/stop on a keyframe, so a split video part's picture may run a moment
  longer than its audio.

### 10.6 GUI

- **`gui()`**: the Tkinter window. Checks for ffmpeg/ffprobe, loads settings, enables DPI awareness for sharp
  text, builds the four sections, keeps the file list's preview rows up to date as settings change, loads any
  command-line paths, and saves settings on close.
- Inner functions: `load` (analyze files), `refresh` (redraw rows/status), `run` (validate inputs, plan jobs,
  ask about existing files, write everything), `on_split` (enable/disable related controls when Split is toggled).

### 10.7 Self-test

- **`selftest()`**: see [section 4](#4-running-the-self-test).

---

## 11. Releasing a new version

Needs the [GitHub CLI](https://cli.github.com/) (`winget install GitHub.cli`, then `gh auth login` once).

```powershell
python channel_mirror.py --selftest          # must print: selftest ok
.\build.ps1                                  # -> dist\ChannelMirror.exe
.\dist\ChannelMirror.exe                     # quick manual check: it opens, a file loads and runs
git status                                   # everything committed?
git push
gh release create v1.2 dist\ChannelMirror.exe --title "v1.2" --notes "What changed..."
```

Use the next version number (`gh release list` shows the existing ones). The exe is attached to the release
and appears on the repo's Releases page.

Development conventions:

- Keep all logic in `channel_mirror.py`; dependencies are stdlib + numpy only.
- Run the self-test before every build and commit.
- When you change behaviour, add an assertion for it to `selftest()`.

---

## 12. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| First-time setup screen appears | ffmpeg wasn't found. Click **Install ffmpeg**, or install it yourself (section 2.3). |
| Setup says "Couldn't install ffmpeg" | No internet / blocked by a firewall or proxy, or the download was damaged. Click **Try again**, or use `winget install Gyan.FFmpeg` and open a new terminal / sign out and in, or put `ffmpeg.exe` + `ffprobe.exe` next to the exe. |
| Want to re-run first-time setup | Delete `%LOCALAPPDATA%\ChannelMirror\ffmpeg` (and make sure no other ffmpeg is on PATH). |
| `ModuleNotFoundError: No module named 'numpy'` | `python -m pip install numpy` (into the same Python / venv you run with). |
| `No module named 'tkinter'` / `_tkinter` | Re-run the Python installer → Modify → tick **tcl/tk and IDLE**. |
| `pythonw` does nothing / window closes instantly | Run `python channel_mirror.py` instead to see the error in the console. |
| `.\build.ps1 cannot be loaded ... running scripts is disabled` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or `powershell -ExecutionPolicy Bypass -File .\build.ps1`. |
| `python` opens the Microsoft Store | Windows' app alias. Install real Python, or turn off the alias under Settings → Apps → Advanced app settings → App execution aliases. |
| SmartScreen / antivirus warning on the exe | Unsigned PyInstaller exe. **More info → Run anyway**, or add an exception. |
| A file is "skipped" when added | It has no audio track, or ffmpeg can't decode it. Try `ffprobe "<file>"` to see what's in it. |
| Output came out as `.flac` or `.mkv` | The chosen format couldn't hold the result (e.g. too many channels for MP3); this fallback is deliberate. |
| Output is a little shorter than Length | "End at a quiet spot" or splitting is on: it ends at the nearest quiet spot up to 3 s early. Untick it for exact length (not available when splitting). |
| Split video part's picture starts/ends a moment off | Copied video can only cut on keyframes. Pick an audio output type, or accept the small offset. |
| Window says "Not responding" during a big batch | Work runs on the UI thread; wait for it to finish. |
| Settings look wrong / want defaults back | Delete `%USERPROFILE%\.channel_mirror.json`. |
| Send to / shortcut stopped working | The exe moved. Re-run the commands in [section 7](#7-windows-integration). |
| Self-test fails | Read the assertion message. Check `ffmpeg -version` works first; very old ffmpeg builds may lack filters/encoders it uses. |

---

## 13. Quick reference

```powershell
# one-time setup
winget install Python.Python.3.13
winget install Gyan.FFmpeg
python -m pip install numpy

# run
pythonw channel_mirror.py                     # GUI
python  channel_mirror.py --selftest          # test -> "selftest ok"

# build + release
.\build.ps1                                   # -> dist\ChannelMirror.exe
gh release create vX.Y dist\ChannelMirror.exe
```
