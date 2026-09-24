# AutoRB Closed-Loop Development: Final Summary

## Current State (v0.1.4)

### Pipeline Status
✅ Pipeline runs successfully end-to-end
✅ CON + PS4 PKG packaging works
✅ Clone Hero export works
✅ Stem separation (Demucs) works
✅ Vocal alignment (WhisperX) works
✅ Evaluation framework operational

### Critical Issues Remaining

| Instrument | F1 Score | Key Issues |
|------------|----------|------------|
| **Drums** | 0.15 | 70% notes missing, 190ms timing error, 12% lane accuracy, no intro detection |
| **Bass** | 0.20 | 50% missing, 133ms error, 8% lane accuracy, phantom early notes |
| **Guitar** | 0.36 | 47% over-charted, 140ms error, 14% lane accuracy, over-charting |
| **Vocals** | 0.00 | 0% expert notes, complete failure |

### Root Causes Identified

1. **Drum stem separation failure**: Demucs fails to extract quiet intro drums; drum stem has 0.0002 RMS in first 30s vs 0.023 in "other" stem
2. **Stem leakage**: "Other" stem contains drum bleed (kick 0.0045, snare 0.017), bass stem has drum bleed
3. **Bass phantom notes**: Stem separation bleed creates phantom notes in intro (energy gating partially fixed)
4. **Drum classification**: Over-aggressive hi-hat suppression (3 notes), tom over-detection (129→57)
5. **Guitar over-charting**: Basic Pitch detects keys/piano as guitar on shared "other" stem
6. **Vocal MIDI generation**: Complete failure - 0 expert notes

## Implemented Fixes (v0.1.4)

### Drums
- ✅ Multi-stem onset detection (drums stem + "other" stem for intro)
- ✅ Windowed onset detection with local normalization (30s windows)
- ✅ Boundary duplicate removal (30s window boundaries)
- ✅ Lowered classification thresholds: hi-hat 0.15×, snare 0.18×, kick 1.0×
- ✅ "Unknown" default instead of tom default
- ✅ Strength threshold lowered to 0.05
- ✅ Min interval 0.05s for merge

### Bass
- ✅ Energy-based phantom note filtering (2% global RMS threshold)
- ✅ Extended max hold to 8s
- ✅ Min note length 30ms

### Guitar
- ✅ Frequency filter (70-1400 Hz) to reject keys bleed
- ✅ CHORD_WINDOW widened to 60ms
- ✅ 15ms dedup tolerance for (time, lane)
- ✅ 10ms post-quantization merge pass
- ✅ ONSET_THRESHOLD 0.45, FRAME_THRESHOLD 0.35

### Drums (Classification)
- ✅ Hi-hat threshold: 0.15× total, 0.6× dominance
- ✅ Snare threshold: 0.18×
- ✅ Kick threshold: 1.0×
- ✅ "Unknown" default replaces tom default

## Infrastructure Built

### Evaluation Framework
- `autorb/evaluation/chart_evaluator.py` - MIDI comparison with timing/lane metrics
- `autorb/evaluation/stem_analyzer.py` - Stem quality analysis with leakage detection
- `autorb/evaluation/run_iterations.py` - Automated iteration loop with golden master
- `autorb/evaluation/iteration_loop.py` - Full iteration loop framework

### Evaluation Metrics (vs 311 Down Reference)
| Metric | Drums | Bass | Guitar |
|--------|-------|------|--------|
| F1 Score | 0.15 | 0.20 | 0.36 |
| Lane Accuracy | 12% | 8% | 14% |
| Onset Error | 190ms | 133ms | 140ms |
| False Positives | 309 | 488 | 2069 |
| False Negatives | 1356 | 512 | 657 |

## Next Phase: Closed-Loop Automation

### Phase 1: Reference Establishment
- [ ] Extract audio from 311 - Down MOGG (need MOGG parser)
- [ ] Run pipeline on 311 - Down with reference
- [ ] Establish baseline metrics for known good song

### Phase 2: Targeted Fixes
1. **Drums**: Fix kick detection (only 4 kicks), improve hi-hat in intro
2. **Bass**: Fix lane mapping (wrong octave), improve hold detection
3. **Guitar**: Reduce over-charting, improve chord detection
4. **Vocals**: Fix complete failure (0 expert notes)

### Phase 3: Multi-Song Validation
- Test on 3+ songs (311 Down, 311 Amber, Smells Like Nirvana)
- Automated regression detection

### Phase 4: Automation
- Automated fix hypothesis generation
- A/B testing of parameter changes
- CI/CD integration

## Required Tools

### MOGG Audio Extraction
Need to parse Rock Band MOGG format (custom multi-track OGG container). Options:
1. Write custom parser (format documented in C3 tools)
2. Use C3 CON tools via Wine/mono
3. Convert via FFmpeg with custom demuxer

### Reference Charts
- 311 - Down: Have MIDI, need audio
- 311 - Amber: Have CON, need extraction
- Smells Like Nirvana: Have CON, need extraction

## Immediate Next Steps (Priority Order)

1. **Extract 311 - Down audio** - Highest priority for validation
2. **Fix vocal MIDI generation** - Complete failure
3. **Improve drum kick detection** - Only 4 kicks detected
4. **Fix bass lane mapping** - Wrong octave/fret assignment
5. **Reduce guitar over-charting** - 2x over-charted

## Commands for Quick Testing

```bash
# Run pipeline on Eve 6
python -m autorb.cli input/eve6-openRoadSong.mp3 --artist "Eve 6" --title "Open Road Song" --year 1998 --genre Alternative --lyrics input/eve6-openRoadSong.lrc --output-dir ./output_test --skip-separation

# Analyze stems
python autorb/evaluation/stem_analyzer.py output/stems

# Evaluate against golden master
python -m autorb.evaluation.chart_evaluator /tmp/reference.mid output/validation/notes.mid

# Run iteration loop
python -m autorb.evaluation.run_iterations
```