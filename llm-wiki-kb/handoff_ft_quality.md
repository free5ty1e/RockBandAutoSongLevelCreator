# Handoff: htdemucs_ft quality tuning (v0.1.11 → v0.1.16)

Context for the next agent taking over the `--use-ft-stems` quality work. The
exploring agent ran a 5-config A/B experiment, found the single-submodel unwrap
was the bleed bug, switched to the full ensemble through sectioned strips, and
committed the fix as **v0.1.12**. User listening tests confirmed the ft ensemble
beats stock `htdemucs` across all stems, making it the **default** (v0.1.13).
The `--separator` option and `htdemucs_6s`/spleeter backends were added in v0.1.14.

## 1. Repo state (authoritative: `git diff HEAD --stat`)
Current working tree has staged changes for v0.1.14 (default-on ft stems +
`--separator` + piano/keyboard separation documentation).
```
CHANGELOG.md                     (+10, v0.1.13 + v0.1.14 entries)
README.md                        (+15, --separator / --ft-overlap / narrative updated)
autorb/audio/stems.py            (+10, htdemucs_6s chunking + separate_stems_spleeter)
autorb/cli.py                    (+15, --separator + --ft-overlap + spleeter dispatch)
autorb/version.py                (__version__ = "0.1.14")
llm-wiki-kb/handoff_ft_quality.md (+updated, v0.1.14 status + §8 guitar/rhythm)
llm-wiki-kb/instrument_charting.md (+updated, v0.1.13/v0.1.14 version tail)
llm-wiki-kb/log.md               (+v0.1.13 + v0.1.14 entries)
llm-wiki-kb/piano_keyboard_separation.md (NEW — full separator comparison)
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

## 4. Final defaults (v0.1.13: `--use-ft-stems` is now DEFAULT ON)
`separate_stems(..., model_name='htdemucs_ft', shifts=1, overlap=0.25, segment=None, strip_seconds=45.0)`
- full `BagOfModels` ensemble forwarded to `demucs.apply.apply_model`,
- via `_separate_strips` (45 s strips, 10 s overlap, level-constant crossfade),
  falling back 45 s → 20 s strips → stock `htdemucs` on OOM,
- torch CPU threads bounded to 4, `del`+`gc.collect()` per strip.

CLI (exposed in `autorb/cli.py`, wired into `separate_stems`):
- `--use-ft-stems` / `--no-use-ft-stems` — **DEFAULT ON**. Full ensemble + 45 s strips.
  Use `--no-use-ft-stems` for fast stock `htdemucs` (~1 min vs ~16 min on 8 GB CPU).
- `--ft-shifts N` (default 1) — Demucs translation-averaging passes.
- `--ft-strip-seconds S` (default 45) — strip length; lower = less RAM.
- `--ft-segment S` (default None → full context) — Demucs internal segment seconds.
- `--ft-overlap F` (default 0.25) — Demucs STFT overlap; 0.5 = cleaner transients, ~2× time/RAM.

**User listening test (v0.1.13):** ft ensemble stems rated MUCH BETTER than stock across all
instruments (drums, bass, other/rhythm-guitar, vocals). Preview mix sounds like the original
song. See `output_ab/full/ft/` vs `output_ab/full/stock/`. This confirmed ft as the default.

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
- Does NOT separate guitar solo vs. rhythm guitar in the `other` stem (see §8).
  Demucs separates by instrument family (drums/bass/other/vocals), not by
  lead-vs-rhythm within a family. The ft `other` stem contains both the rhythm
  guitar underneath and the lead guitar solo — these are mixed together by the
  model. A future improvement could try multi-band separation or a different model,
  but for now the chart must represent both parts (or the user must edit the
  stem to mute the rhythm part during the solo).

## 8. Guitar solo vs. rhythm guitar in the `other` stem
**Problem:** The user noted that during the guitar solo, the `other` stem
(rhythm guitar) contains a distinct rhythm guitar part layered behind the lead
guitar solo. The chart would need to separate these — the guitar soloist will not
want to play rhythm guitar during the solo.

**Root cause:** Demucs (including `htdemucs_ft`) separates by **instrument
family** (drums / bass / other / vocals), not by role within a family. The
`other` stem is "everything that's not drums, bass, or vocals" — so it contains
**both** the rhythm guitar and the lead guitar solo, mixed together by the model.

**No model-level separation exists** to split lead vs. rhythm guitar within the
`other` stem. This is a fundamental limitation of the instrument-family
separation approach. Options for future improvement:
- **Multi-band separation:** Split the `other` stem into frequency bands
  (e.g., ~300 Hz–2 kHz for rhythm power chords, 2–5 kHz for lead guitar)
  and transcribe each band independently — but there's significant overlap.
- **Different model:** Some models (e.g., `htdemucs_ft` variants trained on
  lead/rhythm separation, or `asteroid` models with more stem classes) may
  already distinguish lead guitar from rhythm guitar, but this is unverified.
- **Manual stem editing:** The user can manually edit the `other.wav` stem to
  mute/suppress the rhythm guitar during the solo section before charting.

**For now:** The guitar chart from the `other` stem will include both rhythm
strumming and lead solo notes. The existing guitar transcription
(`transcribe/instruments/guitar.py`) handles chord detection and will represent
whatever fundamental pitches are present — during the solo, both the rhythm
chords and the lead notes may appear, which is musically correct but may not be
what the player wants for a fun solo section.
