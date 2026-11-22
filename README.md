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
   **One key per sound, in folders of N** (tick it below the sound list): instead of the key mapping, every sound gets its own key inside a folder, in list order, playing **once** or on a **loop** (or as set per sound). When a folder is full the next one is made (`name`, `name 2`...); the folder keys fill the page. *Scale volume...* multiplies the volume of the selected sounds (or all) by a percentage.
4. **Send to Stream Deck**: with *Install directly* ticked (the default when Stream Deck is installed), the profile goes straight into Stream Deck. Stream Deck is closed and reopened, and there's no import prompt. Otherwise it writes `%LOCALAPPDATA%\ChannelMirror\Stream Deck profiles\<name>.streamDeckProfile` (audio bundled inside) and opens it. Stream Deck then asks you to import it as a new profile.

## Stream Deck editor tab

Edits the buttons already in your local Stream Deck app.

1. Pick a **profile** (decks that are plugged in are listed first) and a **page**. Pages behind folder keys show as `Folder: <name>`.
2. Click keys to select them, or use *Select sound keys* / *Select missing* / *Select all*. Colours: green = sound key, red = its sound file is missing, grey = another kind of action.
3. Choose **what you want to do**, set the options, press **Apply** (you can apply several changes in a row):
   - **Set them up for a purpose**: one-click presets. Reaction/spammable, stinger/one-shot, toggle clip, background music loop, ambience bed, intro/outro music, voice line.
   - **Playback and fade**: Play / Stop, Play / Overlap, Play / Restart or Loop / Stop, fade type and fade length.
   - **Volume**: set it, change it by +/-, **scale it by %** (keeps them in proportion), or **Match loudness** (measures every file and turns the louder ones down to match the quietest).
   - **Output device**: pick a Multi or Random Action from the *Multi / Random* list (every page and folder of the profile; ones with sounds first) and set the output for every sound inside it at once. The list shows devices Stream Deck has saved itself first (exact), then this PC's playback devices.
   - **Key names and look**: name from the file name, folder name or a number; clear it; add text before/after; find and replace; show/hide the name; font size, position and colour.
   - **Arrange keys**: move/swap a key, combine keys into one Random or Multi Action, split them back into single keys, add a *Stop all audio* key, delete keys.
   - **Fix missing sound files**: points broken sound keys (e.g. profiles copied from another computer) at a file with the same name in a folder you choose.

   With *Apply to: Selected keys*, a selected **folder key stands for every sound inside it** (folders inside folders too) for the sound tools above: presets, playback, volume (including *Match loudness* and tuning to your OBS levels), output device and fixing missing files. *Key names and look* and *Arrange keys* still act on the folder key itself.
4. **Save to Stream Deck**: closes Stream Deck (it rewrites its profiles when it exits), backs up the touched profiles to `%LOCALAPPDATA%\ChannelMirror\Stream Deck backups\profiles-<time>.zip`, writes the changes and reopens Stream Deck. To undo a save, unzip the backup into `%APPDATA%\Elgato\StreamDeck\ProfilesV3`. *Revert unsaved* throws away changes you haven't saved.

### Adding sounds and folders (editor tab, right-click a key)

Picked files, and the files in a picked folder, always go in name order as Explorer shows them (`track2` before `track10`).

- **A sound, Random or Multi key**: *Add sound files to this key...* / *Add a folder of sounds to this key...*. A Random or Multi Action gets the new sounds added. A single sound asks whether to become a Random Action or a Multi Action. New sounds copy the key's first sound's settings.
- **A folder key**:
  - *Add sound files into this folder...* / *Add a folder of sounds into this folder...* put one key per sound on the folder's free keys, in order. Sounds that don't fit **carry over into new folders** (`SFX 2`, `SFX 3`...), placed just beside the folder key, or on the next free keys of the page.
  - *Same settings for every sound inside...* sets playback, fade, volume or output for all of them in one window.
- **An empty key**:
  - *New folder(s) of sounds from files... / from a folder...* make a new folder there. Its page has the Parent Folder key top-left, then one key per sound in order. If there are more sounds than a folder holds, it makes as many folders as needed, each one beside the last.
  - *New folders, one per subfolder (mass import)...* takes a folder of folders (e.g. `Drums\`, `Voices\`, `Memes\`) and makes one Stream Deck folder per subfolder, named after it. It also makes one for the sounds sitting directly in the picked folder, and full ones carry over as above.
  - *Fill free keys from here...* puts one key per sound on this page's free keys, starting at that key.
- If the page runs out of keys, it asks whether to add just the first ones that fit.
- Copying and pasting a folder key copies everything inside it, so the pasted folder is its own (also in another profile).
- New folders show in the page list straight away, and undo removes them. A new folder deleted before you save is never written.

## Import to folders tab

Puts sounds into a profile already in Stream Deck, each on its own key, in folders.

1. **Sounds**: add files, a folder, or what the Channel Mirror tab just wrote. They go in name order (`track2` before `track10`).
2. **How each key plays**: **Play once** (press again to stop) or **Loop** (repeats until pressed again), with fade, volume and output device.
3. **Volume**: tune each sound to your OBS levels and/or scale every volume by a percentage. *Check levels...* listens to each file and shows where it would sit before anything changes.
4. **Folders**: a name and how many sounds go in each folder (up to a full page; one key is the back key). More sounds = more folders: `name`, `name 2`, `name 3`...
5. **Where the folders go**: pick a profile and browse its pages (folder pages too). Keys in use are grey and can't be picked, so nothing is doubled up or overwritten. Click free keys in order: folder 1, 2, 3... If you pick fewer keys than folders, the rest go on the next free keys after your last pick.

**Import** adds it all as one change, which you can undo here or in the editor tab. It's sent to Stream Deck from the editor (or automatically). Right-clicking an empty key in the editor (*Import sounds into folders...*) opens this tab with that key picked.

## Key mover tab

Copies or moves keys of any kind between pages, profiles and devices: sounds, Multi / Random Actions, folders (with everything inside them, folders in folders too), hotkeys and other plugin actions. Custom key icons come along.

1. Pick a profile and page on each side (left and right decks).
2. Click the keys to copy or move (click again to drop one; *Select every key* takes a whole page).
3. On the other side, click where they go: one key to start from (with *Keep their layout* they keep their shape), or a key for each, in order.
4. **When a target key is in use**: put it on the next free key, replace what's there, or skip it. Keys that don't fit a smaller deck go on the next free keys.
5. **Copy >>** / **Move >>** (or the other way round). Copies are independent keys (their own folder pages). Moving within one profile keeps a folder's pages; moving to another profile gives it its own copy.

Changes are one undo (here or in the editor tab) and are sent to Stream Deck from the editor tab (or automatically).

## Screen recorder tab

Records part of a monitor to a video file.

1. **Monitor**: pick the one to record. Sizes and positions are real pixels, even when monitors use different Windows scaling.
2. **The area**: type X / Y (from the monitor's top-left), width and height, press *Whole monitor*, or *Drag the area on screen...* (a see-through layer appears on that monitor; drag the box, Esc cancels).
3. **Outline**: a line around the area stays on screen so you can see exactly what's recorded (amber while waiting, red while recording). Clicks go straight through it, so everything underneath stays usable, and it never shows up in the video.
4. **Floating Record / Stop button**: sits beside the area (drag it by its timer to move it), so you can start and stop without switching back to the app. It isn't recorded either.
5. **How and where**: frames per second, show the mouse pointer or not, minimize Channel Mirror while recording, the folder to save in and the file name. Each recording is `<name> <date time>.mp4` (H.264).
6. **Record** / **Stop**. The recordings made this session are listed below; double-click one to play it. Closing the app while recording finishes the file first.

Leaving out the outline and button needs Windows 10 (version 2004) or newer.

## VTube Studio backgrounds tab

Puts backgrounds into VTube Studio, makes a hotkey for each, and puts a Stream Deck key for each that switches to it.

1. **VTube Studio**: the install is found through Steam (or *Browse...* to its `StreamingAssets` folder). Pick the **model** that gets the hotkeys - they work while that model is loaded.
2. **Backgrounds**: *Add files...* (one or several) or *Add folder...* (every png / jpg / mp4 directly in it, in name order). The list shows which are new and which VTube Studio already has.
3. **Copy and set up**:
   - copies them into VTube Studio's `Backgrounds` folder. Nothing there is overwritten: the same file is reused, and a different file with the same name goes in as `name (2)`;
   - adds a **Change Background** hotkey for each to the model (one it already has for that background is reused). VTube Studio saves its model files when it closes, so if it's open it is closed for a moment (you're asked first), the model file is backed up to `%LOCALAPPDATA%\ChannelMirror\VTube Studio backups`, the hotkeys are written and checked, and VTube Studio is reopened;
   - puts a **Trigger Hotkey** key for each on Stream Deck (the *VTube Studio* plugin by Cazzar), on the keys you pick on any profile and page - in-use keys are grey and can't be picked - or **in folders of N** (`name`, `name 2`...). They're one undo and are sent to Stream Deck from the editor tab (or automatically).

## Link tab

Send files into Channel Mirror from a link, or from another device on your home network. Whatever arrives is shown first, with where it would go; nothing is placed until you **Accept** (Decline deletes the received copies).

- **Links on this PC** (`channelmirror://...`): installing Channel Mirror sets these up (or press *Set up links*). Clicking one - in a browser, Discord, a shortcut - opens Channel Mirror (or hands it to the one already open) with its files ready for a tab: Stream Deck keys (*Import to folders*), *VTube Studio backgrounds*, the *soundboard*, or *Channel Mirror* itself. *Make a link* builds one from files; links can also carry web addresses, which are downloaded. Format: `channelmirror://open?to=import|vts|soundboard|mirror&file=C:\path\sound.mp3&url=https://...`.
- **Receive from other devices**: press *Start receiving* and open the pairing link it shows (`http://<this PC>:8765/?code=123456`) on the other device - a phone, laptop or another PC on the same network gets a page to pick files and where they go. Only devices on the home network with the code can send; only sound, video and picture files are taken. *New code* stops old links working; *Stop receiving* closes it. Windows may ask once whether Channel Mirror may use the network: allow **private** networks.
- **Send to another device**: paste the other Channel Mirror's pairing link, pick files and where they go, *Send*.

## Working in the app

- **Keys grid** (both Stream Deck tabs): click to select; Ctrl+click to add more keys; drag one key onto another to move or swap them; double-click to edit; right-click for a menu. Hover over a key to see what's on it.
- **Edit key window** (Stream Deck editor tab; double-click a key or right-click > Edit key): name, show/hide, font size, position, colour, and every sound on the key (file, action, fade, volume, output). You can also add sounds or a whole folder of sounds (a single sound becomes a Random or Multi Action), remove them or reorder them.
- **Lists**: double-click a cell to change it in place (name, key, action, fade, volume, output). In the soundboard tab, drag sounds from the list onto a key to map them.
- **Shortcuts**:
  - Editor tab: Ctrl+Z / Ctrl+Y undo/redo, Ctrl+S save, Ctrl+C / Ctrl+V copy/paste a key (works across pages and profiles), Del delete, Ctrl+A select all, Esc select none.
  - Soundboard tab: Del removes sounds, Space previews the selected sound.
- The window remembers its size and the last tab you used.
