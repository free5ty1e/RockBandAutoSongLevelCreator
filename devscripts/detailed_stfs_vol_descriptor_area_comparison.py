#!/usr/bin/env python3

# Detailed comparison of the STFS volume descriptor area
# The STFS Volume Descriptor starts at 0x0379 for CON files
# Based on Free60/community documentation:
# 0x0379: Volume Descriptor Size (1 byte) - should be 0x24 (36 bytes)
# 0x037A: (padding/reserved)  
# 0x037B-0x037E: 
# The actual STFS volume descriptor structure (at 0x037A, 36 bytes):
#   +0x00 (0x037A): 1 byte - Block Separation (0 or 1)
#   +0x01 (0x037B): 2 bytes LE - File Table Block Count  
#   +0x03 (0x037D): 3 bytes LE - File Table Block Number
#   +0x06 (0x0380): ?? 
# But let me just carefully dump and compare the raw bytes

for fname in ['output/known_good_cons/SmellsLikeNirvana_rb3con', 'output/known_good_cons/311 - Down', 'output/open_road_song.con']:
    import os
    if not os.path.exists(fname):
        print(f'SKIP: {fname}')
        continue
    data = open(fname, 'rb').read()
    print(f'=== {fname} ({len(data)} bytes) ===')
    
    # Dump raw bytes around the volume descriptor  
    print('Header area [0x0340-0x03A8]:')
    for off in range(0x0340, 0x03A8, 16):
        chunk = data[off:off+16]
        hex_str = ' '.join(f'{b:02X}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f'  {off:04X}: {hex_str}  |{ascii_str}|')
    
    # The STFS Volume Descriptor is traditionally at offset 0x379
    # Size byte at 0x0379
    print(f'  VD Size byte @0x379 = 0x{data[0x379]:02X}')
    # Block Separation at VD+1 = 0x037A
    print(f'  Block Sep @0x37A = 0x{data[0x37A]:02X}')
    # File Table Block Count at VD+2 (2 bytes LE) = 0x037B
    ftbc = int.from_bytes(data[0x037B:0x037D], 'little')
    print(f'  FT Block Count @0x37B = {ftbc}')
    # File Table Block Number at VD+4 (3 bytes LE) = 0x037D
    ftbn = int.from_bytes(data[0x037D:0x0380], 'little')
    print(f'  FT Block Num @0x37D = {ftbn}')
    # Total Allocated Block Count at VD+7 (3 bytes LE) = 0x0380 
    tabc = int.from_bytes(data[0x0380:0x0383], 'little')
    print(f'  Total Alloc Block Cnt @0x380 = {tabc}')
    # Total Unallocated Block Count at VD+10 (3 bytes LE) = 0x0383
    tubc = int.from_bytes(data[0x0383:0x0386], 'little')
    print(f'  Total Unalloc Block Cnt @0x383 = {tubc}')
    
    # Number of file table entries (at various offsets)
    # Data File Count at 0x039D (4 bytes BE? or LE?)
    dfc_be = int.from_bytes(data[0x039D:0x03A1], 'big')
    dfc_le = int.from_bytes(data[0x039D:0x03A1], 'little')
    print(f'  Data File Count @0x39D = BE:{dfc_be}, LE:{dfc_le}')
    
    # Data File Combined Size at 0x03A1 (8 bytes)
    dfcs = int.from_bytes(data[0x03A1:0x03A9], 'big')
    print(f'  Data File Combined Size @0x3A1 = {dfcs}')
    
    print()

