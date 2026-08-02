# Rock Band Customs Domain Knowledge

## Target Format: Xbox 360 CON (STFS)
We target the Xbox 360 CON format because it is the universally accepted standard for modern custom songs. Community tools like Onyx Music Toolkit can ingest Xbox 360 CONs and effortlessly convert them to PS3, PS4 (Rock Band 4 Deluxe), Wii, or Clone Hero formats. 

## Known Tooling Quirks & Technical History
- **The ForgeTool Zlib Crash:** Older custom songs or tools often packed files using "Stored" (uncompressed) Zlib blocks. When converting these to PS4 using ForgeTool GUI, it crashes with a "Zlib block inflation not implemented yet" error because ForgeTool lacks the logic to read Type 0 blocks.
- **The Onyx Fix:** Onyx acts as a "cleaner." Processing files through Onyx rewrites the internal Zlib blocks into standard Deflated formats that tools like ForgeTool can decompress without crashing. Note: Onyx does not have a dedicated "PS4" button; users target Xbox 360 in Onyx to standardize the CON, which is then passed to PS4 packaging tools. Our AutoRB tool must ensure its output mimics this clean, deflated Zlib standard to prevent downstream crashes for users.

## MIDI Requirements
- **PART VOCALS:** Requires syllable-by-syllable note placement. Pitch matters for harmonies, but for basic vocals, timing and text injection (via MIDI lyric events) are the primary requirements. AutoRB now writes real `start`/`end`/`pitch` per word into `synced_lyrics` (from word segments + Basic-Pitch note events); a chart with every note at tick 0 / pitch 60 renders as a flash of the fretboard then an instant 0% finish.
- **EVENTS markers (mandatory):** Every chart must carry the text markers `[prc_intro]`, `[music_start]`, `[prc_verse_1]`, `[preview]`, `[prc_chorus_1]`, `[prc_outro]`, `[music_end]`, and `[end]` (as the final event). A missing `[preview]` kills the song-list preview; a missing `[music_end]`/`[end]` makes the game finish the song instantly at 0% (with the full-combo jingle).
- **BEAT track (real markers):** Stock RB3 charts carry one quarter-note marker per beat in `BEAT` — pitch 12 on the downbeat (vel 101) and pitch 13 on other beats (vel 100), spaced 480 ticks apart at 120 BPM. A named BEAT track with no notes does not satisfy the engine.
- **Difficulty ranks:** `songs.dta` `(rank ...)` values drive the in-game difficulty dots. AutoRB computes per-instrument ranks from chart note density via level bands 1-6 (`difficulty.py`) and sets `band` to the hardest charted instrument — never a hardcoded value that renders every song as "1 of 6".
- **Instrument Lanes:** 5 lanes (0=Green, 1=Red, 2=Yellow, 3=Blue, 4=Orange).
