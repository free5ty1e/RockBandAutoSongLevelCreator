# AutoRB 🎸 (MP3 -> CON)
## (MP3 + LRC -> CON, PS4 RB4 US PKG, Clone Hero)

**Automated Rock Band 3 CON File Generator using Machine Learning & Signal Processing.**

`autorb` is an end-to-end Python CLI tool designed to take raw audio files and optional lyric files and transform them into fully playable, synchronized Xbox 360 CON (STFS) files for *Rock Band 3*.  (This pipeline will also optionally output a Clone Hero song folder and a PS4 Rock Band 4 US DLC PKG installer)

By leveraging modern AI models for stem separation, pitch detection, and vocal alignment, AutoRB automates the complex manual workflow traditionally required to create custom Rock Band tracks.

NOTE: The v0.0.92 alpha release now produces real (non-placeholder) **instrument charts** (guitar, bass, drums, keys) via the `autorb/transcribe/instruments` package **in addition to** the pitch-corrected solo-vocals + lyrics chart (see [Known Limitations](#-known-limitations)). The instrument charts are freshly generated and still benefit from playtest refinement, but the end-to-end concept — vocals *and* instruments — is now demonstrated.

Quick demo video of an MP3 + LRC file conversion to Rock Band CON + PS4 PKG on Rock Band 4 Deluxe PS4 converted with the v0.0.92 alpha release
https://youtu.be/lcFGsQfb9tg

---

## 🌟 Key Features

* **Universal Audio Input:** Accepts standard audio formats (MP3, WAV, FLAC, M4A, etc.) via FFmpeg.
* **Audio Stem Separation:** Leverages Meta's **Demucs** to isolate drums, bass, vocals, and backing tracks.
* **Smart Lyrics & Vocal Alignment:** 
  * Parses **Enhanced LRC (.lrc)** files for word/syllable-level timing.
  * Falls back to **WhisperX** for automated speech-to-text alignment if no LRC file is supplied.
  * **LRC timestamps are suggestions only — WhisperX decides where each lyric lands.** The MP3 and the `.lrc` come from different sources, so LRC line times carry a global offset and can be badly late. Instead of slicing the audio at each LRC line (which forced whole phrases late — Brian Wilson's worst word charted +1.8s late), the pipeline feeds WhisperX a handful of coarse ~60s chunks spanning the track and lets it freely align every word to the actual vocal audio (single whole-track alignment would be ideal but exhausts CPU memory on longer songs). On a fresh "Open Road Song" build: word starts median 0.000s, p90 +0.027s, **0 words > 1s late** (the previous tested build had 9).
  * **Audio-derived word starts & ends:** WhisperX word boundaries run ~80-400ms late, so each word's **start** is snapped to the latest true vocal-stem attack onset at-or-before its WhisperX boundary (librosa onset detection on the vocal stem, kept when a pyin-confident voiced frame or an RMS energy rise follows it within the search window, backtracking to the envelope floor once charted the first word 0.38s before its LRC timestamp and never back into the previous word or beyond its own window; the 1.5s search window absorbs badly late LRC/WhisperX phrases), and each word's **end** is the last voiced/RMS-energetic frame of its own region — so over-sustains are clipped ("bored" 22.8s→21.0s, "mirror" 34.6s→32.9s, "floor" 11.5s→9.9s) and under-sustains extend ("forgottennnn" now reaches its true sung tail). **The charted note lands on that snapped word start**, not Basic-Pitch's pitch onset: `generate_vocal_midi()` anchors the first note of each word at `word.start` (BP pitch onsets can lag the attack by 0.1-0.6s and, on held words, land near the word's *end*), while later segments within the word keep their own pitch-change times so syllable-internal slides and vibrato survive.
  * **Audio-true syllable timing & no doubled lyrics:** syllable starts/ends come from WhisperX character alignments when available (vowel-weighted proportion only as fallback), so syllable-internal notes follow the sung rhythm. Words with more pitch segments than syllables are never split into an empty-lyric note (Rock Band re-renders the previous lyric on empty text — the old "crack crack" doubling); they're split at vowel boundaries instead ("eighty" → "ei"/"ghty"). WhisperX word duplications (and melisma splits like "I'm-I'm") are deduplicated so one sung word is never charted twice.
  * **Audio-derived note ends:** LRC/WhisperX ends are not trusted (they're only suggestions and over/under-shoot the real sustain). Each note's end is set to the **last voiced/RMS-energetic frame of its own region** (`_audio_word_end`) and clipped to the **next note's charted start**, so every `note_on` lands exactly on its true sung onset, consecutive notes never overlap, and sustains follow the audio — no more progressive drift, no chopped ("forgottennnn") or over-held ("bored", "mirror", "floor") final syllables.
  * **Phrase-gap & late-word re-anchors (v0.0.87):** a word WhisperX glued onto the *previous* phrase's tail moves to its own phrase's true attack only when the **next word starts ≥ 1.0s away AND the `[start+0.20, +0.80]` window is vocally silent** (no voiced frame, no RMS above the floor — the 0.20s grace skips the previous word's own voiced tail) — "And" 20.94→23.80, "'Cause" 32.72→35.11. A word WhisperX pushed *late* re-anchors to the **earliest voiced-validated onset** in `(prev_end, start]` (bounded by a 2.0s window; the onset is kept only if a confident voiced frame follows within 0.15s, rejecting instrument-bleed attacks — "out" 143.6→142.15), or to a **settled pitch boundary** when the singer changed pitch and held the new note (`_last_pitch_unit_boundary`: a frame whose pitch is ≥ 3.5 semitones from the median of the stable pitch it settles into ~0.25s later, skipping in-progress descents and vibrato; it then prefers a real onset within ±0.15s when guarded by the neighbouring words) — "be"/"alone" split at the 63.37 drop. Word **ends** are now **voiced-primary** (break on voiced gaps > 0.20s; RMS only as fallback; the attack-to-voicing lead-in no longer false-triggers a break), so "it" no longer holds 1.8s past its sung tail and "listen"/"road"/"out" sustains clip to the true tail. Ends are re-ingested **between** the gap and late passes (a moved word's neighbour must see its corrected end or it re-snags the moved word).
* **Automatic Instrument Transcription:** Converts pitch and transient audio into quantized 5-lane instrument tracks (`PART GUITAR`, `PART BASS`, `PART DRUMS`, `PART KEYS`) via the `autorb/transcribe/instruments` package — Basic-Pitch pitch + librosa onsets for the fretted parts, the **ADTOF Frame-RNN neural drum transcriber** (5 classes: kick/snare/toms/hi-hat/cymbals) for drums, and progressive per-difficulty reduction (Expert/Hard/Medium/Easy) following the RBN/C3 authoring rules. Drums are transcribed from the drums stem (falling back to the mixed audio only when Demucs has left the stem's intro digitally silent); cymbal hits are re-split into ride (Blue) vs crash (Green) and toms into tom1/2/3 by spectral centroid, and all hits are grid-quantized to the 1/8 beat. Strummed guitar chords are reconstructed from the audio's chroma (the `other` stem's chordal strums get a perfect-fifth power-chord tone added so rhythm parts read as chords, not single notes). Keys reuses the guitar transcription (the guitar+keys stems are inseparable in Demucs).
* **Robust Vocal Pitch:** The sung pitch per word is chosen from the most reliable source. **librosa pyin is primary** — a word is trusted only when its (next-word-clipped) window has ≥ 2 confident voiced frames whose rounded mode agrees with the median (rejecting harmonics/bleed split readings while keeping real vibrato/slides), its note segments don't span more than 6 semitones (a real slide never jumps that far inside one syllable), and its first note sits within 7 semitones of the outlier-rejected **robust melodic contour** (so a single harmonic misread — e.g. "road"=72, the 3rd harmonic of A3 — can't stay charted or warp the contour). Words without a trusted pyin reading fall back to a **Basic-Pitch note octave-snapped to the melodic contour** interpolated through the trusted words, and then to the contour itself — so octave-flipped or contaminated BP notes become sane, in-key pitches. Measured on "Open Road Song": consecutive jumps ≥ 4 semitones **61 → 28/283**, range **50..83 → 50..78** (and the remaining wild first-phrase/ending jumps ≥ 5 st further cut **18 → 10** in v0.0.83), **0/284 notes off the A-major scale**, and repeated phrases sing the same notes while genuine melody dips (the low "As") are preserved.
* **Automatic Difficulty Ratings:** Computes per-instrument Rock Band difficulty (`rank`) values from chart note density (per-instrument level bands 1-6, `band` = hardest charted instrument) instead of a hardcoded value that rendered every song as "1 of 6".
* **Stock-like Measure-Level Tempo Map:** The MIDI tempo track carries a sparse, smooth `set_tempo` map (one event per measure, tempo = that bar's mean beat interval, ~90-100 events for a 3-minute song) instead of a dense jittery per-beat map. A 1-event-per-beat map (with its ~±3 BPM per-beat oscillation) makes the game drift progressively late — the symptom we measured against the working references (stock 311 - Down DLC: 69 smooth events; Smells Like Nirvana custom: 86) — so every note tick is now derived from the *inverse* of the tempo map the file carries, keeping chart and map self-consistent (no drift by construction).
* **Mandatory Count-In:** Automatically prepends a silent count-in (3 measures at the song's opening tempo) to the multi-channel MOGG and shifts the chart past it, mirroring stock RB3 DLC's ~5s lead-in so the game gets a real pre-roll and the first vocal phrase survives ForgeTool's 640-tick offset (which previously underflowed and broke the vocal guide).
* **Direct CON Packaging:** Assembles multi-channel audio (`.mogg`), `notes.mid`, `songs.dta`, and album artwork into an Xbox 360 STFS CON container directly—no legacy tools required.
* **Freestyle Vocals (RB4, opt-in):** `--generate-freestyle-vocals` writes `(freestyle_vocals 1)` into `songs.dta`, which the vendored (patched) ForgeTool carries into the PS4 `songdta_ps4` `HasFreestyleVocals` flag so Rock Band 4 draws the diatonic Freestyle Vocals guide lines on Hard/Expert (the game computes the guide scale from the charted vocal notes).
* **Clone Hero Export (`--build-clone-hero`):** Builds a standard, Clone Hero-compliant song folder (`song.ini` + `notes.chart` *and* `notes.mid` + `song.ogg` + `album.png`) so the vocal/lyric chart can be playtested on a PC in Clone Hero — no PS4, no CON packaging. The chart is re-generated **count-in free** (note ticks == audio time exactly), so any sync judgment made in Clone Hero transfers directly to the Rock Band chart (same data shifted past its count-in). Both chart files are written because CH accepts either and its `.chart` reader is the most battle-tested import path; lyrics ride as `[Events]` `phrase_start`/`phrase_end`/`lyric <text>` events exactly as Moonscraper writes them.
* **No-PS4 Sync Validation & Preview:** Every run now also emits `preview_mix.wav` (summed stereo stems), `lyrics_preview.srt` (karaoke subtitles from charted word timings — load both in VLC/MPV for a rewindable lyric-sync check), `alignment_report.json` (per-word charted start vs nearest vocal-stem onset: median/p90/max delta + late/early flags), and annotated waveform/spectrogram PNGs of the worst outliers — a quantitative signal for iterating on sync accuracy without a game console.

---

## ⚠️ Known Limitations

The v0.0.92 alpha release generates real instrument charts (guitar, bass, drums, keys) alongside the pitch-corrected solo-vocals + lyrics chart, but it is still an **alpha** with many features missing and the generated charts not yet playtest-validated. Be aware of what is and isn't supported yet:

- **Instrument charts are freshly generated, not yet playtest-validated.** `PART GUITAR` / `PART BASS` / `PART DRUMS` / `PART KEYS` are now produced by the `autorb/transcribe/instruments` package (Basic-Pitch + librosa, the **ADTOF neural drum transcriber**, 5-lane mapping, progressive RBN/C3 difficulty reduction) instead of single-note placeholders, so they are real, loadable instrument charts that no longer crash ForgeTool's CON→PKG conversion. They **have not yet been playtested against the actual audio** — note accuracy, HOPO/chord decisions, and drum-lane assignment may need tuning, and the guitar + keys stems are inseparable in Demucs (keys reuses the guitar transcription). Since v0.1.6 the drums are transcribed by the ADTOF neural model from the drums stem (the mixed audio is only used when the stem's intro is digitally silent), so intros chart as the real hi-hats/snares instead of guitar/bass lows. The bass chart starts at the true first bass note (~12 s into "Open Road Song") because the bass genuinely doesn't play in the intro — the earlier attempt to supplement it from the `other` stem was reverted after playtest (it charted guitar chords as bass). The bass stem is now energy-gated (v0.1.8: bass-band 40–250 Hz RMS vs the track's active level + a density pass for lone bleed spikes) so stem-separation bleed no longer produces phantom bass before the real first note (on "Open Road Song" the bass does not play until measure 17, ~23 s).
- **Per-word sync has outliers.** Word starts and ends are now driven by the vocal-stem audio (onset attacks + voiced/RMS tails), correcting the LRC's global offset and WhisperX's lateness, but individual words can still be slightly early or late where the onset/voicing signal is ambiguous, and lyrics must come from a good `.lrc` file — words missing from the LRC don't get charted (detecting & filling those is on the roadmap).- **Vocal phrases are wrong.** Phrase boundaries currently fall back to fixed 2-bar measure windows on the beat grid, not the song's real phrasing — so the in-game phrase regions and vocal scoring feel all wrong. Each timestamped line in the `.lrc` file marks the **start of one vocal phrase** and should be the source of truth (falling back to the 2-bar windows only when the `.lrc` is missing or doesn't make phrasing obvious). This is the highest-priority roadmap item (see [Next Steps](#-next-steps--roadmap)).
- **PS4 song-list preview audio is silent** on Rock Band 4 Deluxe, even though all preview metadata (`songdta_ps4`, `rbmid_ps4`, MOGG seek table) and the 10-channel audio layout (mirroring stock "311 - Down") are verified correct. This is suspected to be game-side (RB4DX caching/behavior) rather than file-side.
- **Freestyle Vocals guide lines do not render on PS4** yet, despite `HasFreestyleVocals=1` being written to the PKG. Both gates the RB4 manual documents are satisfied, so the failure is likely RB4DX-side (how it commits/reads the flag).
- **`--build-pkg` and the PS4 freestyle-vocals flag require a `git clone`** (or the devcontainer), not a bare wheel: ForgeTool is vendored as **source** (`tools/libforge/`) and rebuilt by `tools/build_forgetool.sh` (needs .NET SDK 8 + `mono-devel`). On a wheel, `--build-pkg` fails fast with a clear pointer, and the freestyle flag is a no-op for PS4.
- **Python 3.14 is NOT supported** (`Requires-Python >=3.11,<3.14`); macOS's default `python3` is 3.9.6 and too old — use `brew install python@3.12` and `python3.12`.

## 🗺️ Next Steps / Roadmap

Beyond the current alpha (vocals plus freshly-generated instrument charts), the roadmap (see `ROADMAP.md`) includes:

- **LRC-line phrase source of truth** — each `.lrc` line timestamp defines the **start of one vocal phrase** (currently phrase boundaries fall back to fixed 2-bar measure windows, which makes scoring feel wrong; the 2-bar fallback remains for when the `.lrc` is missing or doesn't make phrasing obvious). **Highest priority.**
- **Lyric/audio sync improvements** — tighten the remaining early/late per-word outliers so lyrics land exactly on the sung audio.
- **One pitch per lyrical syllable** — lyrical resolution enhancement so every syllable gets its own note/pitch instead of one static pitch per word.
- **Vocal pitch tracking** — when the singer changes pitch mid-lyric, the on-screen note moves up/down with the voice (sliding pitch transitions), not a single flat pitch per word.
- **Overdrive section marking** — automatically mark overdrive activation phrases (and vocal fills / talkie sections) so players can activate overdrive.
- **Solo / Harmony 1 / Harmony 2 detection, separation & instrument tracks** — split the vocal stem into melody + harmony parts, detect solo sections, and build real (non-placeholder) drum/guitar/bass charts.
- **Real instrument charts** — Basic-Pitch / signal-processing transcription of drums, guitar, and bass into playable 5-lane tracks (instead of placeholders).
- **Verify/refine Freestyle Vocals guide lines** on PS4 and the silent song-list preview.
- **Vocal gender detection** (`'male'`/`'female'`) for `songs.dta` metadata.
- **Tambourine detection** — map vocal-free instrumental breaks to microphone "Tambourine" sections.
- **Multi-harmony vocals** — extract harmony + melody parts for Rock Band's up-to-3-mic harmony system.
- **Robust tempo detection (stem fallback chain)** — beat tracking currently runs on the drums stem and only falls back to vocals for drumless sections; songs without a usable drums stem (all-break intros, instrumentals) get a wrong/missing tempo map. Planned: fall back **drums → bass → vocals → other** with per-stem validation and per-section merging, and record which stem drove each section in `tempo_map.json`.

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
  * **macOS users:** your system `python3` may be the wrong version in either direction — macOS ships an old **3.9.6** (too old — installs fail with "requires a different Python: 3.9.6 not in '>=3.11'"), and newer macOS releases / upgraded setups can resolve `python3` to **3.14.x** (too new — the wheel's `Requires-Python` is `>=3.11,<3.14`, so pip refuses with "Package 'autorb' requires a different Python: 3.14.x"). Install a supported Python: `brew install python@3.12`, or download from [python.org](https://www.python.org/downloads/). Then use `python3.12` in place of `python3` below — i.e. create the venv with `/opt/homebrew/bin/python3.12 -m venv venv`, **not** with bare `python3` (which would just re-create the venv on the wrong version). Verify with `python3.12 --version`.
* **FFmpeg** installed and available on your system PATH (`ffmpeg -version` should succeed). **Important:** AutoRB needs the `libvorbis` encoder to build the multi-channel MOGG. Homebrew's standard `ffmpeg` formula dropped libvorbis in ffmpeg 8 — if your run fails with `Unknown encoder 'libvorbis'`, install a libvorbis-capable build (see below) and confirm with `ffmpeg -encoders 2>&1 | grep vorbis` (should list `libvorbis`).
  * **Windows:** Download FFmpeg from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or install via Chocolatey (`choco install ffmpeg`). The full/essentials builds include libvorbis.
  * **macOS:** Install `brew install ffmpeg-full` (which includes libvorbis; it is keg-only, so put its `bin` on PATH first — e.g. `export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"` on Apple Silicon). Alternatively use a [ffmpeg.org](https://ffmpeg.org/download.html) macOS static build, which includes libvorbis. (Plain `brew install ffmpeg` since ffmpeg 8 lacks libvorbis.)
  * **Linux (Ubuntu/Debian):** Install via apt (`sudo apt install ffmpeg libsndfile1`). Distro packages (Debian/Ubuntu/Fedora/Arch) build ffmpeg with libvorbis.

### 2. Installing AutoRB
Open your terminal (Command Prompt/PowerShell on Windows, Terminal on macOS/Linux) and run:

```bash
# Clone the repository
git clone https://github.com/free5ty1e/RockBandAutoSongLevelCreator.git
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

*Note on `--build-pkg`:* The `--build-pkg` flag requires the `ForgeTool` C#/.NET binary toolchain vendored in `tools/forgetool`. If you are running outside of the devcontainer or CI environment, ensure the **.NET SDK 8** (`dotnet`), **mono-devel** (`mono`), and **libgdiplus** are installed so `tools/build_forgetool.sh` can build the helper binaries if needed. Standard CON file generation does not require `.NET` or `mono`.

  These are the **tested/pinned versions** — `ForgeTool.csproj` targets `.NET Framework v4.7.1`, so mono must ship the `4.7.1-api` reference assemblies (any mono 6.x, e.g. 6.14.1, does):
  * **macOS:** `brew install mono` (installs 6.14.1), `brew install mono-libgdiplus` (ForgeTool uses System.Drawing to read the CON's album art, and Homebrew's mono does **not** bundle libgdiplus; the `tools/forgetool` wrapper sets `DYLD_FALLBACK_LIBRARY_PATH` to Homebrew's lib dir automatically so mono can load it), and `brew install --cask dotnet-sdk@8` (SDK 8).
  * **Linux (Debian/Ubuntu):** `sudo apt install mono-devel libgdiplus` (libgdiplus is bundled with mono on Linux but installed explicitly to be safe; Debian 12 / Ubuntu 22.04+ ships mono 6.8+/6.12+) and the [.NET 8 SDK installer](https://dotnet.microsoft.com/en-us/download/dotnet/8.0) (`wget https://dot.net/v1/dotnet-install.sh -O /tmp/dotnet-install.sh && chmod +x /tmp/dotnet-install.sh && /tmp/dotnet-install.sh --channel 8.0 --install-dir /tmp/dotnet`).
  * `tools/build_forgetool.sh` checks for `dotnet`, `mono`, and `libgdiplus`, prints these install instructions if any is missing, and resolves mono's `4.7.1-api` reference-assembly path automatically (it must find `mscorlib.dll` under a `4.7.1-api` directory). Verify with `mono --version` (should be ≥ 6.0) and `dotnet --version` (should be 8.x).

### Installing from the release wheel (exact commands per platform)

Prefer the wheel for a quick install without the source tree. The release artifacts are `autorb-*.whl` (and `autorb-*.tar.gz`). The one step that trips people up is creating the venv with a **supported Python (3.11–3.13)** — bare `python3` on macOS is often the wrong version (stock 3.9.6 too old, or a newer 3.14 too new). Use the exact commands for your platform:

**macOS (Apple Silicon):**
```bash
brew install python@3.12                       # skip if already installed
/opt/homebrew/bin/python3.12 -m venv venv      # NOT bare python3 — that re-creates the venv on the wrong version
source venv/bin/activate
python3.12 -c "import sys; assert (3, 11) <= sys.version_info < (3, 14), 'Need Python 3.11–3.13 — recreate the venv'"
pip3 install ./autorb-*.whl
```

**macOS (Intel):**
```bash
brew install python@3.12                       # skip if already installed
/usr/local/bin/python3.12 -m venv venv
source venv/bin/activate
python3.12 -c "import sys; assert (3, 11) <= sys.version_info < (3, 14), 'Need Python 3.11–3.13 — recreate the venv'"
pip3 install ./autorb-*.whl
```

**Windows (PowerShell):**
```powershell
py -3.12 -m venv venv                          # the py launcher picks Python 3.12 (install from python.org if missing)
.\venv\Scripts\Activate.ps1
python -c "import sys; assert (3, 11) <= sys.version_info < (3, 14), 'Need Python 3.11-3.13 — recreate the venv'"
pip install .\autorb-*.whl
```

**Linux (Debian/Ubuntu)** — if `python3 --version` is already 3.11+ you can use `python3` in place of `python3.12`:
```bash
sudo apt install python3.12 python3.12-venv python3.12-pip   # or: sudo apt install python3 python3-venv python3-pip
python3.12 -m venv venv
source venv/bin/activate
python3.12 -c "import sys; assert (3, 11) <= sys.version_info < (3, 14), 'Need Python 3.11–3.13 — recreate the venv'"
pip3 install ./autorb-*.whl
```

Then run the pipeline (see [Quick Start](#-quick-start--usage)). The first install pulls the ML dependencies (PyTorch, Demucs, WhisperX, Basic-Pitch), so it takes a few minutes. On a bare wheel, everything except `--build-pkg` / the PS4 freestyle-vocals flag works out of the box; those need the vendored ForgeTool source — see the [Feature Support Matrix](#feature-support-matrix-where-each-feature-works) and the `--build-pkg` note above.

### Feature Support Matrix (where each feature works)

ForgeTool is vendored as **source only** — the compiled `.exe`/`.dll` binaries are gitignored and never shipped in the wheel. AutoRB patches to the ForgeTool source (e.g. `HasFreestyleVocals` for `--generate-freestyle-vocals`) therefore only reach users who build the tool from the vendored source. Everything that does not require ForgeTool works everywhere.

| Feature | pip wheel | git checkout (after `tools/build_forgetool.sh`) | devcontainer (auto-built) |
| :--- | :---: | :---: | :---: |
| CON generation (`.con`), stems, tempo, vocals, difficulty, count-in, MOGG, `songs.dta` | ✅ | ✅ | ✅ |
| `--build-pkg` (PS4 PKG) | ❌* | ✅ | ✅ |
| `--generate-freestyle-vocals` — PS4 guide lines | ❌* | ✅ | ✅ |
| `--build-clone-hero` (Clone Hero folder) + no-PS4 validation artifacts (`preview_mix.wav`, `lyrics_preview.srt`, `alignment_report.json`, `alignment_specs/`) | ✅ | ✅ | ✅ |

\* On a bare wheel install, `--build-pkg` fails fast with a clear message pointing you to `git clone` + `tools/build_forgetool.sh` (the wheel contains only the `autorb.*` Python packages; `_find_forgetool()` searches for `tools/forgetool` under the CWD, its parent, `sys.prefix`, and `sys.base_prefix`, so running the CLI from a clone's root also works against a wheel-installed `autorb`). `--generate-freestyle-vocals` still writes `(freestyle_vocals 1)` into the CON's `songs.dta` on a wheel, but that line has **no effect on PS4 without the patched ForgeTool** carrying it into the `songdta_ps4` `HasFreestyleVocals` flag — so on a wheel it is effectively a no-op for the intended feature.

**Propagation mechanics:**
- **Devcontainer:** every fresh container runs `.devcontainer/post-install.sh` (`postCreateCommand`), which installs .NET SDK 8 to `/tmp/dotnet` and runs `tools/build_forgetool.sh` — the patched tool is compiled automatically, feature works out of the box. The container image already ships `mono-devel` for running the built tool.
- **Git clone:** `git clone` gives you the patched source; run `tools/build_forgetool.sh` once (needs .NET SDK 8 + `mono-devel`) and run the CLI from the repository root (or anywhere within/near it — `_find_forgetool()` auto-discovers the tool by searching the CWD, its child dirs, and its ancestors). Re-run the script once on an existing clone to pick up newly committed patches.
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

### Troubleshooting `Package 'autorb' requires a different Python` (macOS)

If installing the wheel fails with something like:
`ERROR: Package 'autorb' requires a different Python: 3.14.6 not in '<3.14,>=3.11'`

Your `python3` is newer than AutoRB supports (Python 3.14 — WhisperX, a hard dependency, caps at `<3.14`, so the wheel's `Requires-Python` deliberately rejects it to fail fast instead of breaking later). This is not a broken wheel — the venv was just created with the wrong Python. Use the exact per-platform venv commands in [Installing from the release wheel](#installing-from-the-release-wheel-exact-commands-per-platform) (macOS Apple Silicon / Intel shown above) — the key is using the **explicit Homebrew path**, since bare `python3` will only re-create the venv on 3.14:

```bash
brew install python@3.12          # skip if already installed
rm -rf venv
/opt/homebrew/bin/python3.12 -m venv venv
source venv/bin/activate
python3 -c "import sys; print(sys.version)"   # should print 3.12.x
pip3 install ./autorb-*.whl
```

(The same check fires when `python3` is too *old* — macOS's stock 3.9.6 — with the message "3.9.6 not in '>=3.11'". On Intel Macs the Homebrew path is `/usr/local/bin/python3.12`; on Apple Silicon it is `/opt/homebrew/bin/python3.12`. `python3.13` also works if you have it installed.)

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
# Recommended: run from a directory OUTSIDE the repo clone to avoid import shadowing
# Use ABSOLUTE paths for all file arguments
python3 -m autorb.cli \
  /full/path/to/song.mp3 \
  --artist "Artist Name" \
  --title "Song Title" \
  --year 2024 \
  --genre "Alternative" \
  --lyrics /full/path/to/lyrics.lrc \
  --output-dir /full/path/to/output \
  --build-pkg
```

**Why run from outside the clone?** The pip wheel installs `autorb` as a package. If you `cd` into the repo clone, Python imports the local source instead of the installed wheel (shadowing), and features like the album art preview won't work. Running from a parent/sibling directory with absolute paths uses the true wheel install.

**ForgeTool discovery:** The `--build-pkg` flag requires the vendored ForgeTool (not in the wheel). `_find_forgetool()` auto-discovers it by searching:
1. Current directory + immediate child dirs (finds `./RockBandAutoSongLevelCreator/tools/forgetool` when run from parent)
2. All ancestor directories
3. `sys.prefix` / `sys.base_prefix`

So from `temp/` with the clone at `temp/RockBandAutoSongLevelCreator/`, it just works.

Your outputs will be generated in `/full/path/to/output/` (the `.con` file + `album_art_preview.png`) and `/full/path/to/output/pkg/` (the PS4 `.pkg` file).

#### Batch packaging: many CONs → one PS4 PKG

If you want a single PS4 PKG installer that contains **multiple songs**, run the pipeline as many times as you like (each run drops a `.con` into the same `--output-dir`), then run **one** command that gathers every `.con` in a folder and repackages them into a single multi-song PKG — no audio/lyrics inputs needed for that final step:

```bash
# 1) Generate the first song's CON (+ Clone Hero folder + freestyle vocals)
python -m autorb.cli \
  input/eve6-openRoadSong.mp3 \
  --lyrics input/eve6-openRoadSong.lrc \
  --output-dir ./output \
  --artist "Eve 6" \
  --title "Open Road Song" \
  --year 1998 \
  --genre "Alternative" \
  --generate-freestyle-vocals \
  --build-clone-hero \
&& python -m autorb.cli \
  input/barenakedLadies-brianWilson.mp3 \
  --lyrics input/barenakedLadies-brianWilson.lrc \
  --output-dir ./output \
  --artist "Barenaked Ladies" \
  --title "Brian Wilson" \
  --year 1992 \
  --genre "Alternative" \
  --generate-freestyle-vocals \
  --build-clone-hero \
&& python -m autorb.cli \
  --package-con-dir ./output \
  --ps4-pkg-id CPRIMEAUTORBDEV1
```

`--package-con-dir` switches the CLI into **batch packaging mode**: it parses every `.con` in the given directory, merges their `songs.dta` metadata into one shared file, rebuilds them into a single multi-song STFS CON, and hands that to ForgeTool to produce `./output/pkg/UP8802-CUSA02084_00-CPRIMEAUTORBDEV1.pkg`. Because it is a standalone repackaging step, `--package-con-dir` requires **none** of the pipeline inputs (`AUDIO_FILE`, `--artist`, `--lyrics`, …) — only the folder of `.con` files and an optional `--ps4-pkg-id`. The same 16-char ID rule applies (uppercase A–Z / 0–9, padded/truncated to 16); if omitted it is derived from the first `.con`'s song ID.

> Note: `--package-con-dir` ignores any `song_pack.con` it previously produced in that folder, so re-running it is safe.

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
| `--album-art` | Path | Optional. Custom album art image (PNG/JPG) for the CON's `_keep.png_xbox` texture. Defaults to a generated "Chris Prime Custom" cover (stacked CHRIS/PRIME text with an orange "BOT" badge in the top-right and a "CP" monogram in the top-left: a thick orange C forming the outer circle with a white P inscribed inside). The art's font is bundled with the package, so it renders legibly on any OS (no system font paths required). |
| `--skip-separation` | Flag | Skip AI stem separation; requires `drums.wav`, `bass.wav`, `vocals.wav`, `other.wav` in `[output-dir]/stems`. Optional `guitar.wav` / `piano.wav` are picked up when present and drive the guitar / keys charts directly (master-stems workflow). Nothing is ever cleared in this mode. |
| `--separator` | Choice | Stem separation model (default: `htdemucs_ft`). Options: `htdemucs_ft` — **DEFAULT**, full Demucs `BagOfModels` ensemble, 4 stems (drums/bass/other/vocals), best quality, ~16 min on 8 GB CPU; `htdemucs` — stock single model, 4 stems, fast (~1 min), lower quality; `htdemucs_6s` — single Demucs model, **6 stems** (drums/bass/other/vocals/**guitar**/piano); with it, `guitar.wav` drives the guitar chart and `piano.wav` the keys chart (both also mixed into in-game backing audio); piano stem quality is reportedly poor. `spleeter:5stems` — Spleeter TensorFlow model, 5 stems incl. piano (**⚠️ spleeter must never be pip-installed into this venv — dependency conflict; isolated venv only**). Every new separation run first clears stale `*.wav` from `[output-dir]/stems`, so switching separators never mixes stems between runs. `--use-ft-stems`/`--no-use-ft-stems` are deprecated aliases (on/off for `htdemucs_ft`/`htdemucs`; `--separator` takes priority if both given). Quality comparison (60 s Eve6 clip): `htdemucs_ft` bass↔other NCC 0.034 vs `htdemucs` 0.046; rhythm-guitar separation in `other` ~2× cleaner; vocals clearer; ~16 min vs ~1 min on 8 GB CPU. The `--ft-*` knobs (`--ft-shifts`, `--ft-strip-seconds`, `--ft-segment`, `--ft-overlap`) only apply to `htdemucs_ft` and `htdemucs_6s`. See `llm-wiki-kb/piano_keyboard_separation.md` for the full separator comparison. |
| `--ft-shifts` | Integer | Demucs translation-averaging passes for `--use-ft-stems` (default `1`). `shifts>1` averages shifted copies for marginally cleaner stems at N× time; measured on the 60 s clip that `shifts=2` gives **no** bleed/gain improvement over `shifts=1` (bass↔other 0.034 vs 0.034; drums↔other 0.084 vs 0.086), so `1` is the default (2× slower for nothing). Only applies with `htdemucs_ft` or `htdemucs_6s`. |
| `--ft-strip-seconds` | Float | Strip length (seconds) for `htdemucs_ft` (default `45`). Lower = less peak RAM (auto-falls back to 20 s strips if 45 s OOMs) at the cost of more inaudible strip-seams (10 s crossfade). Tune down only on memory-constrained CPUs. Only applies with `htdemucs_ft`. |
| `--ft-segment` | Float | Demucs internal segment length (seconds) for `htdemucs_ft` (default `None` = full-song context, highest quality). Small values (e.g. 10 s, 20 s) lower memory further but may degrade quality and slightly reduce drums↔other spectral bleed. Only applies with `htdemucs_ft`. |
| `--ft-overlap` | Float | Demucs STFT overlap ratio for `htdemucs_ft`/`htdemucs_6s` (default `0.25`). Higher values (e.g. `0.5`) give cleaner transients / slightly better bleed reduction at ~2× time and memory cost. Only applies with `htdemucs_ft` or `htdemucs_6s`. |
| `--ft-shifts` | Integer | Demucs translation-averaging passes for `--use-ft-stems` (default `1`). `shifts>1` averages shifted copies for marginally cleaner stems at N× time; measured on the 60 s clip that `shifts=2` gives **no** bleed/gain improvement over `shifts=1` (bass↔other 0.034 vs 0.034; drums↔other 0.084 vs 0.086), so `1` is the default (2× slower for nothing). Only applies with `--use-ft-stems`. |
| `--ft-strip-seconds` | Float | Strip length (seconds) for `--use-ft-stems` (default `45`). Lower = less peak RAM (auto-falls back to 20 s strips if 45 s OOMs) at the cost of more inaudible strip-seams (10 s crossfade). Tune down only on memory-constrained CPUs. Only applies with `--use-ft-stems`. |
| `--ft-segment` | Float | Demucs internal segment length (seconds) for `--use-ft-stems` (default `None` = full-song context, highest quality). Small values (e.g. 10 s, 20 s) lower memory further but may degrade quality and slightly reduce drums↔other spectral bleed. Only applies with `--use-ft-stems`. |
| `--ft-overlap` | Float | Demucs STFT overlap ratio for `--use-ft-stems` (default `0.25`). Higher values (e.g. `0.5`) give cleaner transients / slightly better bleed reduction at ~2× time and memory cost. Only applies with `--use-ft-stems`. |
| `--skip-tempo-detection` | Flag | Skip beat tracking; loads `tempo_map.json` from the output directory. |
| `--skip-vocals` | Flag | Skip WhisperX alignment and basic-pitch; loads `vocals_cache.json`. |
| `--skip-mogg` | Flag | Skip MOGG encoding; reuses the existing `.mogg` file (which is expected to already contain the count-in lead-in). The chart is still shifted past the count-in to match the reused audio. |
| `--generate-freestyle-vocals` | Flag | Enable Rock Band 4 **Freestyle Vocals** guide lines (Hard/Expert): writes `(freestyle_vocals 1)` into `songs.dta`, which the vendored (patched) ForgeTool carries into the PS4 `songdta_ps4` `HasFreestyleVocals` flag so the game advertises and draws the diatonic guide lanes. Off by default. Requires `--build-pkg` to take effect on PS4 (the flag lives in the PKG's songdta; the Xbox 360 CON's `songs.dta` is untouched by the game's freestyle check). |
| `--build-clone-hero` | Flag | Also export a **Clone Hero**-format song folder (`<output-dir>/clone_hero/<Artist> - <Title>/` with `song.ini` + `notes.chart` *and* `notes.mid` + `song.ogg` + `album.png`) for computer-based playtest — load the folder into Clone Hero (Settings → Open Default Songs Folder → Scan Songs) to review the vocal/lyric chart synced to audio without a PS4. The chart is count-in free so sync judgments transfer directly to the Rock Band chart. |
| `--freestyle-drums` | Flag | Create drum freestyle mode: drum track gets only one placeholder note at the start, allowing free drum play throughout the song (the drum track is unmuted for freestyle play). |
| `--package-con-dir` | Path | Batch packaging mode: package all `.con` files in this directory into a single PS4 PKG installer (multi-song pack). Does not require audio file or lyrics — skips the pipeline and goes straight to PS4 PKG creation. |
| `--ps4-pkg-id` | String | Optional. 16-character PS4 Content ID for the PKG (format: `UP8802-CUSA02084_00-XXXXXXXXXXXXXXXX`). Auto-generated from artist + title (lowercase alphanumeric, padded/truncated to 16 chars) if omitted. Use to ensure unique PKG IDs per song and avoid overwriting previously installed customs on PS4. |

---

## Previewing Results

### Previewing separated audio mix

To sum the separated audio tracks back together into a single audio file to hear what all tracks would sound like playing in-game in multitrack mode: 

```bash
python -m autorb.audio.mix_preview
```

Your stems in `output/stems` will be summed into `output/preview_mix.wav`

### No-PS4 sync validation & Clone Hero playtest

Every run emits local preview/validation artifacts — `preview_mix.wav`, `lyrics_preview.srt`, `alignment_report.json`, and annotated spectrograms in `alignment_specs/` (see [Key Features](#-key-features)). To playtest the chart on a PC:

```bash
python3 -m autorb.cli input/eve6-openRoadSong.mp3 \
  --artist "Eve 6" --title "Open Road Song" --year 1998 --genre "Alternative" \
  --lyrics input/eve6-openRoadSong.lrc \
  --output-dir ./output \
  --build-clone-hero
```

The song folder lands in `./output/clone_hero/Eve 6 - Open Road Song/` (`song.ini` + `notes.chart` + `notes.mid` + `song.ogg` + `album.png`). In Clone Hero: *Settings → General → Open Default Songs Folder*, copy the folder in, then *Settings → General → Scan Songs*. If it still doesn't appear, check the `badsongs.txt` file Clone Hero generates (it names the exact file it couldn't load) — after adding songs you must always press **Scan Songs** for changes to take effect. The `notes.chart` tempo markers are written as **integer plain-BPM** (drift-compensated) because Clone Hero's reader — a fork of Moonscraper's `ChartReader` — parses the `B` field with `uint.TryParse` and silently drops any fractional value, which would leave the chart with no tempo map and the song invisible. Full procedure in `llm-wiki-kb/local_preview_and_testing.md`.

#### Headless capture (devcontainer): load a song and screenshot a specific instrument at a specific time

The devcontainer ships a fully headless Clone Hero instance (Clone Hero running under **box64** on arm64, with **Xvfb** + a null-sink **PulseAudio** and an ALSA-seq shim so RtMidi can't crash Unity). This lets you render any AutoRB-exported song and grab a screenshot of the note highway for a chosen instrument, difficulty, and point in the song — no GPU, no display, no manual clicking. It is installed automatically when the devcontainer is built (`tools/setup_clone_hero_headless.sh` is run from the Dockerfile and `post-install.sh`).

Use the documented wrapper `tools/ch_capture.sh`:

```bash
# See the guitar chart at 1:15 on Expert:
tools/ch_capture.sh \
  --song "$PWD/output/clone_hero/Eve 6 - Open Road Song" \
  --instrument guitar --difficulty expert --at 75 \
  --out /tmp/guitar75.png

# Confirm the drums chart actually loaded (capture early):
tools/ch_capture.sh \
  --song "$PWD/output/clone_hero/Eve 6 - Open Road Song" \
  --instrument drums --difficulty expert --at 20 \
  --out /tmp/drums20.png
```

Arguments: `--song` (absolute path to the song folder, required), `--instrument` (`guitar`/`bass`/`drums`/`vocals`/`keys`, default `guitar`), `--difficulty` (`expert`/`hard`/`medium`/`easy`, default `expert`), `--at` (seconds into the song to capture, default 30), `--out` (PNG path, default `/tmp/ch_capture.png`). Clone Hero needs ~15 s to boot under box64, so `--at` values smaller than that are clamped up to the boot grace period. Behind the scenes it calls `tools/clone_hero_headless.sh`, which boots Xvfb + PulseAudio, launches Clone Hero straight into gameplay on the requested `-p <Instrument>,<Difficulty>`, waits, and captures one frame with `ffmpeg` x11grab.

Notes and gotchas:
- **Use an absolute `--song` path.** Under box64, Clone Hero resolves relative paths from its own binary directory and fails.
- **Keys will not appear** — Clone Hero has no playable keyboard instrument; only guitar, bass, drums, and vocals are visible. The `PART KEYS` track is still written for Rock Band / the MIDI.
- To set up the harness outside the devcontainer (or after a manual rebuild), run `bash tools/setup_clone_hero_headless.sh` (it is idempotent: it skips anything already installed, and verifies the Clone Hero download against a pinned sha256).
- For automated pass/fail (does the export load at all? did it render a non-blank frame? was it rejected via `badsongs.txt`?), use the load gate: `python -m autorb.testing.ch_runner --help` (the `run_load_gate()` function in `autorb/testing/ch_runner.py`). Mark related tests `@pytest.mark.devcontainer` — they are excluded from the default CI run because GitHub Actions has no X11/audio stack.

## Using Original Master Stems (For Bands/Artists)

If you have access to the original studio multitracks (stems) for a song, you can skip the AI audio separation step to achieve perfect, artifact-free audio in-game.

1. Create a `stems` folder inside your designated output directory (e.g., `./output/stems/`).
2. Place your 4 master audio files in this folder and name them exactly:
   - `drums.wav`
   - `bass.wav`
   - `vocals.wav`
   - `other.wav` (Synths, backing tracks, anything not drums/bass/vocals)
3. **Optionally** add dedicated stems for better charts and in-game audio:
   - `guitar.wav` — when present, drives the **guitar chart** directly (instead of being re-detected from `other.wav`) and is mixed into the in-game backing audio
   - `piano.wav` / keys stem — when present, drives the **keys chart**
4. Run the CLI tool with the `--skip-separation` flag:

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

--separator: **DEFAULT: htdemucs_ft.** Stem separation model. Options:
  - htdemucs_ft (default): Full Demucs ensemble, 4 stems (drums/bass/other/vocals), best quality. ~16 min on 8 GB CPU.
  - htdemucs: Stock single model, 4 stems, fast (~1 min), lower quality.
  - htdemucs_6s: Single model, 6 stems (adds guitar + piano). Splits guitar out of "other".
  - spleeter:5stems: TensorFlow Spleeter, 5 stems (adds separate piano).
Use --no-use-ft-stems (deprecated) as a shortcut for --separator htdemucs.

--ft-shifts / --ft-strip-seconds / --ft-segment / --ft-overlap: Tunables for htdemucs_ft and htdemucs_6s. --ft-shifts (default 1; shifts=2 gives no bleed improvement). --ft-strip-seconds (default 45; lower = less RAM). --ft-segment (default None = full context, best quality). --ft-overlap (default 0.25; 0.5 = cleaner transients at 2x time/RAM). Improves stem cleanliness but does NOT reduce the guitar bridge's ~23 re-strum attacks (the re-articulation is in the audio, not the bleed — see Known Limitations).

--skip-tempo-detection: Skips librosa beat tracking and loads tempo_map.json from the output directory.

--skip-vocals: Skips WhisperX alignment and basic-pitch extraction, loading vocals_cache.json from the output directory.

--skip-mogg: Skips MOGG audio container encoding and uses the existing `.mogg` file (which is expected to already contain the count-in lead-in). The chart is still shifted past the count-in to match the reused audio.

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
* Generate the release notes from user-facing sources (`tools/gen_release_notes.py`): a "What's Changed" section from this version's `CHANGELOG.md` entry, followed by the current README's Features / Known Limitations / Roadmap / Installation / Quick Start / Previewing / Master-Stems sections — so the notes always describe how to actually use the release. The same content ships as `RELEASE_NOTES.txt` inside the wheel and sdist (see `[tool.setuptools.data-files]` in `pyproject.toml`).

```bash
# Trigger a build release (the tag PREFIX must match the version in autorb/version.py,
# pyproject.toml, and CHANGELOG.md — currently 0.0.92; a free-form SUFFIX is allowed,
# e.g. v0.0.92test02, for test releases of the same version — the suffix is baked into
# the wheel/sdist filenames as a PEP 440 local version so test releases never collide
# with the final one)
git tag v0.0.92
git tag v0.0.92test02   # optional: a test release without bumping the version
git push origin v0.0.92
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
