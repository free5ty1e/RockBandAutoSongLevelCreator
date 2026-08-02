#!/usr/bin/env python

from pathlib import Path
import shutil
import click
import os

BLOCK_SIZE = 0x1000

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

    # Use SmellsLikeNirvana_rb3con as a known-good signed template CON
    template_con = Path("output/known_good_cons/SmellsLikeNirvana_rb3con")
    con_file_path = output_path / f"{song_id}.con"
    
    if template_con.exists():
        shutil.copy2(template_con, con_file_path)
        click.echo(f"Cloned signed template CON from {template_con}")
    else:
        raise FileNotFoundError(f"Template CON not found at {template_con}")

    con_data = bytearray(con_file_path.read_bytes())

    dta_content = target_dta_parent.read_bytes()
    midi_content = target_mid.read_bytes()
    mogg_content = target_mogg.read_bytes()

    ft_offset = 0xC000

    # Update file table entry names to match active song_id
    set_entry_name(con_data, ft_offset, 1, song_id)
    set_entry_name(con_data, ft_offset, 4, f"{song_id}.mid")
    set_entry_name(con_data, ft_offset, 5, f"{song_id}.mogg")
    set_entry_name(con_data, ft_offset, 6, f"{song_id}.milo_xbox")
    set_entry_name(con_data, ft_offset, 7, f"{song_id}_keep.png_xbox")

    # Helper to update file table entry and write payload
    def update_entry(entry_idx: int, new_content: bytes):
        entry_addr = ft_offset + entry_idx * 0x40
        entry_bytes = con_data[entry_addr : entry_addr + 0x40]
        
        start_block = int.from_bytes(entry_bytes[0x2F:0x32], 'little')
        size = len(new_content)
        block_count = (size + BLOCK_SIZE - 1) // BLOCK_SIZE

        con_data[entry_addr + 0x34 : entry_addr + 0x38] = size.to_bytes(4, 'big')
        con_data[entry_addr + 0x29 : entry_addr + 0x2C] = block_count.to_bytes(3, 'little')
        con_data[entry_addr + 0x2C : entry_addr + 0x2F] = block_count.to_bytes(3, 'little')

        payload_offset = 0xD000 + start_block * BLOCK_SIZE
        
        # If updating songs.dta (entry 3), zero out 8KB to clear any leftover template DTA text
        if entry_idx == 3:
            con_data[payload_offset : payload_offset + 8192] = b'\x00' * 8192

        con_data[payload_offset : payload_offset + size] = new_content

    # Update entry 3 (songs.dta)
    update_entry(3, dta_content)
    # Update entry 4 (mid)
    update_entry(4, midi_content)
    # Update entry 5 (mogg)
    update_entry(5, mogg_content)

    con_file_path.write_bytes(con_data)
    os.utime(con_file_path, None)
    click.echo(f"Successfully patched signed template CON with safe DTA clearing: {con_file_path}")
    return con_file_path
