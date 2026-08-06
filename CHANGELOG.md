# Changelog

All notable changes to AutoRB will be documented in this file.

## [0.0069] - 2026-08-06
- **MOGG: all 10 channels now carry audio (fixes the silent PS4 song-list preview).** Binary analysis of the reference "311 - Down" DLC proved every channel of its MOGG is non-silent (kick/snare ch0/1 are its LOUDEST channels, ~3500 RMS; ch9 fake/crowd ~50 RMS). Our MOGG had forced ch0/1 (kick/snare) and ch9 to `volume=0` digital silence, so any preview mixdown that uses the front stereo pair (or channels the game picks up for the library preview) was completely silent even though the chart, `songs.dta` preview window, OggMap, and rbmid `PreviewStartMillis` were all verified correct. `mogg_builder.py` now sends the full drum kit to ch0/1 and a low-level backing ambience to ch9, mirroring 311 Down's channel loudness. Verified: the rebuilt MOGG has RMS 433/521/171 on ch0/1/9 (vs 0.0 before), the OggMap entries still decode to their claimed samples (64/64 sampled), and both the dta preview (50.636s) and MIDI `[preview]` (54.458s) seek windows land in loud music (RMS > 1500).
- **Full CON-internal verification (documents where the remaining issues live).** Parsed the shipped CON's `rbmid_ps4` end-to-end (all 55,411 bytes, 0 remaining): first vocal note tick 6071 ↔ `StartMillis` 5037.445ms, `PreviewStartMillis` 54457.59, `PreviewEndMillis` 84457.59, 391 tempo events whose tick→time map reproduces every note time exactly, `FinalEventTick` 274900, 284 vocal notes, 24 freestyle regions. The CON's MOGG is byte-identical (md5 `aa5765806d645ce8bfa629b74f0afbd9`) to `output/open_road_song.mogg` and the PKG's copy. The `(preview ...)`/`(song_length ...)` units in `songs.dta` are confirmed **milliseconds** per the RB3 authoring guide and corroborated by 311 Down (`(preview 32178 62178)` = 32.178s lands in loud audio; 0.73s is ~87 dB quieter). Consequence: the ~1s audio-before-notes offset the user still sees on PS4 is **not reproducible from the files** (every timing layer agrees within ~30ms and the count-in plays normally in-game) and the v0.0064 count-in hypothesis is now disproven — the remaining suspects are game-side (chart-init delay, likely related to the 391-event dense tempo map vs ~69 in stock).
- **New regression test:** `tests/test_mogg.py` builds a real 10-channel MOGG from synthetic stems with ffmpeg and asserts every channel carries audio (rms > 50 after the first 20%) so a future "forced silent channel" change is caught. Full suite: 27 passed.

## [0.0068] - 2026-08-06
- **Vocal onset snapping (fixes late words).** WhisperX word boundaries arrive systematically LATE (median ~80ms, tail up to ~400ms), so every word's start is now snapped to the nearest Basic-Pitch vocal-stem onset within a 0.45s-before/0.05s-after window — constrained to never snap more than 0.30s, and never back into the previous word's sung region (Basic-Pitch often merges a fast following word, e.g. "Tonight I", into one sustained note). Word ends extend across all notes that begin inside the word's own span so multi-syllable words keep their full sung window without stealing the next word's region. `synced_track.json` regenerated; the rebuilt chart's first vocal note (tick 6071 → 5.037s) lands within 7ms of the MOGG's first vocal energy peak (5.03s) and median stem-onset lag improved 60→55ms (p90 347→336ms).
- **Max-overlap vocal pitch selection.** `pitch_at` previously returned the weighted-median pitch, which let a spurious neighbour note sitting near the window centre drag the reading off the true sung note. It now picks the note with the largest overlap over the word's window — the sustained note wins over brief harmonics/echo bleed on Demucs stems. Pyin agreement improved 83% → 86% (125/149 → 139/160 words), octave-level errors (>4 st) down 15 → 11.
- **Pyin octave guard.** Words cached from a run that generated `vocals_cache.json` now carry per-word `pyin_pitch`/`pyin_confidence` (librosa pyin, C2..C6, voiced mask prob > 0.6), computed by the new `_annotate_pyin_pitches()` in `vocals.py`. When pyin is genuinely confident (≥ 0.8) and disagrees with Basic-Pitch by more than 4 semitones, the pyin reading overrides — fixing the octave-flipped words while leaving ambiguous stem artifacts (where both estimators themselves flip) untouched. All pitches stay clamped to the C2..C6 vocal range.
- **Feature Support Matrix in README.** Documents exactly where ForgeTool-gated features work: CON generation/stems/tempo/vocals/difficulty/count-in/MOGG/songs.dta everywhere; `--build-pkg` and the PS4 freestyle-vocals guide lines only on a git checkout or devcontainer (ForgeTool is vendored source-only, rebuilt by `tools/build_forgetool.sh`; the wheel ships no ForgeTool and `--generate-freestyle-vocals` is a no-op for PS4 on a bare wheel).
- **Tests:** new `tests/test_sync.py` (9 tests) covers onset snapping (nearest-onset, prev-word rejection, max-shift cap, end extension), max-overlap pitch selection, the pyin guard's confidence and disagreement thresholds, the octave correction, and vocal-range clamping. Full suite: 26 passed. CON `stfs_validator.py` VALID; rebuilt PKG's `songdta_ps4` still reports `HasFreestyleVocals=1`.

## [0.0067] - 2026-08-05
- **`--generate-freestyle-vocals`: RB4 freestyle guide lines, root cause found.** The PS4 test showed the "diatonic guide lines" (Hard/Expert vocals) never rendered. Research disproved the old theory that `(vocal_tonic_note N)` + `(song_tonality 0|1)` in `songs.dta` enable them: the PS4 `songdta_ps4` binary format has **no slot** for those fields, and `SongDataConverter.ToSongData` silently drops them (they're RB3-only metadata). The RB4 manual confirms the guide lines are the **Freestyle Vocals** feature, gated **per-song** ("available for songs that support it, as indicated in the Music Library"), and the `songdta_ps4` binary carries the `HasFreestyleVocals` bool for exactly that. Upstream ForgeTool hardcoded it to `false`, so no ForgeTool-converted custom ever advertised freestyle support.
- **Patched the vendored ForgeTool** (`tools/libforge/.../SongDataConverter.cs`): `HasFreestyleVocals = songDta.Array("freestyle_vocals")?.Int(1) == 1`. The new `--generate-freestyle-vocals` CLI flag makes `generate_songs_dta()` write `(freestyle_vocals 1)` into `songs.dta`; without it the field is omitted and the flag stays `false`. Once enabled, the game itself computes the guide scale from the charted vocal notes (root/3rd/5th interval shading per Harmonix patent US 2010/0304810).
- **Patched ForgeTool propagates automatically.** ForgeTool is vendored as **source** and rebuilt on every fresh devcontainer (`.devcontainer/post-install.sh` → `tools/build_forgetool.sh`); the wheel never ships ForgeTool binaries (`--build-pkg` requires a git clone), so any fresh clone of the tag gets the patched source too. No binary distribution needed.
- **Verified end-to-end:** regenerated the CON/PKG with the flag and parsed the built `songdta_ps4` — `HasFreestyleVocals=1` with the flag (was `0` on the pre-patch artifact), `0` when the flag is omitted; CON `stfs_validator.py` VALID; new `tests/test_dta_writer.py` covers flag written/omitted. Full suite: 17 passed.
- **Wiki correction:** `rock_band_customs_domain.md`, `architecture.md`, `vocal_alignment.md`, and `forgetool_compat.md` now document the real mechanism and mark the `vocal_tonic_note`/`song_tonality` guide-line theory as disproven for PS4.

## [0.0066] - 2026-08-05
- **README + GitHub Release install troubleshooting.** Added a "Troubleshooting `python3 -m venv venv` failures (macOS/Linux)" section to both the README and the CI/CD release body covering the `ensurepip` `non-zero exit status 1` failure seen by a fresh user (who successfully installed the wheel after following it): run `python3.12 -m ensurepip --upgrade` to see the real error, then (1) `unset PYTHONPATH PYTHONHOME` and recreate the venv, (2) confirm `which python3.12` is the Homebrew/pyenv build you expect, or (3) bootstrap pip manually with `python3.12 -m venv --without-pip venv` + `get-pip.py`. Also deduplicated the duplicated "Installing from this release" / "Finding Lyrics" sections in the release body.
- **ROADMAP: new `--build-clone-hero` feature.** Added a planned CLI flag to also build/output a Clone Hero-format song (`.chart`/`.mid` + audio) alongside the Rock Band CON, reusing the same generated chart and audio mix without the Xbox 360 CON packaging or Rock Band count-in.

## [0.0065] - 2026-08-05
- **Install fix: enforce `Requires-Python >=3.11,<3.14` on the wheel.** Python 3.14 is not supported: the current WhisperX releases cap at `<3.14`, and the only whisperx without an upper bound (3.2.0) pins `ctranslate2==4.4.0`, which ships no Python 3.14 wheel — so `pip install autorb` on 3.14 previously died with the cryptic `No matching distribution found for ctranslate2==4.4.0` after a long resolution. The wheel now declares `requires-python = ">=3.11,<3.14"` so pip refuses immediately with a clear message, and the README documents why 3.14 is excluded.

## [0.0064] - 2026-08-05
- **Mandatory count-in (fixes the ~1s audio-ahead-of-lyrics offset and the ForgeTool phrase underflow).** `mogg_builder.py` now prepends a silent count-in to the 10-channel MOGG via ffmpeg `adelay` (sized from the song's opening beat-grid tempo: 3 measures = 12 beats; Eve 6 "Open Road Song" gets 4458 ms / 5760 ticks), and `midi_generator.py` shifts the whole chart past it (`count_in_ticks`), placing `[prc_intro]`/`[music_start]` at the end of the count-in like stock RB3 DLC (311 - Down has `[music_start]` at 5280 with ~5s of MOGG lead-in). This eliminates the constant ~1s audio-vs-lyrics offset by giving the game a real pre-roll, and moves the first vocal phrase to tick 6071 so ForgeTool's `RBMidConverter.cs` `e.StartTicks - 640` (line 1286) no longer underflows a `uint` to 4294966967 — the old first phrase at tick 311 wrapped to a ~198s StartMillis with a negative length, which is what made the vocal guide show a broken first phrase. Placeholder DRUM/BASS/GUITAR notes also move to the count-in end so no gems land in the lead-in silence.
- **`--skip-mogg` disables the count-in** so a chart rebuilt against a reused (un-shifted) `.mogg` doesn't desync from its audio.
- Rebuilt `output/open_road_song.{con,mogg,mid}` and the PS4 PKG (song_length 202547 ms incl. count-in; preview 50636→80636). `stfs_validator.py` VALID; ForgeTool CON→PKG conversion succeeds; `pytest` 15 passed (incl. new `test_count_in_shifts_chart_and_fixes_underflow` and `test_no_count_in_when_beat_grid_missing`).

## [0.0063] - 2026-08-05
- **Dynamic tempo map from the beat grid (fixes progressive lyric drift).** `midi_generator.py` no longer writes a single averaged BPM into the MIDI tempo track. When the beat-tracked grid (`beat_times`/`bpms` from `tempo_map.json`) is available, it emits a **dynamic tempo map** — one `set_tempo` event per beat interval, mirroring stock RB3 charts like "311 - Down" that change tempo every ~2 bars — and derives every note/beat tick from the real beat grid (tick 480*i == `beat_times[i]`). A virtual beat at t=0 anchors tick 0 to audio sample 0 (the tracker starts at ~0.9s, which previously shifted the whole chart early by a constant lead-in). Result: word start/end ticks round-trip to their original audio timestamps within **1.3 ms** across the whole 192 s song (was: unbounded progressive drift from the jittery 534-value average). Also fixed the BEAT track length, which hardcoded 120 BPM (`song_length_ms / 1000 * 2`) and so did not even cover the song at 169 BPM.
- **Automatic vocal key detection (`vocal_tonic_note` / `song_tonality`).** New `autorb/export/key_detect.py` runs Krumhansl-Schmuckler key-finding over the Basic-Pitch vocal note events (pitch classes weighted by note duration) and emits a real tonic pitch class (0-11, 0=C) plus tonality (0=major, 1=minor) into `songs.dta` instead of the hardcoded `(vocal_tonic_note 4) (song_tonality 0)`. This is the metadata enabler for Rock Band 3/4's "Acceptable Pitch" key guide lines on Hard/Expert vocals: with a correct tonic + tonality the game can draw diatonic guide lanes that let players freestyle-harmonize in any compatible key. Note the C3 authoring guide's "0=C, 1=D, no sharps or flats" wording is a simplification — real RB3DX DTA files use chromatic values 0-11 (e.g. `vocal_tonic_note 11` for B). Verified against the Eve 6 "Open Road Song" vocal data: detects A major (tonic 9, tonality 0).
- **Fixed the release wheel filename.** The CI release job appended the git tag *after* the platform tag (`autorb-0.62-py3-none-any-v0.005xTest17.whl`), which pip rejects with `ERROR: Invalid build number`. The job now inserts the sanitized tag as a PEP 440 local version *before* the platform tag (`autorb-0.62+v0.005xTest17-py3-none-any.whl`), so `pip3 install ./autorb-*.whl` works from the GitHub Release.
- **Fixed the CI workflow YAML** — a mis-indented `3. Run:` line in the release body block scalar broke GitHub's workflow parser and blocked all CI runs (PR + release).
- **Documentation:** README and release-body install/run instructions now use `python3`/`pip3` consistently (macOS's default `python3` is 3.9.6 and won't satisfy the `>=3.11` requirement; the venv sanity check catches a stale-Python venv).
- **Tests:** new `tests/test_key_detect.py` covers major/minor key detection and the empty-input fallback. Full suite: 11 passed.

## [0.0062] - 2026-08-04
- **Vocal phrase markers now align to 2-measure windows on the beat grid.** `midi_generator.py` groups words by their position in the song's meter (4/4 at 120 BPM, 480 ticks/beat => 1920 ticks/measure, 3840 ticks/phrase) rather than by detecting pauses > 1.5 s in the lyrics. This matches Rock Band's convention: every phrase is a fixed 2 bars of the beat grid, so the in-game vocal HUD shows phrase boundaries at musically correct positions. The function accepts `phrase_measures` (default 2) for 2-bar or 4-bar phrasing.
- **Version and packaging consistency fix (v0.1.0 → 0.0062).** The wheel filename was previously `autorb-0.1.0-...` because pyproject.toml had `version = "0.1.0"` while the source code and changelog used `0.00XX` — the two never matched. `pyproject.toml` now declares `version = "0.0062"` (setuptools normalizes the wheel filename to `autorb-0.62-py3-none-any.whl` per PEP 440). The README's `git tag` example now points to `v0.0062` and documents the tag-version link. `autorb/version.py` and `CHANGELOG.md` are kept in sync at `0.0062`.
- **Wheel now ships template assets (`template.con`, `template_milo.bin`, `template_png.bin`).** `[tool.setuptools.package-data]` was added so `autorb/export/data/*.{con,bin}` are included in the wheel — without them `con_packer.py` raises `FileNotFoundError` on every run. A `MANIFEST.in` ensures the sdist also includes these files and the vendored ForgeTool source.
- **Wheel now ships the ForgeTool binary + all runtime DLLs** so `--build-pkg` works from a pip install without needing to clone the repo. `pyproject.toml` data-files install `tools/forgetool` + `tools/libforge/*.dll` to `{sys.prefix}/tools/`. `con_packer.py:build_ps4_pkg()` now resolves ForgeTool via `_find_forgetool()` (checks CWD, `sys.prefix`, `sys.base_prefix`), and the `forgetool` wrapper script handles both the flat wheel layout (`libforge/ForgeTool.exe`) and the git-clone layout (`libforge/LibForge/ForgeTool/bin/Release/ForgeTool.exe`).
- **Revised CI/CD release body and README installation instructions.** Release notes now recommend `git clone` as the primary path and clearly document what the pip wheel install requires (Python 3.11+, FFmpeg, mono for `--build-pkg`). Fixed the stale "PyInstaller executable" reference in README CI/CD section to say "source distribution and wheel."
- **New tests for vocal phrase markers** (`tests/test_vocal_midi.py`): verifies phrase starts (pitch 105) appear once per 3840-tick window and that phrase ends precede each new phrase start. Full suite: 8 passed.
- Pipeline: Added `--build-pkg` flag to CLI for automated PS4 PKG generation via vendored `ForgeTool`.
- Pipeline: Integrated vendored `ForgeTool` (LibForge) for reliable CON-to-PKG conversion on Linux.
- Devcontainer: Baked in Mono + .NET SDK 8 build environment for reproducible toolchain.

## [0.0061] - 2026-08-02
- **Fixed the vocal chart timeline (root cause of "fretboard flashes then instant 0%")**. `autorb/audio/step4_sync.py` wrote synced word entries under `time`/`beat_time` but without `start`/`end`/`pitch`, so `generate_vocal_midi()` fell back to `start=0.0`, `pitch=60` for every word — the entire 284-note PART VOCALS chart was a blob at tick 0. `step4_sync.py` now emits real `start`/`end` (from `word_segments`) and a `pitch` (from the Basic-Pitch `note_events` in `vocals_cache.json` via nearest/containing-note lookup). The rebuilt chart spans 0.61s → 190.2s with pitches 50-83.
- **Added the mandatory Rock Band EVENTS markers** to the chart MIDI. `midi_generator.py` now emits `[prc_intro]`, `[music_start]`, `[prc_verse_1]`, `[preview]` (tick 48000 / 50s), `[prc_chorus_1]`, `[prc_outro]`, `[music_end]`, and `[end]` (the final event) in the EVENTS track, mirroring the proven-good "311 - Down" reference (which has `[music_start]` at 5280, `[preview]` at 22800, `[music_end]` at 123360, `[end]` at 125759). The missing `[preview]` marker explains the absent song-list preview; missing `[music_end]`/`[end]` makes the game finish the song instantly at 0%.
- **Added a real BEAT track**. 311's BEAT track carries one quarter-note marker per beat (pitch 12 downbeat vel 101, pitch 13 other beats vel 100); our chart previously had zero beat notes and placed the tempo map in a named BEAT track with no markers. The MIDI is now structured exactly like 311: track 0 = tempo map (name = song id, 4/4 + 120 BPM), then PART DRUMS/BASS/GUITAR/VOCALS, EVENTS, BEAT (385 beats over 192s).
- **Album art v2**: "CHRIS PRIME" now renders on two lines (narrower title) with an orange rounded **"BOT"** badge in the top-right corner (`autorb/export/album_art.py`).
- **Difficulty rewrite** (`autorb/export/difficulty.py`): replaced the linear `density * factor` model (which put every instrument in the level-1 band) with per-instrument note-density bands mapped to difficulty levels 1-6, emitting each level band's midpoint rank. Calibrated to 311 (30.2/18.9/9.9/3.35 nps → drums 5, guitar 4, bass 3, vocals 2) and `band = hardest charted instrument`. Our chart now reports vocals 159 / band 188 (2 of 6) instead of everything 1 of 6; drums/guitar/bass stay level 1 (placeholder single notes).
- Verified with mido: PART VOCALS 284 notes spanning 585→182578 ticks, EVENTS 8 markers ending `[end]` at 187273, BEAT 385 notes at 480-tick spacing. Rebuilt `output/open_road_song.con` (vocals 159, band 188, art v2, new MIDI). `stfs_validator.py` VALID, `pytest` 6 passed.

## [0.0060] - 2026-08-02
- Added **automatic per-instrument difficulty ratings**. `autorb/export/difficulty.py` parses the chart MIDI (with a running-status-aware SMF parser that also tolerates the truncated final events present in RB3 charts) and converts per-second note density into `(rank ...)` values. The linear factors (drum 10, guitar 13, bass 22, vocals 43 nps^-1) are calibrated against the "311 - Down" DLC reference (311/250/225/144/233), which the calculator reproduces as 302/246/218/144/228. `dta_writer.py` no longer hardcodes `(rank ... 150 ...)` — every song was rendering as difficulty 1 of 6.
- Added **custom album art support** via the new `--album-art PATH` CLI flag (PNG/JPG). `autorb/export/texture.py` reverse-engineers the `_keep.png_xbox` format (32-byte HMXBitmap header + S3TC DXT payload with Xbox 360 16-bit word swap) and implements DXT1/DXT5 block encoders/decoders matching SuperFreq `png2tex --platform x360` output (verified by decoding the SmellsLikeNirvana template's DXT5 texture and a SuperFreq-produced reference). `autorb/export/album_art.py` renders the default generic "Chris Prime Custom" 256x256 cover (flattened to opaque so it encodes as compact DXT1). `con_packer.py` accepts `album_art_bytes` and stages it as `{song_id}_keep.png_xbox`.
- New tests: `tests/test_texture_and_difficulty.py` covers DXT1 round-trips, default art validity, and rank computation from chart density. Full suite: 6 passed.
- Rebuilt `output/open_road_song.con` (dta now carries computed ranks, CON carries the new default album art). `stfs_validator.py` reports VALID. Awaiting the user's next RB4DX/ForgeTool test of the in-game audio issue.

## [0.0059] - 2026-08-02
- Rebuilt the MOGG to mirror the proven-working **"311 - Down"** DLC structure. Two consecutive builds (0.0055, 0.0058) fixed the CON packaging, MIDI placeholders, MOGG container, and Ogg page sizing, yet RB4 (via ForgeTool PKG conversion on the user's PS4/RB4DX) still showed **no audio preview** and **instant 0% completion**. Research surfaced `maxton/LibForge#30` ("Mismatching audio track and instruments"), which documents that a track/channel layout that does not match the physical MOGG makes songs start but **stop playing after a few seconds in-game** — our symptom's failure family. The remaining structural difference vs. the known-good 311 mogg was the channel layout (8ch vs 10ch) and the `songs.dta` track/pan/vol/core assignment.
- `mogg_builder.py`: `build_mogg_from_stems()` now builds a **10-channel** MOGG when the 4 standard stems (drums/bass/other/vocals) are present, matching 311's exact layout — ch0-1 silent mix1 kick/snare tracks, ch2-3 stereo drum kit, ch4 mono bass, ch5-6 stereo guitar/backing (`other`), ch7-8 stereo vocals, ch9 silent fake/crowd (the engine falls back to procedural crowd). A generic per-stem stereo merge is retained as a fallback for non-standard stem counts.
- `dta_writer.py`: `generate_songs_dta()` now declares the 311-compatible structure `(tracks ((drum (0 1 2 3)) (bass (4)) (guitar (5 6)) (vocals (7 8))))` with 10-entry `pans`/`vols`/`cores` (guitar channels cored), plus the 311 metadata fields `drum_solo`/`drum_freestyle` seqs, `band_fail_cue`, `solo (vocal_percussion)`, `short_version`, `vocal_tonic_note`, `song_tonality`, and `real_guitar`/`real_bass` ranks. `vocal_parts` stays 1 (our chart is single vocalist). ForgeTool's `MakeMoggDta` therefore emits the identical track list as 311: `drum (0) drum (1) drum (2 3) bass (4) guitar (5 6) vocals (7 8) fake (9)`.
- Verified: the 10ch Ogg decodes cleanly with **Tremor** (integer-only `libvorbisidec`, same decoder family as RB4's Milkshake engine): 0 decode errors across 8,735,744 frames. `stfs_validator.py` VALID, `forge_simulator.py` SUCCESS, `pytest` passes (1 passed). The seek table / small-page changes from 0.0055/0.0058 are retained.
- Rebuilt `output/open_road_song.con` (12956766-byte MOGG). Next test (user): ForgeTool CON→PKG → install → verify (1) song-list audio preview and (2) playback to completion instead of instant 0% finish.

## [0.0058] - 2026-08-02
- Fixed in-game RB4 audio playback: the CON converted and installed (RB4DX + ForgeTool) but the song had **no audio preview in the song list** and **completed instantly at 0%** when played. Root cause: the MOGG's embedded Ogg stream used ffmpeg's default libvorbis paging (~1-second / ~56KB pages, granule deltas ~31000-36000 samples). Rock Band's Milkshake audio engine cannot reliably decode such coarse pages. Known-good stock moggs (e.g. "311 - Down" RB3 DLC) use ~4KB pages with ~2048-3072 sample granules (4006 pages for the full song).
- `mogg_builder.py`: added `PAGE_DURATION_US = 40000` and passed `-page_duration str(PAGE_DURATION_US)` to the ffmpeg libvorbis encode command in `build_mogg_from_stems()`, forcing the Ogg muxer to emit small ~4KB pages (~2048-3072 sample granules) that Milkshake can decode.
- `mogg_builder.py`: added `read_mogg_duration_ms(mogg_path)` which parses the MOGG `header_size`, locates the Vorbis identification header's sample rate and the final audio granule, and returns the integer duration in milliseconds.
- `dta_writer.py`: `generate_songs_dta()` now accepts an optional `song_length` param; if not given, it derives the value from the MOGG at `output_dir/{song_id}.mogg` via `read_mogg_duration_ms()` (falls back to 198089 ms with a warning if the MOGG is absent). Removed the hardcoded `(song_length 230162)` line; the generator now emits `(song_length {song_length})`.
- Rebuilt `output/open_road_song.con` (14966784 bytes) with the fixed MOGG (4233 pages, avg 3414 bytes/page, granule deltas 2048/2624) and songs.dta with `(song_length 198089)`. `stfs_validator.py` reports VALID, `forge_simulator.py` SUCCESS, `pytest` passes (1 passed).

## [0.0057] - 2026-08-02
- Fixed ForgeTool "CON to PKG Conversion" crash (`System.NullReferenceException` at `LibForge.Midi.RBMidConverter.MidiConverter.<>c.<HandleDrumTrk>b__65_9` / `HandleGuitarBass`) introduced by v0.0056. Root cause: `RBMidConverter` builds per-difficulty `gem_tracks` as a 4-element array (Easy/Medium/Hard/Expert) that is filled lazily — only when a note for that difficulty is seen — so the v0.0056 placeholder (a single note at pitch 60) left 3 slots null and `gem_tracks.Select(g => g.ToArray()).ToArray()` (RBMidConverter.cs:606 and :975) threw the NRE.
- `midi_generator.py`: `build_placeholder_track()` now emits one note on **each** difficulty (60/72/84/96 = EasyStart/MediumStart/HardStart/ExpertStart from RBMidConverter.cs) per track, so all four `gem_tracks` slots are non-null and ForgeTool conversion no longer NREs. Added `PLACEHOLDER_DIFFICULTY_PITCHES = (60, 72, 84, 96)` (replaces the single `PLACEHOLDER_NOTE_PITCH = 60` approach).
- Rebuilt `output/open_road_song.con` (14860288 bytes) with the regenerated 6-track MIDI (staged at `output/songs/open_road_song/open_road_song.mid`, 5030 bytes; PART DRUMS/GUITAR/BASS each contain notes at keys [60, 72, 84, 96], PART VOCALS unchanged at 284 notes). `stfs_validator.py` reports VALID, `forge_simulator.py` SUCCESS, `pytest` passes (1 passed).

## [0.0056] - 2026-08-02
- Fixed RB4 (via ForgeTool PKG conversion) crashing when the vocal fretboard loaded. Working hypothesis: `songs.dta` advertises drums/guitar/bass at rank 150 but the chart contained only `PART VOCALS`, so RB4 had no MIDI track to load for the advertised parts.
- `midi_generator.py`: `generate_vocal_midi()` now emits placeholder `PART DRUMS`, `PART GUITAR`, and `PART BASS` MIDI tracks (one note each at pitch 60) in addition to the existing `BEAT`, `EVENTS`, and `PART VOCALS` tracks, so every instrument advertised in `songs.dta` has a corresponding chart track. Header track count bumped from 3 to 6.
- `midi_generator.py`: added module-level `build_track()` (moved out of the closure) and `build_placeholder_track()` helpers, plus `PLACEHOLDER_NOTE_PITCH = 60`.
- Rebuilt `output/open_road_song.con` (14860288 bytes) with the new 6-track MIDI (staged at `output/songs/open_road_song/open_road_song.mid`, 4958 bytes, verified: BEAT, EVENTS, PART DRUMS=1 note, PART GUITAR=1 note, PART BASS=1 note, PART VOCALS=284 notes). `stfs_validator.py` reports VALID, `forge_simulator.py` SUCCESS, `pytest` passes (1 passed).

## [0.0055] - 2026-08-02
- Fixed in-game RB4 audio: the built `.mogg` was a **plain multi-channel Ogg Vorbis file** (`OggS...`), not the proprietary Harmonix MOGG container. LibForge copies the mogg verbatim into the PS4 PKG, so RB4 could not decode it — no audio preview in the song list, and a crash (CE-34878-0) when the notes/fretboard came up (audio engine fails to start). The template's real mogg (v13) confirms the proprietary header (`version 0x0A` unencrypted for RB4 customs).
- `mogg_builder.py`: added `wrap_ogg_as_mogg()` which prepends the v10 MOGG header (LE `version=0x0A`, `header_size`, `map_version=0x10`, `seek_interval=20000`, `entry_count`) and an OggMap of `(byte_offset, sample)` seek entries computed by parsing the Ogg pages (granulepos per page, 0x8000-byte stepping, mirroring mtolly/ogg2mogg). The Ogg payload is byte-identical after the header.
- `mogg_builder.py`: each stem is now normalized to a stereo pair (`aformat=channel_layouts=stereo`) before `amerge`, guaranteeing the 8-channel layout songs.dta expects (drums 0-1, bass 2-3, guitar 4-5, vocals 6-7) even with mono stems.
- Rebuilt `output/open_road_song.mogg` (v10, 8ch @ 44100) and `output/open_road_song.con`; all 5 payloads still byte-identical under the GameArchives per-block read, and the served mogg parses as a valid v10 MOGG. Validator, simulator, and pytest pass.

## [0.0054] - 2026-08-02
- Fixed the real root cause of the ForgeTool "CON to PKG Conversion" crash. STFS hash tables are interleaved every 0xAA logical blocks, so a file's physical blocks are **not contiguous** (logical block `L` maps to `0xC000 + logical_to_physical(L) * 0x1000`, with a hash-table block between each group of 170). The previous code read/wrote payloads **contiguously** from the first physical block, which corrupted any file crossing a 170-block boundary.
- `con_packer.py`: added `read_file_blocks()` and rewrote `write_payload()` to resolve **each logical block** through `logical_to_physical()`. Previously the milo (logical 3551-3570, crossing the boundary at 3570) had its last block written over a hash-table slot and read back from the wrong physical block (template zeros) -> no trailing `0xADDEADDE` -> `ReadBytes(-1)` overflow in `MiloFile.ParseDirectory`.
- Fixed template `.milo_xbox` / `_keep.png_xbox` extraction to read block-by-block: the contiguous read was pulling the template's interleaved hash-table block into milo block 12 (and misplacing the last block). The extracted milo is now the true, unmodified template milo (81894 bytes), which already terminates entries correctly.
- Updated `stfs_validator.py` and `forge_simulator.py` bounds checks to use the last logical block's physical offset (interleave-aware).
- Verified: a faithful replication of GameArchives `STFSFileStream.Read` (per-block `BlockToOffset`) now serves **all 5 payloads byte-identical** to the staged files, and the served milo parses under a replication of LibForge 0.1.19 `ReadFromStream` -> `ParseDirectory` (all `0xADDEADDE` markers found). Validator, simulator, and pytest pass.

## [0.0053] - 2026-08-02
- Added `_libforge_milo_parseable()` guard in `con_packer.py`: every staged `.milo_xbox` is validated against a faithful replication of LibForge 0.1.19 `MiloFile.ReadFromStream` -> `ParseDirectory` (all `0xADDEADDE` entry terminators present) before the CON is written. An unparseable milo now raises `RuntimeError` instead of silently producing a CON that crashes ForgeTool's "CON to PKG Conversion" with `OverflowException` in `ReadBytes(-1)`.
- Rebuilt `output/open_road_song.con`; verified via validator, forge_simulator, pytest, and byte-checks.

## [0.0052] - 2026-08-02
- Fixed ForgeTool "CON to PKG Conversion" crash (`System.OverflowException: Array dimensions exceeded supported range` in `LibForge.Milo.MiloFile.ParseDirectory` / `StreamExtensions.ReadBytes(-1)`). The staged `gen/*.milo_xbox` (extracted from the `SmellsLikeNirvana_rb3con` template) is an RBN v28 milo whose `CharLipSync "song.lipsync"` payload runs to the end of the block region with no trailing `0xADDEADDE` padding marker, so LibForge's entry-size scan (`FindNext`) returns `-1`.
- Added `repair_milo()` in `con_packer.py`: for MILO_A (uncompressed) milos whose final block's data does not end in the `0xADDEADDE` terminator, it appends the marker to the file and grows the last block's size field so the marker falls inside the block region LibForge copies. CharLipSync data itself is byte-identical; the marker only supplies the missing format terminator, so in-game lipsync is unchanged.
- Verified end-to-end: a Python replication of LibForge's `MiloFile.ReadFromStream` -> `ParseDirectory` -> `CharLipSync.FromStream` now parses the rebuilt CON's milo (version 1/2, 36 visemes, 6749 keyframes); `stfs_validator.py`, `forge_simulator.py`, and all 5 payload byte-checks pass.

## [0.0051] - 2026-08-02
- Fixed STFS CON block addressing in `con_packer.py`: readers resolve file-table `start` as a *logical* block whose physical offset is `0xC000 + logical_to_physical(start) * 0x1000`, where `logical_to_physical` uses the arkem/free60 formula (hash tables interleaved every 0xAA logical blocks). Previously payloads were written at `0xD000 + start * 0x1000`, so ForgeTool read `songs.dta` from the file-table block itself, producing `Element at index 0 is not an Array. It is DataSymbol`. Data is now allocated starting at logical block 1 (block 0 is the file table).
- Corrected `.milo_xbox` / `_keep.png_xbox` extraction from the `SmellsLikeNirvana_rb3con` template to use the physical mapping (0x4AD000 / 0x4C2000) instead of `0xD000 + start * 0x1000`, fixing bogus graphic assets in the staged `gen/` folder.
- Patched STFS volume descriptor `Total Allocated Block Count` (be32 at `0x395` = file table + data blocks) and `Total Unallocated Block Count` (be32 at `0x399`) to match the rebuilt package size.
- Updated `stfs_validator.py`, `forge_simulator.py`, and `devscripts/analyze_cons.py` to use the correct logical-to-physical mapping, and added payload placement checks to the validator (out-of-bounds / zeroed payload detection).

## [0.0050] - 2026-08-02
- Implemented fully contiguous block allocation and extraction for ALL CON assets (`songs.dta`, `.mid`, `.mogg`, `.milo_xbox`, `_keep.png_xbox`) in `con_packer.py`, preventing large `.mogg` files (e.g. 14.5 MB) from overlapping and corrupting `.milo_xbox` and `.png_xbox` graphic assets.

## [0.0049] - 2026-08-02
- Fixed MIDI generator (`midi_generator.py`) to correctly extract `"synced_lyrics"` from synchronized track data instead of `"synced_words"`, producing a fully populated 4.8 KB MIDI chart with all 284 lyric/note events instead of a 113-byte stub.
- Aligned `songs.dta` generator (`dta_writer.py`) with concise single-line property format matching known-good working CON packages (`311 - Down`), preventing DTA symbol/array parsing errors.

## [0.0048] - 2026-07-31
- Implemented contiguous block allocation (`set_entry_allocation` and `write_payload` in `con_packer.py`) starting at block 0 for `songs.dta`, followed contiguously by `.mid` and `.mogg`, ensuring correct block start indexing and preventing misaligned file reads.

## [0.0047] - 2026-07-31
- Added STFS header metadata patching (`patch_stfs_header_metadata` in `con_packer.py`) to dynamically update package title and artist strings in the STFS header block (UTF-16-BE at offsets `0x43D` and `0x413`), preventing NullReferenceExceptions during metadata reflection in ForgeTool GUI.

## [0.0046] - 2026-07-31
- Retained original valid `.milo_xbox` and `_keep.png_xbox` binary assets from `SmellsLikeNirvana_rb3con` template (renamed to active song ID) in `con_packer.py`, preventing `Object reference not set to an instance of an object` NullReferenceExceptions in ForgeTool GUI during graphic/milo asset resolution.

## [0.0045] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) to use standard unquoted bare symbols for keys and song IDs (e.g. `(name "...")`, `(genre alternative)`), complying with official Rock Band 3 DTA formatting and resolving symbol parsing errors in ForgeTool GUI.

## [0.0044] - 2026-07-31
- Added comprehensive zero-padding/clearing in `con_packer.py` prior to writing patched payload files (like `songs.dta`) to ensure no leftover template garbage from `SmellsLikeNirvana_rb3con` remains in allocated blocks, preventing `Whitespace encountered in symbol` parsing errors.

## [0.0043] - 2026-07-31
- Re-enabled signed template CON cloning in `con_packer.py` combined with the 4-stem aligned `songs.dta` (`dta_writer.py`), satisfying both STFS cryptographic container validation and DTA S-expression parsing rules in ForgeTool GUI.

## [0.0042] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) track count to match the 4-stem multitrack layout (`tracks_count (2 2 2 2)` with 8-channel pans/vols/cores), preventing parser token mismatches.

## [0.0041] - 2026-07-31
- Reverted to pure standalone programmatic CON packaging (`con_packer.py`) combined with the exact single-quoted C3/Magma `songs.dta` format (`dta_writer.py`), eliminating external template dependencies while satisfying ForgeTool GUI's DTA array parsing rules.

## [0.0040] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) to correctly quote `('drum_bank' "sfx/kit01_bank.milo")`, eliminating unquoted path tokens that caused `Whitespace encountered in symbol` parsing errors in ForgeTool GUI while utilizing signed template CON cloning (`con_packer.py`).

## [0.0039] - 2026-07-31
- Refactored `con_packer.py` to be 100% standalone and programmatic from scratch (removing dependency on external template files), constructing the 12-block STFS header, 8-entry file table layout, and payload block stream natively.

## [0.0038] - 2026-07-31
- Implemented signed template CON cloning and payload patching in `con_packer.py` using `SmellsLikeNirvana_rb3con` as a base template, preserving 100% valid cryptographic signatures, STFS certificates, and file table structures while updating `songs.dta`, `.mid`, and `.mogg` in-place.

## [0.0037] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) to replicate the exact field list (`tracks_count`, `pans`, `vols`, `cores`, `vocal_parts`, `rank`, `version`, `format`, `album_art`, `rating`, `sub_genre`, `tuning_offset_cents`, `guide_pitch_volume`, `game_origin`, `encoding`, etc.) and CRLF line endings of `SmellsLikeNirvana_rb3con`.

## [0.0036] - 2026-07-31
- Updated `songs.dta` generator (`dta_writer.py`) to match the exact single-quoted C3/Magma format (`('{song_id}' ('name' "{title}") ...)`), mirroring the structure and syntax of known-good working CON packages (`SmellsLikeNirvana_rb3con` and `311 - Down`).

## [0.0035] - 2026-07-31
- Reverted `songs.dta` (`dta_writer.py`) to standard single-wrapped format `({song_id} ...)` combined with the correct 8-entry file table layout (`con_packer.py`), ensuring ForgeTool GUI parses the song entry correctly now that file table index alignment is correct.

## [0.0034] - 2026-07-31
- Wrapped song ID as an array `({song_id})` in `dta_writer.py` to ensure index 0 of the song definition block is parsed as a `DataArray` rather than a `DataSymbol`, satisfying C3 / ForgeTool GUI DTA array validation rules.

## [0.0033] - 2026-07-31
- Wrapped song ID in quotes as `("{song_id}")` in `dta_writer.py` to ensure index 0 of the song array is parsed as a String/Array rather than a bare DataSymbol by ForgeTool GUI's DTA parser.

## [0.0032] - 2026-07-31
- Expanded `con_packer.py` file table to match the exact 8-entry `SmellsLikeNirvana_rb3con` layout (including `songs`, `{song_id}`, `gen` directories, `songs.dta`, `.mid`, `.mogg`, `.milo_xbox`, and `_keep.png_xbox`), ensuring correct file index alignment for ForgeTool GUI's DTA parser.

## [0.0031] - 2026-07-31
- Wrapped song definition in an outer DTA list `( ( song_id ... ) )` in `dta_writer.py`, ensuring root `DataArray` element at index 0 is a song list Array rather than a DataSymbol, resolving `Element at index 0 is not an Array. It is DataSymbol` errors in ForgeTool GUI.

## [0.0030] - 2026-07-31
- Adjusted CI workflow (`.github/workflows/ci-cd.yml`) tag trigger from `v*.*.*` to `v*` so pre-release/test tags (e.g. `v0.001xTest`) correctly trigger CI/CD builds and GitHub Releases.
- Refactored `con_packer.py` to match the exact 5-entry `SmellsLikeNirvana_rb3con` file table structure (`songs` dir, `{song_id}` dir, `songs.dta` inside `/songs/songs.dta`, `.mid`, and `.mogg`), resolving `Unable to find the file songs.dta` errors in ForgeTool GUI.

## [0.0029] - 2026-07-31
- Reverted `songs.dta` (`dta_writer.py`) to single-level unquoted song entry format (`(open_road_song ...)`), matching the standard DTA schema expected by ForgeTool GUI and resolving DTA parsing errors.

## [0.0028] - 2026-07-31
- Restored standard hierarchical 6-entry STFS file table layout (`con_packer.py`) with root `songs.dta`, `songs` directory, song subfolder, and song-level `songs.dta`, `.mid`, and `.mogg`, matching standard Rock Band 3 and C3 custom package conventions.

## [0.0027] - 2026-07-31
- Updated GitHub Actions CI workflow (`.github/workflows/ci-cd.yml`) to install the package in editable mode (`pip install -e .`) before executing pytest.

## [0.0026] - 2026-07-31
- Reverted to clean programmatic 12-block STFS CON generation (`con_packer.py`) with payload offset tracking (`0xD000`), passing all local `forge_simulator.py` and `stfs_validator.py` checks.

## [0.0025] - 2026-07-31
- Updated in-place template patcher (`con_packer.py`) to correctly align file table entries 4 and 5 with active song filenames (`open_road_song.mid` and `open_road_song.mogg`), resolving internal stream resolution NullReferenceExceptions in ForgeTool GUI.

## [0.0024] - 2026-07-31
- Updated in-place template patching (`con_packer.py`) to dynamically rewrite filenames (`songs.dta`, `{song_id}.mid`, `{song_id}.mogg`) in file table entries 3, 4, and 5, matching the active song ID and preventing file-lookup NullReferenceExceptions in ForgeTool GUI.

## [0.0023] - 2026-07-31
- Implemented true in-place template payload patching in `con_packer.py` (`SmellsLikeNirvana_rb3con`), preserving all 8 file table entries (including album art and milo scenes), block offsets, and digital signatures without truncating or mismatching entry order.

## [0.0022] - 2026-07-31
- Wrapped the song definition block in an outer S-expression list `( ( song_id ... ) )` in `songs.dta` (`dta_writer.py`), satisfying the root `DataArray` structure expected by ForgeTool GUI's DTA parser.

## [0.0021] - 2026-07-31
- Fixed song ID formatting in `songs.dta` (`dta_writer.py`) to be an unquoted bare DataSymbol rather than a quoted string, resolving ForgeTool GUI DTA parser errors (`Element at index 0 is not an Array. It is DataSymbol`).
- Added Vocal Gender Detection to `ROADMAP.md`.

## [0.0020] - 2026-07-31
- Fixed payload start block alignment (`current_block = 0`) in `con_packer.py` so file table start blocks match the exact payload write offsets (`0xD000`), resolving stream reading NullReferenceExceptions in ForgeTool GUI.

## [0.0018] - 2026-07-31
- Updated `ROADMAP.md` to include vocal overdrive sections and activation phrases during lyrical breaks.
- Updated `con_packer.py` to explicitly update file modification timestamps (`os.utime`) upon successful packaging.

## [0.0017] - 2026-07-31
- Created project feature roadmap (`ROADMAP.md`) tracking completed features and planned enhancements (multi-harmony vocal extraction, master multitrack support, solo section recognition, and overdrive/fill markers).

## [0.0016] - 2026-07-31
- Implemented signed template CON cloning and payload patching in `con_packer.py` to preserve valid cryptographic certificates and signatures from known-good templates, preventing signature validation NullReferenceExceptions in ForgeTool GUI.

## [0.0015] - 2026-07-31
- Added `--skip-mogg` CLI flag to allow skipping MOGG audio container building and using pre-existing MOGG files.

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
