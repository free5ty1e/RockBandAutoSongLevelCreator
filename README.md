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
* **Automatic Transcription:** Converts pitch and transient audio into quantized 5-lane instrument tracks (`PART GUITAR`, `PART BASS`, `PART DRUMS`) using Spotify's **Basic-Pitch** and signal processing.
* **Direct CON Packaging:** Assembles multi-channel audio (`.mogg`), `notes.mid`, `songs.dta`, and album artwork into an Xbox 360 STFS CON container directly—no legacy tools required.

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

## 🛠️ Requirements & Setup

### Option A: VS Code Devcontainer (Recommended)
This repository includes a fully configured Docker Devcontainer equipped with CUDA/CPU PyTorch dependencies, `ffmpeg`, and C++ build tools.

1. Clone this repository.
2. Open the project in **VS Code**.
3. When prompted, click **"Reopen in Container"** (or run `Dev Containers: Reopen in Container` from the Command Palette).
4. All system and Python dependencies will be automatically installed.

### Option B: Local Installation

**Prerequisites:**
* Python 3.11+
* `ffmpeg` and `libsndfile1` installed on system path.

**Installation:**
```bash
# Clone repository
git clone https://github.com/your-username/autorb.git
cd autorb

# Set up virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## 🚀 Quick Start & Usage

Run `autorb` via the command line:

```bash
python -m autorb.cli \
  path/to/song.mp3 \
  --artist "The Beatles" \
  --title "Hey Jude" \
  --year 1968 \
  --genre "Classic Rock" \
  --lyrics path/to/lyrics.lrc \
  --output-dir ./output


python -m autorb.cli \
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
python -m autorb.cli \
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
python -m autorb.cli \
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

## 🧪 Development, Testing & CON Validation

Run unit tests and STFS validation locally:

```bash
# Run test suite
pytest

# Validate generated CON package structure and parent directory pointers
python3 autorb/export/stfs_validator.py output/open_road_song.con
```

### STFS Packaging & Multi-track DTA Generation
Step 5 automatically generates a fully compliant Xbox 360 STFS CON package with hierarchical directory structures (`songs/{song_id}/`) and maps all 4 Demucs stems (drums `0-1`, bass `2-3`, guitar `4-5`, vocals `6-7`) in `songs.dta`. All packaging and metadata are dynamically generated via pipeline scripts (never manually edited).

### CI/CD Pipeline
This repository uses GitHub Actions (`.github/workflows/ci-cd.yml`) to:
* Automatically run test suites on every `push` and `pull_request` to `main`.
* Build a standalone, cross-platform executable via PyInstaller and automatically draft a **GitHub Release** whenever a tag matching `v*.*.*` is pushed.

```bash
# Trigger a build release
git tag v0.1.0
git push origin v0.1.0
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
├── AGENT_PLAN.md         # Detailed specification & task tracking for AI agents
├── requirements.txt      # Python dependencies
└── README.md
```

---

## 📜 Disclaimer & Acknowledgments

* **AutoRB** is a fan-created, non-commercial open-source utility designed for homebrew and custom game content creation.
* Special thanks to the **MiloHax** community, **C3**, and the creators of **Demucs**, **WhisperX**, and **Basic-Pitch**.
