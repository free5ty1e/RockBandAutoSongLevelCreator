---
title: Local Preview & Rapid Testing (No PS4)
date: 2026-08-14
---

# Local Preview & Rapid Testing (No PS4)

**Problem:** PS4 (RB4DX) testing is slow, and the MOGG in the CON is not reliably
seekable, so iterating on lyric/vocal sync against the game is painful. We need a
computer-side loop that lets a developer (or an agent) preview a chart synced to
audio, rewind as needed, and get a quantitative pass/fail signal — without touching
the PS4.

**Solution:** the pipeline now emits a full set of **local preview & validation
artifacts** plus a **Clone Hero export** (`--build-clone-hero`). Clone Hero is a free
desktop rhythm game that plays directory-based custom songs, so an AutoRB chart can be
playtested on a PC in ~1 minute. This page is the operating manual for that loop.

## The two-part loop

1. **Human playtest:** load the exported Clone Hero song (or the WAV + SRT in VLC) and
   watch lyrics/notes land on the audio with full seek/rewind.
2. **Automated validation:** the `alignment_report.json` (+ annotated spectrograms)
   quantifies every word's charted start vs the real vocal onset, so a developer/agent
   can "read off" exactly which words are still early/late and iterate without asking
   anyone to play the game.

## Artifacts produced by every pipeline run

| Artifact | Where | What it is |
| :--- | :--- | :--- |
| `preview_mix.wav` | `<out>/preview_mix.wav` | Summed stereo mix of the 4 stems (no count-in) |
| `lyrics_preview.srt` | `<out>/lyrics_preview.srt` | Karaoke subtitles from charted word timings |
| `alignment_report.json` | `<out>/alignment_report.json` | Per-word charted vs vocal-onset deltas + summary |
| `alignment_*.png` | `<out>/alignment_specs/` | Annotated waveform/spectrogram of the worst outliers |
| `validation/notes.mid` | `<out>/validation/notes.mid` | Count-in-free chart (ticks == audio time) used by the report |
| Clone Hero folder | `<out>/clone_hero/<Artist> - <Title>/` | `song.ini` + `notes.chart` *and* `notes.mid` + `song.ogg` + `album.png` (only with `--build-clone-hero`) |

## Method A — Clone Hero playtest (recommended human loop)

Clone Hero requirements (per the [official wiki](https://wiki.clonehero.net/books/clone-hero-manual/page/adding-custom-songs)):
each song lives in its own folder inside the Songs directory and must contain at minimum
`notes.chart` **or** `notes.mid`, an audio file, and a `song.ini`. AutoRB writes
**both** chart files — the `notes.chart` is derived from the count-in-free
`notes.mid` with lyrics as `[Events]` `phrase_start`/`phrase_end`/`lyric <text>`
events (the exact layout Moonscraper exports, so CH's most battle-tested reader
path always has a file it can load). If your song fails to appear, the usual
culprit is not having pressed **Scan Songs** — CH does *not* rescan automatically.
Always check `badsongs.txt` (Songs-folder-adjacent data dir: `~/Documents/Clone Hero`,
`~/.clonehero`, or `~/Clone Hero` per [Data Locations](https://wiki.clonehero.net/books/clone-hero-manual/page/data-locations)):
it names the exact file that failed to load, which is far more useful than guessing.

> **One historical gotcha (fixed in v0.0.91):** Clone Hero's `.chart` reader is a
> fork of Moonscraper's `ChartReader`, which parses the `B` (tempo) field as an
> **integer** via `uint.TryParse` and *silently drops* any line with a fractional
> value. A `.chart` whose tempo markers were floats therefore had **no tempo map
> at all** and CH rejected the song — this was the actual reason an exported song
> could fail to appear even with a valid `notes.mid` and a fresh Scan. AutoRB now
> writes integer plain-BPM markers (drift-compensated: ~35ms worst over a song vs
> ~175ms for plain rounding), so no tempo line is ever dropped.

1. **Build the song with the CH export:**
   ```bash
   python3 -m autorb.cli input/eve6-openRoadSong.mp3 \
     --artist "Eve 6" --title "Open Road Song" --year 1998 --genre "Alternative" \
     --lyrics input/eve6-openRoadSong.lrc \
     --output-dir ./output \
     --build-clone-hero
   ```
   Produces `./output/clone_hero/Eve 6 - Open Road Song/{song.ini, notes.chart, notes.mid, song.ogg, album.png}`.

2. **Install Clone Hero** (free; Windows/macOS/Linux): <https://clonehero.info/> (the
   project also publishes builds at <https://github.com/CloneHero/CloneHero/releases>).

3. **Add the song folder:**
   - In Clone Hero: *Settings → General → Open Default Songs Folder*.
   - Copy the entire `<Artist> - <Title>` folder (or the whole `<out>/clone_hero/`
     group folder — CH supports any number of nested group folders) into the Songs dir.
   - Back in-game: *Settings → General → Scan Songs*. If a song fails to load, CH
     writes `badsongs.txt` naming the reason (most often a missing/misnamed file).

4. **Playtest:** *Quick Play → Open Road Song*. The `PART VOCALS` track renders the
   lyric notes moving up/down with pitch; use Practice Mode / pause / rewind to review
   any reported issue timestamp. Sync issues that previously took a PS4 round-trip to
   spot are now visible in seconds.

> Note: the CH chart has **no Rock Band count-in** — `notes.mid` is regenerated with
> `count_in_ticks=0` and the audio is a plain stereo mix, so **note ticks == audio
> time exactly**. Any sync judgment made in CH transfers directly to the RB chart (the
> RB chart is the same data shifted past its count-in).

### Why the CH export is loadable and the raw `.mid`/stems are not

A bare Rock Band `.mid` + MOGG isn't playable: the MOGG is a multi-channel Harmonix
container the game expects inside a CON, and the chart is shifted past the count-in.
The CH folder is the standard directory format the game scans natively.

## Method B — WAV + SRT in VLC/MPV (fastest, no game)

For a pure lyric↔audio check with rewind:

```bash
python3 -m autorb.audio.preview mix          # builds <out>/preview_mix.wav
```
Then open `preview_mix.wav` in VLC and add `lyrics_preview.srt`
(*Subtitle → Add Subtitle File*). Words highlight exactly at their charted times.
Individual stems are normal WAVs — open `stems/vocals.wav` directly to hear the
isolated vocal and verify words against the sung audio.

`python -m autorb.audio.preview --list` shows which stems are present;
`python -m autorb.audio.preview vocals` prints the path to the vocals stem.

## Method C — Automated validation (agent loop, no human)

The alignment report is the quantitative signal:

```bash
python3 -c "
import json
r = json.load(open('output/alignment_report.json'))
print(r['summary'])
print('late words:')
for w in r['words']:
    if w['flag'] == 'late':
        print(' ', w['index'], w['lyric'], w['charted_sec'], 'delta', w['delta_sec'])
"
```

- `summary.median_abs_delta_s` / `summary.p90_abs_delta_s` / `n_late` / `n_early` give a
  one-line health check of the whole chart (a good build: median ≈ 0.00–0.03, p90 ≲ 0.3).
- Each flagged word also gets an annotated waveform + mel-spectrogram in
  `alignment_specs/` (dashed = charted note, dotted = detected vocal onset) for visual
  inspection of *why* a word misses — the onset detector can be fooled by
  instrument bleed, so a human/agent confirms before treating a flag as a bug.
- The report reads the chart from `validation/notes.mid` via the MIDI tempo map
  (exact inverse of the generator), so `charted_sec` is precisely the audio time the
  game would play the note at.

**Iteration recipe:** change sync code → rebuild (`--skip-separation --skip-tempo-detection
--skip-vocals` reuse stems/cache for speed) → read `alignment_report.json` summary →
drill into the worst outliers → repeat. The repo's `tests/test_vocal_sync_fixes.py`
(13 tests) and `tests/test_clone_hero.py` / `tests/test_alignment_report.py` encode the
same invariants as CI so regressions surface without any human playtest.

## Where the code lives

- Clone Hero exporter: `autorb/export/clone_hero.py` (`build_clone_hero_song` writes the
  folder; `midi_to_chart_file` derives `notes.chart` from the count-in-free `notes.mid`) —
  wired into `autorb/cli.py` via `--build-clone-hero`.
- Alignment report + SRT: `autorb/export/alignment_report.py`
  (`build_lyrics_srt`, `build_alignment_report`).
- Stem preview CLI: `autorb/audio/preview.py` (`python -m autorb.audio.preview`).
- Stem mixing: `autorb/audio/mix_preview.py`.
- CLI option reference: `../README.md` (CLI options table).

## Why the folder has two chart files

`notes.mid` is the same data the Rock Band CON carries (minus the count-in), so it is
byte-consistent with the game chart. `notes.chart` is derived from it and is what CH's
most-tested reader consumes; if one parser ever rejects a quirk (e.g. a meta-event or
tempo-map edge case the other tolerates), the song still loads. The two are kept
in-sync by construction (`midi_to_chart_file` parses the on-disk MIDI), and
`tests/test_clone_hero.py` asserts the first vocal note / first lyric / first phrase
match between them.

## Related pages

- **[[architecture]]** — where the exporter hooks into the pipeline.
- **[[vocal_alignment]]** — the sync algorithms the report validates.
- **[[mogg_audio_format]]** — why the CON's MOGG isn't directly previewable.
- **[[ps4-environment]]** — the game-side loop this replaces for rapid iteration.
- **[[log]]** — change ledger for this and every cycle.

## Out of scope (known)

- The CH export uses the **placeholders** for drums/guitar/bass (one gem per difficulty)
  until real instrument transcription lands — the playtest value today is the vocal/lyric
  track. `PART VOCALS` is fully playable/visible.
- No attempt is made to drive Clone Hero's input headlessly; automation is done via the
  alignment report + tests rather than game automation.
- Tempo detection's stem fallback is still **drums → vocals only**; a full
  **drums → bass → vocals → other** chain with per-stem validation is on the roadmap
  (see `../ROADMAP.md`) so beat tracking works for drumless/bass-led songs.
