#!/usr/bin/env python

import click
from pathlib import Path
import torch

@click.command()
@click.argument('audio_file', type=click.Path(exists=True))
@click.option('--artist', required=True, help='Artist name')
@click.option('--title', required=True, help='Song title')
@click.option('--year', type=int, required=True, help='Release year')
@click.option('--genre', required=True, help='Song genre')
@click.option('--lyrics', type=click.Path(exists=True), required=True, help='Path to LRC file')
@click.option('--output-dir', default='./output', type=click.Path(), help='Output directory')
@click.option('--skip-separation', is_flag=True, help='Skip Demucs separation and use existing stems in the output directory')
def main(audio_file, artist, title, year, genre, lyrics, output_dir, skip_separation):
    click.echo(f"Starting AutoRB Pipeline for: {artist} - {title}")
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    click.echo(f"Using compute device: {device}")
    
    out_path = Path(output_dir)
    stems_dir = out_path / "stems"

    if skip_separation:
        click.echo("\n[1/5] Skipping Demucs separation. Loading existing stems...")
        stems = {
            "drums": stems_dir / "drums.wav",
            "bass": stems_dir / "bass.wav",
            "other": stems_dir / "other.wav",
            "vocals": stems_dir / "vocals.wav"
        }
        
        # Validate that the user actually provided all 4 required files
        for name, path in stems.items():
            if not path.exists():
                click.echo(f"Error: --skip-separation used, but missing required stem: {path}", err=True)
                return
        click.echo("All pre-existing stems found successfully.")
    else:
        click.echo("\n[1/5] Separating stems via Demucs...")
        from autorb.audio.stems import separate_stems
        stems = separate_stems(audio_file, out_path, device=device)

    click.echo(f"Stems ready: {stems}")

    click.echo("\n[2/5] Extracting tempo and quantizing instruments...")
    from autorb.audio.tempo import extract_tempo_map
    beat_times, dynamic_bpms = extract_tempo_map(stems["drums"])
    
    click.echo(f"First 5 beat timestamps (seconds): {beat_times[:5]}")
    click.echo(f"First 5 dynamic tempos (BPM): {[f'{bpm:.2f}' for bpm in dynamic_bpms[:5]]}")

    click.echo("\n[3/5] Aligning vocals and parsing LRC...")
    # [Placeholder for next step]

    click.echo("\n[4/5] Generating MOGG and DTA metadata...")
    # [Placeholder for next step]

    click.echo("\n[5/5] Packaging Xbox 360 CON file...")
    # [Placeholder for next step]

if __name__ == '__main__':
    main()
    
