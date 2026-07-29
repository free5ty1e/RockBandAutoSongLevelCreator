# Project Specification: AutoRB (Automated Rock Band CON Generator)

## 1. Overview
A Python CLI tool (`autorb`) that ingests an audio file and an optional Enhanced LRC lyrics file, processes it through ML models (stem separation, pitch-to-MIDI), and outputs a fully playable Rock Band 3 Xbox 360 CON file.

## 2. The End-to-End Pipeline
1. **Ingestion:** Parse input audio and `.lrc` text.
2. **Separation (Demucs):** Split audio into `drums`, `bass`, `vocals`, `other`.
3. **Audio Encoding:** Mix stems into a multi-channel `.ogg`, then prepend the Harmonix MOGG header to create `audio.mogg`.
4. **Transcription (Basic-Pitch / Librosa):** 
   - Extract a tempo map (BPM) and measure grid.
   - Transcribe stems into raw MIDI data.
   - Quantize notes to 5-lane Rock Band frets (Expert down to Easy).
5. **Vocal Alignment (WhisperX):** If LRC is provided, parse timestamps. If not, use WhisperX to transcribe and timestamp vocals. Map syllables to `PART VOCALS` MIDI pitches.
6. **Metadata & Assembly:** Generate `songs.dta` using user-provided CLI parameters (Artist, Title, Year, Genre).
7. **CON Packaging:** Pack `notes.mid`, `audio.mogg`, `songs.dta`, and a default album art `png` into an STFS (Xbox 360 CON) file.

## 3. Tooling & Environment
- **Python:** 3.11+
- **Core Libraries:** `click`, `demucs`, `whisperx`, `basic-pitch`, `librosa`, `mido`, `pydub`, `construct`.
- **System Requirements:** `ffmpeg` must be installed on the host.

## 4. MVP Scope
The MVP must successfully create a 1-instrument (Guitar) + Vocals CON file that loads into Rock Band 3. Auto-generation of full drum animations and venue lighting are out of scope for the MVP and should use static/default values in the MIDI.

