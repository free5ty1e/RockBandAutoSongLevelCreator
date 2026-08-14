#!/usr/bin/env python

import librosa
import numpy as np
from pathlib import Path
import click
import json


def _detect_beats_from_onsets(y, sr, min_bpm=60, max_bpm=200):
    """Detect beats from onset envelope with reasonable BPM constraints."""
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo_estimate, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr,
        bpm=min(max(tempo_estimate, min_bpm), max_bpm) if 'tempo_estimate' in dir() else None,
        start_bpm=120.0,
        tightness=100  # Strict tempo adherence
    )
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    return beat_times


def _merge_beat_sequences(drum_beats, vocal_beats, max_gap=2.0):
    """Merge drum and vocal beat sequences, preferring drum beats where available.
    
    Uses vocal beats to fill gaps in drum beats (e.g., drumless intro).
    """
    if not drum_beats:
        return vocal_beats
    if not vocal_beats:
        return drum_beats
    
    # If drum beats start late (>10s), prepend vocal beats for the intro
    if drum_beats[0] > 10.0:
        # Find vocal beats that occur before the first drum beat
        intro_vocal = [b for b in vocal_beats if b < drum_beats[0] - 0.1]
        if intro_vocal:
            # Ensure smooth transition: last vocal beat should align with first drum beat
            # Use the tempo implied by the vocal beats to interpolate
            combined = sorted(intro_vocal + drum_beats)
            return combined
    
    # Also fill any large gaps in drum beats with vocal beats
    merged = [drum_beats[0]]
    for i in range(1, len(drum_beats)):
        gap = drum_beats[i] - drum_beats[i-1]
        if gap > max_gap:
            # Fill gap with vocal beats
            gap_vocal = [b for b in vocal_beats 
                        if drum_beats[i-1] < b < drum_beats[i]]
            if gap_vocal:
                merged.extend(gap_vocal)
        merged.append(drum_beats[i])
    
    return merged


def extract_tempo_map(drum_stem_path: Path, out_dir: Path, vocal_stem_path: Path = None):
    """
    Analyzes a drum stem to generate a dynamic tempo map.
    Falls back to vocal stem for drumless sections (intro, bridges).
    Saves the results to tempo_map.json in the output directory.
    """
    click.echo(f"Analyzing drum stem for dynamic tempo mapping: {drum_stem_path.name}...")
    
    # Load the drum stem
    y_drum, sr = librosa.load(str(drum_stem_path), sr=None, mono=True)
    
    # Isolate percussive transients
    click.echo("Isolating percussive transients...")
    y_percussive = librosa.effects.percussive(y_drum)
    
    # Calculate the onset envelope and track beats on drums
    click.echo("Calculating dynamic beat grid from drums...")
    onset_env = librosa.onset.onset_strength(y=y_percussive, sr=sr)
    tempo_estimate, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    
    # Convert frames to precise time (seconds)
    drum_beats = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    
    # Fallback: analyze vocal stem for drumless sections
    vocal_beats = []
    if vocal_stem_path and vocal_stem_path.exists():
        click.echo("Analyzing vocal stem for drumless section tempo...")
        y_vocal, _ = librosa.load(str(vocal_stem_path), sr=sr, mono=True)
        y_vocal_perc = librosa.effects.percussive(y_vocal, margin=3.0)
        vocal_onset_env = librosa.onset.onset_strength(y=y_vocal_perc, sr=sr)
        _, vocal_beat_frames = librosa.beat.beat_track(
            onset_envelope=vocal_onset_env, sr=sr, start_bpm=tempo_estimate
        )
        vocal_beats = librosa.frames_to_time(vocal_beat_frames, sr=sr).tolist()
        click.echo(f"Vocal stem yielded {len(vocal_beats)} beats.")
    
    # Merge beat sequences
    beat_times = _merge_beat_sequences(drum_beats, vocal_beats)
    
    # Calculate localized BPMs
    bpms = []
    for i in range(1, len(beat_times)):
        duration = beat_times[i] - beat_times[i-1]
        if duration > 0:
            bpms.append(60.0 / duration)
        else:
            bpms.append(0)
            
    if bpms:
        bpms.append(bpms[-1])
        
    click.echo(f"Extracted {len(beat_times)} dynamic beats. Overall Average Tempo: {np.mean(bpms):.2f} BPM.")
    if len(beat_times) > 5:
        click.echo(f"First 5 beat timestamps (seconds): {beat_times[:5]}")
        click.echo(f"First 5 dynamic tempos (BPM): {[f'{bpm:.2f}' for bpm in bpms[:5]]}")
    
    # Cache to JSON
    tempo_map = {
        "beat_times": beat_times,
        "bpms": bpms
    }
    
    map_path = out_dir / "tempo_map.json"
    with open(map_path, "w") as f:
        json.dump(tempo_map, f, indent=4)
        
    click.echo(f"Tempo map cached to {map_path}")
    
    return np.array(beat_times), bpms


def load_tempo_map(out_dir: Path):
    """
    Loads a previously cached tempo map from the output directory.
    """
    map_path = out_dir / "tempo_map.json"
    if not map_path.exists():
        raise FileNotFoundError(f"Tempo map cache not found at {map_path}")
        
    with open(map_path, "r") as f:
        data = json.load(f)
        
    # Convert beat_times back to a numpy array for downstream processing
    return np.array(data["beat_times"]), data["bpms"]
