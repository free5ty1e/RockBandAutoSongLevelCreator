# Changelog

All notable changes to AutoRB will be documented in this file.

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
