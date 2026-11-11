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

To put it on another computer, copy or download `ChannelMirror.exe` there and double-click it. Click **Install** and it installs itself for that user (Start menu, optional desktop and Send To shortcuts, uninstall from Settings > Apps); or click **Just run it** to use it portably. Running a newer exe the same way updates it. Details: [SETUP.md section 6](SETUP.md#6-installing-and-distributing-the-executable).

It needs ffmpeg: on first
start without it, a setup screen offers **Install ffmpeg** (downloads the official Windows build, ~110 MB,
checksum-verified, into `%LOCALAPPDATA%\ChannelMirror\ffmpeg`; only once). Or install ffmpeg on PATH yourself,
or put `ffmpeg.exe` + `ffprobe.exe` in the same folder as the exe. Prebuilt exe: see the repo's **Releases** page.

**Drag and drop**: drop files or folders onto `ChannelMirror.exe` (or its shortcut) to open with them loaded.
The installer adds right-click **Send to** for you. To add it by hand for an uninstalled copy (run once, from this folder in PowerShell):

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

## Stream Deck soundboard tab

Turns sounds (picked files, a folder, or what the Channel Mirror tab just wrote) into Stream Deck **Play Audio** keys.

1. **Device**: decks come from your own Stream Deck profiles. A deck that is plugged in right now is listed first as `[connected]`. Columns/Rows set the key grid.
2. **Map keys**: click a key on the grid. Then use *Add folder to this key* (every sound in the folder goes on that one key), *Add files to this key*, or *Selected sounds -> this key*. Set the key's **Action** (Single sound / Multi Action = all play at once / Random Action = one random sound per press) and its **Key name**. Sounds with no key fill the free keys in order.
3. **Sound settings** (per sound): name, Play / Stop, Play / Overlap, Play / Restart or Loop / Stop, fade (in/out/both, 1-5 s), volume, output device.
4. **Send to Stream Deck**: with *Install directly* ticked (the default when Stream Deck is installed), the profile goes straight into Stream Deck. Stream Deck is closed and reopened, and there's no import prompt. Otherwise it writes `%LOCALAPPDATA%\ChannelMirror\Stream Deck profiles\<name>.streamDeckProfile` (audio bundled inside) and opens it. Stream Deck then asks you to import it as a new profile.

## Stream Deck editor tab

Edits the buttons already in your local Stream Deck app.

1. Pick a **profile** (decks that are plugged in are listed first) and a **page**. Pages behind folder keys show as `Folder: <name>`.
2. Click keys to select them, or use *Select sound keys* / *Select missing* / *Select all*. Colours: green = sound key, red = its sound file is missing, grey = another kind of action.
3. Choose **what you want to do**, set the options, press **Apply** (you can apply several changes in a row):
   - **Set them up for a purpose**: one-click presets. Reaction/spammable, stinger/one-shot, toggle clip, background music loop, ambience bed, intro/outro music, voice line.
   - **Playback and fade**: Play / Stop, Play / Overlap, Play / Restart or Loop / Stop, fade type and fade length.
   - **Volume**: set it, change it by +/-, or **Match loudness** (measures every file and turns the louder ones down to match the quietest).
   - **Output device**: pick a Multi or Random Action from the *Multi / Random* list (every page and folder of the profile; ones with sounds first) and set the output for every sound inside it at once. The list shows devices Stream Deck has saved itself first (exact), then this PC's playback devices.
   - **Key names and look**: name from the file name, folder name or a number; clear it; add text before/after; find and replace; show/hide the name; font size, position and colour.
   - **Arrange keys**: move/swap a key, combine keys into one Random or Multi Action, split them back into single keys, add a *Stop all audio* key, delete keys.
   - **Fix missing sound files**: points broken sound keys (e.g. profiles copied from another computer) at a file with the same name in a folder you choose.
4. **Save to Stream Deck**: closes Stream Deck (it rewrites its profiles when it exits), backs up the touched profiles to `%LOCALAPPDATA%\ChannelMirror\Stream Deck backups\profiles-<time>.zip`, writes the changes and reopens Stream Deck. To undo a save, unzip the backup into `%APPDATA%\Elgato\StreamDeck\ProfilesV3`. *Revert unsaved* throws away changes you haven't saved.

## Working in the app

- **Keys grid** (both Stream Deck tabs): click to select; Ctrl+click to add more keys; drag one key onto another to move or swap them; double-click to edit; right-click for a menu. Hover over a key to see what's on it.
- **Edit key window** (Stream Deck editor tab; double-click a key or right-click > Edit key): name, show/hide, font size, position, colour, and every sound on the key (file, action, fade, volume, output). You can also add sounds (a single sound becomes a Random or Multi Action), remove them or reorder them.
- **Lists**: double-click a cell to change it in place (name, key, action, fade, volume, output). In the soundboard tab, drag sounds from the list onto a key to map them.
- **Shortcuts**:
  - Editor tab: Ctrl+Z / Ctrl+Y undo/redo, Ctrl+S save, Ctrl+C / Ctrl+V copy/paste a key (works across pages and profiles), Del delete, Ctrl+A select all, Esc select none.
  - Soundboard tab: Del removes sounds, Space previews the selected sound.
- The window remembers its size and the last tab you used.
