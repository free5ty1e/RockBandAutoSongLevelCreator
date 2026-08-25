# Handoff: htdemucs_ft quality tuning (v0.1.11 → v0.1.12)

Context for the next agent taking over the `--use-ft-stems` quality work. The
exploring agent ran a 5-config A/B experiment, found the single-submodel unwrap
was the bleed bug, switched to the full ensemble through sectioned strips, and
staged the fix as **v0.1.12**. Everything below is the literal state of the repo
right now — no further action has been taken.

## 1. Repo state (authoritative: `git diff HEAD --stat`)
Exactly 7 files differ from HEAD, all **staged** (`git add` done):
```
CHANGELOG.md            (+5, v0.1.12 entry)
README.md               (+7, CLI table updated)
autorb/audio/stems.py   (+98/-54, full ensemble + apply_kwargs threading)
autorb/cli.py           (+11/-3, --ft-shifts/--ft-strip-seconds/--ft-segment)
autorb/version.py       (__version__ = "0.1.12")
llm-wiki-kb/instrument_charting.md  (version-history tail updated to v0.1.12)
llm-wiki-kb/log.md      (v0.1.11/0.1.12 entries)
```
- Tests: `pytest -q` → **159 passed, 4 skipped, 4 xfailed** (the 4 xfailed are
  pre-existing v0.1.9 strict=True vocal-sync TDD guards; not touched by this work).
- No untracked or unstaged changes vs the index.
- `output_ab/`, `.tmp/`, `output_ft/` are all in `.gitignore` (verified via
  `git check-ignore`) — the ~140 MB of experiment artifacts are on disk but
  **excluded from any commit**.

## 2. What changed and WHY (the actual bug)
`separate_stems(model_name='htdemucs_ft')` used to unwrap the `BagOfModels`
ensemble to `model = model.models[0]` "to fit CPU RAM". The sub-models are **not**
interchangeable: that one sub-model weakens bass (stem RMS 0.031 vs 0.052) and
bleeds bass↔other **5× worse** (NCC 0.172 vs 0.034 on the 60 s clip).
Fix: run the **full ensemble** through the v0.1.11 45 s strip-sectioning
(`_separate_strips`) — strips bound peak memory to one strip (~2.3 GB on the 198 s
track on an 8 GB box), so the ensemble fits without the unwrap.

## 3. Experiment results (60 s Eve6 clip, NCC off-diagonal = bleed; lower = cleaner)
Artifacts: `output_ab/cfg/<cfg>/{stems/*.wav, preview_mix.wav, ncc.json}`
| config | model | shifts | bass↔other NCC | drums↔other NCC | bass RMSE |
|---|---|---|---|---|---|
| stock1 | htdemucs | 1 | 0.046 | 0.085 | 0.052 |
| ft_single1 | ft, 1 sub-model | 1 | **0.172** | 0.076 | 0.031 |
| ft_single2 | ft, 1 sub-model | 2 | 0.174 | 0.078 | 0.031 |
| **ft_ens1** | **ft, full ensemble** | 1 | **0.034** | 0.084 | 0.052 |
| ft_ens2 | ft, full ensemble | 2 | 0.034 | 0.086 | 0.052 |

Conclusions (all on the 60 s clip):
- Full ensemble vs single sub-model → 5× less bass↔other bleed (the unwrap was the bug). **Ensemble is the shipping default now.**
- `shifts=2` vs `shifts=1` (ensemble) → **identical** bleed, 1.7× slower. `shifts=1` is the default.
- `drums↔other` (0.084 ensemble) is ~unchanged from single (0.076) — this is **spectral** bleed (drums/guitar share midrange), low temporal NCC, and was NOT improved by ensemble or shifts. See §5.

## 4. Final staged defaults (what `--use-ft-stems` now does)
`separate_stems(..., model_name='htdemucs_ft', shifts=1, overlap=0.25, segment=None, strip_seconds=45.0)`
- full `BagOfModels` ensemble forwarded to `demucs.apply.apply_model`,
- via `_separate_strips` (45 s strips, 10 s overlap, level-constant crossfade),
  falling back 45 s → 20 s strips → stock `htdemucs` on OOM,
- torch CPU threads bounded to 4, `del`+`gc.collect()` per strip.

CLI (exposed in `autorb/cli.py`, wired into `separate_stems`):
- `--use-ft-stems` — enable ft (full ensemble + strips).
- `--ft-shifts N` (default 1) — Demucs translation-averaging passes.
- `--ft-strip-seconds S` (default 45) — strip length; lower = less RAM.
- `--ft-segment S` (default None → full context) — Demucs internal segment seconds.

Full-song A/B (198 s, RMS-matched to 0.12): `output_ab/full/stock/` vs
`output_ab/full/ft/` (ft peak 0.754 vs stock 0.661 at equal loudness → ft spikier/cleaner).

## 5. Open decision for the user (DO NOT auto-decide)
The original complaint was "drums bleeding into the ft `other` stem". The ensemble
fix solved **bass↔other** bleed but **not drums↔other** (spectral, NCC ≈ 0.08 for
all ft configs). To attack drums↔other, the unexplored knobs are:
- `overlap` 0.25 → 0.5 (Demucs STFT overlap; cleaner transients, 2× memory/time),
- `segment` None → 10 s / 20 s (smaller LSTM context; may localize drums better).
No config with these has been generated yet. If the user wants them, run
`.tmp/ab_probe.py` with a new CFG entry and re-generate; the harness is in §6.

## 6. How to add/validate more configs (the harness)
`.tmp/ab_probe.py <cfg_label> <out_dir>` — single-config probe. Edit the `CFG` dict:
```python
"ft_ens_ovl0.5": ("htdemucs_ft", "ensemble", 1, None, 0.5),   # overlap sweep
"ft_ens_seg20":  ("htdemucs_ft", "ensemble", 1, 20.0, 0.25),  # smaller segment
```
Run: `python3 .tmp/ab_probe.py ft_ens_ovl0.5 output_ab/cfg/ft_ens_ovl0.5`
→ writes `stems/*.wav`, `preview_mix.wav` (RMS=0.12), `ncc.json` (4×4 bleed matrix).
To validate a full 198 s run with any knob set, use `autorb/audio/stems.py::separate_stems`
directly or `python3 -m autorb.cli <audio> --artist .. --use-ft-stems --ft-shifts 2 ...`.
Memory watchdog (optional): read PID from `<out>/probe.pid`, sample
`/proc/<PID>/status VmRSS`.

## 7. What this agent did NOT do (boundaries)
- Did not commit (per repo rules — `git add` only; user commits).
- Did not modify the guitar-bridge 23-vs-4 merge logic (it's a separate, documented
  limitation — see `llm-wiki-kb/log.md` bridge analysis; the windowed-chord-identity
  merge is still a future item).
- Did not expose `--ft-overlap` or `--no-ft-ensemble` on the CLI (deliberate: full
  ensemble is strictly better and exposing single-submodel would be a footgun).
  Add them if the overlap/segment sweep (§5) shows a reason to.
