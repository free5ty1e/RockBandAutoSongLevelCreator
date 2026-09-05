# Rock Band Difficulty Authoring Rules (Expert → Easy derivation)

Authoritative guidelines for authoring Rock Band instrument charts and **deriving
Hard / Medium / Easy from Expert**, distilled from the Harmonix Rock Band Network
(RBN) and C3 Customs authoring documentation (`docs.c3universe.com/rbndocs`) and
corroborated by community chart-format references. AutoRB's instrument
transcription must follow these rules so the charts are **compliant and fun to
play** on every difficulty, not just loadable.

These rules are the spec for the difficulty-derivation rework tracked in
`.ai_memory/plans/drum_difficulty_derivation.md` and
`.ai_memory/plans/guitar_bass_articulation_fixes.md`. See also
[[instrument_charting]] for how AutoRB currently serializes charts to MIDI.

## 0. Universal principles (every instrument)

1. **Expert = literal rhythmic transcription.** Expert must be, rhythmically, a
   faithful transcription of the actual performed part, **quantized to the beat
   grid** (16th / 32nd / triplet grids as needed). It must **never be authored to
   be intentionally harder** than the real part — if the part is genuinely
   brutal (32th/64th runs), keep it; never inflate difficulty.
2. **Reduce one difficulty at a time** (Expert → Hard → Medium → Easy), like the
   C3 Automation Tools (CAT) "reduce" operation. Each lower difficulty is a
   *simplified, structured* version of the one above it — **not** a random
   density thinning. Always re-check the reduced chart against the rules for that
   difficulty before reducing further.
3. **Lane / color consistency.** For every lane (gem color) used in Expert, there
   must be **at least one gem of that color in every lower difficulty**. (If
   Expert itself uses fewer than 5 colors, all difficulties use that same reduced
   set.) This is what makes the chart feel coherent across difficulties.
4. **Sustain spacing & "reasonable to whammy."** Leave at least a **1/16-note gap**
   between the end of a sustain and the next note. A sustain too short to whammy
   is a defect ("stumpy tail"). Lower difficulties pull sustains back further
   (see per-instrument rules). Don't author nuanced pickup / passing / muted
   notes between chords on Hard.
5. **Consistency of representation.** The same gem color should represent the same
   musical note throughout the song; chords should be voiced consistently. Fast
   songs (>160 BPM): don't expect continuous 8th notes — thin by removing every
   4th note per half-measure.

## Vocals — NO per-difficulty chart derivation (exception)

**Rock Band vocals do not derive Hard/Medium/Easy from Expert the way the
instrument tracks do.** All four vocal difficulties share the **identical note
track** (same notes, same lyrics, same pitches). The only thing that changes
between Easy/Medium/Hard/Expert is the **leniency of the vocal hit engine** — the
game renders the note "tubes" wider or skinnier and fills the phrase meter more
or less strictly. There is **nothing to author per difficulty** in the chart
itself; AutoRB therefore needs only ONE vocal chart, which it applies to all four
difficulties.

Confirmed by the YARG wiki Difficulty page and multiple Rock Band community
sources (GameFAQs/RBN docs):

- *"On Vocals, all of the difficulty levels use the same note track, which means
  that all of the notes and lyrics are identical regardless of if you choose
  Easy, Medium, Hard or Expert. The only difference between the difficulties is
  the leniency of the hit engine."*
- The visual "note tube" gets **fatter (wider pitch tolerance) on Easy, skinnier
  on Expert**, exactly as the user described.
- Engine parameters (default preset, from the YARG wiki table):

  | Difficulty | Window size (semitone tolerance) | Perfect-pitch % | Fill ("Hit %") |
  |---|---|---|---|
  | Easy   | 1.7 semitones | 60% | 33% |
  | Medium | 1.4 semitones | (≈0.84 st) | 40% |
  | Hard   | 1.1 semitones | (≈0.66 st) | 45% |
  | Expert | 0.8 semitones | (≈0.48 st) | 58% |

  `Window size` = how far off-pitch the singer can be and still register;
  `Perfect-pitch %` = fraction of the window that scores 100%; `Hit %` = fraction
  of a phrase's credit needed for an "Awesome." Easy also requires less of the
  phrase to be sung correctly to score.

- Octave is ignored by the engine (singing any octave of the right note counts),
  so the charted pitch need not match the singer's range.
- Talkie (rap/spoken) sections are governed by the same leniency, not by separate
  notes.

**Implication for AutoRB:** the vocal MIDI (`PART VOCALS`) is written once and
packed into all four difficulty lanes (Easy 60 / Medium 72 / Hard 84 / Expert 96
+ pitch) unchanged. No `DifficultyReducer` step runs for vocals. The
difficulty-dependent behavior is entirely a runtime game-engine property, not
something we encode in the chart. (This is why AutoRB does not need a vocal
difficulty-derivation algorithm at all.)

## 1. Guitar / Bass

Gem **focus** per difficulty (which lanes players are eased into):

| Difficulty | Lanes in focus | Chords? | HOPOs? |
|---|---|---|---|
| Expert | all 5 (R G Y B O) | all types | yes (game + forced) |
| Hard | all 5 | no Green/Orange, no 3-note | yes |
| Medium | R G Y B (first 4) | 2-note only, no G/B G/O R/O, no 3-note | strums only (no HOPO) |
| Easy | R G Y (first 3) | **none** | strums only (no HOPO) |

- **Expert:** all 5 buttons; all chord types (1-2 G/R, 1-3 G/Y, 1-4 G/B, 1-5 G/O,
  and 3-note). A 3-note chord **must not contain both Green and Orange**. 1-5
  (Green/Orange) chords are allowed on Expert only and should be used sparingly
  (great for octaves). Chord notes begin and end together; a note/chord must end
  before the next begins.
- **Hard** = the "reasonable version of Expert." An expert player should be able
  to 100% Hard with minimal practice. Remove 16th-note-and-faster variations /
  subtle motion. **All Expert chords are retained** unless they represent
  harmonizing guitar parts or strong harmonics. Chord-to-chord HOPOs reduce to
  single→chord HOPOs. **No Green/Orange or 3-note chords** (Green/Blue and
  Red/Orange chords are acceptable, and a good Green/Orange replacement).
- **Medium** (the hardest to author, most-played by casuals): remove remaining
  8th notes, keep playable notes on **strong quarter-note beats**. Chords allowed
  but avoid fast chord changes. **No Green/Blue, Green/Orange, or Red/Orange
  chords; no 3-note chords.** **Pull durations back** — general rule: leave a
  quarter-note gap between notes (pull every duration back an 8th so dotted-8ths
  become 16ths; if a tail looks too short, pull to a 16th). Add **orange** gems
  only in appropriate, infrequent places (unique sections, bridges, solos, final
  notes) to limit hand-position shifts; restrict patterns to 4 lanes at a time.
- **Easy:** remove remaining **quarter** notes; leave **half-note** spaces between
  strums. **No chords at all** — reduce every chord to its most prominent single
  note. Sustains pulled back an extra 1/16 beyond Medium (≥ 1/4-note gap; if too
  short, collapse to a single strum). Add blue/orange in appropriate spots but
  **restrict added patterns (including orange) to the top three colors
  (Y B O)** to minimize hand movement.
- **HOPOs:** normally game-generated. Forced HOPOs are used sparingly; **never
  force HOPOs on Medium or Easy**. Repeating same-color gems should always be
  strummed (a forced HOPO after the same color won't register).
- **Bass:** same rules as guitar; maintain consistency **within each section**
  (bassists change register — drop an octave in the chorus, slide up in the
  bridge — so author each section to the pattern that fits, consistent within it).

## 2. Drums (standard 4-pad + kick)

Lane mapping in AutoRB: `0=kick, 1=snare, 2=hat, 3=tom/ride, 4=crash`. RB
conventions the docs mandate:
- **Crash should almost always be Green** (lane 4 in our map). Different toms =
  different gems. Snare and crash are **always more important than the kick** —
  author accordingly.
- **No 3-pad simultaneous hits** ("three gems cannot be placed together to be hit
  together; two will do").
- **No kicks on off-beats.** Remove kick gems from **all fills** (drum fills must
  contain no kicks).
- Avoid crossovers (hi-hat↔cymbal same-hand reach) except via the "disco flip"
  event; strong open hi-hats best map to the Blue pad (lane 3) when Blue is free
  in that section.

### 2.1 Double bass pedals — THE big one

Rock Band **does not support fully-authored double bass** in most cases. The
official rule (Drum Review Process): *"We don't support fully authored double
bass in most cases… so usually we just author what the drummer is playing with
their right foot."* Slow enough double-bass (a steady single-foot-paced stream)
**may** be kept (e.g. some Disturbed songs); otherwise the left-foot kicks are
cut. Authors may ship a separate **"(2x Bass Pedal)"** version containing all
kicks, provided a one-foot-playable version also exists.

**Implication for AutoRB:** Expert drums must **not** contain rapid alternating
double-bass kick streams. Any burst of kicks faster than one foot can play
should be reduced to a single-foot kick pattern (or, optionally, emit a parallel
`PART DRUMS_2X` chart for the full kicks). This directly addresses playtest
feedback that Expert had "a lot of double bass pedal hits which is not really
normally part of the rock band allowed patterns."

### 2.2 Difficulty derivation

- **Expert:** literal transcription (single-foot kicks only, per 2.1). All lanes,
  all crashes, durable cymbal/ride work.
- **Hard:** kicks should land **about halfway between Expert and Medium** in
  count. **No kicks during drum fills.** All crash cymbals reduced to a **single
  color** (no back-and-forth, no two-crash hits unless preceded by lots of space).
  Overall nuances scaled back while keeping the song's feel.
- **Medium** (intro to real drumming; hands + foot together, but not fully
  independent): **no kicks or snares between hi-hat/ride time-keeping gems** (no
  limb independence yet); **no 3-limb hits** (no simultaneous kick+snare+crash —
  drop the kick). Right hand not expected to keep **8th notes if >140 BPM**
  (use quarter notes; fewer kick places). **If >170 BPM, one kick per measure.**
  Fills/rolls reduced to **8th notes** (or less when faster) — a player will try
  to one-hand a same-color run. Crashes on **downbeats** get a kick underneath;
  syncopated/off-beat crashes get **no** kick. Tempo-based kick grid: for
  ~100–110+ BPM, consider authoring kicks only on quarter notes.
- **Easy** (never more than **2 limbs at once**): **no hand gems paired with
  kicks** — either a 2-hand beat with no kick, or a kick+snare beat, never all
  three. **No kick/crash pairing** (that's a Medium concept). Reduce Medium's 8th
  fills to quarter notes when fast. **If >170 BPM, one kick per measure.** If a
  kick/snare section feels too sparse, it's OK to add an extra kick on a
  quarter/eighth grid. Important off-beat accents: thin surrounding gems even
  more than Medium.

### 2.3 Tempo-driven kick density (practical ceiling)

| Tempo | Easy/Medium kick guidance |
|---|---|
| ≤ ~100–110 BPM | kicks on quarter notes OK |
| 140+ BPM | right-hand time-keeping drops to quarter notes (fewer kick places) |
| 170+ BPM | **one kick per measure** is enough |

## 3. Keys (5-lane)

5-lane Keys follows the **same difficulty derivation as Guitar/Bass** (literal
Expert → reduce one at a time). Because the hand never shifts, **all 5 colors are
allowed on every difficulty** (lane consistency is trivial — just ensure any
Expert color appears somewhere in each lower difficulty; only tricky when Expert
uses <5 colors, in which case apply the guitar/bass lane-consistency technique).

- **Expert:** all 5 buttons; all chords; subtle variations kept.
- **Hard:** remove 16th-and-faster rhythms; **durations same as Expert**; 3-note
  chords permitted but thin long 3-note passages.
- **Medium:** remove 8th notes, keep strong quarter-note beats; **2-note chords
  only** (no 3-note); durations pulled back (quarter-note gap, same as guitar).
- **Easy:** remove quarter notes; half-note spaces; **no chords** (reduce to most
  prominent single note).
- (Pro Keys adds 2-octave range-shift rules — out of scope for AutoRB's 5-lane
  Keys; see `docs.c3universe.com/rbndocs` Pro_Keyboard_Authoring if we ever add
  Pro Keys.)

## 4. How AutoRB maps to this today (gaps)

See [[instrument_charting]] for current serialization. Summary of gaps vs the
rules above (as of v0.0.99):

- **Double bass not handled:** Expert drums can contain rapid alternating kick
  bursts (false kicks from bass bleed + energy classifier). Needs a single-foot
  kick reducer (2.1).
- **Difficulty derivation is still heuristic:** `difficulty.py` does role/lane
  thinning + 1/8 grid for drums, and density-cap + lane-drop for guitar/bass.
  It does **not** yet enforce the specific per-difficulty rules above (no
  Green/Orange / 3-note chord bans on Hard/Medium; no "no chords on Easy";
  no Easy "max 2 limbs / no kick-hand pairing" for drums; no tempo-driven kick
  ceilings; no medium "no kick between time-keeping gems").
- **Sustain pull-back** is not difficulty-aware (Medium/Easy should pull sustains
  back further).
- **Lane consistency** is approximately maintained (every used lane appears in
  every difficulty) but not explicitly guaranteed.
- **Clone Hero export flattens drum difficulty:** `remap_drums_for_clone_hero`
  currently copies every hit into **all four** CH difficulty sections, so a
  Clone Hero playtest of Medium drums looks identical to Expert. This is a
  *rendering* bug, not a data bug — the packed MIDI already carries distinct
  per-difficulty drums. Fix: write the actual reduced drums to each CH difficulty
  section (Clone Hero supports per-difficulty drum charts).

## 4b. Implementation status (as of v0.1.1)

`autorb/transcribe/instruments/difficulty.py` now enforces these rules via
`_reduce_fretted` (guitar/bass/keys) and `_reduce_drums` (drums). Two behavior
decisions worth recording:

- **Drums — kick/snare snapping (Medium):** audio-derived kick and snare onsets
  jitter and rarely sit *exactly* on the hi-hat/ride time-keeping gem, so a
  naive "drop any kick/snare not simultaneous with a hat" rule deletes the entire
  basic beat (and then Easy, derived from Medium, becomes empty → crashes
  ForgeTool's `HandleDrumTrk` with a null gem track). Fix: a kick/snare that is
  within **0.13 s** of the nearest time-keeping gem is **snapped onto it** (kept)
  rather than dropped; only kicks/snares with no nearby hat are discarded.
- **Lane consistency is safe-placement only:** `_ensure_lane_consistency` adds
  any Expert lane missing from a lower difficulty, but only at an occurrence
  where adding it would **not** recreate a forbidden chord (Hard Green/Orange &
  3-note; Medium Green/Blue, Green/Orange, Red/Orange & 3-note; Easy any chord).
  If no safe slot exists for a lane, that lane is left out of the lower difficulty
  rather than violate a hard authoring rule. This prevents the old bug where a
  missing orange was re-added at the G/O chord it was just removed from.
- **Vocals have no per-difficulty reducer.** All four vocal difficulties share
  the identical note track; only the game's hit-engine leniency differs
  (Easy 1.7 / Medium 1.4 / Hard 1.1 / Expert 0.8 semitone tolerance; OD fill
  33/40/45/58 %). No code change is required for vocal difficulty.

## 5. Sources

- Guitar and Bass Authoring — `docs.c3universe.com/rbndocs/Guitar_and_Bass_Authoring`
- Guitar/Bass Review Process; Drum Review Process; Common Authoring Mistakes
- Drum Authoring — `docs.c3universe.com/rbndocs/Drum_Authoring`
- 5 Lane Keyboard Authoring; Pro Keyboard Authoring (C3)
- Rock Band chart-format reference (MIDI notes / lane conventions)
- YARG wiki Difficulty page (confirms Easy 3-fret focus, etc.)
