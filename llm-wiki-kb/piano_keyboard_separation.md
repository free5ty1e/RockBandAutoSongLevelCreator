# Piano/Keyboard Stem Separation Options

Captured at **v0.1.13** — research into separating piano/keyboard from the main mix for Rock Band keys charting.

## Current situation

The default `htdemucs_ft` model separates into 4 stems: `drums, bass, other, vocals`. The `other` stem contains **everything that's not drums, bass, or vocals** — including piano/keyboard, rhythm guitar, and any other non-drum/bass/vocal instruments. For Rock Band keys charting, the piano parts need to be isolated from the `other` stem.

## Available options

### 1. Demucs `htdemucs_6s` (installed, works out of the box) ✅

**Status:** Available via `pip install demucs` (v4.1.0). `get_model('htdemucs_6s')` returns a BagOfModels with sources: `drums, bass, other, vocals, guitar, piano`.

- **Stems:** `drums, bass, other, vocals, guitar, piano`
- **Architecture:** Single HTDemucs model (not an ensemble), so faster than `htdemucs_ft` (which is a 4-model ensemble)
- **Quality:** The README notes "poor piano quality" — the piano stem captures piano but with leakage from other instruments. The `guitar` stem can help isolate guitar from the `other` stem, but the `piano` stem is not clean enough for isolated key charting.
- **Memory:** Single model, so lower memory than `htdemucs_ft` ensemble. Can likely process full songs in one pass on 8 GB.
- **Speed:** Single model inference — several times faster than `htdemucs_ft` (which runs 4 sub-models)
- **Code integration:** `separate_stems()` already supports `model_name='htdemucs_6s'` — it's a standard Demucs model with 6 sources. The `_separate_strips` path handles any model. A `guitar` and `piano` stem would appear in the output alongside the 4 existing stems.

**Trade-off:** The `piano` stem quality is reportedly poor. May not isolate keys cleanly enough for Rock Band keys charting. But the `guitar` stem IS useful — it splits guitar out of `other`, making the `other` stem cleaner (just piano/strings/ambient, no guitar).

### 2. Spleeter `5stems` (opt-in code path; ⚠️ DO NOT install into the main venv)

**Status:** The `--separator spleeter:5stems` code path exists in `autorb/audio/stems.py::separate_stems_spleeter`, but the `spleeter` package is **NOT a project dependency and must not be pip-installed alongside the main stack**.

> **⚠️ VERIFIED DEPENDENCY CONFLICT (2026-08-25):** Installing `spleeter==2.4.2` into this repo's venv **downgraded click 8.1.7 → 7.1.2, typing_extensions → 4.5.0 (breaking `import torch` entirely — torch needs `TypeIs` from ≥4.9), numpy → 1.24.3 (breaking matplotlib's spectrogram rendering)**, plus dragged in tensorflow 2.12 / keras / jax / pandas 1.5.3 (~600 MB). The repair was `pip install -U 'click>=8.1.7' 'typing_extensions>=4.9,<6' 'numpy==1.26.4'`. If you want to evaluate Spleeter's piano stem quality, do it in an **isolated venv**, export WAVs there, and point AutoRB at them via `--skip-separation`.

- **Stems:** `vocals, piano, drums, bass, other`
- **Architecture:** TensorFlow-based U-Net with spectrogram masking (2022-era)
- **Quality:** Generally lower than Demucs (no ensemble, older architecture); piano stem usable for quick experiments
- **Code integration:** Already wired — `separate_stems_spleeter()` lazily imports spleeter *inside* the function, so the main pipeline works with or without it; selecting `--separator spleeter:*` without the package installed raises a clear ImportError
- **Why kept as opt-in:** htdemucs_6s already provides a piano stem with zero new dependencies; Spleeter is only worth revisiting if its piano quality beats htdemucs_6s in an isolated test

**Trade-off:** Separate piano stem, but a dependency landmine — isolated venv only.

### 3. MDX-Net (not installed) ⚠️

**Status:** Available via `pip install mdx-net` or HuggingFace. Requires significant setup.

- **Stems:** Varies by model, typically `vocals, drums, bass, other` plus some models add piano
- **Architecture:** Complex ensemble of models, very high quality
- **Quality:** Best available for piano/vocal separation
- **Speed:** Very slow (ensemble of models, complex architecture)
- **Memory:** High
- **Code integration:** Custom API, would require significant new code

**Trade-off:** Best quality but complex setup, slow, high memory.

### 4. Open-Unmix (not installed) ⚠️

**Status:** Available via `pip install openunmix`. Primarily for vocals/bass/drums.

- **Stems:** `vocals, drums, bass, other` (standard), some variants add piano
- **Quality:** Decent for its specific stems, but not as good as Demucs
- **Code integration:** Separate code path

## Recommendation

For the immediate need (finding a song with keys to experiment with):

1. **Start with `htdemucs_6s`** — already installed, fast (single model, no ensemble), 6 stems including `piano`, zero new dependencies. The `guitar` stem alone is valuable — it splits guitar out of `other`, making the remaining `other` stem much cleaner.
2. **If the piano stem quality proves too poor**, evaluate Spleeter `5stems` in an **isolated venv only** (see the conflict warning above) — never pip-install it into the main environment.
3. The `--separator` CLI option switches between all of these (`htdemucs_ft` default / `htdemucs` fast / `htdemucs_6s` piano+guitar / `spleeter:5stems`).

## Integration status (v0.1.14 — Phases 1 & 2 done, Phase 3 pending)

### ✅ Done: `--separator` CLI option
```
--separator [htdemucs|htdemucs_ft|htdemucs_6s|spleeter:5stems]
```
Default: `htdemucs_ft` (best quality). Users who need piano/guitar separation use `htdemucs_6s`. The legacy `--use-ft-stems/--no-use-ft-stems` flags still work as aliases; `--separator` wins if both are given.

### ✅ Done: separation backends
- `htdemucs_6s` runs through the existing `separate_stems()` unchanged — it's a single-model BagOfModels, so it takes the single-model branch (auto-chunked via the 10 s COLA chunker for tracks > 2 min) and saves all 6 stems from `model.sources`.
- `spleeter:*` dispatches to `separate_stems_spleeter()` (`autorb/audio/stems.py`), which lazily imports spleeter and renames its `<base>_<stem>.wav` outputs to the standard stem names + builds a preview mix.

### ✅ Done (v0.1.15): charting + MOGG wiring
- The guitar chart reads `guitar.wav` and the keys chart reads `piano.wav` whenever those files exist in `[output-dir]/stems/`, falling back to the `other` stem otherwise (`autorb/cli.py`). This covers both master stems (bands' own multitracks via `--skip-separation`) and `htdemucs_6s` output.
- The MOGG builder mixes guitar/piano into the ch5-6 backing bus so their audio is audible in-game while preserving the verified 10-channel layout.
- Every separation run clears stale `*.wav` from the stems folder first, so switching separators never leaks stems between runs.

### Remaining for keys quality
- Evaluate `htdemucs_6s`'s `piano.wav` on a keys-heavy song (README reports poor piano quality) vs Spleeter's in an isolated venv.
- `transcribe_keys` currently quantizes to 5 lanes; a real keys part may deserve the full 2-octave treatment once a clean `piano` stem exists to validate against.

## Known limitations

- **`htdemucs_6s` piano quality is reportedly poor** — the Demucs README explicitly notes this. The piano stem may have significant leakage from other instruments.
- **No model cleanly separates lead-piano from rhythm-piano** (or synth from piano) — both would be in the `piano` stem.
- **Spleeter's 5stems piano** is decent but lower resolution than Demucs, and the package cannot coexist with this repo's torch/click/numpy versions (isolated venv only — see warning above).
- **Rock Band keys use 5-lane (green/red/yellow/blue/orange)** — unlike guitar which is 5-fret buttons, keys can also use the 5-lane pad layout. Need to verify the charting code handles this.

## References

- Demucs v4: https://github.com/facebookresearch/demucs
- Spleeter: https://github.com/deezer/spleeter
- MDX-Net: https://github.com/naudio-lab/MDX-Net
- Open-Unmix: https://github.com/sigsep/open-unmix-pytorch
