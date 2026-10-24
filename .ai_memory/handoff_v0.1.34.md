# Agent Handoff — AutoRB as of v0.1.34 (2026-10-24)

**For:** the next agent session, picking up after the v0.1.34 release validation.
**State:** v0.1.34 tagged, built, and validated green (CI audit 26 PASS / 0 FAIL;
local audit results appended at the bottom when complete). PRs #3 and #4 merged.
Working tree clean at 0.1.34. The user is starting a fresh session for the next
feature/improvement.

## 1. Read these first (they are the operating manual)

- **`CLAUDE.md`** — project instructions. Non-negotiables: the Release Rules
  (pre-tag checklist, "never claim a release is good without a green CI audit
  or passing local --strict audit"), the hook-enforced end-of-cycle workflow
  (validate → stage → suggest commit message; NEVER commit/push/tag yourself —
  git write ops are FORBIDDEN, the user does them), gh read-ops allowed
  (run list/view, release view/download; pr edit for titles/bodies).
- **`llm-wiki-kb/release_process.md`** — the full release pipeline, pre-tag
  checklist, audit stage table, and the audit-findings history.
- Memory files (`~/.claude/.../memory/`): `release-validation-workflow.md`
  (the tag→monitor→audit cycle), `webui-architecture.md` (engine/UI contracts),
  `guitar-strum-backbone-approach.md`, `bn-pipeline-oom-avoidance.md`,
  `strip-merge-position-aware.md`.

## 2. The release validation cycle (how "monitor and thoroughly validate" goes)

1. **Pre-verify the tag**: `git show vX:autorb/version.py` and spot-check the
   tagged tree contains the fixes (`git ls-tree -r vX --name-only`).
2. **Monitor the pipeline**: `gh run list` → Monitor on the run; jobs are
   test → build → release → **audit** (the audit is the gate: it runs
   `tools/audit_release.py --strict` and converts a real song through the
   wheel; a red audit means the release is NOT valid even if published).
3. **Pull the CI audit report** artifact (`release-audit-report`) and the
   `release-conversion-output` artifact (the benchmark's actual artifacts).
4. **Run the independent local audit**: `python tools/audit_release.py --tag
   vX --work-dir /tmp/auditX --strict` in the BACKGROUND (takes ~25 min —
   stage 5b converts BOTH the committed free benchmark AND any mp3+lrc pairs
   in git-ignored `tools/test_data/local/` — the user's Open Road Song files
   live there; local audits convert both songs). Poll the conversion_out_NN
   dirs for progress; don't sleep-loop on the log (it buffers).
5. Report PASS/FAIL tables per song (instrument note counts, CON/MOGG sizes).

**History**: the audit caught 9+ real release bugs, all the "works in the
devcontainer ≠ works in the release" class — see `release_process.md` § audit
findings. Two fully green releases so far: v0.1.33, v0.1.34 (+ their alpha01 tags).

## 3. The web architecture (v0.1.34 state — recently changed, don't regress it)

- **The control panel is served BY THE ENGINE** at http://127.0.0.1:7860
  (`python -m webui.server` / `autorb-webui`). Same-origin, everything works.
- **GitHub Pages (`docs/index.html`) is a LANDING PAGE ONLY** — install →
  start engine → open 127.0.0.1:7860. It must contain NO engine-calling code:
  Chrome's Private Network Access denies the public https origin the loopback
  address space, and uvicorn answers the PNA preflight with `400 Disallowed
  CORS private-network` — doubly unfixable. Enforced by
  `tests/check_pages_landing.py` (runs in pages.yml AND the pytest suite; the
  docs/↔webui bytesync contract was INVERTED into a must-differ check).
- pages.yml uses `configure-pages@v5` with `enablement: true` (a missing
  Pages site self-heals) and triggers ONLY on main pushes — a Pages change
  can only be fully tested by merging to main, then validating the live site
  (curl content == docs/index.html, Playwright render + link checks).
- **Web app UI contracts** (regression-tested in tests/test_webui.py — browser
  tests self-skip without Playwright, all run in this devcontainer): native
  `<label>` drop zones + off-screen inputs, section-0 output folder with the
  engine-fs Browse dialog, click-to-copy output-path chip on job finish,
  busy-state greys all action buttons for the whole run, CMD/CTRL+V paste
  fallback, headless-honest reveal. The engine wraps the REAL CLI as a
  subprocess (never re-implements pipeline logic).

## 4. Validation status as of this handoff

- **v0.1.34 release**: all 4 CI jobs green (test 4m19s / build / release /
  audit 18m23s — the audit includes the fresh-venv install + benchmark
  conversion). CI audit report: 26 PASS / 0 FAIL; benchmark charted
  GUITAR=882 / DRUMS=567 / BASS=300 through the wheel.
- **GitHub Pages**: deploy green on the merge (12s). Live site validated:
  HTTP 200, byte-identical to docs/index.html, 3-step getting-started renders
  (h2 "1 · Install" / "2 · Start the engine" / "3 · Open the control panel"),
  content accuracy verified against reality (install cmd, engine address, CLI
  flags, Python 3.11–3.13 claim, README link, zero engine-calling JS),
  .nojekyll deployed, no page errors or failed requests.
- **Local web app**: full browser smoke passed (caps line, output-folder
  display, htdemucs_6s default, upload → job run → log streams → output-path
  chip shows the job dir).
- **Local audit (benchmark + ORS)**: running at handoff time; results
  appended below when done. Expect ~28 PASS / 0 FAIL (prior runs:
  v0.1.32-alpha01 26 PASS, v0.1.33-alpha01 28 PASS / 0 FAIL).
- Test suite: 305 pass locally (full: `python -m pytest tests/ -q --deselect
  tests/test_quality_validation.py::TestSyncedTrackQuality`).

## 5. Known sharp edges (gotchas that have bitten before)

- **CLI failure paths MUST `sys.exit(1)`** — a bare `return` in a click
  callback exits 0 and the web engine reads failures as successes.
- **`[tool.setuptools].packages`**: every new package must be listed there
  AND in the CI wheel-content check AND in the audit tool's EXPECTED_IMPORTS
  — the editable install masks a missing entry forever (v0.1.30 nearly
  shipped wheels with no instrument charting).
- **Fresh-install breaks**: never add a dependency whose BUILD imports
  `pkg_resources` (crepe/madmom class); the devcontainer masks these until
  a tag build. Always verify with a fresh-venv install before tagging.
- **Copyright**: NEVER commit copyrighted audio. Test fixtures = the free
  benchmark only; local songs go in git-ignored `tools/test_data/local/`
  (enforced by `test_no_copyrighted_material_in_committed_tree`).
- **Instrumentals / no-detectable-vocals songs** chart an empty vocal track
  (fixed v0.1.32; two separate empty-array IndexErrors were the bug).
- **Stage 6 of the audit** compares the TAG's version.py (via `git show`), not
  the working tree — tree drift is a WARN, never a FAIL (fixed after a
  false-failure on v0.1.32-alpha01).
- **`gh release download` needs the asset NAME** (URLs percent-encode `+`),
  and `--clobber` for idempotent re-runs.
- The audit's stage-1 "run still in_progress" WARN is expected when the audit
  runs inside its own CI pipeline (its own run is the only one) — harmless.
- **8 GB host**: full-song Demucs ~16 min; the local audit's two conversions
  take ~25 min total. Use `--skip-separation` on cached stems for fast
  re-charting when iterating (see bn-pipeline-oom-avoidance memory).

## 6. Where to go next (candidates from ROADMAP.md + open threads)

- LRC-line phrase source of truth (roadmap: "highest priority") — phrase
  boundaries from LRC lines; the 2-bar fallback remains for no-LRC.
- Guitar chart quality iteration (user: "could use some more closed-loop
  iteration involving the error quantification") — the tab-validation loop
  (`tools/guitar_tab_alignment/`) is the harness.
- Drum-roll support beyond Expert 1/16 (roadmap item); bass double-stop
  detection (roadmap item).
- Missing-lyrics detection & filling (roadmap: detect sung-but-uncharted
  regions like the ORS ad-lib "YEAHHHHH!").
- `--guitar-solo-charting` is EXPERIMENTAL and default-off; needs playtest
  validation before promoting.
- PS4 known issues (roadmap): song-list preview silent; pause/resume freeze
  (MOGG seekability).

## 7. Quick reference

| Thing | Command |
|---|---|
| Full test suite | `python -m pytest tests/ -q --deselect tests/test_quality_validation.py::TestSyncedTrackQuality` |
| Local release audit | `python tools/audit_release.py --tag vX --work-dir /tmp/auditX --strict` (background; ~25 min) |
| Fetch benchmark song | `bash tools/test_data/fetch_benchmark.sh` (idempotent) |
| Add local test songs | `cp song.mp3 song.lrc tools/test_data/local/` (git-ignored) |
| Engine | `python -m webui.server` → http://127.0.0.1:7860 |
| Pages site | https://free5ty1e.github.io/RockBandAutoSongLevelCreator/ |
| Release notes gen | `python tools/gen_release_notes.py --tag vX` |
| Clone Hero capture | `tools/ch_capture.sh --song <dir> --instrument guitar --at 75 --out /tmp/x.png` |

---

## Appendix: v0.1.34 local audit results (filled when the background run completes)

**Local audit (completed 2026-10-24): 28 PASS / 0 FAIL / strict exit 0.**
Both benchmark tiers converted end-to-end through the v0.1.34 wheel:
- Tisk Tisk Sadness (free benchmark, no LRC): GUITAR=770, DRUMS=579, BASS=300; CON 3.22MB, MOGG 3.00MB
- Open Road Song (local, with LRC): GUITAR=3216, DRUMS=2195, BASS=3016; CON 14.0MB, MOGG 13.6MB
The one WARN is the informational transitive-imports note (expected). **v0.1.34 is fully validated.**
