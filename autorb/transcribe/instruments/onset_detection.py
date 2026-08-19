"""
Shared onset detection for instrument transcription.

Provides multi-method onset detection optimized for different instrument stems.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import numpy as np
import librosa


@dataclass
class OnsetResult:
    """Results from onset detection."""
    times: np.ndarray          # Onset times in seconds
    strengths: np.ndarray      # Onset strength (0-1)
    sample_indices: np.ndarray # Onset sample indices


def detect_onsets_librosa(
    audio_path: Path,
    sr: int = 44100,
    hop_length: int = 512,
    backtrack: bool = True,
    pre_max: int = 20,
    post_max: int = 20,
    pre_avg: int = 100,
    post_avg: int = 100,
    delta: float = 0.02,
    wait: int = 5,
    window_seconds: float = 0.0,  # 0 = whole file (legacy global normalization)
) -> OnsetResult:
    """
    Detect onsets using librosa's spectral flux method.
    
    Works well for guitar, bass, and general instrument stems.
    
    If `window_seconds` > 0, processes audio in windows with local strength
    normalization to prevent early quiet sections from being crushed by later
    loud transients (the global 95th-percentile normalization problem).
    """
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    
    if window_seconds > 0:
        return _detect_onsets_windowed(
            y, sr, hop_length, backtrack, pre_max, post_max,
            pre_avg, post_avg, delta, wait, window_seconds
        )
    
    # Legacy whole-file processing (global normalization)
    return _detect_onsets_legacy(y, sr, hop_length, backtrack, pre_max, post_max,
                                  pre_avg, post_avg, delta, wait)


def _detect_onsets_legacy(
    y: np.ndarray, sr: int, hop_length: int, backtrack: bool,
    pre_max: int, post_max: int, pre_avg: int, post_avg: int,
    delta: float, wait: int,
) -> OnsetResult:
    """Original whole-file onset detection with global normalization."""
    onset_env = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=hop_length,
        aggregate=np.median, fmax=8000, n_mels=128
    )
    
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env, sr=sr, hop_length=hop_length,
        backtrack=backtrack, pre_max=pre_max, post_max=post_max,
        pre_avg=pre_avg, post_avg=post_avg, delta=delta, wait=wait,
    )
    
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)
    onset_samples = librosa.frames_to_samples(onset_frames, hop_length=hop_length)
    
    win = max(1, int(wait))
    onset_strengths = np.array([
        float(onset_env[f: f + win + 1].max()) if f + win < len(onset_env) else float(onset_env[f])
        for f in onset_frames
    ])
    
    if onset_strengths.size > 0:
        ref = float(np.percentile(onset_strengths, 95)) or float(onset_strengths.max())
        if ref > 0:
            onset_strengths = np.clip(onset_strengths / ref, 0.0, 1.0)
    
    return OnsetResult(
        times=librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length),
        strengths=onset_strengths,
        sample_indices=librosa.frames_to_samples(onset_frames, hop_length=hop_length),
    )


def _detect_onsets_windowed(
    y: np.ndarray, sr: int, hop_length: int, backtrack: bool,
    pre_max: int, post_max: int, pre_avg: int, post_avg: int,
    delta: float, wait: int, window_seconds: float,
) -> OnsetResult:
    """Windowed onset detection with local strength normalization."""
    window_samples = int(window_seconds * sr)
    hop_samples = hop_length
    
    all_times = []
    all_strengths = []
    all_samples = []
    
    # Process in overlapping windows
    window_step = int(window_seconds * sr * 0.5)  # 50% overlap
    n_samples = len(y)
    
    for start in range(0, n_samples, window_step):
        end = min(start + window_samples, n_samples)
        if end - start < sr * 0.5:  # Skip very short final window
            break
            
        y_win = y[start:end]
        win_sr = sr
        
        onset_env = librosa.onset.onset_strength(
            y=y_win, sr=sr, hop_length=hop_length,
            aggregate=np.median, fmax=8000, n_mels=128
        )
        
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_env, sr=sr, hop_length=hop_length,
            backtrack=True, pre_max=20, post_max=20,
            pre_avg=100, post_avg=100, delta=0.02, wait=5,
        )
        
        if len(onset_frames) == 0:
            continue
            
        # Local strength normalization within this window
        win = max(1, 5)  # wait=5 frames
        onset_strengths = np.array([
            float(onset_env[f: f + win + 1].max()) if f + win < len(onset_env) else float(onset_env[f])
            for f in onset_frames
        ])
        
        if onset_strengths.size > 0:
            ref = float(np.percentile(onset_strengths, 95)) or float(onset_strengths.max())
            if ref > 0:
                onset_strengths = np.clip(onset_strengths / ref, 0.0, 1.0)
        
        # Convert to global time
        frame_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)
        global_times = frame_times + (start / sr)
        global_samples = librosa.frames_to_samples(onset_frames, hop_length=hop_length) + start
        
        all_times.extend(global_times)
        all_strengths.extend(onset_strengths)
        all_samples.extend(global_samples)
    
    if not all_times:
        return OnsetResult(times=np.array([]), strengths=np.array([]), sample_indices=np.array([]))
    
    # Merge overlapping detections from adjacent windows
    all_times = np.array(all_times)
    all_strengths = np.array(all_strengths)
    all_samples = np.array(all_samples)
    
    # Sort by time
    order = np.argsort(all_times)
    all_times = all_times[order]
    all_strengths = all_strengths[order]
    all_samples = all_samples[order]
    
    # Deduplicate nearby detections (from window overlap)
    min_interval = 0.02  # 20ms minimum separation
    keep = [True]
    for i in range(1, len(all_times)):
        if all_times[i] - all_times[i-1] < 0.02:
            # Keep the stronger one
            if all_strengths[i] > all_strengths[i-1]:
                keep[-1] = False
                keep.append(True)
            else:
                keep.append(False)
        else:
            keep.append(True)
    
    return OnsetResult(
        times=all_times[keep],
        strengths=all_strengths[keep],
        sample_indices=all_samples[keep],
    )


def detect_onsets_madmom(
    audio_path: Path,
    fps: int = 100,
    threshold: float = 0.3,
    smooth: float = 0.07,
) -> OnsetResult:
    """
    Detect onsets using madmom's neural network onset detector.
    
    More accurate for drums and complex polyphonic material.
    """
    try:
        from madmom.features.onsets import CNNOnsetProcessor, OnsetPeakPickingProcessor
    except ImportError:
        # Fallback to librosa
        return detect_onsets_librosa(audio_path)
    
    # CNN-based onset detection
    proc = CNNOnsetProcessor()
    onset_env = proc(audio_path)
    
    # Peak picking
    peak_proc = OnsetPeakPickingProcessor(fps=fps, threshold=threshold, smooth=smooth)
    onset_frames = peak_proc(onset_env)
    
    onset_times = np.array(onset_frames)
    onset_samples = (onset_times * 44100).astype(int)
    
    # Get strengths from envelope at onset frames
    frame_indices = (onset_times * fps).astype(int)
    frame_indices = np.clip(frame_indices, 0, len(onset_env) - 1)
    onset_strengths = onset_env[frame_indices]
    
    if onset_strengths.max() > 0:
        onset_strengths = onset_strengths / onset_strengths.max()
    
    return OnsetResult(
        times=onset_times,
        strengths=onset_strengths,
        sample_indices=onset_samples,
    )


def detect_onsets_multi_band(
    audio_path: Path,
    bands: list = None,
    sr: int = 44100,
) -> dict[str, OnsetResult]:
    """
    Multi-band onset detection for drum element separation.
    
    Splits audio into frequency bands and detects onsets in each band.
    Useful for classifying kick, snare, hi-hat, cymbals, toms.
    
    Default bands (Hz):
    - kick: 40-100
    - snare: 150-250
    - hihat: 6000-12000
    - ride: 4000-8000
    - crash: 4000-8000
    - toms: 80-300
    """
    if bands is None:
        bands = {
            'kick': (40, 100),
            'snare': (150, 250),
            'hihat': (6000, 12000),
            'ride': (4000, 8000),
            'crash': (4000, 8000),
            'toms': (80, 300),
        }
    
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    results = {}
    
    for name, (fmin, fmax) in bands.items():
        # Bandpass filter
        y_band = librosa.effects.preemphasis(y)
        # Simple bandpass using FFT
        D = librosa.stft(y_band)
        freqs = librosa.fft_frequencies(sr=sr)
        mask = (freqs >= fmin) & (freqs <= fmax)
        D_band = D * mask[:, np.newaxis]
        y_band = librosa.istft(D_band)
        
        # Onset detection on band
        onset_env = librosa.onset.onset_strength(
            y=y_band, sr=sr, hop_length=512,
            aggregate=np.max, fmax=fmax, n_mels=64
        )
        
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_env,
            sr=sr,
            hop_length=512,
            delta=0.05,
            wait=3,
        )
        
        onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=512)
        onset_strengths = onset_env[onset_frames]
        
        if onset_strengths.max() > 0:
            onset_strengths = onset_strengths / onset_strengths.max()
        
        results[name] = OnsetResult(
            times=onset_times,
            strengths=onset_strengths,
            sample_indices=librosa.frames_to_samples(onset_frames, hop_length=512),
        )
    
    return results


def merge_nearby_onsets(
    onsets: OnsetResult,
    min_interval: float = 0.03,  # 30ms minimum between onsets
) -> OnsetResult:
    """
    Merge onsets that are too close together (likely same hit).
    
    Keeps the stronger onset when merging.
    """
    if len(onsets.times) <= 1:
        return onsets
    
    keep = [True] * len(onsets.times)
    
    for i in range(1, len(onsets.times)):
        if onsets.times[i] - onsets.times[i-1] < min_interval:
            # Merge: keep the stronger one
            if onsets.strengths[i] > onsets.strengths[i-1]:
                keep[i-1] = False
            else:
                keep[i] = False
    
    mask = np.array(keep)
    return OnsetResult(
        times=onsets.times[mask],
        strengths=onsets.strengths[mask],
        sample_indices=onsets.sample_indices[mask],
    )


def filter_onsets_by_strength(
    onsets: OnsetResult,
    min_strength: float = 0.1,
) -> OnsetResult:
    """Filter out weak onsets below threshold."""
    mask = onsets.strengths >= min_strength
    return OnsetResult(
        times=onsets.times[mask],
        strengths=onsets.strengths[mask],
        sample_indices=onsets.sample_indices[mask],
    )