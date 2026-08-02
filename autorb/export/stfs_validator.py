#!/usr/bin/env python

from pathlib import Path
import struct

BLOCK_SIZE = 0x1000

def logical_to_physical(logical: int) -> int:
    """STFS CON logical->physical block mapping (see con_packer.logical_to_physical)."""
    block_adjust = 0
    if logical >= 0xAA:
        block_adjust += (logical // 0xAA) + 1
    if logical >= 0x70E4:
        block_adjust += (logical // 0x70E4) + 1
    if logical >= 0x4AF768:
        block_adjust += (logical // 0x4AF768) + 1
    return logical + block_adjust

def validate_con(con_path: str | Path) -> dict:
    """
    Parses an Xbox 360 STFS CON file and validates its file table structure,
    parent directory references, and file integrity to catch errors like
    'File references non-existent directory' before testing in ForgeTool GUI.
    """
    path = Path(con_path)
    if not path.exists():
        raise FileNotFoundError(f"CON file not found: {path}")

    data = path.read_bytes()
    if len(data) < 0xA000:
        raise ValueError("Invalid CON file: File too small for STFS header")

    magic = data[0:4]
    if magic != b"CON ":
        raise ValueError(f"Invalid CON magic bytes: {magic!r} (expected b'CON ')")

    # Determine file table offset (check 0xC000 first (12 blocks), then 0xA000 (10 blocks))
    file_table_offset = 0xC000
    if len(data) <= 0xC000 or not (b'songs' in data[0xC000:0xC000+0x40]):
        if b'songs' in data[0xA000:0xA000+0x40]:
            file_table_offset = 0xA000
        else:
            # Search for 'songs' in 4KB block increments from 0x8000 to 0x10000
            found = False
            for offset in range(0x8000, min(len(data), 0x20000), BLOCK_SIZE):
                if b'songs' in data[offset:offset+0x40]:
                    file_table_offset = offset
                    found = True
                    break
            if not found:
                file_table_offset = 0xC000 # default fallback

    file_table = data[file_table_offset:file_table_offset + BLOCK_SIZE]

    entries = []
    for i in range(64):
        entry_offset = i * 0x40
        if entry_offset + 0x40 > len(file_table):
            break
        entry_bytes = file_table[entry_offset:entry_offset + 0x40]
        
        # Check if entry is empty/unallocated
        if all(b == 0xFF for b in entry_bytes) or all(b == 0x00 for b in entry_bytes):
            if not entries:
                continue
            # Check if all remaining entries are empty
            if all(all(b in (0x00, 0xFF) for b in file_table[j*0x40:(j+1)*0x40]) for j in range(i, 64)):
                break

        name_len = entry_bytes[0x28] & 0x3F
        name = entry_bytes[0:min(name_len, 40)].decode('ascii', errors='ignore')
        is_dir = bool(entry_bytes[0x28] & 0x80)
        allocated_blocks = int.from_bytes(entry_bytes[0x29:0x2C], 'little')
        real_blocks = int.from_bytes(entry_bytes[0x2C:0x2F], 'little')
        start_block = int.from_bytes(entry_bytes[0x2F:0x32], 'little')
        parent_index = int.from_bytes(entry_bytes[0x32:0x34], 'big')
        file_size = int.from_bytes(entry_bytes[0x34:0x38], 'big')

        if not name or ord(name[0]) == 0 or ord(name[0]) == 0xFF:
            continue

        entries.append({
            "index": i,
            "name": name,
            "is_dir": is_dir,
            "allocated_blocks": allocated_blocks,
            "real_blocks": real_blocks,
            "start_block": start_block,
            "parent_index": parent_index,
            "file_size": file_size
        })

    # Validate parent references
    errors = []
    for entry in entries:
        p_idx = entry["parent_index"]
        if p_idx != 0xFFFF:
            if p_idx < 0 or p_idx >= len(entries):
                errors.append(f"Entry {entry['index']} ({entry['name']}) references out-of-bounds parent index {p_idx}")
            else:
                parent_entry = entries[p_idx]
                if not parent_entry["is_dir"]:
                    errors.append(f"Entry {entry['index']} ({entry['name']}) references parent index {p_idx} ({parent_entry['name']}) which is a file, not a directory.")

    # Build virtual paths
    def get_path(entry):
        parts = [entry["name"]]
        curr = entry
        seen = set()
        while curr["parent_index"] != 0xFFFF:
            if curr["index"] in seen or curr["parent_index"] >= len(entries):
                break
            seen.add(curr["index"])
            curr = entries[curr["parent_index"]]
            parts.insert(0, curr["name"])
        return "/" + "/".join(parts)

    virtual_paths = [get_path(e) for e in entries]

    # Validate payload placement: readers resolve the logical start block to a
    # physical offset of 0xC000 + logical_to_physical(start) * 0x1000.  If the
    # payload does not live there (or extends past the file), the CON will not
    # load, regardless of how clean the file table looks.
    for entry in entries:
        if entry["is_dir"] or entry["file_size"] == 0:
            continue
        payload_off = 0xC000 + logical_to_physical(entry["start_block"]) * BLOCK_SIZE
        payload_end = payload_off + entry["file_size"]
        if payload_end > len(data):
            errors.append(f"Entry {entry['index']} ({entry['name']}) payload "
                          f"(offset {hex(payload_off)}, size {entry['file_size']}) "
                          f"extends past end of CON file ({len(data)} bytes)")
        elif data[payload_off:payload_off + min(entry["file_size"], 16)] == b'\x00' * min(entry["file_size"], 16):
            errors.append(f"Entry {entry['index']} ({entry['name']}) payload at {hex(payload_off)} is zeroed (block addressing likely wrong)")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "entry_count": len(entries),
        "entries": entries,
        "virtual_paths": virtual_paths,
        "file_table_offset": file_table_offset
    }

if __name__ == "__main__":
    import sys
    con_file = sys.argv[1] if len(sys.argv) > 1 else "output/open_road_song.con"
    print(f"Validating CON file: {con_file}")
    try:
        result = validate_con(con_file)
        print(f"File Table Offset: {hex(result['file_table_offset'])}")
        print(f"Entry count: {result['entry_count']}")
        for entry, vpath in zip(result["entries"], result["virtual_paths"]):
            print(f"  [{entry['index']}] {vpath} (is_dir={entry['is_dir']}, parent={entry['parent_index']}, size={entry['file_size']})")
        if result["valid"]:
            print("CON file structure is VALID!")
        else:
            print("CON file structure has ERRORS:")
            for err in result["errors"]:
                print(f"  - {err}")
            sys.exit(1)
    except Exception as e:
        print(f"Validation failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
