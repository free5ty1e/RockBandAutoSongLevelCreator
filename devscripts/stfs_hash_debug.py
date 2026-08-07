#!/usr/bin/env python3

import hashlib

def logical_to_physical(logical_block):
    # For Type 0 block separation
    l0_offset = (logical_block // 170)
    l1_offset = (logical_block // 28900)
    l2_offset = (logical_block // 4913000)
    return logical_block + l0_offset + l1_offset + l2_offset

def physical_to_logical(physical_block):
    # Rough approximation, we will just iterate to find it
    for i in range(physical_block + 1):
        if logical_to_physical(i) == physical_block:
            return i
    return -1

def test_hashing(fname):
    print(f"\\nTesting {fname}")
    with open(fname, 'rb') as f:
        data = f.read()

    top_hash_expected = data[0x380:0x394]
    
    total_blocks = (len(data) - 0xC000) // 4096
    print(f"Total blocks (data + hashes): {total_blocks}")
    
    data_blocks = []
    original_l0_blocks = []
    original_l1_blocks = []
    
    physical_idx = 0
    logical_idx = 0
    
    while physical_idx < total_blocks:
        # Check if the current physical block is a hash block
        # An L0 hash block is at physical_idx if physical_idx corresponds to logical_idx % 170 == 0 but it's the block BEFORE the next logical block.
        # Actually, if we just build the expected physical layout:
        # P = logical_to_physical(i) for data block i.
        # Hash L0 for group G is at logical_to_physical((G+1)*170 - 1) + 1 ?
        pass

    # A simpler way: just iterate logical blocks from 0 to total_alloc
    # Total alloc is at 0x394 (BE) ? Let's find it.
    total_alloc = int.from_bytes(data[0x394:0x398], 'big')
    print(f"Total alloc from header: {total_alloc}")
    
    if total_alloc == 0:
        total_alloc = int.from_bytes(data[0x394:0x398], 'little')
        
    for i in range(total_alloc):
        p = logical_to_physical(i)
        if p >= total_blocks:
            print(f"Warning: logical {i} maps to physical {p} which is >= total blocks {total_blocks}")
            break
        data_blocks.append(data[0xC000 + p*4096 : 0xC000 + (p+1)*4096])
        
    print(f"Extracted {len(data_blocks)} data blocks.")
    
    # Rebuild L0
    my_l0_blocks = []
    for i in range(0, len(data_blocks), 170):
        group = data_blocks[i:i+170]
        l0_block = bytearray(4096)
        for j, db in enumerate(group):
            l0_block[j*24 : j*24+20] = hashlib.sha1(db).digest()
        my_l0_blocks.append(l0_block)
        
    # See if they match original L0 blocks
    for idx, l0_block in enumerate(my_l0_blocks):
        # Where is the original L0 block?
        # It comes right after the last data block in this group.
        # The last data block is i + len(group) - 1.
        last_logical = idx * 170 + len(group) - 1
        p_last_data = logical_to_physical(last_logical)
        p_l0 = p_last_data + 1
        if p_l0 < total_blocks:
            orig_l0 = data[0xC000 + p_l0*4096 : 0xC000 + (p_l0+1)*4096]
            if orig_l0 == l0_block:
                print(f"L0 block {idx} matches perfectly!")
            else:
                print(f"L0 block {idx} mismatch at physical {p_l0}!")
        else:
            print(f"L0 block {idx} physical index {p_l0} out of bounds")
            
    # Now for L1 blocks
    my_l1_blocks = []
    for i in range(0, len(my_l0_blocks), 170):
        group = my_l0_blocks[i:i+170]
        l1_block = bytearray(4096)
        for j, lb in enumerate(group):
            l1_block[j*24 : j*24+20] = hashlib.sha1(lb).digest()
        my_l1_blocks.append(l1_block)
        
    print(f"Expected Top Hash: {top_hash_expected.hex()}")
    
    if len(my_l1_blocks) == 1:
        my_top = hashlib.sha1(my_l1_blocks[0]).digest()
        print(f"My Top Hash (from L1): {my_top.hex()}")
        if my_top == top_hash_expected:
            print("MATCH!")
    
    if len(my_l0_blocks) == 1:
        my_top = hashlib.sha1(my_l0_blocks[0]).digest()
        print(f"My Top Hash (from single L0): {my_top.hex()}")
        if my_top == top_hash_expected:
            print("MATCH!")
            
    # Let's also check if top hash is just hash of concatenated L0 blocks
    my_top_alt = hashlib.sha1(b''.join(my_l0_blocks)).digest()
    print(f"My Top Hash (alt): {my_top_alt.hex()}")

test_hashing('output/known_good_cons/SmellsLikeNirvana_rb3con')
test_hashing('output/known_good_cons/311 - Down')
