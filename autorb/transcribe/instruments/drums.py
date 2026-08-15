"""
Drum transcription for Rock Band charts.

Transcribes the drums stem into a playable 5-lane drum chart
with all drum elements, fill detection → overdrive, solos, BRE.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import numpy as np
import librosa

from .onset_detection import (
    detect_onsets_librosa,
    detect_onsets_madmom,
    merge_nearby_onsets,
    filter_onsets_by_strength,
    detect_onsets_multi_band,
    OnsetResult,
)
from .drum_classifier import (
    classify_onsets_batch,
    detect_hihat_state_changes,
    detect_fills,
    DrumElement,
)
from .difficulty import (
    InstrumentChart,
    ChartNote,
    Difficulty,
    create_all_difficulties,
)


def transcribe_drums(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> InstrumentChart:
    """
    Main drum transcription pipeline.
    
    Args:
        stem_path: Path to 'drums.wav' stem
        tempo_map: List of (time, bpm) tuples
        song_end: Song end time in seconds
        sr: Sample rate
    
    Returns:
        InstrumentChart with Expert difficulty
    """
    # 1. Onset detection (try madmom for drums, fallback to librosa)
    try:
        onset_result = detect_onsets_madmom(stem_path)
        onset_result = merge_nearby_onsets(onset_result, min_interval=0.02)  # Drums can be faster
        onset_result = filter_onsets_by_strength(onset_result, min_strength=0.08)
    except Exception:
        onset_result = detect_onsets_librosa(stem_path, sr=sr)
        onset_result = merge_nearby_onsets(onset_result, min_interval=0.02)
        onset_result = filter_onsets_by_strength(onset_result, min_strength=0.08)
    
    # 2. Classify each onset into drum element
    drum_elements = classify_onsets_batch(
        str(stem_path),
        onset_result.times,
        sr=sr,
        window_ms=80,  # Shorter window for drums
    )
    
    # 3. Detect hi-hat open/closed transitions
    hihat_transitions = detect_hihat_state_changes(drum_elements, onset_result.times)
    
    # 4. Detect fills (source of overdrive phrases)
    fills = detect_fills(drum_elements, onset_result.times, min_hits=3, window_ms=500)
    
    # 5. Detect solo sections
    solos = detect_drum_solos(drum_elements, onset_result.times, tempo_map)
    
    # 6. Detect BRE
    bre = detect_drum_bre(drum_elements, onset_result.times, song_end)
    
    # 7. Build Expert chart notes
    expert_notes = build_drum_notes(
        drum_elements,
        onset_result.times,
        hihat_transitions,
        fills,
        tempo_map,
    )
    
    # 8. Build Expert chart
    expert_chart = InstrumentChart(
        notes=expert_notes,
        tempo_map=tempo_map,
        solo_sections=solos,
        bre_section=bre,
        overdrive_phrases=[(f['start_time'], f['end_time']) for f in fills],  # Fills → OD
        metadata={
            'instrument': 'drums',
            'num_kick': sum(1 for e in drum_elements if e.element_type == 'kick'),
            'num_snare': sum(1 for e in drum_elements if e.element_type == 'snare'),
            'num_hihat': sum(1 for e in drum_elements if e.element_type in ('hihat', 'hihat_open')),
            'num_fills': len(fills),
        },
    )
    
    return expert_chart


def detect_drum_solos(
    elements: list[DrumElement],
    times: np.ndarray,
    tempo_map: list,
    min_density: float = 5.0,
    min_duration: float = 4.0,
) -> list[tuple]:
    """Detect drum solo sections."""
    if not elements:
        return []
    
    solos = []
    window = 2.0
    step = 0.5
    max_time = max(times) if len(times) > 0 else 0
    t = 0
    
    while t <= max_time:
        window_elements = [e for e, t_onset in zip(elements, times) if t <= t_onset < t + window]
        density = len(window_elements) / window
        
        if density >= min_density:
            start = t
            end = t + window
            
            while start > 0:
                prev_window = [e for e, t_onset in zip(elements, times) if start - window <= t_onset < start]
                if len(prev_window) / window >= min_density * 0.7:
                    start -= step
                else:
                    break
            
            while end < max_time:
                next_window = [e for e, t_onset in zip(elements, times) if end <= t_onset < end + window]
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


def detect_drum_bre(
    elements: list[DrumElement],
    times: np.ndarray,
    song_end: float,
    bre_window: float = 20.0,
) -> Optional[tuple]:
    """Detect Big Rock Ending for drums."""
    if not elements:
        return None
    
    # Filter to last bre_window seconds
    end_mask = times >= song_end - bre_window
    end_elements = [e for e, m in zip(elements, end_mask) if m]
    end_times = times[end_mask]
    
    if len(end_elements) < 15:  # Need high density for drum BRE
        return None
    
    # Check for increasing density towards end
    densities = []
    window = 2.0
    for t in np.linspace(song_end - bre_window, song_end - window, 5):
        window_elements = [e for e, t_onset in zip(end_elements, end_times) if t <= t_onset < t + window]
        densities.append(len(window_elements) / window)
    
    if len(densities) >= 3 and densities[-1] > densities[0] * 1.5:
        return (song_end - bre_window, song_end)
    
    return None


def build_drum_notes(
    elements: list[DrumElement],
    times: np.ndarray,
    hihat_transitions: list,
    fills: list,
    tempo_map: list,
) -> list:
    """Convert classified drum elements to ChartNotes."""
    from .difficulty import ChartNote
    
    notes = []
    
    # Create a quick lookup for hi-hat state at each time
    hihat_state = {}  # time -> 'open'/'closed'
    for trans in hihat_transitions:
        hihat_state[trans['time']] = trans['state']
    
    # For times between transitions, interpolate state
    # Simplified: we'll just check the nearest transition
    
    for elem, onset_time in zip(elements, times):
        if elem.element_type == 'unknown':
            continue
        
        # Handle hi-hat open/closed
        midi_pitch = elem.midi_pitch
        if elem.element_type == 'hihat':
            # Check if open at this time
            is_open = False
            for trans_time, state in sorted(hihat_state.items()):
                if onset_time >= trans_time:
                    is_open = (state == 'open')
            if is_open:
                midi_pitch = 46  # Open hi-hat pitch
        
        # Determine velocity
        velocity = 100
        if elem.element_type == 'snare':
            # Could differentiate ghost notes here
            pass
        elif elem.element_type == 'kick':
            # Could differentiate double kicks
            pass
        
        # Check if part of a fill (for OD marking)
        is_in_fill = any(
            f['start_time'] <= onset_time <= f['end_time'] for f in []
        )  # We'll pass fills from outer scope if needed
        
        note = ChartNote(
            time=onset_time,
            lane=elem.lane,
            length=0.0,  # Drums rarely have holds (except cymbal swells)
            is_open=False,
            is_hopo=False,
            velocity=velocity,
            difficulty_pitch=midi_pitch,
            is_chord=False,
            is_in_fill=is_in_fill,
        )
        notes.append(note)
    
    # Sort by time
    notes.sort(key=lambda n: n.time)
    
    # Merge simultaneous notes (chords - e.g., kick + snare hit together)
    merged = []
    i = 0
    while i < len(notes):
        current = notes[i]
        # Check for simultaneous notes within 10ms
        chord_notes = [current]
        j = i + 1
        while j < len(notes) and abs(notes[j].time - current.time) <= 0.01:
            chord_notes.append(notes[j])
            j += 1
        
        if len(chord_notes) > 1:
            # Create chord (multiple notes at same tick)
            # Mark first as chord root, others as chord tones
            for k, cn in enumerate(chord_notes):
                cn.is_chord = (k > 0)
                if k == 0:
                    cn.chord_notes = chord_notes[1:]
            merged.extend(chord_notes)
        else:
            merged.append(current)
        
        i = j
    
    return merged


def generate_all_difficulties(expert_chart: InstrumentChart) -> dict:
    """Generate Hard, Medium, Easy from Expert."""
    return create_all_difficulties(expert_chart, 'drums')