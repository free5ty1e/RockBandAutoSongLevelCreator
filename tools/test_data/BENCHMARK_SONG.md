# Release-audit benchmark song (stage 5b functional conversion)

**Track:** "Tisk Tisk Sadness" — **Trans Atlantic Rage**
**Source:** [Free Music Archive (Internet Archive mirror)](https://archive.org/details/Introverted_Circumstances-7242)
**License:** [Creative Commons BY-NC-ND 3.0](http://creativecommons.org/licenses/by-nc-nd/3.0/) — free to share and use non-commercially with attribution; no derivatives. **This file is committed to the repo as a validation fixture.** (If a fully-permissive license is ever required, swap the benchmark via `fetch_benchmark.sh` and update this file.)

## Why this song
- Full-band punk rock: drums, bass, distorted guitar, prominent vocals — the
  instrument mix AutoRB must chart.
- A *different* profile from Open Road Song (81% voiced vs 59%, sparser
  onsets, thinner cymbal highs) so the two benchmark songs exercise
  different transcription paths.
- 52 seconds: the Demucs separation in the release audit completes in a
  few minutes of CI time.

## Adding your own local test songs (e.g. Open Road Song)
Stage 5b ALSO converts any `*.mp3` (+ optional matching `*.lrc`) placed in
`tools/test_data/local/` — one conversion per song pair. That folder is
**git-ignored**: copyrighted material must never be committed. To enable
the Open Road Song validation locally:

```bash
mkdir -p tools/test_data/local
cp /path/to/eve6-openRoadSong.mp3 tools/test_data/local/
cp /path/to/eve6-openRoadSong.lrc tools/test_data/local/   # optional
```

The audit logs each local song's artifact results separately, so your
local validations cover the free benchmark AND Open Road Song (plus any
other songs you drop in). CI only runs the committed benchmark — local
songs are private to your machine.

## Re-fetching / swapping the benchmark
`bash tools/test_data/fetch_benchmark.sh` (idempotent). The download URL
and license are pinned above; if the item moves, update the script AND
this file together.
