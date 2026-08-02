# ForgeTool / LibForge Compatibility (CON -> PKG)

AutoRB's CON opens fine in ForgeTool GUI, but the **"CON to PKG Conversion"** flow crashed with:

```
System.OverflowException: Array dimensions exceeded supported range.
   at LibForge.Extensions.StreamExtensions.ReadBytes(Stream s, Int32 count)
   at LibForge.Milo.MiloFile.ParseDirectory(Stream stream)
   at LibForge.Milo.MiloFile.ReadFromStream(Stream stream)
   at LibForge.Util.PkgCreator.ConvertDLCSong(...)
```

## Root cause: contiguous payload I/O across STFS interleave boundaries

`PkgCreator.ConvertDLCSong` derives the song "shortname" from the dta (`songs/<name>/<name>` -> `open_road_song`) and reads `gen/{shortname}.milo_xbox` purely for lipsync (`LipsyncConverter.FromMilo`). The artwork conversion is wrapped in try/catch, so it is never the crash.

`MiloFile.ReadFromStream`:
- Reads the magic (LE u32). `0xCABEDEAF` = **MILO_A** (uncompressed), `0xCDBEDEAF` = **MILO_D** (blocked).
- For MILO_A it reads `offset`(LE, at 0x04), `blockCount`(LE, at 0x08), sums the `blockCount` LE u32 sizes at `0x10`, seeks to `offset`, and copies exactly `sum(sizes)` bytes into a buffer.
- `ParseDirectory` on that buffer: BE u32 version (25/28 supported), length-prefixed `dirType`, `dirName`, skip 8, BE u32 entry count, then for each entry a length-prefixed `(type, name)`. It then **sizes every entry by scanning for a big-endian `0xADDEADDE` padding marker** (`FindNext`). If none is found, `FindNext` returns `-1` and `ReadBytes(-1)` throws the OverflowException.

The crash was **not** a malformed template milo. The template's real milo terminates every entry with `0xADDEADDE` correctly. The bug was AutoRB's contiguous I/O: STFS interleaves a hash-table block every 0xAA logical blocks (see [con_stfs_format.md](con_stfs_format.md)), so a file that crosses a boundary is non-contiguous in physical space. A contiguous read of the template's milo injected the interleaved hash-table block into milo block 12 and dropped the real final block (along with the trailing `0xADDEADDE`), and the contiguous re-pack then placed the milo's last block over a hash-table slot — so GameArchives served the last block from template zeros. Both removed the final marker, producing the `ReadBytes(-1)` overflow.

## The fix: interleave-aware (block-by-block) I/O

`autorb/export/con_packer.py` now reads/writes every logical block through `logical_to_physical()` (`read_file_blocks()` and a per-block `write_payload()`). The extracted/staged milo is the true template milo (81894 bytes) with valid entry terminators, and GameArchives' per-block read of the rebuilt CON serves it byte-identical.

`repair_milo()` remains as a safety net: if a MILO_A milo's final block's data does not end in `0xADDEADDE`, it appends the marker and grows the last block-size field so the marker lands inside the block region LibForge copies. The staged milo is also verified by `_libforge_milo_parseable()` (a replication of LibForge's parse) and the build fails loudly if it can't parse.

## CharLipSync layout (for reference)

`version`(BE u32), `subVersion`(BE u32), `DTAImport`(len-prefixed string), `dtb`(1 byte, must be 0), skip 4, `visemeCount`(BE u32), viseme name strings, `keyFrameCount`(BE u32), skip 4, then per frame: `eventCount`(1 byte) followed by `(visemeIndex, weight)` pairs. The `song.lipsync` entry here parses to 36 visemes and 6749 keyframes.

## Other things that matter in this flow

- **Song name must match filenames.** The dta `(name "songs/open_road_song/open_road_song")` -> shortname `open_road_song`, matching `open_road_song.mid`, `gen/open_road_song.milo_xbox`, `gen/open_road_song_keep.png_xbox`.
- **MILO_D / compressed blocks are unsupported by LibForge.** The 311 reference milo (`MILO_D`, `0xCDBEDEAF`) throws `NotImplementedException("Zlib block inflation not implemented yet")` when a block lacks the `0x01000000` compressed flag — so it can't be used as a conversion source either. Only MILO_A (uncompressed) milos work end-to-end.
- **Artwork failures are non-fatal.** A failed `TextureConverter.MiloPngToTexture` just disables album art via the `warner` callback.
