#!/usr/bin/env python

import librosa
import numpy as np
from pathlib import Path
import click
import json

def extract_tempo_map(drum_stem_path: Path, out_dir: Path):
    """
    Analyzes a drum stem to generate a dynamic tempo map.
    Saves the results to tempo_map.json in the output directory.
    """
    click.echo(f"Analyzing drum stem for dynamic tempo mapping: {drum_stem_path.name}...")
    
    # Load the drum stem
    y, sr = librosa.load(str(drum_stem_path), sr=None, mono=True)
    
    # Isolate percussive transients
    click.echo("Isolating percussive transients...")
    y_percussive = librosa.effects.percussive(y)
    
    # Calculate the onset envelope and track beats
    click.echo("Calculating dynamic beat grid...")
    onset_env = librosa.onset.onset_strength(y=y_percussive, sr=sr)
    tempo_estimate, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    
    # Convert frames to precise time (seconds)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    
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
