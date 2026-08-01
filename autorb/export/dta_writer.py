#!/usr/bin/env python

from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def generate_songs_dta(song_id: str, metadata: dict, output_dir: Path) -> Path:
    """
    Generates the Rock Band songs.dta metadata configuration file in exact C3/Magma single-quoted format.
    """
    genre = metadata.get('genre', 'rock').lower().replace(' ', '')
    year = metadata.get('year', 1998)
    song_id_num = metadata.get('song_id_num', 61752838)
    title = metadata.get('title', 'Open Road Song')
    artist = metadata.get('artist', 'Eve 6')
    album = metadata.get('album', title)

    dta_content = f"""('{song_id}'
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
         (2 2 2 2 0 2)
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
         (-1.0 1.0 -1.0 1.0 -1.0 1.0 -1.0 1.0)
      )
      (
         'vols'
         (0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0)
      )
      (
         'cores'
         (-1 -1 -1 -1 -1 -1 -1 -1)
      )
      ('vocal_parts' 1)
      (
         'midi_file'
         "songs/{song_id}/{song_id}.mid"
      )
   )
   (
      'bank'
      "sfx/tambourine_bank.milo"
   )
   ('anim_tempo' 16)
   (
      'preview'
      30000
      60000
   )
   ('genre' '{genre}')
   ('year_released' {year})
   (
      'album_name'
      "{album}"
   )
   ('album_track_number' 1)
   (
      'rank'
      ('drum' 150)
      ('guitar' 150)
      ('bass' 150)
      ('vocals' 150)
      ('keys' 0)
      ('real_keys' 0)
      ('band' 150)
   )
   ('vocal_gender' 'male')
   ('version' 30)
   ('format' 10)
   ('album_art' 1)
   ('rating' 1)
   ('song_id' {song_id_num})
)
"""
    song_staging_dir = output_dir / "songs" / song_id
    song_staging_dir.mkdir(parents=True, exist_ok=True)
    
    dta_path = song_staging_dir / "songs.dta"
    dta_path.write_text(dta_content, encoding="utf-8")
    logger.info(f"Generated songs.dta at {dta_path}")
    return dta_path
