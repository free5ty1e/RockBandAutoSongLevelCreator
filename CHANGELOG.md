# Changelog

All notable changes to AutoRB will be documented in this file.

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
