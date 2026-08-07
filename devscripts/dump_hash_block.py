import sys

with open('output/known_good_cons/SmellsLikeNirvana_rb3con', 'rb') as f:
    f.seek(0xC000 + 170 * 4096)
    hash_block = f.read(4096)
    
    print("Hash Block at 0xB6000 (Physical Block 170, L0 for blocks 0-169):")
    for i in range(10): # First 10 entries
        entry = hash_block[i*24:(i+1)*24]
        sha1 = entry[:20].hex()
        status = entry[20:].hex()
        print(f"  Entry {i:3d}: SHA1={sha1} Status={status}")

    # Check an entry near the end of the file table to see what unused looks like
    print("...")
    for i in range(165, 170):
        entry = hash_block[i*24:(i+1)*24]
        sha1 = entry[:20].hex()
        status = entry[20:].hex()
        print(f"  Entry {i:3d}: SHA1={sha1} Status={status}")
