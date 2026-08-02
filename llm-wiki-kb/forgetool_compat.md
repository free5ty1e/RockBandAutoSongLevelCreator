# ForgeTool / LibForge Compatibility (CON -> PKG)

AutoRB's CON opens fine in ForgeTool GUI, but the **"CON to PKG Conversion"** flow crashed with:

```
System.OverflowException: Array dimensions exceeded supported range.
   at LibForge.Extensions.StreamExtensions.ReadBytes(Stream s, Int32 count)
   at LibForge.Milo.MiloFile.ParseDirectory(Stream stream)
   at LibForge.Milo.MiloFile.ReadFromStream(Stream stream)
   at LibForge.Util.PkgCreator.ConvertDLCSong(...)
```

## Root cause: missing 0xADDEADDE terminator in the template milo

`PkgCreator.ConvertDLCSong` derives the song "shortname" from the dta (`songs/<name>/<name>` -> `open_road_song`) and reads `gen/{shortname}.milo_xbox` purely for lipsync (`LipsyncConverter.FromMilo`). The artwork conversion is wrapped in try/catch, so it is never the crash.

`MiloFile.ReadFromStream`:
- Reads the magic (LE u32). `0xCABEDEAF` = **MILO_A** (uncompressed), `0xCDBEDEAF` = **MILO_D** (blocked).
- For MILO_A it reads `offset`(LE, at 0x04), `blockCount`(LE, at 0x08), sums the `blockCount` LE u32 sizes at `0x10`, seeks to `offset`, and copies exactly `sum(sizes)` bytes into a buffer.
- `ParseDirectory` on that buffer: BE u32 version (25/28 supported), length-prefixed `dirType`, `dirName`, skip 8, BE u32 entry count, then for each entry a length-prefixed `(type, name)`. It then **sizes every entry by scanning for a big-endian `0xADDEADDE` padding marker** (`FindNext`). If none is found, `FindNext` returns `-1` and `ReadBytes(-1)` throws the OverflowException.

The staged `SmellsLikeNirvana` template milo (81894 bytes) is an RBN **v28** milo: `ObjectDir "lipsync"` containing a single `CharLipSync "song.lipsync"` whose payload runs to the end of the block region **with no trailing `0xADDEADDE`**. The only marker in the whole file is the one after the entry headers.

## The fix: `repair_milo()` in `autorb/export/con_packer.py`

Because `ReadFromStream` copies exactly the summed block sizes, appending a marker *at the end of the file* is not enough — it must land **inside** the copied block region. `repair_milo()` therefore:
1. Only touches MILO_A milos.
2. Grows the **last block's size field** by 4 (so `total_size` includes the marker).
3. Appends the 4-byte marker `\xad\xde\xad\xde` to the file.

The `CharLipSync` data is byte-identical; the marker is just the missing format terminator, so in-game lipsync is unchanged. Verified by replicating LibForge in Python: `ReadFromStream -> ParseDirectory -> CharLipSync.FromStream` now parses the rebuilt CON's milo (version 1/2, 36 visemes, 6749 keyframes).

## CharLipSync layout (for reference)

`version`(BE u32), `subVersion`(BE u32), `DTAImport`(len-prefixed string), `dtb`(1 byte, must be 0), skip 4, `visemeCount`(BE u32), viseme name strings, `keyFrameCount`(BE u32), skip 4, then per frame: `eventCount`(1 byte) followed by `(visemeIndex, weight)` pairs. The `song.lipsync` entry here parses to 36 visemes and 6749 keyframes.

## Other things that matter in this flow

- **Song name must match filenames.** The dta `(name "songs/open_road_song/open_road_song")` -> shortname `open_road_song`, matching `open_road_song.mid`, `gen/open_road_song.milo_xbox`, `gen/open_road_song_keep.png_xbox`.
- **MILO_D / compressed blocks are unsupported by LibForge.** The 311 reference milo (`MILO_D`, `0xCDBEDEAF`) throws `NotImplementedException("Zlib block inflation not implemented yet")` when a block lacks the `0x01000000` compressed flag — so it can't be used as a conversion source either. Only MILO_A (uncompressed) milos work end-to-end.
- **Artwork failures are non-fatal.** A failed `TextureConverter.MiloPngToTexture` just disables album art via the `warner` callback.
