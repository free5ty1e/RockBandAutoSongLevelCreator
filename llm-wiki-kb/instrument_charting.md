# AutoRB Knowledge Base - Instrument Charting

How AutoRB turns separated stems into playable 5-lane instrument charts (guitar, bass, drums, keys) and how those charts are serialized to MIDI and to the Clone Hero `.chart` format. Captured at **v0.0.92** (first alpha with *real*, non-placeholder instrument charts); drum element classification + fill detection reworked in **v0.0.94**; chord (multi-pitch) transcription + simultaneous-note MIDI fix in **v0.0.98**.

## Overview (v0.0.92, drum logic reworked in v0.0.94)

Before v0.0.92, `PART GUITAR/BASS/DRUMS/KEYS` were single-note placeholders so ForgeTool's CON→PKG conversion wouldn't `NullReferenceException`. v0.0.92 replaces them with charts produced by the `autorb/transcribe/instruments/` package:

- **Onset detection** (multi-band librosa; optional madmom for drums, optional CREPE for pitch)
- **Pitch → lane mapping** (tuning/capo detection, fret→5-lane)
- **Drum-element classification** — v0.0.92 used a spectral-score heuristic (kick/snare/hihat/tom/crash/ride) whose normalization dropped the low-mid/sub bands and inflated kick/tom so almost every hit collapsed to kick or tom (the "4 toms then 4 bass drums" unplayable track). v0.0.94 replaced it with `classify_drum_onsets_energy()` (per-band RMS energy ratios measured on band-passed signals: kick 30–110 Hz, body 110–350 Hz, hat 7–14 kHz, cymbal 3–9 kHz; cymbals default to ride unless the high band dominates → crash). Verified on the Open Road Song `drums.wav` (291s): 796 notes, kick 243 / snare 95 / hi-hat 181 / ride 229 / crash 31.
- **Progressive per-difficulty reduction** (Expert → Hard → Medium → Easy)

### v0.0.94 drum fill fix
Old `detect_fills` flagged any 3 hits in a 500 ms window with 2 lanes as a fill → ~188 false fills (each an overdrive phrase) on a 5-minute song. New version is adaptive: threshold = song's groove baseline (median hits-per-window) × 1.3, must span ≥2 distinct lanes. Same song → **7** fills (realistic). `transcribe_drums` also now merges full-signal onsets with dedicated high-band onset detection (hat 7–14 kHz, cymbal 3–9 kHz) so quiet hi-hats/cymbals attenuated by stem separation are not missed.

### v0.0.95 guitar transcription crash fix
`pitch_to_fret_string` (`pitch_to_lane.py`) returned `None` for any detected pitch outside every string's 0–22 fret range (triggered after capo detection shifted pitches, or for extreme/low transients). `build_lane_map` then dereferenced `fret_pos.fret` and raised `'NoneType' object has no attribute 'fret'`, aborting the whole instrument step. The function now never returns `None` — out-of-range pitches clamp to the nearest string's open (fret 0) or top (fret 22), and degenerate (≤0) pitches fall back to the lowest open string; the capo shift is also clamped to 0–12. Regression test: `tests/test_pitch_to_lane.py`.

Keys reuses the guitar transcription because Demucs' `other` stem is guitar+keys inseparable (see `[[architecture]]`).

### v0.0.98 chord (multi-pitch) transcription + MIDI writer fix
Before v0.0.98 the transcription was **monophonic**: one CREPE f0 per onset, and a chord strum yields a single spectral-flux onset, so every chord collapsed to one note. Worse, the flow gated every note on a monophonic CREPE confidence `> 0.5`, discarding ~90% of onsets — so intros looked empty and (because Rock Band gates an instrument's stem audio on its chart) the guitar stayed silent until a high-confidence onset.

- Added `detect_chord_tones()` (`guitar.py`): for each onset, a CQT salience column (±30 ms) is peak-picked and **harmonic-rejected** (a peak whose freq is ≈½/⅓/2×/3× another chosen peak is dropped) so overtones don't become false "chord tones". Up to `top_k=4` simultaneous tones per onset → multiple lanes.
- `transcribe_guitar` / `transcribe_keys` now keep the dense onset backbone (strength-gated, **not** CREPE-conf-gated) and expand each onset into its chord tones; `tuning`/`capo` come from the full tone set. The legacy per-onset helpers (`detect_chords`/`detect_holds`/`detect_solo`/`detect_bre`) still run on each onset's primary tone. Keys quantizes the detected 2-octave pitch into 5 lanes (a true 25-key piano roll crashes `con2pkg`).
- **MIDI writer bug fixed:** `build_instrument_track` advanced `last_tick` by each note's *duration*, so a chord's 2nd+ notes landed *after* the previous note ended (never simultaneous). Rewritten as a flat, time-sorted note-on/note-off list (on before off at the same tick) so chords are truly simultaneous. Regression test: `tests/test_midi_structure.py::test_simultaneous_notes_stay_simultaneous`.
- Verified on "Open Road Song": guitar Expert went 150 monophonic → **257 with 154 chord-onsets**; keys 243 with 150 chord-onsets. PKG still builds.

**Known limitation (still alpha):** chord *presence* and note *density* are now representative, but pitch/fret accuracy, strum-vs-HOPO, and rhythm alignment are unplaytest-validated and may need tuning (the CQT threshold / harmonic-rejection are first-pass). Drums remain the weakest.

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

`build_instrument_track` packs all four difficulties into **one** MIDI track per instrument. The difficulty is encoded in the **pitch** using the Rock Band / ForgeTool packed-MIDI convention (this is mandatory: `tools/libforge/LibForge/LibForge/Midi/RBMidConverter.cs` `HandleDrumTrk`/`HandleGuitarBass` only accept `base + lane` for **every** instrument — raw 35–59 drum sound pitches or true key pitches are rejected and leave the difficulty gem-track null, crashing PKG conversion with a `NullReferenceException`):

- **Difficulty bases (all instruments):** Easy **60**, Medium **72**, Hard **84**, Expert **96**. A note in lane `L` (0–4) is written at `base + L`. ⇒ Recoverable from pitch: `60≤p<65`→Easy, `72≤p<77`→Medium, `84≤p<89`→Hard, `96≤p<101`→Expert.
- **Guitar / Bass** — `pitch = base + lane`. Rock Band 5-button guitar/bass charts have **no "open" notes**, so an open-string hit is encoded as a normal `base + lane` strum (the old `OPEN_PITCH = 67` encoding put it outside the 60–100 ranges and ForgeTool dropped it — fixed in v0.0.97).
- **Drums** — `pitch = base + lane` where lane is the 0–4 drum pad lane (kick=0, snare=1, hat/tom=2, tom=3, cymbal=4). The raw drum sound pitches (36–51) are **NOT** written. ForgeTool's `HandleDrumTrk` only accepts `base + lane`; writing 36–51 made every difficulty gem-track null → `NullReferenceException` in `GemTracks.Add`.
- **Keys** — `pitch = base + lane` (5-lane, reused from the guitar transcription). Keys is handled by `HandleGuitarBass` in ForgeTool, so it must use the same difficulty-offset scheme; the true piano pitch is not carried in the CON MIDI.

**Consequence:** every instrument's difficulty IS recoverable from the packed MIDI pitch (four distinct `60–100` ranges). That is what makes the CON loadable by ForgeTool and the PS4 PKG build succeed. (Historical note: earlier versions wrote drums at 35–59 and keys at 36–60 under the mistaken belief that "RB keeps real pitches"; that assumption was wrong for ForgeTool and broke PKG conversion — see v0.0.96.)

## Clone Hero `.chart` writer (`autorb/export/clone_hero.py :: midi_to_chart_file`)

The RB3 MIDI packs 4 difficulties per track; the `.chart` format wants one `[<Difficulty><Instrument>]` section per difficulty. The writer must map packed-MIDI pitches back to (difficulty, lane):

- **Guitar / Bass** — split by pitch base (above). Each note goes to its own difficulty section; lane = `pitch - base`. This is the **correct** path and shows the reduced note counts per difficulty.
- **Drums / Keys** — the CON `PART DRUMS` is already in the difficulty-offset scheme (Easy 60 / Medium 72 / Hard 84 / Expert 96 + lane 0–4), so the writer splits by that base, lane = `pitch − base`. `remap_drums_for_clone_hero` then re-emits every hit into **all four** Clone Hero difficulty sections (CH needs each hit present in every difficulty to build a drums player); the lane→pad mapping is `_rb_drum_pitch_to_ch_lane` (`0=kick, 1=red(snare), 2=yellow(hat), 3=blue(tom), 4=green(cymbal)`). **Keys is ignored by CH** (Clone Hero has no keyboard instrument) so its notes are copied through harmlessly. Hence `notes.chart`/`notes.mid` show identical drum/keys counts in Expert/Hard/Medium/Easy (faithful to the packed MIDI, not a true per-difficulty reduction).

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
- **Guitar/Bass sparseness (largely fixed in v0.0.98).** The old CREPE-confidence gate dropped ~90% of onsets; v0.0.98 recovers density via a dense onset backbone + per-onset multi-pitch, so chord *presence* and note *count* are now representative even without CREPE. Remaining gap is pitch/fret **accuracy** and rhythm alignment, not raw count.
- **Guitar + Keys share the Demucs `other` stem**, so keys transcription is a re-map of the guitar onsets, not a separate keys source.
