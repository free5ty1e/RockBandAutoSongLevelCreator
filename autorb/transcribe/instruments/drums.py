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
    classify_drum_onsets_energy,
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
    # 1. Onset detection (try madmom for drums, fallback to librosa with windowed normalization)
    y, _ = librosa.load(stem_path, sr=sr, mono=True)
    try:
        onset_result = detect_onsets_madmom(stem_path)
        onset_result = merge_nearby_onsets(onset_result, min_interval=0.02)
        onset_result = filter_onsets_by_strength(onset_result, min_strength=0.08)
    except Exception:
        # Use windowed detection (30s windows) to get local strength normalization
        # This prevents early quiet sections from being crushed by later loud crashes
        onset_result = detect_onsets_librosa(stem_path, sr=sr, window_seconds=30.0)
        onset_result = merge_nearby_onsets(onset_result, min_interval=0.02)
        onset_result = filter_onsets_by_strength(onset_result, min_strength=0.05)

    # Augment full-signal onsets with high-band onsets so quiet hi-hats /
    # cymbals (often attenuated by stem separation) are not missed.
    hat_t = _band_onsets(y, sr, 7000, 14000, delta=0.12, wait=3)
    cym_t = _band_onsets(y, sr, 3000, 9000, delta=0.12, wait=4)
    times = np.asarray(_merge_times([onset_result.times, hat_t, cym_t], tol=0.025), dtype=float)

    # 2. Classify each onset into a drum element by band-energy ratios.
    drum_elements = classify_drum_onsets_energy(y, sr, times, window_ms=60)
    
    # 3. Detect hi-hat open/closed transitions
    hihat_transitions = detect_hihat_state_changes(drum_elements, times)
    
    # 4. Detect fills (source of overdrive phrases)
    fills = detect_fills(drum_elements, times, min_hits=3, window_ms=500)
    
    # 5. Detect solo sections
    solos = detect_drum_solos(drum_elements, times, tempo_map)
    
    # 6. Detect BRE
    bre = detect_drum_bre(drum_elements, times, song_end)
    
    # 7. Build Expert chart notes
    expert_notes = build_drum_notes(
        drum_elements,
        times,
        hihat_transitions,
        fills,
        tempo_map,
    )

    # 7b. Rock Band does NOT support fully-authored double bass (alternating
    # pedal). Author only what a single foot can play: collapse rapid kick
    # bursts (two kicks closer than ~MIN_KICK_GAP) into a single foot hit.
    # See llm-wiki-kb/difficulty_charting.md §2.1.
    expert_notes = reduce_double_bass(expert_notes, min_gap=0.11)

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


def _band_onsets(
    y: np.ndarray,
    sr: int,
    fmin: float,
    fmax: float,
    delta: float = 0.07,
    wait: int = 4,
) -> np.ndarray:
    """Detect onsets in a band-passed version of the signal (per-element)."""
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2.0
    lo = max(fmin / nyq, 1e-3)
    hi = min(fmax / nyq, 0.99)
    if hi <= lo:
        hi = min(lo * 1.5, 0.99)
    sos = butter(4, [lo, hi], btype='band', output='sos')
    yb = sosfiltfilt(sos, y)
    env = librosa.onset.onset_strength(
        y=yb, sr=sr, hop_length=512, aggregate=np.median, n_mels=64, fmax=fmax
    )
    frames = librosa.onset.onset_detect(
        onset_envelope=env, sr=sr, hop_length=512,
        delta=delta, wait=wait, backtrack=True,
    )
    return librosa.frames_to_time(frames, sr=sr, hop_length=512)


def _merge_times(lists, tol: float = 0.025):
    """Merge several onset-time lists, averaging any within `tol` seconds."""
    all_t = sorted(float(t) for lst in lists for t in lst)
    merged = []
    for t in all_t:
        if merged and t - merged[-1] <= tol:
            merged[-1] = (merged[-1] + t) / 2.0
        else:
            merged.append(t)
    return merged


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


def reduce_double_bass(notes: list, min_gap: float = 0.11) -> list:
    """Collapse rapid kick bursts into single-foot hits.

    Rock Band does not support fully-authored double bass (alternating pedal);
    Expert kick patterns must be playable with one foot. Any kick (lane 0) whose
    onset is within ``min_gap`` seconds of the previously kept kick is dropped,
    keeping the first of the burst. Other lanes are untouched. This removes the
    "double bass pedal" runs the transcription otherwise emits from low-end bleed
    and fast classifier onsets (see ``llm-wiki-kb/difficulty_charting.md`` §2.1).
    """
    out: list = []
    last_kick_t = -1e9
    for n in sorted(notes, key=lambda x: x.time):
        if getattr(n, "lane", None) == 0:  # kick
            if n.time - last_kick_t < min_gap:
                continue
            last_kick_t = n.time
        out.append(n)
    return out


def generate_all_difficulties(expert_chart: InstrumentChart) -> dict:
    """Generate Hard, Medium, Easy from Expert."""
    return create_all_difficulties(expert_chart, 'drums')