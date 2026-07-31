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
@click.option('--skip-separation', is_flag=True, help='Skip Demucs separation and use existing stems')
@click.option('--skip-tempo-detection', is_flag=True, help='Skip beat tracking and use cached tempo map')
@click.option('--skip-vocals', is_flag=True, help='Skip vocal alignment and pitch extraction (uses cached data)')
def main(audio_file, artist, title, year, genre, lyrics, output_dir, skip_separation, skip_tempo_detection, skip_vocals):
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
        for name, path in stems.items():
            if not path.exists():
                click.echo(f"Error: missing required stem: {path}", err=True)
                return
        click.echo("All pre-existing stems found successfully.")
    else:
        click.echo("\n[1/5] Separating stems via Demucs...")
        from autorb.audio.stems import separate_stems
        stems = separate_stems(audio_file, out_path, device=device)

    click.echo(f"Stems ready: {stems}")

    if skip_tempo_detection:
        click.echo("\n[2/5] Skipping tempo detection. Loading cached tempo map...")
        from autorb.audio.tempo import load_tempo_map
        try:
            beat_times, dynamic_bpms = load_tempo_map(out_path)
            click.echo("Successfully loaded tempo map from cache.")
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            return
    else:
        click.echo("\n[2/5] Extracting tempo and quantizing instruments...")
        from autorb.audio.tempo import extract_tempo_map
        # Notice we are passing out_path here now so it knows where to save the JSON
        beat_times, dynamic_bpms = extract_tempo_map(stems["drums"], out_path)
        
    click.echo(f"First 5 beat timestamps (seconds): {beat_times[:5]}")
    click.echo(f"First 5 dynamic tempos (BPM): {[f'{bpm:.2f}' for bpm in dynamic_bpms[:5]]}")

    if skip_vocals:
        click.echo("\n[3/5] Skipping vocal extraction. Loading cached data...")
        from autorb.audio.vocals import load_vocals_cache
        try:
            lyrics_data, word_segments, vocal_notes = load_vocals_cache(out_path)
            click.echo("Successfully loaded vocals data from cache.")
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            return
    else:
        click.echo("\n[3/5] Aligning vocals and parsing LRC...")
        from autorb.audio.vocals import process_vocals
        # Pass out_path so it knows where to save the JSON cache
        lyrics_data, word_segments, vocal_notes = process_vocals(stems["vocals"], lyrics, out_path)
    
    if word_segments:
        first_word = word_segments[0]
        w_text = first_word.get('word', '')
        w_start = first_word.get('start', 0.0)
        w_end = first_word.get('end', 0.0)
        click.echo(f"First aligned word: '{w_text}' (Starts: {w_start:.2f}s, Ends: {w_end:.2f}s)")
    
    if vocal_notes:
        first_note = vocal_notes[0]
        click.echo(f"First vocal note: starts at {first_note[0]:.2f}s, MIDI pitch {first_note[2]}")

    click.echo("\n[4/5] Generating MOGG and DTA metadata...")
    # [Placeholder for next step]

    click.echo("\n[5/5] Packaging Xbox 360 CON file...")
    # [Placeholder for next step]

if __name__ == '__main__':
    main()
