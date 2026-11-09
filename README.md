# Channel Mirror

Small desktop tool that analyzes the channels of audio files and writes new files with a chosen
source channel routed to Left, Right, or Both. Channels that aren't targets are fully silent.
Originals are never modified.

## Requirements

- Python 3.10+ with `numpy` (`pip install numpy`)
- [ffmpeg](https://ffmpeg.org/) (`ffmpeg` and `ffprobe` on PATH), e.g. `winget install Gyan.FFmpeg`

## Use

```
python channel_mirror.py             # open the window
python channel_mirror.py --selftest  # end-to-end check
```

1. **Add files...** or **Add folder...** (every audio file in that folder). Each row shows per-channel loudness (RMS dB).
2. Tick **Source**: `Auto (loudest)`, `L`, `R` (or `All`).
3. Tick **Output to**: `Both`, `Left`, `Right` (or `All`).
4. **Save output files...** and pick a folder. One file is written per input × source × output.

Output names: `song_left.mp3`, `song_right.mp3`, `song_both.mp3`. When several sources are ticked
the source is added: `song_fromR_left.mp3`. The source format and bitrate are kept where possible.
