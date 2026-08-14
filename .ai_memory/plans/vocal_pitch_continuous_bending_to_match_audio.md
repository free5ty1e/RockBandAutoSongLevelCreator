# Feature Plan: Continuous Vocal Pitch Bending

## Overview
Add MIDI pitch bend events to vocal notes so the chart continuously tracks the singer's actual pitch contour, rather than quantizing to discrete semitone steps. This enables smooth slides, vibrato representation, and precise pitch matching between the chart and audio.

---

## Background & Motivation

### Current State (v0.0.76)
- Each syllable's pitch contour is segmented into discrete notes at semitone boundaries
- Example: "ambitious" → 3 notes: `am`(A3), `bi`(A3), `tious`(B3)
- Slides represented as adjacent notes (no pitch bend)
- Vibrato ignored (single static note)

### Problem
- Discrete notes can't represent continuous pitch motion
- Singer's slides between notes sound "stepped" rather than smooth
- Vibrato isn't visually represented
- Scoring penalizes natural pitch variations that don't land exactly on semitones

### Target: Rock Band 3/4 Pitch Bend Support
- RB3/RB4 support MIDI pitch wheel (0xE0-0xEF) on vocal track
- Pitch bend range: ±2 semitones (standard for vocals)
- Allows continuous pitch tracking within each note

---

## Target Architecture

### Pipeline Flow
```
Audio → Demucs → WhisperX → Syllables → Dense pyin (full stem)
                                              ↓
                                    Continuous pitch bend segments
                                              ↓
                              MIDI Assembly: notes + pitch bend events
```

### Key Changes
1. **Pitch tracking**: Instead of segmenting at semitone boundaries, track continuous pitch within each note
2. **Pitch bend encoding**: Emit MIDI pitch wheel events (0xE0 + channel) alongside note_on/note_off
3. **Pitch bend range**: ±2 semitones (8192 = center, 0 = -2st, 16383 = +2st)

---

## Implementation Plan

### Phase 1: Continuous Pitch Extraction (Week 1)

#### 1.1 Modify `pitch_tracking.py` - Continuous Pitch per Note
```python
# Current: segments pitch at semitone change points
# New: keep continuous pitch within each note, emit pitch bend data

@dataclass
class ContinuousNoteSegment:
    start: float          # seconds
    end: float            # seconds
    base_midi: int        # base note (quantized to semitone)
    pitch_bend_cents: List[Tuple[float, float]]  # (time, cents from base)
    # OR: continuous f0 array for the segment
```

#### 1.2 Algorithm: Continuous Pitch Bend per Note
```
For each discrete note segment (from plateau detector):
  1. Extract f0 frames within [segment_start, segment_end]
  2. Convert to cents relative to base_midi: cents = 100 * log2(f0 / base_freq)
  3. Smooth pitch trajectory (median filter, 5-frame window)
  4. Downsample to pitch bend event rate (e.g., 50Hz = 20ms per event)
  5. Clamp to ±200 cents (±2 semitones) - anything beyond = split note
  6. Output: base_midi + pitch_bend_events [(tick, bend_value)]
```

#### 1.3 Pitch Bend Event Rate
- Rock Band updates pitch bend at MIDI tick resolution (480 PPQ)
- But practical limit: ~50-100 events/second max for smooth playback
- Downsample continuous pitch to ~50Hz (20ms intervals)
- Encode as MIDI pitch wheel: 14-bit value (0-16383), 8192 = center

### Phase 2: MIDI Pitch Bend Encoding (Week 2)

#### 2.1 MIDI Generator Changes (`midi_builder.py`)
```python
# Add pitch bend events to vocal track
def add_pitch_bend(track_events, tick, bend_value):
    # bend_value: 0-16383 (14-bit)
    lsb = bend_value & 0x7F
    msb = (bend_value >> 7) & 0x7F
    track_events.append((tick, 0xE0 | channel, lsb, msb))
```

#### 2.2 Pitch Bend Range
- Standard: ±2 semitones = ±200 cents
- MIDI: 0 = -200 cents, 8192 = 0 cents, 16383 = +200 cents
- Formula: `bend_value = 8192 + int(cents * 8192 / 200)`

#### 2.3 Vocal Track Channel
- Vocal track typically channel 0 (first track)
- Pitch bend events on same channel as notes

#### 2.4 Note + Pitch Bend Sync
- Pitch bend events must be interleaved with note_on/note_off at correct ticks
- Initial pitch bend at note_on should be 8192 (center)
- Pitch bend events continue until note_off

### Phase 3: Cache Format Update (Week 2)

#### 3.1 Updated `vocals_cache.json` v3
```json
{
  "version": 3,
  "syllable_pitches": [
    {
      "syllable_text": "tious",
      "syllable_start": 1.83,
      "syllable_end": 2.23,
      "note_segments": [
        {
          "start": 1.83,
          "end": 2.23,
          "base_midi": 71,
          "pitch_bend_events": [
            [1830, 8192],   // tick, bend_value (center at note start)
            [1850, 8200],   // slight upward bend
            [1870, 8250],
            [1890, 8300],
            [1910, 8200],
            [1930, 8192]    // back to center at note end
          ]
        }
      ],
      "is_trusted": true,
      "word_index": 3
    }
  ]
}
```

#### 3.2 Backward Compatibility
- v3 cache includes pitch_bend_events
- If missing: fall back to discrete notes (no pitch bend)
- Loader handles both v2 (discrete) and v3 (continuous)

### Phase 4: Integration & Validation (Week 3)

#### 4.1 Test Cases
1. **Slide detection**: "road" (C4→D4 slide) → single note with pitch bend
2. **Vibrato**: sustained note with ±50 cent oscillation → pitch bend oscillation
3. **Clean note**: no bend events (flat pitch)
4. **Large slide**: >2 semitones → split into two notes (bend range exceeded)

#### 4.2 In-Game Validation
- Load CON on RB3/RB4
- Verify pitch bend renders on vocal fretboard
- Check scoring with pitch bend (should be more forgiving)
- Test with vocal trainer mode

---

## Technical Details

### Pitch Bend MIDI Format
```
Status byte: 0xE0 | channel (0-15)
Data byte 1: LSB (7 bits)
Data byte 2: MSB (7 bits)
Combined: (MSB << 7) | LSB = 0-16383
```

### Tick Alignment
- Pitch bend events use same tick timeline as notes
- Insert at appropriate ticks between note_on and note_off
- Multiple pitch bend events per note allowed

### Pitch Bend Smoothing
- Raw pyin pitch is noisy → apply median filter (window=5 frames)
- Downsample to 50Hz (20ms) for event rate control
- Linear interpolation between events for smooth curve

### Edge Cases
| Scenario | Handling |
|----------|----------|
| Bend exceeds ±200 cents | Split into two discrete notes |
| Unvoiced frames in middle | Hold last pitch bend value |
| Note too short (<80ms) | No pitch bend (single static note) |
| Multiple bends in one syllable | Each plateau segment gets own note + bends |

---

## Dependencies
- No new Python dependencies (uses existing librosa, numpy)
- MIDI encoding uses existing mido/struct

---

## File Changes

| File | Change |
|------|--------|
| `autorb/transcribe/pitch_tracking.py` | Add continuous pitch extraction + pitch bend event generation |
| `autorb/export/midi_builder.py` | Encode pitch bend events in vocal track |
| `autorb/audio/vocals.py` | Update cache to v3 with pitch_bend_events |
| `autorb/audio/step4_sync.py` | Pass pitch_bend_events through to MIDI generator |
| `tests/test_pitch_bending.py` | NEW - test continuous pitch extraction & MIDI encoding |

---

## Rollout Plan
1. **Feature branch**: `feature/continuous-pitch-bending`
2. **Phase 1-2**: Implement pitch extraction + MIDI encoding, test locally
3. **Phase 3**: Cache migration, full pipeline integration
4. **Phase 4**: Manual validation on 3+ songs, CON+PKG test
5. **Version bump**: `0.0.77`
6. **Release**: Tag `v0.0.77`

---

## Success Criteria
1. **Slide accuracy**: "road" (C4→D4) renders as single note with smooth pitch bend
2. **Vibrato visible**: Sustained notes show pitch oscillation on fretboard
3. **No regression**: Discrete notes still work for clean pitches
4. **Scoring**: Pitch bend notes score more naturally (less penalized for microtonal variation)
5. **Performance**: <10% pipeline slowdown