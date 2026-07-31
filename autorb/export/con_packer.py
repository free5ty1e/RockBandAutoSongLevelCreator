#!/usr/bin/env python

from pathlib import Path
import struct
import shutil
import click

RB3_TITLE_ID = 0x45410914  # Rock Band 3 Title ID
CONTENT_TYPE_DLC = 0x00010000
BLOCK_SIZE = 0x1000

def create_stfs_header(display_name: str, total_payload_blocks: int, total_payload_size: int, entry_count: int, title_id: int = RB3_TITLE_ID) -> bytearray:
    """
    Constructs a valid STFS package header structure with correct content sizing,
    file counts, and volume descriptor metadata for Rock Band 3 customs and ForgeTool GUI.
    """
    header = bytearray(0xA000)
    header[0:4] = b"CON "
    header[4:132] = b"\x00" * 128
    
    # Pack content size (Int64) at offset 0x34C
    struct.pack_into(">q", header, 0x34C, total_payload_size)
    
    struct.pack_into(">I", header, 0x344, CONTENT_TYPE_DLC)
    struct.pack_into(">I", header, 0x3EC, CONTENT_TYPE_DLC)
    struct.pack_into(">I", header, 0x360, title_id)
    struct.pack_into(">I", header, 0x410, title_id)
    
    # Volume Descriptor (STFS) starting at offset 0x379 (Strict Free60 Spec)
    header[0x379] = 0x24  # Descriptor size
    header[0x37A] = 0x00  # Reserved/Version
    header[0x37B] = 0x00  # Block separation/Flags
    
    # File Table Block Count (2 bytes, Little Endian)
    struct.pack_into("<H", header, 0x37C, 1)  
    
    # File Table Start Block Number (3 bytes, Little Endian) -> Block 0
    header[0x37E:0x381] = b'\x00\x00\x00'
    
    # Total Allocated Blocks (4 bytes, Big Endian)
    struct.pack_into(">I", header, 0x395, total_payload_blocks)
    # Total Unallocated Blocks
    struct.pack_into(">I", header, 0x399, 0)
    
    # Data File Count and Combined Size
    struct.pack_into(">I", header, 0x39D, entry_count)
    struct.pack_into(">q", header, 0x3A1, total_payload_size)
    
    name_encoded = display_name.encode("utf-16-be")[:0x80]
    header[0x41C:0x41C + len(name_encoded)] = name_encoded
    return header

def create_file_entry(name: str, allocated_blocks: int, real_blocks: int, start_block: int, parent_index: int = 0xFFFF, file_size: int = 0, is_dir: bool = False) -> bytearray:
    """
    Creates a 64-byte STFS file/directory table entry.
    """
    entry = bytearray(0x40)
    name_bytes = name.encode('ascii', errors='ignore')[:0x28]
    entry[0:len(name_bytes)] = name_bytes
    
    name_len = len(name_bytes) & 0x3F
    
    # Flags: Bit 7 (0x80) = Directory | Bit 6 (0x40) = Contiguous File (Required if no hash blocks)
    flags = name_len | (0x80 if is_dir else 0x40)
    entry[0x28] = flags
    
    entry[0x29:0x2C] = allocated_blocks.to_bytes(3, 'little', signed=False)
    entry[0x2C:0x2F] = real_blocks.to_bytes(3, 'little', signed=False)
    entry[0x2F:0x32] = start_block.to_bytes(3, 'little', signed=False)
    
    # Parent directory index (Big Endian, unsigned 16-bit, 0xFFFF for root)
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
    """
    Stages song assets and generates a flattened Xbox 360 STFS CON container 
    compatible with ForgeTool GUI.
    """
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
    dta_sub_content = target_dta_sub.read_bytes()
    mogg_content = target_mogg.read_bytes()
    midi_content = target_mid.read_bytes()

    # Flattened table layout:
    # Index 0: Song folder directory (parent: 0xFFFF root)
    # Index 1: songs.dta at root (parent: 0xFFFF root)
    # Index 2: songs.dta inside song folder (parent: 0)
    # Index 3: .mogg inside song folder (parent: 0)
    # Index 4: .mid inside song folder (parent: 0)
    items = [
        {"name": "songs.dta", "parent": 0xFFFF, "content": dta_parent_content},
        {"name": "songs.dta", "parent": 0, "content": dta_sub_content},
        {"name": f"{song_id}.mogg", "parent": 0, "content": mogg_content},
        {"name": f"{song_id}.mid", "parent": 0, "content": midi_content},
    ]

    current_block = 1
    file_table_block = bytearray(BLOCK_SIZE)
    
    # Pre-fill all 64 potential file table entries with 0xFFFF (Root) for parent index safety
    for i in range(64):
        file_table_block[i * 0x40 + 0x32 : i * 0x40 + 0x34] = b'\xff\xff'
    
    # Index 0: Song Subfolder Directory (Parent is 0xFFFF Root)
    file_table_block[0x00:0x40] = create_file_entry(song_id, 0, 0, 0, parent_index=0xFFFF, file_size=0, is_dir=True)

    packed_files = []
    for idx, item in enumerate(items):
        content = item["content"]
        file_size = len(content)
        block_count = (file_size + BLOCK_SIZE - 1) // BLOCK_SIZE
        
        # Files start at index 1 (offset 0x40)
        entry_offset = (1 + idx) * 0x40
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
    # Entry count is len(items) + 1 directory entry
    header = create_stfs_header(song_id, total_payload_blocks, total_payload_size, len(items) + 1)

    with open(con_file_path, "wb") as con_file:
        con_file.write(header)
        
        current_offset = con_file.tell()
        padding_needed = (BLOCK_SIZE - (current_offset % BLOCK_SIZE)) % BLOCK_SIZE
        con_file.write(b"\x00" * padding_needed)

        # Write File Table block (Block 0)
        con_file.write(file_table_block)

        # Write Payload Files
        for item in packed_files:
            con_file.write(item["content"])
            remainder = item["size"] % BLOCK_SIZE
            if remainder != 0:
                con_file.write(b"\x00" * (BLOCK_SIZE - remainder))
                
    click.echo(f"Direct CON file successfully packaged with flattened STFS file table: {con_file_path}")
    return con_file_path
