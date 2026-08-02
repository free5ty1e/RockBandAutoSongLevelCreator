#!/usr/bin/env python

from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def generate_songs_dta(song_id: str, metadata: dict, output_dir: Path) -> Path:
    """
    Generates the Rock Band songs.dta metadata configuration file in standard concise single-line property format.
    """
    genre = metadata.get('genre', 'alternative').lower().replace(' ', '')
    year = metadata.get('year', 1998)
    song_id_num = metadata.get('song_id_num', 86876552)
    title = metadata.get('title', 'Open Road Song')
    artist = metadata.get('artist', 'Eve 6')
    album = metadata.get('album', title)

    dta_lines = [
        f"({song_id}",
        f'   (name "{title}")',
        f'   (artist "{artist}")',
        "   (master TRUE)",
        f'   (song_id {song_id_num})',
        "   (song",
        f'      (name "songs/{song_id}/{song_id}")',
        "      (tracks",
        "         ((drum (0 1))",
        "          (bass (2 3))",
        "          (guitar (4 5))",
        "          (vocals (6 7))",
        "         )",
        "      )",
        "      (vocal_parts 1)",
        "      (pans (-1.0 1.0 -1.0 1.0 -1.0 1.0 -1.0 1.0))",
        "      (vols (0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0))",
        "      (cores (-1 -1 -1 -1 -1 -1 -1 -1))",
        "   )",
        "   (bank sfx/tambourine_bank.milo)",
        "   (drum_bank sfx/kit01_bank.milo)",
        "   (anim_tempo kTempoSlow)",
        "   (song_scroll_speed 2300)",
        "   (preview 50000 80000)",
        "   (song_length 230162)",
        "   (rank",
        "      (drum 150)",
        "      (guitar 150)",
        "      (bass 150)",
        "      (vocals 150)",
        "      (keys 0)",
        "      (real_keys 0)",
        "      (band 150)",
        "   )",
        f"   (genre {genre})",
        "   (vocal_gender male)",
        "   (version 30)",
        "   (format 10)",
        "   (game_origin rb3_dlc)",
        "   (rating 1)",
        "   (sub_genre subgenre_rock)",
        "   (tuning_offset_cents 0)",
        "   (guide_pitch_volume -3.00)",
        "   (encoding latin1)",
        f'   (album_name "{album}")',
        "   (album_track_number 1)",
        f'   (year_released {year})',
        "   (album_art TRUE)",
        ")"
    ]

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
