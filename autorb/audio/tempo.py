#!/usr/bin/env python

import librosa
import numpy as np
from pathlib import Path
import click

def extract_tempo_map(drum_stem_path: Path):
    """
    Analyzes a drum stem to generate a dynamic tempo map.
    Returns:
        beat_times (np.ndarray): An array of timestamps (in seconds) for every detected beat.
        bpms (list): A list of dynamic BPMs corresponding to the tempo at each beat.
    """
    click.echo(f"Analyzing drum stem for dynamic tempo mapping: {drum_stem_path.name}...")
    
    # Load the drum stem (mono is highly preferred for transient detection)
    y, sr = librosa.load(str(drum_stem_path), sr=None, mono=True)
    
    # Isolate percussive transients for cleaner beat detection
    click.echo("Isolating percussive transients...")
    y_percussive = librosa.effects.percussive(y)
    
    # Calculate the onset envelope (where hits occur)
    onset_env = librosa.onset.onset_strength(y=y_percussive, sr=sr)
    
    # Track the dynamic beat grid
    click.echo("Calculating dynamic beat grid...")
    tempo_estimate, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    
    # Convert librosa frames to precise time (seconds)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    
    # Calculate the localized BPM between each individual beat
    # BPM = 60 / duration_of_beat_in_seconds
    bpms = []
    for i in range(1, len(beat_times)):
        duration = beat_times[i] - beat_times[i-1]
        
        # Avoid division by zero in any weird edge cases
        if duration > 0:
            bpm = 60.0 / duration
            bpms.append(bpm)
        else:
            bpms.append(0)
            
    # The final beat doesn't have a "next" beat to calculate duration, 
    # so we'll gracefully duplicate the last known tempo to cap off the array
    if bpms:
        bpms.append(bpms[-1])
        
    click.echo(f"Extracted {len(beat_times)} dynamic beats. Overall Average Tempo: {np.mean(bpms):.2f} BPM.")
    
    return beat_times, bpms
