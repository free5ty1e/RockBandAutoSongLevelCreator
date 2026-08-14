# Feature Plan: Detect & Fill Missing Lyrics (un-represented vocal segments)

## Overview
The current chart only emits notes for words that appear in the `.lrc` file (via WhisperX forced
alignment + onset snapping). Any vocal passage that is *not* in the LRC — an ad-lib, a shouted
"YEAHHHHH!", a scat/ah section, an un-timestamped tag, or a lyric the LRC author omitted — gets
**no note at all** and the singer hears/watches silence where the game should chart a note.

Concrete, observed example (the user's "Open Road Song" reference, `output_ors/`):
- After the "forgotten" sustain (`synced_track.json` word 244, end ~168.67s) and before the next
  phrase "My pile shakes..." (word 245, start ~168.97s), the vocal stem has a loud, pitch-bearing
  **"YEAHHHHH!"** ad-lib that is completely absent from the chart. It appears in the vocal-stem
  pyin/RMS analysis but not in any LRC line, so nothing is emitted for it.

**Goal:** Scan the vocal stem for *un-represented* sung regions (vocal activity with no charted
note), transcribe them with WhisperX where possible, and emit pitched Rock Band vocal notes for
them so nothing the singer actually sings is left uncharted. The `.lrc` remains a *suggestion*;
the audio is the source of truth for what must be charted.

Status: **PLANNED** (not implemented). This cycle only produces this plan + a ROADMAP entry; the
timing fixes are implemented separately. See `# Implementation Phases` for the build order.

---

## Why This Is Needed (Evidence)

### 1. The `.lrc` is incomplete, not just mis-timed
The user's `.lrc` (`input/eve6-openRoadSong.lrc`) omits the shouted "YEAHHHHH!" after
"forgotten". This is not a sync error — the audio simply has a sung segment that has no
corresponding line. Even a perfect sync pipeline cannot chart a word that was never entered.

### 2. The `.lrc` may be mis-timed (offset) — handled by the sibling timing fix
The MP3 and LRC frequently come from different sources. Measured on this track: LRC line
timestamps are ~0.35s **early** vs the true vocal onsets (median −0.35s, mean −0.23s, stdev
0.51s, two lines +1.98s wrong). So we already **must not** trust LRC timestamps as anchors.
The missing-lyrics feature inherits this same principle: gap detection runs on the audio, not on
LRC line boundaries.

### 3. Gaps are detectable with existing tech
We already have the vocal stem, librosa (onset/RMS/pyin), and WhisperX. A vocal "gap" is
precisely a time span that:
- has strong vocal energy (RMS above the noise floor) and/or pyin-voiced frames, AND
- is not covered by any charted vocal note (word's `[start, end)`).

These are all computable with the exact same signals used for onset snapping and pitch.

---

## Current Architecture (where the gap lives)

Pipeline (see `autorb/cli.py`, `autorb/audio/step4_sync.py`, `autorb/audio/vocals.py`):
```
Audio → Demucs vocal stem
        → WhisperX forced alignment (word_segments: text + start/end)
        → librosa onset + pyin  → onset-snap each word's start
        → syllable segmentation (LRC / pyphen / whisperx chars)
        → pitch resolve (pyin primary, BP + melodic contour fallback)
        → _clip_and_extend_word_ends (clip overlaps; extend line-final sustains)
        → synced_track.json  →  midi_generator.py → PART VOCALS notes
```

**Where charted notes are born:** `autorb/audio/step4_sync.py` builds `refined` — one entry per
WhisperX word. `autorb/export/midi_generator.py` then turns each word (and its syllable
`note_segments`) into MIDI `note_on`/`note_off`. A region only gets a note if it was a WhisperX
word. **There is no step that compares the full vocal-activity signal to the set of charted
notes and fills the difference.**

### Key files
| File | Role today | Role after |
|------|-----------|-----------|
| `autorb/audio/step4_sync.py` | onset snapping, word ends, `sync_lyrics_to_beats()` | **Hosts the new gap-detection + fill stage** |
| `autorb/audio/vocals.py` | WhisperX alignment, `syllable_pitches` cache | Reused to transcribe individual gaps |
| `autorb/transcribe/syllables.py` | word → syllable split | unchanged |
| `autorb/export/midi_generator.py` | word → MIDI notes | unchanged (already supports multi-note words) |
| `autorb/cli.py` | orchestration, `vocals_cache.json` | possibly new flag |

### Reusable signals already computed
- `_detect_vocal_onsets(vocals_stem)` — libosa onset times filtered by voicing.
- `librosa.pyin(...)` f0/voiced/probs arrays (used for onset voicing + per-word pitch).
- `librosa.feature.rms(...)` — energy envelope (used to find word-end tails; see timing fix).
- WhisperX `word_segments` + `alignment_result` (char timing) — for transcribing a gap.

---

## Design

### Terminology
- **Covered** time: any second inside a charted vocal note's `[start, end)` (clipped, no overlap).
- **Un-represented vocal region (a.k.a. gap):** a contiguous span where the vocal-activity signal
  is "on" but coverage is "off", with duration ≥ `MIN_GAP_DURATION`.

### High-level algorithm (new stage, after word refinement, before/inside `sync_lyrics_to_beats`)
1. **Build a vocal-activity mask** over the whole stem at a hop (e.g. 25–50 ms):
   `active[t] = (RMS[t] > energy_threshold) OR (pyin voiced & prob > 0.3)`.
   The energy threshold is *relative* (e.g. `max(noise_floor*3, 0.15 * global_peak_rms)`) so a
   loud track vs a quiet track both work; this mirrors the tail-detection used by the timing fix.
2. **Build a coverage mask** from the refined charted notes: `covered[t]` if inside any note's
   `[start, end)`.
3. **Find contiguous runs** where `active && !covered`, of length ≥ `MIN_GAP_DURATION`
   (proposed default ~0.35 s; tune so that the tiny inter-word breaths — already handled by
   `MIN_WORD_GAP` — do not become spurious notes).
4. For each qualifying run, produce a **gap word**:
   - **Timing:** onset = run start snapped to the first vocal onset in the run (reuse
     `_refine_word_timing`/`_detect_vocal_onsets`); end = run end snapped to the last voiced /
     RMS-tail frame (reuse the audio-tail logic from the timing fix). Clamp to not overlap the
     next charted note.
   - **Text:** run WhisperX on the gap's audio slice (see `# Transcription`). If it returns text,
     use it; if it returns nothing confident, fall back to a generic lyric token (`"la"` is the
     Rock Band convention for non-lyric sung syllables) so a pitched note is still emitted.
   - **Pitch:** compute pyin over the gap (same `_compute_word_pyin_pitches` trust rules);
     fallback to the melodic contour (same `_build_melodic_contour`/`_octave_snap` path) so the
     ad-lib lands on a sane, in-key note.
5. **Merge** the gap words into `refined` (sorted by start), run them through the existing
   syllable segmentation + pitch + clip/extend passes so they behave exactly like normal words.

### Transcription (gap → lyric text)
Preferred path, per user decision: **WhisperX-transcribe the slice + always emit a pitched note**.
- Slice the vocal stem `[run.start, run.end]`, feed to WhisperX (the same model used for
  alignment, e.g. `whisperx.load_model`).
- Accept the transcription if its confidence exceeds a threshold *and* it is a plausible sung
  token (letters/`!`/vowels); otherwise generic `"la"`.
- Cost control: only run WhisperX on detected gaps (usually few), never the whole track; cache
  results keyed by `(song_id, round(gap.start,2))` in `vocals_cache.json` so re-runs are free.
- Phase-2 alternative (cheaper, no model dependency): skip transcription, always use `"la"` and
  rely on the pitched note. The plan keeps WhisperX first because the user asked for it, but the
  gap *detection* (energy + coverage) is model-free either way.

### Phrase / punctuation sanity
- A gap that lands inside an existing word's sustain tail (the singer holds a vowel and also
  shouts) must not create a near-zero-length duplicate. Enforce `MIN_GAP_DURATION` and require
  the run to be outside every note's `[start - ε, end + ε)`.
- Punctuation/ad-lib words ("YEAHHHHH!", "woah", "hey!") are legitimately charted in Rock Band;
  no filtering needed beyond not duplicating real words.

---

## Constants (proposed, to be tuned with the reference track)
| Constant | Value | Notes |
|----------|-------|-------|
| `MIN_GAP_DURATION` | 0.35 s | Below this, treat as a breath/transition, not a missing word |
| `GAP_ACTIVE_RMS_FACTOR` | 0.15 × global_peak | "active" energy threshold (relative) |
| `GAP_ACTIVE_VOICED_PROB` | 0.3 | "active" voicing threshold |
| `GAP_SNAP_WINDOW` | 0.20 s | snap run start back to nearest onset |
| `GAP_SNAP_TAIL` | 0.30 s | extend run end to last RMS/voiced tail |
| `GAP_MIN_RUN_LEN` | (>= MIN_GAP_DURATION) | guard against filler |
| `GAP_MAX_PER_SONG` | e.g. 30 | safety cap so a broken energy signal can't flood the chart |

---

## Acceptance Criteria (how we'll know it works)
1. On the reference track, the post-"forgotten" "YEAHHHHH!" produces ≥1 charted vocal note whose
   `[start,end)` overlaps the audio ad-lib (verified against pyin/RMS) and is absent from the
   current chart.
2. Every pre-existing charted word is unchanged (no duplicate, no shifted note) — regression
   check vs the timing-fixed chart.
3. A word that the `.lrc` includes still charts exactly once.
4. A synthetic fixture (a stem with an extra shouted syllable spliced between two LRC words)
   yields the new note while the two original words keep their timing.
5. `--skip-vocals` (cache reuse) still works; gap results are cached.

---

## Implementation Phases
- **Phase 0 (this cycle):** this plan document + ROADMAP entry. No code.
- **Phase 1:** Reusable `vocal-activity mask` + `coverage mask` helpers in `step4_sync.py` (or a
  new `autorb/audio/gap_fill.py`), unit-tested on synthetic fixtures.
- **Phase 2:** Wire gap detection into `sync_lyrics_to_beats()` after word refinement; emit
  pitched `"la"` notes (model-free) and validate on the reference track + synthetic fixture.
- **Phase 3:** Add WhisperX gap transcription (per-slice, cached) + confidence gating; the
  "YEAHHHHH!" shows real text when the model is confident.
- **Phase 4:** CLI flag (e.g. `--fill-missing-lyrics`, default on) + `vocals_cache.json` schema
  addition; README/CHANGELOG/llm-wiki updates.

---

## Risks & Mitigations
- **Energy bleed from other instruments in the vocal stem** → relative RMS threshold + require
  either RMS *or* voicing; tune on the reference stems which are Demucs-clean.
- **Spurious notes from breaths/sighs** → `MIN_GAP_DURATION` + require pitch evidence (voiced
  frames) unless RMS is very strong; keep `GAP_MAX_PER_SONG` cap.
- **WhisperX cost/latency on gaps** → only run on detected gaps (few), cache results; Phase 3
  can be toggled off with a flag if too slow.
- **Overlap with real words** → strict "outside every note's span" check before creating a gap
  word; merge-and-reclip afterward like normal words.

## Related / Depends On
- **Timing fix (implemented separately this cycle):** audio-derived word starts *and* ends. The
  gap feature relies on the same audio-tail logic and on charted notes being accurate; do the
  timing fix first so coverage boundaries are trustworthy.
- See also `vocal_phrase_management_from_lrc.md` (phrasing), `vocal_pitch_tracking_per_syllable.md`
  (multi-pitch), and this repo's `ROADMAP.md` / `CHANGELOG.md`.