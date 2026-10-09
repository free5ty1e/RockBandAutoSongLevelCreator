#!/usr/bin/env python3
"""
Stem Quality Analyzer

Analyzes stem separation quality, detects cross-stem leakage,
and recommends best stem per instrument.
"""

import librosa
import numpy as np
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List
from scipy.signal import butter, sosfiltfilt

@dataclass
class StemQualityMetrics:
    stem_name: str
    duration: float
    rms_full: float
    rms_per_band: dict
    dynamic_range: float
    onset_count: int
    onset_density_per_sec: float
    leakage_score: float
    recommended_for: list

def band_rms(y: np.ndarray, sr: int, fmin: float, fmax: float) -> float:
    """RMS energy in frequency band."""
    nyq = sr / 2.0
    lo = max(fmin / nyq, 1e-3)
    hi = min(fmax / nyq, 0.99)
    if hi <= lo:
        hi = min(lo * 1.5, 0.99)
    sos = butter(4, [lo, hi], btype='band', output='sos')
    yb = sosfiltfilt(sos, y)
    return float(np.sqrt(np.mean(yb ** 2)))

def analyze_stem(stem_path: Path, sr: int = 44100) -> StemQualityMetrics:
    """Analyze a single stem for quality metrics."""
    y, _ = librosa.load(stem_path, sr=sr, mono=True)
    duration = len(y) / sr
    
    # Full RMS
    rms_full = float(np.sqrt(np.mean(y ** 2)))
    
    # Per-band RMS
    bands = {
        'sub': (20, 60),
        'kick': (30, 110),
        'snare_body': (110, 350),
        'snare_snap': (2000, 14000),
        'hihat': (7000, 14000),
        'cymbal': (3000, 9000),
        'guitar_low': (70, 400),
        'guitar_mid': (400, 2000),
        'guitar_high': (2000, 6000),
        'bass_fund': (38, 250),
        'vocal_fund': (80, 400),
        'vocal_presence': (2000, 5000),
    }
    
    rms_per_band = {}
    for name, (fmin, fmax) in bands.items():
        rms_per_band[name] = band_rms(y, 44100, fmin, fmax)
    
    # Dynamic range
    frame_rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    dynamic_range = float(np.max(frame_rms) / (np.min(frame_rms) + 1e-9))
    
    # Onset detection
    onset_env = librosa.onset.onset_strength(y=y, sr=44100, hop_length=512)
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=44100, hop_length=512)
    onset_count = len(onset_frames)
    onset_density = onset_count / duration if duration > 0 else 0
    
    # Cross-stem leakage (requires other stems, simplified here)
    # leakage_score = cross_stem_correlation(stem_path, other_stems)
    leakage_score = 0.0  # Placeholder
    
    # Recommend instruments based on spectral content
    recommended = []
    if rms_per_band['kick'] > 0.001 and rms_per_band['snare_body'] > 0.001:
        recommended.append('drums')
    if rms_per_band['bass_fund'] > 0.001:
        recommended.append('bass')
    if rms_per_band['guitar_mid'] > 0.001 or rms_per_band['guitar_high'] > 0.001:
        recommended.append('guitar')
    if rms_per_band['guitar_high'] > 0.002:
        recommended.append('keys')
    if rms_per_band['vocal_fund'] > 0.001 and rms_per_band['vocal_presence'] > 0.001:
        recommended.append('vocals')
    
    return StemQualityMetrics(
        stem_name="",
        duration=duration,
        rms_full=rms_full,
        rms_per_band=rms_per_band,
        dynamic_range=dynamic_range,
        onset_count=onset_count,
        onset_density_per_sec=onset_density,
        leakage_score=leakage_score,
        recommended_for=recommended
    )

def analyze_all_stems(stem_dir: Path) -> Dict[str, StemQualityMetrics]:
    """Analyze all stems in directory."""
    results = {}
    for stem_file in stem_dir.glob("*.wav"):
        stem_name = stem_file.stem
        metrics = analyze_stem(stem_file)
        metrics.stem_name = stem_file.name
        results[stem_name] = metrics
    return results

def cross_stem_leakage(stems: Dict[str, np.ndarray], sr: int) -> Dict[str, float]:
    """Detect cross-stem leakage by correlation."""
    leakage = {}
    names = list(stems.keys())
    for i, name1 in enumerate(names):
        for name2 in names[i+1:]:
            # Correlation in drum-relevant bands
            corr = np.corrcoef(stems[name1][:min(len(stems[name1]), len(stems[name2]))],
                               stems[name2][:min(len(stems[name1]), len(stems[name2]))])[0,1]
            leakage[f"{name1}-{name2}"] = abs(float(corr))
    return leakage

def analyze_stem_dir(stem_dir: Path, output_json: Path = None):
    """Analyze all stems in directory."""
    stem_files = list(stem_dir.glob("*.wav"))
    results = {}
    
    for stem_file in stem_files:
        print(f"Analyzing {stem_file.name}...")
        metrics = analyze_stem(stem_file)
        metrics.stem_name = stem_file.name
        results[stem_file.stem] = metrics
    
    if output_json:
        with open(output_json, 'w') as f:
            json.dump({k: v.__dict__ for k, v in results.items()}, f, indent=2)
    
    # Print summary
    print("\n=== STEM QUALITY ANALYSIS ===")
    for name, metrics in results.items():
        print(f"\n{name}:")
        print(f"  Duration: {metrics.duration:.1f}s")
        print(f"  RMS Full: {metrics.rms_full:.6f}")
        print(f"  Dynamic Range: {metrics.dynamic_range:.1f}")
        print(f"  Onsets: {metrics.onset_count} ({metrics.onset_density_per_sec:.1f}/sec)")
        print(f"  Recommended for: {', '.join(metrics.recommended_for) or 'none'}")
        print(f"  Band RMS:")
        for band, rms in metrics.rms_per_band.items():
            print(f"  {band:15s}: {rms:.6f}")
    
    return results

if __name__ == "__main__":
    import sys
    stem_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/workspaces/RockBandAutoSongLevelCreator/output/stems")
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    analyze_stem_dir(Path(stem_dir), Path(output) if output else None)