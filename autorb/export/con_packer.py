#!/usr/bin/env python

from pathlib import Path
import shutil
import click
import os

BLOCK_SIZE = 0x1000

# STFS CON data block addressing.  Readers interpret file-table entry "start"
# as a *logical* block number whose physical location is:
#     physical_offset = 0xC000 + logical_to_physical(logical) * 0x1000
# Block 0 (physical 0x0, i.e. offset 0xC000) is the file table itself, so data
# files must be allocated starting at logical block 1.  Hash tables are
# interleaved every 0xAA logical blocks (plus higher-level tables), which is
# why the physical mapping is not 1:1.
#
# This is the arkem/free60 "fix block numbers" formula with table_size_shift=0
# (block separation & 1 == 1, which is the case for all reference CONs here).
def logical_to_physical(logical: int) -> int:
    block_adjust = 0
    if logical >= 0xAA:
        block_adjust += (logical // 0xAA) + 1
    if logical >= 0x70E4:
        block_adjust += (logical // 0x70E4) + 1
    if logical >= 0x4AF768:
        block_adjust += (logical // 0x4AF768) + 1
    return logical + block_adjust

def set_entry_name(con_data: bytearray, ft_offset: int, entry_idx: int, new_name: str):
    entry_addr = ft_offset + entry_idx * 0x40
    entry_bytes = con_data[entry_addr : entry_addr + 0x40]
    
    flags = entry_bytes[0x28]
    is_dir = bool(flags & 0x80)
    
    name_bytes = new_name.encode('ascii', errors='ignore')[:0x28]
    con_data[entry_addr : entry_addr + 0x28] = b'\x00' * 0x28
    con_data[entry_addr : entry_addr + len(name_bytes)] = name_bytes
    
    name_len = len(name_bytes) & 0x3F
    new_flags = name_len | (0x80 if is_dir else 0x40)
    con_data[entry_addr + 0x28] = new_flags

def set_entry_allocation(con_data: bytearray, ft_offset: int, entry_idx: int, start_block: int, size: int):
    entry_addr = ft_offset + entry_idx * 0x40
    block_count = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
    
    # Size (big endian 4 bytes at 0x34)
    con_data[entry_addr + 0x34 : entry_addr + 0x38] = size.to_bytes(4, 'big')
    # Allocated blocks (little endian 3 bytes at 0x29)
    con_data[entry_addr + 0x29 : entry_addr + 0x2C] = block_count.to_bytes(3, 'little')
    # Real blocks (little endian 3 bytes at 0x2C)
    con_data[entry_addr + 0x2C : entry_addr + 0x2F] = block_count.to_bytes(3, 'little')
    # Start block (little endian 3 bytes at 0x2F)
    con_data[entry_addr + 0x2F : entry_addr + 0x32] = start_block.to_bytes(3, 'little')

def patch_stfs_header_metadata(con_data: bytearray, title: str, artist: str):
    title_encoded = title.encode('utf-16-be')
    con_data[0x43D : 0x43D + len(title_encoded)] = title_encoded
    
    artist_encoded = artist.encode('utf-16-be')
    con_data[0x413 : 0x413 + len(artist_encoded)] = artist_encoded

def package_con(
    output_dir: str | Path,
    song_id: str,
    mogg_path: Path,
    midi_path: Path,
    dta_path: Path,
    title: str = "Open Road Song",
    artist: str = "Eve 6"
) -> Path:
    output_path = Path(output_dir)
    songs_root = output_path / "songs"
    song_staging_dir = songs_root / song_id
    gen_staging_dir = song_staging_dir / "gen"
    gen_staging_dir.mkdir(parents=True, exist_ok=True)
    
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

    template_con = Path("output/known_good_cons/SmellsLikeNirvana_rb3con")
    con_file_path = output_path / f"{song_id}.con"
    
    if template_con.exists():
        shutil.copy2(template_con, con_file_path)
        click.echo(f"Cloned signed template CON from {template_con}")
    else:
        raise FileNotFoundError(f"Template CON not found at {template_con}")

    template_data = template_con.read_bytes()
    ft_offset = 0xC000
    if not (b'songs' in template_data[0xC000:0xC000+0x40]):
        if b'songs' in template_data[0xA000:0xA000+0x40]:
            ft_offset = 0xA000

    # Extract milo and png from template if not present
    target_milo = gen_staging_dir / f"{song_id}.milo_xbox"
    target_png = gen_staging_dir / f"{song_id}_keep.png_xbox"

    entry6 = template_data[ft_offset + 6*0x40 : ft_offset + 7*0x40]
    start6 = int.from_bytes(entry6[0x2F:0x32], 'little')
    size6 = int.from_bytes(entry6[0x34:0x38], 'big')
    milo_offset = 0xC000 + logical_to_physical(start6) * BLOCK_SIZE
    milo_bytes = template_data[milo_offset : milo_offset + size6]
    target_milo.write_bytes(milo_bytes)

    entry7 = template_data[ft_offset + 7*0x40 : ft_offset + 8*0x40]
    start7 = int.from_bytes(entry7[0x2F:0x32], 'little')
    size7 = int.from_bytes(entry7[0x34:0x38], 'big')
    png_offset = 0xC000 + logical_to_physical(start7) * BLOCK_SIZE
    png_bytes = template_data[png_offset : png_offset + size7]
    target_png.write_bytes(png_bytes)
    click.echo("Extracted and staged valid .milo_xbox and .png_xbox assets from template.")

    click.echo(f"Staged clean song folder structure at: {song_staging_dir}")

    con_data = bytearray(con_file_path.read_bytes())

    patch_stfs_header_metadata(con_data, title, artist)

    dta_content = target_dta_parent.read_bytes()
    midi_content = target_mid.read_bytes()
    mogg_content = target_mogg.read_bytes()
    milo_content = target_milo.read_bytes()
    png_content = target_png.read_bytes()

    # Update file table entry names
    set_entry_name(con_data, ft_offset, 1, song_id)
    set_entry_name(con_data, ft_offset, 4, f"{song_id}.mid")
    set_entry_name(con_data, ft_offset, 5, f"{song_id}.mogg")
    set_entry_name(con_data, ft_offset, 6, f"{song_id}.milo_xbox")
    set_entry_name(con_data, ft_offset, 7, f"{song_id}_keep.png_xbox")

    # Calculate contiguous logical block allocations for all 5 files.
    # Logical block 0 is the file table, so data starts at block 1.
    dta_size = len(dta_content)
    dta_blocks = (dta_size + BLOCK_SIZE - 1) // BLOCK_SIZE

    mid_size = len(midi_content)
    mid_blocks = (mid_size + BLOCK_SIZE - 1) // BLOCK_SIZE

    mogg_size = len(mogg_content)
    mogg_blocks = (mogg_size + BLOCK_SIZE - 1) // BLOCK_SIZE

    milo_size = len(milo_content)
    milo_blocks = (milo_size + BLOCK_SIZE - 1) // BLOCK_SIZE

    png_size = len(png_content)
    png_blocks = (png_size + BLOCK_SIZE - 1) // BLOCK_SIZE

    dta_start = 1
    mid_start = dta_start + dta_blocks
    mogg_start = mid_start + mid_blocks
    milo_start = mogg_start + mogg_blocks
    png_start = milo_start + milo_blocks

    # Update file table entries 3, 4, 5, 6, 7
    set_entry_allocation(con_data, ft_offset, 3, dta_start, dta_size)
    set_entry_allocation(con_data, ft_offset, 4, mid_start, mid_size)
    set_entry_allocation(con_data, ft_offset, 5, mogg_start, mogg_size)
    set_entry_allocation(con_data, ft_offset, 6, milo_start, milo_size)
    set_entry_allocation(con_data, ft_offset, 7, png_start, png_size)

    # Total Allocated Block Count (be32 at 0x395) = file table (1) + data blocks.
    total_allocated = 1 + dta_blocks + mid_blocks + mogg_blocks + milo_blocks + png_blocks
    con_data[0x395 : 0x399] = total_allocated.to_bytes(4, 'big')
    con_data[0x399 : 0x39D] = (0).to_bytes(4, 'big')

    # Helper to write payload at the physical offset readers resolve from the
    # logical start block (hash tables are interleaved every 0xAA logical blocks).
    def write_payload(start_block: int, content: bytes):
        payload_offset = 0xC000 + logical_to_physical(start_block) * BLOCK_SIZE
        size = len(content)
        block_count = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
        total_space = block_count * BLOCK_SIZE
        end = payload_offset + total_space
        if len(con_data) < end:
            con_data.extend(b'\x00' * (end - len(con_data)))
        con_data[payload_offset : end] = b'\x00' * total_space
        con_data[payload_offset : payload_offset + size] = content

    write_payload(dta_start, dta_content)
    write_payload(mid_start, midi_content)
    write_payload(mogg_start, mogg_content)
    write_payload(milo_start, milo_content)
    write_payload(png_start, png_content)

    con_file_path.write_bytes(con_data)
    os.utime(con_file_path, None)
    click.echo(f"Successfully patched signed template CON with fully contiguous block allocation for all assets: {con_file_path}")
    return con_file_path
