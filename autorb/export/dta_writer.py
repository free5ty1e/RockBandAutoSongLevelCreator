#!/usr/bin/env python

from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def generate_songs_dta(song_id: str, metadata: dict, output_dir: Path) -> Path:
    """
    Generates the Rock Band songs.dta metadata configuration file.
    """
    dta_content = f"""({song_id}
   (name "{metadata.get('title', 'Custom Vocals Song')}")
   (artist "{metadata.get('artist', 'Unknown Artist')}")
   (master TRUE)
   (song_id {metadata.get('song_id_num', 98765432)})
   (song
      (name "songs/{song_id}/{song_id}")
      (tracks
         ((vocals (0 1))
         )
      )
      (pans (-1.0 1.0))
      (vols (0.0 0.0))
      (cores (-1 -1))
      (midi_file "songs/{song_id}/{song_id}.mid")
   )
   (bank sfx/tambourine_bank.milo)
   (anim_tempo 16)
   (preview 30000 60000)
   (genre pop)
   (year 2026)
   (album_name "{metadata.get('album', 'Custom Vocals Album')}")
   (album_track_number 1)
   (rank
      (vocals 150)
   )
)
"""
    song_staging_dir = output_dir / "songs" / song_id
    song_staging_dir.mkdir(parents=True, exist_ok=True)
    
    dta_path = song_staging_dir / "songs.dta"
    dta_path.write_text(dta_content, encoding="utf-8")
    logger.info(f"Generated songs.dta at {dta_path}")
    return dta_path
