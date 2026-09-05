# Closed-Loop Development Plan: Perfect Rock Band Chart Generation

## Problem Statement
Current pipeline produces unplayable charts:
- **Drums**: No early detection (starts at 60s), wrong element classification, no easy difficulty
- **Guitar**: Intro chords don't match audio, double/triple strums merged into chords
- **Bass**: Starts 8 measures early, chords/rapid strums instead of holds
- **Root cause**: Stem separation bleed, wrong stem usage, no validation against ground truth

## Closed-Loop Architecture

### 1. Ground Truth Reference (Already Available)
```
output/known_good_cons/
  ├── known_good_*.con          # Perfectly synchronized reference CONs
  ├── reference_stems/          # Original stems used to create them
  └── metadata.json             # Known correct timing, notes, difficulties
```

### 2. Automated Evaluation Pipeline
```
evaluate_chart_accuracy.py
  ├── Load generated CON + reference CON
  ├── Extract MIDI from both
  ├── Align by tempo map
  ├── Compare per-instrument:
  │   ├── Note onset accuracy (ms)
  │   ├── Note pitch/lane accuracy
  │   ├── Sustain length accuracy
  │   ├── Difficulty distribution
  │   └── Overlap/dropout detection
  ├── Output: JSON report + visual diff (HTML)
  └── Exit code: 0 if all metrics pass thresholds
```

### 3. Stem Quality Analysis
```
analyze_stem_quality.py
  ├── For each stem (drums, bass, guitar, vocals, other):
  │   ├── Spectral analysis per time window
  │   ├── Cross-stem correlation (leakage detection)
  │   ├── Onset detection accuracy vs mixed audio
  │   └── Frequency band energy profiles
  ├── Output: Stem quality report + recommended stem for each instrument
  └── Used by pipeline to auto-select best stem per instrument
```

### 4. Iteration Loop
```
iterate_pipeline.py
  ├── 1. Run full pipeline on test song
  ├── 2. Run evaluate_chart_accuracy.py
  ├── 3. If metrics fail:
  │   ├── Analyze failure modes (timing, pitch, classification)
  │   ├── Generate targeted fix hypotheses
  │   ├── Apply highest-confidence fix
  │   └── Goto 1
  ├── 4. On success: commit, tag, run regression suite
  └── 5. Update known_good_cons if new song added
```

## Implementation Phases

### Phase 1: Evaluation Infrastructure (Week 1)
- [ ] Build `evaluate_chart_accuracy.py` with MIDI comparison
- [ ] Extract reference charts from `known_good_cons`
- [ ] Define accuracy thresholds per instrument
- [ ] HTML visual diff generator

### Phase 2: Stem Analysis & Selection (Week 1-2)
- [ ] Build `analyze_stem_quality.py`
- [ ] Auto-select best stem per instrument (may be mixed audio)
- [ ] Implement stem leakage correction

### Phase 3: Targeted Fixes (Week 2-3)
- [ ] **Bass**: Fix early start (energy gating), hold detection
- [ ] **Drums**: Kick detection from mixed audio, tom suppression
- [ ] **Guitar**: Chord window tuning, double-strum separation
- [ ] **All**: Note timing quantization to audio onsets

### Phase 4: Closed-Loop Automation (Week 3)
- [ ] `iterate_pipeline.py` with automated hypothesis generation
- [ ] Regression test suite with `known_good_cons`
- [ ] CI/CD integration

## Validation Metrics (Per Instrument)

| Metric | Threshold | Measurement |
|--------|-----------|-------------|
| Onset timing error | < 50ms | Median absolute deviation vs reference |
| Pitch/lane accuracy | > 95% | Note-by-note comparison |
| Sustain length error | < 100ms | Sustain end vs reference |
| False positive rate | < 5% | Extra notes not in reference |
| False negative rate | < 5% | Missing notes from reference |
| Difficulty distribution | Match reference | Note count per difficulty |

## Stem Strategy

### Current Problem
- Drum stem: Failed separation (quiet intro, no kick)
- Bass stem: Phantom early notes (stem bleed)
- Other stem: Contains drum bleed (good for drums intro)

### Solution: Multi-Stem Fusion
| Instrument | Primary Stem | Fallback | Fusion Strategy |
|------------|--------------|----------|-----------------|
| Drums | Drums stem | Mixed audio | Drums stem + mixed audio for kick |
| Bass | Bass stem | Mixed audio | Bass stem + energy gate |
| Guitar | Other stem | Mixed audio | Other stem + pitch filter |
| Keys | Other stem | Mixed audio | Pitch filter (high) |
| Vocals | Vocals stem | N/A | N/A |

## Immediate Next Steps (Start Now)

1. **Extract reference charts** from `known_good_cons`
2. **Build `evaluate_chart_accuracy.py`** - compare generated vs reference MIDI
3. **Analyze stem quality** for current test song
4. **Implement multi-stem drum detection** (drums stem + mixed audio)
5. **Fix bass energy gate** (already started)
6. **Run evaluation on current pipeline** → get baseline metrics

## Success Criteria
- All instruments start at correct time (±50ms)
- Note accuracy > 95% vs reference
- Zero same-lane overlaps
- Playable on all difficulties
- Passes evaluation on 3+ test songs