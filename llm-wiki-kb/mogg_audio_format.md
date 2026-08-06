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

## Ogg page size is critical (v0.0058)

The embedded Ogg bitstream **must use small pages**. ffmpeg's default libvorbis paging emits ~1-second / ~56KB pages (granule deltas ~31000-36000 samples). Rock Band's **Milkshake** audio engine cannot reliably decode such coarse pages — on PS4 the custom song converted and installed (RB4DX + ForgeTool) but had **no audio preview in the song list** and **"completed instantly" at 0%** when played.

Known-good stock moggs (e.g. "311 - Down" RB3 DLC) use ~4KB pages with ~2048-3072 sample granules (4006 pages for the full song). AutoRB now forces this via the ffmpeg Ogg muxer's `-page_duration` option:

```bash
ffmpeg ... -c:a libvorbis -q:a 5 -page_duration 40000 -f ogg out.ogg
```

`PAGE_DURATION_US = 40000` (40 ms page target) in `mogg_builder.py` yields pages of ~2048-3072 granules at 44100 Hz. The rebuilt `output/open_road_song.mogg` has 4233 pages, avg 3414 bytes/page, granule deltas 2048/2624.

## song_length comes from the real audio (v0.0058)

`songs.dta`'s `(song_length ...)` was previously hardcoded (230162) and did not match the actual audio. `dta_writer.py` now derives it with `read_mogg_duration_ms()`: parse the MOGG `header_size` (u32 at offset 4), read the Vorbis identification header's sample rate (LE u32 at packet offset 12), take the final audio granulepos from the Ogg pages, and return `granule * 1000 // rate` ms. `generate_songs_dta(..., song_length=...)` can still override the value explicitly; it falls back to 198089 ms with a warning only if the MOGG is missing.

## Channel layout

The Ogg stream is a **single logical stream with N channels**; songs.dta's `tracks` assigns channels to instruments. AutoRB emits **10 channels** mirroring the proven-working "311 - Down" DLC layout (which maps cleanly through ForgeTool's `MakeMoggDta` to `drum (0) drum (1) drum (2 3) bass (4) guitar (5 6) vocals (7 8) fake (9)`):

```
ch0-1 full drum kit split stereo (v0.0069: was digital silence)
ch2-3 stereo drum kit
ch4  mono bass
ch5-6 stereo guitar/backing (the 'other' stem)
ch7-8 stereo vocals
ch9  quiet fake/crowd ambience (backing at 0.1 gain; was digital silence)
```

**v0.0069 correction (silent channels → silent preview):** binary decoding of the reference "311 - Down" MOGG showed **every channel carries audio** — kick/snare ch0/1 are its LOUDEST channels (~3511/1328 RMS vs ~704/530 on the kit ch2/3) and ch9 fake/crowd reads ~50 RMS. AutoRB's previous layout forced ch0/1/ch9 to `volume=0`, which made the PS4 song-list preview **completely silent** while gameplay audio (which mixes ch2-8) still worked. `mogg_builder.py` now sends the full drum kit to ch0/1 and low-level backing to ch9. Any preview mixdown that uses the front stereo pair — or any default mix the engine picks — is therefore never silent. This is the best-supported remaining explanation for the v0.0068 "no preview audio" report (chart, `songs.dta` preview window (ms), rbmid `PreviewStartMillis`, OggMap byte offsets, and Ogg page sizes were all independently verified correct and structurally equivalent to 311 Down).

`pans`/`vols`/`cores` arrays in songs.dta must have one value per channel (10 entries, guitar channels cored). The 8-channel layout used before v0.0059 (`drum 0-1, bass 2-3, guitar 4-5, vocals 6-7`) left the track/channel structure different from every stock/311 song; `maxton/LibForge#30` documents that a track layout that does not match the physical MOGG makes songs start but stop playing prematurely in-game — the failure family of the persistent "no preview + instant 0%" bug.

## Implementation

`autorb/export/mogg_builder.py`:
- With the 4 standard stems present, pans each stem into mono/stereo channels (`pan`/`aformat` filters) and `amerge=inputs=10` -> 10ch Ogg @ source rate (44100). Since v0.0069 the full drum kit is sent to ch0/1 and a low-level backing ambience to ch9 so **every channel carries audio** (previously 0, 1, and 9 were derived from the drums input with `volume=0`). A generic per-stem stereo merge fallback handles non-standard stem counts.
- Preprends the mandatory count-in silence with `adelay={count_in_ms}:all=1` on the merged output when `count_in_ms > 0` (v0.0064) — the game expects a silent pre-roll (stock 311 - Down has ~5s of MOGG lead-in); the chart is shifted to match via `midi_generator.generate_vocal_midi(count_in_ticks=...)`.
- Forces small Ogg pages with `-page_duration 40000` (`PAGE_DURATION_US`) — RB's Milkshake decoder fails on ffmpeg-default ~1s/56KB pages (see above).
- `wrap_ogg_as_mogg()` parses the Ogg pages and prepends the v10 header + OggMap (pure Python, no external tools beyond ffmpeg). The OggMap's per-entry sample values track page granules (about 1024 samples lower than the reference `ogg2mogg` tool's `ov_raw_seek`+`ov_pcm_tell` values at each 0x8000-byte row, which only affects seek precision, not forward playback; byte offsets are identical).
- `read_mogg_duration_ms()` parses the MOGG header + Vorbis id header + final granule to report the real audio duration for songs.dta's `(song_length ...)` — after the count-in is added this includes the lead-in silence (e.g. 198089 -> 202547 ms).

## References

- Format: https://milo.ipg.pw/index.php/MOGG_File_Format
- `ogg2mogg` (reference builder, public domain): https://github.com/mtolly/ogg2mogg
- `moggulator` (Python port + decryption): https://github.com/LocalH/moggulator
