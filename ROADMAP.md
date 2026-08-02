# AutoRB Feature Roadmap

## Completed Features
- [x] **Universal Audio Ingestion:** CLI support for standard audio formats (MP3, WAV, FLAC, M4A) via FFmpeg.
- [x] **AI Stem Separation:** Integration with Meta's **Demucs** to isolate drums, bass, vocals, and backing tracks.
- [x] **Smart Lyrics & Vocal Alignment:** Enhanced LRC (.lrc) parsing and WhisperX forced alignment.
- [x] **Automatic Instrument Transcription:** Spotify's **Basic-Pitch** and signal processing for 5-lane instrument tracks.
- [x] **MOGG Audio Container Builder:** Multi-channel OGG mixing with Harmonix container format support (`--skip-mogg` CLI flag).
- [x] **C3/Magma Compatible DTA Writer:** Automated `songs.dta` metadata generation formatted with single-quoted keys and track mappings.
- [x] **Automatic Difficulty Rating Calculator:** Per-instrument `rank` values now computed from chart note density (verified against the "311 - Down" DLC reference: our linear factors reproduce its 311/250/225/144/233 ranks as 302/246/218/144/228) instead of the hardcoded `(rank ... 150 ...)` block that rendered every song as difficulty 1 of 6.
- [x] **Custom Album Art Support:** New `--album-art` CLI flag encodes any PNG/JPG cover into the CON's `_keep.png_xbox` texture (reverse-engineered HMXBitmap header + byte-swapped DXT1/DXT5, matching SuperFreq `png2tex --platform x360` output); defaults to a generated generic "Chris Prime Custom" image.
- [x] **Devcontainer Test Suite:** Comprehensive PyTest test suite (`tests/test_con.py`, `tests/test_texture_and_difficulty.py`) running locally in the devcontainer.

## In Progress
- [~] **In-Game Audio Playback:** The STFS/CON package now validates and loads in ForgeTool (`STFS VALID`, `forge SUCCESS`), but on the PS4 test environment (RB4DX) the song still has no audio preview in the song list, and in-game the vocal fretboard/lyrics render for ~0.5 s before the song instantly finishes at 0%. Three consecutive MOGG structural fixes (small Ogg pages, real `song_length`, 10-channel 311 "Down" layout mirroring) produced identical symptoms, so the remaining cause is likely elsewhere (e.g. the `.mogg.dta`/`.moggsong` metadata, MIDI chart end markers, or how the engine starts the audio stream).

## Planned Features & Enhancements
- [ ] **Vocal Gender Detection:** Automatically analyze the pitch and spectral characteristics of the dominant vocal stem to infer singer vocal gender (`'male'` vs `'female'`) for `songs.dta` metadata.
- [ ] **Multi-Harmony Vocal Extraction:** Extract harmony parts and melody parts from vocal tracks to support Rock Band's multi-harmony system (up to 3 microphones: 1 melody and 2 harmonies).
- [ ] **Master Track Multitrack Support:** Allow passing separated master guitar and keyboard audio parts directly when original multitracks/stems are available, bypassing AI Demucs separation.
- [ ] **Solo Section Recognition:** Automatically detect and mark guitar, drum, and bass solo sections to activate the Rock Band solo scoring/lighting system.
- [ ] **Overdrive & Drum/Vocal Fill Markers:** Automatically compute and mark overdrive (star power) activation phrases across instruments, including vocal overdrive sections and regular activation opportunities / talkie/freestyle phrases during lyrical breaks.
