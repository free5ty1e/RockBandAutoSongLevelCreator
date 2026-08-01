#!/usr/bin/env python

from pathlib import Path
import struct
import shutil
import click
import os

RB3_TITLE_ID = 0x45410914  # Rock Band 3 Title ID
CONTENT_TYPE_DLC = 0x00010000
BLOCK_SIZE = 0x1000

def create_stfs_header(display_name: str, total_payload_blocks: int, total_payload_size: int, entry_count: int, title_id: int = RB3_TITLE_ID) -> bytearray:
    header = bytearray(0xC000)
    header[0:4] = b"CON "
    header[4:132] = b"\x00" * 128
    
    struct.pack_into(">q", header, 0x34C, total_payload_size)
    struct.pack_into(">I", header, 0x344, CONTENT_TYPE_DLC)
    struct.pack_into(">I", header, 0x3EC, CONTENT_TYPE_DLC)
    struct.pack_into(">I", header, 0x360, title_id)
    struct.pack_into(">I", header, 0x410, title_id)
    
    header[0x379] = 0x24  # Descriptor size
    header[0x37A] = 0x00  # Reserved/Version
    header[0x37B] = 0x01  # Block separation/Flags
    
    struct.pack_into("<H", header, 0x37C, 1)  # File Table Block Count
    header[0x37E:0x381] = b'\x00\x00\x00'   # File Table Start Block Number
    
    struct.pack_into(">I", header, 0x395, total_payload_blocks)
    struct.pack_into(">I", header, 0x399, 0)
    struct.pack_into(">I", header, 0x39D, entry_count)
    struct.pack_into(">q", header, 0x3A1, total_payload_size)
    
    name_encoded = display_name.encode("utf-16-be")[:0x80]
    header[0x41C:0x41C + len(name_encoded)] = name_encoded
    return header

def create_file_entry(name: str, allocated_blocks: int, real_blocks: int, start_block: int, parent_index: int = 0xFFFF, file_size: int = 0, is_dir: bool = False) -> bytearray:
    entry = bytearray(0x40)
    name_bytes = name.encode('ascii', errors='ignore')[:0x28]
    entry[0:len(name_bytes)] = name_bytes
    
    name_len = len(name_bytes) & 0x3F
    flags = name_len | (0x80 if is_dir else 0x40)
    entry[0x28] = flags
    
    entry[0x29:0x2C] = allocated_blocks.to_bytes(3, 'little', signed=False)
    entry[0x2C:0x2F] = real_blocks.to_bytes(3, 'little', signed=False)
    entry[0x2F:0x32] = start_block.to_bytes(3, 'little', signed=False)
    entry[0x32:0x34] = parent_index.to_bytes(2, 'big', signed=False)
    entry[0x34:0x38] = file_size.to_bytes(4, 'big', signed=False)
    entry[0x38:0x3C] = (0x50212000).to_bytes(4, 'big', signed=False)
    
    return entry

def package_con(
    output_dir: str | Path,
    song_id: str,
    mogg_path: Path,
    midi_path: Path,
    dta_path: Path
) -> Path:
    output_path = Path(output_dir)
    songs_root = output_path / "songs"
    song_staging_dir = songs_root / song_id
    song_staging_dir.mkdir(parents=True, exist_ok=True)
    
    target_dta_parent = songs_root / "songs.dta"
    target_dta_sub = song_staging_dir / "songs.dta"
    
    if dta_path.resolve() != target_dta_parent.resolve():
        shutil.copy2(dta_path, target_dta_parent)
    shutil.copy2(target_dta_parent, target_dta_sub)

    target_mogg = song_staging_dir / f"{song_id}.mogg"
    target_mid = song_staging_dir / f"{song_id}.mid"
    
    if mogg_path.resolve() != target_mogg.resolve():
        shutil.copy2(mogg_path, target_mogg)
    if midi_path.resolve() != target_mid.resolve():
        shutil.copy2(midi_path, target_mid)
        
    click.echo(f"Staged clean song folder structure at: {song_staging_dir}")

    dta_parent_content = target_dta_parent.read_bytes()
    mogg_content = target_mogg.read_bytes()
    midi_content = target_mid.read_bytes()
    dummy_asset = b"MILO_PNG_DUMMY_CONTENT"

    file_table_block = bytearray(b'\xff' * BLOCK_SIZE)

    # Exact 8-entry layout matching SmellsLikeNirvana_rb3con:
    # Index 0: songs (dir, parent 0xFFFF)
    # Index 1: song_id (dir, parent 0)
    # Index 2: gen (dir, parent 1)
    # Index 3: songs.dta (file, parent 0)
    # Index 4: {song_id}.mid (file, parent 1)
    # Index 5: {song_id}.mogg (file, parent 1)
    # Index 6: {song_id}.milo_xbox (file, parent 2)
    # Index 7: {song_id}_keep.png_xbox (file, parent 2)
    items = [
        {"name": "songs", "is_dir": True, "parent": 0xFFFF, "content": None},
        {"name": song_id, "is_dir": True, "parent": 0, "content": None},
        {"name": "gen", "is_dir": True, "parent": 1, "content": None},
        {"name": "songs.dta", "is_dir": False, "parent": 0, "content": dta_parent_content},
        {"name": f"{song_id}.mid", "is_dir": False, "parent": 1, "content": midi_content},
        {"name": f"{song_id}.mogg", "is_dir": False, "parent": 1, "content": mogg_content},
        {"name": f"{song_id}.milo_xbox", "is_dir": False, "parent": 2, "content": dummy_asset},
        {"name": f"{song_id}_keep.png_xbox", "is_dir": False, "parent": 2, "content": dummy_asset},
    ]

    current_block = 0
    packed_files = []
    
    for idx, item in enumerate(items):
        entry_offset = idx * 0x40
        if item["is_dir"]:
            file_table_block[entry_offset:entry_offset + 0x40] = create_file_entry(
                name=item["name"],
                allocated_blocks=0,
                real_blocks=0,
                start_block=0,
                parent_index=item["parent"],
                file_size=0,
                is_dir=True
            )
        else:
            content = item["content"]
            file_size = len(content)
            block_count = (file_size + BLOCK_SIZE - 1) // BLOCK_SIZE
            
            file_table_block[entry_offset:entry_offset + 0x40] = create_file_entry(
                name=item["name"],
                allocated_blocks=block_count,
                real_blocks=block_count,
                start_block=current_block,
                parent_index=item["parent"],
                file_size=file_size,
                is_dir=False
            )
            packed_files.append({
                "content": content,
                "size": file_size,
                "blocks": block_count
            })
            current_block += block_count

    total_payload_blocks = current_block
    total_payload_size = total_payload_blocks * BLOCK_SIZE

    con_file_path = output_path / f"{song_id}.con"
    header = create_stfs_header(song_id, total_payload_blocks, total_payload_size, len(items))

    with open(con_file_path, "wb") as con_file:
        con_file.write(header)
        
        current_offset = con_file.tell()
        padding_needed = (BLOCK_SIZE - (current_offset % BLOCK_SIZE)) % BLOCK_SIZE
        con_file.write(b"\x00" * padding_needed)

        # Write File Table block (Block 12 at 0xC000)
        con_file.write(b"\x00" * (0xC000 - con_file.tell()))
        con_file.write(file_table_block)

        # Write Payload Files starting at 0xD000
        for item in packed_files:
            con_file.write(item["content"])
            remainder = item["size"] % BLOCK_SIZE
            if remainder != 0:
                con_file.write(b"\x00" * (BLOCK_SIZE - remainder))
                
    os.utime(con_file_path, None)
    click.echo(f"Direct CON file successfully packaged with 8-entry SmellsLikeNirvana layout: {con_file_path}")
    return con_file_path
