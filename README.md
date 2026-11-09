# Channel Mirror

Small desktop tool that analyzes the channels of audio or video files and writes new files with a chosen
source channel routed to Left, Right, or Both. Channels that aren't targets are fully silent.
Originals are never modified.

## Requirements

- Python 3.10+ with `numpy` (`pip install numpy`)
- [ffmpeg](https://ffmpeg.org/) (`ffmpeg` and `ffprobe` on PATH), e.g. `winget install Gyan.FFmpeg`

## Use

```text
pythonw channel_mirror.py            # open the desktop window (no console)
python channel_mirror.py --selftest  # end-to-end check
```

Desktop shortcut (Windows, run once from this folder in PowerShell):

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Channel Mirror.lnk")
$s.TargetPath = (Get-Command pythonw).Source; $s.Arguments = "`"$PWD\channel_mirror.py`""; $s.WorkingDirectory = "$PWD"; $s.Save()
```

1. **Input files**: **Add files...** or **Add folder...** (every audio file in that folder). Each row shows
   per-channel loudness (RMS dB) and the files it will produce. **Remove selected** / **Clear all** to edit the list.
2. **Settings**: tick **Source channel** `Auto (loudest)`, `L`, `R` and **Output to** `Both`, `Left`, `Right` (`All` ticks a whole row).
   **Output type**: `Same as input` (videos keep their video, copied untouched) or `Audio only`
   (a video's audio is saved as `.m4a` / `.mp3` / `.opus` / `.ogg` / `.flac` / `.wav` to match its codec, else `.mka`).
3. **Output folder**: type or **Browse...**; leave blank to write next to each input file.
4. **Run**. One file is written per input × source × output. Settings and output folder are remembered.

Output names: `song_left.mp3`, `song_right.mp3`, `song_both.mp3`. When several sources are ticked
the source is added: `song_fromR_left.mp3`. The source format and bitrate are kept where possible.
