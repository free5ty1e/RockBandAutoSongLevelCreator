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
4. This data is mapped to MIDI pitch notes on the `PART VOCALS` track. Each `synced_lyrics` entry now carries real `start`/`end` (from the word segments) and `pitch` (from the Basic-Pitch `note_events` in `vocals_cache.json`, nearest/containing-note lookup) — `step4_sync.py` emits these fields explicitly (v0.0061). Before that fix the entries only had `time`/`beat_time`, so `generate_vocal_midi()` fell back to `start=0.0`, `pitch=60` for every word and the entire 284-note chart was a blob at tick 0 (the "fretboard flashes then instant 0%" symptom).

## Placeholder Instrument Tracks (required for RB4)
The `.mid` chart emitted by `generate_vocal_midi()` also includes placeholder `PART DRUMS`, `PART GUITAR`, and `PART BASS` tracks even though the vocals pipeline does not chart real instruments. Rationale: `songs.dta` advertises drums/guitar/bass at rank 150, and RB4 (via ForgeTool PKG conversion) crashed when the vocal fretboard loaded if an advertised part had no corresponding MIDI track. Every instrument advertised in `songs.dta` must have a loadable chart track, even if it is just a placeholder. The MIDI header track count is now 7 (v0.0061), mirroring "311 - Down": track 0 = tempo map (named `song_id`, 4/4 + 120 BPM), then `PART DRUMS`, `PART GUITAR`, `PART BASS`, `PART VOCALS`, `EVENTS`, `BEAT`. The `EVENTS` track carries the mandatory text markers `[prc_intro]`, `[music_start]`, `[prc_verse_1]`, `[preview]`, `[prc_chorus_1]`, `[prc_outro]`, `[music_end]`, `[end]` and the `BEAT` track carries one quarter-note marker per beat (pitch 12 downbeat vel 101, pitch 13 vel 100, 480-tick spacing).

Each placeholder track (`build_placeholder_track()` in `midi_generator.py`) emits one note per difficulty using `PLACEHOLDER_DIFFICULTY_PITCHES = (60, 72, 84, 96)` — EasyStart=60, MediumStart=72, HardStart=84, ExpertStart=96, matching the difficulty start keys in LibForge's `RBMidConverter.cs`. This is mandatory: `RBMidConverter` (`HandleDrumTrk` / `HandleGuitarBass`) stores `gem_tracks` as a 4-element difficulty array (Easy/Medium/Hard/Expert) that is filled lazily only when a note for that difficulty is seen, then runs `gem_tracks.Select(g => g.ToArray()).ToArray()` (RBMidConverter.cs:606 and :975). A single note at pitch 60 filled only the Easy slot, leaving Medium/Hard/Expert null and throwing `System.NullReferenceException` during ForgeTool "CON to PKG Conversion" (fixed in v0.0057).
