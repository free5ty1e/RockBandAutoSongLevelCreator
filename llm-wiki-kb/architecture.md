# Architecture & Pipeline

AutoRB is a Python CLI tool that automates the creation of Rock Band 3 CON (STFS) files from raw audio and lyrics.

## The Pipeline
1. **Stem Separation:** Meta's `demucs` separates the source audio into `drums.wav`, `bass.wav`, `vocals.wav`, and `other.wav`.
2. **Tempo & Beat Mapping:** `librosa` analyzes the audio to generate a continuous BPM map and measure grid.
3. **Vocal Alignment (The LRC Upgrade):** 
   - Accepts Standard LRC (line-level) files.
   - Uses WhisperX (or similar OpenAI Whisper implementation with `word_timestamps=True`) to force-align the provided text to the `vocals.wav` stem.
   - Outputs an Enhanced LRC (word/syllable-level) mapping for the MIDI compiler.
4. **Instrument Transcription:** `basic-pitch` extracts raw MIDI from the stems. A down-charting algorithm quantizes these notes to 5-lane Rock Band frets (Green, Red, Yellow, Blue, Orange) across 4 difficulties (Expert -> Easy).
5. **MOGG Generation:** `pydub`/`ffmpeg` mixes the stems into a multi-channel OGG file and prepends the proprietary Harmonix MOGG header.
6. **STFS/CON Packaging & Validation:** `con_packer.py` assembles the hierarchical `songs/{song_id}/` structure containing `.mid`, `.mogg`, and `songs.dta` (with full 4-stem multitrack mapping: drums `0-1`, bass `2-3`, guitar `4-5`, vocals `6-7`) into an Xbox 360 CON file. `stfs_validator.py` and `pytest` provide automated validation of STFS file tables and parent directory references in the devcontainer.
