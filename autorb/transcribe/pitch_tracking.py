#!/usr/bin/env python
"""
Per-syllable pitch tracking using dense librosa pyin.

Runs pyin ONCE on the full vocal stem, then segments each syllable's
pitch contour into discrete notes at detected pitch change points.
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class NoteSegment:
    """A single note segment within a syllable."""
    start: float      # seconds
    end: float        # seconds
    midi_note: int    # integer MIDI note (C3=48, C4=60, etc.)
    confidence: float # 0.0 - 1.0


@dataclass
class SyllablePitch:
    """Pitch analysis result for one syllable."""
    syllable_text: str
    syllable_start: float
    syllable_end: float
    note_segments: List[NoteSegment]
    is_trusted: bool  # whether pyin reading was trusted


# Pitch tracking constants
MIN_SEMITONE_CHANGE = 1.5      # minimum pitch change to trigger new note (semitones)
MIN_SUSTAINED_FRAMES = 3       # frames that must sustain the change
MERGE_GAP_MS = 50              # merge same-pitch segments separated by < this (ms)
MIN_NOTE_DURATION_MS = 80      # minimum note duration (Rock Band playable limit)
PYIN_PROB_THRESH = 0.5         # voiced probability threshold
PYIN_MIN_FRAMES = 2            # minimum confident voiced frames for trust
PYIN_MODE_AGREE_ST = 1.0       # median vs mode agreement threshold (semitones)
VOCAL_MIDI_MIN, VOCAL_MIDI_MAX = 48, 84  # C3..C6


def compute_dense_pitch(vocals_stem_path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Run librosa pyin once on the entire vocal stem.
    
    Returns:
        times: frame times (seconds)
        f0: fundamental frequency (Hz), NaN for unvoiced
        voiced: boolean voiced flag
        probs: voiced probability per frame
    """
    import librosa
    y, sr = librosa.load(vocals_stem_path, sr=22050, mono=True)
    f0, voiced, probs = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C6"),
        sr=sr,
        frame_length=2048,
    )
    times = librosa.times_like(f0, sr=sr)
    return times, f0, voiced, probs


def hz_to_midi(f0: np.ndarray) -> np.ndarray:
    """Convert Hz to continuous MIDI note numbers (fractional)."""
    return 69.0 + 12.0 * np.log2(f0 / 440.0)


def segment_syllable_pitch(
    syllable_start: float,
    syllable_end: float,
    syllable_text: str,
    times: np.ndarray,
    f0: np.ndarray,
    voiced: np.ndarray,
    probs: np.ndarray,
) -> SyllablePitch:
    """
    Segment a single syllable's pitch contour into discrete notes.
    
    Algorithm:
    1. Extract frames within syllable window
    2. Filter to confident voiced frames
    3. Convert to MIDI, median-smooth to suppress jitter
    4. Detect change points (|Δmidi| > MIN_SEMITONE_CHANGE sustained)
    5. Segment at change points
    6. Per segment: compute rounded mode, trust if mode≈median
    7. Merge adjacent same-pitch segments with small gaps
    8. Enforce minimum note duration
    """
    # Find frame indices for this syllable
    i0 = int(np.searchsorted(times, syllable_start, side='left'))
    i1 = int(np.searchsorted(times, syllable_end, side='right'))
    
    if i1 <= i0 or i0 >= len(times):
        # No frames - return empty
        return SyllablePitch(
            syllable_text=syllable_text,
            syllable_start=syllable_start,
            syllable_end=syllable_end,
            note_segments=[],
            is_trusted=False
        )
    
    # Clamp to array bounds
    i0 = max(0, i0)
    i1 = min(len(times), i1)
    
    # Extract syllable frames
    syl_times = times[i0:i1]
    syl_f0 = f0[i0:i1]
    syl_voiced = voiced[i0:i1]
    syl_probs = probs[i0:i1]
    
    # Filter to confident voiced frames
    mask = syl_voiced & (syl_probs > PYIN_PROB_THRESH) & np.isfinite(syl_f0)
    
    if np.count_nonzero(mask) < PYIN_MIN_FRAMES:
        return SyllablePitch(
            syllable_text=syllable_text,
            syllable_start=syllable_start,
            syllable_end=syllable_end,
            note_segments=[],
            is_trusted=False
        )
    
    # Convert to MIDI (continuous)
    midi_cont = hz_to_midi(syl_f0[mask])
    syl_times_voiced = syl_times[mask]
    syl_probs_voiced = syl_probs[mask]
    
    # Median filter to suppress jitter (window=3 frames)
    from scipy.signal import medfilt
    midi_smooth = medfilt(midi_cont, kernel_size=3)
    
    # Detect change points
    change_points = detect_pitch_changes(midi_smooth, MIN_SEMITONE_CHANGE, MIN_SUSTAINED_FRAMES)
    
    # Segment at change points
    segments = []
    seg_start_idx = 0
    
    for cp in change_points + [len(midi_smooth) - 1]:
        seg_end_idx = cp
        if seg_end_idx > seg_start_idx:
            seg_midi = midi_smooth[seg_start_idx:seg_end_idx + 1]
            seg_times = syl_times_voiced[seg_start_idx:seg_end_idx + 1]
            seg_probs = syl_probs_voiced[seg_start_idx:seg_end_idx + 1]
            
            # Compute segment pitch (rounded mode)
            rounded = np.round(seg_midi).astype(int)
            mode = int(np.bincount(rounded - rounded.min()).argmax() + rounded.min())
            median = float(np.median(seg_midi))
            
            # Trust logic: mode agrees with median
            is_trusted = abs(mode - median) <= PYIN_MODE_AGREE_ST
            
            # Clamp to vocal range
            pitch = max(VOCAL_MIDI_MIN, min(VOCAL_MIDI_MAX, mode))
            
            # Average confidence
            confidence = float(np.mean(seg_probs))
            
            segments.append(NoteSegment(
                start=float(seg_times[0]),
                end=float(seg_times[-1]),
                midi_note=pitch,
                confidence=confidence
            ))
        seg_start_idx = cp + 1
    
    # Merge adjacent same-pitch segments with small gaps
    segments = merge_segments(segments, MERGE_GAP_MS / 1000.0)
    
    # Enforce minimum note duration
    segments = enforce_min_duration(segments, MIN_NOTE_DURATION_MS / 1000.0, syllable_end)
    
    is_overall_trusted = len(segments) > 0 and all(s.confidence > PYIN_PROB_THRESH for s in segments)
    
    return SyllablePitch(
        syllable_text=syllable_text,
        syllable_start=syllable_start,
        syllable_end=syllable_end,
        note_segments=segments,
        is_trusted=is_overall_trusted
    )


def detect_pitch_changes(midi_values: np.ndarray, threshold: float, min_frames: int) -> List[int]:
    """
    Detect pitch plateaus: regions where pitch is stable.
    
    A plateau is a region where pitch stays within ±0.5 semitones for >= min_frames.
    Segment boundaries are placed at transitions between plateaus.
    
    This naturally handles:
    - Sustained notes (long plateaus)
    - Slides (transition between plateaus)
    - Vibrato (stays within one plateau since oscillation < 1 semitone)
    - Jumps (immediate transition between plateaus)
    """
    if len(midi_values) < min_frames + 5:
        return []
    
    # Smooth to remove vibrato
    from scipy.signal import medfilt
    midi_smooth = medfilt(midi_values, kernel_size=9)
    
    # Find plateaus: windows of >= min_frames where pitch range < 1 semitone
    plateaus = []  # list of (start_idx, end_idx, median_pitch)
    i = 0
    while i < len(midi_smooth) - min_frames:
        # Check if window i:i+min_frames is a plateau
        window = midi_smooth[i:i + min_frames]
        pitch_range = window.max() - window.min()
        
        if pitch_range < 1.0:  # plateau threshold: 1 semitone range
            # Extend plateau as far as possible
            j = i + min_frames
            while j < len(midi_smooth):
                # Check if adding frame j keeps range < 1.0
                extended = midi_smooth[i:j+1]
                if extended.max() - extended.min() < 1.0:
                    j += 1
                else:
                    break
            plateau_pitch = np.median(midi_smooth[i:j])
            plateaus.append((i, j - 1, plateau_pitch))
            i = j
        else:
            i += 1
    
    # Now find transitions between plateaus with different pitches
    changes = []
    for k in range(len(plateaus) - 1):
        curr_pitch = plateaus[k][2]
        next_pitch = plateaus[k + 1][2]
        if abs(next_pitch - curr_pitch) > threshold:
            # Transition between different pitch plateaus
            # Place boundary at the midpoint of the gap
            gap_start = plateaus[k][1] + 1
            gap_end = plateaus[k + 1][0] - 1
            if gap_start <= gap_end:
                changes.append((gap_start + gap_end) // 2)
            else:
                changes.append(plateaus[k][1])
    
    return changes


def merge_segments(segments: List[NoteSegment], max_gap: float) -> List[NoteSegment]:
    """Merge adjacent segments with same pitch if gap < max_gap."""
    if len(segments) <= 1:
        return segments
    
    merged = [segments[0]]
    for seg in segments[1:]:
        last = merged[-1]
        if seg.midi_note == last.midi_note and seg.start - last.end < max_gap:
            # Merge
            merged[-1] = NoteSegment(
                start=last.start,
                end=seg.end,
                midi_note=last.midi_note,
                confidence=max(last.confidence, seg.confidence)
            )
        else:
            merged.append(seg)
    return merged


def enforce_min_duration(
    segments: List[NoteSegment], 
    min_dur: float, 
    syllable_end: float
) -> List[NoteSegment]:
    """Ensure each segment meets minimum duration by extending or dropping."""
    if not segments:
        return segments
    
    result = []
    for i, seg in enumerate(segments):
        dur = seg.end - seg.start
        if dur >= min_dur:
            result.append(seg)
        else:
            # Try to extend into next segment's gap or syllable end
            next_start = segments[i + 1].start if i + 1 < len(segments) else syllable_end
            available = next_start - seg.start
            if available >= min_dur:
                result.append(NoteSegment(
                    start=seg.start,
                    end=seg.start + min_dur,
                    midi_note=seg.midi_note,
                    confidence=seg.confidence
                ))
            elif result and result[-1].midi_note == seg.midi_note:
                # Merge with previous if same pitch
                result[-1] = NoteSegment(
                    start=result[-1].start,
                    end=max(result[-1].end, seg.end),
                    midi_note=result[-1].midi_note,
                    confidence=max(result[-1].confidence, seg.confidence)
                )
            # else drop too-short segment
    return result


def compute_vocal_pitch_per_syllable(
    syllables: List[dict],
    vocals_stem_path: str,
) -> List[SyllablePitch]:
    """
    Compute pitch for all syllables in one pass (dense pyin on full stem).
    
    Args:
        syllables: list of dicts with keys 'text', 'start', 'end'
        vocals_stem_path: path to vocal stem WAV
    
    Returns:
        List of SyllablePitch objects with note_segments
    """
    # Run pyin once on full stem
    times, f0, voiced, probs = compute_dense_pitch(vocals_stem_path)
    
    results = []
    for syl in syllables:
        syl_pitch = segment_syllable_pitch(
            syllable_start=syl["start"],
            syllable_end=syl["end"],
            syllable_text=syl["text"],
            times=times,
            f0=f0,
            voiced=voiced,
            probs=probs,
        )
        results.append(syl_pitch)
    
    return results


def build_melodic_contour_from_syllables(
    syllable_pitches: List[SyllablePitch],
) -> Optional[callable]:
    """
    Build a melodic contour callable from trusted syllable pitches.
    
    Uses the first note of each trusted syllable as anchor points.
    """
    from scipy.interpolate import interp1d
    import warnings
    
    # Collect trusted anchor points (first note of each trusted syllable)
    trusted = []
    for i, syl in enumerate(syllable_pitches):
        if syl.is_trusted and syl.note_segments:
            # Use the first note's pitch and the syllable's start time
            trusted.append((syl.syllable_start, syl.note_segments[0].midi_note))
    
    if len(trusted) < 2:
        return None
    
    x = np.array([t for t, _ in trusted], dtype=float)
    y = np.array([p for _, p in trusted], dtype=float)
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fn = interp1d(x, y, kind="linear", fill_value="extrapolate")
    
    x0, x1 = float(x[0]), float(x[-1])
    y0, y1 = float(y[0]), float(y[-1])
    
    def contour(t):
        if t < x0:
            return y0
        if t > x1:
            return y1
        return float(fn(t))
    
    return contour


def resolve_syllable_pitches_with_fallback(
    syllable_pitches: List[SyllablePitch],
    basic_pitch_notes: List[Tuple[float, float, int]],  # (start, end, pitch)
    melodic_contour: Optional[callable],
) -> List[SyllablePitch]:
    """
    For syllables without trusted pyin, fall back to Basic-Pitch or contour.
    
    Modifies syllable_pitches in place for untrusted syllables.
    """
    for syl in syllable_pitches:
        if syl.is_trusted and syl.note_segments:
            continue
        
        # Try Basic-Pitch fallback: find BP note overlapping this syllable
        bp_pitch = None
        for bp_start, bp_end, bp_midi in basic_pitch_notes:
            overlap = min(bp_end, syl.syllable_end) - max(bp_start, syl.syllable_start)
            if overlap > 0.02:  # 20ms minimum overlap
                bp_pitch = bp_midi
                break
        
        if bp_pitch is not None and melodic_contour is not None:
            # Octave-snap BP pitch to contour
            contour_pitch = melodic_contour(syl.syllable_start)
            snapped = octave_snap(bp_pitch, contour_pitch)
            if snapped is not None and abs(snapped - contour_pitch) <= 3.0:
                # Replace with single note at snapped pitch
                syl.note_segments = [NoteSegment(
                    start=syl.syllable_start,
                    end=syl.syllable_end,
                    midi_note=snapped,
                    confidence=0.5
                )]
                syl.is_trusted = False
                continue
        
        # Final fallback: melodic contour
        if melodic_contour is not None:
            pitch = int(round(max(VOCAL_MIDI_MIN, min(VOCAL_MIDI_MAX, melodic_contour(syl.syllable_start)))))
            syl.note_segments = [NoteSegment(
                start=syl.syllable_start,
                end=syl.syllable_end,
                midi_note=pitch,
                confidence=0.3
            )]
            syl.is_trusted = False
        elif syl.note_segments:
            # Keep whatever pyin gave us
            pass
        else:
            # Absolute fallback: middle C
            syl.note_segments = [NoteSegment(
                start=syl.syllable_start,
                end=syl.syllable_end,
                midi_note=60,
                confidence=0.1
            )]
            syl.is_trusted = False
    
    return syllable_pitches


def octave_snap(bp_pitch: int, target: float) -> Optional[int]:
    """Pick the octave copy of bp_pitch nearest to target."""
    candidates = [bp_pitch + 12 * k for k in range(-2, 3)
                  if VOCAL_MIDI_MIN <= bp_pitch + 12 * k <= VOCAL_MIDI_MAX]
    if not candidates:
        return None
    return min(candidates, key=lambda x: abs(x - target))


if __name__ == "__main__":
    # Quick test with synthetic data
    print("Testing pitch tracking...")
    
    # Create synthetic pitch contour: C4 (60) -> slide to E4 (64) -> vibrato on E4
    times = np.linspace(0, 2.0, 200)  # 2 seconds, 100Hz frame rate
    f0 = np.full_like(times, 261.63)  # C4
    # Slide from 0.5s to 1.0s: C4->E4
    slide_mask = (times >= 0.5) & (times <= 1.0)
    f0[slide_mask] = 261.63 * 2 ** ((times[slide_mask] - 0.5) / 0.5 * (4/12))
    # Vibrato on E4 from 1.0s to 1.5s
    vib_mask = (times > 1.0) & (times <= 1.5)
    f0[vib_mask] = 329.63 * (1 + 0.02 * np.sin(2 * np.pi * 6 * times[vib_mask]))
    # Back to C4
    f0[times > 1.5] = 261.63
    
    voiced = np.ones_like(times, dtype=bool)
    probs = np.ones_like(times) * 0.9
    
    # Test syllable covering the slide
    syl = segment_syllable_pitch(0.0, 2.0, "test", times, f0, voiced, probs)
    print(f"Syllable 'test': {len(syl.note_segments)} segments")
    for seg in syl.note_segments:
        print(f"  {seg.start:.2f}-{seg.end:.2f}: MIDI {seg.midi_note} (conf={seg.confidence:.2f})")