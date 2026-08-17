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


def detect_string_pitches(
    stem_path: Path,
    sr: int = 44100,
    min_strength: float = 0.15,
    conf_thresh: float = 0.5,
) -> list:
    """
    Shared onset + pitch detection for the 'other' (guitar + keys) stem.

    Demucs cannot separate guitar from keys, so the two Rock Band parts must be
    derived from the SAME (time, pitch) onsets or they will diverge (different
    note counts / rhythms). Both ``transcribe_guitar`` and ``transcribe_keys``
    call this so the parts stay consistent.

    Returns a list of dicts: {time, pitch_hz, midi_note, confidence, strength}.
    """
    onset_result = detect_onsets_librosa(stem_path, sr=sr)
    onset_result = merge_nearby_onsets(onset_result, min_interval=0.03)
    onset_result = filter_onsets_by_strength(onset_result, min_strength=min_strength)

    times = onset_result.times
    # CREPE pitch at each onset (fall back to librosa pyin).
    pitches = []
    try:
        if not CREPE_AVAILABLE:
            raise ImportError("crepe not available")
        import crepe
        y, _ = librosa.load(stem_path, sr=sr, mono=True)
        y16 = librosa.resample(y, orig_sr=sr, target_sr=16000)
        tc, freq, conf, _ = crepe.predict(
            y16, 16000, model_capacity='full', viterbi=True, step_size=10
        )
        for t in times:
            idx = int(np.argmin(np.abs(tc - t)))
            pitches.append((float(freq[idx]), float(conf[idx])))
    except Exception:
        y, _ = librosa.load(stem_path, sr=sr, mono=True)
        f0, vf, vp = librosa.pyin(
            y, fmin=65.0, fmax=1200.0, sr=sr, frame_length=2048, hop_length=512
        )
        ptimes = librosa.times_like(f0, sr=sr, hop_length=512)
        for t in times:
            idx = int(np.argmin(np.abs(ptimes - t)))
            f = f0[idx] if (vf[idx] and f0[idx] and f0[idx] > 0) else 0.0
            c = float(vp[idx]) if vf[idx] else 0.0
            pitches.append((float(f), c))

    out = []
    for i, t in enumerate(times):
        f, c = pitches[i]
        midi = int(round(69 + 12 * np.log2(f / 440.0))) if f > 0 else 0
        out.append({
            'time': float(t),
            'pitch_hz': float(f),
            'midi_note': midi,
            'confidence': c,
            'strength': float(onset_result.strengths[i]),
        })
    out = [o for o in out if o['confidence'] > conf_thresh and o['pitch_hz'] > 0]
    return out


def detect_chord_tones(
    stem_path: Path,
    times: np.ndarray,
    sr: int = 44100,
    top_k: int = 4,
    win: float = 0.03,
) -> list:
    """
    Multi-pitch (chord) detection: for each onset time, return the list of
    simultaneously-sounding pitches so that a strummed chord becomes several
    lanes instead of a single monophonic note.

    A single CREPE f0 cannot represent a chord, and spectral-flux onset
    detection emits ONE onset per strum — so the legacy per-onset monophonic
    path collapsed every chord to one note and gated density on CREPE
    confidence (``conf_thresh``). Here we keep the (dense) onset backbone but
    estimate multiple pitches per onset from a CQT salience column, rejecting
    harmonics so a note and its overtones don't both become "chord tones".

    Returns a list (aligned to ``times``) of frequency lists.
    """
    y, _ = librosa.load(stem_path, sr=sr, mono=True)
    hop = 512
    fmin = librosa.note_to_hz('E2')
    C = np.abs(librosa.cqt(
        y, sr=sr, hop_length=hop, fmin=fmin, n_bins=60, bins_per_octave=12))
    freqs = librosa.cqt_frequencies(n_bins=60, fmin=fmin, bins_per_octave=12)
    ftimes = librosa.frames_to_time(np.arange(C.shape[1]), sr=sr, hop_length=hop)

    out = []
    for t in times:
        lo = max(0, int(np.argmin(np.abs(ftimes - (t - win)))))
        hi = min(C.shape[1] - 1, int(np.argmin(np.abs(ftimes - (t + win)))))
        col = C[:, lo:hi + 1].max(axis=1)
        if col.size == 0 or col.max() <= 0:
            out.append([])
            continue
        thr = col.max() * 0.25
        peaks = []
        for i in range(1, len(col) - 1):
            if col[i] >= thr and col[i] >= col[i - 1] and col[i] >= col[i + 1]:
                peaks.append((col[i], freqs[i]))
        peaks.sort(reverse=True)
        chosen = []
        for _mag, f in peaks:
            if f < 70 or f > 1200:
                continue
            harmonic = False
            for _cm, cf in chosen:
                for h in (0.5, 1 / 3, 2.0, 3.0):
                    if abs(f - cf * h) < 8:
                        harmonic = True
                        break
                if harmonic:
                    break
            if not harmonic:
                chosen.append((_mag, f))
            if len(chosen) >= top_k:
                break
        out.append([f for _m, f in chosen])
    return out


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
    # 1-2. Onset backbone (dense rhythm) — NO monophonic CREPE confidence gate,
    # which previously dropped ~90% of onsets and flattened every chord to one
    # note. Chord content is recovered separately in step 4.
    onset_result = detect_onsets_librosa(stem_path, sr=sr)
    onset_result = merge_nearby_onsets(onset_result, min_interval=0.03)
    onset_result = filter_onsets_by_strength(onset_result, min_strength=0.25)
    onset_times = onset_result.times
    onset_strs = onset_result.strengths

    # 3. Multi-pitch (chord) detection per onset — the core fix for chords.
    chord_tone_lists = detect_chord_tones(stem_path, onset_times, sr=sr, top_k=4)

    # 4. Tuning + capo from the full set of detected tones.
    all_tones = np.array([f for tones in chord_tone_lists for f in tones])
    if all_tones.size == 0:
        all_tones = np.array([110.0])  # fallback: A2
    tuning = detect_tuning_from_pitches(all_tones, 'guitar')
    capo = detect_capo(all_tones, tuning)
    # Guard against a bogus capo (e.g. from a skewed pitch distribution) that
    # would shift every note out of the playable fret range. Real capos are
    # 0-12; clamp so downstream fret mapping never receives an impossible pitch.
    capo = max(0, min(12, int(round(capo))))
    if capo > 0:
        chord_tone_lists = [
            [f * (2 ** (capo / 12)) for f in tones] for tones in chord_tone_lists
        ]

    # 5. Build a per-onset GuitarOnset (primary = strongest tone) so the existing
    #    holds / solo / BRE helpers still work. Chord expansion happens at step 8.
    onsets_with_pitch = [
        GuitarOnset(
            time=onset_times[i],
            pitch_hz=(chord_tone_lists[i][0] if chord_tone_lists[i] else 0.0),
            confidence=1.0,
            strength=float(onset_strs[i]),
        )
        for i in range(len(onset_times))
    ]
    onsets_with_pitch = detect_chords(onsets_with_pitch)
    onsets_with_pitch = detect_holds(onsets_with_pitch, stem_path, sr=sr)
    solos = detect_solo_sections(onsets_with_pitch, tempo_map)
    bre = detect_bre_section(onsets_with_pitch, tempo_map, song_end)

    # 8. Expand each onset into its chord tones → multiple 5-lane notes.
    expert_notes = []
    for i, tones in enumerate(chord_tone_lists):
        if not tones:
            continue
        used_lanes = []
        for f in tones:
            fps = pitch_to_fret_string(f, tuning)
            lane = fret_string_to_lane(fps, tuning.num_strings)
            if lane < 0 or lane > 4:
                lane = 0
            if lane in used_lanes:
                continue  # two chord tones mapping to the same lane -> keep one
            used_lanes.append(lane)
            is_open = fps.fret == 0
            hold = getattr(onsets_with_pitch[i], 'hold_duration', 0) if lane == used_lanes[0] else 0
            expert_notes.append(ChartNote(
                time=onset_times[i],
                lane=lane,
                length=hold,
                is_open=is_open,
                is_hopo=False,
                velocity=100,
                difficulty_pitch=LANE_BASE['expert'] + lane,
                is_chord=len(used_lanes) > 1,
            ))

    # 9. HOPO detection pass (adjacent lanes ≤120ms, same direction). Skip notes
    #    that share a time with another (chord members) — they're not HOPOs.
    expert_notes.sort(key=lambda n: n.time)
    for i in range(1, len(expert_notes)):
        prev = expert_notes[i - 1]
        curr = expert_notes[i]
        if curr.time == prev.time:
            continue
        time_diff = curr.time - prev.time
        lane_diff = abs(curr.lane - prev.lane)
        if (time_diff <= 0.12 and
            lane_diff == 1 and
            not prev.is_open and not curr.is_open):
            if (curr.lane > prev.lane) == (expert_notes[min(i + 1, len(expert_notes) - 1)].lane > curr.lane):
                curr.is_hopo = True
                curr.velocity = 127

    # 10. Build Expert chart
    expert_chart = InstrumentChart(
        notes=expert_notes,
        tempo_map=tempo_map,
        solo_sections=solos,
        bre_section=bre,
        overdrive_phrases=[],
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