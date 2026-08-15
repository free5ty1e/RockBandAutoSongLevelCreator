# AutoRB Knowledge Base - Rock Band Difficulty-Chartaing Guidelines

The authoritative rules for deriving **Hard / Medium / Easy** from an **Expert** chart in Rock Band (Rock Band Network / C3 authoring standards). Captured at **v0.0.92** so AutoRB's difficulty reducer (`autorb/transcribe/instruments/difficulty.py`) can be brought in line with how human authors actually reduce charts. See also `[[instrument_charting]]` (current implementation + gaps).

## Sources

- **C3 / RBN "Guitar and Bass Authoring"** — `http://docs.c3universe.com/rbndocs/index.php?title=Guitar_and_Bass_Authoring` (mirror: `https://web.archive.org/web/20180413005329/docs.c3universe.com/rbndocs/index.php?title=Guitar_and_Bass_Authoring`). The canonical rules for every difficulty.
- **C3 / RBN "5-Lane Keyboard Authoring"** — `http://docs.c3universe.com/rbndocs/index.php?title=5_Lane_Keyboard_Authoring`. Same cascade for keys.
- **C3 / RBN "Guitar/Bass Review Process"** — `http://docs.c3universe.com/rbndocs/index.php?title=Guitar%2FBass_Review_Process`. What peer review checks per difficulty.
- **Rock Band Customs Blog "Authoring Guitar and Bass – Expert"** — `https://rockbandcustomsblog.wordpress.com/2020/05/05/guitar-bass-expert/`. Beginner-friendly restatement + gem-focus table.
- **mariteaux "Authoring Lower Difficulties"** — `https://mariteaux.somnolescent.net/modding/guitar-hero/tutorials/authoring-lower-difficulties/`. Practical, run-by-run simplification guide.
- **DowncharterPlus** (reference implementation) — `https://github.com/sammymuse/DowncharterPlus`. A tool that auto-derives lower difficulties from Expert; its rule table is a clean spec to mirror in code.
- **WIRED "How to Create a Song in Rock Band Network"** — `https://www.wired.com/2009/08/rock-band-network-2/`. Confirms lower-difficulty reduction is deliberately done by hand/carefully, not by blind density thinning.

## Core philosophy

1. **Expert is authored first** — a *literal rhythmic transcription* of the performance (barring general sloppiness). Then each lower difficulty is created by **copying the difficulty immediately above it and simplifying** — cascade **Expert → Hard → Medium → Easy**. Anything not on a higher difficulty is never on a lower one.
2. **Keep the rhythmic feel.** "Just removing every other 16th note is not always the correct way to reduce." Syncopated/upbeat notes are kept; the *space* left by removed notes is as important as the notes (never drag a preceding note out to fill the gap).
3. **Lane consistency:** every lane (colour) used in Expert must appear in **at least one gem in every lower difficulty**. Most songs use all 5; then Easy/Medium each need ≥1 gem per lane. Easy focus = Green/Red/Yellow (top 3); Medium focus = Green/Red/Yellow/Blue (top 4). If Expert omits a colour, lower diffs use the same reduced set. To satisfy consistency, authors **add** ≥1 orange to Medium and ≥1 blue+orange to Easy (in appropriate, hand-shift-friendly spots).

## Gem focus / MIDI note ranges (per difficulty)

| Difficulty | Guitar/Bass/Keys gem range | Focus lanes | Chords | HOPOs |
| :--- | :--- | :--- | :--- | :--- |
| Expert | 96–100 (C6–E6) / Keys 36–60 | all 5 | all types (incl. 3-note) | real + forced |
| Hard | 84–88 (C5–E5) | all 5 | 2-note only, no green+orange, no 3-note | real + forced (sparingly) |
| Medium | 72–75 (C4–D#4) | first 4 (no G/B, G/O, R/O chords) | 2-note only, no 3-note | not forced (effectively all strum) |
| Easy | 60–62 (C3–D3) | first 3 (Green/Red/Yellow) | **none** | none (all strum) |

(DowncharterPlus restates: Hard = real HOPOs, no green+orange/3-note chords, sustain gap 1/16; Medium = min spacing 1/4, gap-fill + beat-snap, all strum, sustain gap 1/4; Easy = min spacing dotted-1/4 (1.5 beat), no chords, all strum, sustain gap 1/4.)

## Hard (copy Expert, simplify)

- "Reasonable" version of Expert — an expert player should 100% Hard with minimal practice.
- All five gems in play. **No green-orange chords, no three-finger (3-note) chords, no fast single-green↔single-orange jumps.**
- Remove subtle variations to make the part consistent; remove 16th-note-or-faster motion/strumming (tempo-dependent). **No 32nd notes or faster.** Reduce triplets.
- **Chords in Expert are retained in Hard** (except when they represent harmonizing guitar parts, strong harmonics, or fast chord changes).
- **Real HOPOs kept**; forced HOPOs used sparingly. Repeating same-colour gems must stay strummed.
- **Sustain durations same as Expert** unless the slower Hard scroll rate makes them visually too short.

## Medium (copy Hard, simplify — the most important difficulty)

- Retain as much rhythmic + melodic feel of Expert/Hard as possible, but easier to play. Most casual players start here.
- Focus on first 4 lanes. **No Green/Blue, Green/Orange, or Red/Orange chords; no 3-note chords.** 2-note chords allowed (avoid fast changes).
- **Remove remaining 8th notes**; keep playable notes on strong quarter-note beats.
- **All Hard chords retained in Medium** unless special (harmonizing parts / strong harmonics / fast changes).
- **Durations pulled back:** leave a quarter note between the end of a note and the next; pull every duration back an 8th note (dotted-8ths → 16ths). Tail too short → pull to a 16th (avoid "stumpy" tails).
- Avoid quick 3–4 note jumps (Green↔Blue/Orange, Red↔Orange).
- **HOPOs not forced on Medium** (effectively all strums — a beginner should be able to downstrum every note).
- Min spacing between notes: a quarter note. Add orange gems where appropriate (lane consistency).

## Easy (copy Medium, simplify)

- "Really easy. No player will complain it's too easy." Single notes only — **no chords.**
- Focus on first 3 lanes (Green/Red/Yellow). Add blue+orange for lane consistency, but restrict added patterns to the top three colours to minimise hand movement.
- **Remove all remaining quarter notes when possible**; leave half-note spaces between strums.
- **Sustains pulled back an extra 1/16 from Medium**, with at least a 1/4-note gap to the next note; too short → single strum.
- **No HOPOs — all strum.** Min spacing: a half note (or dotted-1/4).
- Don't leave giant empty sections; you may author more gems in very busy sections.

## Keys / 5-lane keyboard (same cascade)

- Expert: all 5 buttons, all chord types.
- Hard: reasonable version; **no 3-note chords in long passages** (thin them); real HOPOs; durations same as Expert.
- Medium: first 4 lanes; **2-note chords allowed** (avoid fast changes); **no 3-note chords**; durations pulled back (quarter gap); HOPOs not forced.
- Easy: **no chords**; all 5 colours must still be used (lane consistency) but wrapped to stay playable; half-note spaces.

## Drums (from the same standards; lighter documentation)

- **Easy:** basic rock beat — kick on 1 & 3, snare on 2 & 4, hats on 8ths. Kick/snare/hat only; no tom/cymbal complexity.
- **Medium:** add simplified toms/fills; ride/crash → hi-hat.
- **Hard:** more fills, pro cymbals introduced.
- **Expert:** everything (all drums + cymbals + pro elements).

## How AutoRB's current reducer compares (v0.0.92 gap)

`autorb/transcribe/instruments/difficulty.py :: DifficultyReducer` **does cascade** Expert→Hard→Medium→Easy, but its rules do **not** follow the guidelines above:

- It uses **absolute density caps** (Expert 16 / Hard 14 / Medium 10 / Easy 6 notes/sec) and slides a 1s window to thin — instead of RB's rhythm-based reduction (remove 16ths, keep strong beats, lane consistency). A dense song gets under-reduced; a sparse one gets over-reduced.
- **No lane-consistency enforcement** (every Expert lane must appear in lower diffs).
- **HOPOs are not converted to strums** on Medium/Easy.
- **Sustains are not pulled back** per the quarter/1/16 gap rules.
- Medium drops the orange lane (correct) but never **adds** it back for consistency; chord handling is a naive "max 2 notes" rather than RB's chord-retention rules.
- Drum reduction (ride/crash→hihat, drop toms) is roughly RB-ish but simplified and unverified.
- On top of the reducer, the **packed single-MIDI-track encoding loses drum/keys difficulty differentiation** (CH needs fixed drum pitches), so the exported `.chart` shows identical drum/keys counts across difficulties regardless of the reducer — see `[[instrument_charting]]`.

**Action:** rewrite `DifficultyReducer` to implement the per-difficulty rule tables above (rhythm-grid-aware reduction, lane consistency, HOPO→strum on Medium/Easy, sustain pull-back), then resolve the packed-MIDI difficulty ambiguity so the reductions survive into the MIDI/`.chart`.
