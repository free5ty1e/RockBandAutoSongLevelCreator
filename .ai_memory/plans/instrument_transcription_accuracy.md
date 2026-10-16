# Plan: Instrument Transcription Accuracy & Validation

**Status:** Proposed (v0.0.98 caveat → roadmap)
**Owner:** AutoRB
**Depends on:** `autorb/transcribe/instruments/*`, `autorb/export/midi_generator.py`

## Context

v0.0.98 made instrument charts *representative* in two ways that were previously
broken: (1) **chords** now render as multiple simultaneous lanes via
`detect_chord_tones()` (CQT salience + harmonic rejection), and (2) **density**
was restored by dropping the monophonic CREPE `conf > 0.5` gate that was
discarding ~90% of onsets. The MIDI writer was also fixed so simultaneous notes
stay simultaneous.

What is **NOT** yet validated is *correctness* — the user's first PS4/Clone Hero
playtest (v0.0.98) confirmed "this pipeline is actually attempting to represent
the tracks," but flagged accuracy gaps:

- Guitar rapid re-strums collapse into a single strum (intro especially).
- Bass separate notes merge into one super-long hold.
- Drum Expert looks sporadic / possibly unplayable; no usable Hard/Med/Easy.

Those are tracked in dedicated plans (see `guitar_bass_articulation_fixes.md`,
`drum_difficulty_derivation.md`). This document covers the **cross-cutting**
accuracy work that remains after those targeted fixes, plus the **validation
harness** needed to stop shipping un-playtested charts.

## v0.0.99 playtest findings (new)

- **Double bass in Expert drums is non-compliant.** User: "there are a lot of
  double bass pedal hits which is not really normally part of the rock band
  allowed patterns." Rock Band does **not** support fully-authored double bass
  (see `[[difficulty_charting]]` §2.1) — Expert must use **single-foot kick
  patterns**. The rapid alternating kicks in our Expert chart come from
  (a) bass-guitar low-end bleeding into the kick band and (b) the per-band energy
  classifier over-triggering kick. **Fix:** after Expert assembly, run a
  single-foot kick reducer — merge any kick burst faster than one foot can play
  into a single-foot pattern (keep the dominant kick grid; optionally emit a
  parallel `PART DRUMS_2X` chart for the full kicks). This is an **Expert
  authoring** fix, paired with tightening kick classification (don't classify
  low bass energy as kick).
- **Clone Hero flattens drum difficulty (rendering bug).** The user "saw no
  difference on Medium" — but the packed MIDI *does* carry distinct per-difficulty
  drums. `remap_drums_for_clone_hero` (`autorb/export/clone_hero.py`) copies
  every hit into all four CH difficulty sections. **Fix:** write the *actual
  reduced* drums to each CH section (Clone Hero supports per-difficulty drum
  charts). Until fixed, playtest drum difficulty on PS4 or by parsing the packed
  MIDI, not Clone Hero.
- **Grid quantization is partially in:** drums are 1/8-gridded in the reducer;
  guitar/bass are **not** quantized before writing (onsets are raw spectral-flux
  peaks). The "rhythm alignment" gap (item 3 below) remains for guitar/bass.

## Remaining accuracy gaps (cross-cutting)

1. **Pitch / fret accuracy.** `pitch_to_fret_string` + `fret_string_to_lane`
   map a detected Hz to a 5-lane note, but the CQT peak-picking in
   `detect_chord_tones` uses first-pass thresholds (salience 0.25, harmonic
   tolerance 8 Hz, `top_k=4`). Wrong fundamentals → wrong lanes and wrong
   chord voicings. No per-note validation against the audio yet.
2. **Strum vs HOPO.** `is_hopo` is decided by a fragile same-direction +
   adjacent-lane heuristic (`guitar.py` HOPO pass). Real RB authoring derives
   HOPO from note spacing vs the beat grid and previous note; mislabeled HOPOs
   make a chart feel wrong even when the notes are right.
3. **Rhythm / timing alignment.** Onsets come from spectral-flux peak-picking
   (`backtrack=True`) and are **not quantized** to the beat grid before being
   written. Notes can sit off-grid, which is doubly bad because RB snaps
   gameplay to the grid — off-grid notes feel early/late and can merge visually
   with neighbours.
4. **Sustain correctness.** Over/under-long sustains from `detect_holds`
   (guitar) / `detect_holds_bass` (bass) — see `guitar_bass_articulation_fixes.md`.

## Proposed approach

### A. Beat-grid quantization pass (fixes rhythm alignment)
Add a `quantize_to_grid(notes, tempo_map)` step (the `DifficultyReducer` already
has a stub `_quantize_to_grid`) applied **once**, right after expert-note
assembly, before difficulty reduction. Resolution: 1/16 (or 1/12 for swing) at
the local BPM from `tempo_map`. Keep an *unquantized* copy for the overlap/sustain
math. Quantizing also makes the HOPO and chord logic grid-aware.

### B. Per-note pitch validation
After `detect_chord_tones`, re-check each chosen tone against a fine CREPE/pyin
frame at that time; drop/replace tones whose pitch disagrees > 2 semitones with
both the CQT peak and the local salience peak. This rejects residual harmonic
errors cheaply (CREPE is already loaded for the `other` stem).

### C. Grid-aware HOPO derivation
Replace the adjacent-lane heuristic with: a note is a HOPO iff it is within
~1.5× the 1/16-grid spacing of the previous note, is not on the same lane, and
the previous note was a strum OR a HOPO in the same direction (standard RB
"hammer-on chain" rule). Chord members are never HOPOs.

### D. Validation / playtest harness (the missing gate)
Today "no regressions" = unit tests pass. We need a **chart-quality gate**:
- **Clone Hero headless capture** (`tools/ch_capture.sh`) already renders a
  frame per instrument/difficulty; extend it to (a) dump the note list
  (`notes.mid` parsed → per-difficulty note count, chord count, max-simul,
  on-grid %), and (b) assert sanity (Expert ≥ Hard ≥ Medium ≥ Easy note counts;
  Hard/Med/Easy are *distinct* from Expert for drums/guitar/bass).
- A **reference-song scorecard**: for 2–3 known songs, store expected
  note-count bands and chord ratios; CI fails if a change moves Expert drum
  count outside the band (catches the "all difficulties identical" regression).
- Keep the existing `alignment_report.json` (vocal) and add an
  `instrument_report.json` (per-instrument: notes, chords, density, on-grid %,
  hold-length histogram).

## Validation
- Unit: `test_midi_structure.py` extended with grid-quantization and HOPO
  assertions; a new `test_instrument_quality.py` for the scorecard gate.
- Integration: run the full pipeline on `eve6-openRoadSong` + `barenakedLadies-
  brianWilson`; confirm Expert ≥ Hard ≥ Medium ≥ Easy for every instrument and
  that chord counts are non-zero and on-grid % ≥ ~90%.
- Playtest: user confirms on PS4/Clone Hero that strums are distinct, bass
  holds match audio, drums are playable per difficulty.

## Files to touch
- `autorb/transcribe/instruments/guitar.py`, `bass.py`, `keys.py` (quantize,
  HOPO, pitch re-check)
- `autorb/transcribe/instruments/difficulty.py` (`_quantize_to_grid` wired in)
- `autorb/export/midi_generator.py` (no change beyond current simultaneous fix)
- `tools/ch_capture.sh` + new `autorb/testing/chart_report.py`
- `tests/test_instrument_quality.py` (new)

## Non-goals (this plan)
- Real per-instrument ML transcription models (Basic-Pitch v2, etc.) — out of
  scope; we improve the signal-processing pipeline that already exists.
- Perfect music-theory authoring (cascades, phrasing) — tracked elsewhere.
