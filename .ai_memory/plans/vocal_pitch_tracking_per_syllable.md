# Feature Plan: Per-Syllable Vocal Pitch Tracking

## Overview
Transform the vocal chart from **one static pitch per word** to **multiple notes per word** that track the singer's actual pitch contour (slides, vibrato, pitch changes within a word). This improves scoring accuracy and gives singers a visual representation of the true vocal melody.

---

## Current Architecture (v0.0.75)

### Pipeline Flow
```
Audio → Demucs (vocals stem) → WhisperX (word alignment) → Basic-Pitch (note candidates) → librs pyin (pitch validation)
                                                                                          ↓
                                              MIDI Assembly ← pitch_per_word ← trusted_pyin_mode_or_fallback
```

### Key Files
| File | Role |
|------|------|
| `autorb/transcribe/vocals.py` | WhisperX alignment, Basic-Pitch extraction, pyin pitch validation, `compute_vocal_pitch_per_word()` |
| `autorb/transcribe/step4_sync.py` | Syllable/word timing from LRC + WhisperX fallback, onset snapping |
| `autorb/export/midi_builder.py` | MIDI note creation (`add_vocal_track()`), one note per word |
| `autorb/cli.py` | Orchestration, cache (`vocals_cache.json`) |

### Current Pitch Logic (`vocals.py:compute_vocal_pitch_per_word`)
1. **pyin primary**: For each word's time window (clipped to next word start), collect voiced frames where `confidence > 0.8`. Accept if `rounded_mode == median` (rejects octave flips/bleed). Output: trusted MIDI note.
2. **Basic-Pitch fallback**: For untrusted words, take BP note in window, octave-snap to melodic contour interpolated through trusted words.
3. **Contour fallback**: If no BP note, use interpolated contour value.
4. Result: **One MIDI note per word** (constant pitch for entire word duration).

---

## Target Architecture

### New Pipeline Flow
```
Audio → Demucs → WhisperX (word alignment) → **Syllable segmentation** (LRC or heuristic)
                                              ↓
                                    **Per-syllable pyin** (dense pitch trace)
                                              ↓
                                    **Pitch segmentation** → note boundaries where pitch changes
                                              ↓
                                    MIDI Assembly → multiple notes per word
```

### Core Changes

#### 1. Syllable-Level Alignment (`step4_sync.py` + new module)
- **LRC-enhanced**: If `.lrc` has syllable timestamps (e.g., `[00:12.34]To-night`), use those directly.
- **Heuristic fallback**: Split WhisperX word segments into syllables using:
  - `pyphen` (Python hyphenation) for English syllable boundaries
  - Proportional time allocation within word (weighted by vowel count)
  - Optional: forced alignment with `phonemizer` + `montreal-forced-aligner` (heavy dep, Phase 2)

#### 2. Dense Pitch Trace per Syllable (`vocals.py` → new `pitch_tracking.py`)
- Run **librosa pyin** on **entire vocal stem** once (not per-word windows) → continuous `f0` + `voiced_flag` + `voiced_prob` arrays at hop length (default 512 samples ≈ 11.6ms at 44.1kHz).
- For each syllable window: extract pitch sub-array, compute statistics.
- **Pitch change detection**: Find frame boundaries where pitch shifts > threshold (e.g., 1.5 semitones) sustained for > N frames.

#### 3. Note Segmentation Algorithm
```
Input: syllable [t_start, t_end], dense f0[t], voiced_prob[t]
Output: List of (note_start, note_end, midi_note) covering the syllable

Algorithm:
1. Filter to voiced frames (voiced_prob > 0.6)
2. Convert f0 → MIDI (continuous, fractional)
3. Smooth with median filter (window=3-5 frames) to suppress jitter
4. Detect change points: |Δmidi| > 1.5 semitones for ≥ 3 consecutive frames
5. Segment at change points → each segment = one MIDI note
6. Per segment: rounded_mode of midi values (same trust logic as current pyin)
7. Merge adjacent segments if same midi_note and gap < 50ms
8. Quantize note boundaries to MIDI ticks (480 PPQ)
```

#### 4. Vibrato / Slide Handling
- **Vibrato**: Rapid oscillation around a center pitch (±1-2 semitones, 5-7 Hz). Detect via autocorrelation of pitch residual. Represent as **single note with pitch bend** (MIDI pitch wheel) OR as sustained note (current RB3 engine doesn't render vibrato visually). Decision: **single note, no pitch bend** (simpler, matches RB3 behavior).
- **Slides (portamento)**: Sustained pitch change > 2 semitones over > 100ms. Represent as **two notes with overlapping tie** OR **pitch bend between notes**. Decision: **two notes** (RB3 shows slide as adjacent gems).

#### 5. MIDI Builder Changes (`midi_builder.py`)
- `add_vocal_track()` currently: one `note_on`/`note_off` per word.
- New: iterate over `word.syllables`, each with `note_segments[]`, emit notes sequentially.
- Preserve **overlap-free clipping**: each note's end = min(segment_end, next_note_start).
- Keep **count-in shift** (3 measures) applied after all note times computed.

#### 6. Cache Format (`vocals_cache.json`)
Current: `{word_idx: {pitch, start, end, ...}}`
New: `{word_idx: {syllables: [{start, end, notes: [{pitch, start, end}]}]}}`
- Backward compatible: if cache has old format, fall back to per-word logic.

---

## Implementation Phases

### Phase 1: Syllable Segmentation (Week 1)
- [ ] Add `pyphen` to requirements
- [ ] Create `autorb/transcribe/syllables.py`:
  - `segment_word_to_syllables(word_text, word_start, word_end, lrc_syllables=None)`
  - Returns list of `(syllable_text, start, end)`
  - LRC path: parse `[mm:ss.xx]syl-la-ble` format (hyphen-separated)
  - Fallback: `pyphen.Pyphen(lang='en').positions()` + proportional timing
- [ ] Integrate into `step4_sync.py` → `sync_lyrics_to_audio()` returns `Word` objects with `syllables` list
- [ ] Tests: known LRC with syllable timestamps, fallback on plain LRC

### Phase 2: Dense Pitch Trace & Segmentation (Week 2)
- [ ] Create `autorb/transcribe/pitch_tracking.py`:
  - `compute_dense_pitch(vocals_stem_path) → (times, f0, voiced_prob)` — single pyin call
  - `segment_syllable_pitch(syllable_start, syllable_end, times, f0, voiced_prob) → List[NoteSegment]`
  - NoteSegment: `start, end, midi_note (int), confidence (float)`
- [ ] Refactor `vocals.py`: replace `compute_vocal_pitch_per_word()` with `compute_vocal_pitch_per_syllable()` using new module
- [ ] Maintain same trust logic (mode==median, confidence threshold)
- [ ] Tests: synthetic pitch traces (slide, vibrato, jump), real song validation

### Phase 3: MIDI Generation (Week 3)
- [ ] Modify `midi_builder.py:add_vocal_track()`:
  - Accept `words_with_syllables_and_notes` structure
  - Emit sequential notes per syllable segment
  - Apply overlap-free clipping at syllable level too
- [ ] Update `cli.py` to pass new structure
- [ ] Update `vocals_cache.json` schema + load/save logic
- [ ] Tests: MIDI round-trip, tick alignment, count-in shift preserved

### Phase 4: Integration & Validation (Week 4)
- [ ] End-to-end test on "Open Road Song" + 2-3 other tracks
- [ ] Compare note count: expect ~2-4× current (words → syllables × pitch changes)
- [ ] Validate in-game: CON builds, PKG converts, vocals playable on RB3/RB4
- [ ] Difficulty rating update: more notes = higher vocal density → may shift tier
- [ ] Performance: pyin on full stem is faster than per-word (single call), cache helps

---

## Technical Details

### Pitch Segmentation Thresholds (Tunable)
| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `MIN_SEMITONE_CHANGE` | 1.5 | Ignores vibrato/jitter, catches real melody moves |
| `MIN_SUSTAINED_FRAMES` | 3 | ~35ms at 11.6ms hop — filters transient noise |
| `MERGE_GAP_MS` | 50 | Merges same-pitch segments separated by brief unvoiced |
| `MIN_NOTE_DURATION_MS` | 80 | Rock Band minimum gem length (~1/32 note at 120 BPM = 62.5ms) |

### Vibrato Detection (Optional Enhancement)
```
residual = midi_values - median_filter(midi_values, window=9)
acf = autocorr(residual)
if peak at 5-7 Hz with amplitude > 0.5 semitones:
    mark as vibrato → single note, no segmentation
```

### LRC Syllable Format Support
```
[00:12.34]To-night
[00:12.58]the
[00:12.82]world
```
Parsing: split on `-` within timestamp bracket, distribute time proportionally by character count or equal split.

### Cache Invalidation
- Cache key includes: audio file hash + lyrics file hash + `pyin` parameters (hop_length, fmin, fmax)
- On mismatch: recompute full pipeline

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Pyin on full stem slower | Medium | Single call vs N word calls; cache eliminates repeat; 3-min song ≈ 2-3s on CPU |
| Syllable timing inaccurate | High | LRC syllables = ground truth; heuristic fallback only when LRC missing |
| Too many short notes (unplayable) | High | `MIN_NOTE_DURATION_MS` merge, difficulty rating auto-adjusts |
| RB3 engine limits (max notes/measure) | Low | RB3 supports dense vocal charts (e.g., "Bohemian Rhapsody" customs) |
| WhisperX word alignment drift | Medium | Onset snapping already fixes; syllable split inherits word boundaries |

---

## Success Criteria

1. **Note density**: "Open Road Song" goes from ~150 notes (words) → ~400-600 notes (syllables × pitch segments)
2. **Pitch accuracy**: Consecutive jumps ≥4 semitones remain low (current: 28/283); no new octave flips
3. **In-game**: Chart loads, scores correctly, visual pitch matches singer
4. **Performance**: Full pipeline < 2× current runtime (pyin once, not per-word)
5. **Backward compat**: `--skip-vocals` with old cache still works (per-word fallback)

---

## Dependencies to Add
- `pyphen>=0.10` (syllable hyphenation, pure Python, no compile)
- Optional Phase 2: `phonemizer`, `montreal-forced-aligner` (heavy, skip for MVP)

---

## File Changes Summary

| File | Change |
|------|--------|
| `autorb/transcribe/syllables.py` | NEW — syllable segmentation |
| `autorb/transcribe/pitch_tracking.py` | NEW — dense pyin + segmentation |
| `autorb/transcribe/vocals.py` | REFACTOR — use new modules, per-syllable output |
| `autorb/transcribe/step4_sync.py` | MODIFY — attach syllables to Word objects |
| `autorb/export/midi_builder.py` | MODIFY — emit multiple notes per word |
| `autorb/cli.py` | MODIFY — pass new structure, cache schema v2 |
| `requirements.txt` | ADD — `pyphen` |
| `tests/test_vocal_pitch_tracking.py` | NEW — unit tests for segmentation |
| `tests/test_syllable_segmentation.py` | NEW — unit tests for syllables |

---

## Rollout Plan

1. **Feature branch**: `feature/per-syllable-pitch-tracking`
2. **Phase 1-3**: Implement, test locally, CI passes
3. **Phase 4**: Manual validation on 3+ songs, CON+PKG test
4. **Version bump**: `0.0.76` (per AGENTS.md: +0.0001)
5. **Changelog**: Document feature, note density increase, cache migration
6. **Release**: Tag `v0.0.76`, CI builds wheel