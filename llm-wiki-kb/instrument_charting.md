# AutoRB Knowledge Base - Instrument Charting

How AutoRB turns separated stems into playable 5-lane instrument charts (guitar, bass, drums, keys) and how those charts are serialized to MIDI and to the Clone Hero `.chart` format. Captured at **v0.0.92** (first alpha with *real*, non-placeholder instrument charts).

## Overview (v0.0.92)

Before v0.0.92, `PART GUITAR/BASS/DRUMS/KEYS` were single-note placeholders so ForgeTool's CON→PKG conversion wouldn't `NullReferenceException`. v0.0.92 replaces them with charts produced by the `autorb/transcribe/instruments/` package:

- **Onset detection** (multi-band librosa; optional madmom for drums, optional CREPE for pitch)
- **Pitch → lane mapping** (tuning/capo detection, fret→5-lane)
- **Spectral drum-element classification** (kick/snare/hihat/tom/crash/ride)
- **Progressive per-difficulty reduction** (Expert → Hard → Medium → Easy)

Keys reuses the guitar transcription because Demucs' `other` stem is guitar+keys inseparable (see `[[architecture]]`).

## Pipeline flow

```
stems/{drums,bass,other}.wav
   └─ transcribe_drums / transcribe_bass / transcribe_guitar / transcribe_keys
         └─ InstrumentChart(expert)   # autorb/transcribe/instruments/difficulty.py
               └─ create_all_difficulties(expert_chart, instrument)
                     └─ dict[Difficulty, InstrumentChart]   # EXPERT/HARD/MEDIUM/EASY
                           └─ build_instrument_track(...)   # autorb/export/midi_generator.py
                                 └─ one MIDI track per instrument (all 4 difficulties packed)
```

`build_all_instrument_tracks()` (midi_generator) calls each transcriber, runs `create_all_difficulties`, then `build_instrument_track` to merge all 4 difficulties into one MIDI track using a pitch-offset scheme (below). `generate_vocal_midi()` also takes `keys_charts` + `freestyle_drums` so Keys rides alongside vocals and `--freestyle-drums` collapses the drum track to a single placeholder note.

## MIDI pitch encoding (the load-bearing detail)

`build_instrument_track` packs all four difficulties into **one** MIDI track per instrument. The difficulty is encoded in the **pitch**:

- **Guitar / Bass** — pitch offset per difficulty (`autorb/transcribe/instruments/pitch_to_lane.py` `LANE_BASE`):
  - Expert base **60**, Hard **72**, Medium **84**, Easy **96**.
  - A note in lane `L` (0=Green … 4=Orange) is written at `base + L`. Open string is pitch **67** for all difficulties.
  - ⇒ Difficulty is recoverable from pitch: `60≤p<65`→Expert, `72≤p<77`→Hard, `84≤p<89`→Medium, `96≤p<101`→Easy.
- **Drums** — `pitch = note.difficulty_pitch` (the drum's **fixed** MIDI pitch, e.g. kick=36, snare=38, hihat=42, open-hihat=46, tom=48, crash=49, ride=51). **All difficulties share the same pitch range** (36–51) because Rock Band / Clone Hero drum lanes are pitch-addressed, not offset by difficulty.
- **Keys** — `pitch = KEYS_BASE_PITCH + lane` where `KEYS_BASE_PITCH = 36` (C2) and lane ∈ 0..24 (2-octave piano roll C2..C4). **All difficulties share 36–60** because the actual key pitch is musically meaningful and cannot be offset per difficulty.

**Consequence:** guitar/bass difficulties are recoverable from the packed MIDI; **drum and keys difficulties are NOT** — they overlap in pitch. This is a structural limitation of the single-track packing and drives the `.chart` writer behavior below.

## Clone Hero `.chart` writer (`autorb/export/clone_hero.py :: midi_to_chart_file`)

The RB3 MIDI packs 4 difficulties per track; the `.chart` format wants one `[<Difficulty><Instrument>]` section per difficulty. The writer must map packed-MIDI pitches back to (difficulty, lane):

- **Guitar / Bass** — split by pitch base (above). Each note goes to its own difficulty section; lane = `pitch - base`. This is the **correct** path and shows the reduced note counts per difficulty.
- **Drums / Keys** — since difficulty is not recoverable from pitch, every note is emitted into **all four** difficulty sections. The Clone Hero **`.chart`** splits drums by the CH drum base (Easy 60 / Medium 72 / Hard 84 / Expert 96; inverted vs guitar), lane = `pitch − base`; the underlying RB drum note (35–59) → CH lane 0–4 mapping is `_rb_drum_pitch_to_ch_lane` (`0=kick, 1=red(snare), 2=yellow(hat), 3=blue(tom), 4=green(cymbal)`). The Clone Hero **`.mid`** is rewritten by `remap_drums_for_clone_hero` from RB pitches (35–59) into the same difficulty-offset scheme (60/72/84/96 + lane) — see `[[charting_basics]]`. **Keys writes its true pitch and is ignored by CH** (Clone Hero has no keyboard instrument). So `notes.chart`/`notes.mid` show identical drum/keys counts in Expert/Hard/Medium/Easy (faithful to the packed MIDI, not a true per-difficulty reduction).

### v0.0.92 bugs fixed in the writer
1. **Keys omitted entirely** — only `PART GUITAR/BASS/DRUMS` were handled. Added `PART KEYS` → `[ExpertKeys]…[EasyKeys]` sections.
2. **Guitar/Bass duplicated into every difficulty** — the old code did `instruments[inst] = [(tick, pitch % 12, sustain) for …]` then wrote that *same list* into each `[<diff><inst>]` block, so Expert Guitar notes also appeared in Hard/Medium/Easy (and `pitch % 12` was wrong for drums). Now per-difficulty lists are built (guitar/bass split by base; drums/keys emitted to all).
3. **Drums wrote the raw RB MIDI pitch** (e.g. `N 36`/`N 46`/`N 48`) instead of a Clone Hero **lane** (0–4). CH's drum lanes are *not* MIDI pitches; lane 36/46/48 is invalid, so CH rejected the entire drum chart (the headless `-p Drums,Expert` capture rendered an **error screen** and drums never appeared in the song list / gameplay). Fixed: drums now map RB MIDI note → CH lane 0–4 via `_rb_drum_midi_to_ch_lane`; drum sustains are forced to 0 (percussive hits — CH rolls would otherwise be implied by the transcription's accidental sustains). Keys still writes true pitch but CH ignores the section.

`midi_to_chart_file` reads the same notes.mid that goes into the CON, so the chart and RB3 chart stay self-consistent (no count-in in the CH export — ticks == audio time, per `[[local_preview_and_testing]]`).

## Difficulty reduction engine (`difficulty.py :: DifficultyReducer`)

`create_all_difficulties(expert, instrument)` applies `DifficultyReducer` **progressively** (Expert→Hard→Medium→Easy) with per-difficulty density caps (notes/sec): Expert 16, Hard 14, Medium 10, Easy 6. `_thin_notes` slides a 1s window and drops the least-important notes (protected = HOPO/chord/hold/solo/BRE/fill) where density exceeds the cap.

Per-instrument rules implemented:
- **Hard**: ~20–30% thinning, keep HOPOs/chords/holds/solos/BRE.
- **Medium**: HOPOs→strums, drop orange lane (lane 4) for guitar/bass, ride/crash→hihat for drums, cap 10/sec.
- **Easy**: single notes only, no blue/orange, no chords/HOPOs/solos/BRE for guitar/bass; kick/snare/hat only for drums, cap 6/sec.

**Known limitation (critical, v0.0.92):** the reducer is heuristic (density caps + lane drops), **NOT** a Rock Band-authoring pass. The actual RB rules for deriving difficulties from Expert — cascade, lane consistency, HOPO→strum on Medium/Easy, sustain pull-back, per-difficulty chord restrictions — are documented in `[[difficulty_charting]]` and are **not yet implemented**. The packed-MIDI encoding (above) also means drum/keys reductions are lost when serialized to a single track / `.chart`. This is the single biggest gap between AutoRB's instrument charts and playable, RB-correct charts.

### Guitar vs Keys note-count mismatch (v0.0.92)
Guitar and Keys both transcribe the same Demucs `other` stem, so they should represent the **same note events** (keys = actual pitches, guitar = those pitches mapped to frets/lanes). They currently diverge because `transcribe_guitar` and `transcribe_keys` run **separate** pitch-detection passes with different `fmin/fmax` (guitar pyin 80–1200 Hz, keys pyin 65–600 Hz) and guitar additionally filters through tuning/fret mapping (`build_lane_map`) that drops notes. Result: e.g. ~102 guitar vs ~87 keys notes on the test song. Fix: share one onset+pitch-detection result, then map to both lane (guitar) and piano-roll (keys). Low absolute counts on this env are mostly because **`crepe` is not installed** (see Transcription backends) — both fall back to weak librosa pyin on the polyphonic `other` stem.

## Transcription backends & why guitar/bass look sparse here

Each transcriber tries a high-quality backend and falls back to librosa:
- **Pitch:** `crepe` (CNN, preferred) → `librosa.pyin` fallback. On the devcontainer/arm64 env **crepe is NOT installed**, so guitar/bass fall back to pyin, which is weak on polyphonic `other` stem audio → far fewer/lower-confidence notes (e.g. Expert Bass came out ~4 notes, Expert Guitar ~27 on the test song). Installing `crepe` (and `madmom` for drums) restores density. `madmom` is also optional; drums fell back to librosa onsets until the onset-strength fix (see `[[log]]`).
- **Onsets:** `madmom` for drums → `librosa` fallback. `detect_onsets_librosa` with `backtrack=True` made `onset_env[onset_frames]` ≈ 0 for most onsets, so the strength filter dropped ~472/479 drum onsets. Fixed by computing strength from the envelope **peak in a forward window** after each onset, normalized by the 95th percentile → ~472 Expert drum notes (1888 across difficulties).

## Known limitations (instrument charts, v0.0.92)

- **Not yet playtest-validated.** Charts are loadable and no longer crash ForgeTool, but note accuracy, HOPO/chord/sustain decisions, and drum-lane assignment need playtest tuning.
- **Drum/Keys difficulty not differentiated** in the packed MIDI or `.chart` (pitch-ambiguous; CH needs fixed drum pitches). Easy/Medium/Hard drums == Expert in the exported chart.
- **Clone Hero does not support Keys** — `[*Keys]` sections are emitted but ignored by CH; validate keys only in RB3/RB4.
- **Guitar/Bass sparseness without CREPE** (librosa pyin fallback). Install `crepe` for production density.
- **Guitar + Keys share the Demucs `other` stem**, so keys transcription is a re-map of the guitar onsets, not a separate keys source.
