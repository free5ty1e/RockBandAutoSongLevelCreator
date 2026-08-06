# AutoRB Knowledge Base - Architecture & Pipeline

The AutoRB pipeline is an end-to-end automation system for converting raw audio and lyrics into playable Xbox 360 CON and PlayStation 4 PKG custom song packages. A planned `--build-clone-hero` flag (ROADMAP) will additionally export a Clone Hero-format song (`.chart`/`.mid` + audio) reusing the same chart and mix, without the Xbox 360 CON packaging or Rock Band count-in.

## Fresh-User Wheel Install (v0.0066)
Fresh users install only the wheel (no git clone). Known macOS/Linux pitfall: `python3 -m venv venv` can fail with `ensurepip ... non-zero exit status 1` — see the "Troubleshooting `python3 -m venv venv` failures" section in README.md and the GitHub release body (run `python3.12 -m ensurepip --upgrade` to see the real error; fixes: `unset PYTHONPATH PYTHONHOME`, verify `which python3.12`, or bootstrap pip with `--without-pip` + `get-pip.py`). The wheel enforces `Requires-Python >=3.11,<3.14` (Python 3.14 unsupported — WhisperX caps at `<3.14`).

## Pipeline Components

1.  **Audio Processing (`autorb.audio`)**:
    *   **Stem Separation**: Uses Meta's **Demucs** to isolate drums, bass, vocals, and instruments (`other`).
    *   **Tempo Detection**: Uses `librosa` to compute a tempo map (`tempo_map.json`).
    *   **Vocal Extraction**: Uses **WhisperX** for speech-to-text and alignment.
2.  **Transcription (`autorb.transcribe`)**:
    *   Converts pitch and transient audio into quantized MIDI (`.mid`) charts using signal processing and machine learning models.
3.  **Export & Packaging (`autorb.export`)**:
    *   **Asset Generation**: Generates `songs.dta` metadata, default album art (`_keep.png_xbox`), and milo assets.
    *   **CON Packaging**: Builds a fully compliant Xbox 360 STFS CON container using a verified template.
    *   **PS4 Packaging**: Leverages the vendored `ForgeTool` to convert the CON into a playable `.pkg` installer for PS4.
4.  **Tooling Integration**:
    *   The `ForgeTool` is built from vendored source within the `tools/libforge/` directory using .NET SDK 8 and Mono, ensuring full reproducibility within the development container.
    *   Pipeline supports automatic PKG generation via the `--build-pkg` flag.

## Key Detection (v0.0063) & Freestyle-Vocals Gating (v0.0067)
`autorb/export/key_detect.py` estimates the song's key from the Basic-Pitch vocal note events (`[start, end, midi_pitch, ...]`): it builds a pitch-class histogram weighted by note duration, rotates the Krumhansl-Schmuckler major/minor profiles, and returns the best-matching `(tonic_pitch_class, tonality)`. Values are 0-11 chromatic (0=C) and 0=major/1=minor. The CLI passes these to `generate_songs_dta()` which writes `(vocal_tonic_note N)` and `(song_tonality 0|1)` (RB3-side key metadata). The RB4 guide-lines feature is gated separately: the new `--generate-freestyle-vocals` flag makes `generate_songs_dta()` write `(freestyle_vocals 1)` into `songs.dta`, which the vendored `SongDataConverter` (patched in v0.0067) reads into the PS4 `songdta_ps4` `HasFreestyleVocals` bool (`SongDataWriter.cs:42`). Without the flag, `HasFreestyleVocals` is `false` and the game won't show freestyle guide lanes. See `rock_band_customs_domain.md`.

## Mandatory Count-In (v0.0064)
Rock Band charts must start with a silent pre-roll; content at tick 0 breaks sync and ForgeTool conversion. The pipeline now computes a 3-measure count-in from the song's opening beat-grid tempo (`midi_generator.count_in_params`), prepends that much silence to the 10-channel MOGG via ffmpeg `adelay` (`mogg_builder.build_mogg_from_stems(count_in_ms=...)`), and shifts the entire chart past it (`generate_vocal_midi(count_in_ticks=...)`, with `[prc_intro]`/`[music_start]` at the count-in end and a tick-0 tempo event so `MidiHelper`'s `idx--` doesn't crash). This fixes the ~1s audio-ahead-of-lyrics offset and keeps the first vocal phrase past ForgeTool's `StartTicks - 640` uint underflow (first phrase now at tick 6071). `--skip-mogg` disables the count-in so reused (un-shifted) audio stays in sync. See `vocal_alignment.md` / `forgetool_compat.md`.

## Supported Python Range (v0.0065)
The wheel declares `requires-python = ">=3.11,<3.14"`. Python 3.14 is NOT supported: current WhisperX releases cap at `<3.14`, and the only whisperx release without an upper bound (3.2.0) pins `ctranslate2==4.4.0`, which ships no Python 3.14 wheel. Without the upper bound, pip on 3.14 backtracked to whisperx 3.2.0 and failed with the cryptic `No matching distribution found for ctranslate2==4.4.0`; with it, pip refuses immediately and clearly. macOS's default `python3` is 3.9.6 (too old) — use `brew install python@3.12` and `python3.12`.

## Release Packaging: PEP 440 Wheel Filenames
The CI release job renames the built artifacts to carry the git tag. The old code appended the tag **after** the platform tag (`autorb-0.62-py3-none-any-v0.005xTest17.whl`), which pip rejects with `ERROR: Invalid build number` — macOS users could not install release wheels. The fix inserts the sanitized tag as a **PEP 440 local version** before the platform tag: `autorb-0.62+v0.005xTest17-py3-none-any.whl` (and `autorb-0.62+v0.005xTest17.tar.gz` for the sdist). Tag characters are sanitized with `${TAG//[^a-zA-Z0-9._-]/-}`. pip install instructions must use `python3`/`pip3` (macOS's default `python3` is 3.9.6, below the `>=3.11` requirement).
