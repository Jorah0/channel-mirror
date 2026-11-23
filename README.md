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
The installer adds right-click **Send to** for you: *Channel Mirror* (opens with them loaded) and *Channel Mirror (linked
computers)*, which opens a small window - which linked computer and which of its tabs they go to - and sends them there
on **Send** (handed to the app if it's already open; uninstalling removes both). To add it by hand for an uninstalled copy (run once, from this folder in PowerShell):

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\SendTo\Channel Mirror.lnk")
$s.TargetPath = "$PWD\dist\ChannelMirror.exe"; $s.Save()
```

## Use from source

```text
pythonw channel_mirror.py            # open the desktop window (no console)
python channel_mirror.py --selftest  # end-to-end check
python tests/run_all.py              # everything: selftest, every tab driven by script, layout in light + dark
```

`channel_mirror.py` is the master file you run; the app itself is in `cmlib/`, one file per part (the first line
of each says what it holds; `tab_*.py` = one per tab, `app.py` = the main window).

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
7. **Recordings go to**: *Folder I pick* (the folder above), *VTube Studio backgrounds (this PC)* (straight into VTube Studio's Backgrounds folder - a new name every time, nothing is overwritten; if VTube Studio isn't found, pick it in the Setup tab), or *VTube Studio backgrounds on [linked computer]* (sent there when you stop; it lands in that PC's backgrounds once someone accepts it there). Tick *Also put it in the VTube Studio tab* to make a hotkey / Stream Deck key for it next. Your choice is remembered.

Leaving out the outline and button needs Windows 10 (version 2004) or newer.

## VTube Studio backgrounds tab

Puts backgrounds into VTube Studio, makes a hotkey for each, and puts a Stream Deck key for each that switches to it.

1. **VTube Studio**: the install is found through Steam (or *Browse...* to its `StreamingAssets` folder). Pick the **model** that gets the hotkeys - they work while that model is loaded.
2. **Backgrounds**: *Add files...* (one or several) or *Add folder...* (every png / jpg / mp4 directly in it, in name order). The list shows which are new and which VTube Studio already has.
3. **Copy and set up**:
   - copies them into VTube Studio's `Backgrounds` folder. Nothing there is overwritten: the same file is reused, and a different file with the same name goes in as `name (2)`;
   - adds a **Change Background** hotkey for each to the model (one it already has for that background is reused). VTube Studio saves its model files when it closes, so if it's open it is closed for a moment (you're asked first), the model file is backed up to `%LOCALAPPDATA%\ChannelMirror\VTube Studio backups`, the hotkeys are written and checked, and VTube Studio is reopened;
   - puts a **Trigger Hotkey** key for each on Stream Deck (the *VTube Studio* plugin by Cazzar), on the keys you pick on any profile and page - in-use keys are grey and can't be picked - or **in folders of N** (`name`, `name 2`...). They're one undo and are sent to Stream Deck from the editor tab (or automatically).

## Music player tab

Music playlists, played here and in OBS - on this PC or any PC on your home network.

1. **Playlists**: *New*, *Rename*, *Duplicate*, *Delete*. *Import .m3u...* turns playlists from other players (.m3u / .m3u8) into playlists here; *Export .m3u...* saves one as .m3u8 (songs inside its folder as relative paths). Only files on this PC's own drives are taken from a playlist file - web addresses and network shares are skipped.
2. **Songs** (red = its file isn't there; looked at once, and again when you add or import songs or come back to the tab): *Add files...*, *Add folder...* (name order), *From Channel Mirror...* in the strip at the top (files the app knows, or **a linked computer's playlists and files** - fetched, checked and kept in Received), *Move up* / *Move down*, *Remove* (Del). Double-click a song to play it. *Send there* sends the open playlist to a linked computer, where it becomes a playlist once accepted. Files sent from another device or a link with *Music player* as the destination go into the open playlist.
3. **Player**: *Previous* / *Play* / *Pause* / *Stop* / *Next*, the position bar (drag to seek), volume, *Shuffle*, *Repeat off / one / all*. *Hear it here on* plays it on this PC too, on the output you pick.
4. **Play it in OBS**: *Start sharing* shows two links (*Copy* beside each). In OBS on any PC on your home network:
   - **Media Source** -> untick *Local File* -> paste the **music stream** link. It's one endless stream: it doesn't stop between songs or while paused, so OBS never drops it.
   - **Browser Source** -> paste the **now-playing overlay** link (about 800 x 160): the song and playlist on a transparent background, updated by itself.
   - OBS on this PC can also show the song with a **Text source** set to *Read from file*: `%LOCALAPPDATA%\ChannelMirror\Now playing.txt`.

   The links stay the same after a restart (sharing starts again by itself if it was on). *New link* makes new ones - the old ones stop working at once. Like the Link tab it only answers devices on your home network, plain http (home only; on a network Windows has marked Public you're asked first). Nothing changes OBS's own settings.

## OBS tab

Control OBS from Channel Mirror - on this PC, or on a linked computer's - and feed it what Channel Mirror plays.

1. **Connect**: in OBS, *Tools > WebSocket Server Settings*: tick *Enable WebSocket server*, then *Show Connect Info* for the port (4455) and password. Put them in the tab and press **Connect**. A wrong password is refused and said so; a dropped connection comes back by itself; it connects again on the next start if it was connected. (OBS 28 or later; the password is kept in your Channel Mirror settings file.)
2. **Scenes**: one button per scene - click one to put it on air (the one on air is blue; a change made in OBS shows here by itself).
3. **Sources in the scene**: *Show / hide* (or double-click) a source.
4. **Audio mixer**: pick an audio source, *Mute / unmute*, drag the volume (set when you let go).
5. **Media sources**: *Play*, *Pause*, *Restart*, *Stop*, with its state.
6. **Live**: start / stop **streaming**, **recording** and the **virtual camera** - LIVE / REC / ON shows while they run.
7. **Feeds for OBS** - only audio Channel Mirror plays itself:
   - **Music**: the Music player's stream (*Start sharing* there first).
   - **Soundboard**: *Start soundboard feed* - one endless stream (like the music one: silence between sounds, so OBS never drops it). Pick a **Sound** (the Stream Deck soundboard tab's sounds) and *Play* - sounds mix, several at once; *Stop* ends them. *Play a file in the feed...* plays any sound file.
   - *Copy* beside each link; **Add to OBS: Music / Overlay / Soundboard** puts the music stream, the now-playing overlay (a Browser Source) or the soundboard feed straight into the **Scene** you pick - in this PC's OBS or the linked computer's.
8. **Files to OBS**: *Send files to OBS...* puts a picture, sound or video **into** a source OBS has (an Image or Media source), or as **a new source** in the scene picked above.

**A linked computer's OBS**: in the strip at the top pick the computer and press **Control its OBS** (the purple *Controlling: OBS on ...* banner shows it; *This PC's OBS* goes back). It works only once **that** PC allows this one: on the PC with OBS, *Linked computers* tab, select this computer and tick **May control OBS on this PC** - off unless you turn it on, for each computer. Then its commands run straight away (live, mid-stream) - only the ones above, nothing else, at most 20 every 5 seconds. Files sent for its OBS still ask there first, like everything else over the link; accepted, they're kept in its Received folder and shown in its OBS.

## Transcribe tab

Turns what's said in videos and recordings (any file with sound - hours long is fine) into documents: every voice line with its time. It all runs on this PC, inside ffmpeg (its `whisper` filter: whisper.cpp speech recognition); nothing is uploaded.

1. **Add files...** / **Add folder...** (every video / recording directly in it, in name order). The list shows each file's status: *waiting*, *transcribing 40%*, *done (n lines)*, *failed* (with why - e.g. a video with no sound).
2. **Model**: *tiny* (75 MB, fastest) up to *large-v3-turbo* (1.6 GB, most accurate); *small* (466 MB) is the default. Models ending in *.en* understand English only (and are a little better at it). A model is downloaded the first time it's used - only after you say yes - from the whisper.cpp project on Hugging Face, into `%LOCALAPPDATA%\ChannelMirror\whisper`; its size and SHA-256 checksum are checked, and a cut-off download carries on where it stopped next time.
3. **Language**: *Auto-detect* (each file) or the one spoken.
4. **Use the graphics card**: on by default (much faster); if that run fails, the file is done again on the processor. **Voice detection** skips long silences, but ffmpeg 8.1's filter is much slower with it, so it's off by default (whisper copes with silence on its own).
5. **Documents**: *Word (.docx)* (the title, then one paragraph per voice line with its `[hh:mm:ss]`), *PDF* (the same, wrapped and paged with page numbers; the text is real, selectable and searchable text in any script - fonts from Windows are embedded), *Subtitles (.srt)* and *Text (.txt)*. Each is named `<file name> transcript.<ext>`, beside the file or in the folder you pick; a subtitle file the video already has is never touched.
6. **Start** / **Cancel** (stops at once; nothing half-written is left). **Open result** opens the selected file's document (double-click a row does too), **Open folder** its folder.

Speed on an RTX 4090 (10 minutes of speech): *tiny.en* about 195 minutes of video per minute on the graphics card, 15 on the processor; *small* about 58 on the graphics card, 3.6 on the processor.

Needs ffmpeg 8 or newer built with whisper (the gyan.dev "full" build, as on this PC); with an older ffmpeg the tab says so. Not done in the PDF: joining Arabic letters and shaping Indian scripts (the text is still all there, copyable and searchable). The *Working on* strip picks recordings from Channel Mirror (here or on a linked computer) to transcribe; sending the finished documents to a linked computer isn't possible yet (links carry media files only).

## Link tab

Send files into Channel Mirror from a link, or from another device on your home network. Whatever arrives is shown first, with where it would go; nothing is placed until you **Accept** (Decline deletes the received copies).

- **Links on this PC** (`channelmirror://...`): installing Channel Mirror sets these up (or press *Set up links*). Clicking one - in a browser, Discord, a shortcut - opens Channel Mirror (or hands it to the one already open) with its files ready for a tab: Stream Deck keys (*Import to folders*), *VTube Studio backgrounds*, the *soundboard*, or *Channel Mirror* itself. *Make a link* builds one from files; links can also carry web addresses, which are downloaded. Format: `channelmirror://open?to=import|vts|soundboard|mirror&file=C:\path\sound.mp3&url=https://...`.
- **Receive from other devices**: press *Start receiving* and open the pairing link it shows (`http://<this PC>:8765/?code=123456`) on the other device - a phone, laptop or another PC on the same network gets a page to pick files and where they go. Only devices on the home network with the code can send; only sound, video and picture files are taken. *New code* stops old links working; *Stop receiving* closes it. Windows may ask once whether Channel Mirror may use the network: allow **private** networks.
- **Send to another device**: paste the other Channel Mirror's pairing link, pick files and where they go, *Send*.

- **Linked computers tab**: everything for two PCs working together is there (below). *Send files...* sends files straight to a linked computer, to the tab that fits them there (pictures: VTube Studio backgrounds, sounds: Import to folders, recordings: kept as files, other videos: Channel Mirror). *Send again* sends the same files to the same place. *From Channel Mirror...* beside *Add files* picks from files the app already knows.

## Linked computers (two PCs working together)

Got a streaming PC and a gaming PC? Link them once, and for **30 days** each one can send its work to the other, and open the other's Stream Deck and VTube Studio from here.

**Link them**
1. On the other PC, open the **Link** tab and press *Start receiving*. Copy the pairing link it shows.
2. On this PC, open the **Linked computers** tab, paste it and press **Link**.
3. The other PC asks whether to link - press *Yes* there. Done: both PCs list each other.

The list shows each linked computer's name, address, **linked until** (and days left) and what's happening now (online / offline and last seen, sending 3 of 5, waiting for an answer, accepted / declined). *Rename* changes the name shown here. *Renew* asks the other PC to start a fresh 30 days (it's asked there). *Unlink* forgets it here and tells the other PC. After 30 days the link stops working on both PCs and shows **expired - verify again**: paste its pairing link and press *Link* again. Linked PCs start receiving by themselves when the app opens, and find each other again if one gets a new address on your network.

**The Linked computers tab** is home for all of it: link / renew / rename / unlink, *Send files...* and *Send again*, *Its Stream Decks* (its decks, plugged in or not, and its VTube Studio models), *Get its files...* (its outputs, recordings, received files, backgrounds and key sounds - fetched into your Received folder), *Record there* / *Stop there*, buttons that open a tool already pointed at that PC (*Stream Deck editor with it*, *Key mover with it*, *VTube Studio with it*, ...), and **Going back and forth**: a log of everything sent and received - sending, waiting for an answer, accepted, declined - both ways.

**In every tool** a strip at the top shows **Working on: This PC**, and lets you:
- **From Channel Mirror...** - pick files the app already knows: Channel Mirror outputs, screen recordings, received files, VTube Studio backgrounds and the sounds already on your Stream Deck keys - on this PC or on a linked computer (its files are fetched and checked first). Search, and Ctrl / Shift + click for several.
- **Send there** - send the tab's work to the linked computer you pick: Channel Mirror files with your settings, soundboard sounds with their keys and playback settings, Import to folders sounds, VTube Studio backgrounds with the model, or recordings. It lands in the same tab there, filled in.
  - Soundboard: tick **install it there** and, once accepted, it's also installed into that PC's Stream Deck as a new profile (its deck; Stream Deck closed and reopened, a backup first - like *Install directly* here).
  - VTube Studio: tick **set them up there (hotkeys, keys)** and, once accepted, that PC's own VTube Studio tab does it all: copies them into its Backgrounds, a Change Background hotkey each (on your model if it has it, else the one picked there), and a Stream Deck key each (on the keys picked there, or its first free one) - VTube Studio is closed, its model file backed up, and reopened. The same option is in *Open its VTube Studio...*.
  - **Right-click > Send to [PC]** on a tab's file list (soundboard sounds, Import to folders, VTube Studio backgrounds, recordings, music playlist songs) sends just the selected files the same way.
  - More than 200 files go **in batches of 200**: each batch is its own proposal there (one Accept each).
- **Open its Stream Deck...** (editor and Key mover tabs) - a window with a purple **Working on: [that PC]** banner shows its Stream Decks (plugged in or not) and profiles next to yours. Put sounds on its keys, rename or clear them, or copy keys between the two PCs (*Copy to [PC] &gt;* and *&lt; Copy here*, folders and icons included - the icons of keys inside folders too). *Move to [PC] &gt;* moves them: your keys are taken away here only after that PC accepted and applied the copy (one undo in the editor tab). Your changes wait in the window until **Send**; on the other PC they're shown in plain words and applied only when someone accepts - through its own editor (undo works there), then sent to its Stream Deck app (backup first, Stream Deck reopened).
- **Open its VTube Studio...** - its models and backgrounds; send backgrounds there, put in its Backgrounds folder once accepted, with its VTube Studio tab filled in for hotkeys / keys.
- **Record there / Stop there** (Screen recorder) - starts or stops a recording on the other PC (it's asked there); the finished file is sent back to you.

**Nothing changes without a yes.** Every send, edit or recording request waits on the other PC until someone presses *Accept* there; *Decline* deletes what came. Either way the answer shows on the PC that sent it.

**What's allowed over the link** - only what these tools use:
- files: sounds for the soundboard, Import and Stream Deck keys; sounds and videos for Channel Mirror; png / jpg / mp4 for VTube Studio; mp4 recordings; key icons only with their key. Each file's content is checked (a renamed program is refused), with size limits.
- Stream Deck keys: sounds, Stop audio, Multi / Random Actions of those, folders, and VTube Studio hotkeys. Keys that open programs or websites, press hotkeys or type text never go over the link.
- requests: a fixed list (look at its Stream Deck / VTube Studio / files, send files or changes for a tab, start / stop a recording, link / renew / unlink, and - only where that PC ticked *May control OBS* - the OBS tab's own commands, each checked). Anything else is refused and the reason is shown.
- It only works between PCs on your home network. Every request is signed with the link's secret (the secret itself crosses the network once, when you link); recordings of a request can't be replayed; file paths from the other PC are never used here.

## Setup tab

Where everything is on this PC - found by itself:
- the **Stream Deck** profiles folder and app, **VTube Studio**, **ffmpeg**, the Channel Mirror **output** folder, the **recordings** folder, **received files**, and where **Stream Deck** and **VTube Studio backups** go.
- Each shows *Found*, *Ready* or *Not found*. Kept somewhere else? Press **Browse...** and pick it - every tool uses it from then on. **Auto** goes back to finding it by itself.
- Changing the Stream Deck folder or app needs a restart: press **Restart now**.

**Appearance**: **Light**, **Dark** or **Follow Windows** (switches with Windows' own light / dark setting). It changes straight away, title bars included, and is remembered.

## Working in the app

- **Finding your way**: the tools ("tabs" below) are listed down the left, grouped - *Audio* (Channel Mirror, Music player, Transcribe), *Stream Deck* (soundboard, editor, Import to folders, Key mover), *Capture* (Screen recorder, VTube Studio backgrounds), *Broadcast* (OBS), *Connect* (Link, Linked computers) - with *Setup* at the foot. Click one, or use Ctrl+Tab / Ctrl+Shift+Tab anywhere (Up / Down when the list has focus). A narrow window shows icons only (hover for the name); the menu button at the top does that on a wide one too.
- **Status bar** (the foot of the window): linked computers, whether OBS is connected (or which linked computer's OBS you control), what's shared with OBS (music, soundboard feed), a recording running, and Stream Deck pages not sent yet. Click one to open its tool.
- **Keys grid** (both Stream Deck tabs): click to select; Ctrl+click to add more keys; drag one key onto another to move or swap them; double-click to edit; right-click for a menu. Hover over a key to see what's on it.
- **Edit key window** (Stream Deck editor tab; double-click a key or right-click > Edit key): name, show/hide, font size, position, colour, and every sound on the key (file, action, fade, volume, output). You can also add sounds or a whole folder of sounds (a single sound becomes a Random or Multi Action), remove them or reorder them.
- **Lists**: double-click a cell to change it in place (name, key, action, fade, volume, output). In the soundboard tab, drag sounds from the list onto a key to map them.
- **Shortcuts**:
  - Editor tab: Ctrl+Z / Ctrl+Y undo/redo, Ctrl+S save, Ctrl+C / Ctrl+V copy/paste a key (works across pages and profiles), Del delete, Ctrl+A select all, Esc select none.
  - Soundboard tab: Del removes sounds, Space previews the selected sound.
- The window remembers its size, the last tool you used and whether the list on the left shows names.
