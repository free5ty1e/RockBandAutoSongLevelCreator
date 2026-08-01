# Changelog

All notable changes to AutoRB will be documented in this file.

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
