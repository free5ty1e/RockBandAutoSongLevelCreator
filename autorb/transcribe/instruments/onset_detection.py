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
) -> OnsetResult:
    """
    Detect onsets using librosa's spectral flux method.
    
    Works well for guitar, bass, and general instrument stems.
    """
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    
    # Compute onset envelope (spectral flux)
    onset_env = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=hop_length,
        aggregate=np.median, fmax=8000, n_mels=128
    )
    
    # Find peaks in onset envelope
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=hop_length,
        backtrack=backtrack,
        pre_max=pre_max,
        post_max=post_max,
        pre_avg=pre_avg,
        post_avg=post_avg,
        delta=delta,
        wait=wait,
    )
    
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)
    onset_samples = librosa.frames_to_samples(onset_frames, hop_length=hop_length)

    # Strength must be taken from the envelope PEAK in a small window *after* each
    # onset. With backtrack=True the onset frame sits at the onset *start* (envelope
    # ~0 there), so indexing onset_env[onset_frames] directly yields ~0 for almost
    # every hit and any strength filter would discard them all.
    win = max(1, int(wait))
    onset_strengths = np.array([
        float(onset_env[f: f + win + 1].max()) if f + win < len(onset_env) else float(onset_env[f])
        for f in onset_frames
    ])

    # Normalize strengths to 0-1. Use the 95th percentile (not the global max) as
    # the reference so a single loud transient doesn't crush every other hit to
    # near-zero — otherwise downstream strength filters drop the vast majority of
    # legitimate onsets on a track with one dominant hit (e.g. a big crash).
    if onset_strengths.size > 0:
        ref = float(np.percentile(onset_strengths, 95)) or float(onset_strengths.max())
        if ref > 0:
            onset_strengths = np.clip(onset_strengths / ref, 0.0, 1.0)

    return OnsetResult(
        times=onset_times,
        strengths=onset_strengths,
        sample_indices=onset_samples,
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