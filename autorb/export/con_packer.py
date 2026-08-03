#!/usr/bin/env python
from pathlib import Path
import shutil
import click
import os
import struct
import subprocess

BLOCK_SIZE = 0x1000

# LibForge (ForgeTool) MiloFile constants.  MILO_A = uncompressed block layout.
MILO_A_MAGIC = 0xCABEDEAF
MILO_D_MAGIC = 0xCDBEDEAF
ADDE_PADDING = b'\xad\xde\xad\xde'

def repair_milo(milo_bytes: bytes) -> bytes:
    """Ensure a MILO_A (uncompressed) milo is parseable by LibForge."""
    magic = int.from_bytes(milo_bytes[0:4], 'little')
    if magic != MILO_A_MAGIC:
        return milo_bytes
    offset = int.from_bytes(milo_bytes[4:8], 'little')
    block_count = int.from_bytes(milo_bytes[8:12], 'little')
    if block_count == 0:
        return milo_bytes
    total_size = 0
    for i in range(block_count):
        total_size += int.from_bytes(milo_bytes[0x10 + i * 4: 0x14 + i * 4], 'little')
    data_region = milo_bytes[offset: offset + total_size]
    if len(data_region) >= 4 and data_region[-4:] == ADDE_PADDING:
        return milo_bytes
    out = bytearray(milo_bytes)
    last_field = 0x10 + (block_count - 1) * 4
    cur = int.from_bytes(milo_bytes[last_field:last_field + 4], 'little')
    out[last_field:last_field + 4] = (cur + 4).to_bytes(4, 'little')
    out.extend(ADDE_PADDING)
    return bytes(out)

def _libforge_milo_parseable(milo_bytes: bytes) -> bool:
    """Replicate LibForge 0.1.19 MiloFile.ReadFromStream -> ParseDirectory ->
    CharLipSync.FromStream and return True if every ObjectDir entry terminates
    with a 0xADDEADDE marker."""
    import struct
    def read_u32be(buf, p):
        return struct.unpack('>I', buf[p:p + 4])[0]
    def read_str(buf, p):
        length = read_u32be(buf, p)
        return buf[p + 4: p + 4 + length].decode('utf-8', 'replace'), p + 4 + length
    def find_next(buf, p):
        start = p
        magic = 0
        while p < len(buf):
            magic = ((magic << 8) | buf[p]) & 0xFFFFFFFF
            p += 1
            if magic == 0xADDEADDE:
                return (p - 4) - start
        return -1
    if int.from_bytes(milo_bytes[0:4], 'little') != MILO_A_MAGIC:
        return False
    offset = int.from_bytes(milo_bytes[4:8], 'little')
    block_count = int.from_bytes(milo_bytes[8:12], 'little')
    total_size = 0
    for i in range(block_count):
        total_size += int.from_bytes(milo_bytes[0x10 + i * 4: 0x14 + i * 4], 'little')
    if offset + total_size > len(milo_bytes):
        return False
    buf = milo_bytes[offset: offset + total_size]
    p = 0
    version = read_u32be(buf, p); p += 4
    if version not in (25, 28):
        return False
    _, p = read_str(buf, p)
    _, p = read_str(buf, p)
    p += 8
    count = read_u32be(buf, p); p += 4
    if count > 64:
        return False
    for _ in range(count):
        _, p = read_str(buf, p)
        _, p = read_str(buf, p)
    start = p
    if find_next(buf, p) < 0:
        return False
    p += find_next(buf, p) + 4
    for _ in range(count):
        if find_next(buf, p) < 0:
            return False
        p += find_next(buf, p) + 4
    return True

def logical_to_physical(logical: int) -> int:
    block_adjust = 0
    if logical >= 0xAA:
        block_adjust += (logical // 0xAA) + 1
    if logical >= 0x70E4:
        block_adjust += (logical // 0x70E4) + 1
    if logical >= 0x4AF768:
        block_adjust += (logical // 0x4AF768) + 1
    return logical + block_adjust

def read_file_blocks(con_data: bytes, start_logical: int, size: int) -> bytes:
    """Read a file from a CON by resolving EVERY logical block through the
    interleave (hash-table blocks sit between groups of 0xAA logical blocks, so
    the physical layout is NOT contiguous)."""
    block_count = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
    out = bytearray()
    for i in range(block_count):
        offset = 0xC000 + logical_to_physical(start_logical + i) * BLOCK_SIZE
        out += con_data[offset: offset + BLOCK_SIZE]
    return bytes(out[:size])

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
    artist: str = "Eve 6",
    album_art_bytes: bytes | None = None
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

    template_con = Path(__file__).parent / "data/template.con"
    con_file_path = output_path / f"{song_id}.con"
    
    if not template_con.exists() or template_con.stat().st_size < 0x1000:
        raise FileNotFoundError(f"Valid Template CON not found at {template_con} (size: {template_con.stat().st_size if template_con.exists() else 'N/A'})")

    shutil.copy2(template_con, con_file_path)
    click.echo(f"Cloned signed template CON from {template_con}")

    template_data = template_con.read_bytes()
    ft_offset = 0xC000
    if not (b'songs' in template_data[0xC000:0xC000+0x40]):
        if b'songs' in template_data[0xA000:0xA000+0x40]:
            ft_offset = 0xA000

    target_milo = gen_staging_dir / f"{song_id}.milo_xbox"
    target_png = gen_staging_dir / f"{song_id}_keep.png_xbox"

    entry6 = template_data[ft_offset + 6*0x40 : ft_offset + 7*0x40]
    start6 = int.from_bytes(entry6[0x2F:0x32], 'little')
    size6 = int.from_bytes(entry6[0x34:0x38], 'big')
    milo_bytes = read_file_blocks(template_data, start6, size6)
    repaired = repair_milo(milo_bytes)
    if len(repaired) != len(milo_bytes):
        click.echo("Patched template milo: appended missing 0xADDEADDE terminator for LibForge compat.")
    if not _libforge_milo_parseable(repaired):
        click.echo(
            "WARNING: Staged milo might not be fully parseable by LibForge. "
            "PKG conversion may fail if the MiloFile cannot be processed.",
            err=True
        )
    target_milo.write_bytes(repaired)

    entry7 = template_data[ft_offset + 7*0x40 : ft_offset + 8*0x40]
    start7 = int.from_bytes(entry7[0x2F:0x32], 'little')
    size7 = int.from_bytes(entry7[0x34:0x38], 'big')
    png_bytes = read_file_blocks(template_data, start7, size7)
    if album_art_bytes is not None:
        if not album_art_bytes.startswith(b"\x01"):
            raise ValueError("album_art_bytes must be a Rock Band _keep.png_xbox texture")
        png_bytes = album_art_bytes
        click.echo("Using custom album art texture.")
    target_png.write_bytes(png_bytes)
    click.echo("Extracted and staged valid .milo_xbox and .png_xbox assets from template.")

    con_data = bytearray(con_file_path.read_bytes())
    patch_stfs_header_metadata(con_data, title, artist)
    dta_content = target_dta_parent.read_bytes()
    midi_content = target_mid.read_bytes()
    mogg_content = target_mogg.read_bytes()
    milo_content = target_milo.read_bytes()
    png_content = target_png.read_bytes()

    set_entry_name(con_data, ft_offset, 1, song_id)
    set_entry_name(con_data, ft_offset, 4, f"{song_id}.mid")
    set_entry_name(con_data, ft_offset, 5, f"{song_id}.mogg")
    set_entry_name(con_data, ft_offset, 6, f"{song_id}.milo_xbox")
    set_entry_name(con_data, ft_offset, 7, f"{song_id}_keep.png_xbox")

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

    set_entry_allocation(con_data, ft_offset, 3, dta_start, dta_size)
    set_entry_allocation(con_data, ft_offset, 4, mid_start, mid_size)
    set_entry_allocation(con_data, ft_offset, 5, mogg_start, mogg_size)
    set_entry_allocation(con_data, ft_offset, 6, milo_start, milo_size)
    set_entry_allocation(con_data, ft_offset, 7, png_start, png_size)

    total_allocated = 1 + dta_blocks + mid_blocks + mogg_blocks + milo_blocks + png_blocks
    con_data[0x395 : 0x399] = total_allocated.to_bytes(4, 'big')
    con_data[0x399 : 0x39D] = (0).to_bytes(4, 'big')

    def write_payload(start_block: int, content: bytes):
        size = len(content)
        block_count = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
        for i in range(block_count):
            payload_offset = 0xC000 + logical_to_physical(start_block + i) * BLOCK_SIZE
            chunk = content[i * BLOCK_SIZE: (i + 1) * BLOCK_SIZE]
            chunk = chunk + b'\x00' * (BLOCK_SIZE - len(chunk))
            end = payload_offset + BLOCK_SIZE
            if len(con_data) < end:
                con_data.extend(b'\x00' * (end - len(con_data)))
            con_data[payload_offset: end] = chunk

    write_payload(dta_start, dta_content)
    write_payload(mid_start, midi_content)
    write_payload(mogg_start, mogg_content)
    write_payload(milo_start, milo_content)
    write_payload(png_start, png_content)
    con_file_path.write_bytes(con_data)
    os.utime(con_file_path, None)
    click.echo(f"Successfully patched CON: {con_file_path}")
    return con_file_path

def build_ps4_pkg(con_path: Path, output_dir: Path, song_id: str) -> Path:
    pkg_dir = output_dir / "pkg"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "tools/forgetool",
        "con2pkg",
        "--id", "0000000000000001",
        "--desc", f"Custom Song - {song_id}",
        str(con_path),
        str(pkg_dir)
    ]
    click.echo(f"Running ForgeTool: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        click.echo(f"Error during PKG conversion: {result.stderr}", err=True)
        raise RuntimeError(f"ForgeTool failed to build PKG: {result.stderr}")
    pkg_file = pkg_dir / f"{song_id}.pkg"
    return pkg_file
