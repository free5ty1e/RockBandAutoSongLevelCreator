# Guitar Tab Alignment & Chart Validation

Tools to make the guitar chart match the audio **and** a guitar-tab guide, in a
closed loop.

## Why this exists

The guitar chart previously did not match the audible strum rhythm: on the Open
Road Song intro there were ~50 audible palm-muted strums in 10 s but the chart
started with a handful of long held notes. Root cause: Basic Pitch over-detects
rhythm-guitar onsets (~1814 on this track — it splits each strum's chord tones
into separate onsets) and the old post-processing *also* collapsed dense strums
into holds. This package extracts a reliable **strum backbone** from the audio
and validates the chart against it, so the algorithm can be tuned objectively.

## Pipeline

1. **`audio_ground_truth.py`** — extract ground-truth strum times from a stem
   via librosa onset strength (de-duplicated at 60 ms, delta tuned to match the
   human-audible count: ~698 on Open Road Song). Also optionally assigns a
   per-strum f0 (pyin) for pitch/lane ground truth.

2. **`tab_parser.py`** — parse standard 6-string ASCII tabs into per-column
   chord guides (fret sets + MIDI root pitch).

3. **`align_tab_to_audio.py`** — DTW-align a tab's **pitch contour** to the
   audio's **strum times** to timestamp the tab (the tab gives note order/pitch,
   the audio gives timing).

4. **`validate_chart.py`** — compare a charted MIDI guitar track against a
   ground-truth strum guide, reporting strum recall / precision / F1 / time
   error.

## The closed loop (how it's used)

The transcriber (`autorb/transcribe/instruments/guitar.py`) now:
1. Detects the audio **strum backbone** (`_strum_backbone`).
2. Snaps each Basic Pitch note onto its nearest real strum (within 0.15 s).
3. **Gap-fills** strums with no Basic Pitch note by inheriting the chord from a
   nearby matched strum.

This drives the chart rhythm 1:1 from the audio strums (what the human ear
hears), and gets pitches/lanes from Basic Pitch. Measured on Open Road Song:
**strum F1 0.56 → 0.993, recall 0.99, precision 1.00, 0 false attacks**; intro
now charts all 50 audible strums with correct 8th-note timing (previously
collapsed).

## Usage

```bash
# Ground-truth strum guide from a stem
python -m tools.guitar_tab_alignment.audio_ground_truth stems/guitar.wav

# Parse an ASCII tab
python -m tools.guitar_tab_alignment.tab_parser my_tab.txt

# Validate a chart (Clone Hero notes.mid is count-in-free, offset 0)
python -m tools.guitar_tab_alignment.validate_chart \
    stems/guitar.wav clone_hero/<song>/notes.mid 0
```

## Ground-truth guides

See `guides/*.yaml`. These are the reference rhythm/pitch goals validated
against (song-specific).