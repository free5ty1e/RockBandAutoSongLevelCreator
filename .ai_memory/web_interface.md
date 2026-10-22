# Plan: AutoRB Web Interface (local-first control plane + GitHub Pages control surface)

**Status:** SHIPPED v0.1.23 (2026-10-05) — engine + UI + Pages + tests + a
real end-to-end run through the HTTP engine (ORS stems → CON + Clone Hero +
validation PASS). Two CLI blockers were found and fixed along the way (exit
codes, optional lyrics) — see CHANGELOG 0.1.23. Remaining user actions:
merge to main + enable GitHub Pages (Settings → Pages → Source: "GitHub
Actions"), see §9.
**Owner:** AutoRB
**Request (user, verbatim intent):** A web app interface to our pipeline script
with all the options in a user-friendly format. Investigate deploying to GitHub
Pages with it *actually live and usable* for users to chart their own Rock Band
songs by providing an MP3 (or individual stems) + optional LRC. A couple of
Choose File buttons + checkboxes + dropdowns + a text field or two. When the
process completes, a button to show the folder in the system's explorer. Support
Windows as well as Mac connecting to this website.

---

## 0. The honest feasibility assessment (read first)

The pipeline runs **Demucs stem separation + WhisperX alignment + Basic-Pitch /
ADTOF transcription + torch** on CPU — roughly **2 GB of model + RAM and
10–40 minutes of compute per song** on this 8 GB / 2-core devcontainer. That
cannot execute in a browser tab, and GitHub Pages is **static hosting only** —
no server-side execution, no Python, no ffmpeg, no file writes. Therefore the
only honest architecture for "actually live on GitHub Pages" is:

1. **GitHub Pages hosts the control surface** (the UI itself — HTML/CSS/JS,
   static). This is what the user asked for: file buttons, checkboxes,
   dropdowns, text fields, live job log, and results links. It works on any
   machine with a browser (Windows, macOS, Linux, phone).
2. **The user's own machine runs the engine** via a tiny local companion
   (`autorb-webui` / `webui/server.py`): FastAPI + uvicorn on
   `127.0. hosted_port` (`AUTORB_WEBUI_PORT`, default 7860). It serves the SAME
   UI (served at `/`), accepts uploads (MP3/stems/LRC/art), runs the real
   pipeline in a background thread with live progress, and exposes the outputs
   (CON/PKG/Clone Hero folder/art) for download, plus an **"Show in Explorer /
   Finder"** button that opens the job folder in the OS file manager
   (`os.startfile` on Windows, `open` on macOS, `xdg-open` on Linux).

   The GitHub Pages site is the same single-page UI: when it can't reach the
   local engine it shows a **"Connect to your AutoRB engine"** panel with
   instructions + one-click copy of the install/run command (`pip install -e
   . && autorb-webui`, or the repo's Dockerfile). No cloud, no uploads leaving
   the user's machine, no GPU bills, no privacy problems — and it matches the
   spirit of "site with buttons where users drop a song and get a chart".

**Why not a pure static "browser-based" pipeline?** Demucs/WhisperX/ADTOF
require PyTorch + heavy models; the full stack is ~2 GB of weights; a
browser-only version would mean rewriting the whole pipeline in WASM and
shipping models on Pages (100 MB-per-file hosting limits, 1 GB repo soft cap
— a non-starter). The local-engine architecture is the only one that can run
the *actual, current* pipeline unmodified.

**Windows + Mac support:** the engine is pure-Python (the repo's dependencies
are pip-installable on both; the devcontainer is for development). The UI
runs in any modern browser. "Show folder" uses `os.startfile` (Win) /
`open` (Mac) / `xdg-open` (Linux). We document Windows (PowerShell) and macOS
(Zsh) launch instructions directly in the UI.

---

## 1. Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  Browser (any OS)                                                  │
│  - static UI  (GitHub Pages OR http://127.0.0.1:7860/ from engine) │
│  - JS: form state -> POST /api/jobs (JSON) or upload via /api/upload│
│  - polls /api/jobs/<id> for progress; renders log tail + progress  │
│    bar + ETA; on success shows results + "Show in Explorer"        │
└────────────────────────┬───────────────────────────────────────────┘
                         │ HTTP (localhost, or user's LAN if they choose)
┌────────────────────────▼───────────────────────────────────────────┐
│  Engine: webui/server.py  (FastAPI + uvicorn, one per user machine) │
│  - POST /api/upload      multipart: audio / stems / lrc / art      │
│  - POST /api/jobs        start job (JSON options)                  │
│  - GET  /api/jobs/<id>   status/progress/log tail/results           │
│  127.0.0.1/localhost only by default (explicit env opt-in for LAN) │
│  - GET  /api/engines etc. (health, versions)                       │
│  - Static UI at /          (same index.html as the Pages site)     │
│  - ThreadPoolExecutor(1) → run_pipeline() — THE REAL autorb CLI     │
│    (subprocess with -u, line-buffered log capture, tmp→jobs dir)   │
│  - Job folder: webui_jobs/<job>/  (uploads + outputs + job.json)   │

┌────────────────────────────────────────────────────────────────────┐
│  GitHub Pages (free5ty1e.github.io/RockBandAutoSongLevelCreator/)  │
│  - docs/  → index.html (the SAME UI, minus engine-reachable state) │
│            + instructions panel + Windows/macOS install/launch      │
│  - .nojekyll so Pages serves the copied files as-is                │
└────────────────────────────────────────────────────────────────────┘
```

### Design principles
- **The UI is one `index.html`** with inline CSS/JS (no build step, no npm —
  matches the repo's zero-frontend-tooling convention and Pages' static
  hosting). It runs in two skins:
  - **Local mode** (engine reachable): full workflow.
  - **Pages mode** (engine unreachable): "connect to your engine" instructions
   + feature tour, same file.
- **The engine wraps the real CLI unchanged.** No forking of pipeline logic.
  We call `python -m autorb.cli ...` via subprocess with `-u` for unbuffered
  logs, capturing stdout+err to the job's log file. The CLI already prints
  `[1/5] ... [5/5] ...` stage markers, which the engine parses for progress.
  (Nice-to-have: cli could emit machine-readable progress; not required.)
- **Staged progress parsing**: the CLI prints known stage markers
  (`[1/5] Separating`, `[2/5] Extracting tempo`, `[3/5] Aligning vocals`,
  `[4/5] Synchronizing`, `[4b/5] Transcribing`, `[5/5] Building`, `[6/5] Clone
  Hero`, `[7/5] Validating/PKG`). Engine regex-maps each marker to a % and
  a friendly stage name; everything else appends to the log.
- **Jobs are isolated**: uploads land in `webui_jobs/<job_id>/uploads/`,
  outputs in `webui_jobs/<id>/output/`. A `job.json` records parameters,
  status, timings, log path, result paths, and exit code.
- **Concurrency = 1**: heavy models on 8 GB RAM — one job at a time; further
  jobs queue with status `queued`.
- **Never fabricate**: failures are fatal and shown in the UI with the real
  log tail; no placeholder charts ever ship (already enforced in the CLI).

---

##  Web UI options exposed (mapping to CLI)

| UI control | CLI arg(s) | Type / default |
|---|---|---|
| Audio file (MP3/WAV/FLAC/M4A) | positional `audio_file` | required unless stems uploaded |
| Stems ZIP or individual files | `--skip-separation` + stems dir | optional (guitar/piano optional) |
| LRC lyrics | `--lyrics` | optional |
| Artist / Title / Year / Genre | `--artist/--title/--year/--genre` | required-ish (title/artist required) |
| Album art | `--album-art` | optional PNG/JPG |
| Build PS4 PKG | `--build-pkg` | checkbox |
| Build Clone Hero folder | `→ --build-clone-hero` | checkbox (default ON in UI) |
| Freestyle vocals | `--generate-freestyle-vocals     | checkbox |
| Freestyle drums | `--freestyle-drums` | checkbox |
| Guitar solo charting | `--guitar-solo-charting` | checkbox (EXPERIMENTAL badge) |
| Stem separator | `--separator` dropdown | htdemucs_ft / htdemucs / htdemucs_6s / spleeter:5stems |
| Advanced: ft-shifts / ft-strip-seconds / ft-segment / ft-overlap | numeric fields | defaults 1 / 45 / None / 0.25 |
| Output name | job id (web) | auto |
| Show-in-Explorer button | engine `/api/jobs/<id>/reveal` | post-completion action |

**Required-field validation mirroring the CLI**: artist/title required; audio
file required unless (stems ZIP / 4 core stems) provided; lyrics optional
(now genuinely optional end-to-end — CLI blocker fixed, see §3).

---

## 3. Blockers found in the CLI — BOTH FIXED in v0.1.23

1. **`return 1`/bare `return` in the click callback does NOT set the process
   exit code** (verified experimentally AND live: a stems-mode job reported
   success/exit-0 while the CLI had refused to run — caught by the first e2e
   run through the engine). **Fix shipped:** every failure path now
   `sys.exit(1)` (missing args, missing stems, missing caches, step-4 sync,
   guitar transcription, validation FAIL, asset packaging). Regression
   tests: AST scan + subprocess exit-code checks in tests/test_webui.py;
   the older tests/test_cli_guitar_wiring.py pins updated to the same
   contract.
2. **`--lyrics` was effectively required** (the CLI `missing` check included
   it AND `process_vocals` opened the LRC unconditionally) while the README
   advertised a WhisperX no-LRC fallback that never existed. **Fix shipped:**
   `process_vocals(lrc_path=None)` transcribes the vocal stem (whisperx
   "small"/int8 — alignment refines timing anyway) and each segment becomes a
   lyric line; downstream machinery unchanged; LRC path byte-identical.
   `--year`/`--genre` also optional (explicit coalesce — `dict.get`'s
   default only fires on ABSENT keys, so None would write `year_released
   None` / crash `genre.lower()`). Plus: AUDIO_FILE positional optional with
   `--skip-separation` (stems-only workflow; `transcribe_drums` already
   handled a None mixed-audio source).

### Non-blocker notes
- **`spleeter:5stems` availability** — reported by `/api/capabilities`;
  the UI greys the dropdown option out when missing.
- **Batch packaging (`--package-con-dir`)** — out of scope for the web UI
  v1 (single-song focus). CLI-only.
- **Engine host security**: binds 127.0.0.1 by default; `AUTORB_WEBUI_HOST`
  opt-in for LAN (no auth in v1 — only on networks you trust). CORS allows
  all origins because the Pages-hosted UI (public origin) posts to the local
  engine; browsers' private-network-access restrictions still apply on
  their own schedule — the UI's connect panel + retry handles a blocked
  engine gracefully, and the engine also serves the same UI at `/` for the
  zero-CORS path.
- **Log tail polling**: single JSON endpoint per job returns status,
   progress %, stage name, log tail (last 64 lines), result file list, error.
   Poll every 1s.

---

## 4. File plan

```
webui/
  __init__.py            (empty)
  server.py              FastAPI app: routes, job manager, subprocess runner,
                         progress parser, reveal-in-explorer, static mount
  jobs.py                (in server.py to keep it simple; or split if >400 lines)
  reveal.py              os.startfile / open / xdg-open wrapper
  static/
    index.html           single-file UI (works from Pages AND from engine)
    (inline CSS/JS; no build step)
docs/                   → GitHub Pages site (index.html + assets copied/symlinked
                          from webui/static; .nojekyll)
.github/workflows/ci-cd.yml  (examine existing; add Pages deploy job if
                              Actions is the chosen Pages source)
tests/test_webui_server.py    API contract tests (TestClient, no heavy models:
                              upload→job→queue→status→result-files; reveal
                              endpoint; validation errors; static UI served)
```

**Docs deployment:** add a dedicated Pages-deploy workflow that copies
`webui/static/index.html` to the Pages artifact (or commit compiled docs/
into the repo at `docs/` and point Pages at `/docs`). Decision: point Pages
at `/ (root)` with an `index.html`? No — repo root has no index.html and the
repo's real README must stay authoritative; use `docs/` folder with `.nojekyll`
and Pages "Deploy from branch / (root) / (docs)" setting. The user must
enable Pages in repo settings (I cannot — gh write ops are forbidden). I'll
produce the files and a workflow so that if the user flips the Pages setting
to "GitHub Actions" or "Deploy from branch → main → /docs", it goes live.
Since I can't push (push is forbidden), the user pushes/merges to main and
enables Pages. Deliverable: `docs/` + workflow + instructions in the final
report.

## 5. Test plan

1. `tests/test_webui_server.py` — FastAPI TestClient tests:
   - GET / → serves index.html (200, contains "AutoRB")
   - POST /api/jobs with no audio → 422-style validation error JSON
   - POST /fictitious upload of tiny fake stems/audio → job queued →
     eventually runs (in tests, stub the runner to avoid 30-min Demucs)
   - POST /api/j Bringing a fake long log through the progress parser →
     assert % monotonic + stage names
   - parse_markers unit tests (each stage marker → expected stage/progress)
   - reveal endpoint unit test (monkeypatched subprocess/os.startfile)
   - Correct handling of CLI exit codes (runner records exit 1 on FAIL)
2. **CLI exit-code fix test**: subprocess-run a tiny script that invokes
   `cli.main` with a failing scenario? Simpler: assert `sys.exit` present in
   failure paths via AST scan (consistent with existing test style in
   test_cli_guitar_wiring.py AST scans).
3. partial / LRC handling: `process_vocals(lrc_path=None)` returns empty
   lyrics_data + word_segments from whisperx *transcription* (mock whisperx
   model load in test; monkeypatch `whisperx.load_model`, `whisperx.load_audio`,
   and `whisperx.align`... transcribe mode differs: `model.transcribe`)
   — cover both the LRC and no-LRC code paths with the alignment mocked.
4. Manually smoke the whole thing: start server, upload a real song, watch
   job run 30 min, check outputs. (Manual; I can run it here in devcontainer
   with real audio!)
   - NOTE: this is the ONLY true end-to-end validation; the automated tests
     stub the runner.
4. Final gate: run full pytest suite; stage all files; suggested commit msg.

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Pages hosting is static-only — no server-side processing | Architecture is local-engine + Pages-hosted control surface (§0) |
| CORS from Pages (public origin) to 127.0 going stricter (PNA) | Engine allows `*` origin; UI attempts fetch to 127.0.0.1:7860 and shows connect panel when blocked |
| 8 GB RAM, one job at a time | single-worker executor; queue; UI states queued |
| Users on Windows/macOS can't run devcontainer | Pure pip install; document `pip install -e .` + `autorb-webui` launch |
| `spleeter` not installed | detect at engine start; grey-out in dropdown via /api/capabilities |
 |
| ffmpeg absent on user machines | Document as prerequisite (Demucs/whisperx need it anyway) + /api/capabilities reports it |
| Private/proprietary songs | Files never leave the user's machine (local engine); privacy note in UI |
 |
| CLI exit-code bug means failed builds look successful | Fix #1 above (sys.exit) + runner checks exit code + log-marker failure regex |
 |

## 7. Tonight's build order

1. CLI exit-code fix (`sys.exit(1)` in the three failure paths) + AST test.
2. Optional-LRC plumbing (`process_vocals(lrc_path=None)` via WhisperX
   transcription mode; CLI drops lyrics from missing check) + tests.
3. Engine `webui/server.py` (FastAPI, upload, jobs, queue, progress, reveal).
4. Static UI `webui/static/index.html` (form + log + results + reveal + connect-panel).
5. Pages site `docs/` (copy of UI + instructions) + workflow.
6. Tests for engine + progress parser.
7. Full suite + integration smoke (real song through the engine on this box).
8. Stage everything, suggest commit message. (Never commit.)
```

## § API contract (as actually implemented, v0.1.23)

**POST /api/upload** (multipart) → `{"job_id": "<8hex>", "uploads": {...}}`
Files: `audio` (MP3/WAV/FLAC/M4A/OGG/AAC/WMA, ≤600 MB), `lrc` (.lrc/.txt,
≤2 MB), `album_art` (PNG/JPG, ≤20 MB), and EITHER `stems_zip` (one .zip with
drums/bass/other/vocals.wav [+ guitar/piano] at its root) OR repeated
`stems_files` (each named `<stem>.wav`, stem ∈ drums/bass/other/vocals/
guitar/piano). Creates a DRAFT job; paths are server-derived, never
client-supplied.

**POST /api/jobs/<id>/start** (JSON) → `{"job": {...}}`
`{"options": {artist*, title*, year?, genre?, separator?, build_pkg?,
build_clone_hero?, generate_freestyle_vocals?, freestyle_drums?,
guitar_solo_charting?, ft_shifts?, ft_strip_seconds?, ft_segment?,
ft_overlap?}}` — validated eagerly (bad input → 400 before anything runs);
stems are copied to `<job>/output/stems/` and core stems verified. Status
becomes `queued`.

**GET /api/jobs/<id>** → job record:
```json
{
  "id": "523fdc6b", "status": "running", "stage": "Separating stems",
  "progress": 0.15, "created_at": ..., "started_at": ..., "finished_at": null,
  "exit_code": null, "error": null, "uploads": {...}, "options": {...},
  "dir": "...", "output_dir": "...", "log_tail": ["last 400 lines"]
}
```
Statuses: draft → queued → running → success | failed | cancelled.

**GET /api/jobs** — list (newest first, no log tails).
**POST /api/jobs/<id>/cancel** — SIGTERM the pipeline (409 if finished).
**POST /api/jobs/<id>/reveal** — open the output folder in the OS file
manager; returns `{ok, message, path}` (never 500s on headless boxes).
**GET /api/jobs/<id>/files** — artifact list with `/files/<id>/output/...`
download URLs (CON, PKG, MIDI, MOGG, Clone Hero folder, reports).
**GET /api/capabilities** — `{cpu_cores, mem_total_gb, cuda, ffmpeg,
ffprobe, spleeter, adtof, os, python, autorb_version}` for UI grey-outs.

## 8. Post-v1 ideas (NOT tonight)
- Drag-and-drop staging area with per-file type inference
- Per-job config presets saved to localStorage
- Auth token for LAN mode (AUTORB_WEBUI_TOKEN)
- Dockerized one-liner for non-pip users
- Dynamic job progress from a JSON the CLI itself writes (machine-readable)
- Delete/retire old jobs from the dashboard (disk cleanup)

---

## 9. What the user must do to make the Pages site live (Claude cannot: git push/merge + repo settings are forbidden/owner-only)

1. Merge this branch to `main` and push (or commit the staged changes and
   push the branch, then merge).
2. Repo **Settings → Pages**: set **Source = "GitHub Actions"**.
   `.github/workflows/pages.yml` (already staged) deploys `docs/` on every
   push to main that touches `docs/`, `webui/static/`, or the workflow.
3. The site goes live at
   `https://free5ty1e.github.io/RockBandAutoSongLevelCreator/` (first deploy
   ~1 min after step 2).
4. To chart a song: run `pip install -e ".[web]"` then `python -m webui.server`
   locally; open the Pages URL (or `http://127.0.0.1:7860` directly).

---

## 10. What shipped (v0.1.23) — verification summary

- **Engine**: `webui/server.py` (FastAPI, upload → draft job, start → queued,
  single worker, subprocess CLI runner with live log/progress parsing,
  cancel, reveal, artifacts, capabilities), `webui/jobs.py` (job store,
  eager validation, CLI arg builder), `webui/progress.py` (stage/strip
  parser, monotonic progress), `webui/reveal.py` (Explorer/Finder/xdg-open).
- **UI**: `webui/static/index.html` (single file, inline CSS/JS, dark/light
  via prefers-color-scheme, drag+drop or click pickers, all CLI options,
  live log + progress, artifacts, show-in-explorer, Pages-mode connect
  panel with Windows/macOS commands, capability grey-outs).
- **Pages**: `docs/` (byte-identical copy of webui/static, enforced by a
  test + workflow guard) + `.github/workflows/pages.yml` (Actions-based
  deploy of docs/ with a sync guard step).
- **Packaging**: `[project.optional-dependencies] web`, console script
  `autorb-webui`, requirements.txt entries, `.gitignore` webui_jobs/, README
  Web Interface section + --lyrics help update.
- **CLI fixes**: exit codes on ALL failure paths (sys.exit(1)); optional
  --lyrics/--year/--genre; optional AUDIO_FILE with --skip-separation.
- **Tests**: 52 new (test_webui.py 48 + test_optional_lyrics.py 4);
  full suite 228 passed. Real e2e through uvicorn + real CLI subprocess:
  ORS stems upload → success → CON 14 MB + MOGG + Clone Hero folder +
  guitar validation PASS 17.46; reveal OK; cancel-when-finished 409;
  error paths exit 1 (the first e2e attempt caught the exit-code bug live
  — job "success" while the CLI had refused — proving the guard's worth).
