#!/usr/bin/env python3

with open('output/known_good_cons/311 - Down', 'rb') as f:
    f.seek(0xC000 + 170 * 4096)
    hash_block = f.read(4096)
    for i in range(170):
        status = hash_block[i*24+20:(i+1)*24]
        if status != b'\x00\x00\x00\x00':
            print(f'Entry {i} has status {status.hex()}')
            break
    else:
        print('All statuses are 00000000 in 311 - Down L0 hash block 0')
