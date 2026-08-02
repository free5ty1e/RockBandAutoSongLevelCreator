#!/usr/bin/env python

from pathlib import Path
import struct

from autorb.export.con_packer import logical_to_physical

def simulate_forge_load(con_path: str | Path) -> bool:
    path = Path(con_path)
    if not path.exists():
        raise FileNotFoundError(f"CON file not found: {path}")

    data = path.read_bytes()
    if len(data) < 0xC000:
        raise ValueError("CON file too small")

    if data[0:4] != b"CON ":
        raise ValueError("Invalid CON magic bytes")

    ft_offset = 0xC000
    file_table = data[ft_offset : ft_offset + 4096]

    entries = []
    for i in range(64):
        entry_offset = i * 0x40
        if entry_offset + 0x40 > len(file_table):
            break
        entry_bytes = file_table[entry_offset : entry_offset + 0x40]
        if all(b in (0x00, 0xFF) for b in entry_bytes):
            continue

        name_len = entry_bytes[0x28] & 0x3F
        name = entry_bytes[0:min(name_len, 40)].decode('ascii', errors='ignore')
        if not name or ord(name[0]) == 0 or ord(name[0]) == 0xFF:
            continue

        is_dir = bool(entry_bytes[0x28] & 0x80)
        start_block = int.from_bytes(entry_bytes[0x2F:0x32], 'little')
        file_size = int.from_bytes(entry_bytes[0x34:0x38], 'big')

        entries.append({
            "name": name,
            "is_dir": is_dir,
            "start_block": start_block,
            "file_size": file_size
        })

    print(f"Simulation loaded {len(entries)} entries for {path.name}:")
    for e in entries:
        print(f"  - {'[DIR]' if e['is_dir'] else '[FILE]'} {e['name']} (start_block={e['start_block']}, size={e['file_size']})")
        if not e['is_dir'] and e['file_size'] > 0:
            # Block 0 is the file table at 0xC000; data payloads live at the
            # physical block readers resolve from the logical start block.
            payload_off = 0xC000 + logical_to_physical(e['start_block']) * 4096
            if payload_off + e['file_size'] > len(data):
                raise ValueError(f"File {e['name']} extends beyond file bounds (offset {hex(payload_off)}, size {e['file_size']})")
            content_slice = data[payload_off : payload_off + min(e['file_size'], 100)]
            print(f"    Sample content: {content_slice[:30]!r}")

    return True

if __name__ == "__main__":
    import sys
    files = sys.argv[1:] if len(sys.argv) > 1 else ['output/open_road_song.con']
    for f in files:
        print(f"\nSimulating ForgeTool load for: {f}")
        try:
            simulate_forge_load(f)
            print("SUCCESS: Simulation passed!")
        except Exception as e:
            print(f"FAILURE: Simulation caught error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
