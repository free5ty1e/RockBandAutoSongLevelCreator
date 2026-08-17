# Plan: Guitar/Bass Articulation Fixes (rapid strums & bass hold-merge)

**Status:** Proposed (v0.0.98 caveat → roadmap)
**Owner:** AutoRB
**Symptoms (user playtest, v0.0.98):**
- *Guitar:* "the doubled notes are being blended into single notes (should be
  two rapid strums but it shows as one strum) especially all throughout the
  intro."
- *Bass:* "definitely needs more sensitivity on the 'attack' detection, because
  I'm hearing clearly played separate bass notes that are being merged into one
  super long hold in the bass track."

## Guitar: rapid re-strums collapse into one note

### Root cause (analysis)
Two independent mechanisms merge rapid same-lane strums:
1. **Onset suppression.** `detect_onsets_librosa` is called with
   `wait=5` (≈58 ms at hop 512 / sr 44100). `librosa.onset.onset_detect`
   suppresses any new peak within `wait` frames of the last one, so two strums
   closer than ~58 ms become a single onset → a single note. Intros with fast
   strummed chords are exactly this case.
2. **Hold over-extension.** `detect_holds` (`guitar.py`) extends a note's
   `hold_duration` while RMS ≥ 30% of the onset RMS, up to `min_hold_duration`
   (1.0 s). If the next strum is < 1 s later, the first note's sustain reaches
   (or overlaps) the second, so they read as one connected note.

### Proposed fix
- Lower `wait` (try 3) and lower `merge_nearby_onsets(min_interval=0.03)` is
  fine, but add a **re-attack splitter**: after onset detection, run a
  *fine-grained* onset envelope (smaller `wait`, higher `delta`) over each
  detected note's window; any sub-peak becomes a separate onset at the same
  pitch (a re-strum).
- **Cap every hold to the gap before the next onset** for that lane:
  `hold = min(hold, next_onset_same_lane - onset - 0.01)`. A note must never
  sustain into the next attack. This alone eliminates the "merged into one"
  symptom for both guitar and bass.
- Keep hold detection for *true* sustains (legato, held chords) — only cap,
  don't remove.

## Bass: separate notes merged into one long hold

### Root cause (confirmed in `bass.py:128-160`)
`detect_holds_bass` walks the RMS envelope while `rms[j] >= 0.25 * rms[onset]`
and sets `hold_duration` to that span — **up to 8 seconds**, with no cap to the
next onset and a very low (25%) threshold. A bass note whose tone rings (natural
sustain, amp compression, or a busier low end) keeps RMS above 25% across the
gap to the *next* bass note, so the first note's sustain reaches the second —
 the two read as one super-long hold. "More sensitivity on attack detection"
  also suggests the **onset gate is too strict**: `conf > 0.4`
  (`bass.py:283`) drops legitimate low-confidence bass onsets, so what should be
  two attacks becomes one sustained note.

### Proposed fix
- **Cap hold to next onset** (same as guitar): `hold_duration = min(hold,
  next_onset - onset - 0.01)`. Separate bass notes stay separate.
- **Raise the RMS hold threshold** (e.g. 0.4–0.5) and stop the walk at the
  first sustained dip; a real bass note's body decays, and the threshold should
  track the *decay*, not a flat 25% of the peak.
- **Lower the onset confidence gate** from `0.4` to ~`0.25` (or remove it and
  rely on the dense onset backbone + multi-pitch, mirroring the guitar v0.0.98
  change) so distinct attacks aren't dropped.
- Add a **minimum inter-note gap** so two onsets < ~70 ms that resolve to the
  same pitch/lane are not double-charted (avoid the opposite bug).

## Shared change
Both fixes want a `cap_hold_to_next_onset(notes)` helper in
`autorb/transcribe/instruments/difficulty.py` (or a shared module) used by
`transcribe_guitar` and `transcribe_bass` right after hold detection.

## Validation
- Unit `test_instrument_quality.py`: synthesize a bass line of 4 distinct 0.3 s
  notes 0.4 s apart → assert 4 separate notes, each hold < 0.15 s (not one
  1.6 s hold). Synthesize two guitar strums 0.12 s apart at the same lane →
  assert 2 notes (not 1).
- Integration on `eve6-openRoadSong`: bass Expert hold-length histogram peaks
  short; guitar intro shows distinct re-strums (per-difficulty note count rises
  vs v0.0.98 in the intro region).
- Playtest: user confirms bass notes are separate and guitar intro strums are
  distinct on PS4/Clone Hero.

## Files to touch
- `autorb/transcribe/instruments/guitar.py`: `detect_onsets_librosa` `wait`,
  re-attack splitter, hold cap.
- `autorb/transcribe/instruments/bass.py`: `detect_holds_bass` threshold +
  hold cap, `transcribe_bass` conf gate, hold cap.
- `autorb/transcribe/instruments/difficulty.py` (or shared): `cap_hold_to_next_onset`.
- `tests/test_instrument_quality.py` (new).
