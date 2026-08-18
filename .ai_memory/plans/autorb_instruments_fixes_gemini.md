# Plan: Instrument Transcription Overhaul (Guitar, Bass, Drums, Keys)

## Background and Root Cause Analysis
Based on the latest playtests of "Open Road Song," the generated expert charts for the instruments are unplayable and do not align with the audio.

1. **Guitar & Bass (CQT/Spectral Flux failures):** The current pipeline uses standard math algorithms (Constant-Q Transform and Spectral Flux) to guess notes. This results in terrible timing (because notes don't snap to the beat grid), missing rapid strums, and wildly inaccurate pitches due to harmonic bleed.
2. **Keys Mapping:** The pipeline naively tries to compress 25 piano keys down into 5 lanes using division, creating a chaotic chart.
3. **Drums (Post-Onset Classification failure):** The pipeline detects a generic "hit" in the drum audio, and then looks at the frequency at that exact millisecond to guess what drum it was. Because cymbals ring out and bleed over kicks and snares, the classifier gets confused and hallucinates repeating patterns of toms and kicks.

## Proposed Implementation Plan

I will completely overhaul the transcription logic to prioritize **audio accuracy and playability**.

### 1. Guitar & Bass: Upgrade to Basic Pitch (Machine Learning)
Instead of relying on fragile math heuristics, I will replace the core transcription in `guitar.py` and `bass.py` with **Spotify's Basic Pitch ML model** (which is already installed in our environment). Basic Pitch is a neural network designed specifically to output precise, polyphonic MIDI notes from audio.
- This will instantly fix pitch accuracy, chords, and note durations to perfectly match the audio.
- After extracting the ML notes, I will apply a **Grid Quantization** step that snaps every note to the nearest 1/16th or 1/32nd beat using the `tempo_map`. This ensures notes land exactly on the rhythm lines in-game.
- I will rewrite the HOPO (Hammer-on/Pull-off) logic to use standard Rock Band authoring rules based on the new quantized grid (e.g., adjacent single notes on a 16th-note spacing become HOPOs).

### 2. Keys: Clone the Guitar Track
Per your feedback, I will rip out the broken 25-key mapping logic in `keys.py`. Instead, `transcribe_keys` will simply call the new guitar transcription and output an exact copy of the 5-lane Guitar chart as the `PART KEYS` track, allowing it to be played perfectly on the 5-lane keyboard controller.

### 3. Drums: Independent Per-Band Detection & Quantization
Since Basic Pitch doesn't work for drums, I will rewrite `drums.py` to use **Independent Per-Band Onset Detection**.
- Instead of detecting a generic hit and guessing what it is, I will split the audio into isolated frequency bands (Kick: 30-100Hz, Snare: 150-300Hz, Cymbals: 6000-14000Hz).
- I will run onset detection *independently* on each band. A peak in the kick band is guaranteed to be a kick drum. This entirely eliminates the cross-talk and "repeating toms" bugs.
- I will merge these independent tracks and **quantize them to the beat grid**, guaranteeing a tight, rhythmic, playable drum chart.

### Open Questions / User Review Required
> [!IMPORTANT]
> - By switching to the Basic Pitch ML model for Guitar and Bass, the pipeline will become slightly slower (adding a few seconds per song for neural net inference). This is a standard tradeoff for massive transcription accuracy gains.
> - For Keys, copying the 5-lane Guitar chart means Pro Keys (25-key pitch-accurate piano roll) will not be supported yet. It will just be standard 5-lane keys.
> 
> Please confirm you approve this transcription overhaul plan so we can finally get accurate, playable charts!

## Verification Plan
1. I will implement the changes in `guitar.py`, `bass.py`, `drums.py`, and `keys.py`.
2. I will run the pipeline locally on `eve6-openRoadSong`.
3. I will use the `tools/clone_hero_headless.sh` script to capture screenshots of the generated expert charts. The screenshots will prove that the notes are correctly structured into chords, aligned to the beat grid, and free of the previous chaotic noise.


# Where we left off
The crash is in HandleDrumTrk — same as before. The NRE is in a LINQ lambda (b__65_9) which means ForgeTool is trying to process a note in some difficulty group that has a null value. This is almost certainly coming from our new drums.py generating MIDI notes that are missing required fields (like difficulty_pitch).

Let me inspect the generated MIDI and the LibForge source to pinpoint exactly what's null.

The crash is on line 592: gem_tracks.Select(g => g.ToArray()). gem_tracks is a List<GEM>[4] — if any of the 4 difficulty slots (gem_tracks[0], gem_tracks[1], etc.) is null (no notes were added to that difficulty slot), the .ToArray() call on null throws a NullReferenceException.

This is the fundamental problem: the old drums.py had the old reduce_double_bass function; our new drums.py also has it. But the real issue is that the drum MIDI export code must be emitting notes for Expert difficulty only, leaving Easy/Medium/Hard gem track lists null.

Let me look at how the MIDI is written:

Now I can see the issue clearly. Look at line 298:

python
# "safety fallback" for a difficulty with no chart:
all_notes.append((count_in_ticks, pitch, 100, 120, diff))
This emits a single placeholder note at count_in_ticks for each missing difficulty. But looking at the ForgeTool source at line 592:

csharp
Gems = gem_tracks.Select(g => g.ToArray()).ToArray(),
gem_tracks[diff] is initialized as null — it only gets a new list when AddGem() is called. If the placeholder note ends up with a pitch OUTSIDE the EasyStart..ExpertEnd range (e.g. drum pitch 36 in count_in_ticks=0), AddGem() returns false and the list stays null, crashing on .ToArray().

But wait — looking more carefully at line 297-298: when chart is None for drums, it sets pitch = 36 (a raw drum pitch). Raw drum pitches are NOT in the ForgeTool difficulty range (60-100), so AddGem() returns false, gem_tracks[diff] stays null, and the .Select().ToArray() crashes.

The fix is: even for the fallback placeholder, use the correct difficulty-offset pitch (base + 0, i.e. lane 0 at the correct base), not the raw drum pitch 36. Let me fix this:

Now I have full confirmation of the bug. The ForgeTool pitch ranges are:

Easy: 60-64
Medium: 72-76
Hard: 84-88
Expert: 96-100
Our new drums.py sets difficulty_pitch=36 (kick) and difficulty_pitch=38 (snare) and difficulty_pitch=42 (hi-hat). These are raw MIDI drum pitches — they all fall in the DrumAnimStart..DrumAnimEnd (24-51) range, which is the animation range. AddGem() returns false for them, gem_tracks stay null for every difficulty, and .ToArray() crashes.

The old drums.py used a different scheme to set difficulty_pitch. Let me check what it was doing:

Now the root cause is crystal clear. In our new drums.py, we assign difficulty_pitch=36 for kicks, 38 for snares, 42 for hi-hats. The build_instrument_track() function in midi_generator.py reads note.lane (not note.difficulty_pitch) and computes the correct ForgeTool pitch as base + lane. So difficulty_pitch on ChartNotes for drums is irrelevant — what matters is note.lane.

The real problem is in the fallback branch at line 297-298 of midi_generator.py:

python
pitch = LANE_BASE[diff] if instrument != 'drums' else 36  # ← 36 is wrong for ForgeTool
But actually wait — looking again at the code flow: if chart is None for a difficulty, it adds a note at pitch=36. Then in build_instrument_track, this note bypasses the lane = note.lane logic (it's using a plain tuple, not a ChartNote). This tuple (count_in_ticks, 36, 100, 120, diff) gets unpacked at line 345 and pitch=36 goes straight into the MIDI, which ForgeTool rejects.

The fix: change the fallback pitch for drums to the correct base (e.g., base + 0). Let me fix midi_generator.py:

midi_generator.py
But wait — I also need to check whether the new drums.py itself emits correct notes. The lane values are 0, 1, 2 for kick, snare, hi-hat. build_instrument_track() computes pitch = base + lane for drums — that's correct. So the notes themselves are fine; only the fallback placeholder was broken.

However, there's another potential issue: the new drums.py uses DrumElement import from drum_classifier, but looks up a detect_fills function that may have a different signature. Let me check that and also verify the DrumElement dataclass fields:

Good — detect_fills takes elements: list[DrumElement] and onset_times: np.ndarray, which matches what our new drums.py is passing. Now let me run the tests quickly, then kick off the full pipeline in the background:

The tests pass (157 pass, 3 pre-existing vocal-sync failures that aren't related to our changes). But the crash is still happening — which means my midi_generator.py fix didn't yet reach the running code since the user had already re-run the pipeline before the fix landed. Let me dig deeper.

The key insight: the crash still happens even with the fix. Let me dump the actual generated MIDI to see what pitches the drum track contains:

Found it. The PART DRUMS track has only 3 events — that's just a track name + end-of-track marker. No notes at all. This means the drum chart is coming back with zero notes, the code is hitting the "all-None or empty" fallback, which renders a build_placeholder_track with zero gem notes in it. ForgeTool's HandleDrumTrk then processes the empty track, and all 4 gem_tracks[0..3] stay null → crash.

The fix isn't in midi_generator.py's fallback pitch; it's that the drum chart itself has zero notes. Let me check why:

The task is still running (loading the drum stem takes a moment). While we wait, let me look at the actual crash more carefully. The CON file is the one ForgeTool reads — not the Clone Hero notes.mid. Let me check the CON's drum MIDI directly:

