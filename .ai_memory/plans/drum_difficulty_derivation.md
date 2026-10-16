# Plan: Drum Difficulty Derivation (distinct Hard / Medium / Easy)

**Status:** Rules researched (see `[[difficulty_charting]]`); rework not yet coded.
**Owner:** AutoRB
**Symptom (user playtest, v0.0.98):** "Drums look a little sporadic on expert
and maybe impossible to play, but they might be right. I would need a derived
hard / medium / easy difficulty set in order to properly test drums on the PS4
on my drum kit."

**Update (v0.0.99 playtest):** user confirmed Hard/Medium/Easy now *exist*
distinctly in the CON/MIDI, but reported two problems:
1. **"Saw no difference on Medium"** — this is the **Clone Hero export
   flattening**, not the reducer. `remap_drums_for_clone_hero`
   (`autorb/export/clone_hero.py`) copies every hit into **all four** CH
   difficulty sections, so a Clone Hero playtest of Medium drums looks identical
   to Expert. The packed MIDI already carries distinct per-difficulty drums.
   **Fix:** write the *actual reduced* drums to each CH difficulty section
   (Clone Hero supports per-difficulty drum charts). Until then, playtest
   difficulty on PS4 (or parse the packed MIDI), not Clone Hero drums.
2. **"Too busy on Expert / double-bass pedal hits not normally allowed."** Rock
   Band does **not** support fully-authored double bass; Expert must use
   single-foot kick patterns (see `[[difficulty_charting]]` §2.1). This is an
   **Expert transcription/authoring** fix, not a reduction fix — see
   `instrument_transcription_accuracy.md`.

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

## Researched Rock Band drum difficulty rules (`[[difficulty_charting]]` §2)

The reduction is **not** a density thinning — it follows specific per-difficulty
rules. Authoritative (RBN/C3 Drum Authoring + Drum Review Process):

- **Hard:** kicks ≈ halfway between Expert and Medium in count; **no kicks during
  drum fills**; all crashes reduced to a **single color** (no back-and-forth, no
  two-crash hits unless lots of preceding space).
- **Medium:** **no kicks/snares between hi-hat/ride time-keeping gems**; **no
  3-limb hits** (no simultaneous kick+snare+crash — drop the kick); right hand
  not expected to keep 8th notes if >140 BPM (use quarter notes); **if >170 BPM,
  one kick per measure**; fills/rolls reduced to 8th notes; crashes on downbeats
  get a kick, off-beat crashes get none; ~100–110+ BPM → kicks on quarter notes.
- **Easy:** **never more than 2 limbs at once** — no hand gems paired with kicks
  (either a 2-hand beat with no kick, or kick+snare); **no kick/crash pairing**
  (that's a Medium thing); >170 BPM → one kick/measure; thin Medium's 8th fills
  to quarter notes when fast.
- **Lane conventions:** crash should almost always be Green (lane 4); different
  toms = different gems; **no 3-pad simultaneous** (two at a time max); **no kicks
  on off-beats**; remove kicks from all fills; snare+crash > kick.
- **Tempo-driven kick ceiling** (practical): ≤~100–110 BPM kicks on quarters OK;
  140+ BPM right-hand time-keeping drops to quarters (fewer kick places); 170+
  BPM one kick/measure.

## Proposed approach: rule-based drum reduction

Replace the current role/lane thinning + 1/8 grid with a **rule-driven** reducer
that encodes the rules above:

1. **Quantize** Expert drum hits to the beat grid (kick/snare on 1/4, hats/cymbals
   on 1/8) using `tempo_map` — removes the "sporadic" feel.
2. **Carry role** (kick/snare/hat/tom/cymbal) through `ChartNote.metadata` from
   `drums.py` element classification.
3. **Derive per difficulty by rule, not density:**
   - **Hard:** all hits; drop kicks inside fills; collapse crashes to one color;
     kicks ≈ halfway to Medium.
   - **Medium:** keep kick/snare/hat (+ crashes on downbeats w/ kick); **drop
     toms**; **no kick between time-keeping gems**; enforce tempo kick ceiling;
     reduce fills/rolls to 8th notes.
   - **Easy:** kick/snare OR 2-hand beat; **no kick+hand pairing**; **no
     cymbals**; tempo kick ceiling (one/measure if >170).
4. **Clone Hero export:** write the *actual reduced* drums to each CH difficulty
   section (stop duplicating all hits to all four) so Medium/Easy playtest
   correctly in Clone Hero.

### Why rule-based, not density-cap
A beginner on a real e-kit cannot play 2.9 random hits/sec but *can* play a
kick-snare-hat groove. The RB rules guarantee each lower difficulty is a real,
learnable pattern (and legally compliant), not a thinned expert.

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
