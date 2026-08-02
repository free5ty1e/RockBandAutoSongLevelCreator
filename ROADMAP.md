# AutoRB Feature Roadmap

## Completed Features
- [x] **Universal Audio Ingestion:** CLI support for standard audio formats (MP3, WAV, FLAC, M4A) via FFmpeg.
- [x] **AI Stem Separation:** Integration with Meta's **Demucs** to isolate drums, bass, vocals, and backing tracks.
- [x] **Smart Lyrics & Vocal Alignment:** Enhanced LRC (.lrc) parsing and WhisperX forced alignment.
- [x] **Automatic Instrument Transcription:** Spotify's **Basic-Pitch** and signal processing for 5-lane instrument tracks.
- [x] **MOGG Audio Container Builder:** Multi-channel OGG mixing with Harmonix container format support (`--skip-mogg` CLI flag).
- [x] **C3/Magma Compatible DTA Writer:** Automated `songs.dta` metadata generation formatted with single-quoted keys and track mappings.
- [x] **Devcontainer Test Suite:** Comprehensive PyTest test suite (`tests/test_con.py`) running locally in the devcontainer.

## In Progress
- [~] **Xbox 360 STFS / CON Packaging & Validation:** STFS package assembler with signed template cloning/patching and automated structure validator (`autorb/export/stfs_validator.py`).  Currently fails to open with ForgeTools GUI, which has provided errors such as:

```
Error loading C:\Users\test\Documents\code\RockBandAutoSongLevelCreator\output\open_road_song.con: File references non-existent directory.

Error loading \\192.168.100.135\incoming\temp\Rb4Auto\open_road_song.con: Object reference not set to an instance of an object.

Error loading \\192.168.100.135\incoming\temp\Rb4Auto\open_road_song.con: Element at index 0 is not an Array. It is DataSymbol

Error loading \\192.168.100.135\incoming\temp\Rb4Auto\open_road_song.con: Unable to find the file songs.dta

Error loading \\192.168.100.135\incoming\temp\Rb4Auto\open_road_song.con: Whitespace encountered in symbol.

```

See recent git commit messages for details regarding current STFS packaging issues.

## Planned Features & Enhancements
- [ ] **Vocal Gender Detection:** Automatically analyze the pitch and spectral characteristics of the dominant vocal stem to infer singer vocal gender (`'male'` vs `'female'`) for `songs.dta` metadata.
- [ ] **Multi-Harmony Vocal Extraction:** Extract harmony parts and melody parts from vocal tracks to support Rock Band's multi-harmony system (up to 3 microphones: 1 melody and 2 harmonies).
- [ ] **Master Track Multitrack Support:** Allow passing separated master guitar and keyboard audio parts directly when original multitracks/stems are available, bypassing AI Demucs separation.
- [ ] **Solo Section Recognition:** Automatically detect and mark guitar, drum, and bass solo sections to activate the Rock Band solo scoring/lighting system.
- [ ] **Overdrive & Drum/Vocal Fill Markers:** Automatically compute and mark overdrive (star power) activation phrases across instruments, including vocal overdrive sections and regular activation opportunities / talkie/freestyle phrases during lyrical breaks.
