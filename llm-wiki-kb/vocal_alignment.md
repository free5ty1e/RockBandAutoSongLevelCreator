# Vocal Alignment & LRC Processing

## Standard vs. Enhanced LRC
- **Standard LRC:** Provides line-level timestamps. Example: `[00:12.00] This is an open road song`
- **Enhanced LRC:** Provides word/syllable-level timestamps. Example: `[00:12.00] <00:12.00> This <00:12.20> is <00:12.40> an <00:12.60> o<00:12.70>pen <00:13.00> road <00:13.50> song`

## AutoRB's AI Alignment Strategy
Rock Band requires MIDI events for every spoken syllable so the in-game lyric tubes scroll correctly. Standard LRCs are insufficient. 

To solve this:
1. AutoRB ingests the user's Standard LRC (which provides the 100% accurate lyrics, avoiding AI hallucination on the text itself).
2. The pipeline extracts the `vocals.wav` stem.
3. A forced-alignment model (like WhisperX) listens to the vocal stem and maps precise start/end timings to the words provided in the Standard LRC.
4. This data is mapped to MIDI pitch notes on the `PART VOCALS` track.

## Placeholder Instrument Tracks (required for RB4)
The `.mid` chart emitted by `generate_vocal_midi()` also includes placeholder `PART DRUMS`, `PART GUITAR`, and `PART BASS` tracks (one note each at pitch 60, `PLACEHOLDER_NOTE_PITCH = 60`) even though the vocals pipeline does not chart real instruments. Rationale: `songs.dta` advertises drums/guitar/bass at rank 150, and RB4 (via ForgeTool PKG conversion) crashed when the vocal fretboard loaded if an advertised part had no corresponding MIDI track. Every instrument advertised in `songs.dta` must have a loadable chart track, even if it is just a placeholder. The MIDI header track count is 6: `BEAT`, `EVENTS`, `PART DRUMS`, `PART GUITAR`, `PART BASS`, `PART VOCALS`.
