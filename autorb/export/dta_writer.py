#!/usr/bin/env python

from pathlib import Path
import logging

from autorb.export.difficulty import compute_ranks
from autorb.export.mogg_builder import read_mogg_duration_ms

logger = logging.getLogger(__name__)

def generate_songs_dta(song_id: str, metadata: dict, output_dir: Path, song_length: int | None = None,
                       ranks: dict | None = None, vocal_tonic_note: int = 4,
                       song_tonality: int = 0, freestyle_vocals: bool = False) -> Path:
    """
    Generates the Rock Band songs.dta metadata configuration file in standard concise single-line property format.
    """
    genre = metadata.get('genre', 'alternative').lower().replace(' ', '')
    year = metadata.get('year', 1998)
    song_id_num = metadata.get('song_id_num', 86876552)
    title = metadata.get('title', 'Open Road Song')
    artist = metadata.get('artist', 'Eve 6')
    album = metadata.get('album', title)

    if song_length is None:
        mogg_path = output_dir / f"{song_id}.mogg"
        if mogg_path.exists():
            song_length = read_mogg_duration_ms(mogg_path)
        else:
            logger.warning("MOGG not found; defaulting song_length to 198089 ms.")
            song_length = 198089

    if ranks is None:
        midi_path = output_dir / f"{song_id}.mid"
        if midi_path.exists():
            ranks = compute_ranks(midi_path, song_length)
        else:
            logger.warning("MIDI not found; defaulting all ranks to 100.")
            ranks = {"drum": 100, "guitar": 100, "bass": 100, "vocals": 100,
                     "keys": 0, "real_guitar": 0, "real_bass": 0, "real_keys": 0, "band": 100}
    else:
        ranks = {k: int(ranks.get(k, 0)) for k in
                 ("drum", "guitar", "bass", "vocals", "keys", "real_guitar", "real_bass", "real_keys", "band")}

    preview_start = max(0, int(song_length * 0.25))
    preview_end = min(song_length, preview_start + 30000)
    dta_lines = [
        f"({song_id}",
        f'   (name "{title}")',
        f'   (artist "{artist}")',
        "   (master TRUE)",
        f'   (song_id {song_id_num})',
        "   (song",
        f'      (name "songs/{song_id}/{song_id}")',
        "      (tracks",
        "         ((drum (0 1 2 3))",
        "          (bass (4))",
        "          (guitar (5 6))",
        "          (vocals (7 8))",
        "         )",
        "      )",
        "      (vocal_parts 1)",
        "      (pans (0.0 0.0 -1.0 1.0 0.0 -1.0 1.0 -1.0 1.0 0.0))",
        "      (vols (-0.5 -0.1 -2.1 -2.1 -3.1 -2.0 -2.0 -3.0 -3.0 -3.1))",
        "      (cores (-1 -1 -1 -1 -1 1 1 -1 -1 -1))",
        "      (drum_solo",
        "         (seqs (kick.cue snare.cue tom1.cue tom2.cue crash.cue))",
        "      )",
        "      (drum_freestyle",
        "         (seqs (kick.cue snare.cue hat.cue ride.cue crash.cue))",
        "      )",
        "   )",
        "   (bank sfx/tambourine_bank.milo)",
        "   (drum_bank sfx/kit01_bank.milo)",
        "   (anim_tempo kTempoSlow)",
        "   (band_fail_cue band_fail_heavy.cue)",
        "   (song_scroll_speed 2300)",
        f"   (preview {preview_start} {preview_end})",
        f"   (song_length {song_length})",
        "   (solo (vocal_percussion))",
        "   (rank",
        f"      (drum {ranks['drum']})",
        f"      (guitar {ranks['guitar']})",
        f"      (bass {ranks['bass']})",
        f"      (vocals {ranks['vocals']})",
        f"      (keys {ranks['keys']})",
        f"      (real_guitar {ranks['real_guitar']})",
        f"      (real_bass {ranks['real_bass']})",
        f"      (real_keys {ranks['real_keys']})",
        f"      (band {ranks['band']})",
        "   )",
        "   (format 10)",
        "   (version 30)",
        "   (game_origin rb3_dlc)",
        "   (short_version 0)",
        "   (rating 1)",
        f"   (genre {genre})",
        "   (vocal_gender male)",
        f"   (year_released {year})",
        "   (album_art TRUE)",
        f'   (album_name "{album}")',
        "   (album_track_number 1)",
        f"   (vocal_tonic_note {vocal_tonic_note})",
        f"   (song_tonality {song_tonality})",
        ")",
    ]
    if freestyle_vocals:
        dta_lines.insert(-1, "   (freestyle_vocals 1)")

    dta_content = "\r\n".join(dta_lines) + "\r\n"

    song_staging_dir = output_dir / "songs" / song_id
    song_staging_dir.mkdir(parents=True, exist_ok=True)
    
    target_dta_parent = output_dir / "songs" / "songs.dta"
    target_dta_parent.parent.mkdir(parents=True, exist_ok=True)

    dta_path = song_staging_dir / "songs.dta"
    dta_path.write_bytes(dta_content.encode('latin1'))
    target_dta_parent.write_bytes(dta_content.encode('latin1'))
    
    logger.info(f"Generated songs.dta at {dta_path}")
    return dta_path
