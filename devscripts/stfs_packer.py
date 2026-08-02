#!/usr/bin/env python3

import hashlib
import struct
import math

BLOCK_SIZE = 4096

def logical_to_physical(logical_block):
    return logical_block + (logical_block // 170) + (logical_block // 28900)

def compute_stfs_hashes(data_blocks):
    """
    Given a list of bytes (each representing a 4096-byte data block),
    returns a dictionary mapping physical block index to its 4096-byte content,
    including the data blocks and the generated hash blocks.
    Also returns the top hash (SHA-1).
    """
    physical_blocks = {}
    
    # Store all data blocks at their physical locations
    for i, data in enumerate(data_blocks):
        physical_blocks[logical_to_physical(i)] = data
        
    num_data_blocks = len(data_blocks)
    
    # Level 0 Hash Blocks (hashes of data blocks)
    num_l0_blocks = math.ceil(num_data_blocks / 170)
    l0_hashes = [] # List of SHA1 hashes for the L0 blocks
    
    for l0_idx in range(num_l0_blocks):
        hash_block = bytearray(BLOCK_SIZE)
        start_idx = l0_idx * 170
        end_idx = min(start_idx + 170, num_data_blocks)
        
        for i in range(start_idx, end_idx):
            data = data_blocks[i]
            sha1 = hashlib.sha1(data).digest()
            # Each hash record is 24 bytes: 20 bytes SHA1 + 4 bytes status/info
            # For data blocks, we'll use status 0x80 (valid) in the first byte of status?
            # Actually, the 4 byte status is usually:
            # bit 7: 1=valid, 0=invalid. (0x80)
            # Or we can just set it to 0x80 00 00 00, or let's use 0x40 00 00 00.
            # Free60 says: 0x80 = Active. We'll use 0x80, 0x00, 0x00, 0x00.
            record_offset = (i % 170) * 24
            hash_block[record_offset:record_offset+20] = sha1
            # Status: 0x80 for valid? Wait, let's look at a real hash block.
            # Next block index is sometimes stored here. Let's just put 0x80 for valid for now.
        
        # Calculate physical index of this L0 block
        # The L0 block comes immediately after its data blocks
        # Wait, if start_idx = 0, the L0 block is at logical 170's physical spot?
        # Actually, the physical index of the L0 block is logical_to_physical(end_idx - 1) + 1.
        # BUT if the group is incomplete (e.g. only 5 data blocks), the L0 block is still placed right after those 5? 
        # NO! STFS is pre-allocated rigidly. The L0 block is ALWAYS at physical block (l0_idx * 170 + 170)??
        # Let's check 311 - Down.
        pass


