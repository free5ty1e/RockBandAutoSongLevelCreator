# Xbox 360 CON / STFS Format (Block Addressing)

Everything below was derived from reading GameArchives (`STFSPackage.cs`) and free60/arkem documentation, and verified byte-for-byte against `output/known_good_cons/311 - Down`, `SmellsLikeNirvana_rb3con`, and AutoRB's own output.

## Physical layout

```
0x0000..0xC000  STFS header + hash tables (2x for odd/even magic, 0xAA-entry levels)
0xC000..        Data blocks, 0x1000 bytes each
```

- Block 0 (physical offset `0xC000`) is the **file table** (8 entries of 0x40 = 0x200 bytes, followed by zero padding).
- Every `0xAA` logical blocks a hash table is interleaved, so logical block N is NOT at physical block N.

## Logical -> physical mapping (the fix)

Readers interpret a file-table `start` field as a **logical** block number and compute the physical offset as:

```
physical_offset = 0xC000 + logical_to_physical(logical) * 0x1000

def logical_to_physical(logical):
    adj = 0
    if logical >= 0xAA:   adj += (logical // 0xAA) + 1
    if logical >= 0x70E4: adj += (logical // 0x70E4) + 1
    if logical >= 0x4AF768: adj += (logical // 0x4AF768) + 1
    return logical + adj
```

This is the arkem/free60 "fix block numbers" formula with `table_size_shift = 0` (valid because `block separation & 1 == 1` for all reference CONs here, `entry_id@0x340 = 0x0000AD0E`). GameArchives uses the same formula (`fixBlockNumber`), which is why its reads matched ours. **Data files must be allocated starting at logical block 1** (block 0 is the file table itself).

Forget the old `0xD000 + start * 0x1000` assumption — it silently reads the file-table block as `songs.dta` and makes ForgeTool throw `Element at index 0 is not an Array. It is DataSymbol`.

## File table entry (0x40 bytes, big-endian name, mixed-endian fields)

| Offset | Size | Field |
| --- | --- | --- |
| 0x00 | 0x28 | Name (ASCII, null-padded) |
| 0x28 | 1 | Flags: `0x80` dir / `0x40` file + low 6 bits = name length |
| 0x29 | 3 LE | Allocated blocks |
| 0x2C | 3 LE | Real blocks |
| 0x2F | 3 LE | Start block (logical) |
| 0x34 | 4 BE | Size |
| 0x38 | 2 BE | Parent directory index (0xFFFF = root) |

Directory entries carry `size=0`; `gen/` must sit inside the song dir with the song as its parent.

## Volume descriptor (header, offsets from 0)

| Offset | Size | Field |
| --- | --- | --- |
| 0x340 | 4 | `entry_id` (0x0000AD0E -> shift 0) |
| 0x37C | 2 LE | File table block count (1) |
| 0x37E | 3 LE | File table block number (0) |
| 0x395 | 4 BE | **Total Allocated Block Count** = 1 (file table) + sum(file allocated blocks) |
| 0x399 | 4 BE | **Total Unallocated Block Count** (must be 0) |

When rebuilding a CON that grew, recompute the `0x395`/`0x399` fields or readers/validators will disagree about the package size.

## Reference payload offsets in the SmellsLikeNirvana template

- `.milo_xbox` at physical `0x4AD000` (logical 3551 in the rebuilt CON)
- `_keep.png_xbox` at physical `0x4C2000` (logical 3571)

AutoRB extracts these from the template, patches them (see [ForgeTool/LibForge compatibility](forgetool_compat.md)), then re-packs them contiguously after `.mogg`. All 5 payloads in the rebuilt `output/open_road_song.con` byte-match the staged files.
