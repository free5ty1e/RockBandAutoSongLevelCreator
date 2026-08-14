# Feature Plan: LRC-Line Vocal Phrase Management

## Overview
Fix vocal phrase boundaries to use each `.lrc` line timestamp as the **start of a vocal phrase**, replacing the current fixed 2-bar measure window fallback. This aligns phrase boundaries with the actual song structure for correct scoring, overdrive activation, and visual phrase markers in Rock Band.

---

## Current State (v0.0.76)

### Problem
- Vocal phrases currently use **fixed 2-bar measure windows** (phrase_ticks = 2 * 4 * 480 = 3840 ticks)
- Phrase boundaries fall on measure grid, not actual lyrical phrases
- Results in:
  - Wrong phrase scoring (phrases split mid-lyric or merged across lines)
  - Overdrive activation at wrong moments
  - Visual phrase markers don't match lyrics
  - "Phrase" markers in MIDI don't align with `.lrc` lines

### Current Implementation (`midi_generator.py`)
```python
phrase_measures = 2  # Hardcoded
phrase_ticks = phrase_measures * beats_per_measure * ticks_per_beat
# Opens phrase at first note, then every phrase_ticks thereafter
```

---

## Target Architecture

### Core Principle
**Each `.lrc` line timestamp = start of one vocal phrase.**

### LRC Format
```
[mm:ss.xx]Lyric text for this phrase
[mm:ss.xx]Next phrase starts here
```
- Each timestamped line = one vocal phrase
- Phrase ends at the **next line's timestamp** (or song end)
- Empty lines or lines without timestamps are ignored

### Phrase Properties
| Property | Source |
|----------|--------|
| Start time | `.lrc` line timestamp |
| End time | Next `.lrc` line timestamp (or song end) |
| Text | Full line text after timestamp |
| Overdrive | Detected from special markers (see below) |

---

## Implementation Plan

### Phase 1: LRC Phrase Parsing (Week 1)

#### 1.1 New Module: `autorb/transcribe/phrases.py`
```python
@dataclass
class VocalPhrase:
    text: str           # Full line text
    start: float        # Line timestamp (seconds)
    end: float          # Next line timestamp or song end
    is_overdrive: bool  # Whether phrase has overdrive marker
    is_freestyle: bool  # Freestyle vocals marker (RB4)
    is_talkie: bool     # Talkie/spoken section marker
```

#### 1.2 LRC Phrase Parsing
```python
def parse_lrc_phrases(lrc_path: Path, song_end_time: float) -> List[VocalPhrase]:
    """
    Parse .lrc file into vocal phrases.
    
    Each timestamped line = one phrase.
    Phrase end = next line's start (or song_end_time).
    """
    # Parse all [mm:ss.xx] lines
    # Group into phrases with start/end times
    # Detect special markers:
    #   [od] or (overdrive) = overdrive phrase
    #   [fs] or (freestyle) = freestyle phrase
    #   [tk] or (talkie) = talkie phrase
```

#### 1.3 Special Marker Detection
| Marker | Meaning | MIDI Encoding |
|--------|---------|---------------|
| `[od]` or `(overdrive)` | Overdrive activation phrase | Text event `[od]` at phrase start |
| `[fs]` or `(freestyle)` | Freestyle vocals (RB4) | `(freestyle_vocals 1)` in songs.dta |
| `[tk]` or `(talkie)` | Spoken/talkie section | Pitch 0 note with "talkie" lyric |
| `[br]` or `(break)` | Vocal break (no lyrics) | Empty phrase, just timing |

### Phase 2: Integrate Phrases into Sync Pipeline (Week 1-2)

#### 2.1 Pass Phrases Through `step4_sync.py`
```python
def sync_lyrics_to_beats(..., lrc_phrases: List[VocalPhrase] = None):
    # If lrc_phrases provided, use them for phrase boundaries
    # Otherwise fall back to 2-bar measure grid
    # Attach phrase_id to each word/syllable
```

#### 2.2 Attach Phrase ID to Words/Syllables
```python
# In sync_lyrics_to_beats():
for word in refined:
    # Find which phrase this word belongs to
    word["phrase_id"] = find_phrase_for_time(word["start"], lrc_phrases)
    word["phrase_start"] = lrc_phrases[word["phrase_id"]].start
    word["phrase_end"] = lrc_phrases[word["phrase_id"]].end
```

### Phase 3: MIDI Phrase Marker Generation (Week 2)

#### 3.1 Modify `midi_generator.py` - Phrase Markers
```python
# Current: fixed 2-bar phrases
# New: phrase boundaries from lrc_phrases

def build_vocal_track(..., lrc_phrases: List[VocalPhrase] = None):
    if lrc_phrases:
        # Build phrase markers at exact phrase boundaries
        phrase_markers = []
        for i, phrase in enumerate(lrc_phrases):
            start_tick = time_to_tick(phrase.start) + count_in_ticks
            end_tick = time_to_tick(phrase.end) + count_in_ticks
            phrase_markers.append((start_tick, end_tick, phrase))
    else:
        # Fallback: 2-bar grid (current behavior)
```

#### 3.2 MIDI Phrase Events
| Event | MIDI Encoding | When |
|-------|---------------|------|
| Phrase start | `FF 01` text event `[prc_verse_N]` / `[prc_chorus_N]` | At phrase start tick |
| Phrase end | Implicit (next phrase start) | At next phrase start |
| Overdrive | Text event `[od]` | At overdrive phrase start |
| Freestyle | `(freestyle_vocals 1)` in songs.dta | Global flag |

#### 3.3 Rock Band Phrase Types
| Phrase Type | Text Marker | Usage |
|-------------|-------------|-------|
| Intro | `[prc_intro]` | Before first vocal phrase |
| Verse | `[prc_verse_N]` | N=1,2,3... |
| Chorus | `[prc_chorus_N]` | N=1,2,3... |
| Bridge | `[prc_bridge]` | Bridge section |
| Solo | `[prc_solo]` | Instrumental solo (no vocals) |
| Outro | `[prc_outro]` | Final vocal phrase |
| End | `[music_end]` + `[end]` | Song end |

**Heuristic for verse/chorus detection:**
- First phrases → verse
- Repeated text phrases → chorus
- After chorus → verse
- Long gaps → bridge/outro
- Allow manual override via LRC markers: `[vc]` = verse, `[ch]` = chorus

### Phase 4: Cache Integration (Week 2)

#### 4.1 Update `vocals_cache.json` v3
```json
{
  "version": 3,
  "lrc_phrases": [
    {
      "text": "Tonight I feel ambitious",
      "start": 0.61,
      "end": 2.23,
      "is_overdrive": false,
      "phrase_type": "verse"
    },
    {
      "text": "And so does my foot",
      "start": 2.23,
      "end": 3.87,
      "is_overdrive": false,
      "phrase_type": "verse"
    }
  ]
}
```

#### 4.2 Backward Compatibility
- If no `lrc_phrases` in cache → fall back to 2-bar grid
- If LRC file missing → fall back to 2-bar grid

### Phase 5: songs.dta & Overdrive (Week 2-3)

#### 5.1 Overdrive Phrases
- Overdrive phrases marked in LRC with `[od]` or detected heuristically
- Write `[od]` text event at phrase start in MIDI
- Set `overdrive` flag in `songs.dta` for that phrase

#### 5.2 Freestyle Vocals (RB4)
- Global flag: `(freestyle_vocals 1)` in songs.dta
- Per-phrase: freestyle sections marked in LRC with `[fs]`
- Adds diatonic guide lanes on Hard/Expert

---

## Technical Details

### LRC Phrase Format Extensions
```
# Standard
[00:12.34]Tonight I feel ambitious

# With phrase type
[00:12.34][vc]Tonight I feel ambitious
[00:15.23][ch]And so does my foot

# With overdrive
[00:18.45][od]As it sinks on the pedal

# Freestyle (RB4)
[00:22.90][fs]And for a moment I love everything

# Talkie/spoken
[00:34.66][tk]'Cause it's so perfect

# Empty phrase (instrumental break)
[00:39.48]
```

### Phrase Type Detection Heuristic (if no markers)
```python
def detect_phrase_type(phrases: List[VocalPhrase]) -> List[VocalPhrase]:
    # 1. First phrase → verse (or intro if instrumental)
    # 2. Repeated text → chorus
    # 3. Text similarity to previous chorus → chorus
    # 4. After chorus + different text → verse
    # 5. Long instrumental gap before → bridge
    # 6. Last phrases → outro
```

### MIDI Phrase Marker Encoding
```python
def add_phrase_marker(events, tick, marker_text):
    # Text event (FF 01)
    marker_bytes = marker_text.encode('latin1')
    events.append((tick, 0xFF, 0x01, len(marker_bytes), marker_bytes))
```

---

## File Changes

| File | Change |
|------|--------|
| `autorb/transcribe/phrases.py` | NEW - LRC phrase parsing |
| `autorb/transcribe/step4_sync.py` | Pass phrases, attach phrase_id to words |
| `autorb/export/midi_generator.py` | Generate phrase markers from LRC phrases |
| `autorb/export/dta_writer.py` | Add overdrive/freestyle flags per phrase |
| `autorb/audio/vocals.py` | Store phrases in cache v3 |
| `autorb/cli.py` | Pass LRC path for phrase parsing |
| `tests/test_lrc_phrases.py` | NEW - test phrase parsing & MIDI markers |

---

## Testing Strategy

### Unit Tests
1. **Parse LRC phrases**: Standard, with markers, empty lines
2. **Phrase timing**: Start/end times match LRC timestamps
3. **Special markers**: Overdrive, freestyle, talkie detection
4. **MIDI markers**: Correct text events at phrase boundaries

### Integration Tests
1. **Full pipeline**: LRC → phrases → MIDI → CON
2. **Phrase boundaries**: Verify phrase start/end in MIDI matches LRC
3. **Overdrive**: `[od]` phrases generate `[od]` MIDI events
4. **Fallback**: No LRC → 2-bar grid still works

### In-Game Validation
1. Load CON on RB3/RB4
2. Verify phrase sections match lyrics
3. Check overdrive activation at correct phrases
4. Verify freestyle vocals guide lanes on marked phrases

---

## Rollout Plan
1. **Feature branch**: `feature/lrc-line-vocal-phrases`
2. **Phase 1-2**: Phrase parsing + sync integration
3. **Phase 3**: MIDI phrase markers + dta updates
4. **Phase 4**: Cache v3 + full integration
5. **Version bump**: `0.0.77` (after pitch bending) or `0.0.78`
6. **Release**: Tag and CI build

---

## Success Criteria
1. **Phrase alignment**: Each LRC line = one vocal phrase in-game
2. **Scoring**: Phrase scoring matches lyrical phrases
3. **Overdrive**: Activates on `[od]` marked phrases
4. **No regression**: Songs without LRC phrases still use 2-bar grid
5. **RB4 freestyle**: `[fs]` phrases show guide lanes on Hard/Expert

---

## Dependencies
- No new Python dependencies
- Uses existing LRC parsing infrastructure

---

## Related Features
- **Pitch bending** (`vocal_pitch_continuous_bending_to_match_audio.md`): Pitch bend within phrases
- **Per-syllable pitch** (v0.0.76): Granular pitch tracking within phrases
- **Vocal harmony detection**: Future - separate harmony phrases