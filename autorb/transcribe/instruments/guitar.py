"""
Guitar transcription for Rock Band charts.

Transcribes the 'other' stem (guitar + keys) into a playable
5-lane guitar chart with HOPOs, chords, holds, solos, and BRE.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import numpy as np
import librosa

# Optional high-quality pitch detection
try:
    import crepe
    CREPE_AVAILABLE = True
except ImportError:
    CREPE_AVAILABLE = False

from .onset_detection import (
    detect_onsets_librosa,
    merge_nearby_onsets,
    filter_onsets_by_strength,
    OnsetResult,
)
from .pitch_to_lane import (
    Tuning,
    pitch_to_fret_string,
    fret_string_to_lane,
    build_lane_map,
    detect_tuning_from_pitches,
    detect_capo,
    LANE_BASE,
    OPEN_PITCH,
    midi_note_to_lane,
    pitch_to_midi_note,
)
from .difficulty import (
    InstrumentChart,
    ChartNote,
    Difficulty,
    create_all_difficulties,
)


@dataclass
class GuitarOnset:
    """A detected guitar onset with pitch information."""
    time: float
    pitch_hz: float
    confidence: float
    strength: float
    is_chord_root: bool = False


def detect_guitar_pitch_crepe(
    audio_path: Path,
    onset_times: np.ndarray,
    sr: int = 44100,
    model_capacity: str = 'full',
    viterbi: bool = True,
) -> list:
    """
    Detect pitch at each onset using CREPE (high-quality pitch estimator).
    
    CREPE uses a deep CNN and is much more accurate than librosa pyin
    for polyphonic guitar audio.
    """
    if not CREPE_AVAILABLE:
        raise ImportError("crepe not available, install with 'pip install crepe'")
    
    import crepe
    # Load full audio for CREPE
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    
    # CREPE expects 16kHz
    y_16k = librosa.resample(y, orig_sr=sr, target_sr=16000)
    
    # Run CREPE on full audio
    time_crepe, frequency, confidence, _ = crepe.predict(
        y_16k, 16000, model_capacity=model_capacity, viterbi=viterbi, step_size=10
    )
    
    # Match each onset to nearest CREPE frame
    onsets_with_pitch = []
    for onset_time in onset_times:
        # Find closest CREPE time
        idx = np.argmin(np.abs(time_crepe - onset_time))
        
        onsets_with_pitch.append(GuitarOnset(
            time=onset_time,
            pitch_hz=frequency[idx],
            confidence=confidence[idx],
            strength=1.0,  # Will be set from onset detection
        ))
    
    return onsets_with_pitch


def detect_guitar_pitch_pyin(
    audio_path: Path,
    onset_times: np.ndarray,
    sr: int = 44100,
    fmin: float = 80.0,
    fmax: float = 1200.0,
) -> list[GuitarOnset]:
    """
    Detect pitch at each onset using librosa pyin (fallback).
    
    Less accurate for polyphonic audio but no extra dependency.
    """
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    
    # Run pyin on full audio
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y, fmin=fmin, fmax=fmax, sr=sr, frame_length=2048, hop_length=512
    )
    times = librosa.times_like(f0, sr=sr, hop_length=512)
    
    onsets_with_pitch = []
    for onset_time in onset_times:
        idx = np.argmin(np.abs(times - onset_time))
        if voiced_flag[idx] and f0[idx] > 0:
            onsets_with_pitch.append(GuitarOnset(
                time=onset_time,
                pitch_hz=f0[idx],
                confidence=voiced_probs[idx],
                strength=1.0,
            ))
        else:
            onsets_with_pitch.append(GuitarOnset(
                time=onset_time,
                pitch_hz=0.0,
                confidence=0.0,
                strength=1.0,
            ))
    
    return onsets_with_pitch


def detect_chords(
    onsets: list[GuitarOnset],
    max_chord_time: float = 0.05,  # 50ms window for chord grouping
    min_chord_notes: int = 2,
) -> list[GuitarOnset]:
    """
    Group near-simultaneous onsets into chords.
    
    Marks the lowest pitch as chord root, others as chord tones.
    """
    if len(onsets) < min_chord_notes:
        return onsets
    
    result = []
    i = 0
    while i < len(onsets):
        # Check if next onsets are within chord window
        chord_group = [onsets[i]]
        j = i + 1
        while j < len(onsets) and (onsets[j].time - onsets[i].time) <= max_chord_time:
            chord_group.append(onsets[j])
            j += 1
        
        if len(chord_group) >= min_chord_notes:
            # Sort by pitch (lowest = root)
            chord_group.sort(key=lambda o: o.pitch_hz)
            chord_group[0].is_chord_root = True
            for o in chord_group[1:]:
                o.is_chord_root = False
            result.extend(chord_group)
        else:
            result.extend(chord_group)
        
        i = j
    
    return result


def detect_holds(
    onsets: list[GuitarOnset],
    audio_path: Path,
    sr: int = 44100,
    min_hold_duration: float = 1.0,  # Minimum 1 beat at 60 BPM
) -> list[GuitarOnset]:
    """
    Detect held notes by checking energy decay after onset.
    
    If energy stays high after onset, it's likely a held note.
    """
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    hop_length = 512
    
    # RMS energy envelope
    rms = librosa.feature.rms(y=y, hop_length=hop_length, frame_length=2048)[0]
    rms_times = librosa.times_like(rms, sr=sr, hop_length=hop_length)
    
    for i, onset in enumerate(onsets):
        if onset.pitch_hz <= 0:
            continue
        
        onset_idx = np.argmin(np.abs(rms_times - onset.time))
        
        # Look ahead for energy decay
        hold_duration = 0.0
        threshold = rms[onset_idx] * 0.3  # 30% of initial energy
        
        for j in range(onset_idx + 1, min(onset_idx + int(sr * min_hold_duration / hop_length), len(rms))):
            if rms[j] >= threshold:
                hold_duration = rms_times[j] - onset.time
            else:
                break
        
        if hold_duration >= min_hold_duration:
            onset.hold_duration = hold_duration
    
    return onsets


def detect_solo_sections(
    onsets: list[GuitarOnset],
    tempo_map: list,
    min_density: float = 8.0,  # notes per second
    min_duration: float = 4.0,  # seconds
) -> list[tuple]:
    """
    Detect solo sections: dense, melodic passages.
    
    Returns list of (start_time, end_time) for solo sections.
    """
    if not onsets:
        return []
    
    solos = []
    window = 2.0  # 2 second sliding window
    step = 0.5
    
    max_time = max(o.time for o in onsets)
    t = 0
    
    while t <= max_time:
        window_onsets = [o for o in onsets if t <= o.time < t + window]
        density = len(window_onsets) / window
        
        if density >= min_density:
            # Found dense region - expand to find boundaries
            start = t
            end = t + window
            
            # Expand backward
            while start > 0:
                prev_window = [o for o in onsets if start - window <= o.time < start]
                if len(prev_window) / window >= min_density * 0.7:
                    start -= step
                else:
                    break
            
            # Expand forward
            while end < max_time:
                next_window = [o for o in onsets if end <= o.time < end + window]
                if len(next_window) / window >= min_density * 0.7:
                    end += step
                else:
                    break
            
            if end - start >= min_duration:
                solos.append((start, end))
                t = end
            else:
                t += step
        else:
            t += step
    
    # Merge overlapping/adjacent solos
    if solos:
        merged = [solos[0]]
        for s in solos[1:]:
            if s[0] <= merged[-1][1] + 1.0:
                merged[-1] = (merged[-1][0], max(merged[-1][1], s[1]))
            else:
                merged.append(s)
        return merged
    
    return []


def detect_bre_section(
    onsets: list[GuitarOnset],
    tempo_map: list,
    song_end: float,
    bre_window: float = 20.0,
) -> Optional[tuple]:
    """
    Detect Big Rock Ending (BRE) section at end of song.
    
    BRE = free-form ending with dense, improvisatory playing.
    Typically last 10-20 seconds.
    """
    if not onsets:
        return None
    
    # Look at last bre_window seconds
    end_onsets = [o for o in onsets if o.time >= song_end - bre_window]
    
    if len(end_onsets) < 10:  # Need minimum density
        return None
    
    # Check for increasing density towards end (characteristic of BRE)
    densities = []
    window = 2.0
    for t in np.linspace(song_end - bre_window, song_end - window, 5):
        window_onsets = [o for o in end_onsets if t <= o.time < t + window]
        densities.append(len(window_onsets) / window)
    
    # If density increases significantly towards end, likely BRE
    if len(densities) >= 3 and densities[-1] > densities[0] * 1.5:
        return (song_end - bre_window, song_end)
    
    return None


def transcribe_guitar(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> InstrumentChart:
    """
    Main guitar transcription pipeline.
    
    Args:
        stem_path: Path to 'other.wav' stem (guitar + keys)
        tempo_map: List of (time, bpm) tuples
        song_end: Song end time in seconds
        sr: Sample rate
    
    Returns:
        InstrumentChart with Expert difficulty (other difficulties generated separately)
    """
    # 1. Onset detection
    onset_result = detect_onsets_librosa(stem_path, sr=sr)
    onset_result = merge_nearby_onsets(onset_result, min_interval=0.03)
    onset_result = filter_onsets_by_strength(onset_result, min_strength=0.15)
    
    # 2. Pitch detection (try CREPE first, fallback to pyin)
    try:
        onsets_with_pitch = detect_guitar_pitch_crepe(stem_path, onset_result.times, sr=sr)
    except Exception:
        onsets_with_pitch = detect_guitar_pitch_pyin(stem_path, onset_result.times, sr=sr)
    
    # Add strengths from onset detection
    for i, onset in enumerate(onsets_with_pitch):
        onset.strength = onset_result.strengths[i]
    
    # Filter out low-confidence pitches
    onsets_with_pitch = [o for o in onsets_with_pitch if o.confidence > 0.5 and o.pitch_hz > 0]
    
    # 3. Detect tuning from pitch distribution
    pitches = np.array([o.pitch_hz for o in onsets_with_pitch])
    tuning = detect_tuning_from_pitches(pitches, 'guitar')
    capo = detect_capo(pitches, tuning)
    
    # Adjust pitches for capo
    if capo > 0:
        for o in onsets_with_pitch:
            o.pitch_hz *= 2 ** (capo / 12)
    
    # 4. Detect chords
    onsets_with_pitch = detect_chords(onsets_with_pitch)
    
    # 5. Detect holds
    onsets_with_pitch = detect_holds(onsets_with_pitch, stem_path, sr=sr)
    
    # 6. Detect solo sections
    solos = detect_solo_sections(onsets_with_pitch, tempo_map)
    
    # 7. Detect BRE
    bre = detect_bre_section(onsets_with_pitch, tempo_map, song_end)
    
    # 8. Build lane map (pitches → 5 lanes)
    onset_pitches = [(o.time, o.pitch_hz) for o in onsets_with_pitch]
    lane_notes = build_lane_map(onset_pitches, tuning, 'expert')
    
    # 8b. Add chord info to lane notes
    for i, lane_note in enumerate(lane_notes):
        if i < len(onsets_with_pitch):
            onset = onsets_with_pitch[i]
            lane_note['is_chord_root'] = onset.is_chord_root
            lane_note['hold_duration'] = getattr(onset, 'hold_duration', 0)
    
    # 9. Convert to ChartNotes (Expert)
    expert_notes = []
    for lane_note in lane_notes:
        is_open = lane_note['is_open']
        is_hopo = False  # Will be set in HOPO detection pass
        
        # Determine if this is a HOPO (adjacent lane, within 120ms, same direction)
        # This is a simplified check - full HOPO detection needs neighbor analysis
        
        note = ChartNote(
            time=lane_note['time'],
            lane=lane_note['lane'],
            length=lane_note.get('hold_duration', 0),
            is_open=is_open,
            is_hopo=False,  # Set in post-process
            velocity=100,
            difficulty_pitch=lane_note['difficulty_pitch'],
            is_chord=lane_note.get('is_chord_root', False),
        )
        expert_notes.append(note)
    
    # 10. HOPO detection pass (adjacent lanes ≤120ms, same direction)
    expert_notes.sort(key=lambda n: n.time)
    for i in range(1, len(expert_notes)):
        prev = expert_notes[i-1]
        curr = expert_notes[i]
        time_diff = curr.time - prev.time
        lane_diff = abs(curr.lane - prev.lane)
        
        if (time_diff <= 0.12 and  # 120ms
            lane_diff == 1 and
            not prev.is_chord and not curr.is_chord and
            not prev.is_open and not curr.is_open):
            # Same direction check
            if (curr.lane > prev.lane) == (expert_notes[min(i+1, len(expert_notes)-1)].lane > curr.lane):
                curr.is_hopo = True
                curr.velocity = 127
    
    # 11. Build Expert chart
    expert_chart = InstrumentChart(
        notes=expert_notes,
        tempo_map=tempo_map,
        solo_sections=solos,
        bre_section=bre,
        overdrive_phrases=[],  # Will be populated by overdrive detector
        metadata={
            'instrument': 'guitar',
            'tuning': tuning.name,
            'capo': capo,
            'num_onsets': len(expert_notes),
        },
    )
    
    return expert_chart


def generate_all_difficulties(expert_chart: InstrumentChart) -> dict:
    """Generate Hard, Medium, Easy from Expert."""
    return create_all_difficulties(expert_chart, 'guitar')