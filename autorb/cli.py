#!/usr/bin/env python

import click
import os
from pathlib import Path
import torch
from autorb.audio.stems import separate_stems

@click.command()
@click.argument('audio_file', type=click.Path(exists=True))
@click.option('--lyrics', '-l', type=click.Path(exists=True), help='Path to standard or Enhanced LRC lyrics file.')
@click.option('--artist', '-a', required=True, prompt=True, help='Artist name')
@click.option('--title', '-t', required=True, prompt=True, help='Song title')
@click.option('--year', '-y', default=2024, help='Year of release')
@click.option('--genre', '-g', default='Rock', help='Song genre')
@click.option('--output-dir', '-o', default='./output', type=click.Path(), help='Directory to save the resulting CON file.')
def main(audio_file, lyrics, artist, title, year, genre, output_dir):
    """
    AutoRB: Generate Rock Band 3 CON files from audio and lyrics.
    """
    click.echo(f"Starting AutoRB Pipeline for: {artist} - {title}")
    
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    # Determine best device
    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    click.echo(f"Using compute device: {device}")
    
    # Pipeline stages
    click.echo("[1/5] Separating stems via Demucs...")
    stems = separate_stems(audio_file, out_path, device=device)
    click.echo(f"Stems generated: {stems}")
    
    click.echo("[2/5] Extracting tempo and quantizing instruments...")
    from autorb.audio.tempo import extract_tempo_map
    
    # Pass the drums.wav path to our new tempo mapper
    beat_times, dynamic_bpms = extract_tempo_map(stems["drums"])
    
    # Echo the first few beats just so we can visually verify the drift in the console
    click.echo(f"First 5 beat timestamps (seconds): {beat_times[:5]}")
    click.echo(f"First 5 dynamic tempos (BPM): {[f'{bpm:.2f}' for bpm in dynamic_bpms[:5]]}")

    click.echo("\n[3/5] Aligning vocals and parsing LRC...")
    # ... rest of your code ...   
    
    click.echo("[3/5] Aligning vocals and parsing LRC...")
    
    click.echo("[4/5] Generating MOGG and DTA metadata...")
    
    click.echo("[5/5] Packaging Xbox 360 CON file...")
    
    click.echo(f"Success! CON file saved to {out_path.absolute()}")

if __name__ == '__main__':
    main()
