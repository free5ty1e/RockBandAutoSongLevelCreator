# Charting songs for Clone Hero (`.chart` lane rules)

How AutoRB turns its packed Rock Band 3 MIDI into a Clone Hero-loading `notes.chart`, and the **lane-decoding rules that make or break a load**. Captured at **v0.0.93** after a headless capture proved the drums chart was erroring out because it wrote raw MIDI pitches instead of Clone Hero lanes.

## Scope: Clone Hero `.chart` vs Rock Band CON `.mid`

**This page is primarily about the Clone Hero `.chart` export.** The two target formats address notes differently, and conflating them is the root of most charting bugs:

- **Rock Band CON (`notes.mid`) — pitch-addressed.** Drums are stored as real MIDI notes via `DRUM_LANE_MAP` (`autorb/transcribe/instruments/drum_classifier.py`): `kick=36, snare=38, hihat=42, hihat_open=46, ride=51, crash=49, tom1=48, tom2=45, tom3=43`, etc. This is the standard Rock Band drum MIDI assignment and is **correct as-is** — do **NOT** apply the 0–4 lane remap to the RB `.mid`, or the Rock Band chart breaks. Guitar/bass in the RB `.mid` are offset by difficulty base (60/72/84/96) + lane (see below).
- **Clone Hero `.chart` — lane-addressed for drums.** Drums must be `0–4` (kick/red/blue/green/yellow), so the RB MIDI drum pitch must be **remapped** when serialized to `.chart` (see table below). The `.chart` writer does this via `_rb_drum_midi_to_ch_lane`; it is a `.chart`-only transformation and does not touch the RB `.mid`.

**Shared vital knowledge:** the RB drum MIDI note assignment (`DRUM_LANE_MAP`) is the single source of truth for "which sound = which note" — the RB `.mid` keeps the pitch, and the CH `.chart` derives a lane from it. Both formats must agree on that assignment.

## Clone Hero `.mid` drums: difficulty-offset pitches (the real bug)

This is the one that bites everyone. **Clone Hero's `.mid` drums are NOT Rock Band drum pitches.** CH expects drums in the `.mid` to use the same difficulty-offset scheme as guitar/bass: `note = base + lane`, where the lane is 0–4 (0=kick, 1=red, 2=yellow/hat, 3=blue/tom, 4=green/cymbal) and the **bases are inverted vs guitar/bass**:

| Difficulty | Drums base | Guitar/Bass base |
| :--- | :---: | :---: |
| Easy | 60 | 96 |
| Medium | 72 | 84 |
| Hard | 84 | 72 |
| Expert | 96 | 60 |

So an Expert kick is `96+0 = 96`, Expert green cymbal is `96+4 = 100`; an Easy snare is `60+1 = 61`. Rock Band, by contrast, packs **all** drum difficulties at the real drum MIDI notes (kick=36, snare=38, hat=42, open-hat=46, tom=48, ride=51, crash=49 — see `DRUM_LANE_MAP` in `drum_classifier.py`) with **no difficulty offset**.

**Consequence:** if you hand Clone Hero a `.mid` whose `PART DRUMS` is in RB pitch space (35–59), CH's `midDrumParser` finds no notes in any of the 60/72/84/96 ranges and reports **"no players were loaded. this may be caused by trying to load instruments / difficulties that do not exist in the chart file."** — even though the `.chart` version of the same song loads fine (the `.chart` uses lanes 0–4 directly). AutoRB hit exactly this: the `.chart` worked, the `.mid` didn't, and because CH prefers `notes.mid` when both are present, the whole song failed to show drums.

**The fix (`autorb/export/clone_hero.py :: remap_drums_for_clone_hero`):** after `generate_vocal_midi` writes the RB-format `notes.mid`, rewrite `PART DRUMS` from RB pitches (35–59) to CH difficulty-offset (60/72/84/96 + lane), emitting every RB hit into all four CH difficulties (RB doesn't differentiate drum difficulty in the packed MIDI). `_rb_drum_pitch_to_ch_lane` maps each RB drum note to a CH lane 0–4 (kick→0, snare→1, hat→2, tom→3, cymbal→4). The RB CON `.mid` is generated separately and must keep the real 35–59 notes — do **not** run this remap on it.

> **Verification:** a minimal `PART DRUMS` `.mid` with notes at 36/38/42/46 (RB pitches) fails in CH; the identical chart with notes at 96–100 (CH Expert offset) loads and renders gameplay. Captured headlessly via `tools/ch_capture.sh`.

**Rescan:** Clone Hero caches nothing problematic for the headless `-p` capture (each launch re-parses the `--song` folder), but the in-game **Scan Songs** menu option must be used whenever you replace a song's files in a normal CH install — a stale scan is why manually-added songs sometimes show old/broken charts.


## The single most common breakage: drum lanes

Clone Hero's `.chart` drum notes are written as `tick = N <lane> <sustain>` where **`<lane>` is 0–4**, NOT a MIDI pitch:

| Lane | Drum element | RB MIDI notes that map to it |
| :--: | :--- | :--- |
| 0 | Kick (red) | 35, 36 |
| 1 | Snare / red (side-stick, rim) | 37, 38, 39, 40 |
| 2 | Blue (closed/open hat) | 42, 44, 46 |
| 3 | Green (toms) | 41, 43, 45, 47, 48, 50 |
| 4 | Yellow (crash / ride / cymbal) | 49, 51, 52, 53, 54, 55, 56, 57, 58, 59 |

The packed RB3 MIDI `PART DRUMS` track carries the **real** drum MIDI notes (36 kick, 38 snare, 46 open-hat, 48 tom, …). If those pitches are written straight into the `.chart` (`N 46`, `N 36`), Clone Hero sees lane 36/46/48 — **invalid** — and **rejects the entire drum chart**: the song either fails to scan or, when you select `-p Drums,Expert` headlessly, it renders an **error screen** and no notes ever appear. This was the bug fixed in v0.0.93 (`autorb/export/clone_hero.py :: _rb_drum_midi_to_ch_lane`).

**Rule:** always remap RB drum MIDI note → CH lane 0–4. Unmapped notes default to lane 1 (red) so they still show. Drum sustains must be **0** — drums are percussive hits; a non-zero sustain implies a CH roll the transcription never intended.

## Per-instrument lane decoding (from the packed MIDI)

The RB3 MIDI packs 4 difficulties into one track per instrument using a pitch-offset scheme. The `.chart` writer (`midi_to_chart_file`) must decode packed pitch → (difficulty, lane):

- **Guitar / Bass** — pitch base per difficulty: **Expert 60, Hard 72, Medium 84, Easy 96**. Lane = `pitch - base` (0=Green … 4=Orange). Note: open string is pitch **67** for all difficulties (it sits *below* the lane-0 base of every difficulty, so it is recovered specially). This path is correct and shows the reduced per-difficulty note counts.
- **Drums** — all difficulties share the **same** RB MIDI pitch range (35–59), because drum lanes are pitch-addressed. Difficulty is **not** recoverable from pitch, so every note is emitted into **all four** `[EasyDrums]…[ExpertDrums]` sections (identical counts — a structural limitation of single-track packing, not a true reduction). Each note's pitch is remapped 35–59 → lane 0–4 (above).
- **Keys** — piano-roll pitch (base 36 = C2, lane 0..24). Also shared across difficulties, so emitted to all four sections at its true pitch. **Clone Hero has no keyboard instrument** — the `[*Keys]` sections are tolerated (the loader ignores them) but never rendered. Safe to keep; do not try to "fix" them into lanes.
- **Vocals** — written as `tick = N <pitch> <sustain>` on `[EasyVocals]…[ExpertVocals]` using the **actual MIDI pitch** (e.g. 60–84). CH vocals expect the real pitch, so this is correct as-is. Lyrics ride as `[Events]` `phrase_start`/`phrase_end`/`lyric <text>` exactly as Moonscraper writes them.

## Other `.chart` load rules (gotchas)

- **Tempo must be integer BPM.** Moonscraper/CH parse the `B` field with `uint.TryParse` and **silently drop any fractional value** → no tempo map → song invisible in CH. AutoRB emits integer plain-BPM with drift compensation (`BPM_DRIFT_TOL_S = 0.020`) so the `.chart` stays within ~35 ms of the exact MIDI tempo. The `notes.mid` keeps the exact tempo; the `.chart` is the playtest copy only.
- **`[Song]` metadata** (`Name =`, `Artist =`, …) are valid `.chart` syntax — a strict validator may false-positive on them; they are not parse errors.
- **Song folder** must contain `notes.chart` *and/or* `notes.mid` + `song.ogg` + `song.ini` (name/artist minimum). CH accepts either chart file; shipping both maximizes loadability.

## Verify a part actually loads (headless capture)

`tools/ch_capture.sh --song <abs folder> --instrument drums --difficulty expert --at 20 --out shot.png` boots Clone Hero under box64 + Xvfb + PulseAudio, jumps into gameplay on the requested part, waits, and screenshots one frame. This is the definitive "did this part load?" check — if the frame is an error screen, the section's lane values are wrong (see drum table above). See `[[clone_hero_headless]]` and `[[local_preview_and_testing]]`.

## Outstanding charting gaps (see also)

- Drum/Keys difficulties are **not** differentiated in the packed MIDI or the `.chart` (pitch-ambiguous). Easy/Medium/Hard == Expert.
- Difficulty reduction overall is density-cap heuristic, **not** RB-authoring (cascade / HOPO→strum / sustain pull-back) — see `[[difficulty_charting]]`.
- Instrument note accuracy needs playtest tuning (CREPE/madmom not installed on arm64 → weak pyin fallback). See `[[instrument_charting]]`.
