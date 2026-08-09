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
- No guitar solo/BRE detection
- No bass hammer-ons/pull-offs (HOPOs)
- No drum expert+ (pro drums) support

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
| **Solo markers** | `[solo_start]` / `[solo_end]` for guitar/bass |
| **BRE** | Big Rock Ending: `[bre_start]` / `[bre_end]` |

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

### Guitar-Specific Features

#### 1. Hammer-Ons / Pull-Offs (HOPOs)
- **Detection**: Adjacent notes ≤ 120ms apart, same direction
- **Encoding**: `note_on` with velocity 127 (vs 100 for strummed)
- **Rules**: Only on same string (adjacent lanes), max 3 in a row

#### 2. Tapping
- **Detection**: HOPOs spanning >2 lanes
- **Encoding**: Velocity 127 + special text event `[tap]`

#### 3. Strummed Chords
- **Multi-lane notes**: Simultaneous note_on on multiple lanes
- **Encoding**: Separate note_on events at same tick, velocity 100

#### 4. Solo Sections
- **Markers**: `[solo_start]` / `[solo_end]` text events
- **Scoring**: 2x multiplier, no overdrive drain

#### 5. Big Rock Ending (BRE)
- **Markers**: `[bre_start]` / `[bre_end]`
- **Charting**: Free-form strumming, any notes valid

#### 6. Difficulty Reduction Rules (Expert → Hard → Medium → Easy)
| Reduction | Rule |
|-----------|------|
| Expert → Hard | Remove 20-30% notes, keep pattern integrity |
| Hard → Medium | Remove HOPOs, simplify chords to 2-note max |
| Medium → Easy | Single notes only, remove orange lane |

---

## Instrument 2: Bass (PART BASS)

### Lane Mapping (Same as Guitar)
| Lane | Color | MIDI Pitch (Expert) |
|------|-------|---------------------|
| 0 | Green | 60 (C4) |
| 1 | Red | 61 (C#4) |
| 2 | Yellow | 62 (D4) |
| 3 | Blue | 63 (D#4) |
| 4 | Orange | 64 (E4) |

**Open string**: Pitch 67 (G4)

### Bass-Specific Features

#### 1. HOPOs
- Same as guitar but **more common** (bass lines are melodic)
- **Slides**: Adjacent notes with pitch bend (bass slides are common)

#### 2. Bass-Specific Techniques
- **Slap/Pop**: Velocity 127 + `[slap]` text event
- **Harmonics**: Pitch 2 octaves up + `[harm]` text event
- **Palm mute**: Lower velocity (80) + `[pm]` text event

#### 3. No Chords
- Bass is **always single notes** (no multi-lane chords)

#### 4. Solo Sections
- Same markers as guitar `[solo_start]`/`[solo_end]`

#### 5. Difficulty Reduction
| Reduction | Rule |
|-----------|------|
| Expert → Hard | Remove ghost notes, simplify runs |
| Hard → Medium | Remove HOPOs, simplify rhythm |
| Medium → Easy | Root notes only, quarter-note pulses |

---

## Instrument 3: Drums (PART DRUMS)

### Lane Mapping (5-Lane + Cymbals = 9 Total)
| Lane | Drum Element | MIDI Pitch (Expert) | MIDI Pitch (Hard) | MIDI Pitch (Medium) | MIDI Pitch (Easy) |
|------|--------------|---------------------|-------------------|---------------------|-------------------|
| 0 | Kick (Bass Drum) | 36 (C2) | 36 | 36 | 36 |
| 1 | Snare | 38 (D2) | 38 | 38 | 38 |
| 2 | Hi-Hat / Yellow Cymbal | 42 (F#2) | 42 | 42 | 42 |
| 3 | Blue Cymbal (Ride) | 46 (A#2) | 46 | - | - |
| 4 | Green Cymbal (Crash) | 49 (D#3) | 49 | - | - |

**Pro Drums (7-lane)**: Adds hi-hat pedal (44), second crash (52), china (55)

### Drum-Specific Features

#### 1. Drum Elements
| Element | Standard MIDI | Notes |
|---------|---------------|-------|
| Kick | 36 | Always charted |
| Snare | 38 | Main backbeat |
| Hi-Hat | 42 (closed), 46 (open) | Primary rhythm |
| Ride Cymbal | 51 | Alternative to hi-hat |
| Crash | 49 | Accents, fills |
| Tom 1 (High) | 48 | Fills |
| Tom 2 (Mid) | 45 | Fills |
| Tom 3 (Low/Floor) | 43 | Fills |

#### 2. Drum-Specific Rules

##### Kick Drum
- **Double kick**: Two kicks ≤ 100ms → chart both
- **Ghost kicks**: Lower velocity (80) for quiet kicks

##### Snare
- **Ghost notes**: Velocity 60-80 for quiet snares
- **Rimshot**: Velocity 127 + `[rim]` text event
- **Cross-stick**: Velocity 90 + `[xs]` text event

##### Hi-Hat
- **Open/Closed**: Text events `[hh_open]` / `[hh_closed]`
- **Pedal hi-hat**: Pitch 44 (pro drums only)

##### Cymbals
- **Crash**: Pitch 49, velocity 100
- **Ride**: Pitch 51, bell = velocity 127 + `[ride_bell]`
- **Choke**: Note_off immediately after note_on + `[choke]`

##### Toms
- **Tom rolls**: Rapid successive hits on multiple toms
- **Flam**: Two hits ≤ 30ms apart, second lower velocity

#### 3. Drum Fills & Overdrive
- **Fill detection**: ≥3 drum hits within 500ms, multi-lane
- **Overdrive phrases**: `[od]` markers on fill sections
- **Big Rock Ending**: Free-form drumming `[bre_start]`/`[bre_end]`

#### 4. Difficulty Reduction (Expert → Easy)
| Reduction | Rule |
|-----------|------|
| Expert → Hard | Remove ghost notes, simplify tom runs |
| Hard → Medium | Remove cymbal variations (ride→hat), simplify fills |
| Medium → Easy | Kick + snare + hat only, basic rock beat |

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
├── pitch_to_lane.py   # Pitch → 5-lane mapping
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
    # 3. Chord detection (simultaneous onsets)
    # 4. Map pitches to 5-lane frets
    # 5. Detect HOPOs, taps, chords
    # 6. Generate Expert chart
    # 7. Apply difficulty reduction for Hard/Medium/Easy
```

#### 1.3 Bass Transcription (`bass.py`)
```python
def transcribe_bass(stem_path: Path, tempo_map: TempoMap) -> BassChart:
    """
    Input: bass.wav, tempo map
    Output: BassChart with notes per difficulty
    """
    # 1. Onset detection on bass stem
    # 2. Fundamental pitch detection (pyin with fmin=30, fmax=250)
    # 3. Map to 5-lane frets
    # 4. Detect slides, slap/pop, harmonics
    # 5. Generate Expert chart (single notes only)
    # 6. Apply difficulty reduction
```

#### 1.4 Drum Transcription (`drums.py`)
```python
def transcribe_drums(stem_path: Path, tempo_map: TempoMap) -> DrumChart:
    """
    Input: drums.wav, tempo map
    Output: DrumChart with notes per difficulty
    """
    # 1. Source separation within drums stem (kick/snare/hh/toms/cymbals)
    #    - Use spectral clustering or trained classifier
    # 2. Onset detection per element
    # 3. Classify each onset: kick, snare, hi-hat, ride, crash, tom1/2/3
    # 4. Detect open/closed hi-hat, ghost notes, flams
    # 5. Detect fills (multi-element bursts)
    # 6. Map to drum lanes
    # 7. Generate Expert chart
    # 8. Apply difficulty reduction
```

### Phase 2: Difficulty Reduction Engine (Week 3)

#### 2.1 Shared Difficulty Reducer (`difficulty.py`)
```python
class DifficultyReducer:
    def reduce(self, expert_chart: Chart, target: str) -> Chart:
        """
        target: 'hard' | 'medium' | 'easy'
        """
        if target == 'hard':
            return self._to_hard(expert_chart)
        elif target == 'medium':
            return self._to_medium(self._to_hard(expert_chart))
        elif target == 'easy':
            return self._to_easy(self._to_medium(self._to_hard(expert_chart)))
    
    # Instrument-specific reduction rules
    def _to_hard(self, chart): ...
    def _to_medium(self, chart): ...
    def _to_easy(self, chart): ...
```

#### 2.2 Reduction Algorithms
| Technique | Description |
|-----------|-------------|
| **Note thinning** | Remove notes while preserving rhythm contour |
| **Pattern preservation** | Keep iconic riffs, remove filler |
| **Lane simplification** | Medium: max 2-note chords, Easy: single notes |
| **Technique removal** | Medium: no HOPOs, Easy: no orange lane |
| **Quantization** | Easy: snap to quarter/eighth notes |

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
    """
    Build PART GUITAR, PART BASS, PART DRUMS tracks
    with proper difficulty lanes and text events.
    """
    tracks = []
    
    # Guitar: 4 difficulties × 5 lanes
    tracks.append(build_guitar_track(guitar_chart, tempo_map, count_in_ticks))
    
    # Bass: 4 difficulties × 5 lanes  
    tracks.append(build_bass_track(bass_chart, tempo_map, count_in_ticks))
    
    # Drums: 4 difficulties × up to 9 lanes (pro)
    tracks.append(build_drum_track(drum_chart, tempo_map, count_in_ticks))
    
    return tracks
```

#### 3.2 Per-Difficulty Track Structure
```
PART GUITAR
├── Expert (lane_base=60)
├── Hard (lane_base=72) 
├── Medium (lane_base=84)
└── Easy (lane_base=96)

PART BASS
├── Expert (lane_base=60)
├── Hard (lane_base=72)
├── Medium (lane_base=84)
└── Easy (lane_base=96)

PART DRUMS
├── Expert (kick=36, snare=38, hat=42, ride=46, crash=49, toms=43/45/48)
├── Hard (same, fewer cymbals)
├── Medium (kick, snare, hat only)
└── Easy (kick, snare, hat only, simplified)
```

### Phase 4: songs.dta & Overdrive (Week 4-5)

#### 4.1 Overdrive Phrase Detection
```python
def detect_overdrive_phrases(
    guitar_chart: GuitarChart,
    bass_chart: BassChart,
    drum_chart: DrumChart,
    vocal_phrases: List[VocalPhrase]
) -> List[OverdrivePhrase]:
    """
    Overdrive phrases are typically:
    - Guitar: solo sections, dense chord sections
    - Bass: prominent melodic runs
    - Drums: fill sections
    - Vocals: designated phrases
    """
    # Combine all instrument overdrive candidates
    # Select ~4-6 per song, distributed across sections
    # Align to phrase boundaries
```

#### 4.2 Update `dta_writer.py`
```python
def write_songs_dta(..., instrument_charts: Dict) -> str:
    # Add overdrive phrases per instrument
    # Add solo sections for guitar/bass
    # Add BRE markers if detected
    # Set difficulty ranks per instrument (1-6 based on note density)
```

---

## File Changes

| File | Change |
|------|--------|
| `autorb/transcribe/instruments/guitar.py` | NEW - Guitar transcription |
| `autorb/transcribe/instruments/bass.py` | NEW - Bass transcription |
| `autorb/transcribe/instruments/drums.py` | NEW - Drum transcription |
| `autorb/transcribe/instruments/onset_detection.py` | NEW - Shared onset detection |
| `autorb/transcribe/instruments/pitch_to_lane.py` | NEW - Pitch → 5-lane mapping |
| `autorb/transcribe/instruments/difficulty.py` | NEW - Difficulty reduction |
| `autorb/export/midi_generator.py` | Add instrument track builders |
| `autorb/export/dta_writer.py` | Add overdrive, solos, BRE, difficulty ranks |
| `autorb/audio/separation.py` | Enhance stem separation for drums |
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
madmom>=0.16.1         # Drum transcription, onset detection
basic-pitch>=0.2.0     # Already present - can use for guitar/bass
scikit-learn>=1.3.0    # For drum element classification
```

### Drum Element Classification
Option A: **Spectral clustering** on drum stem (unsupervised)
- Separate kick/snare/hh/toms by spectral centroid, bandwidth

Option B: **Pre-trained classifier** (madmom or custom)
- Train on labeled drum hits
- Classify each onset

Option C: **Frequency-band onset detection** (simplest)
- Kick: 40-100Hz
- Snare: 150-250Hz + noise
- Hi-hat: 6-12kHz
- Toms: 100-300Hz
- Cymbals: 4-8kHz

---

## Testing Strategy

### Unit Tests
1. **Guitar**: Pitch → lane mapping, HOPO detection, chord detection
2. **Bass**: Fundamental detection, slide detection, technique detection
3. **Drums**: Element classification, fill detection, ghost notes
4. **Difficulty**: Reduction preserves rhythm, removes correct notes

### Integration Tests
1. **Full pipeline**: Audio → stems → charts → MIDI → CON
2. **MIDI validation**: Correct pitches per difficulty, text events
3. **ForgeTool**: CON → PKG conversion succeeds
4. **In-game**: Load on RB3/RB4, all instruments playable

### Reference Songs for Validation
| Song | Source | Purpose |
|------|--------|---------|
| "Down" by 311 | Official DLC | Baseline for all instruments |
| "Smells Like Teen Spirit" | Custom (known good) | Drum fill validation |
| "Sweet Child O' Mine" | Custom | Guitar solo/BRE |
| "Another One Bites the Dust" | Custom | Bass groove |
| "YYZ" | Custom | Pro drums, odd time |

---

## Rollout Plan

### Milestone 1: Guitar MVP (v0.0.80)
- Basic pitch → lane mapping
- Expert chart only
- No HOPOs/chords yet
- Placeholder Hard/Medium/Easy

### Milestone 2: Bass MVP (v0.0.81)
- Fundamental detection
- Single-note Expert chart
- Difficulty reduction

### Milestone 3: Drums MVP (v0.0.82)
- Kick/snare/hi-hat detection
- Basic rock beat charting
- Fill detection

### Milestone 4: Full Features (v0.0.83-0.0.85)
- Guitar: HOPOs, chords, tapping, solos, BRE
- Bass: Slides, slap/pop, harmonics
- Drums: All cymbals, toms, ghost notes, flams, pro drums
- Difficulty reduction for all
- Overdrive phrase detection
- songs.dta integration

---

## Success Criteria

### Per Instrument
| Instrument | Criteria |
|------------|----------|
| **Guitar** | Playable Expert chart with HOPOs, chords, solos; 4 difficulties |
| **Bass** | Playable Expert chart with slides/techniques; 4 difficulties |
| **Drums** | Playable Expert with all elements; fills, ghost notes; 4 difficulties + pro |

### Overall
1. **ForgeTool conversion**: No crashes, all tracks recognized
2. **In-game**: All 4 instruments selectable and playable
3. **Scoring**: Overdrive works, phrases score correctly
4. **Difficulty**: Each tier feels appropriately easier
5. **No regression**: Vocals still work perfectly

---

## Related Features
- **Vocal phrases** (v0.0.77): Phrase boundaries for overdrive alignment
- **Pitch bending** (v0.0.77): Guitar/bass pitch bend for slides
- **Harmony vocals**: Future - separate vocal parts
- **Clone Hero export**: Reuse charts for CH format

---

## Notes & Open Questions

### Open Questions
1. **Drum separation quality**: Demucs drums stem mixes all elements. Need better separation or frequency-band detection.
2. **Guitar vs Keys in `other.wav`**: Demucs puts guitar+keys together. May need additional separation or accept keys as guitar.
3. **Tuning detection**: Songs may be in Drop D, Drop C, etc. Need tuning detection for accurate fret mapping.
4. **Capo detection**: Acoustic songs with capo - detect and adjust fret mapping.
5. **Polyrhythms/odd time**: Handle tempo changes, odd meters in transcription.

### Research Needed
- [ ] Analyze 10+ official DLC MIDI files for pattern statistics
- [ ] Benchmark drum element classifiers
- [ ] Test difficulty reduction algorithms on known charts
- [ ] Validate MIDI output with Magma/ForgeTool