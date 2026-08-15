"""
Keys (Keyboard) transcription for Rock Band charts.

Since Demucs "other" stem contains both guitar and keys mixed together,
this module reuses the guitar transcription from the "other" stem but
maps the detected pitches to the Rock Band keys lane layout (2-octave
piano roll).

In Rock Band 3, PART KEYS uses a 2-octave piano roll starting at C2 (MIDI 36).
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
from .difficulty import (
    InstrumentChart,
    ChartNote,
    Difficulty,
    create_all_difficulties,
)


# Rock Band Keys lane: 2-octave piano roll starting at C2 (MIDI 36)
# This is 25 keys: C2 (36) to C4 (60) inclusive
KEYS_BASE_PITCH = 36  # C2
KEYS_NUM_KEYS = 25    # 2 octaves + 1 = C2..C4


def detect_keys_pitch_crepe(
    audio_path: Path,
    onset_times: np.ndarray,
    sr: int = 44100,
    model_capacity: str = 'full',
    viterbi: bool = True,
) -> list:
    """Detect pitch at each onset using CREPE."""
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


def detect_keys_pitch_pyin(
    audio_path: Path,
    onset_times: np.ndarray,
    sr: int = 44100,
    fmin: float = 65.0,   # C2
    fmax: float = 600.0,  # ~D5
) -> list:
    """Fallback pitch detection using librosa pyin."""
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y, fmin=fmin, fmax=fmax, sr=sr, frame_length=2048, hop_length=512
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


def hz_to_midi_note(pitch_hz: float) -> int:
    """Convert frequency in Hz to MIDI note number."""
    if pitch_hz <= 0:
        return 0
    return int(round(69 + 12 * np.log2(pitch_hz / 440.0)))


def midi_to_keys_lane(midi_note: int) -> int:
    """Map MIDI note to keys lane (0-24 for 25 keys C2..C4)."""
    # Keys start at C2 (MIDI 36)
    lane = midi_note - KEYS_BASE_PITCH
    # Clamp to valid range
    return max(0, min(KEYS_NUM_KEYS - 1, lane))


def transcribe_keys(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> InstrumentChart:
    """
    Main keys transcription pipeline.
    
    Reuses the same onset/pitch detection as guitar but maps to
    the keys piano-roll lane layout (2-octave piano roll C2..C4).
    
    Args:
        stem_path: Path to 'other.wav' stem (guitar + keys)
        tempo_map: List of (time, bpm) tuples
        song_end: Song end time in seconds
        sr: Sample rate
    
    Returns:
        InstrumentChart with Expert difficulty
    """
    # 1. Onset detection
    onset_result = detect_onsets_librosa(stem_path, sr=sr)
    onset_result = merge_nearby_onsets(onset_result, min_interval=0.03)
    onset_result = filter_onsets_by_strength(onset_result, min_strength=0.15)
    
    # 2. Pitch detection
    try:
        onsets_with_pitch = detect_keys_pitch_crepe(stem_path, onset_result.times, sr=sr)
    except Exception:
        onsets_with_pitch = detect_keys_pitch_pyin(stem_path, onset_result.times, sr=sr)
    
    # Add strengths
    for i, onset in enumerate(onsets_with_pitch):
        onset['strength'] = onset_result.strengths[i]
    
    # Filter
    onsets_with_pitch = [o for o in onsets_with_pitch if o['confidence'] > 0.5 and o['pitch_hz'] > 0]
    
    # 3. Build lane map (pitches -> keys lanes)
    expert_notes = []
    for onset in onsets_with_pitch:
        midi_note = hz_to_midi_note(onset['pitch_hz'])
        if midi_note < KEYS_BASE_PITCH or midi_note > KEYS_BASE_PITCH + KEYS_NUM_KEYS - 1:
            continue  # Outside keys range
        
        lane = midi_to_keys_lane(midi_note)
        
        note = ChartNote(
            time=onset['time'],
            lane=lane,
            length=0.0,
            is_open=False,
            is_hopo=False,
            velocity=100,
            difficulty_pitch=KEYS_BASE_PITCH + lane,  # Actual MIDI pitch for keys
        )
        expert_notes.append(note)
    
    # 4. HOPO detection for keys (adjacent semitones within 120ms)
    expert_notes.sort(key=lambda n: n.time)
    for i in range(1, len(expert_notes)):
        prev = expert_notes[i-1]
        curr = expert_notes[i]
        time_diff = curr.time - prev.time
        lane_diff = abs(curr.lane - prev.lane)
        
        if (time_diff <= 0.12 and
            lane_diff == 1 and
            not prev.is_open and not curr.is_open):
            # Same direction check
            if i + 1 < len(expert_notes):
                next_note = expert_notes[i+1]
                if (next_note.lane > curr.lane) == (curr.lane > prev.lane):
                    curr.is_hopo = True
                    curr.velocity = 127
    
    # 5. Build Expert chart
    expert_chart = InstrumentChart(
        notes=expert_notes,
        tempo_map=tempo_map,
        solo_sections=[],
        bre_section=None,
        overdrive_phrases=[],
        metadata={
            'instrument': 'keys',
            'num_onsets': len(expert_notes),
        },
    )
    
    return expert_chart


def generate_all_difficulties(expert_chart: InstrumentChart) -> dict:
    """Generate Hard, Medium, Easy from Expert."""
    return create_all_difficulties(expert_chart, 'keys')