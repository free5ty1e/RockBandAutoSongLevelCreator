# Rock Band Customs Domain Knowledge

## Target Format: Xbox 360 CON (STFS)
We target the Xbox 360 CON format because it is the universally accepted standard for modern custom songs. Community tools like Onyx Music Toolkit can ingest Xbox 360 CONs and effortlessly convert them to PS3, PS4 (Rock Band 4 Deluxe), Wii, or Clone Hero formats. 

## Known Tooling Quirks & Technical History
- **The ForgeTool Zlib Crash:** Older custom songs or tools often packed files using "Stored" (uncompressed) Zlib blocks. When converting these to PS4 using ForgeTool GUI, it crashes with a "Zlib block inflation not implemented yet" error because ForgeTool lacks the logic to read Type 0 blocks.
- **The Onyx Fix:** Onyx acts as a "cleaner." Processing files through Onyx rewrites the internal Zlib blocks into standard Deflated formats that tools like ForgeTool can decompress without crashing. Note: Onyx does not have a dedicated "PS4" button; users target Xbox 360 in Onyx to standardize the CON, which is then passed to PS4 packaging tools. Our AutoRB tool must ensure its output mimics this clean, deflated Zlib standard to prevent downstream crashes for users.

## MIDI Requirements
- **PART VOCALS:** Requires syllable-by-syllable note placement. Pitch matters for harmonies, but for basic vocals, timing and text injection (via MIDI lyric events) are the primary requirements.
- **Instrument Lanes:** 5 lanes (0=Green, 1=Red, 2=Yellow, 3=Blue, 4=Orange).
