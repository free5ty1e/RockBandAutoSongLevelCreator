#!/usr/bin/env python

from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def generate_songs_dta(song_id: str, metadata: dict, output_dir: Path) -> Path:
    """
    Generates the Rock Band songs.dta metadata configuration file with 4-stem track mapping
    matching the exact structure, single-quoted keys, double-quoted strings, and CRLF line endings.
    """
    genre = metadata.get('genre', 'rock').lower().replace(' ', '')
    year = metadata.get('year', 1998)
    song_id_num = metadata.get('song_id_num', 61752838)
    title = metadata.get('title', 'Open Road Song')
    artist = metadata.get('artist', 'Eve 6')
    album = metadata.get('album', title)

    dta_lines = [
        f"('{song_id}'",
        "   (",
        "      'name'",
        f'      "{title}"',
        "   )",
        "   (",
        "      'artist'",
        f'      "{artist}"',
        "   )",
        "   ('master' 1)",
        "   (",
        "      'song'",
        "      (",
        "         'name'",
        f'         "songs/{song_id}/{song_id}"',
        "      )",
        "      (",
        "         'tracks_count'",
        "         (2 2 2 2)",
        "      )",
        "      (",
        "         'tracks'",
        "         (",
        "            (",
        "               'drum'",
        "               (0 1)",
        "            )",
        "            (",
        "               'bass'",
        "               (2 3)",
        "            )",
        "            (",
        "               'guitar'",
        "               (4 5)",
        "            )",
        "            (",
        "               'vocals'",
        "               (6 7)",
        "            )",
        "         )",
        "      )",
        "      (",
        "         'pans'",
        "         (-1.00 1.00 -1.00 1.00 -1.00 1.00 -1.00 1.00)",
        "      )",
        "      (",
        "         'vols'",
        "         (0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00)",
        "      )",
        "      (",
        "         'cores'",
        "         (-1 -1 -1 -1 -1 -1 -1 -1)",
        "      )",
        "      ('vocal_parts' 1)",
        "   )",
        "   ('song_scroll_speed' 2300)",
        "   (",
        "      'bank'",
        '      "sfx/tambourine_bank.milo"',
        "   )",
        "   (",
        "      'drum_bank'",
        '      "sfx/kit01_bank.milo"',
        "   )",
        "   ('anim_tempo' 16)",
        "   ('song_length' 230162)",
        "   (",
        "      'preview'",
        "      50000",
        "      80000",
        "   )",
        "   (",
        "      'rank'",
        "      ('drum' 150)",
        "      ('guitar' 150)",
        "      ('bass' 150)",
        "      ('vocals' 150)",
        "      ('keys' 0)",
        "      ('real_keys' 0)",
        "      ('band' 150)",
        "   )",
        f"   ('genre' '{genre}')",
        "   ('vocal_gender' 'male')",
        "   ('version' 30)",
        "   ('format' 10)",
        "   ('album_art' 1)",
        f"   ('year_released' {year})",
        "   ('rating' 1)",
        "   ('sub_genre' 'subgenre_rock')",
        f"   ('song_id' {song_id_num})",
        "   ('tuning_offset_cents' 0)",
        "   ('guide_pitch_volume' -3.00)",
        "   ('game_origin' 'ugc_plus')",
        "   ('encoding' 'latin1')",
        "   (",
        "      'album_name'",
        f'      "{album}"',
        "   )",
        "   ('album_track_number' 1)",
        ")"
    ]

    dta_content = "\r\n".join(dta_lines) + "\r\n"

    song_staging_dir = output_dir / "songs" / song_id
    song_staging_dir.mkdir(parents=True, exist_ok=True)
    
    dta_path = song_staging_dir / "songs.dta"
    dta_path.write_bytes(dta_content.encode('latin1'))
    logger.info(f"Generated songs.dta at {dta_path}")
    return dta_path
