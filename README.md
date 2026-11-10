# Channel Mirror

Small desktop tool that analyzes the channels of audio or video files and writes new files with a chosen
source channel routed to Left, Right, or Both. Channels that aren't targets are fully silent.
Originals are never modified.

Full setup, build, release and troubleshooting guide: [SETUP.md](SETUP.md).

## Requirements

- Python 3.10+ with `numpy` (`pip install numpy`)
- [ffmpeg](https://ffmpeg.org/) (`ffmpeg` and `ffprobe` on PATH), e.g. `winget install Gyan.FFmpeg`

## Executable (easiest)

```powershell
.\build.ps1        # -> dist\ChannelMirror.exe (single file, no Python needed to run it)
```

Double-click `dist\ChannelMirror.exe`, or copy it anywhere (Desktop, another PC). It needs ffmpeg: on first
start without it, a setup screen offers **Install ffmpeg** (downloads the official Windows build, ~110 MB,
checksum-verified, into `%LOCALAPPDATA%\ChannelMirror\ffmpeg`; only once). Or install ffmpeg on PATH yourself,
or put `ffmpeg.exe` + `ffprobe.exe` in the same folder as the exe. Prebuilt exe: see the repo's **Releases** page.

**Drag and drop**: drop files or folders onto `ChannelMirror.exe` (or its shortcut) to open with them loaded.
To add it to right-click **Send to** (run once, from this folder in PowerShell):

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\SendTo\Channel Mirror.lnk")
$s.TargetPath = "$PWD\dist\ChannelMirror.exe"; $s.Save()
```

## Use from source

```text
pythonw channel_mirror.py            # open the desktop window (no console)
python channel_mirror.py --selftest  # end-to-end check
```

Desktop shortcut (Windows, run once from this folder in PowerShell):

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Channel Mirror.lnk")
$s.TargetPath = (Get-Command pythonw).Source; $s.Arguments = "`"$PWD\channel_mirror.py`""; $s.WorkingDirectory = "$PWD"; $s.Save()
```

1. **Input files**: **Add files...** or **Add folder...** (every audio/video file in that folder). Any file
   with an audio track works: common and less common audio (wav, mp3, flac, m4a, ogg, opus, wma, ape, wv, aiff,
   ac3, dts, amr, caf...) and video (mp4, mkv, mov, avi, webm, wmv, flv, mpg, ts, m2ts, 3gp, vob...). Anything
   else: pick **All files** in the file picker, or drag it onto the exe. Files with no audio are skipped with a message.
   Each row shows per-channel loudness (RMS dB) and the files it will produce. **Remove selected** / **Clear all** to edit the list.
2. **Settings**: tick **Source channel** `Auto (loudest)`, `L`, `R` and **Output to** `Both`, `Left`, `Right` (`All` ticks a whole row).
   **Output type** (dropdown):
   - `Same as input`: same format; videos keep their video, copied untouched.
   - `Audio only (match source codec)`: a video's audio is saved as `.m4a` / `.mp3` / `.opus` / `.ogg` / `.flac` / `.wav` to match its codec, else `.mka`.
   - `WAV`, `MP3`, `FLAC`, `M4A`, `OGG`, `OPUS`, `AIFF`: audio only, in that format.
   - `MP4`, `MKV`, `MOV`: video + audio (video copied when the container allows it, else re-encoded).
   If a format can't hold the result (e.g. 6 channels into MP3), that file is written as `.flac` (audio) or `.mkv` (video) instead.

   **Length** (optional, seconds or `m:ss`): cut every output to exactly this long, with a 20 ms fade so it never clicks.
   Blank = full length. Longer than the file = whole file, unless **Loop to fill length** is ticked, which repeats
   the input until it reaches the length. **End at a quiet spot** ends up to 3 s earlier (never more than half the
   length), at the quietest moment, so it doesn't stop mid-sound.

   **Split each file into parts** writes several files (`..._part01`, `..._part02`, ...) instead of one:
   - Length only: parts of that length through the whole file (the last part is whatever is left).
   - Length + **Parts**: only the first N parts of that length.
   - Parts only: N roughly equal parts.

   Parts are only ever cut at silence (or the quietest stretch, if there's no true silence): each cut sits in the
   middle of the last quiet stretch before the length you set, so parts run about that long (usually a little
   shorter) and never stop mid-word. Every part starts and ends in the middle of a silence. If the file itself
   starts or ends with silence, the first part starts and the last part ends in the middle of it. Splitting never loops.
3. **Output folder**: outputs are grouped by the folder each input came from.
   Blank: written to a `Channel Mirror output` folder inside each input's folder
   (`C:\music\album\song.mp3` -> `C:\music\album\Channel Mirror output\song_left.mp3`).
   Set (type or **Browse...**): one subfolder per source folder (`<output>\album\song_left.mp3`).
4. **Run**. One file is written per input × source × output. Settings and output folder are remembered.

Output names: `song_left.mp3`, `song_right.mp3`, `song_both.mp3`. When several sources are ticked
the source is added: `song_fromR_left.mp3`. The source format and bitrate are kept where possible.
