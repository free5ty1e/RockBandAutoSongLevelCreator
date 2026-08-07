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

Readers interpret a file-table `start` field as a **logical** block number and compute each block's physical offset as:

```
physical_offset = 0xC000 + logical_to_physical(logical) * 0x1000

def logical_to_physical(logical):
    adj = 0
    if logical >= 0xAA:   adj += (logical // 0xAA) + 1
    if logical >= 0x70E4: adj += (logical // 0x70E4) + 1
    if logical >= 0x4AF768: adj += (logical // 0x4AF768) + 1
    return logical + adj
```

This is the arkem/free60 "fix block numbers" formula with `table_size_shift = 0` (valid because `block separation & 1 == 1` for all reference CONs here, `entry_id@0x340 = 0x0000AD0E`). GameArchives uses the same formula (`fixBlockNumber`), which is why its reads matched ours.

### CRITICAL: physical blocks are NOT contiguous

A level-0 hash-table block sits between every group of **0xAA logical blocks**. So a file that spans a boundary (e.g. logical 169 -> 170 -> 171 maps to physical 170 -> 172 -> 173, skipping the hash-table block at physical 171) does **not** occupy consecutive physical blocks. This is why:

- **Writing**: a payload must be written block-by-block (`logical_to_physical(start + i) * 0x1000` for each block `i`). Writing contiguously from the first physical block overwrites hash-table slots and misplaces the tail of any file crossing a boundary.
- **Reading**: the same per-block resolution must be used. A contiguous read picks up hash-table bytes and drops the file's real last block.

Both bugs hit together: the template's milo (logical 1178-1197 in the template) crossed the 1190 boundary; a contiguous read injected the hash-table block into milo block 12 and lost the real final block (and its trailing `0xADDEADDE` terminator), which made ForgeTool's `ParseDirectory` fail. Data files must be allocated starting at logical block 1 (block 0 is the file table itself).

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

- `.milo_xbox` at physical `0x4AD000` (logical 1178)
- `_keep.png_xbox` at physical `0x4C2000` (logical 1198)

AutoRB extracts these from the template block-by-block, then re-packs them interleave-aware after `.mogg`. A faithful replication of GameArchives' per-block read of the rebuilt `output/open_road_song.con` serves all 5 payloads byte-identical to the staged files.

## `_keep.png_xbox` album art texture (HMXBitmap)

The `{song_id}_keep.png_xbox` inside `songs/{song_id}/gen/` is NOT a PNG. It is a standalone Milo `HMXBitmap` texture: a **32-byte header** followed by S3TC (DXT) block data whose every 16-bit word is byte-swapped (Xbox 360 little-endian quirks).

Header layout (matches Mackiloha's `HMXBitmapSerializer.cs` / SuperFreq `png2tex --platform x360`):

| Offset | Size | Field |
| --- | --- | --- |
| 0x00 | 1 | Magic `0x01` (some files use `0x02`) |
| 0x01 | 1 | Bits per pixel: `4` = DXT1, `8` = DXT5 |
| 0x02 | 4 LE | Encoding: `8` = DXT1, `24` = DXT5 |
| 0x06 | 1 | Mip count byte (official DLC uses `4`, SuperFreq custom art uses `0`) |
| 0x07 | 2 LE | Width |
| 0x09 | 2 LE | Height |
| 0x0B | 2 LE | Bytes per line = `width * bpp / 8` |
| 0x0D | 19 | Zero padding |

Payload sizes: DXT1 = `w*h/2` bytes, DXT5 = `w*h` bytes (base mip only). Official DLC art is DXT5 256x256 with 4 mips (87444 B template / 43680 B for the DXT1 311 art); SuperFreq `png2tex` emits a single mip (mips byte `0`), e.g. a 256x256 DXT5 file is 65568 bytes. `autorb/export/texture.py` encodes opaque art as DXT1 (mips 0) and alpha-bearing art as DXT5; decoded round-trips of both the template and a SuperFreq reference validate byte-compatible against the header spec.

Verified with `pretty_midi`: the "311 - Down" `down2.mid` PART DRUMS track genuinely contains 5411 note-ons (all difficulty lanes + chord hits), not the ~800 a naive parser suggests — calibrating density heuristics against it requires the corrected count.
