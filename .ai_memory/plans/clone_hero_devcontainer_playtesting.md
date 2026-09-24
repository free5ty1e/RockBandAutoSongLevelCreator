# Clone Hero Devcontainer Closed-Loop Playtesting

**Status:** Phase 0 COMPLETE — headless CH running, songs load, audio plays, lyrics render and advance. Phase 1 (loadability gate) ready to codify.
**Targets:** `.devcontainer/` (Dockerfile + post-install.sh), new `autorb/testing/` package, ROADMAP
**Owner:** AutoRB agent loop (no user involvement after initial install)

## 1. Goal

Run **Clone Hero (Linux) inside the devcontainer, headlessly**, so the agent can:

1. **Load-test exports** — verify a generated song folder is accepted by CH (no `badsongs.txt` rejection, chart parses, song starts).
2. **Audit audio/note/lyric sync** — "play" the song and measure, per word, when CH highlights each lyric vs when our chart intends it to be highlighted, using the game's own parser + renderer (the ground truth the user plays against), instead of our static MIDI/audio cross-checks.
3. **Iterate closed-loop** — run the audit after every pipeline change, no user on a console needed.

This directly de-risks the open ROADMAP sync work ("tighten the remaining early/late per-word outliers") and the v0.0.90 mystery (a chart that *looked* valid was rejected by CH at scan time — only a real CH instance could have caught that).

## 2. Why a real game instance is worth it

| Capability | Today (static, no CH) | With CH in container |
| --- | --- | --- |
| Chart file syntax (`.chart`/`.mid`) | ✅ parsehero + mido cross-check | ✅ plus CH's actual parser |
| Song appears in song list | ❌ unknown until user scans | ✅ launch + screenshot |
| `badsongs.txt` rejection | ❌ | ✅ direct |
| **Lyric highlight sync vs audio** | ❌ inferred only | ✅ measured from the rendered game |
| Tempo-map drift end-to-end | ✅ computed | ✅ confirmed in-game |
| Playability feel | ❌ | partial (via bot player) |

## 3. How CH plays our chart (what we're auditing)

CH parses `notes.chart`/`notes.mid` + `song.ogg` from one folder, builds its own tempo map from the `B`/`set_tempo` events, and advances the **lyric highlight** (the sung word turns white/colored) according to that tempo map *while the audio plays*. So the on-screen highlight time of each lyric, relative to the audio, **is** the end-to-end sync our whole pipeline exists to get right. Measuring it in-game is the definitive audit.

## 4. Researched facts (June 2026)

- **The Linux build is a self-contained Unity standalone**, ~1.1 GB. No .NET needed to *run* the game (the .NET runtime is only for the separate online server + Windows launcher).
- **Download** (official release, current as of 2026-06-01):
  - URL: `https://github.com/clonehero-game/releases/releases/download/v1.1.0.6142-final/Linux.x86_64-Standalone.tar`
  - SHA-256: `572971d93092283c5d0d52006a26b52ab8e8fb128dcfb42a3496de26c8aa231d`
  - Contents: extract → `./clonehero` executable (needs `chmod +x`).
- **Runtime deps (AUR/community packaging):** `alsa-lib`, `gcc-libs`, `gtk3`, and an ALSA bridge (`pulseaudio-alsa` or `pipewire-alsa`) for audio. Unity needs GL (OpenGL/EGL) or Vulkan for rendering — in a headless container that means Mesa **llvmpipe** (GL) and/or **lavapipe** (Vulkan).
- **Data locations (Linux):** scores + song cache live in `~/.config/unity3d/srylain Inc_/Clone Hero`. The **Songs** folder is user-configurable inside the game (we'll point it at a gitignored workspace folder).
- **CLI launch args (official, this is the key unlock):**
  - `-s / --song <folder>` → auto-load a song folder and go straight into it (no UI navigation needed).
  - `-p / --player <instrument>,<difficulty>` → add bot players (Guitar/Bass/Rhythm/GuitarCoop/6-Fret/Keys/Drums/ProDrums; **no Vocals tag exists** — irrelevant, playback doesn't require a player; a single bot on the placeholder Guitar track is a safe default so the highway renders).
  - `-i` instrument names, `-v` versus, `--profile <name>`.
  - This removes the need for xdotool menu navigation entirely for the core loop.
- **Audio:** CH uses **BASS** (`Bass: 2.4.18.0 BassFx: 2.4.12.6 BassMix: 2.4.12.0`); on Linux it wants ALSA. A headless container has no sound card — we give it **PulseAudio with a null sink** (`module-null-sink`), which BASS opens as a real device whose clock advances in real time. Open question for the spike: whether BASS falls back gracefully if no device is present (it may) — the null sink is the safe path.

## 5. Installation & persistence

**Choice: bake CH into the Docker image** (option A below), because it is a ~1.1 GB, immutable, version-pinned binary — the exact thing Docker layers exist for. A fresh container then has CH instantly, no re-download.

### Option A (recommended) — Dockerfile bake
- Add to `.devcontainer/Dockerfile`:
  - `apt-get install` headless runtime deps: `xvfb mesa-utils libgl1-mesa-dri libgl1 libegl1 libgles2 libvulkan1 mesa-vulkan-drivers pulseaudio pulseaudio-utils tesseract-ocr x11-apps dbus` (plus `libgtk-3-0`).
  - A `RUN` that downloads the pinned tar, verifies sha256, extracts to `/opt/clonehero`, `chmod +x /opt/clonehero/clonehero`, deletes the tar (layer stays in the image; `apt-get clean`).
- Pin the URL + sha256 in the Dockerfile with a comment, so an upstream release change is an intentional, reviewed edit.

### Option B — post-install.sh download
- Falls back to `post-install.sh` if we ever want to avoid the image weight; re-downloads ~1.1 GB per fresh container. Acceptable but wasteful. Keep the same `setup_clone_hero_headless()` function in a shared script (`tools/setup_clone_hero_headless.sh`) used by both the Dockerfile and post-install, so the logic lives once.

### Persistence
- **CH binary** → image layer (option A). Nothing to persist.
- **Songs** → CH Songs dir set to `<workspace>/.tmp/clone-hero/Songs` (already gitignored). Each audit copies the export folder in (a song folder is a few MB: `song.ogg` + PNGs + chart). No cross-container persistence needed.
- **CH settings/cache** (`~/.config/unity3d/srylain Inc_/Clone Hero`) → regenerated on first run; to skip the "first-launch settings dialog" during automation, the runner pre-creates the config dir with a minimal known-good config and `--profile` as needed (spike detail).

## 6. Headless runtime environment (the spike's core)

Everything runs under a virtual X display:

```bash
Xvfb :99 -screen 0 1920x1080x24 -ac &
export DISPLAY=:99
export LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe   # GL via software
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.x86_64.json  # Vulkan via lavapipe, if Unity needs it
# virtual audio device whose clock runs in real time:
pulseaudio -D --exit-idle-time=-1 --load="module-null-sink sink_name=ch_sink sink_properties=device.description=CloneHeroHeadless"
export PULSE_SERVER=unix:/tmp/pulse/native PULSE_SINK=ch_sink
```

Launch: `/opt/clonehero/clonehero --song "<song folder>" -p Guitar,Expert`

**Spike acceptance:** process stays alive > 60 s, `xdotool search --name "Clone Hero"` (or `xwininfo -root -tree`) shows a window, an ffmpeg `x11grab` frame shows the song highway (not a black screen), and BASS logged no fatal audio error. Unity games sometimes hard-require Vulkan — the env above provides both paths; the spike resolves which one CH takes on llvmpipe/lavapipe.

## 6b. Actual Findings (August 2026 — Phase 0 Complete)

**Environment**: Debian 13 (trixie) arm64, devcontainer `mcr.microsoft.com/devcontainers/python:3.11`, user `vscode`, sudo passwordless.

| Component | Status | Notes |
|-----------|--------|-------|
| **CH binary** | ✅ Working | v1.1.0.6142-final x86_64 standalone, extracted to `/opt/clonehero` |
| **Architecture** | ✅ Box64 | Built v0.4.5 from source (`/usr/local/bin/box64`, libs at `/usr/lib/box64-x86_64-linux-gnu/`) |
| **Multiarch libs** | ✅ Installed | `libasound2t64:amd64 libasound2-plugins:amd64 libgl1-mesa-dri:amd64 mesa-vulkan-drivers:amd64 libgcc-s1:amd64 libstdc++6:amd64 libgtk-3-0t64:amd64` |
| **Graphics** | ✅ llvmpipe | `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe`, `-force-glcore` (OpenGL 4.5 Core Profile, Mesa 25.0.7) |
| **Audio** | ✅ PulseAudio null sink | `XDG_RUNTIME_DIR=/tmp/ch_pulse`, `PULSE_SERVER=unix:/tmp/ch_pulse/pulse/native`, `ch_sink` active, audio verified recording |
| **MIDI/ALSA seq** | ✅ Shimmed | `/dev/snd/seq` blocked by device cgroup → `BOX64_LD_PRELOAD=/opt/clonehero/alsa_seq_shim.so` (52 symbols, x86_64) |
| **CH settings** | ✅ Configured | `~/.clonehero/settings.ini` `[directories] path0 = /workspaces/RockBandAutoSongLevelCreator/output_fresh/clone_hero` |
| **Song loading** | ✅ Via `--song` | **Must use absolute path**; relative path fails with NRE. `--song "/full/path/to/song"` works. |
| **Gameplay** | ✅ Verified | Process alive > 120s, lyrics render (OCR: "hit eighty on the open road", "'Cause it's so perfect..."), lyrics **advance** over time, audio flows (RMS 0.029, peak 0.13 from 12s recording) |
| **Bot player** | ✅ Working | `-p Guitar,Expert` spawns bot; placeholder Guitar track with 4 notes works |

**Key blockers resolved:**
1. **`/dev/snd/seq` EPERM** → Box64 ALSA-seq shim (51+ symbols), preloaded via `BOX64_LD_PRELOAD` (not `LD_PRELOAD`).
2. **Graphics segfault** → `-force-glcore` forces OpenGL 4.5 core on llvmpipe.
3. **`--song` relative path NRE** → Use absolute path; CH resolves relative paths from its working dir (`/opt/clonehero` under box64), not the shell CWD.
4. **Empty song library** → Set `[directories] path0` in `~/.clonehero/settings.ini` to the parent of song folders.
5. **"Failed to find SongScan game object"** → Benign warning; startup scan disabled but `--song` absolute path bypasses it.

**Artifacts produced in `/tmp/opencode/`:**
- `alsa_seq_shim.c` — versioned shim source (52 intercepted `snd_seq_*` symbols, rebuilt from spec)
- `ch_verify/` — frames + OCR text + audio recording proving end-to-end sync
- `shimtest/seq_probe` — validates `snd_seq_open` returns 0 + valid handle

**Next step:** Phase 1 — codify into `tools/setup_clone_hero_headless.sh` + `tools/clone_hero_headless.sh`, wire into `.devcontainer/Dockerfile` + `post-install.sh`.

## 7. The audit loop (phased implementation)

### Phase 0 — Feasibility spike (blocking, ~1 session)
Install (option A) + headless launch + capture one frame + confirm audio init. Deliverable: a working `tools/clone_hero_headless.sh` that starts Xvfb+Pulse+CH and screenshots. If Unity refuses to render under llvmpipe/lavapipe, pivot to **Risk R1** (below).

### Phase 1 — Loadability gate (replaces manual "did it appear in the song list")
`python -m autorb.testing.ch_load_gate --song <folder>`:
1. Launch CH with `--song`, wait for the song to start (or a timeout).
2. Assert the song folder is **not** listed in `badsongs.txt` (CH appends rejected folders there at scan/load).
3. Screenshot a frame; assert the highway/lyric bar rendered (pixel variance > threshold in the lyric region).
4. Exit CH cleanly; report PASS/FAIL. This alone would have caught the v0.0.90 integer-BPM bug the day it was made.

### Phase 2 — Playthrough capture
`ffmpeg -f x11grab -framerate 30 -i :99 -f pulse -i ch_sink.monitor -c:v libx264 -c:a aac capture.mp4` while CH plays the song through (real time, ~3 min for Open Road Song). Record the wall-clock launch time.

### Phase 3 — Sync auditor
`python -m autorb.testing.ch_playthrough_audit --video capture.mp4 --words <alignment_report.json> --output <dir>`:
1. **Audio-align the capture:** cross-correlate the capture's audio track against the exported `song.ogg` to get an exact mapping `video_frame ↔ song_time` (kills wall-clock/audio-clock drift concerns).
2. **Locate the lyric region:** known-good screen layout (spike) → crop the lyric bar band.
3. **For each word:** at its intended highlight time, OCR the cropped bar (tesseract, `--psm 7`, large high-contrast font → high accuracy) and/or diff against a rendered template of that lyric; the expected word is highlighted ≈ when it is OCR-matchable at maximum brightness/color.
4. **Emit `ch_sync_report.json`** in the same shape as `alignment_report.json` (per-word observed vs expected delta, median/p90/max, early/late lists) + annotated PNGs of worst outliers.
5. Both a PASS (`p90 ≤ threshold`) and a data table for the sync-improvement roadmap.

### Phase 4 — Regression wiring
Wrap Phases 1–3 in one entry point `python -m autorb.testing.clone_hero_audit --song <folder> --words <json> --output <dir>`, and add a `@pytest.mark.devcontainer` test that rebuilds the chart and runs the audit. **Not** part of default `pytest`/CI (GitHub Actions lacks the X11/audio stack); it's the devcontainer loop's tool.

### Phase 5 — Feed results back
Outlier words from `ch_sync_report.json` drive the existing sync roadmap items; every future pipeline change re-runs Phase 4 in the container.

## 8. New tooling (proposed layout)

- `tools/clone_hero_headless.sh` — env bootstrap (Xvfb/Pulse/CH), shared by Dockerfile bake check and runtime.
- `autorb/testing/ch_runner.py` — launch/quit, badsongs.txt gate, frame capture.
- `autorb/testing/ch_playthrough_audit.py` — audio alignment, lyric-region OCR/template diff, report + PNGs.
- `autorb/testing/__main__.py` → `clone_hero_audit` CLI.
- No new hard deps beyond what exists (pillow, numpy, matplotlib, ffmpeg) + container `tesseract-ocr`.

## 9. Risks & mitigations

- **R1 — Unity won't render headless on software GL/Vulkan.** Most likely failure point. Mitigations: try both `LIBGL_ALWAYS_SOFTWARE=1` and lavapipe (`VK_ICD_FILENAMES=lvp`); try `GDK_BACKEND=x11`; try `WINEDLLOVERRIDES`? (no — native build). If all fail: **YARG** (fully open-source CH-format player) as the renderer/parser under test, documented as not-quite-CH. This is why Phase 0 gates everything.
- **R2 — BASS refuses no-device audio → song won't start or clock misbehaves.** Mitigation: PulseAudio null sink (`module-null-sink`) as the primary plan; also test plain `--song` with no players to confirm playback doesn't require input focus.
- **R3 — Capture audio/clock drift.** Mitigation: Phase 3 step 1 (cross-correlate capture audio to `song.ogg`) makes frame↔song-time exact regardless of capture drift.
- **R4 — OCR brittleness.** Lyrics are rendered large and high-contrast; restrict to the lyric-bar crop, use template-matching against our own rendered text as a secondary signal. Outliers annotated as PNGs for eyeballing.
- **R5 — Image bloat.** +~1.5 GB image. Mitigation: it's devcontainer-only (not the wheel, not CI), version-pinned, and gives the loop a capability nothing else can.
- **R6 — Upstream CH release changes.** Pin URL+sha256 in the Dockerfile; updates are explicit one-line bumps re-verified by the spike script.
- **R7 — CH rejects some export at scan time (the class of bug we're chasing).** That's the *point* of the gate — a rejected song is a correct FAIL, not a false negative.

## 10. Acceptance criteria (Definition of Done)

1. `tools/clone_hero_headless.sh` starts Xvfb + Pulse null sink + CH on a fresh devcontainer with **no user interaction**, and a screenshot shows the song highway. (Phase 0)
2. A known-good export passes the load gate; a deliberately broken one (e.g. fractional-BPM chart) is caught by `badsongs.txt`/missing-render — proving the gate has teeth. (Phase 1)
3. `clone_hero_audit` produces `ch_sync_report.json` + annotated PNGs for Open Road Song with a plausible per-word delta distribution (median near 0, few outliers). (Phases 2–3)
4. The audit is re-runnable end-to-end as one command after any pipeline change, and is wired into the ROADMAP sync iterations. (Phases 4–5)
5. Docs updated: README testing section, `llm-wiki-kb/local_preview_and_testing.md`, CHANGELOG, `.ai_memory/plans` pointer.

## 11. Ordering vs other roadmap work

- Not a blocker for any feature work — it's a **testing capability** that runs in the background of sync iteration.
- Unblocks: "Lyric/audio sync improvements", "vocal phrase management", "chart-file preference verification" (can resolve `.chart` vs `.mid` preference empirically once CH loads both).
- Depends on: nothing new from the pipeline; uses existing `--build-clone-hero` output.

## 12. References

- Clone Hero releases (official GitHub org): `https://github.com/clonehero-game/releases/releases` — latest `v1.1.0.6142-final` (2026-06-01), asset `Linux.x86_64-Standalone.tar`.
- CH wiki — Installation (Linux): `https://wiki.clonehero.net/books/clone-hero-manual/page/installation`
- CH wiki — Data Locations (Linux): `~/.config/unity3d/srylain Inc_/Clone Hero`
- CH wiki — **Chart Previews via the Command Line** (`-s/--song`, `-p/--player`): `https://wiki.clonehero.net/books/clone-hero-manual/page/chart-previews-via-the-command-line`
- CH wiki — Common Issues (`badsongs.txt` behavior)
- Flathub community package: `net.clonehero.CloneHero` (fallback install source)
- YARG (open-source CH-format player, fallback if Unity can't render headless)
