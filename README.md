# AutoRB 🎸 (MP3 -> CON)

**Automated Rock Band 3 CON File Generator using Machine Learning & Signal Processing.**

`autorb` is an end-to-end Python CLI tool designed to take raw audio files and optional lyric files and transform them into fully playable, synchronized Xbox 360 CON (STFS) files for *Rock Band 3*. 

By leveraging modern AI models for stem separation, pitch detection, and vocal alignment, AutoRB automates the complex manual workflow traditionally required to create custom Rock Band tracks.

NOTE: Under development.  No release is available to share just yet.  

---

## 🌟 Key Features

* **Universal Audio Input:** Accepts standard audio formats (MP3, WAV, FLAC, M4A, etc.) via FFmpeg.
* **Audio Stem Separation:** Leverages Meta's **Demucs** to isolate drums, bass, vocals, and backing tracks.
* **Smart Lyrics & Vocal Alignment:** 
  * Parses **Enhanced LRC (.lrc)** files for word/syllable-level timing.
  * Falls back to **WhisperX** for automated speech-to-text alignment if no LRC file is supplied.
  * **Onset-snapped timing:** WhisperX word boundaries are systematically late (median ~80ms, tail ~400ms), and Basic-Pitch's own note onsets can lag the true sung attack by another ~300ms (measured: the first word of "Open Road Song" was charted ~350ms late). Each word's start is now snapped to the **earliest vocal-stem attack onset** (librosa onset detection on the vocal stem) inside the search window — the true sung onset — never back into the previous word or beyond its own window, and multi-syllable word ends extend across all notes inside the word's own span.
* **Automatic Transcription:** Converts pitch and transient audio into quantized 5-lane instrument tracks (`PART GUITAR`, `PART BASS`, `PART DRUMS`) using Spotify's **Basic-Pitch** and signal processing.
* **Robust Vocal Pitch:** The sung pitch per word is taken from the note with the largest overlap over the word's window (not a weighted median, which let brief harmonics/echo bleed drag the reading off), with a high-confidence **librosa pyin** guard that corrects octave-flipped words (conf ≥ 0.8, disagreement > 4 semitones).
* **Automatic Difficulty Ratings:** Computes per-instrument Rock Band difficulty (`rank`) values from chart note density (per-instrument level bands 1-6, `band` = hardest charted instrument) instead of a hardcoded value that rendered every song as "1 of 6".
* **Stock-like Measure-Level Tempo Map:** The MIDI tempo track carries a sparse, smooth `set_tempo` map (one event per measure, tempo = that bar's mean beat interval, ~90-100 events for a 3-minute song) instead of a dense jittery per-beat map. A 1-event-per-beat map (with its ~±3 BPM per-beat oscillation) makes the game drift progressively late — the symptom we measured against the working references (stock 311 - Down DLC: 69 smooth events; Smells Like Nirvana custom: 86) — so every note tick is now derived from the *inverse* of the tempo map the file carries, keeping chart and map self-consistent (no drift by construction).
* **Mandatory Count-In:** Automatically prepends a silent count-in (3 measures at the song's opening tempo) to the multi-channel MOGG and shifts the chart past it, mirroring stock RB3 DLC's ~5s lead-in so the game gets a real pre-roll and the first vocal phrase survives ForgeTool's 640-tick offset (which previously underflowed and broke the vocal guide).
* **Direct CON Packaging:** Assembles multi-channel audio (`.mogg`), `notes.mid`, `songs.dta`, and album artwork into an Xbox 360 STFS CON container directly—no legacy tools required.
* **Freestyle Vocals (RB4, opt-in):** `--generate-freestyle-vocals` writes `(freestyle_vocals 1)` into `songs.dta`, which the vendored (patched) ForgeTool carries into the PS4 `songdta_ps4` `HasFreestyleVocals` flag so Rock Band 4 draws the diatonic Freestyle Vocals guide lines on Hard/Expert (the game computes the guide scale from the charted vocal notes).

---

## 🏗️ Architecture & Pipeline

```text
┌──────────────┐     ┌────────────────┐     ┌────────────────────────┐
│ Audio Input  │ ──> │ Demucs Stems   │ ──> │ Basic-Pitch / Librosa  │ ──┐
└──────────────┘     └────────────────┘     └────────────────────────┘   │
                                                                         ▼
┌──────────────┐     ┌────────────────┐     ┌────────────────────────┐ ┌──────────────┐
│ Lyrics (.lrc)│ ──> │ Syllable Sync  │ ──> │ Vocal MIDI Pitch Mapping  │ ──>│ MIDI Assembly│
└──────────────┘     └────────────────┘     └────────────────────────┘ └──────────────┘
                                                                         │
                                                                         ▼
┌──────────────┐     ┌────────────────┐     ┌────────────────────────┐ ┌──────────────┐
│  Metadata    │ ──> │   songs.dta    │ ──> │ Multi-channel MOGG Enc │ ──>│ STFS Container│
└──────────────┘     └────────────────┘     └────────────────────────┘ └──────────────┘
                                                                         │
                                                                         ▼
                                                                  [ Output .CON ]
```

---

## 📥 Installation & Getting Started (Fresh Users)

AutoRB runs on **macOS, Windows, and Linux**. Because AutoRB leverages heavy machine learning frameworks (PyTorch, Demucs, WhisperX, Basic-Pitch), it is distributed as a standard Python package (`autorb`) which you install via `pip`.

### 1. Prerequisites (All Operating Systems)
* **Python 3.11, 3.12, or 3.13** installed on your system. **Python 3.14 is NOT supported** — WhisperX (a hard dependency for vocal alignment) caps at `<3.14`, and the only whisperx release without an upper bound pins `ctranslate2==4.4.0`, which ships no Python 3.14 wheel. The wheel's `Requires-Python` now enforces `>=3.11,<3.14`, so pip refuses early with a clear message instead of failing with `No matching distribution found for ctranslate2==4.4.0`.
  * **macOS users:** your system `python3` is likely **3.9.6** (too old — installs will fail with "requires a different Python: 3.9.6 not in '>=3.11'"). Install a current Python first: `brew install python@3.12`, or download from [python.org](https://www.python.org/downloads/). Then use `python3.12` in place of `python3` below. Verify with `python3 --version`.
* **FFmpeg** installed and available on your system PATH (`ffmpeg -version` should succeed).
  * **Windows:** Download FFmpeg from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or install via Chocolatey (`choco install ffmpeg`).
  * **macOS:** Install via Homebrew (`brew install ffmpeg`).
  * **Linux (Ubuntu/Debian):** Install via apt (`sudo apt install ffmpeg libsndfile1`).

### 2. Installing AutoRB
Open your terminal (Command Prompt/PowerShell on Windows, Terminal on macOS/Linux) and run:

```bash
# Clone the repository
git clone https://github.com/chrispaiano/RockBandAutoSongLevelCreator.git
cd RockBandAutoSongLevelCreator

# Create and activate a virtual environment (Recommended)
python3 -m venv venv
# On macOS / Linux:
source venv/bin/activate
# On Windows (PowerShell):
# .\venv\Scripts\Activate.ps1

# Verify the venv is using Python 3.11+ (macOS's default python3 is 3.9.6 — too old)
python3 -c "import sys; assert sys.version_info >= (3, 11), 'Need Python 3.11+ — recreate the venv with a newer python3'"

# Install AutoRB and all ML dependencies
pip3 install --upgrade pip
pip3 install -r requirements.txt
pip3 install -e .
```

*Note on `--build-pkg`:* The `--build-pkg` flag requires the `ForgeTool` C#/.NET binary toolchain vendored in `tools/forgetool`. If you are running outside of the devcontainer or CI environment, ensure `.NET SDK 8` and `mono-devel` are installed so `tools/build_forgetool.sh` can build the helper binaries if needed. Standard CON file generation does not require `.NET` or `mono`.

### Feature Support Matrix (where each feature works)

ForgeTool is vendored as **source only** — the compiled `.exe`/`.dll` binaries are gitignored and never shipped in the wheel. AutoRB patches to the ForgeTool source (e.g. `HasFreestyleVocals` for `--generate-freestyle-vocals`) therefore only reach users who build the tool from the vendored source. Everything that does not require ForgeTool works everywhere.

| Feature | pip wheel | git checkout (after `tools/build_forgetool.sh`) | devcontainer (auto-built) |
| :--- | :---: | :---: | :---: |
| CON generation (`.con`), stems, tempo, vocals, difficulty, count-in, MOGG, `songs.dta` | ✅ | ✅ | ✅ |
| `--build-pkg` (PS4 PKG) | ❌* | ✅ | ✅ |
| `--generate-freestyle-vocals` — PS4 guide lines | ❌* | ✅ | ✅ |

\* On a bare wheel install, `--build-pkg` fails fast with a clear message pointing you to `git clone` + `tools/build_forgetool.sh` (the wheel contains only the `autorb.*` Python packages; `_find_forgetool()` searches for `tools/forgetool` under the CWD, its parent, `sys.prefix`, and `sys.base_prefix`, so running the CLI from a clone's root also works against a wheel-installed `autorb`). `--generate-freestyle-vocals` still writes `(freestyle_vocals 1)` into the CON's `songs.dta` on a wheel, but that line has **no effect on PS4 without the patched ForgeTool** carrying it into the `songdta_ps4` `HasFreestyleVocals` flag — so on a wheel it is effectively a no-op for the intended feature.

**Propagation mechanics:**
- **Devcontainer:** every fresh container runs `.devcontainer/post-install.sh` (`postCreateCommand`), which installs .NET SDK 8 to `/tmp/dotnet` and runs `tools/build_forgetool.sh` — the patched tool is compiled automatically, feature works out of the box. The container image already ships `mono-devel` for running the built tool.
- **Git clone:** `git clone` gives you the patched source; run `tools/build_forgetool.sh` once (needs .NET SDK 8 + `mono-devel`) and run the CLI from the repository root. Re-run the script once on an existing clone to pick up newly committed patches.
- **Release wheels:** ForgeTool is never shipped (neither binaries nor the source tree), by design — the wheel is pure Python. All non-ForgeTool features are fully available.

### Troubleshooting `python3 -m venv venv` failures (macOS/Linux)

If creating the venv fails with a cryptic error like:
`Command '['.../venv/bin/python3.12', '-m', 'ensurepip', '--upgrade', '--default-pip']' returned non-zero exit status 1`

The real failure is inside `ensurepip` — run it directly to see the actual message:
```bash
python3.12 -m ensurepip --upgrade
```

Try these fixes in order:

1. **Stale `PYTHONPATH`/`PYTHONHOME` env vars** (common on macOS) break the venv's isolated subprocess:
   ```bash
   unset PYTHONPATH PYTHONHOME
   rm -rf venv
   python3.12 -m venv venv
   ```
2. **Wrong `python3.12` binary** — confirm it's the Homebrew/pyenv Python you expect (pyenv shims can point at a build without pip support):
   ```bash
   which python3.12
   python3.12 -c "import sys; print(sys.executable, sys.version)"
   ```
3. **Bootstrap pip manually** if `ensurepip` is genuinely broken:
   ```bash
   python3.12 -m venv --without-pip venv
   source venv/bin/activate
   curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
   python3.12 /tmp/get-pip.py
   ```

Then install the wheel as usual:
```bash
pip3 install ./autorb-*.whl
```

### 3. Preparing Lyrics (`.lrc` Files)
AutoRB relies on Enhanced LRC (`.lrc`) lyric files for precise word and syllable timing. 
* **Where to find `.lrc` files:** You can find or download synced LRC files from community lyric sites (such as [LRC LIB](https://lrclib.net/) or NetEase/QQ Music repositories), or create them manually using tools like [LRC Generator](https://www.lrcgenerator.com/).
* **Example Format:** Your `.lrc` file should include timestamp tags formatted as `[mm:ss.xx]` preceding each lyric line or word:
  ```lrc
  [00.12.34]Tonight, the night
  [00.15.80]When the world was young
  [00.18.45]And we were free
  ```

### 4. Running the Pipeline & Converting CON to PS4 PKG
Once installed, convert any MP3 and lyric file into an Xbox 360 CON file and an optional PS4 PKG installer:

```bash
python3 -m autorb.cli \
  path/to/song.mp3 \
  --artist "Artist Name" \
  --title "Song Title" \
  --year 2024 \
  --genre "Alternative" \
  --lyrics path/to/lyrics.lrc \
  --output-dir ./output \
  --build-pkg
```

Your outputs will be generated in `./output/` (the `.con` file) and `./output/pkg/` (the PS4 `.pkg` file).

---

## 🚀 Quick Start & Usage

Run `autorb` via the command line:

```bash
python3 -m autorb.cli \
  path/to/song.mp3 \
  --artist "The Beatles" \
  --title "Hey Jude" \
  --year 1968 \
  --genre "Classic Rock" \
  --lyrics path/to/lyrics.lrc \
  --output-dir ./output


python3 -m autorb.cli \
  input/eve6-openRoadSong.mp3 \
  --artist "Eve 6" \
  --title "Open Road Song" \
  --year 1998 \
  --genre "Alternative" \
  --lyrics input/eve6-openRoadSong.lrc \
  --output-dir ./output

```

### CLI Options

| Argument / Flag | Type | Description |
| :--- | :--- | :--- |
| `AUDIO_FILE` | Position | **Required.** Path to the source audio file. |
| `-a, --artist` | String | **Required.** Artist name for game metadata. |
| `-t, --title` | String | **Required.** Song title for game metadata. |
| `-l, --lyrics` | Path | Optional. Path to Enhanced LRC file (`.lrc`). |
| `-y, --year` | Integer | Release year (Default: Current Year). |
| `-g, --genre` | String | Genre string (Default: `"Rock"`). |
| `-o, --output-dir` | Path | Destination folder for the compiled CON file (Default: `./output`). |
| `--album-art` | Path | Optional. Custom album art image (PNG/JPG) for the CON's `_keep.png_xbox` texture. Defaults to a generated "Chris Prime Custom" cover (stacked CHRIS/PRIME text with an orange "BOT" badge). |
| `--skip-separation` | Flag | Skip AI stem separation; requires `drums.wav`, `bass.wav`, `vocals.wav`, `other.wav` in `[output-dir]/stems`. |
| `--skip-tempo-detection` | Flag | Skip beat tracking; loads `tempo_map.json` from the output directory. |
| `--skip-vocals` | Flag | Skip WhisperX alignment and basic-pitch; loads `vocals_cache.json`. |
| `--skip-mogg` | Flag | Skip MOGG building; reuses the existing `.mogg` file (disables the count-in so the chart stays in sync with the reused audio). |
| `--generate-freestyle-vocals` | Flag | Enable Rock Band 4 **Freestyle Vocals** guide lines (Hard/Expert): writes `(freestyle_vocals 1)` into `songs.dta`, which the vendored (patched) ForgeTool carries into the PS4 `songdta_ps4` `HasFreestyleVocals` flag so the game advertises and draws the diatonic guide lanes. Off by default. Requires `--build-pkg` to take effect on PS4 (the flag lives in the PKG's songdta; the Xbox 360 CON's `songs.dta` is untouched by the game's freestyle check). |

---

## Previewing Results

### Previewing separated audio mix

To sum the separated audio tracks back together into a single audio file to hear what all tracks would sound like playing in-game in multitrack mode: 

```bash
python -m autorb.audio.mix_preview
```

Your stems in `output/stems` will be summed into `output/preview_mix.mp3`

## Using Original Master Stems (For Bands/Artists)

If you have access to the original studio multitracks (stems) for a song, you can skip the AI audio separation step to achieve perfect, artifact-free audio in-game.

1. Create a `stems` folder inside your designated output directory (e.g., `./output/stems/`).
2. Place your 4 master audio files in this folder and name them exactly:
   - `drums.wav`
   - `bass.wav`
   - `vocals.wav`
   - `other.wav` (Guitars, synths, backing tracks, etc.)
3. Run the CLI tool with the `--skip-separation` flag:

```bash
python3 -m autorb.cli \
  input/dummy-audio.mp3 \
  --artist "Your Band" \
  --title "Your Song" \
  --year 2024 \
  --genre "Rock" \
  --lyrics input/your-song.lrc \
  --output-dir ./output \
  --skip-separation
```

## Usage

Run the pipeline using the CLI. You can optionally skip heavy processing steps if you have already generated the intermediate files (stems, tempo maps, or vocal data) during a previous run.

```bash
python3 -m autorb.cli \
  input/your-audio.mp3 \
  --artist "Eve 6" \
  --title "Open Road Song" \
  --year 1998 \
  --genre "Alternative" \
  --lyrics input/lyrics.lrc \
  --output-dir ./output \
  --skip-separation \
  --skip-tempo-detection \
  --skip-vocals
```

### Command Line Options

audio_file: (Required) Path to the input audio file.

--artist: (Required) The name of the artist.

--title: (Required) The title of the song.

--year: (Required) The year the song was released.

--genre: (Required) The genre of the song.

--lyrics: (Required) Path to the .lrc lyrics file.

--output-dir: The directory to save all output files (default: ./output).

--skip-separation: Skips the AI stem separation. Requires drums.wav, bass.wav, vocals.wav, and other.wav in the [output-dir]/stems folder.

--skip-tempo-detection: Skips librosa beat tracking and loads tempo_map.json from the output directory.

--skip-vocals: Skips WhisperX alignment and basic-pitch extraction, loading vocals_cache.json from the output directory.

--skip-mogg: Skips MOGG audio container building and uses the existing `.mogg` file. Disables the automatic count-in so the chart stays in sync with the reused (un-shifted) audio.

--generate-freestyle-vocals: Writes `(freestyle_vocals 1)` into `songs.dta` so the vendored (patched) ForgeTool sets `HasFreestyleVocals` in the PS4 `songdta_ps4` — enabling Rock Band 4's Freestyle Vocals guide lines (Hard/Expert). Requires `--build-pkg` to affect the PS4 PKG. Off by default.

## 🧪 Development, Testing & CON Validation

Run unit tests and STFS validation locally:

```bash
# Run test suite
pytest

# Validate generated CON package structure and parent directory pointers
python3 autorb/export/stfs_validator.py output/open_road_song.con
```

### ForgeTool Verification (PS4)
We include a vendored, buildable version of `ForgeTool` to verify CON-to-PKG conversion on Linux:
```bash
# Verify the build/conversion path
tools/forgetool con2gp4 --id 0000000000000001 --desc "Test" output/open_road_song.con ./temp_gp4
```

To build and package a PS4 PKG installer directly from the pipeline:
```bash
python3 -m autorb.cli \
  input/song.mp3 \
  --artist "Artist" --title "Title" --year 1968 --genre "Rock" \
  --lyrics input/song.lrc \
  --output-dir ./output \
  --build-pkg
```

### STFS Packaging & Multi-track DTA Generation
Step 5 automatically generates a fully compliant Xbox 360 STFS CON package with hierarchical directory structures (`songs/{song_id}/`) and maps the 4 Demucs stems to a **10-channel** MOGG in `songs.dta`, mirroring the proven-working "311 - Down" DLC layout (ch0-1 stereo drum kit, ch2-3 stereo drums, ch4 mono bass, ch5-6 stereo guitar, ch7-8 stereo vocals, ch9 quiet fake/crowd ambience). Every channel carries audio — binary analysis of "311 - Down" showed its kick/snare (ch0/1) are the loudest channels in the file, and leaving ch0/1/ch9 as digital silence made the PS4 song-list preview completely silent. All packaging and metadata are dynamically generated via pipeline scripts (never manually edited).

The embedded MOGG must use **small Ogg pages**. ffmpeg's default libvorbis paging emits ~1-second / ~56KB pages that Rock Band's Milkshake audio engine cannot reliably decode — the symptom is no audio preview in the song list and the song "completing instantly" at 0%. `mogg_builder.py` forces small ~4KB pages (~2048-3072 sample granules) via ffmpeg's `-page_duration 40000` option, matching stock moggs (e.g. "311 - Down" RB3 DLC). `songs.dta`'s `(song_length ...)` is no longer hardcoded — it is derived from the actual MOGG audio duration via `read_mogg_duration_ms()`.

The generated MIDI chart always includes `BEAT`, `EVENTS`, `PART VOCALS`, and placeholder `PART DRUMS` / `PART GUITAR` / `PART BASS` tracks so that every instrument advertised in `songs.dta` has a loadable chart track. The `EVENTS` track carries the mandatory Rock Band text markers (`[prc_intro]`, `[music_start]`, `[prc_verse_1]`, `[preview]`, `[prc_chorus_1]`, `[prc_outro]`, `[music_end]`, with `[end]` as the final event) and the `BEAT` track emits one quarter-note marker per beat (pitch 12 downbeat vel 101, pitch 13 other beats vel 100, 480-tick spacing), mirroring the proven-good "311 - Down" reference chart. A missing `[preview]` marker kills the song-list preview and missing `[music_end]`/`[end]` makes the song finish instantly at 0%. Each placeholder track emits one note per difficulty (keys 60/72/84/96 for Easy/Medium/Hard/Expert) so LibForge's `RBMidConverter` (`HandleDrumTrk` / `HandleGuitarBass`) finds a non-null gem track for all four difficulty slots — a single-note placeholder (pitch 60 only) left 3 of the 4 slots null and crashed ForgeTool's CON → PKG conversion with a `System.NullReferenceException`. This prevents RB4 crashes (via ForgeTool PKG conversion) that occur when the vocal fretboard loads but an advertised part has no corresponding MIDI track.

### CI/CD Pipeline
This repository uses GitHub Actions (`.github/workflows/ci-cd.yml`) to:
* Automatically run test suites on every `push` and `pull_request` to `main`.
* Build a Python source distribution and wheel (`python -m build`) and automatically draft a **GitHub Release** whenever a tag matching `v*.*.*` is pushed.

```bash
# Trigger a build release (tag MUST match the version in autorb/version.py,
# pyproject.toml, and CHANGELOG.md — currently 0.0064)
git tag v0.0064
git push origin v0.0064
```

---

## 📁 Project Structure

```text
autorb/
├── .devcontainer/        # Docker devcontainer specs
├── .github/workflows/    # CI/CD pipelines (PyTest + PyInstaller release)
├── autorb/
│   ├── cli.py            # Click CLI entrypoint
│   ├── audio/            # Demucs stem separation & MOGG building
│   ├── transcribe/       # Basic-Pitch, Librosa, and WhisperX logic
│   └── export/           # MIDI composition, DTA, and STFS packaging
├── tests/                # PyTest test suite
├── ROADMAP.md            # Feature roadmap & progress tracking
├── CHANGELOG.md          # Version changelog
├── AGENT_PLAN.md         # Detailed specification & task tracking for AI agents
├── requirements.txt      # Python dependencies
└── README.md
```

---

## 📜 Disclaimer & Acknowledgments

* **AutoRB** is a fan-created, non-commercial open-source utility designed for homebrew and custom game content creation.
* Special thanks to the **MiloHax** community, **C3**, and the creators of **Demucs**, **WhisperX**, and **Basic-Pitch**.
