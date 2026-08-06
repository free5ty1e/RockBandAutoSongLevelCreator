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
@click.option('--skip-mogg', is_flag=True, help='Skip MOGG building and use existing .mogg file')
@click.option('--album-art', type=click.Path(exists=True), default=None, help='Path to a custom album art image (PNG/JPG); defaults to the generated "Chris Prime Custom" art')
@click.option('--build-pkg', is_flag=True, help='Build PS4 PKG installer from the generated CON')
@click.option('--generate-freestyle-vocals', is_flag=True, help='Enable Rock Band 4 freestyle-vocals guide lines (Hard/Expert) by setting HasFreestyleVocals in the PS4 songdta')
def main(audio_file, artist, title, year, genre, lyrics, output_dir, skip_separation, skip_tempo_detection, skip_vocals, skip_mogg, album_art, build_pkg, generate_freestyle_vocals):
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

    click.echo("\n[4/5] Synchronizing beats and lyrics data...")
    from autorb.audio.step4_sync import run_step_4
    
    beats_json = out_path / "tempo_map.json"
    lyrics_json = out_path / "vocals_cache.json"
    synced_output_json = out_path / "synced_track.json"
    
    try:
        run_step_4(str(beats_json), str(lyrics_json), str(synced_output_json))
        click.echo(f"Successfully generated synchronized track data at: {synced_output_json}")
    except Exception as e:
        click.echo(f"Error during step 4 synchronization: {e}", err=True)
        return

    click.echo("\n[5/5] Building assets and packaging Xbox 360 CON file...")
    from autorb.export.midi_generator import generate_vocal_midi
    from autorb.export.dta_writer import generate_songs_dta
    from autorb.export.con_packer import package_con
    from autorb.export.key_detect import detect_vocal_key
    
    # Generate a filesystem-safe song ID from the title
    song_id = title.lower().replace(" ", "_").replace("'", "")

    try:
        # 1. Build the .mogg audio container from your separated stem WAVs
        click.echo("Building MOGG audio container from stems...")
        from autorb.export.mogg_builder import build_mogg_from_stems, read_mogg_duration_ms
        from autorb.export.midi_generator import count_in_params
        # Mandatory count-in: prepend silence to the MOGG and shift the whole
        # chart past it (mirrors stock RB3 DLC, e.g. 311 - Down's ~5s lead-in).
        # When reusing an existing MOGG via --skip-mogg, disable the count-in so
        # the chart keeps matching the un-shifted audio it was built against.
        count_in_ticks, count_in_ms = (0, 0) if skip_mogg else count_in_params(list(beat_times))
        if count_in_ticks:
            click.echo(f"Prepending {count_in_ms} ms count-in (opening-tempo, {count_in_ticks} ticks)...")
        mogg_file = build_mogg_from_stems(stems_dir, out_path, song_id, skip_mogg=skip_mogg,
                                          count_in_ms=count_in_ms)

        # 2. Generate the PART VOCALS .mid chart from synced_track.json
        click.echo("Generating vocal MIDI chart (dynamic tempo map from beat grid)...")
        avg_bpm = sum(dynamic_bpms) / len(dynamic_bpms) if dynamic_bpms else 120.0
        song_length_ms = read_mogg_duration_ms(mogg_file)
        midi_file = generate_vocal_midi(
            synced_output_json, out_path, song_id,
            song_length_ms=song_length_ms,
            bpm=avg_bpm,
            beat_times=list(beat_times),
            dynamic_bpms=list(dynamic_bpms),
            count_in_ticks=count_in_ticks,
            count_in_ms=count_in_ms,
        )

        # 3. Generate songs.dta configuration metadata
        click.echo("Generating songs.dta metadata...")
        metadata = {
            "title": title,
            "artist": artist,
            "year": year,
            "genre": genre,
            "song_id_num": abs(hash(song_id)) % 100000000,
            "album": title
        }
        vocal_tonic_note, song_tonality = detect_vocal_key(vocal_notes)
        if generate_freestyle_vocals:
            click.echo("Freestyle vocals enabled: setting HasFreestyleVocals so the PS4 song advertises freestyle-vocals guide lines.")
        dta_path = generate_songs_dta(song_id, metadata, out_path,
                                      vocal_tonic_note=vocal_tonic_note,
                                      song_tonality=song_tonality,
                                      freestyle_vocals=generate_freestyle_vocals)

        # 4. Package everything into the Xbox 360 CON/STFS container
        click.echo("Packaging into CON container...")
        from autorb.export.texture import keep_texture_from_image, default_album_art_bytes
        if album_art is not None:
            click.echo(f"Encoding custom album art from {album_art}...")
            album_art_bytes = keep_texture_from_image(album_art)
        else:
            click.echo("Generating default 'Chris Prime Custom' album art...")
            album_art_bytes = default_album_art_bytes()
        con_output_path = package_con(
            output_dir=out_path,
            song_id=song_id,
            mogg_path=mogg_file,
            midi_path=midi_file,
            dta_path=dta_path,
            album_art_bytes=album_art_bytes
        )
        click.echo(f"CON file successfully packaged: {con_output_path}")

        if build_pkg:
            click.echo("\n[6/5] Building PS4 PKG installer...")
            from autorb.export.con_packer import build_ps4_pkg
            pkg_path = build_ps4_pkg(con_output_path, out_path, song_id)
            click.echo(f"PS4 PKG installer successfully built: {pkg_path}")

    except Exception as e:

        click.echo(f"Error during asset building or CON packaging: {e}", err=True)
        return

    click.echo(f"\nPipeline complete! All assets ready in: {out_path}")

if __name__ == '__main__':
    main()
