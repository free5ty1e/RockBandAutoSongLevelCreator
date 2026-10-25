# Rock Band / Clone Hero Charting Guidelines — Engine Mechanics (verified)

Engine-level charting mechanics and authoring conventions, captured at
**v0.1.36** during the instrument-charting-accuracy research (web-reachable
sources + local converter ground truth). This page is the exact-semantics
companion to:

- [[difficulty_charting]] — the Harmonix RBN authoring *rules* per difficulty (the WHAT)
- [[instrument_charting]] — how AutoRB transcribes/serializes charts today
- [[charting_basics]] — the Clone Hero `.chart` format rules

Every rule below is verified against a named source (file + line-level where
possible), because charting-algorithm work must match the *engine* behavior,
not folklore. Where something could NOT be verified (original docs offline),
it is marked **TO-VERIFY** rather than asserted.

## 1. HOPO mechanics (natural + forced rules, per engine)

### 1.1 The CON path — what actually decides HOPOs in our Rock Band output

Ground truth: `tools/libforge/LibForge/LibForge/Midi/RBMidConverter.cs` — the
converter ForgeTool runs on our `notes.mid` (our PS4/RB output):

- `ToRBMid(mf, hopoThreshold = 170)` — the natural-HOPO window is **170 ticks
  at 480 tpq ≈ 0.354 beat** (a 16th note is 120, a dotted 16th is 180 — the
  window sits between them).
- **Natural HOPO rule** (`HandleGuitarBass`/`AddGem`): a *new* note (not part
  of a chord) is a HOPO iff (a) its start tick is within `hopoThreshold` ticks
  of the previous chord's start tick, AND (b) its lane bit is **disjoint from
  the previous chord's lanes**. Consequences:
  - **Same-lane repeats are always strums** (condition (b) fails).
  - **Chords are never natural HOPOs**: the first gem of a tight chord can be
    marked HOPO by the rule, but each *additional* gem in the same chord
    (within 5 ticks) clears `IsHopo` again unless a ForcedOn marker is active.
  - A chord following a single note (or vice versa) can be a natural HOPO only
    when lane-disjoint.
- **Forced HOPO / forced strum markers**: note events at pitch
  **base+5 (HopoOn) / base+6 (HopoOff = forced strum)** per difficulty —
  Easy 65/66, Medium 77/78, Hard 89/90, Expert 101/102 (same base-offset
  scheme as gems: Easy 60, Medium 72, Hard 84, Expert 96). ForcedOn overrides
  the natural rule (and survives same-lane); ForcedOff suppresses it.
- **Easy and Medium NEVER get HOPOs** — the converter hard-codes
  `IsHopo = diff > 1 ? hopo : false` (diff 0=Easy, 1=Medium). This is the
  engine-level confirmation of the RBN rule "never force HOPOs on Medium or
  Easy" ([[difficulty_charting]] §1); forced markers below Hard are useless.
- **Sustain/tail floors** (`NoTail`): a note renders with NO tail if
  `length ≤ 120 ticks` (a 16th note at 480 tpq) at any difficulty, OR
  `length ≤ 160 ticks` when the note is a HOPO or the difficulty is
  Easy/Medium/Hard. Practical authoring floor: **notes shorter than a 16th
  render as taps; HOPO sustains and lower-difficulty sustains must exceed
  ~⅓ beat to show a tail.**
- Trill/tremolo regions exist in the CON (`GTRTRILLS`, `LANEMARKER`
  tremolos; markers `TrillMarker=127`, `TremoloMarker=126`) — RB4-style
  auto-trill/tremolo lanes we do not emit today (a future fidelity item, low
  priority).

### 1.2 The Clone Hero path

- **SightRead** (`src/sightread/metadata.cpp :: midi_max_hopo_gap`): CH reads
  a `hopo_threshold` from `song.ini` with three semantics —
  `Resolution` (default) → `resolution/3 + 1` ticks (= **161 at 480 tpq**),
  `EighthNote` → `(resolution+3)/2`, `HopoFrequency` → explicit tick count.
- **Moonscraper Chart Editor** (`SongConfig.cs`):
  `FORCED_NOTE_TICK_THRESHOLD = 65` at its native 192 tpq → ≈163 ticks at 480
  tpq — i.e. **~⅓ beat**, matching SightRead's default.
- CH parses the same forced markers from MIDI (`apply_forcing` in
  `src/sightread/detail/midiconverter.cpp`: force-HOPO keys 65/77/89/101,
  force-strum keys 66/78/90/102) and **tap notes at key 104** (plus
  per-difficulty Sysex tap events).
- Moonscraper's natural rule (`Note.cs :: isNaturalHopo`) matches: not a
  chord, previous note exists, previous is a chord OR a different lane, and
  `tick - previous.tick` within the threshold.
- **Consensus**: the natural-HOPO window across engines is **~⅓ beat
  (161–170 ticks at 480 tpq; ≈125 ms at 150 BPM)**. LibForge (our CON path) is
  slightly more generous (170) than CH's default (161).

### 1.3 AutoRB gap (found while verifying, v0.1.36)

`guitar.py` step 5 computes `is_hopo` (adjacent lane, ≤120 ms, same
direction, non-open, non-chord → `velocity = 127`), but **no export layer
serializes it** — `midi_generator.py` and `clone_hero.py` contain no HOPO
handling at all. The CON's HOPOs are therefore 100% engine-derived from the
quantized tick gaps (LibForge's natural rule); the transcriber's HOPO intent
is dead code. Levers for the accuracy work:

1. Emit **forced-HOPO markers (base+5)** when the transcriber intends a HOPO
   the natural rule will not produce (same-lane trills, slightly-over-window
   runs, chord-to-chord HOPOs) — and forced-strum (base+6) where a natural
   HOPO is unwanted (e.g. deliberate fast strums).
2. Or shape quantization so intended HOPO pairs land inside the 170-tick
   window on different lanes (what the engine will do anyway — make the
   intent and the emergent behavior agree).
3. Remember Easy/Medium never HOPO — do not bother marking below Hard.

## 2. Lane / gem selection conventions (guitar, bass)

- **RBN philosophy** (per the rules distilled in [[difficulty_charting]] §0.5):
  the same gem color represents the same musical note throughout a section;
  chart the **relative fretting-hand position**, not absolute pitch. Official
  charts shift the whole lane mapping when the hand position changes.
- **Community-standard fret bands** (the EOF-era Guitar-Pro import
  convention, widely used; **TO-VERIFY** against the original RBN "Guitar
  Authoring" text — see §7): Green = frets 1–4, Red = 5–8, Yellow = 9–12,
  Blue = 13–16, Orange = 17+; power chords chart root + root+2 (two lanes
  up); the mapping is **per position window** — when the hand shifts, the
  bands shift with it.
- **AutoRB's implemented alternative** (v0.1.18, [[instrument_charting]]):
  strum-root clustering + monotonic rank-spread lanes — chosen deliberately,
  because (a) detected absolute pitch on distorted guitars is unreliable, and
  (b) the ORS recording sits a whole step below its tab's standard-tuning
  voicings, making absolute-fret mapping actively wrong. **Any tab-backed
  mode should prefer the TAB's actual frets** over detected pitch (see the
  accuracy plan, `.ai_memory/plans/`).
- **Chord limits** (engine-verified + [[difficulty_charting]] §1): 5-lane
  RB3 guitar allows up to 3-note chords, but a 3-note chord must not contain
  both Green and Orange; G/O 2-note chords are Expert-only and sparing;
  chords begin/end together (no overlapping gems — the v0.1.2 fix).
- **Open notes do not exist in RB3 5-lane guitar/bass** (the v0.0.97
  `OPEN_PITCH=67` encoding was a bug LibForge silently dropped). Open notes
  are a **Clone Hero-only extension** — never emit them on CON paths.
- **Bass is single-note** (RBN + v0.1.21 rule); deliberate double-stop
  detection is a roadmap item only.

## 3. Drums — encoding + authoring mechanics

- **Encoding (our pipeline)**: LibForge `HandleDrumTrk` accepts **base+lane**
  gems for drums exactly like guitar/bass (Easy 60–64 … Expert 96–100,
  lane = key − base) — confirmed at the key-range checks in
  `RBMidConverter.cs`; drum *animation* data is a separate 24–51 range.
  NOTE: the **official RB3/Magma MIDI format** for `PART DRUMS` is
  pitch-addressed (real drum notes 35–59, no difficulty offset) — that is
  what [[charting_basics]] describes. Our CON path diverges from the
  official format here because LibForge's converter expects the packed
  scheme; do not "fix" one into the other (both pages are correct about
  their own path — this note resolves the apparent contradiction).
- **Pro-drums markers** (`RBMidConverter.cs`): cymbal flags at
  `ProYellow=110`, `ProBlue=111`, `ProGreen=112` (yellow/blue/green cymbal
  on/off markers); CH uses the `.chart` `C` note modifier instead.
- **Marker pitches (drums)**: `OverdriveMarker=116`,
  `DrumFillMarkerStart=120`, `DrumFillMarkerEnd=124`, `SoloMarker=103`,
  `Roll1/2=126/127` (lane rolls). Big Rock Ending per [[rock_band_customs_domain]].
- **Authoring rules** (from the RBN docs, already captured in
  [[difficulty_charting]] §2 — keep them there; the engine adds):
  - Ghost notes are not representable in RB 5-lane (chart the audible hits).
  - **No 3-pad simultaneous hits**; the 2-hand limit
    (`limit_simultaneous_drums`, v0.1.17) matches the rule.
  - **No kicks inside drum fills** (fills are hands-only).
  - **Single-foot bass** (double-bass streams must be reduced; the
    "(2x Bass Pedal)" parallel-chart convention exists for full kicks).
  - Crashes on Green/cymbal lanes per the [[difficulty_charting]] lane table.

## 4. The packed-MIDI marker pitch table (quick reference)

| Pitch(es) | Meaning (per difficulty base: 60/72/84/96) |
| :--- | :--- |
| base+0 … base+4 | gems (lanes 0–4) — guitar/bass/keys AND drums (LibForge path) |
| base+5 / base+6 | forced HOPO on / forced strum off (65/66, 77/78, 89/90, 101/102) |
| 103 | solo section marker (length = solo duration; v0.1.20) |
| 104 | tap note (CH/`apply_forcing`; + Sysex per-difficulty taps) |
| 105 / 106 | vocal phrase / alt-phrase markers |
| 110 / 111 / 112 | pro-drums cymbal: yellow / blue / green |
| 116 | drum overdrive activation |
| 120 / 124 | drum fill start / end |
| 126 / 127 | drum lane roll / guitar tremolo+trill markers |
| 36–84 | vocals: real MIDI pitches (VocalsStart=36 … VocalsEnd=84) |

## 5. Difficulty-derivation cross-engine notes

- **onyx** (`mtolly/onyx`, Haskell — the most complete open-source RB customs
  toolchain) implements *auto-reduced difficulties for all instruments*, a 1x
  bass-pedal reduction of 2x charts, and "HOPO and tom/cymbal assignment"
  algorithms (its `doc/onyx.md`). When the DifficultyReducer rework
  ([[difficulty_charting]] §4) needs reference behavior, onyx is the
  code-level authority; the RBN docs are the rule-level authority.
- CH side: SightRead/Moonscraper derive nothing per-difficulty — CH just
  plays the four authored sections ([[charting_basics]] on why CH drum
  flattening must be fixed at export time).

## 6. AutoRB gaps found while verifying (v0.1.36 summary)

1. **HOPO intent never reaches the exports** (§1.3) — the biggest one.
2. **Solo markers exist** (pitch 103, v0.1.20) but trill/tremolo regions do
   not (126/127 unused).
3. **Forced-strum markers unused** — fast same-lane strums at Expert can be
   turned into natural HOPOs by the engine if the grid spacing collapses;
   forced-strum (base+6) is the tool to prevent that.
4. **Tap notes unused** — transcriber fast runs could become taps (104) for
   playability, a deliberate deviation from strict transcription (RBN allows
   taps sparingly for fast solos; **TO-VERIFY** the exact RBN tap policy).

## 7. Sources and their status (accessed 2026-10-24)

| Source | Status | Used for |
| :--- | :--- | :--- |
| `tools/libforge/.../Midi/RBMidConverter.cs` (LOCAL) | ground truth | HOPO state machine, marker pitches, drums encoding, NoTail floors |
| `GenericMadScientist/SightRead` (GitHub, main) | live | CH `hopo_threshold` semantics, forced/tap key parsing |
| `FireFox2000000/Moonscraper-Chart-Editor` (GitHub, master) | live | natural-HOPO rule + `FORCED_NOTE_TICK_THRESHOLD=65 @192` |
| `mtolly/onyx` (GitHub, master) | live | reference implementation (auto difficulty reduction, HOPO, tom/cymbal) |
| `docs.c3universe.com/rbndocs/*` (C3 mirror of Harmonix RBN docs) | **OFFLINE** (404 + TLS fail; Wayback has only the site root) | the difficulty rules already captured in [[difficulty_charting]]; the fret-band text is now TO-VERIFY |
| `creators.rockband.com` (original Harmonix host) | Wayback: only `RBNProgramTerms.pdf` | — |
| DuckDuckGo html/lite search endpoints | **BLOCKED from datacenter IPs** (anomaly challenge) | use Bing `format=rss`, `gh search code/repos`, archive.org APIs instead (see `devscripts/pi_extensions/web-tools.ts`) |

The fret-band lane convention (§2) is the one item now marked TO-VERIFY; when
a mirror of the RBN "Guitar and Bass Authoring" doc is found (the customs
community forums and EOF's bundled manual are the likely survivors), verify
the official text and de-mark this page.
