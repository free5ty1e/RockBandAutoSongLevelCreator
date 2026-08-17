"""
Bass transcription for Rock Band charts.

Transcribes the bass stem into a playable 5-lane bass chart
with HOPOs, held notes (very common in bass), chords (rare), solos, BRE.
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
class BassOnset:
    """A detected bass onset with pitch information."""
    time: float
    pitch_hz: float
    confidence: float
    strength: float


def detect_bass_pitch_crepe(
    audio_path: Path,
    onset_times: np.ndarray,
    sr: int = 44100,
    model_capacity: str = 'full',
    viterbi: bool = True,
) -> list:
    """
    Detect pitch at each onset using CREPE.
    
    Bass pitch detection is more reliable than guitar (monophonic).
    """
    if not CREPE_AVAILABLE:
        raise ImportError("crepe not available, install with 'pip install crepe'")
    
    import crepe
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    y_16k = librosa.resample(y, orig_sr=sr, target_sr=16000)
    
    time_crepe, frequency, confidence, _ = crepe.predict(
        y_16k, 16000, model_capacity=model_capacity, viterbi=viterbi, step_size=10
    )
    
    onsets_with_pitch = []
    for onset_time in onset_times:
        idx = np.argmin(np.abs(time_crepe - onset_time))
        onsets_with_pitch.append({
            'time': onset_time,
            'pitch_hz': frequency[idx],
            'confidence': confidence[idx],
            'strength': 1.0,
        })
    
    return onsets_with_pitch


def detect_bass_pitch_pyin(
    audio_path: Path,
    onset_times: np.ndarray,
    sr: int = 44100,
    fmin: float = 30.0,
    fmax: float = 300.0,
) -> list:
    """Fallback pitch detection using librosa pyin with bass-appropriate range."""
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y, fmin=fmin, fmax=fmax, sr=sr, frame_length=3072, hop_length=512
    )
    times = librosa.times_like(f0, sr=sr, hop_length=512)
    
    onsets_with_pitch = []
    for onset_time in onset_times:
        idx = np.argmin(np.abs(times - onset_time))
        if voiced_flag[idx] and f0[idx] > 0:
            onsets_with_pitch.append({
                'time': onset_time,
                'pitch_hz': f0[idx],
                'confidence': voiced_probs[idx],
                'strength': 1.0,
            })
        else:
            onsets_with_pitch.append({
                'time': onset_time,
                'pitch_hz': 0.0,
                'confidence': 0.0,
                'strength': 1.0,
            })
    
    return onsets_with_pitch


def detect_holds_bass(
    onsets: list,
    audio_path: Path,
    sr: int = 44100,
    min_hold_duration: float = 0.5,  # Bass holds can be shorter (whole notes at slow tempo)
) -> list:
    """
    Detect held notes - very common in bass (whole notes, half notes).

    A hold is capped to the onset of the NEXT note so two clearly separate bass
    notes are never merged into one super-long sustain (the old code walked the
    RMS envelope at a flat 25% threshold for up to 8 s, so a ringing/compressed
    bass tone kept RMS above threshold across the gap to the next attack and the
    first note's sustain reached the second).
    """
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    hop_length = 512

    rms = librosa.feature.rms(y=y, hop_length=hop_length, frame_length=2048)[0]
    rms_times = librosa.times_like(rms, sr=sr, hop_length=hop_length)

    # Sorted onset times so we can cap a hold to the next attack.
    sorted_times = sorted(o['time'] for o in onsets)
    next_after = {}
    for t in sorted_times:
        nxt = next((s for s in sorted_times if s > t + 1e-4), None)
        next_after[t] = nxt

    for onset in onsets:
        if onset['pitch_hz'] <= 0:
            continue

        onset_idx = np.argmin(np.abs(rms_times - onset['time']))
        threshold = rms[onset_idx] * 0.45  # Track the note's own decay, not a flat 25%
        if threshold <= 0:
            continue

        hold_duration = 0.0
        for j in range(onset_idx + 1, min(onset_idx + int(sr * 8.0 / 512), len(rms))):  # Up to 8s
            if rms[j] >= threshold:
                hold_duration = librosa.frames_to_time(j, sr=sr, hop_length=hop_length) - onset['time']
            else:
                break

        # Cap to the next attack so separate notes stay separate.
        cap = next_after.get(onset['time'])
        if cap is not None:
            hold_duration = min(hold_duration, cap - onset['time'] - 0.01)

        if hold_duration >= min_hold_duration:
            onset['hold_duration'] = hold_duration

    return onsets


def detect_solo_sections_bass(
    onsets: list,
    tempo_map: list,
    min_density: float = 6.0,  # Bass solos slightly less dense than guitar
    min_duration: float = 3.0,
) -> list:
    """Detect bass solo sections."""
    if not onsets:
        return []
    
    solos = []
    window = 2.0
    step = 0.5
    max_time = max(o['time'] for o in onsets)
    t = 0
    
    while t <= max_time:
        window_onsets = [o for o in onsets if t <= o['time'] < t + window]
        density = len(window_onsets) / window
        
        if density >= min_density:
            start = t
            end = t + window
            
            # Expand
            while start > 0:
                prev_window = [o for o in onsets if start - window <= o['time'] < start]
                if len(prev_window) / window >= min_density * 0.7:
                    start -= 0.5
                else:
                    break
            
            while end < max_time:
                next_window = [o for o in onsets if end <= o['time'] < end + window]
                if len(next_window) / window >= min_density * 0.7:
                    end += 0.5
                else:
                    break
            
            if end - start >= 3.0:
                solos.append((start, end))
                t = end
            else:
                t += 0.5
        else:
            t += 0.5
    
    # Merge
    if solos:
        merged = [solos[0]]
        for s in solos[1:]:
            if s[0] <= merged[-1][1] + 1.0:
                merged[-1] = (merged[-1][0], max(merged[-1][1], s[1]))
            else:
                merged.append(s)
        return merged
    
    return []


def detect_bre_bass(
    onsets: list,
    song_end: float,
    bre_window: float = 20.0,
) -> tuple | None:
    """Detect BRE for bass."""
    if not onsets:
        return None
    
    end_onsets = [o for o in onsets if o['time'] >= song_end - bre_window]
    
    if len(end_onsets) < 8:
        return None
    
    densities = []
    window = 2.0
    for t in np.linspace(song_end - bre_window, song_end - window, 5):
        window_onsets = [o for o in end_onsets if t <= o['time'] < t + window]
        densities.append(len(window_onsets) / window)
    
    if len(densities) >= 3 and densities[-1] > densities[0] * 1.3:
        return (song_end - bre_window, song_end)
    
    return None


def transcribe_bass(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> 'InstrumentChart':
    """
    Main bass transcription pipeline.
    
    Args:
        stem_path: Path to 'bass.wav' stem
        tempo_map: List of (time, bpm) tuples
        song_end: Song end time in seconds
        sr: Sample rate
    
    Returns:
        InstrumentChart with Expert difficulty
    """
    # 1. Onset detection
    # wait=3 (vs the default 5) makes rapid bass attacks separate onsets instead
    # of merging into one sustained note, addressing "separate bass notes merged
    # into one long hold" feedback.
    onset_result = detect_onsets_librosa(stem_path, sr=sr, wait=3)
    onset_result = merge_nearby_onsets(onset_result, min_interval=0.03)
    onset_result = filter_onsets_by_strength(onset_result, min_strength=0.1)
    
    # 2. Pitch detection (CREPE for bass is very reliable)
    try:
        onsets_with_pitch = detect_bass_pitch_crepe(stem_path, onset_result.times, sr=sr)
    except Exception:
        onsets_with_pitch = detect_bass_pitch_pyin(stem_path, onset_result.times, sr=sr)
    
    # Add strengths
    for i, onset in enumerate(onsets_with_pitch):
        onset['strength'] = onset_result.strengths[i]
    
    # Filter. Lowered from the old 0.4 gate (then 0.25): a strict
    # monophonic-confidence gate dropped legitimate low-confidence bass attacks,
    # so clearly separate notes got merged into one long hold. We keep the dense
    # onset backbone and rely on pitch presence instead (mirrors guitar v0.0.98).
    onsets_with_pitch = [o for o in onsets_with_pitch if o['confidence'] > 0.1 and o['pitch_hz'] > 0]
    
    # 3. Detect tuning
    pitches = np.array([o['pitch_hz'] for o in onsets_with_pitch])
    tuning = detect_tuning_from_pitches(pitches, 'bass')
    
    # 4. Detect holds (very common in bass)
    onsets_with_pitch = detect_holds_bass(onsets_with_pitch, stem_path, sr=sr)
    
    # 5. Detect solos
    solos = detect_solo_sections_bass(onsets_with_pitch, tempo_map)
    
    # 6. Detect BRE
    bre = detect_bre_bass(onsets_with_pitch, song_end)
    
    # 7. Build lane map
    onset_pitches = [(o['time'], o['pitch_hz']) for o in onsets_with_pitch]
    lane_notes = build_lane_map(onset_pitches, tuning, 'expert')
    
    # Add hold info
    for i, lane_note in enumerate(lane_notes):
        if i < len(onsets_with_pitch):
            lane_note['hold_duration'] = onsets_with_pitch[i].get('hold_duration', 0)
    
    # 8. Convert to ChartNotes (Expert)
    from .difficulty import InstrumentChart, ChartNote
    
    expert_notes = []
    for lane_note in lane_notes:
        is_open = lane_note['is_open']
        
        note = ChartNote(
            time=lane_note['time'],
            lane=lane_note['lane'],
            length=lane_note.get('hold_duration', 0),
            is_open=is_open,
            is_hopo=False,  # HOPO detection pass below
            velocity=100,
            difficulty_pitch=lane_note['difficulty_pitch'],
            is_chord=False,  # Bass chords rare
        )
        expert_notes.append(note)
    
    # 9. HOPO detection (same rules as guitar)
    expert_notes.sort(key=lambda n: n.time)
    for i in range(1, len(expert_notes)):
        prev = expert_notes[i-1]
        curr = expert_notes[i]
        time_diff = curr.time - prev.time
        lane_diff = abs(curr.lane - prev.lane)
        
        if (time_diff <= 0.12 and
            lane_diff == 1 and
            not prev.is_open and not curr.is_open):
            # Same direction
            if i + 1 < len(expert_notes):
                next_note = expert_notes[i+1]
                if (next_note.lane > curr.lane) == (curr.lane > prev.lane):
                    curr.is_hopo = True
                    curr.velocity = 127
    
    # 10. Build Expert chart
    from .difficulty import InstrumentChart, ChartNote
    
    expert_chart = InstrumentChart(
        notes=expert_notes,
        tempo_map=tempo_map,
        solo_sections=[],
        bre_section=None,
        overdrive_phrases=[],
        metadata={
            'instrument': 'bass',
            'tuning': 'bass_standard',
            'num_onsets': len(expert_notes),
        },
    )
    
    return expert_chart


def generate_all_difficulties(expert_chart: 'InstrumentChart') -> dict:
    """Generate Hard, Medium, Easy from Expert."""
    from .difficulty import create_all_difficulties, Difficulty
    
    reducer = create_all_difficulties(expert_chart, 'bass')
    return reducer