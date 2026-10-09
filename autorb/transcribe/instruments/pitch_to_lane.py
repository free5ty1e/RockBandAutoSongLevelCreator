"""
Pitch-to-lane mapping for Guitar and Bass transcription.

Converts detected fundamental pitches to 5-lane fret positions,
with automatic tuning detection and capo handling.
"""

from dataclasses import dataclass
from typing import Optional
import numpy as np


# Standard tunings (low to high string)
STANDARD_TUNINGS = {
    'guitar_standard': [82.41, 110.00, 146.83, 196.00, 246.94, 329.63],  # E2 A2 D3 G3 B3 E4
    'guitar_drop_d': [73.42, 110.00, 146.83, 196.00, 246.94, 329.63],   # D2 A2 D3 G3 B3 E4
    'guitar_drop_c': [65.41, 98.00, 130.81, 174.61, 220.00, 293.66],    # C2 G2 C3 F3 A3 D4
    'guitar_dadgad': [73.42, 110.00, 146.83, 196.00, 220.00, 293.66],   # D2 A2 D3 G3 A3 D4
    'bass_standard': [41.20, 55.00, 73.42, 98.00],                       # E1 A1 D2 G2
    'bass_drop_d': [36.71, 55.00, 73.42, 98.00],                         # D1 A1 D2 G2
    'bass_drop_c': [32.70, 48.99, 65.41, 87.31],                         # C1 G1 C2 F2
}


@dataclass
class Tuning:
    """Instrument tuning configuration."""
    name: str
    string_pitches: list[float]  # Low to high
    num_strings: int
    
    @classmethod
    def standard_guitar(cls) -> 'Tuning':
        return cls('guitar_standard', STANDARD_TUNINGS['guitar_standard'], 6)
    
    @classmethod
    def standard_bass(cls) -> 'Tuning':
        return cls('bass_standard', STANDARD_TUNINGS['bass_standard'], 4)
    
    @classmethod
    def from_pitches(cls, pitches: list[float], instrument: str = 'guitar') -> 'Tuning':
        """Detect tuning from pitch distribution."""
        if instrument == 'guitar' and len(pitches) == 6:
            return cls('detected', sorted(pitches), 6)
        elif instrument == 'bass' and len(pitches) == 4:
            return cls('detected', sorted(pitches), 4)
        elif instrument == 'guitar':
            return cls.standard_guitar()
        else:
            return cls.standard_bass()


@dataclass
class FretPosition:
    """Position of a note on the fretboard."""
    string: int        # 0 = highest string, num_strings-1 = lowest
    fret: int          # 0 = open, 1-22 = fret
    pitch: float       # Target pitch in Hz
    cents_error: float # How far off from exact pitch


# Lane mappings per difficulty
# Expert (base 60): Green=60, Red=61, Yellow=62, Blue=63, Orange=64, Open=67
# Hard   (base 72): Green=72, Red=73, Yellow=74, Blue=75, Orange=76, Open=67
# Medium (base 84): Green=84, Red=85, Yellow=86, Blue=87, Orange=88, Open=67 (no orange in gameplay)
# Easy   (base 96): Green=96, Red=97, Yellow=98, Blue=99, Orange=100, Open=67 (no orange/blue in gameplay)

LANE_BASE = {
    'expert': 60,
    'hard': 72,
    'medium': 84,
    'easy': 96,
}

OPEN_PITCH = 67  # G4 - same for all difficulties


def pitch_to_midi_note(pitch_hz: float) -> int:
    """Convert frequency in Hz to MIDI note number."""
    return int(round(69 + 12 * np.log2(pitch_hz / 440.0)))


def midi_note_to_lane(
    midi_note: int,
    difficulty: str = 'expert',
    is_open: bool = False,
) -> int:
    """
    Map MIDI note to 5-lane pitch for given difficulty.
    
    Returns the MIDI pitch value used in the chart.
    """
    if is_open:
        return OPEN_PITCH
    
    base = LANE_BASE[difficulty.lower()]
    # Lane mapping: 0=Green, 1=Red, 2=Yellow, 3=Blue, 4=Orange
    # Expert base 60: 60,61,62,63,64
    # The lane is determined by the note's position in the scale
    lane = (midi_note - base) % 5
    return base + lane


def pitch_to_fret_string(
    pitch_hz: float,
    tuning: Tuning,
) -> FretPosition:
    """
    Find the closest (string, fret) for a given pitch.

    Returns the position with minimum cents error. Never returns ``None``: if a
    pitch lies outside every string's playable 0-22 fret range (e.g. an
    extreme/low transient, or a pitch pushed out of range by capo detection),
    it is clamped to the nearest string's open (fret 0) or highest (fret 22)
    position so callers can safely dereference ``fret_pos.fret``.
    """
    if pitch_hz is None or pitch_hz <= 0:
        # Degenerate pitch (silence / misdetect) -> lowest open string, open.
        return FretPosition(
            string=0,
            fret=0,
            pitch=tuning.string_pitches[0],
            cents_error=0.0,
        )

    best_pos = None
    best_error = float('inf')

    for string_idx, open_pitch in enumerate(tuning.string_pitches):
        # fret 0 = open string; fret n = open_pitch * 2^(n/12)
        # n = 12 * log2(pitch / open_pitch)
        fret_float = 12 * np.log2(pitch_hz / open_pitch)

        # Clamp the candidate fret window into the playable [0, 22] range.
        lo = max(0, int(np.floor(fret_float)))
        hi = min(22, int(np.ceil(fret_float)))

        if lo > hi:
            # Pitch is outside this string's range entirely; clamp to the
            # nearer end so we still emit a (low-accuracy) position.
            fret = 0 if fret_float < 0 else 22
            actual_pitch = open_pitch * (2 ** (fret / 12))
            cents_error = 1200 * np.log2(pitch_hz / actual_pitch)
            if abs(cents_error) < abs(best_error):
                best_error = cents_error
                best_pos = FretPosition(
                    string=string_idx,
                    fret=fret,
                    pitch=actual_pitch,
                    cents_error=cents_error,
                )
            continue

        for fret in range(lo, hi + 1):
            actual = open_pitch * (2 ** (fret / 12))
            cents_error = 1200 * np.log2(pitch_hz / actual)
            if abs(cents_error) < abs(best_error):
                best_error = cents_error
                best_pos = FretPosition(
                    string=string_idx,
                    fret=fret,
                    pitch=actual,
                    cents_error=cents_error,
                )

    if best_pos is None:
        # Defensive fallback (should be unreachable): nearest string, clamped.
        best_str = 0
        best_str_err = float('inf')
        for string_idx, open_pitch in enumerate(tuning.string_pitches):
            e = abs(1200 * np.log2(pitch_hz / open_pitch))
            if e < best_str_err:
                best_str_err = e
                best_str = string_idx
        fret_float = 12 * np.log2(pitch_hz / tuning.string_pitches[best_str])
        fret = max(0, min(22, int(round(fret_float))))
        actual = tuning.string_pitches[best_str] * (2 ** (fret / 12))
        best_pos = FretPosition(
            string=best_str,
            fret=fret,
            pitch=actual,
            cents_error=1200 * np.log2(pitch_hz / actual),
        )

    return best_pos


def fret_string_to_lane(
    fret_pos: FretPosition,
    num_strings: int = 6,
) -> int:
    """
    Map (string, fret) to 5-lane highway.
    
    Simplified mapping: lane = fret % 5
    Open string (fret 0) = special open lane (handled separately)
    
    For guitar (6 strings): strings 0-5 (high E to low E)
    For bass (4 strings): strings 0-3 (G to E)
    """
    if fret_pos.fret == 0:
        return -1  # Special open string marker
    
    # Each fret position maps to a lane
    # Simple: lane = (fret - 1) % 5
    return (fret_pos.fret - 1) % 5


def detect_tuning_from_pitches(
    pitches: np.ndarray,
    instrument: str = 'guitar',
) -> Tuning:
    """
    Detect tuning from a distribution of detected pitches.
    
    Clusters pitches around expected open string frequencies.
    """
    if instrument == 'guitar':
        expected = STANDARD_TUNINGS['guitar_standard']
        num_strings = 6
    else:
        expected = STANDARD_TUNINGS['bass_standard']
        num_strings = 4
    
    # Find peaks in pitch histogram near expected open strings
    detected_open = []
    for exp_pitch in expected:
        # Find pitches within ~50 cents of expected
        mask = np.abs(1200 * np.log2(pitches / exp_pitch)) < 50
        if np.any(mask):
            detected_open.append(np.median(pitches[mask]))
        else:
            detected_open.append(exp_pitch)
    
    return Tuning('detected', detected_open, num_strings)


def detect_capo(pitches: np.ndarray, tuning: Tuning) -> int:
    """
    Detect capo position from pitch distribution.
    
    If all strings are shifted up by N semitones, capo = N.
    """
    # Check if the pitch distribution is consistently shifted
    shifts = []
    for i, open_pitch in enumerate(tuning.string_pitches):
        # Find pitches near this string's open + frets
        for fret in range(0, 5):
            target = open_pitch * (2 ** ((fret + 1) / 12))  # 1 semitone up from open
            nearby = pitches[np.abs(pitches - target) < target * 0.03]  # ~50 cents
            if len(nearby) > 0:
                shifts.append(12 * np.log2(np.median(nearby) / open_pitch) - fret - 1)
    
    if shifts:
        return int(round(np.median(shifts)))
    return 0


def build_lane_map(
    onsets_pitches: list[float],
    tuning: Tuning,
    difficulty: str = 'expert',
) -> list[dict]:
    """
    Convert a sequence of (onset_time, pitch_hz) to lane notes.
    
    Returns list of dicts with: time, pitch, lane, is_open, difficulty_pitch
    """
    notes = []
    for onset_time, pitch_hz in onsets_pitches:
        fret_pos = pitch_to_fret_string(pitch_hz, tuning)
        
        is_open = fret_pos.fret == 0
        lane = fret_string_to_lane(fret_pos, tuning.num_strings)
        diff_pitch = midi_note_to_lane(
            pitch_to_midi_note(fret_pos.pitch),
            difficulty,
            is_open=is_open,
        )
        
        notes.append({
            'time': onset_time,
            'pitch': pitch_hz,
            'lane': lane,
            'is_open': is_open,
            'difficulty_pitch': diff_pitch,
            'fret': fret_pos.fret,
            'string': fret_pos.string,
            'cents_error': fret_pos.cents_error,
        })
    
    return notes