"""
Drum element classification for drum transcription.

Classifies detected onsets into drum elements (kick, snare, hi-hat, etc.)
using frequency-band analysis and spectral features.
"""

from dataclasses import dataclass
from typing import Optional
import numpy as np
import librosa


@dataclass
class DrumElement:
    """Classification result for a drum onset."""
    element_type: str        # 'kick', 'snare', 'hihat', 'ride', 'crash', 'tom1', 'tom2', 'tom3'
    confidence: float        # 0-1
    lane: int                # 0-4 (5-lane mapping)
    midi_pitch: int          # MIDI pitch for the element
    is_open_hihat: bool = False  # For hi-hat open/closed
    metadata: dict = None    # Additional info


# Standard 5-lane drum mapping (Expert). RBN / C3 packing convention:
#   96=kick, 97=Red(snare), 98=Yellow(hi-hat/tom1), 99=Blue(ride/tom2),
#   100=Green(crash/tom3). The raw GM drum pitches below ride the same lanes.
DRUM_LANE_MAP = {
    'kick': (0, 36),        # Green lane, C2
    'snare': (1, 38),       # Red lane, D2
    'hihat': (2, 42),       # Yellow lane, F#2
    'hihat_open': (2, 46),  # Yellow lane, A#2 (same lane, different pitch)
    'ride': (3, 51),        # Blue lane, D#3
    'crash': (4, 49),       # Green lane, C#3
    'tom1': (2, 48),        # Yellow lane, C3 (high tom)
    'tom2': (3, 45),        # Blue lane, A2 (mid tom)
    'tom3': (4, 43),        # Green lane, G2 (floor tom)
}

# Pro drums 7-lane additions
PRO_DRUM_LANES = {
    'hihat_pedal': (5, 44),  # Extra lane, G#2
    'crash2': (6, 52),       # Extra lane, E3
    'china': (6, 55),        # Extra lane, G3
}


def _band_rms(y: np.ndarray, sr: int, fmin: float, fmax: float) -> float:
    """RMS energy of the signal band-passed to [fmin, fmax] Hz."""
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2.0
    lo = max(fmin / nyq, 1e-3)
    hi = min(fmax / nyq, 0.99)
    if hi <= lo:
        hi = min(lo * 1.5, 0.99)
    sos = butter(4, [lo, hi], btype='band', output='sos')
    yb = sosfiltfilt(sos, y)
    return float(np.sqrt(np.mean(yb ** 2)))


def classify_drum_onsets_energy(
    y: np.ndarray,
    sr: int,
    times: np.ndarray,
    window_ms: int = 60,
) -> list:
    """
    Classify onsets by per-band RMS energy ratios measured at each onset time.

    Band energy is computed on a band-passed signal so low/mid/high content is
    isolated *before* the decision. The decision hierarchy matters:

      kick   -> the sub-bass band (30-110 Hz) is the dominant band
      snare  -> the mid band (110-350 Hz) dominates the high bands (snare body
                + crack). Checking mid BEFORE the high bands is essential:
                snares carry a strong 3-9 kHz crack, so a high-band-first rule
                (the old code) classified most snares as ride/cymbal and
                flooded the chart with false rides while under-charting snare.
      hi-hat -> the 7-14 kHz band dominates the 3-9 kHz band
      crash  -> both high bands dominate and the hit is loud
      ride   -> high bands present but not dominant enough for a crash
      unknown-> ambiguous (left uncharted)

    The confidence is the share of the deciding band in the total, clipped to 1.
    """
    half = int(sr * window_ms / 1000 / 2)
    results = []
    for t in times:
        i = int(t * sr)
        start = max(0, i - half)
        end = min(len(y), i + half)
        seg = y[start:end]
        if len(seg) < int(sr * 0.005):
            results.append(DrumElement('unknown', 0.0, 0, 0))
            continue
        ek = _band_rms(seg, sr, 30, 110)
        em = _band_rms(seg, sr, 110, 350)
        eh = _band_rms(seg, sr, 7000, 14000)
        ec = _band_rms(seg, sr, 3000, 9000)
        tot = ek + em + eh + ec + 1e-9
        elem, lane, pitch, conf = 'unknown', 0, 36, 0.0

        # 1. Kick: sub-bass is the single dominant band (kick thump).
        if ek > em and ek > eh and ek > ec:
            elem, lane, pitch = 'kick', 0, 36
            conf = ek / tot
        # 2. Snare: the mid band dominates over the high bands (body + crack).
        elif em > 0.25 * tot and em >= eh and em >= ec:
            elem, lane, pitch = 'snare', 1, 38
            conf = em / tot
        # 3. Hi-hat: 7-14 kHz dominates the 3-9 kHz band.
        elif eh >= ec * 0.6:
            elem, lane, pitch = 'hihat', 2, 42
            conf = eh / tot
        # 4. Crash: both high bands dominate and the hit is loud.
        elif (eh + ec) > 0.55 * tot:
            elem, lane, pitch = 'crash', 4, 49
            conf = (eh + ec) / tot
        # 5. Ride: high bands present but not crash-loud.
        elif (eh + ec) > 0.20 * tot:
            elem, lane, pitch = 'ride', 3, 51
            conf = (eh + ec) / tot
        # else: ambiguous -> unknown (uncharted)
        results.append(DrumElement(elem, float(min(conf, 1.0)), lane, pitch))
    return results


def classify_drum_onsets_energy_intro(
    y: np.ndarray,
    sr: int,
    times: np.ndarray,
    window_ms: int = 60,
) -> list:
    """
    INTRO-SPECIFIC drum classification for first 60 seconds.
    
    Uses maximally aggressive kick/hi-hat detection and suppresses snare/ride/tom
    to handle quiet intros where drums are present but quiet.
    """
    half = int(sr * window_ms / 1000 / 2)
    results = []
    for t in times:
        i = int(t * sr)
        start = max(0, i - half)
        end = min(len(y), i + half)
        seg = y[start:end]
        if len(seg) < int(sr * 0.005):
            results.append(DrumElement('unknown', 0.0, 0, 0))
            continue
        ek = _band_rms(seg, sr, 30, 110)
        em = _band_rms(seg, sr, 110, 350)
        eh = _band_rms(seg, sr, 7000, 14000)
        ec = _band_rms(seg, sr, 3000, 9000)
        ehf = _band_rms(seg, sr, 2000, 14000)
        tot = ek + em + eh + ec + 1e-9
        elem, lane, pitch, conf = 'unknown', 0, 36, 0.0
        
        # INTRO MODE: Maximally aggressive hi-hat/kick detection, suppress everything else
        if max(eh, ec) > 0.1 * tot:
            if eh >= ec * 0.55:
                elem, lane, pitch = 'hihat', 2, 42
            else:
                # Cymbal-band: default to ride, crash only for very loud accents
                if (eh + ec) > 0.5 * tot:
                    elem, lane, pitch = 'crash', 4, 49
                else:
                    elem, lane, pitch = 'ride', 3, 51
            conf = max(eh, ec) / tot
        else:
            if ek > em * 0.8:  # Very low kick threshold for intro
                elem, lane, pitch = 'kick', 0, 36
                conf = ek / (ek + em + 1e-9)
            else:
                if ehf > 0.15 * (ek + em + 1e-9):
                    elem, lane, pitch = 'snare', 1, 38
                    conf = ehf / (ek + em + 1e-9)
                else:
                    # Default to hihat for any remaining rhythmic content in intro
                    elem, lane, pitch = 'hihat', 2, 42
                    conf = eh / (eh + ec + 1e-9) if (eh + ec) > 0 else 0.5
        results.append(DrumElement(elem, float(min(conf, 1.0)), lane, pitch))
    return results


def extract_spectral_features(y: np.ndarray, sr: int) -> dict:
    """Extract spectral features for drum classification."""
    # STFT
    D = librosa.stft(y, n_fft=2048, hop_length=512)
    mag = np.abs(D)
    freqs = librosa.fft_frequencies(sr=sr)
    
    # Frequency bands
    def band_energy(fmin, fmax):
        mask = (freqs >= fmin) & (freqs <= fmax)
        return np.mean(mag[mask]) if np.any(mask) else 0
    
    # Spectral centroid
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    
    # Spectral rolloff
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
    
    # Spectral bandwidth
    bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)[0]
    
    # Zero crossing rate
    zcr = librosa.feature.zero_crossing_rate(y)[0]
    
    # RMS energy
    rms = librosa.feature.rms(y=y)[0]
    
    return {
        'sub_bass': band_energy(20, 60),
        'kick_band': band_energy(40, 100),
        'low_mid': band_energy(80, 250),
        'snare_band': band_energy(150, 250),
        'mid': band_energy(250, 500),
        'high_mid': band_energy(500, 2000),
        'presence': band_energy(2000, 6000),
        'hihat_band': band_energy(6000, 12000),
        'air': band_energy(12000, 20000),
        'centroid': np.mean(centroid),
        'rolloff': np.mean(rolloff),
        'bandwidth': np.mean(bandwidth),
        'zcr': np.mean(zcr),
        'rms': np.mean(rms),
    }


def classify_drum_onset(
    audio_segment: np.ndarray,
    sr: int = 44100,
) -> DrumElement:
    """
    Classify a drum onset into kick, snare, hi-hat, ride, crash, or tom.
    
    Uses frequency-band energy distribution and spectral features.
    """
    features = extract_spectral_features(audio_segment, sr)
    
    # Normalize band energies
    total = sum(features[k] for k in ['kick_band', 'snare_band', 'hihat_band', 'mid', 'presence'])
    if total == 0:
        return DrumElement('unknown', 0.0, 0, 0)
    
    norm = {k: v / total for k, v in features.items()}
    
    # Classification rules based on spectral characteristics
    
    # KICK: Strong sub-bass (40-100Hz), high RMS, low centroid
    kick_score = norm['kick_band'] * 2 + norm['sub_bass'] * 1.5
    
    # SNARE: 150-250Hz + broadband noise (high ZCR, medium centroid)
    snare_score = norm['snare_band'] * 2 + features['zcr'] * 0.5 + (1 - features['centroid'] / 8000) * 0.3
    
    # HI-HAT: 6-12kHz, short decay (high centroid, high ZCR, low RMS duration)
    hihat_score = norm['hihat_band'] * 3 + features['centroid'] / 10000 * 0.5
    
    # RIDE: 4-8kHz, longer decay, more tonal (lower ZCR than hihat)
    ride_score = norm['presence'] * 2 + (1 - features['zcr']) * 0.3
    
    # CRASH: Broadband, very loud, long decay (high across presence/air)
    crash_score = norm['presence'] * 1.5 + norm['air'] * 2 + features['rms'] * 0.5
    
    # TOMS: 80-300Hz, tonal, medium decay
    tom_score = norm['low_mid'] * 2 + norm['mid'] * 1.5
    
    scores = {
        'kick': kick_score,
        'snare': snare_score,
        'hihat': hihat_score,
        'ride': ride_score,
        'crash': crash_score,
        'tom': tom_score,
    }
    
    # Find best match
    best = max(scores, key=scores.get)
    confidence = scores[best] / (sum(scores.values()) + 1e-6)
    
    # Refine: distinguish hihat open vs closed
    if best == 'hihat':
        # Open hihat has more low-end and longer decay
        if norm['kick_band'] > 0.1 and features['centroid'] < 8000:
            best = 'hihat_open'
    
    # Refine: distinguish toms (tom1/2/3) by pitch
    if best == 'tom':
        # Estimate pitch from centroid
        if features['centroid'] > 300:
            best = 'tom1'
        elif features['centroid'] > 200:
            best = 'tom2'
        else:
            best = 'tom3'
    
    lane, pitch = DRUM_LANE_MAP.get(best, (0, 36))
    is_open = best == 'hihat_open'
    
    return DrumElement(
        element_type=best,
        confidence=min(confidence, 1.0),
        lane=lane,
        midi_pitch=pitch,
        is_open_hihat=is_open,
        metadata={'features': features, 'scores': scores},
    )


def classify_onsets_batch(
    audio_path: str,
    onset_times: np.ndarray,
    sr: int = 44100,
    window_ms: int = 100,
) -> list[DrumElement]:
    """
    Classify multiple onsets from an audio file.
    
    Extracts a window around each onset time and classifies.
    """
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    window_samples = int(sr * window_ms / 1000)
    half_window = window_samples // 2
    
    results = []
    for onset_time in onset_times:
        onset_sample = int(onset_time * sr)
        start = max(0, onset_sample - half_window)
        end = min(len(y), onset_sample + half_window)
        
        segment = y[start:end]
        if len(segment) < sr * 0.01:  # Skip too short segments
            results.append(DrumElement('unknown', 0.0, 0, 0))
            continue
        
        element = classify_drum_onset(segment, sr)
        results.append(element)
    
    return results


def detect_hihat_state_changes(
    elements: list[DrumElement],
    onset_times: np.ndarray,
) -> list[dict]:
    """
    Detect hi-hat open/closed transitions.
    
    Returns list of {time, state: 'open'/'closed'} events.
    """
    hihat_times = []
    hihat_states = []
    
    for elem, t in zip(elements, onset_times):
        if elem.element_type in ('hihat', 'hihat_open'):
            hihat_times.append(t)
            hihat_states.append(elem.element_type)
    
    if len(hihat_states) < 2:
        return []
    
    transitions = []
    for i in range(1, len(hihat_states)):
        if hihat_states[i] != hihat_states[i-1]:
            transitions.append({
                'time': hihat_times[i],
                'state': hihat_states[i],
            })
    
    return transitions


def detect_fills(
    elements: list[DrumElement],
    onset_times: np.ndarray,
    min_hits: int = 4,
    window_ms: float = 500,
    density_multiplier: float = 1.3,
) -> list[dict]:
    """
    Detect drum fills: rapid, multi-lane bursts that stand out from the groove.

    A steady groove (kick + snare + hat at a fixed rate) also packs several
    hits into a 500 ms window, so a naive ">= N hits in a window" rule fired on
    every bar and produced ~188 false fills (each becoming an overdrive phrase)
    on a 5-minute song. Instead the threshold is the song's own groove baseline
    (median hits-per-window, computed adaptively below) scaled up, and a fill
    must additionally span >= 2 distinct lanes — a real burst/roll, not a lone
    repeated hit.

    Returns list of {start_time, end_time, lanes_involved, hit_count}.
    """
    if len(elements) < min_hits:
        return []

    times = np.asarray(onset_times, dtype=float)

    # Groove baseline: median number of hits landing within window_ms of a hit.
    baseline_counts = []
    for i in range(len(elements)):
        j = i
        while j < len(elements) and (times[j] - times[i]) * 1000 <= window_ms:
            j += 1
        baseline_counts.append(j - i)
    baseline = float(np.median(baseline_counts)) if baseline_counts else 0.0
    threshold = max(min_hits, int(round(baseline * density_multiplier)) + 1)

    fills = []
    i = 0
    while i < len(elements):
        j = i
        while j < len(elements) and (times[j] - times[i]) * 1000 <= window_ms:
            j += 1
        cluster = elements[i:j]
        cluster_lanes = {e.lane for e in cluster}
        cluster_count = j - i

        if cluster_count >= threshold and len(cluster_lanes) >= 2:
            fills.append({
                'start_time': float(times[i]),
                'end_time': float(times[j - 1]),
                'lanes': sorted(cluster_lanes),
                'hit_count': cluster_count,
            })
            i = j
        else:
            i += 1

    return fills