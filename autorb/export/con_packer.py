#!/usr/bin/env python

from pathlib import Path
import logging
import struct
import shutil

logger = logging.getLogger(__name__)

RB3_TITLE_ID = 0x4D53085B
CONTENT_TYPE_DLC = 0x00010000

def build_stfs_header(content_size: int, title_id: int) -> bytes:
    header = bytearray(0xA000)
    header[0:4] = b"CON "
    struct.pack_into(">I", header, 0x340, 0x244)
    struct.pack_into(">I", header, 0x344, CONTENT_TYPE_DLC)
    struct.pack_into(">q", header, 0x34C, content_size)
    struct.pack_into(">I", header, 0x360, title_id)
    header[0x364] = 0x02
    return bytes(header)

def package_con(
    output_dir: str | Path,
    song_id: str,
    mogg_path: Path,
    midi_path: Path,
    dta_path: Path
) -> Path:
    output_path = Path(output_dir)
    song_staging_dir = output_path / "songs" / song_id
    
    # Move/Copy audio and midi into the song staging folder alongside songs.dta
    shutil.copy2(mogg_path, song_staging_dir / f"{song_id}.mogg")
    shutil.copy2(midi_path, song_staging_dir / f"{song_id}.mid")
    
    files_to_pack = [f for f in song_staging_dir.glob("*") if f.is_file()]
    total_payload_size = sum(f.stat().st_size for f in files_to_pack)
    
    con_file_path = output_path / f"{song_id}.con"
    stfs_header = build_stfs_header(total_payload_size, RB3_TITLE_ID)
    
    with open(con_file_path, "wb") as con_file:
        con_file.write(stfs_header)
        for file_path in files_to_pack:
            with open(file_path, "rb") as f:
                shutil.copyfileobj(f, con_file)
                
    logger.info(f"CON file successfully packaged: {con_file_path}")
    return con_file_path
