#!/usr/bin/env python3
"""Deep binary analysis of STFS CON file structures."""
import sys

BLOCK_SIZE = 0x1000

def logical_to_physical(logical):
    """STFS CON logical->physical block mapping (see con_packer.logical_to_physical)."""
    block_adjust = 0
    if logical >= 0xAA:
        block_adjust += (logical // 0xAA) + 1
    if logical >= 0x70E4:
        block_adjust += (logical // 0x70E4) + 1
    if logical >= 0x4AF768:
        block_adjust += (logical // 0x4AF768) + 1
    return logical + block_adjust

def analyze_con(filepath):
    data = open(filepath, 'rb').read()
    print(f'\n{"="*60}')
    print(f'FILE: {filepath}')
    print(f'Total size: {len(data)} bytes ({len(data)/1024:.1f} KB)')
    print(f'Magic: {data[0:4]!r}')
    
    # Header info
    # Display name at offset 0x1691 (411 in STFS)
    display_name_raw = data[0x1691:0x1691+0x80]
    # UTF-16BE display name
    try:
        dn = display_name_raw.decode('utf-16-be', errors='ignore').rstrip('\x00')
        print(f'Display Name: {dn!r}')
    except:
        print(f'Display Name: (decode error)')
    
    # Title name at 0x1711
    title_raw = data[0x1711:0x1711+0x80]
    try:
        tn = title_raw.decode('utf-16-be', errors='ignore').rstrip('\x00')
        print(f'Title Name: {tn!r}')
    except:
        print(f'Title Name: (decode error)')
    
    # Content type at 0x0344
    ct = int.from_bytes(data[0x0344:0x0348], 'big')
    print(f'Content Type: 0x{ct:08X}')
    
    # File table block count at 0x037B (word, big endian usually)
    # Entry ID at 0x0340
    entry_id = int.from_bytes(data[0x0340:0x0344], 'big')
    print(f'Entry ID: 0x{entry_id:08X}')
    
    # STFS descriptor at 0x0379
    # Volume descriptor type at 0x0379
    vdt = data[0x0379] if len(data) > 0x0379 else 0
    print(f'Volume Descriptor Type: {vdt}')
    
    # Block separation at 0x037B 
    # File table block count at 0x037D (2 bytes, little)
    if len(data) > 0x037F:
        ft_block_count = int.from_bytes(data[0x037D:0x037F], 'little')
        ft_block_num = int.from_bytes(data[0x037F:0x0382], 'little') if len(data) > 0x0382 else 0
        print(f'FT Block Count: {ft_block_count}')
        print(f'FT Block Num (start): {ft_block_num}')
    
    # File table at 0xC000
    ft_offset = 0xC000
    print(f'\nFile Table at offset: {hex(ft_offset)}')
    print(f'{"Idx":>3} {"Flags":>5} {"NLen":>4} {"Name":40s} {"Dir?":>5} {"SBlk":>5} {"ABlk":>5} {"RBlk":>5} {"PIdx":>5} {"Size":>10}')
    print('-' * 120)
    
    entries = []
    for i in range(16):
        eo = ft_offset + i * 0x40
        if eo + 0x40 > len(data):
            break
        e = data[eo:eo + 0x40]
        if all(b in (0x00, 0xFF) for b in e):
            continue
        
        nl = e[0x28] & 0x3F
        flags = e[0x28]
        nm = e[0:min(nl, 40)].decode('ascii', errors='replace')
        isd = bool(flags & 0x80)
        sb = int.from_bytes(e[0x2F:0x32], 'little')
        pi = int.from_bytes(e[0x32:0x34], 'big')
        fs = int.from_bytes(e[0x34:0x38], 'big')
        ab = int.from_bytes(e[0x29:0x2C], 'little')
        rb = int.from_bytes(e[0x2C:0x2F], 'little')
        
        print(f'{i:3d} 0x{flags:02X}  {nl:4d} {nm!r:40s} {str(isd):>5} {sb:5d} {ab:5d} {rb:5d} {pi:5d} {fs:10d}')
        
        # Show raw bytes for metadata region
        print(f'     raw[0x28:0x40]: {e[0x28:0x40].hex()}')
        
        entries.append({
            'index': i, 'name': nm, 'is_dir': isd, 'start_block': sb,
            'parent': pi, 'size': fs, 'alloc': ab, 'real': rb, 'flags': flags
        })
        
        # Show payload sample for files
        if not isd and fs > 0:
            payload_off = 0xC000 + logical_to_physical(sb) * BLOCK_SIZE
            if payload_off + min(fs, 100) <= len(data):
                sample = data[payload_off:payload_off + min(fs, 100)]
                print(f'     payload@{hex(payload_off)}: {sample[:60]!r}')
    
    # Build virtual paths
    print('\nVirtual paths:')
    for entry in entries:
        parts = [entry['name']]
        curr = entry
        seen = set()
        while curr['parent'] != 0xFFFF:
            if curr['index'] in seen or curr['parent'] >= len(entries):
                break
            seen.add(curr['index'])
            curr = entries[curr['parent']]
            parts.insert(0, curr['name'])
        vpath = '/' + '/'.join(parts)
        print(f'  [{entry["index"]:2d}] {vpath}')
    
    # Check for songs.dta content
    for entry in entries:
        if entry['name'] == 'songs.dta' and entry['size'] > 0:
            payload_off = 0xC000 + logical_to_physical(entry['start_block']) * BLOCK_SIZE
            if payload_off + entry['size'] <= len(data):
                dta_data = data[payload_off:payload_off + entry['size']]
                print(f'\n--- songs.dta content (entry [{entry["index"]}], {entry["size"]} bytes) ---')
                try:
                    print(dta_data.decode('latin1')[:2000])
                except:
                    print(dta_data[:2000])
                print('--- end songs.dta ---')

    return entries

# Analyze known-good files  
for f in ['output/known_good_cons/SmellsLikeNirvana_rb3con', 'output/known_good_cons/311 - Down']:
    try:
        analyze_con(f)
    except Exception as ex:
        print(f'Error analyzing {f}: {ex}')

# Analyze generated file if it exists
import os
if os.path.exists('output/open_road_song.con'):
    analyze_con('output/open_road_song.con')
else:
    print('\nGenerated CON file not found at output/open_road_song.con')
