#!/usr/bin/env python

from pathlib import Path
import logging
import struct
import shutil

logger = logging.getLogger(__name__)

RB3_TITLE_ID = 0x45410914  # Rock Band 3 Title ID
CONTENT_TYPE_DLC = 0x00010000
BLOCK_SIZE = 0x1000

def create_stfs_header(display_name: str, total_payload_size: int, file_count: int, title_id: int = RB3_TITLE_ID) -> bytearray:
    """
    Constructs a valid STFS package header structure with correct content sizing,
    file counts, and volume descriptor metadata for Rock Band 3 customs and ForgeTool GUI.
    """
    header = bytearray(0x9400)
    header[0:4] = b"CON "
    header[4:132] = b"\x00" * 128
    
    # Pack content size (Int64) at offset 0x34C
    struct.pack_into(">q", header, 0x34C, total_payload_size)
    
    struct.pack_into(">I", header, 0x344, CONTENT_TYPE_DLC)
    struct.pack_into(">I", header, 0x3EC, CONTENT_TYPE_DLC)
    struct.pack_into(">I", header, 0x360, title_id)
    struct.pack_into(">I", header, 0x410, title_id)
    
    # Volume Descriptor (STFS) starting at offset 0x379
    header[0x379] = 0x24  # Descriptor size
    header[0x37A] = 0x01  # Block separation
    struct.pack_into(">H", header, 0x37B, 1)  # File Table Block Count
    
    # File Table Block Number (3 bytes at 0x37D)
    header[0x37D] = 0x00
    header[0x37E] = 0x00
    header[0x37F] = 0x01
    
    # Total allocated / unallocated blocks estimation
    total_blocks = (total_payload_size + BLOCK_SIZE - 1) // BLOCK_SIZE
    struct.pack_into(">I", header, 0x394, total_blocks)
    struct.pack_into(">I", header, 0x398, 0)
    
    # Data File Count and Combined Size
    struct.pack_into(">I", header, 0x39D, file_count)
    struct.pack_into(">q", header, 0x3A1, total_payload_size)
    
    name_encoded = display_name.encode("utf-16-be")[:0x80]
    header[0x41C:0x41C + len(name_encoded)] = name_encoded
    return header

def package_con(
    output_dir: str | Path,
    song_id: str,
    mogg_path: Path,
    midi_path: Path,
    dta_path: Path
) -> Path:
    """
    Stages song assets into the correct folder hierarchy and generates 
    a direct Xbox 360 STFS CON container compatible with ForgeTool GUI.
    """
    output_path = Path(output_dir)
    songs_root = output_path / "songs"
    song_staging_dir = songs_root / song_id
    song_staging_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Stage songs.dta in both parent and subfolder for full tool and game compatibility
    target_dta_parent = songs_root / "songs.dta"
    target_dta_sub = song_staging_dir / "songs.dta"
    
    if dta_path.resolve() != target_dta_parent.resolve():
        shutil.copy2(dta_path, target_dta_parent)
    shutil.copy2(target_dta_parent, target_dta_sub)

    # 2. Stage .mogg and .mid inside the song subfolder
    target_mogg = song_staging_dir / f"{song_id}.mogg"
    target_mid = song_staging_dir / f"{song_id}.mid"
    
    if mogg_path.resolve() != target_mogg.resolve():
        shutil.copy2(mogg_path, target_mogg)
    if midi_path.resolve() != target_mid.resolve():
        shutil.copy2(midi_path, target_mid)
        
    logger.info(f"Staged clean song folder structure at: {song_staging_dir}")

    # 3. Calculate exact payload size and generate direct STFS CON file
    files_to_pack = [f for f in songs_root.rglob("*") if f.is_file()]
    file_items = []
    total_payload_size = 0
    
    for file_path in files_to_pack:
        content = file_path.read_bytes()
        file_size = len(content)
        padded_size = ((file_size + BLOCK_SIZE - 1) // BLOCK_SIZE) * BLOCK_SIZE
        total_payload_size += padded_size
        file_items.append({
            "size": file_size,
            "content": content
        })

    con_file_path = output_path / f"{song_id}.con"
    header = create_stfs_header(song_id, total_payload_size, len(files_to_pack))

    with open(con_file_path, "wb") as con_file:
        con_file.write(header)
        current_offset = con_file.tell()
        padding_needed = (BLOCK_SIZE - (current_offset % BLOCK_SIZE)) % BLOCK_SIZE
        con_file.write(b"\x00" * padding_needed)

        for item in file_items:
            con_file.write(item["content"])
            remainder = item["size"] % BLOCK_SIZE
            if remainder != 0:
                con_file.write(b"\x00" * (BLOCK_SIZE - remainder))
                
    logger.info(f"Direct CON file successfully packaged: {con_file_path}")
    return con_file_path
    