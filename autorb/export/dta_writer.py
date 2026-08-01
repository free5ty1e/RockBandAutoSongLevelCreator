#!/usr/bin/env python

from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def generate_songs_dta(song_id: str, metadata: dict, output_dir: Path) -> Path:
    """
    Generates the Rock Band songs.dta metadata configuration file in C3/Magma format.
    """
    genre = metadata.get('genre', 'rock').lower().replace(' ', '')
    year = metadata.get('year', 1998)
    song_id_num = metadata.get('song_id_num', 1645500028)
    title = metadata.get('title', 'Open Road Song')
    artist = metadata.get('artist', 'Eve 6')
    album = metadata.get('album', title)

    dta_content = f"""(
   '{song_id}'
   (
      'name'
      "{title}"
   )
   (
      'artist'
      "{artist}"
   )
   ('master' 1)
   (
      'song'
      (
         'name'
         "songs/{song_id}/{song_id}"
      )
      (
         'tracks_count'
         (2 2 2 2)
      )
      (
         'tracks'
         (
            (
               'drum'
               (0 1)
            )
            (
               'bass'
               (2 3)
            )
            (
               'guitar'
               (4 5)
            )
            (
               'vocals'
               (6 7)
            )
         )
      )
      (
         'pans'
         (-1.00 1.00 -1.00 1.00 -1.00 1.00 -1.00 1.00)
      )
      (
         'vols'
         (0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00)
      )
      (
         'cores'
         (-1 -1 -1 -1 -1 -1 -1 -1)
      )
   )
   (
      'bank'
      "sfx/tambourine_bank.milo"
   )
   ('anim_tempo' 32)
   (
      'preview'
      30000 60000
   )
   (
      'rank'
      ('drum' 150)
      ('guitar' 150)
      ('bass' 150)
      ('vocals' 150)
      ('band' 150)
   )
   ('genre' '{genre}')
   ('version' 30)
   ('format' 10)
   ('album_art' 1)
   ('year_released' {year})
   ('rating' 1)
   ('song_id' {song_id_num})
   (
      'album_name'
      "{album}"
   )
   ('album_track_number' 1)
)
"""
    song_staging_dir = output_dir / "songs" / song_id
    song_staging_dir.mkdir(parents=True, exist_ok=True)
    
    dta_path = song_staging_dir / "songs.dta"
    dta_path.write_text(dta_content, encoding="utf-8")
    logger.info(f"Generated songs.dta at {dta_path}")
    return dta_path
