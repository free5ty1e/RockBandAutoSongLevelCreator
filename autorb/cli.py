#!/usr/bin/env python

import click
from pathlib import Path
import torch
import re


def _generate_ps4_pkg_id(artist: str, title: str, custom_id: str | None = None) -> str:
    """Generate a 16-char PS4 Content ID from title + artist.
    
    Format: UP8802-CUSA02084_00-XXXXXXXXXXXXXXXX (16 chars after the prefix).
    Auto-generated from title + artist (UPPERCASE alphanumeric only, truncated/padded).
    Title first for better uniqueness (fewer songs share a title than share an artist).
    PS4 requires uppercase A-Z and 0-9 for the last 16 chars.
    """
    if custom_id:
        # Use provided ID, pad or truncate to 16 chars, UPPERCASE
        clean = re.sub(r'[^a-zA-Z0-9]', '', custom_id).upper()
        return clean[:16].ljust(16, '0')
    
    # Auto-generate from title + artist (title first for uniqueness)
    combined = f"{title}{artist}"
    clean = re.sub(r'[^a-zA-Z0-9]', '', combined).upper()
    return clean[:16].ljust(16, '0')


@click.command()
@click.argument('audio_file', type=click.Path(exists=True), required=False)
@click.option('--artist', default=None, help='Artist name')
@click.option('--title', default=None, help='Song title')
@click.option('--year', type=int, default=None, help='Release year')
@click.option('--genre', default=None, help='Song genre')
@click.option('--lyrics', type=click.Path(exists=True), default=None, help='Path to LRC file')
@click.option('--output-dir', default='./output', type=click.Path(), help='Output directory')
@click.option('--skip-separation', is_flag=True, help='Skip Demucs separation and use existing stems')
@click.option('--use-ft-stems', is_flag=True, help='Use the fine-tuned htdemucs_ft Demucs model (cleaner stem separation; the FULL ensemble of fine-tuned sub-models is used, separated in 45 s overlapping strips so it completes on an 8 GB CPU). Slower than the default htdemucs; shifts and strip-length are tunable with --ft-shifts / --ft-strip-seconds')
@click.option('--ft-shifts', type=int, default=1, show_default=True, help='Demucs translation-averaging passes for --use-ft-stems (shifts>1 averages shifted copies for cleaner stems at N x time; verified on Open Road Song that shifts=2 gives no bleed gain over shifts=1, so 1 is the default)')
@click.option('--ft-strip-seconds', type=float, default=45.0, show_default=True, help='Strip length (seconds) for --use-ft-stems. Lower = less peak RAM (fallback if 45 s OOMs to 20 s) at the cost of more strip-seams (inaudible with the 10 s crossfade). Tune down on memory-constrained CPUs')
@click.option('--ft-segment', type=float, default=None, help='Demucs internal segment length (seconds) for --use-ft-stems; None (default) = full-context (highest quality). Small values lower memory further but degrade quality')
@click.option('--skip-tempo-detection', is_flag=True, help='Skip beat tracking and use cached tempo map')
@click.option('--skip-vocals', is_flag=True, help='Skip vocal alignment and pitch extraction (uses cached data)')
@click.option('--skip-mogg', is_flag=True, help='Skip MOGG encoding and reuse the existing .mogg in the output dir (which is expected to already contain the count-in lead-in); the chart is still shifted to match it')
@click.option('--album-art', type=click.Path(exists=True), default=None, help='Path to a custom album art image (PNG/JPG); defaults to the generated "Chris Prime Custom" art')
@click.option('--build-pkg', is_flag=True, help='Build PS4 PKG installer from the generated CON')
@click.option('--build-clone-hero', is_flag=True, help='Also export a Clone Hero-format song folder (song.ini + notes.mid + song.ogg + album.png) under <output-dir>/clone_hero/ for computer-based playtest/preview without a PS4')
@click.option('--generate-freestyle-vocals', is_flag=True, help='Enable Rock Band 4 freestyle-vocals guide lines (Hard/Expert) by setting HasFreestyleVocals in the PS4 songdta')
@click.option('--freestyle-drums', is_flag=True, help='Create drum freestyle mode: drum track gets only one placeholder note at the start, allowing free drum play throughout the song')
@click.option('--package-con-dir', type=click.Path(exists=True, file_okay=False, dir_okay=True), default=None, help='Package all .con files in this directory into a single PS4 PKG installer (batch packaging mode)')
@click.option('--ps4-pkg-id', type=str, default=None, help='Optional 16-char PS4 Content ID for the PKG (auto-generated from artist+title if omitted)')
def main(audio_file, artist, title, year, genre, lyrics, output_dir, skip_separation, use_ft_stems, ft_shifts, ft_strip_seconds, ft_segment, skip_tempo_detection, skip_vocals, skip_mogg, album_art, build_pkg, build_clone_hero, generate_freestyle_vocals, freestyle_drums, package_con_dir, ps4_pkg_id):
    # Batch packaging mode: package all .con files in a directory into a single PS4 PKG
    if package_con_dir:
        click.echo(f"Batch packaging mode: packaging all .con files in {package_con_dir}")
        from autorb.export.con_packer import build_ps4_pkg_from_con_dir
        pkg_path = build_ps4_pkg_from_con_dir(package_con_dir, ps4_pkg_id)
        click.echo(f"PS4 PKG installer successfully built: {pkg_path}")
        return

    # Pipeline mode requires the core inputs
    missing = [name for name, val in (
        ("AUDIO_FILE", audio_file), ("--artist", artist), ("--title", title),
        ("--year", year), ("--genre", genre), ("--lyrics", lyrics),
    ) if val is None]
    if missing:
        click.echo(f"Error: missing required argument(s) for pipeline mode: {', '.join(missing)}", err=True)
        click.echo("Either supply the audio/metadata arguments, or use --package-con-dir for batch PS4 packaging.", err=True)
        return

    click.echo(f"Starting AutoRB Pipeline for: {artist} - {title}")
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    click.echo(f"Using compute device: {device}")
    
    # Generate PS4 PKG ID
    pkg_id_16 = _generate_ps4_pkg_id(artist, title, ps4_pkg_id)
    if ps4_pkg_id:
        click.echo(f"Using custom PS4 PKG ID: {pkg_id_16}")
    else:
        click.echo(f"Auto-generated PS4 PKG ID: {pkg_id_16}")
    
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
        model_name = "htdemucs_ft" if use_ft_stems else "htdemucs"
        click.echo(f"Using Demucs model: {model_name}" +
                   (" (ft, chunked to bound memory)" if use_ft_stems else ""))
        stems = separate_stems(audio_file, out_path, device=device,
                               model_name=model_name, shifts=ft_shifts,
                               strip_seconds=ft_strip_seconds, segment=ft_segment)

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
        # Pass vocal stem for drumless section fallback
        beat_times, dynamic_bpms = extract_tempo_map(stems["drums"], out_path, stems["vocals"])
        
    click.echo(f"First 5 beat timestamps (seconds): {beat_times[:5]}")
    click.echo(f"First 5 dynamic tempos (BPM): {[f'{bpm:.2f}' for bpm in dynamic_bpms[:5]]}")

    if skip_vocals:
        click.echo("\n[3/5] Skipping vocal extraction. Loading cached data...")
        from autorb.audio.vocals import load_vocals_cache
        try:
            result = load_vocals_cache(out_path)
            # Handle both v1 (3 values) and v2 (4 values) cache formats
            if len(result) == 4:
                lyrics_data, word_segments, vocal_notes, _ = result
            else:
                lyrics_data, word_segments, vocal_notes = result
            click.echo("Successfully loaded vocals data from cache.")
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            return
    else:
        click.echo("\n[3/5] Aligning vocals and parsing LRC...")
        from autorb.audio.vocals import process_vocals
        # Pass out_path so it knows where to save the JSON cache
        result = process_vocals(stems["vocals"], lyrics, out_path)
        if len(result) == 4:
            lyrics_data, word_segments, vocal_notes, _ = result
        else:
            lyrics_data, word_segments, vocal_notes = result
    
    if word_segments:
        first_word = word_segments[0]
        w_text = first_word.get('word', '')
        w_start = first_word.get('start', 0.0)
        w_end = first_word.get('end', 0.0)
        click.echo(f"First aligned word: '{w_text}' (Starts: {w_start:.2f}s, Ends: {w_end:.2f}s)")
    
    if vocal_notes:
        # Basic-Pitch returns note events reverse-chronologically; report the
        # chronologically first note so the log line isn't misleading.
        first_note = min(vocal_notes, key=lambda n: n[0])
        click.echo(f"First vocal note: starts at {first_note[0]:.2f}s, MIDI pitch {first_note[2]}")

    click.echo("\n[4/5] Synchronizing beats and lyrics data...")
    from autorb.audio.step4_sync import run_step_4
    
    beats_json = out_path / "tempo_map.json"
    lyrics_json = out_path / "vocals_cache.json"
    synced_output_json = out_path / "synced_track.json"
    
    try:
        run_step_4(str(beats_json), str(lyrics_json), str(synced_output_json),
                   vocals_stem=stems["vocals"], lrc_path=lyrics)
        click.echo(f"Successfully generated synchronized track data at: {synced_output_json}")
    except Exception as e:
        click.echo(f"Error during step 4 synchronization: {e}", err=True)
        return

    # Transcribe instruments (guitar, bass, drums) for full-band charts
    click.echo("\n[4b/5] Transcribing instrument tracks (guitar, bass, drums)...")
    from autorb.transcribe.instruments import (
        transcribe_guitar,
        transcribe_bass,
        transcribe_drums,
        transcribe_keys,
    )
    from autorb.transcribe.instruments.difficulty import create_all_difficulties

    # tempo.py returns numpy arrays; coerce to plain lists so the transcription
    # helpers (and the song_end check above) don't hit ambiguous numpy truthiness.
    beat_times = list(beat_times) if beat_times is not None else []
    dynamic_bpms = list(dynamic_bpms) if dynamic_bpms is not None else []

    # Song end time for BRE/solo detection. beat_times is a numpy array
    # (tempo.py returns np.array), so test length, not truthiness.
    if 'song_length_ms' in locals() and song_length_ms:
        song_end = song_length_ms / 1000.0
    elif beat_times is not None and len(beat_times) > 0:
        song_end = float(beat_times[-1])
    else:
        song_end = 300.0
    
    click.echo("  Transcribing guitar (from 'other' stem)...")
    try:
        guitar_expert = transcribe_guitar(stems["other"], list(zip(beat_times, dynamic_bpms)), song_end)
        guitar_charts = create_all_difficulties(guitar_expert, "guitar")
        click.echo("  Guitar transcription complete.")
    except Exception as e:
        click.echo(f"  Warning: guitar transcription failed: {e}", err=True)
        guitar_charts = None
    
    click.echo("  Transcribing bass...")
    try:
        bass_expert = transcribe_bass(stems["bass"], list(zip(beat_times, dynamic_bpms)), song_end)
        bass_charts = create_all_difficulties(bass_expert, "bass")
        click.echo("  Bass transcription complete.")
    except Exception as e:
        click.echo(f"  Warning: bass transcription failed: {e}", err=True)
        bass_charts = None
    
    click.echo("  Transcribing drums...")
    try:
        # Use original mixed audio for drum detection (Demucs drum stem fails in quiet intros)
        drum_expert = transcribe_drums(
            stems["drums"], 
            list(zip(beat_times, dynamic_bpms)), 
            song_end, 
            other_stem_path=stems.get("other"),
            mixed_audio_path=Path(audio_file)
        )
        drum_charts = create_all_difficulties(drum_expert, "drums")
        click.echo("  Drum transcription complete.")
    except Exception as e:
        click.echo(f"  Warning: drum transcription failed: {e}", err=True)
        drum_charts = None

    click.echo("  Transcribing keys (from 'other' stem)...")
    try:
        keys_expert = transcribe_keys(stems["other"], list(zip(beat_times, dynamic_bpms)), song_end)
        keys_charts = create_all_difficulties(keys_expert, "keys")
        click.echo("  Keys transcription complete.")
    except Exception as e:
        click.echo(f"  Warning: keys transcription failed: {e}", err=True)
        keys_charts = None

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
        # The count-in is derived purely from the cached beat grid, so it is
        # computed unconditionally. When --skip-mogg reuses an existing MOGG,
        # that cached file was already built WITH this lead-in baked in, so the
        # chart must still be shifted past it (count-in == 0 only when there is
        # no usable beat grid).
        count_in_ticks, count_in_ms = count_in_params(list(beat_times))
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
            guitar_charts=guitar_charts,
            bass_charts=bass_charts,
            drum_charts=drum_charts,
            keys_charts=keys_charts,
            freestyle_drums=freestyle_drums,
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
        from autorb.export.album_art import build_default_album_art
        if album_art is not None:
            click.echo(f"Encoding custom album art from {album_art}...")
            album_art_bytes = keep_texture_from_image(album_art)
        else:
            click.echo("Generating default 'Chris Prime Custom' album art...")
            # Generate at high-res for preview, standard-res for CON
            preview_img = build_default_album_art(1024)
            preview_path = out_path / "album_art_preview.png"
            preview_img.save(preview_path)
            click.echo(f"Album art preview saved: {preview_path}")
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

        # Sync-validation artifacts (no PS4 needed): a count-in-free chart +
        # alignment report + karaoke .srt so lyric/audio sync can be reviewed
        # (and quantitatively validated) on a computer, e.g. paired with
        # preview_mix.wav in VLC/MPV or loaded into Clone Hero.
        source_length_ms = max(0, song_length_ms - count_in_ms)
        val_dir = out_path / "validation"
        val_dir.mkdir(exist_ok=True)
        val_midi = generate_vocal_midi(
            synced_output_json, val_dir, "notes",
            song_length_ms=source_length_ms,
            bpm=avg_bpm,
            beat_times=list(beat_times),
            dynamic_bpms=list(dynamic_bpms),
            count_in_ticks=0,
            count_in_ms=0,
            guitar_charts=guitar_charts,
            bass_charts=bass_charts,
            drum_charts=drum_charts,
            keys_charts=keys_charts,
            freestyle_drums=freestyle_drums,
        )
        from autorb.export.alignment_report import build_lyrics_srt, build_alignment_report
        build_lyrics_srt(synced_output_json, out_path / "lyrics_preview.srt")
        try:
            build_alignment_report(
                synced_output_json, val_midi, stems["vocals"],
                out_path / "alignment_report.json",
                spec_dir=out_path / "alignment_specs",
            )
        except Exception as e:
            click.echo(f"Warning: alignment report failed (pipeline continues): {e}", err=True)

        if build_clone_hero:
            click.echo("\n[6/5] Exporting Clone Hero song folder...")
            from autorb.export.clone_hero import build_clone_hero_song
            ch_folder = build_clone_hero_song(
                output_dir=out_path,
                song_id=song_id,
                title=title,
                artist=artist,
                year=year,
                genre=genre,
                stems_dir=stems_dir,
                synced_json=synced_output_json,
                beat_times=list(beat_times),
                dynamic_bpms=list(dynamic_bpms),
                source_length_ms=source_length_ms,
                avg_bpm=avg_bpm,
                preview_start_ms=50000,
                album_art=out_path / "album_art_preview.png" if album_art is None else album_art,
                guitar_charts=guitar_charts,
                bass_charts=bass_charts,
                drum_charts=drum_charts,
                keys_charts=keys_charts,
                freestyle_drums=freestyle_drums,
            )
            click.echo(f"Clone Hero song exported: {ch_folder}")
            click.echo("Load it in Clone Hero (Songs folder -> Scan Songs) to playtest "
                       "lyric/vocal sync on your computer without a PS4.")

        if build_pkg:
            click.echo("\n[7/5] Building PS4 PKG installer...")
            from autorb.export.con_packer import build_ps4_pkg
            pkg_path = build_ps4_pkg(con_output_path, out_path, pkg_id_16)
            click.echo(f"PS4 PKG installer successfully built: {pkg_path}")

    except Exception as e:

        click.echo(f"Error during asset building or CON packaging: {e}", err=True)
        return

    click.echo(f"\nPipeline complete! All assets ready in: {out_path}")

if __name__ == '__main__':
    main()
