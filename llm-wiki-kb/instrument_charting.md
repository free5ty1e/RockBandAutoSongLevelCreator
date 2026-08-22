# AutoRB Knowledge Base - Instrument Charting

How AutoRB turns separated stems into playable 5-lane instrument charts (guitar, bass, drums, keys) and how those charts are serialized to MIDI and to the Clone Hero `.chart` format. Captured at **v0.0.92** (first alpha with *real*, non-placeholder instrument charts); drum element classification + fill detection reworked in **v0.0.94**; chord (multi-pitch) transcription + simultaneous-note MIDI fix in **v0.0.98**; bass-merge / guitar-chord-overdetection / drum-difficulty fixes in **v0.0.99**; Clone Hero drum-flattening fix + Expert double-bass reducer in **v0.1.0** (difficulty-derivation rules documented in `[[difficulty_charting]]`); difficulty-derivation rewrite in **v0.1.1**; illegal same-lane-overlap fix in **v0.1.2**; drum onset fix + guitar over-charting reduction + bass frequency filter in **v0.1.3**; **v0.1.4** massive guitar chord cleanup + drum balance + bass hold extension; **v0.1.5** intro drums from the mixed audio + classifier hierarchy fix (measured on the WRONG audio — superseded, see below); **v0.1.6** correct test track + ADTOF neural drums + RBN drum difficulty rules + guitar chord reconstruction; **v0.1.7** tom lane assignment fixed (pitch + ring-energy split; fills hit Green/Blue pads, hi-hat lane depacked).

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

### v0.0.99 — bass merges, guitar chord over-detection, drum difficulty derivation
Three playback fixes driven by PS4/Clone Hero playtest feedback (see `[[instrument_transcription_accuracy]]` and the `.ai_memory/plans/*` docs):

- **Bass: separate notes no longer merge into one super-long hold.** The `> 0.4` confidence gate dropped low-confidence bass attacks, so the next *detected* onset could be seconds away and the previous note's sustain stretched across the gap. Fixed by lowering the gate to `> 0.1`, lowering onset `wait` to 3 (separate rapid attacks now register as separate onsets), and capping every hold to the next onset (`detect_holds_bass`). On "Open Road Song": bass 131 notes / max hold 6.0 s (many merged) → 227 notes / max hold 3.8 s, only 4 holds > 1.5 s.
- **Guitar: chords are now real 2–3 note voicings, not 4-note over-detection, and sustains survive without blending.** `detect_chord_tones` was catching spectral leakage (±1 semitone around the fundamental) and weak overtones — 96 % of onsets became "chords" and 60 % carried 4 tones, ballooning the chart to 1281 notes. Tightened: salience threshold raised to 0.5 of the column peak, tones within ~1.5 semitones of an already-chosen one rejected (leakage), 4th/5th-harmonic rejection added, `top_k` lowered 4→3. Sustains were previously dropped entirely (holder required ≥1.0 s); minimum lowered to 0.3 s with the next-onset cap retained, so held chords ring and two rapid strums stay two notes. Result: 1281 → 859 notes (67 % chords, 4.1 notes/sec) with 510 capped sustains preserved.
- **Drums: Hard/Medium/Easy are now distinct, on-grid, playable charts.** The old reducer only thinned by note density (caps 6–16/sec); drum density (~2.9/sec) was below every cap, so Hard/Medium/Easy came out byte-identical to Expert (~612 each) — useless on a real PS4 kit. `DifficultyReducer` now does role/lane-based reduction (`_drum_reduce` in `difficulty.py`): Hard drops cymbals (lane 4) and grid-quantizes to 1/8; Medium additionally drops toms (lane 3); Easy keeps kick/snare/hat and halves the kick count. Verified: Expert 800 → Hard 768 → Medium 543 → Easy 421, strictly decreasing and lane-distinct. Regression test: `tests/test_midi_structure.py::test_drum_difficulties_are_distinct_and_decreasing`.

See the detailed plans in `.ai_memory/plans/instrument_transcription_accuracy.md`, `.ai_memory/plans/guitar_bass_articulation_fixes.md`, and `.ai_memory/plans/drum_difficulty_derivation.md`.

### v0.1.3 — Drum onset fix + Guitar over-charting reduction + Bass frequency filter

Three major playability fixes driven by PS4/Clone Hero playtest feedback:

1. **Drums: First 54 seconds were missing.** Root cause: `detect_onsets_librosa` used global strength normalization (95th percentile over entire 291s song). Early quiet drum hits had normalized strength ~0.09, below the 0.08 filter threshold, while later loud crashes pushed the 95th percentile to ~1.0. Only 1 onset survived in the first 60s (at 21.7s). **Fix:** Added windowed onset detection (`window_seconds=30.0`) with local 95th-percentile normalization per 30s window. Drums now start at **0.10s**. The librosa fallback is now used (madmom is broken on this platform) with 30s windows and local 95th-percentile normalization. Strength threshold lowered to 0.05 for drums.

2. **Guitar: Massive over-charting (3,435 → 1,829 expert notes).** Basic Pitch on the shared Demucs "other" stem (guitar + keys) detected keys/piano as guitar. **Fixes:** (a) Raised Basic Pitch thresholds (onset 0.4→0.55, frame 0.3→0.45) to reduce noise; (b) Added guitar frequency filter (75–1250 Hz) to reject piano/keys bleed; (c) Tightened chord grouping window (30ms→25ms); (d) Minimum note length 20ms. Result: 47% reduction (3,435→1,829 expert notes). Keys still reuses guitar transcription (known limitation).

3. **Bass: Frequency filter added** (38–420 Hz) matching bass guitar range; guitar filter 75–1250 Hz. Prevents guitar/keys bleed on bass stem and vice versa.

**Verified:** All 4 instruments × 4 difficulties now report **0 same-lane overlaps** in validation MIDI. CON + PS4 PKG build successfully. Regression test added: `tests/test_midi_structure.py::test_instrument_tracks_have_no_same_lane_overlaps`.

### v0.1.2 — illegal same-lane-overlap fix (Rock Band requires non-overlapping gems)

The rewritten difficulty derivation (v0.1.1) produced charts with **overlapping same-lane notes** in the final MIDI — illegal in Rock Band (drops notes / crashes-conversion risk). Two root causes, both fixed:

1. **Cross-group (time, lane) duplicates in guitar/bass/keys.** `_transcribe_fretted` snaps each chord group to the 1/16 grid; two *separate* groups that fall inside one grid cell can land on the same quantized time **and** the same lane. The within-group lane dedup (`seen_lanes`) only catches duplicates *inside* one group, so the cross-group collision slipped through, emitting two notes on one lane at the same instant. Fix: a final `(time, lane)` dedup in `_transcribe_fretted` that keeps the longer-sustain note and repairs stale `chord_notes` references (`autorb/transcribe/instruments/guitar.py`).
2. **Zero-length note floor bleed in `build_instrument_track`.** A `length=0` note was floored at **120 ticks (0.088 s)**, which could exceed the gap to the next same-lane note (the source cap only bounds `length`, not the floor). The sustain duration was also hardcoded with a `120 BPM` conversion (`note.length * 480 * 120/60`) instead of the real tempo map, stretching/compressing every sustain for songs not at exactly 120 BPM. Fixes: derive duration from `time_to_tick(note.time + note.length) − time_to_tick(note.time)` (the real tempo map), and add a generic **per-pitch de-overlap clamp** in `build_instrument_track` guaranteeing no two same-pitch notes overlap (what Rock Band requires anyway). Removed a redundant `max(48, …)` re-floor in the flat builder that was re-inflating clamped tails.

Verified end-to-end on "Open Road Song": all `PART GUITAR` / `PART BASS` / `PART DRUMS` / `PART KEYS` tracks report **0 same-lane overlaps** at every difficulty (Expert/Hard/Medium/Easy) in both the CON-track MIDI and the count-in-free validation MIDI. Regression test: `tests/test_midi_structure.py::test_instrument_tracks_have_no_same_lane_overlaps`. (Lessons: the pipeline was importing a **stale installed wheel** `autorb 0.0.76` at `/home/vscode/.local/lib/python3.11/site-packages` rather than the edited source — fixed with `pip install -e . --no-deps --no-build-isolation`; and a hand-rolled tick→second analyzer over-counted tempo segments and inflated durations ~2.78×, so always analyze MIDI in **ticks**, not seconds.)

### v0.1.4 — Guitar chord cleanup + drum balance + bass holds

Three major playability improvements from extended Clone Hero playtesting:

1. **Guitar: Massive chord cleanup (1,797 → 1,350 expert notes, 52% reduction).** Root cause: Basic Pitch on the shared "other" stem detected chord tones with slight onset variance; chord grouping (45ms window) split single strums across multiple grid cells, and quantization spread same-chord tones across adjacent ticks on the same lane. **Fixes:** CHORD_WINDOW widened to 60ms; 15ms dedup tolerance for (time, lane) collisions; new 10ms post-quantization merge pass merges same-lane notes within 10ms, extending sustain to cover both. Result: busiest lane min gap 9ms → 65ms; expert notes 1,797 → 1,350 (47% reduction). Keys inherits fixes (shared "other" stem).

2. **Drums: Balanced kit (hi-hat restored, toms tamed).** Over-aggressive hi-hat suppression (v0.1.3) left only 3 hits; over-eager tom default created rapid tom runs. **Fixes:** Hi-hat threshold relaxed (0.5→0.35 total energy ratio, 0.85→0.75 dominance ratio); snare threshold raised (0.25→0.28); kick threshold raised (2.0→2.2); "unknown" default replaces tom default. Result: hi-hat 3→52 notes; toms 129→57; snare 629→552 (still high but playable).

3. **Bass: Long holds preserved.** Max hold extended 4s→8s; min note length 30ms. Prevents premature truncation of long bass sustains in verse/outro sections.

**Verified:** All 4 instruments × 4 difficulties = **0 same-lane overlaps** in validation MIDI. CON + PS4 PKG build successfully. Regression test: `tests/test_midi_structure.py::test_instrument_tracks_have_no_same_lane_overlaps`.

### v0.1.5 — Intro drums from the mixed audio + classifier hierarchy fix (SUPERSEDED)

> **Superseded in v0.1.6.** All of this section's measurements were made on the **wrong audio file** (Brian Wilson MP3, not the Eve6 "Open Road Song" test track), and the mixed-audio intro approach itself charted **guitar/bass lows as kicks** on the correct track. v0.1.6 replaced the whole drum pipeline with the **ADTOF neural transcriber** on the drums stem. See the v0.1.6 section below; this section is kept for the librosa-band fallback logic it documents.

Two root-cause fixes that finally make the drum chart start at the true first hit with a sane lane balance:

1. **Intro drums are now transcribed from the original mixed audio, not the silent drums stem.** Demucs routes the first ~60 s of drums into `other.wav`, so `drums.wav` is digitally silent there (full-band RMS 0.0002 vs 0.045 after 60 s; kick band 0.000005). The old pipeline ran windowed onset detection on that silent stem; the windowed local normalization boosted *noise* to onset level, so the "drums at 0.10 s" from v0.1.3 was actually charting noise as hi-hats. `transcribe_drums` now takes `mixed_audio_path` (CLI passes the original audio file) and splits the transcription:
   - **Intro (0–60 s):** band-specific onset detection on the mixed audio — kicks (30–110 Hz), snares (150–350 Hz), hi-hats (7–14 kHz) — with each onset snapped onto the 1/8 beat grid (real rock grooves live on the grid; stray guitar/bass transients rarely align). Onsets >35 % of the grid step away are dropped; simultaneous band hits on one slot become chords. First note now lands at the true ~0.25 s.
   - **Body (≥60 s):** the drums stem (real content there) with the standard windowed onset detection + band-energy classifier.
2. **`classify_drum_onsets_energy` decision hierarchy corrected.** The old order checked the high bands *first* (`max(eh, ec) > 0.15*tot` → hi-hat/ride), so every snare's 3–9 kHz crack fell into the cymbal branch — snare was under-charted (7 notes) while the chart flooded with false rides (282–418 notes). The new hierarchy is **kick (sub-bass dominant) → snare (mid 110–350 Hz dominant over high bands) → hi-hat (7–14 kHz over 3–9 kHz) → crash → ride → unknown**. On "Open Road Song": snare 7→534, ride 418→31, kick 310→469, hi-hat 462→253 (Expert).

Also fixed: **librosa 0.11 mel-filterbank collapse on band-passed signals** in `_band_onsets`. The old helper used `n_mels=64` with `aggregate=np.median` for every band; over a narrow band (e.g. 30–110 Hz) 64 mel bins mostly sit outside the band and the *median* across frequency collapses to ~0, so the kick and hi-hat bands returned zero onsets. `n_mels` is now scaled to the band (`int(clamp(fmax/2000*64, 8, 64))`) and `aggregate=np.mean` is used.

**Verified:** CON rebuilds cleanly end-to-end; all 4 difficulties report **0 same-lane overlaps** in the validation MIDI (Expert 1392 notes: kick 469 / snare 534 / hi-hat 253 / crash 105 / ride 31). Tests: 158 passed, 5 pre-existing vocal failures unchanged.

### v0.1.6 — Correct test track + ADTOF neural drums + RBN drum difficulty + guitar chord reconstruction

1. **Verification moved to the correct test track (critical).** The entire `output/` dataset (291 s stems, tempo, vocals cache, validation MIDI, CON) was discovered to have been built from the **wrong audio file** — the Brian Wilson MP3 (correlation 0.994 with `preview_mix.wav`), while the intended Eve6 test track is 198 s (correlation 0.012). The pipeline was fully regenerated on `input/eve6-openRoadSong.mp3`: stems 198 s, tempo 168.99 BPM avg / 534 beats, 284 aligned words, 407 vocal notes, CON + Clone Hero rebuilt. All v0.1.5-era drum counts were measured on that wrong audio and are superseded.
2. **Bass intro "fix" attempted and reverted.** The first pass supplemented the silent-stem regions with bass-range (38–420 Hz) Basic-Pitch notes from the shared `other` stem (moving the first bass note 11.9 s → 0.5 s), but playtest rejected it: **the bass genuinely does not play in the first ~16 measures** (vocals/guitar/drums only) — the supplemented "bass" notes were guitar chords. `transcribe_bass` was reverted to `bass.wav` only. The silent bass-stem intro is real content silence, NOT a Demucs routing artifact (unlike drums on other songs — see the `_choose_drum_source` fallback).
3. **ADTOF Frame-RNN neural drum transcription replaces the hand-tuned band detector.** `drums.py` runs the ADTOF 5-class model (kick/snare/toms/hi-hat/cymbals; packaged weights in `adtof_pytorch`) on the **drums stem** (mixed audio only when the stem intro is digitally silent, librosa band fallback only if ADTOF isn't installed). Cymbal hits re-split into ride (Blue/lane 3) vs crash (Green/lane 4); **tom hits are split into tom1/2/3 by fundamental pitch** (`librosa.pyin` on the tom band; low <100 Hz→tom3/Green, mid 100–140→tom2/Blue, high >140→tom1/Yellow), with an unpitched **ring-window** band-energy fallback (60–100 / 100–170 / 170–260 Hz) for short hits/bleed (v0.1.7 — v0.1.6 used spectral centroid, which reads a tom's bright attack as "high" and dumped 100% of toms onto tom1/Yellow, flooding the hi-hat lane), per the RBN packing standard **96=kick, 97=Red(snare), 98=Yellow(hi-hat/tom1), 99=Blue(ride/tom2), 100=Green(crash/tom3)** — `DRUM_LANE_MAP` tom2/tom3 lanes corrected (they were Red/Green). All hits grid-quantized to 1/8. On the correct Eve6 track the intro charts **snare + hi-hat only, zero false kicks** (was 16–26 kicks/5 s from mixed-audio band detection catching guitar/bass lows).
4. **Real RBN/C3 drum difficulty reduction** (the fabricated "Hard drops cymbals" rule — which never fired, leaving Hard == Expert — is gone). **Hard:** thins kicks (375→189) and snare accents (240→136) to the quarter grid, consolidates crash+ride, no kicks in fills. **Medium:** every kick/snare must sit on a hi-hat/ride gem (snapped ≤ ~1/8 beat), no 3-limb hits, no kick under a crash, 8ths only ≤140 BPM (quarters above), one kick/measure >170 BPM. **Easy:** basic kick/snare beat only (never together, quarter grid). Cascade: Expert 1326 → Hard 1036 → Medium 618 → Easy 577.
5. **Guitar strummed chords reconstructed.** Basic Pitch reports the dominant tone of each strum, so rhythm-guitar chords charted as single notes (27 Expert chords). Where the audio at a charted note is chordal (≥ 3 strong chroma pitch-classes, ≤ 7), the perfect-fifth is added → 2-note power chords (**27 → 565**). Bass stays single-note. Also fixed `_reduce_fretted` re-quantizing Hard to 1/8 (merged Expert's 16ths into 166 fake chords); Hard now stays on the 1/16 grid.
6. **ADTOF baked into `requirements.txt`** (`adtof-pytorch @ git+…`) so devcontainer rebuilds get it automatically.

**Verified on correct Eve6 audio** (count-in-free validation MIDI): drums Expert 1326 (kick 375 / snare 240 / hi-hat 523 / ride 138 / crash 50), bass 644, guitar 1485 (565 chords), keys 1485; cascade drums 1326→1036→618→577, guitar 1485→1414→1181→460; 0 same-lane collisions. Tests: 158 passed, 5 pre-existing vocal failures unchanged.

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

`create_all_difficulties(expert, instrument)` applies `DifficultyReducer` **progressively** (Expert→Hard→Medium→Easy) with per-difficulty density caps (notes/sec): Expert 16, Hard 14, Medium 10, Easy 6. For guitar/bass/keys, `_thin_notes` slides a 1s window and drops the least-important notes (protected = HOPO/chord/hold/solo/BRE/fill) where density exceeds the cap. **For drums**, the density cap is almost never hit (drum density ~2.9/sec < every cap), so difficulty is instead derived role/lane-based (see below).

Per-instrument rules implemented:
- **Hard**: ~20–30% thinning, keep HOPOs/chords/holds/solos/BRE (guitar/bass/keys). **Drums:** drop cymbals (lane 4) and snap to the 1/8 beat grid (`_drum_reduce`).
- **Medium**: HOPOs→strums, drop orange lane (lane 4) for guitar/bass, cap 10/sec. **Drums:** keep kick/snare/hat only (drop toms lane 3 + cymbals), grid-quantized.
- **Easy**: single notes only, no blue/orange, no chords/HOPOs/solos/BRE for guitar/bass; cap 6/sec. **Drums:** keep kick/snare/hat, grid-quantized, and **halve the kick count** so Easy is strictly simpler than Medium.

**Drum difficulty helper (`_drum_reduce`):** keeps only `keep_lanes` (Hard {0,1,2,3}, Medium/Easy {0,1,2}); snaps each retained note to the nearest 1/8-beat via `_snap(time, tempo_map, divisions=2)` (local BPM from the `tempo_map`); Easy additionally drops every other kick (`half_kick=True`). Lane semantics: 0=kick, 1=snare, 2=hat, 3=tom/ride, 4=crash.

**Known limitation (still open):** the reducer is heuristic (density caps + role/lane drops + a coarse 1/8 grid), **NOT** a Rock Band-authoring pass. The actual RB rules for deriving difficulties from Expert — cascade, lane consistency, HOPO→strum on Medium/Easy, sustain pull-back, per-difficulty chord restrictions — are documented in `[[difficulty_charting]]` and are **not yet implemented** (the v0.1.0 work only made the *existing* reductions survive serialization to Clone Hero and removed Expert double bass). Keys reductions are still flattened when serialized to a single track / `.chart`. This remains the biggest gap between AutoRB's instrument charts and playable, RB-correct charts.

### Guitar vs Keys note-count mismatch (v0.0.92)
Guitar and Keys both transcribe the same Demucs `other` stem, so they should represent the **same note events** (keys = actual pitches, guitar = those pitches mapped to frets/lanes). They currently diverge because `transcribe_guitar` and `transcribe_keys` run **separate** pitch-detection passes with different `fmin/fmax` (guitar pyin 80–1200 Hz, keys pyin 65–600 Hz) and guitar additionally filters through tuning/fret mapping (`build_lane_map`) that drops notes. Result: e.g. ~102 guitar vs ~87 keys notes on the test song. Fix: share one onset+pitch-detection result, then map to both lane (guitar) and piano-roll (keys). Low absolute counts on this env are mostly because **`crepe` is not installed** (see Transcription backends) — both fall back to weak librosa pyin on the polyphonic `other` stem.

## Transcription backends & why guitar/bass look sparse here

Each transcriber tries a high-quality backend and falls back to librosa:
- **Pitch:** `crepe` (CNN, preferred) → `librosa.pyin` fallback. On the devcontainer/arm64 env **crepe is NOT installed**, so guitar/bass fall back to pyin, which is weak on polyphonic `other` stem audio → far fewer/lower-confidence notes (e.g. Expert Bass came out ~4 notes, Expert Guitar ~27 on the test song). Installing `crepe` (and `madmom` for drums) restores density. `madmom` is also optional; drums fell back to librosa onsets until the onset-strength fix (see `[[log]]`).
- **Onsets:** `madmom` for drums → `librosa` fallback. `detect_onsets_librosa` with `backtrack=True` made `onset_env[onset_frames]` ≈ 0 for most onsets, so the strength filter dropped ~472/479 drum onsets. Fixed by computing strength from the envelope **peak in a forward window** after each onset, normalized by the 95th percentile → ~472 Expert drum notes (1888 across difficulties).

## Known limitations (instrument charts, v0.0.92)

- **Not yet playtest-validated.** Charts are loadable and no longer crash ForgeTool, but note accuracy, HOPO/chord/sustain decisions, and drum-lane assignment need playtest tuning.
- **Keys difficulty not differentiated** beyond density thinning in the packed MIDI / `.chart` (Easy/Medium may still equal Expert when key density is low). **Drums ARE now differentiated** (v0.0.99): Hard drops cymbals, Medium drops toms, Easy halves the kick, all grid-quantized — so PS4 kit players get a genuinely easier chart per difficulty. **Clone Hero drums are now also distinct** (v0.1.0): `remap_drums_for_clone_hero` previously copied every hit into all four CH difficulty sections (so Medium/Easy looked identical to Expert in a CH playtest); it now preserves each hit in its own difficulty. Verified: CH drums Easy 413 / Medium 529 / Hard 772 / Expert 803 on "Open Road Song".
- **Clone Hero does not support Keys** — `[*Keys]` sections are emitted but ignored by CH; validate keys only in RB3/RB4.
- **Guitar/Bass sparseness (largely fixed in v0.0.98).** The old CREPE-confidence gate dropped ~90% of onsets; v0.0.98 recovers density via a dense onset backbone + per-onset multi-pitch, so chord *presence* and note *count* are now representative even without CREPE. Remaining gap is pitch/fret **accuracy** and rhythm alignment, not raw count.
- **Guitar + Keys share the Demucs `other` stem**, so keys transcription is a re-map of the guitar onsets, not a separate keys source.
