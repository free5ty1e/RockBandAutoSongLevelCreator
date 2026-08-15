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


# Standard 5-lane drum mapping (Expert)
DRUM_LANE_MAP = {
    'kick': (0, 36),        # Green lane, C2
    'snare': (1, 38),       # Red lane, D2
    'hihat': (2, 42),       # Yellow lane, F#2
    'hihat_open': (2, 46),  # Yellow lane, A#2 (same lane, different pitch)
    'ride': (3, 51),        # Blue lane, D#3
    'crash': (4, 49),       # Orange lane, D#3
    'tom1': (2, 48),        # Yellow lane, C3
    'tom2': (1, 45),        # Red lane, A2
    'tom3': (0, 43),        # Green lane, G2
}

# Pro drums 7-lane additions
PRO_DRUM_LANES = {
    'hihat_pedal': (5, 44),  # Extra lane, G#2
    'crash2': (6, 52),       # Extra lane, E3
    'china': (6, 55),        # Extra lane, G3
}


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
    min_hits: int = 3,
    window_ms: float = 500,
) -> list[dict]:
    """
    Detect drum fills: rapid multi-lane hits.
    
    Returns list of {start_time, end_time, lanes_involved, hit_count}.
    """
    if len(elements) < min_hits:
        return []
    
    fills = []
    i = 0
    while i < len(elements):
        # Look for cluster of hits within window
        cluster_start = i
        cluster_lanes = {elements[i].lane}
        cluster_count = 1
        
        j = i + 1
        while j < len(elements) and (onset_times[j] - onset_times[i]) * 1000 <= window_ms:
            cluster_lanes.add(elements[j].lane)
            cluster_count += 1
            j += 1
        
        if cluster_count >= min_hits and len(cluster_lanes) >= 2:
            fills.append({
                'start_time': onset_times[i],
                'end_time': onset_times[j-1],
                'lanes': list(cluster_lanes),
                'hit_count': cluster_count,
            })
            i = j
        else:
            i += 1
    
    return fills