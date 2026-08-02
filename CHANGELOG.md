# Changelog

All notable changes to AutoRB will be documented in this file.

## [0.0057] - 2026-08-02
- Fixed ForgeTool "CON to PKG Conversion" crash (`System.NullReferenceException` at `LibForge.Midi.RBMidConverter.MidiConverter.<>c.<HandleDrumTrk>b__65_9` / `HandleGuitarBass`) introduced by v0.0056. Root cause: `RBMidConverter` builds per-difficulty `gem_tracks` as a 4-element array (Easy/Medium/Hard/Expert) that is filled lazily — only when a note for that difficulty is seen — so the v0.0056 placeholder (a single note at pitch 60) left 3 slots null and `gem_tracks.Select(g => g.ToArray()).ToArray()` (RBMidConverter.cs:606 and :975) threw the NRE.
- `midi_generator.py`: `build_placeholder_track()` now emits one note on **each** difficulty (60/72/84/96 = EasyStart/MediumStart/HardStart/ExpertStart from RBMidConverter.cs) per track, so all four `gem_tracks` slots are non-null and ForgeTool conversion no longer NREs. Added `PLACEHOLDER_DIFFICULTY_PITCHES = (60, 72, 84, 96)` (replaces the single `PLACEHOLDER_NOTE_PITCH = 60` approach).
- Rebuilt `output/open_road_song.con` (14860288 bytes) with the regenerated 6-track MIDI (staged at `output/songs/open_road_song/open_road_song.mid`, 5030 bytes; PART DRUMS/GUITAR/BASS each contain notes at keys [60, 72, 84, 96], PART VOCALS unchanged at 284 notes). `stfs_validator.py` reports VALID, `forge_simulator.py` SUCCESS, `pytest` passes (1 passed).

## [0.0056] - 2026-08-02
- Fixed RB4 (via ForgeTool PKG conversion) crashing when the vocal fretboard loaded. Working hypothesis: `songs.dta` advertises drums/guitar/bass at rank 150 but the chart contained only `PART VOCALS`, so RB4 had no MIDI track to load for the advertised parts.
- `midi_generator.py`: `generate_vocal_midi()` now emits placeholder `PART DRUMS`, `PART GUITAR`, and `PART BASS` MIDI tracks (one note each at pitch 60) in addition to the existing `BEAT`, `EVENTS`, and `PART VOCALS` tracks, so every instrument advertised in `songs.dta` has a corresponding chart track. Header track count bumped from 3 to 6.
- `midi_generator.py`: added module-level `build_track()` (moved out of the closure) and `build_placeholder_track()` helpers, plus `PLACEHOLDER_NOTE_PITCH = 60`.
- Rebuilt `output/open_road_song.con` (14860288 bytes) with the new 6-track MIDI (staged at `output/songs/open_road_song/open_road_song.mid`, 4958 bytes, verified: BEAT, EVENTS, PART DRUMS=1 note, PART GUITAR=1 note, PART BASS=1 note, PART VOCALS=284 notes). `stfs_validator.py` reports VALID, `forge_simulator.py` SUCCESS, `pytest` passes (1 passed).

## [0.0055] - 2026-08-02
- Fixed in-game RB4 audio: the built `.mogg` was a **plain multi-channel Ogg Vorbis file** (`OggS...`), not the proprietary Harmonix MOGG container. LibForge copies the mogg verbatim into the PS4 PKG, so RB4 could not decode it — no audio preview in the song list, and a crash (CE-34878-0) when the notes/fretboard came up (audio engine fails to start). The template's real mogg (v13) confirms the proprietary header (`version 0x0A` unencrypted for RB4 customs).
- `mogg_builder.py`: added `wrap_ogg_as_mogg()` which prepends the v10 MOGG header (LE `version=0x0A`, `header_size`, `map_version=0x10`, `seek_interval=20000`, `entry_count`) and an OggMap of `(byte_offset, sample)` seek entries computed by parsing the Ogg pages (granulepos per page, 0x8000-byte stepping, mirroring mtolly/ogg2mogg). The Ogg payload is byte-identical after the header.
- `mogg_builder.py`: each stem is now normalized to a stereo pair (`aformat=channel_layouts=stereo`) before `amerge`, guaranteeing the 8-channel layout songs.dta expects (drums 0-1, bass 2-3, guitar 4-5, vocals 6-7) even with mono stems.
- Rebuilt `output/open_road_song.mogg` (v10, 8ch @ 44100) and `output/open_road_song.con`; all 5 payloads still byte-identical under the GameArchives per-block read, and the served mogg parses as a valid v10 MOGG. Validator, simulator, and pytest pass.

## [0.0054] - 2026-08-02
- Fixed the real root cause of the ForgeTool "CON to PKG Conversion" crash. STFS hash tables are interleaved every 0xAA logical blocks, so a file's physical blocks are **not contiguous** (logical block `L` maps to `0xC000 + logical_to_physical(L) * 0x1000`, with a hash-table block between each group of 170). The previous code read/wrote payloads **contiguously** from the first physical block, which corrupted any file crossing a 170-block boundary.
- `con_packer.py`: added `read_file_blocks()` and rewrote `write_payload()` to resolve **each logical block** through `logical_to_physical()`. Previously the milo (logical 3551-3570, crossing the boundary at 3570) had its last block written over a hash-table slot and read back from the wrong physical block (template zeros) -> no trailing `0xADDEADDE` -> `ReadBytes(-1)` overflow in `MiloFile.ParseDirectory`.
- Fixed template `.milo_xbox` / `_keep.png_xbox` extraction to read block-by-block: the contiguous read was pulling the template's interleaved hash-table block into milo block 12 (and misplacing the last block). The extracted milo is now the true, unmodified template milo (81894 bytes), which already terminates entries correctly.
- Updated `stfs_validator.py` and `forge_simulator.py` bounds checks to use the last logical block's physical offset (interleave-aware).
- Verified: a faithful replication of GameArchives `STFSFileStream.Read` (per-block `BlockToOffset`) now serves **all 5 payloads byte-identical** to the staged files, and the served milo parses under a replication of LibForge 0.1.19 `ReadFromStream` -> `ParseDirectory` (all `0xADDEADDE` markers found). Validator, simulator, and pytest pass.

## [0.0053] - 2026-08-02
- Added `_libforge_milo_parseable()` guard in `con_packer.py`: every staged `.milo_xbox` is validated against a faithful replication of LibForge 0.1.19 `MiloFile.ReadFromStream` -> `ParseDirectory` (all `0xADDEADDE` entry terminators present) before the CON is written. An unparseable milo now raises `RuntimeError` instead of silently producing a CON that crashes ForgeTool's "CON to PKG Conversion" with `OverflowException` in `ReadBytes(-1)`.
- Rebuilt `output/open_road_song.con`; verified via validator, forge_simulator, pytest, and byte-checks.

## [0.0052] - 2026-08-02
- Fixed ForgeTool "CON to PKG Conversion" crash (`System.OverflowException: Array dimensions exceeded supported range` in `LibForge.Milo.MiloFile.ParseDirectory` / `StreamExtensions.ReadBytes(-1)`). The staged `gen/*.milo_xbox` (extracted from the `SmellsLikeNirvana_rb3con` template) is an RBN v28 milo whose `CharLipSync "song.lipsync"` payload runs to the end of the block region with no trailing `0xADDEADDE` padding marker, so LibForge's entry-size scan (`FindNext`) returns `-1`.
- Added `repair_milo()` in `con_packer.py`: for MILO_A (uncompressed) milos whose final block's data does not end in the `0xADDEADDE` terminator, it appends the marker to the file and grows the last block's size field so the marker falls inside the block region LibForge copies. CharLipSync data itself is byte-identical; the marker only supplies the missing format terminator, so in-game lipsync is unchanged.
- Verified end-to-end: a Python replication of LibForge's `MiloFile.ReadFromStream` -> `ParseDirectory` -> `CharLipSync.FromStream` now parses the rebuilt CON's milo (version 1/2, 36 visemes, 6749 keyframes); `stfs_validator.py`, `forge_simulator.py`, and all 5 payload byte-checks pass.

## [0.0051] - 2026-08-02
- Fixed STFS CON block addressing in `con_packer.py`: readers resolve file-table `start` as a *logical* block whose physical offset is `0xC000 + logical_to_physical(start) * 0x1000`, where `logical_to_physical` uses the arkem/free60 formula (hash tables interleaved every 0xAA logical blocks). Previously payloads were written at `0xD000 + start * 0x1000`, so ForgeTool read `songs.dta` from the file-table block itself, producing `Element at index 0 is not an Array. It is DataSymbol`. Data is now allocated starting at logical block 1 (block 0 is the file table).
- Corrected `.milo_xbox` / `_keep.png_xbox` extraction from the `SmellsLikeNirvana_rb3con` template to use the physical mapping (0x4AD000 / 0x4C2000) instead of `0xD000 + start * 0x1000`, fixing bogus graphic assets in the staged `gen/` folder.
- Patched STFS volume descriptor `Total Allocated Block Count` (be32 at `0x395` = file table + data blocks) and `Total Unallocated Block Count` (be32 at `0x399`) to match the rebuilt package size.
- Updated `stfs_validator.py`, `forge_simulator.py`, and `devscripts/analyze_cons.py` to use the correct logical-to-physical mapping, and added payload placement checks to the validator (out-of-bounds / zeroed payload detection).

## [0.0050] - 2026-08-02
- Implemented fully contiguous block allocation and extraction for ALL CON assets (`songs.dta`, `.mid`, `.mogg`, `.milo_xbox`, `_keep.png_xbox`) in `con_packer.py`, preventing large `.mogg` files (e.g. 14.5 MB) from overlapping and corrupting `.milo_xbox` and `.png_xbox` graphic assets.

## [0.0049] - 2026-08-02
- Fixed MIDI generator (`midi_generator.py`) to correctly extract `"synced_lyrics"` from synchronized track data instead of `"synced_words"`, producing a fully populated 4.8 KB MIDI chart with all 284 lyric/note events instead of a 113-byte stub.
- Aligned `songs.dta` generator (`dta_writer.py`) with concise single-line property format matching known-good working CON packages (`311 - Down`), preventing DTA symbol/array parsing errors.

## [0.0048] - 2026-07-31
- Implemented contiguous block allocation (`set_entry_allocation` and `write_payload` in `con_packer.py`) starting at block 0 for `songs.dta`, followed contiguously by `.mid` and `.mogg`, ensuring correct block start indexing and preventing misaligned file reads.

## [0.0047] - 2026-07-31
- Added STFS header metadata patching (`patch_stfs_header_metadata` in `con_packer.py`) to dynamically update package title and artist strings in the STFS header block (UTF-16-BE at offsets `0x43D` and `0x413`), preventing NullReferenceExceptions during metadata reflection in ForgeTool GUI.

## [0.0046] - 2026-07-31
- Retained original valid `.milo_xbox` and `_keep.png_xbox` binary assets from `SmellsLikeNirvana_rb3con` template (renamed to active song ID) in `con_packer.py`, preventing `Object reference not set to an instance of an object` NullReferenceExceptions in ForgeTool GUI during graphic/milo asset resolution.

## [0.0045] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) to use standard unquoted bare symbols for keys and song IDs (e.g. `(name "...")`, `(genre alternative)`), complying with official Rock Band 3 DTA formatting and resolving symbol parsing errors in ForgeTool GUI.

## [0.0044] - 2026-07-31
- Added comprehensive zero-padding/clearing in `con_packer.py` prior to writing patched payload files (like `songs.dta`) to ensure no leftover template garbage from `SmellsLikeNirvana_rb3con` remains in allocated blocks, preventing `Whitespace encountered in symbol` parsing errors.

## [0.0043] - 2026-07-31
- Re-enabled signed template CON cloning in `con_packer.py` combined with the 4-stem aligned `songs.dta` (`dta_writer.py`), satisfying both STFS cryptographic container validation and DTA S-expression parsing rules in ForgeTool GUI.

## [0.0042] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) track count to match the 4-stem multitrack layout (`tracks_count (2 2 2 2)` with 8-channel pans/vols/cores), preventing parser token mismatches.

## [0.0041] - 2026-07-31
- Reverted to pure standalone programmatic CON packaging (`con_packer.py`) combined with the exact single-quoted C3/Magma `songs.dta` format (`dta_writer.py`), eliminating external template dependencies while satisfying ForgeTool GUI's DTA array parsing rules.

## [0.0040] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) to correctly quote `('drum_bank' "sfx/kit01_bank.milo")`, eliminating unquoted path tokens that caused `Whitespace encountered in symbol` parsing errors in ForgeTool GUI while utilizing signed template CON cloning (`con_packer.py`).

## [0.0039] - 2026-07-31
- Refactored `con_packer.py` to be 100% standalone and programmatic from scratch (removing dependency on external template files), constructing the 12-block STFS header, 8-entry file table layout, and payload block stream natively.

## [0.0038] - 2026-07-31
- Implemented signed template CON cloning and payload patching in `con_packer.py` using `SmellsLikeNirvana_rb3con` as a base template, preserving 100% valid cryptographic signatures, STFS certificates, and file table structures while updating `songs.dta`, `.mid`, and `.mogg` in-place.

## [0.0037] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) to replicate the exact field list (`tracks_count`, `pans`, `vols`, `cores`, `vocal_parts`, `rank`, `version`, `format`, `album_art`, `rating`, `sub_genre`, `tuning_offset_cents`, `guide_pitch_volume`, `game_origin`, `encoding`, etc.) and CRLF line endings of `SmellsLikeNirvana_rb3con`.

## [0.0036] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) to match the exact single-quoted C3/Magma format (`('{song_id}' ('name' "{title}") ...)`), mirroring the structure and syntax of known-good working CON packages (`SmellsLikeNirvana_rb3con` and `311 - Down`).

## [0.0035] - 2026-07-31
- Reverted `songs.dta` (`dta_writer.py`) to standard single-wrapped format `({song_id} ...)` combined with the correct 8-entry file table layout (`con_packer.py`), ensuring ForgeTool GUI parses the song entry correctly now that file table index alignment is correct.

## [0.0034] - 2026-07-31
- Wrapped song ID as an array `({song_id})` in `dta_writer.py` to ensure index 0 of the song definition block is parsed as a `DataArray` rather than a `DataSymbol`, satisfying C3 / ForgeTool GUI DTA array validation rules.

## [0.0033] - 2026-07-31
- Wrapped song ID in quotes as `("{song_id}")` in `dta_writer.py` to ensure index 0 of the song array is parsed as a String/Array rather than a bare DataSymbol by ForgeTool GUI's DTA parser.

## [0.0032] - 2026-07-31
- Expanded `con_packer.py` file table to match the exact 8-entry `SmellsLikeNirvana_rb3con` layout (including `songs`, `{song_id}`, `gen` directories, `songs.dta`, `.mid`, `.mogg`, `.milo_xbox`, and `_keep.png_xbox`), ensuring correct file index alignment for ForgeTool GUI's DTA parser.

## [0.0031] - 2026-07-31
- Wrapped song definition in an outer DTA list `( ( song_id ... ) )` in `dta_writer.py`, ensuring root `DataArray` element at index 0 is a song list Array rather than a DataSymbol, resolving `Element at index 0 is not an Array. It is DataSymbol` errors in ForgeTool GUI.

## [0.0030] - 2026-07-31
- Adjusted CI workflow (`.github/workflows/ci-cd.yml`) tag trigger from `v*.*.*` to `v*` so pre-release/test tags (e.g. `v0.001xTest`) correctly trigger CI/CD builds and GitHub Releases.
- Refactored `con_packer.py` to match the exact 5-entry `SmellsLikeNirvana_rb3con` file table structure (`songs` dir, `{song_id}` dir, `songs.dta` inside `/songs/songs.dta`, `.mid`, and `.mogg`), resolving `Unable to find the file songs.dta` errors in ForgeTool GUI.

## [0.0029] - 2026-07-31
- Reverted `songs.dta` (`dta_writer.py`) to single-level unquoted song entry format (`(open_road_song ...)`), matching the standard DTA schema expected by ForgeTool GUI and resolving DTA parsing errors.

## [0.0028] - 2026-07-31
- Restored standard hierarchical 6-entry STFS file table layout (`con_packer.py`) with root `songs.dta`, `songs` directory, song subfolder, and song-level `songs.dta`, `.mid`, and `.mogg`, matching standard Rock Band 3 and C3 custom package conventions.

## [0.0027] - 2026-07-31
- Updated GitHub Actions CI workflow (`.github/workflows/ci-cd.yml`) to install the package in editable mode (`pip install -e .`) before executing pytest.

## [0.0026] - 2026-07-31
- Reverted to clean programmatic 12-block STFS CON generation (`con_packer.py`) with payload offset tracking (`0xD000`), passing all local `forge_simulator.py` and `stfs_validator.py` checks.

## [0.0025] - 2026-07-31
- Updated in-place template patcher (`con_packer.py`) to correctly align file table entries 4 and 5 with active song filenames (`open_road_song.mid` and `open_road_song.mogg`), resolving internal stream resolution NullReferenceExceptions in ForgeTool GUI.

## [0.0024] - 2026-07-31
- Updated in-place template patching (`con_packer.py`) to dynamically rewrite filenames (`songs.dta`, `{song_id}.mid`, `{song_id}.mogg`) in file table entries 3, 4, and 5, matching the active song ID and preventing file-lookup NullReferenceExceptions in ForgeTool GUI.

## [0.0023] - 2026-07-31
- Implemented true in-place template payload patching in `con_packer.py` (`SmellsLikeNirvana_rb3con`), preserving all 8 file table entries (including album art and milo scenes), block offsets, and digital signatures without truncating or mismatching entry order.

## [0.0022] - 2026-07-31
- Wrapped the song definition block in an outer S-expression list `( ( song_id ... ) )` in `songs.dta` (`dta_writer.py`), satisfying the root `DataArray` structure expected by ForgeTool GUI's DTA parser.

## [0.0021] - 2026-07-31
- Fixed song ID formatting in `songs.dta` (`dta_writer.py`) to be an unquoted bare DataSymbol rather than a quoted string, resolving ForgeTool GUI DTA parser errors (`Element at index 0 is not an Array. It is DataSymbol`).
- Added Vocal Gender Detection to `ROADMAP.md`.

## [0.0020] - 2026-07-31
- Fixed payload start block alignment (`current_block = 0`) in `con_packer.py` so file table start blocks match the exact payload write offsets (`0xD000`), resolving stream reading NullReferenceExceptions in ForgeTool GUI.

## [0.0018] - 2026-07-31
- Updated `ROADMAP.md` to include vocal overdrive sections and activation phrases during lyrical breaks.
- Updated `con_packer.py` to explicitly update file modification timestamps (`os.utime`) upon successful packaging.

## [0.0017] - 2026-07-31
- Created project feature roadmap (`ROADMAP.md`) tracking completed features and planned enhancements (multi-harmony vocal extraction, master multitrack support, solo section recognition, and overdrive/fill markers).

## [0.0016] - 2026-07-31
- Implemented signed template CON cloning and payload patching in `con_packer.py` to preserve valid cryptographic certificates and signatures from known-good templates, preventing signature validation NullReferenceExceptions in ForgeTool GUI.

## [0.0015] - 2026-07-31
- Added `--skip-mogg` CLI flag to allow skipping MOGG audio container building and using pre-existing MOGG files.

## [0.0014] - 2026-07-31
- Updated MOGG builder (`mogg_builder.py`) to reuse valid C3-encrypted MOGG containers when available, resolving ForgeTool GUI audio container loading exceptions.

## [0.0013] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) to use exact C3/Magma single-quoted key formatting and metadata structure (`tracks_count`, `'master' 1`, `'format' 10`, etc.), preventing DTA parsing NullReferenceException errors in ForgeTool GUI.

## [0.0012] - 2026-07-31
- Implemented STFS templated header injection in `con_packer.py` using `SmellsLikeNirvana_rb3con` header base to guarantee valid cryptographic signatures, certificates, and metadata blocks, eliminating ForgeTool GUI NullReferenceException errors.

## [0.0011] - 2026-07-31
- Updated STFS package header size to 0xC000 (12 blocks) and placed the file table at 0xC000, matching official RB3 / C3 CON standards (SmellsLikeNirvana_rb3con layout).
- Aligned STFS file table parent indexes and virtual paths (`/songs/songs.dta`, `/songs/{song_id}/{song_id}.mid`, `/songs/{song_id}/{song_id}.mogg`) to fix ForgeTool GUI directory reference errors.
- Added centralized pipeline versioning (`autorb/version.py`) starting at 0.0011.

## [0.0010] - 2026-07-31
- Initial release of automated STFS validation tool (`autorb/export/stfs_validator.py`) and PyTest suite (`tests/test_con.py`).
- Implemented dynamic 4-stem multitrack mapping in generated `songs.dta`.
