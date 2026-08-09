# Feature Plan: Full Instrument Chart Support (Guitar, Bass, Drums)

## Overview
Implement automatic transcription and charting for **Guitar**, **Bass**, and **Drums** to create fully playable Rock Band 3 charts for all instruments, following official Harmonix authoring standards and community best practices (C3, ScoreHero).

---

## Current State (v0.0.76)

### What Exists
- **Vocals only**: Per-syllable pitch tracking, syllable segmentation, MIDI generation
- **Placeholder tracks**: Guitar/Bass/Drums have single dummy notes per difficulty
- **Stem separation**: Demucs provides `drums.wav`, `bass.wav`, `other.wav` (guitar + keys), `vocals.wav`

### What's Missing
- No instrument-specific transcription
- No fret/note mapping to Rock Band's 5-lane highway
- No difficulty tiering (Expert → Medium → Easy reductions)
- No drum fill/overdrive logic
- No guitar/bass solo/BRE detection
- No held notes (sustains)
- No HOPO detection for guitar/bass

---

## Rock Band Charting Rules Reference

### Core Resources
- **Harmonix Authoring Guide** (official, leaked): `docs/rb3_authoring_guide.pdf`
- **C3 Documentation**: `https://customscreators.com/`
- **ScoreHero Forums**: Charting standards discussions
- **Magma/ForgeTool**: Official compiler reference

### Universal Rules (All Instruments)
| Rule | Detail |
|------|--------|
| **Tick resolution** | 480 PPQ (ticks per quarter note) |
| **Note representation** | MIDI note_on/note_off on specific pitches per lane |
| **Difficulties** | Expert → Hard → Medium → Easy (progressive reduction) |
| **Overdrive** | Specific phrases marked with `[od]` text event |
| **Song sections** | `[prc_verse_N]`, `[prc_chorus_N]`, `[prc_bridge]`, `[prc_outro]` |
| **Solo markers** | `[solo_start]` / `[solo_end]` for ALL instruments |
| **BRE markers** | `[bre_start]` / `[bre_end]` for ALL instruments |
| **Max note density** | ~16 notes/second (Expert cap) - beyond this, chart becomes unreadable |

### Guitar & Bass Shared Features
| Feature | Encoding |
|---------|----------|
| **Strummed note** | `note_on` velocity 100 |
| **HOPO** | `note_on` velocity 127 (adjacent lanes, ≤120ms) |
| **Chord** | Simultaneous `note_on` on multiple lanes, velocity 100 |
| **Held note / Sustain** | Long `note_on` duration (note_off at end) - game auto-detects "hold" if long enough |
| **Open string** | Pitch 67 (G4) - no fret held |
| **Solo section** | `[solo_start]` / `[solo_end]` text events |
| **BRE** | `[bre_start]` / `[bre_end]` text events |
| **Overdrive phrase** | `[od]` text event at phrase start |

### Drum Features
| Feature | Encoding |
|---------|----------|
| **Kick** | Pitch 36 (C2) |
| **Snare** | Pitch 38 (D2) |
| **Hi-Hat (closed)** | Pitch 42 (F#2) |
| **Hi-Hat (open)** | Pitch 46 (A#2) + `[hh_open]` text event |
| **Ride Cymbal** | Pitch 51 (D#3) |
| **Crash Cymbal** | Pitch 49 (D#3) |
| **Tom 1 (High)** | Pitch 48 (C3) |
| **Tom 2 (Mid)** | Pitch 45 (A2) |
| **Tom 3 (Low/Floor)** | Pitch 43 (G2) |
| **Fill / Overdrive activation** | `[od]` text event on fill section |
| **Solo section** | `[solo_start]` / `[solo_end]` |
| **BRE** | `[bre_start]` / `[bre_end]` |
| **Pro Drums (7-lane)** | Adds: Hi-hat pedal (44), 2nd Crash (52), China (55) |

---

## Instrument 1: Guitar (PART GUITAR)

### Lane Mapping (5-Lane Highway)
| Lane | Color | MIDI Pitch (Expert) | MIDI Pitch (Hard) | MIDI Pitch (Medium) | MIDI Pitch (Easy) |
|------|-------|---------------------|-------------------|---------------------|-------------------|
| 0 | Green | 60 (C4) | 72 (C5) | 84 (C6) | 96 (C7) |
| 1 | Red | 61 (C#4) | 73 (C#5) | 85 (C#6) | 97 (C#7) |
| 2 | Yellow | 62 (D4) | 74 (D5) | 86 (D6) | 98 (D7) |
| 3 | Blue | 63 (D#4) | 75 (D#5) | 87 (D#6) | 99 (D#7) |
| 4 | Orange | 64 (E4) | 76 (E5) | 88 (E6) | 100 (E7) |

**Open strum** (no fret): Pitch 67 (G4) on all difficulties

### Guitar-Specific Rules

#### 1. HOPO Detection
- Adjacent notes (lane difference ≤ 1) within 120ms
- Same direction (ascending or descending)
- Max 3 HOPOs in a row before requiring a strum
- Velocity 127 for HOPO notes

#### 2. Chords
- 2-5 simultaneous notes at same tick
- Velocity 100 each
- Common shapes: power chords (2 notes), full chords (3-5 notes)

#### 3. Held Notes (Sustains)
- Note duration ≥ ~1 beat (480 ticks) → game treats as "hold"
- Just use long MIDI note duration; no special encoding needed
- Hold ends at note_off

#### 4. Solo Sections
- Detect dense, melodic lead guitar passages
- Mark with `[solo_start]` / `[solo_end]` text events
- 2x scoring multiplier, no overdrive drain

#### 5. Big Rock Ending (BRE)
- Detect free-form ending section (usually last 10-20 seconds)
- Mark with `[bre_start]` / `[bre_end]`
- Any notes valid during BRE

#### 6. Difficulty Reduction (Expert → Hard → Medium → Easy)
| Target | Rules |
|--------|-------|
| **Hard** | Remove ~20-30% notes; keep all HOPOs and chords; preserve iconic riffs |
| **Medium** | Remove HOPOs (convert to strums); simplify chords to max 2 notes; remove orange lane notes |
| **Easy** | Single notes only; quarter/eighth note grid; no orange lane; only root notes of chords |

---

## Instrument 2: Bass (PART BASS)

### Lane Mapping (Identical to Guitar)
| Lane | Color | MIDI Pitch (Expert) |
|------|-------|---------------------|
| 0 | Green | 60 (C4) |
| 1 | Red | 61 (C#4) |
| 2 | Yellow | 62 (D4) |
| 3 | Blue | 63 (D#4) |
| 4 | Orange | 64 (E4) |

**Open string**: Pitch 67 (G4)

### Bass-Specific Rules

#### 1. HOPOs
- Same as guitar: adjacent lanes ≤ 120ms, velocity 127
- **More common than guitar** - bass lines are often melodic runs

#### 2. Chords
- **Rare but possible** - double stops, power chords
- Chart as simultaneous notes same as guitar

#### 3. Held Notes (Sustains)
- Very common in bass (whole notes, half notes)
- Long MIDI duration → game treats as hold
- No special encoding

#### 4. Slides / Techniques
- **No special encoding in Rock Band**
- Slides = chart as HOPOs or separate notes
- Slap/pop = regular notes (maybe higher velocity)
- Harmonics = regular notes at pitch
- Palm mute = regular notes (maybe lower velocity)

#### 5. Solo Sections
- Same `[solo_start]`/`[solo_end]` markers

#### 6. BRE
- Same `[bre_start]`/`[bre_end]` markers

#### 7. Difficulty Reduction
| Target | Rules |
|--------|-------|
| **Hard** | Remove ghost notes, simplify fast runs |
| **Medium** | Remove HOPOs, simplify rhythm to quarter/eighth |
| **Easy** | Root notes only, mostly quarter notes on downbeats |

---

## Instrument 3: Drums (PART DRUMS)

### Lane Mapping (Standard 5-Lane)
| Lane | Drum Element | MIDI Pitch (All Difficulties) |
|------|--------------|-------------------------------|
| 0 | Kick (Bass Drum) | 36 (C2) |
| 1 | Snare | 38 (D2) |
| 2 | Hi-Hat / Yellow Cymbal | 42 (F#2) |
| 3 | Blue Cymbal (Ride) | 46 (A#2) |
| 4 | Green Cymbal (Crash) | 49 (D#3) |

**Pro Drums (7-lane)**: Adds hi-hat pedal (44), second crash (52), china (55)

### Additional Drum Elements (Mapped to Lanes)
| Element | MIDI Pitch | Lane Mapping |
|---------|------------|--------------|
| Ride Cymbal (bow) | 51 | Lane 3 (Blue) |
| Tom 1 (High) | 48 | Lane 2 (Yellow) or 3 (Blue) |
| Tom 2 (Mid) | 45 | Lane 1 (Red) or 2 (Yellow) |
| Tom 3 (Low/Floor) | 43 | Lane 0 (Green) or 1 (Red) |
| Hi-Hat Open | 46 | Lane 3 (Blue) + `[hh_open]` text |
| Hi-Hat Pedal | 44 | Pro only |

**Mapping Strategy**: Toms/cymbals share lanes with hats/cymbals based on musical context

### Drum-Specific Rules

#### 1. Kick Drum
- Chart every kick hit
- Double kick (two kicks ≤ 100ms): chart both
- Ghost kicks: lower velocity (80)

#### 2. Snare
- Main backbeat = velocity 100
- Ghost notes = velocity 60-80
- Rimshot/cross-stick = regular snare pitch, no special encoding

#### 3. Hi-Hat / Ride
- Primary timekeeper
- Open hi-hat: pitch 46 + `[hh_open]` text event at open, `[hh_closed]` at close
- Ride cymbal: pitch 51 (or 46 for blue lane)

#### 4. Cymbals
- Crash = pitch 49, velocity 100
- Choke = immediate note_off + `[choke]` text (optional)

#### 5. Toms
- Map to available lanes (Yellow/Blue/Red/Green)
- Tom rolls = rapid successive hits across tom lanes

#### 6. Fills & Overdrive
- **Fill detection**: ≥3 drum hits within 500ms across multiple lanes
- **Overdrive activation**: Place `[od]` text event at start of fill sections
- Typically 4-6 overdrive phrases per song, distributed across sections

#### 7. Solo Sections
- Drum solos marked with `[solo_start]`/`[solo_end]`

#### 8. BRE
- Free-form drumming at end: `[bre_start]`/`[bre_end]`

#### 9. Difficulty Reduction
| Target | Rules |
|--------|-------|
| **Hard** | Remove ghost notes, simplify tom runs, fewer cymbal variations |
| **Medium** | Ride → Hi-hat; remove tom fills; basic kick/snare/hat pattern |
| **Easy** | Basic rock beat only: kick on 1/3, snare on 2/4, hat eighth notes |

---

## Implementation Architecture

### Phase 1: Transcription Pipeline (Weeks 1-3)

#### 1.1 New Module: `autorb/transcribe/instruments/`
```
autorb/transcribe/instruments/
├── __init__.py
├── guitar.py          # Guitar transcription
├── bass.py            # Bass transcription  
├── drums.py           # Drum transcription
├── onset_detection.py # Shared onset detection
├── pitch_to_lane.py   # Pitch → 5-lane mapping (guitar/bass)
├── drum_classifier.py # Drum element classification
└── difficulty.py      # Difficulty reduction engine
```

#### 1.2 Guitar Transcription (`guitar.py`)
```python
def transcribe_guitar(stem_path: Path, tempo_map: TempoMap) -> GuitarChart:
    """
    Input: other.wav (guitar + keys), tempo map
    Output: GuitarChart with notes per difficulty
    """
    # 1. Onset detection on guitar stem
    # 2. Pitch detection per onset (librosa pyin / crepe)
    # 3. Chord detection (simultaneous onsets within 50ms)
    # 4. Map pitches to 5-lane frets (with tuning detection)
    # 5. Detect HOPOs (adjacent lanes, ≤120ms, same direction)
    # 6. Detect held notes (duration ≥ 480 ticks)
    # 7. Detect solo sections (dense melodic passages)
    # 8. Detect BRE (free-form ending)
    # 9. Generate Expert chart
    # 10. Apply difficulty reduction for Hard/Medium/Easy
```

#### 1.3 Bass Transcription (`bass.py`)
```python
def transcribe_bass(stem_path: Path, tempo_map: TempoMap) -> BassChart:
    """
    Input: bass.wav, tempo map
    Output: BassChart with notes per difficulty
    """
    # 1. Onset detection on bass stem
    # 2. Fundamental pitch detection (pyin fmin=30, fmax=250)
    # 3. Map to 5-lane frets (with tuning detection)
    # 4. Detect HOPOs (same as guitar)
    # 5. Detect chords (simultaneous onsets - rare)
    # 6. Detect held notes (duration ≥ 480 ticks - common)
    # 7. Detect solo sections
    # 8. Detect BRE
    # 9. Generate Expert chart
    # 10. Apply difficulty reduction
```

#### 1.4 Drum Transcription (`drums.py`)
```python
def transcribe_drums(stem_path: Path, tempo_map: TempoMap) -> DrumChart:
    """
    Input: drums.wav, tempo map
    Output: DrumChart with notes per difficulty
    """
    # 1. Multi-band onset detection (kick/snare/hat/cymbals/toms frequency bands)
    # 2. Classify each onset: kick, snare, hi-hat, ride, crash, tom1/2/3
    # 3. Detect open/closed hi-hat transitions
    # 4. Detect fills (multi-lane bursts ≥3 hits/500ms)
    # 5. Map to drum lanes
    # 6. Detect solo sections
    # 7. Detect BRE
    # 8. Generate Expert chart
    # 9. Apply difficulty reduction
```

### Phase 2: Shared Components

#### 2.1 Pitch to Lane Mapping (`pitch_to_lane.py`)
```python
def detect_tuning(pitches: List[float]) -> Tuning:
    """Detect guitar/bass tuning from pitch distribution."""
    # Standard EADGBE, Drop D, Drop C, etc.

def pitch_to_fret_string(pitch: float, tuning: Tuning) -> (string, fret):
    """Convert pitch to (string_index, fret) for 5-lane mapping."""
    # String 0=high E, 4=low E (bass: 0=G, 3=E)
    # Fret 0=open, 1-22
    # Map to 5 lanes: each lane = one fret position per string

def fret_to_lane(string: int, fret: int) -> int:
    """Map (string, fret) to 0-4 lane."""
    # Simplified: lane = fret % 5 (with open=special)
```

#### 2.2 Drum Classifier (`drum_classifier.py`)
```python
def classify_drum_onset(audio_segment: np.ndarray, sr: int) -> DrumElement:
    """
    Frequency-band classification:
    - Kick: 40-100Hz, high energy
    - Snare: 150-250Hz + broadband noise
    - Hi-Hat: 6-12kHz, short decay
    - Ride: 4-8kHz, longer decay, tonal
    - Crash: 4-8kHz, very loud, long decay
    - Toms: 80-300Hz, tonal, medium decay
    """
```

#### 2.3 Difficulty Reduction Engine (`difficulty.py`)
```python
class DifficultyReducer:
    """Shared reduction logic for all instruments."""
    
    def reduce(self, expert_chart: Chart, instrument: str, target: str) -> Chart:
        """
        instrument: 'guitar' | 'bass' | 'drums'
        target: 'hard' | 'medium' | 'easy'
        """
        if target == 'hard':
            return self._to_hard(expert_chart, instrument)
        elif target == 'medium':
            return self._to_medium(self._to_hard(expert_chart, instrument), instrument)
        elif target == 'easy':
            return self._to_easy(self._to_medium(self._to_hard(expert_chart, instrument), instrument), instrument)
    
    def _to_hard(self, chart, instrument):
        # Remove ~20-30% notes, preserve rhythm contour
        # Keep all HOPOs, chords, holds
        # Cap at max density (16 notes/sec)
    
    def _to_medium(self, chart, instrument):
        # Guitar/Bass: Remove HOPOs, max 2-note chords, no orange lane
        # Drums: Ride→Hat, remove toms, simplify fills
    
    def _to_easy(self, chart, instrument):
        # Guitar/Bass: Single notes only, quarter/eighth grid, root notes only
        # Drums: Basic rock beat only
```

### Phase 3: MIDI Generation Integration (Week 4)

#### 3.1 Update `midi_generator.py`
```python
def build_instrument_tracks(
    guitar_chart: GuitarChart,
    bass_chart: BassChart, 
    drum_chart: DrumChart,
    tempo_map: TempoMap,
    count_in_ticks: int
) -> List[MidiTrack]:
    tracks = []
    tracks.append(build_guitar_track(guitar_chart, tempo_map, count_in_ticks))
    tracks.append(build_bass_track(bass_chart, tempo_map, count_in_ticks))
    tracks.append(build_drum_track(drum_chart, tempo_map, count_in_ticks))
    return tracks
```

#### 3.2 Per-Difficulty Track Structure
```
PART GUITAR
├── Expert (lane_base=60): lanes 60,61,62,63,64 + open=67
├── Hard (lane_base=72): lanes 72,73,74,75,76 + open=67
├── Medium (lane_base=84): lanes 84,85,86,87 + open=67 (no orange)
└── Easy (lane_base=96): lanes 96,97,98,99 + open=67 (no orange/blue)

PART BASS (same lane structure as guitar)

PART DRUMS
├── Expert: kick=36, snare=38, hat=42, ride=46/51, crash=49, toms=43/45/48
├── Hard: same, fewer cymbal variations
├── Medium: kick=36, snare=38, hat=42 only
└── Easy: kick=36, snare=38, hat=42 only (simplified)
```

### Phase 4: songs.dta & Overdrive (Week 4-5)

#### 4.1 Overdrive Phrase Detection
```python
def detect_overdrive_phrases(all_charts, vocal_phrases) -> List[OverdrivePhrase]:
    """
    Sources for overdrive phrases:
    - Guitar: solo sections, dense chord sections
    - Bass: prominent melodic runs
    - Drums: fill sections (primary source)
    - Vocals: designated phrases
    
    Select ~4-6 per song, distributed across sections.
    Align to phrase boundaries (from LRC vocal phrases).
    """
```

#### 4.2 Update `dta_writer.py`
```python
def write_songs_dta(..., instrument_charts: Dict) -> str:
    # Add overdrive phrases per instrument
    # Add solo sections for all instruments
    # Add BRE markers if detected
    # Set difficulty ranks per instrument (1-6 based on note density)
    # All instruments get solo/BRE/OD support
```

---

## File Changes

| File | Change |
|------|--------|
| `autorb/transcribe/instruments/guitar.py` | NEW - Guitar transcription |
| `autorb/transcribe/instruments/bass.py` | NEW - Bass transcription |
| `autorb/transcribe/instruments/drums.py` | NEW - Drum transcription |
| `autorb/transcribe/instruments/onset_detection.py` | NEW - Shared onset detection |
| `autorb/transcribe/instruments/pitch_to_lane.py` | NEW - Pitch → 5-lane + tuning detection |
| `autorb/transcribe/instruments/drum_classifier.py` | NEW - Drum element classification |
| `autorb/transcribe/instruments/difficulty.py` | NEW - Difficulty reduction |
| `autorb/export/midi_generator.py` | Add instrument track builders |
| `autorb/export/dta_writer.py` | Add overdrive, solos, BRE, difficulty ranks for all instruments |
| `autorb/audio/separation.py` | Enhance drum stem processing |
| `autorb/cli.py` | Add `--skip-instruments` flag |
| `tests/test_instrument_transcription.py` | NEW - Transcription tests |
| `tests/test_difficulty_reduction.py` | NEW - Difficulty tests |

---

## Technical Dependencies

### New Python Dependencies
```
# Add to requirements.txt
librosa>=0.10.0        # Already present - onset/pitch
crepe>=0.0.12          # High-quality pitch detection (optional)
madmom>=0.16.1         # Drum onset detection, tempo
basic-pitch>=0.2.0     # Already present - can use for guitar/bass
scikit-learn>=1.3.0    # For drum classification if needed
```

---

## Testing Strategy

### Unit Tests
1. **Guitar**: Pitch → lane mapping, HOPO detection, chord detection, hold detection
2. **Bass**: Fundamental detection, HOPO detection, hold detection
3. **Drums**: Element classification, fill detection, open/closed hat
4. **Difficulty**: Reduction preserves rhythm, removes correct notes, caps density

### Integration Tests
1. **Full pipeline**: Audio → stems → charts → MIDI → CON
2. **MIDI validation**: Correct pitches per difficulty, text events (solo, BRE, OD)
3. **ForgeTool**: CON → PKG conversion succeeds
4. **In-game**: Load on RB3/RB4, all 4 instruments playable

### Reference Songs for Validation
| Song | Source | Purpose |
|------|--------|---------|
| "Down" by 311 | Official DLC | Baseline for all instruments |
| "Smells Like Teen Spirit" | Custom (known good) | Drum fill/OD validation |
| "Sweet Child O' Mine" | Custom | Guitar solo/BRE, bass holds |
| "Another One Bites the Dust" | Custom | Bass groove, HOPOs |
| "YYZ" | Custom | Pro drums, odd time, all instruments |

---

## Rollout Plan

### Milestone 1: Guitar MVP (v0.0.80)
- Pitch → lane mapping with tuning detection
- HOPO detection
- Chord detection
- Held notes (long duration)
- Solo/BRE detection
- Expert + placeholder Hard/Medium/Easy

### Milestone 2: Bass MVP (v0.0.81)
- Fundamental detection + tuning
- HOPOs, held notes (common)
- Chords (rare)
- Solo/BRE detection
- 4 difficulties

### Milestone 3: Drums MVP (v0.0.82)
- Kick/snare/hat classification
- Fill detection → overdrive phrases
- Basic cymbal/tom mapping
- Solo/BRE detection
- 4 difficulties + pro drums

### Milestone 4: Full Features & Polish (v0.0.83-0.0.85)
- Difficulty reduction for all instruments
- Overdrive phrase distribution across instruments
- songs.dta integration complete
- Density capping at 16 notes/sec
- In-game validation on all instruments

---

## Success Criteria

### Per Instrument
| Instrument | Criteria |
|------------|----------|
| **Guitar** | Playable Expert with HOPOs, chords, holds, solos, BRE; 4 difficulties |
| **Bass** | Playable Expert with HOPOs, holds, solos, BRE; 4 difficulties |
| **Drums** | Playable Expert with all elements, fills→OD, solos, BRE; 4 difficulties + pro |

### Overall
1. **ForgeTool conversion**: No crashes, all 4 tracks recognized
2. **In-game**: All 4 instruments selectable and playable
3. **Scoring**: Overdrive works on all instruments, phrases score correctly
4. **Difficulty**: Each tier feels appropriately easier
5. **Density**: Expert capped at ~16 notes/sec
6. **No regression**: Vocals still work perfectly

---

## Related Features
- **Vocal phrases** (v0.0.77): Phrase boundaries for overdrive alignment
- **Pitch bending** (v0.0.77): Not used for guitar/bass in RB (no pitch bend support)
- **Harmony vocals**: Future - separate vocal parts
- **Clone Hero export**: Reuse charts for CH format

---

## Notes & Open Questions

### Open Questions
1. **Drum separation quality**: Demucs drums stem mixes all elements. Frequency-band onset detection may suffice.
2. **Guitar vs Keys in `other.wav`**: Demucs puts guitar+keys together. Accept keys as guitar or add separation.
3. **Tuning detection**: Songs may be in Drop D, Drop C, etc. Need reliable detection from pitch distribution.
4. **Capo detection**: Acoustic songs with capo - detect and adjust fret mapping.
5. **Polyrhythms/odd time**: Handle tempo changes, odd meters in transcription.
6. **Max density enforcement**: Algorithm to thin notes while preserving feel when >16 notes/sec.

### Research Needed
- [ ] Analyze 10+ official DLC MIDI files for pattern statistics
- [ ] Benchmark drum frequency-band classifier accuracy
- [ ] Test difficulty reduction algorithms on known charts
- [ ] Validate MIDI output with Magma/ForgeTool
- [ ] Verify hold threshold (exact tick duration for "hold" detection)