# MOGG Audio Format (Rock Band)

MOGG is Harmonix's multi-track audio container: a **proprietary header + OggMap prepended to a regular multi-channel Ogg Vorbis bitstream**. It is the audio format for RB1-RB4 (360/PS3/PS4); LibForge copies the CON's `.mogg` **byte-for-byte** into the PS4 PKG — RB4 does not re-encode it.

## Why this matters (the RB4 crash)

AutoRB originally produced a **plain multi-channel Ogg** (`OggS...` at offset 0). On PS4:
- No audio preview in the song list (RB4 preview audio comes from the mogg).
- Crash `CE-34878-0` at song start, right when the notes/fretboard appear — the audio engine fails to decode the file.

The template's real mogg starts with the proprietary header, confirming the required layout.

## Layout (all integers little-endian)

```
u32 version         0x0A = v10, unencrypted (all RB4 customs; RB4 supports v10-v17)
u32 header_size     byte offset where the Ogg data begins  == 20 + 8 * entry_count
u32 map_version     0x10
u32 seek_interval   20000 samples
u32 entry_count
OggMap: [u32 byte_offset, u32 sample] * entry_count
... raw Ogg Vorbis bytes (byte-identical to the source .ogg)
```

`version >= 0x0B` adds AES encryption + IV in the header; the Ogg payload itself is then ciphertext (no `OggS` in cleartext — e.g. the RB3 template is v13).

## The OggMap

The game uses it to seek (practice mode, pause rewind, preview): to reach sample `N`, it seeks to `OggMap[N / seek_interval].byte_offset` and skips `N - OggMap[...].sample` samples. AutoRB builds it by parsing every Ogg page's **granulepos**:

1. Parse pages: `[(file_offset, granulepos)]`; audio pages carry the PCM sample position, header pages carry `-1`.
2. For every `0x8000`-byte increment, record the granulepos of the page containing it (`-1` -> `0xFFFFFFFF` so it never qualifies).
3. For each `20000`-sample frame, pick the last seek entry whose sample is `<=` the frame start.

This mirrors `mtolly/ogg2mogg` (`SEEK_INCREMENT 0x8000`, `FRAME_INCREMENT 20000`). Precision only affects seek granularity, never playback.

## Channel layout

The Ogg stream is a **single logical stream with N channels**; songs.dta's `tracks` assigns channels to instruments. AutoRB emits 8 channels = 4 stereo pairs matching `dta_writer.py`:

```
drums 0-1, bass 2-3, guitar 4-5, vocals 6-7
```

`pans`/`vols`/`cores` arrays in songs.dta must have one value per channel (8 entries).

## Implementation

`autorb/export/mogg_builder.py`:
- Encodes each stem to a stereo pair (`aformat=channel_layouts=stereo`) then `amerge=inputs=4` -> 8ch Ogg @ source rate (44100).
- `wrap_ogg_as_mogg()` parses the Ogg pages and prepends the v10 header + OggMap (pure Python, no external tools beyond ffmpeg).

## References

- Format: https://milo.ipg.pw/index.php/MOGG_File_Format
- `ogg2mogg` (reference builder, public domain): https://github.com/mtolly/ogg2mogg
- `moggulator` (Python port + decryption): https://github.com/LocalH/moggulator
