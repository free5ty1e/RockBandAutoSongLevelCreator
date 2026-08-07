#!/usr/bin/env python3

# Let me carefully parse the volume descriptor based on the STFS spec
# The volume descriptor at 0x379 is 0x24 (36) bytes long
# The structure (from community docs) is:
# 0x379: 1 byte - Volume Descriptor Size (0x24)
# Then the actual Volume Descriptor struct starts at 0x37A:
# +0x00 (0x37A): 1 byte - reserved/block separation  
# +0x01 (0x37B): 2 bytes LE - File Table Block Count
# +0x03 (0x37D): 3 bytes LE - File Table Block Number (starting block)
# +0x06 (0x380): 20 bytes - Top Hash Table Hash (SHA-1)
# +0x1A (0x394): 4 bytes BE - Total Allocated Block Count  
# +0x1E (0x398): 4 bytes BE - Total Unallocated Block Count

for fname in ['output/known_good_cons/SmellsLikeNirvana_rb3con', 'output/known_good_cons/311 - Down', 'output/open_road_song.con']:
    import os
    if not os.path.exists(fname): continue
    data = open(fname, 'rb').read()
    print(f'=== {fname} ({len(data)} bytes) ===')
    
    vd_size = data[0x379]
    block_sep = data[0x37A]
    ft_bc = int.from_bytes(data[0x37B:0x37D], 'little')
    ft_bn = int.from_bytes(data[0x37D:0x0380], 'little')
    top_hash = data[0x380:0x394].hex()
    total_alloc_be = int.from_bytes(data[0x394:0x398], 'big')
    total_alloc_le = int.from_bytes(data[0x394:0x398], 'little')
    total_unalloc_be = int.from_bytes(data[0x398:0x039C], 'big')
    total_unalloc_le = int.from_bytes(data[0x398:0x039C], 'little')
    
    print(f'  VD Size: 0x{vd_size:02X}')
    print(f'  Block Sep: {block_sep}')
    print(f'  FT Block Count: {ft_bc}')
    print(f'  FT Block Num: {ft_bn}')
    print(f'  Top Hash (SHA1): {top_hash}')
    print(f'  Total Alloc (BE): {total_alloc_be}  (LE): {total_alloc_le}')
    print(f'  Total Unalloc (BE): {total_unalloc_be}  (LE): {total_unalloc_le}')
    
    # Let's also check bytes 0x039C-0x03A0 for file counts
    raw_39c = data[0x039C:0x03A0]
    print(f'  Raw @0x39C: {raw_39c.hex()} (BE: {int.from_bytes(raw_39c, \"big\")}, LE: {int.from_bytes(raw_39c, \"little\")})')
    
    # Content size at 0x0348
    content_size = int.from_bytes(data[0x0348:0x034C], 'big')
    content_size_le = int.from_bytes(data[0x0348:0x034C], 'little')
    print(f'  Content Size @0x348 (BE): {content_size}  (LE): {content_size_le}')
    
    # The real useful comparison: file sizes and whether the template CON is identical  
    # Check if open_road_song.con header bytes 0x0000-0x0400 match template
    print()
    
import os
# Now check if the header of open_road_song.con is identical to SmellsLikeNirvana
template = open('output/known_good_cons/SmellsLikeNirvana_rb3con', 'rb').read()
generated = open('output/open_road_song.con', 'rb').read()

print('=== Header comparison (template vs generated) ===')
print(f'Template size: {len(template)}, Generated size: {len(generated)}')

# Check 0x0000-0xC000 (header) byte-by-byte
diffs_in_header = 0
for i in range(min(0xC000, len(template), len(generated))):
    if template[i] != generated[i]:
        diffs_in_header += 1
        if diffs_in_header <= 20:
            print(f'  Diff at 0x{i:04X}: template=0x{template[i]:02X} generated=0x{generated[i]:02X}')

print(f'Total diffs in header (0x0000-0xC000): {diffs_in_header}')

# Check file table differences
ft_diffs = 0
for i in range(0xC000, min(0xD000, len(template), len(generated))):
    if template[i] != generated[i]:
        ft_diffs += 1
print(f'Total diffs in file table (0xC000-0xD000): {ft_diffs}')
