# Plan: Drum Difficulty Derivation (distinct Hard / Medium / Easy)

**Status:** Proposed (v0.0.98 caveat → roadmap)
**Owner:** AutoRB
**Symptom (user playtest, v0.0.98):** "Drums look a little sporadic on expert
and maybe impossible to play, but they might be right. I would need a derived
hard / medium / easy difficulty set in order to properly test drums on the PS4
on my drum kit."

## Root cause (confirmed)

`create_all_difficulties` / `DifficultyReducer` reduces by **density caps only**
(`difficulty.py:59-64`): Expert 16, Hard 14, Medium 10, Easy 6 notes/sec.
The drum chart for "Open Road Song" is ~2.9 notes/sec — **below every cap** — so
`_thin_notes` removes nothing and Hard == Medium == Easy == Expert (all ~612
notes). The drum-specific branches in `_to_medium` / `_to_easy` only remap
ride/crash→hihat and drop `lane >= 2 with length == 0`; they never actually
*reduce* the kit or simplify the pattern. Result: no usable lower difficulties.

Separately, "sporadic / possibly impossible on Expert" points at the underlying
drum **transcription quality** (`drums.py`): the per-band element classifier may
be emitting hits at wrong lanes or with wrong density. That is a separate,
larger effort (see `instrument_transcription_accuracy.md`); this plan focuses on
**deriving playable, distinct difficulties** from whatever Expert we have.

## Proposed approach: grid-based drum reduction

Rock Band drum difficulties are not random thinnings — they are *simpler
patterns* on a beat grid. Implement a drum-specific reducer that:

1. **Quantize all Expert drum hits to the beat grid** (1/4 for kick/snare,
   1/8 for hats/cymbals) using `tempo_map`. This alone removes the "sporadic"
   feel by snapping hits to where a drummer expects them.
2. **Classify each hit** into role: kick (lane 0), snare (1), hat (2),
   tom (3), cymbal (4) — already done in `drums.py` element classification;
   carry the role through to `ChartNote.metadata`.
3. **Derive per difficulty by role + grid**, not by density thinning:
   - **Expert:** all hits, all lanes (current Expert).
   - **Hard:** keep kick+snare+hats+cymbals; **drop ghost/tom fills** that are
     not on strong beats (keep toms only when they replace a snare backbeat).
   - **Medium:** kick on beats 1 & 3, snare on 2 & 4, hats on 1/8 notes,
     rides/cymbals on downbeats only; **no toms**.
   - **Easy:** kick on 1 & 3, snare on 2 & 4, hat on 1/4 (or 1/8 if sparse),
     **no toms, no cymbals**. This is the classic "basic rock beat" a beginner
     plays on a real kit.
4. **Keep fills/overdrive phrases** intact in Expert/Hard (don't simplify the
   Fill sections), but Medium/Easy may replace a fill with the basic groove.

### Why grid-based, not density-cap
A beginner on a real e-kit cannot play 2.9 random hits/sec, but *can* play a
kick-snare-hat groove. Deriving from the grid guarantees each lower difficulty
is a real, learnable pattern rather than a thinned expert.

## Validation
- `Hard/Med/Easy` note counts become **strictly decreasing** and **distinct**
  from Expert for drums (currently identical).
- A new assertion in `test_instrument_quality.py`: for drums,
  `len(easy) < len(medium) < len(hard) <= len(expert)` and easy contains only
  kick/snare/hat lanes.
- Playtest on the user's PS4 kit: Easy = playable basic beat; Expert = full chart.

## Files to touch
- `autorb/transcribe/instruments/difficulty.py`: replace drum branches in
  `_to_medium` / `_to_easy` with the grid/role-based derivation; add a
  `quantize_to_grid` call for drums.
- `autorb/transcribe/instruments/drums.py`: ensure each `ChartNote` carries its
  drum role (kick/snare/hat/tom/cymbal) in `metadata` for the reducer.
- `tests/test_instrument_quality.py` (new).

## Out of scope (this plan)
- Fixing the underlying drum *transcription* accuracy (wrong lanes / missing
  hits) — that is `instrument_transcription_accuracy.md` + a future
  `drums_transcription_quality.md`. Deriving difficulties helps the user test
  *now* even if Expert still needs tuning.
