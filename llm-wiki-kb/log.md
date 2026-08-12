---
title: AutoRB Knowledge Base Log
date: 2026-08-07
---
# Log

Append-only ledger of changes to this knowledge base. Newest first. Each entry records: timestamp, what was added, and why (the reasoning that future agents should not have to re-derive).

## 2026-08-12 — Charted vocal notes anchored to onset-snapped word starts (v0.0.84)

**What:** `generate_vocal_midi()` charted every note at its syllable `note_segment.start` (the Basic-Pitch pitch onset) and ignored the word's onset-snapped `start` whenever the word had syllables. Fixed by starting the first segment of a word's first syllable at `word.start`; later segments keep their own pitch-change times. Added a "Charted Note Anchored to the Onset-Snapped Word Start" section to `[[vocal_alignment]]`, plus a debugging note about reading note↔lyric pairs (capture the `FF 05` lyric meta immediately following each `note_on` at the same tick — a last-lyric accumulator lags by one).

**Why:** The v0.0070/v0.0.82 onset snapping fixed the word starts but the MIDI generator never consumed them, so the chart was systematically late by exactly the BP pitch-onset lag that snapping was built to remove (median 0.000s, p90 +0.108s, worst +0.598s on "salt"). The "+4s outliers" reported earlier were an artifact of naive lyric-tracking in analysis scripts, not the chart — the chart was internally consistent but charted at the wrong onset.

---

## 2026-08-11 — Robust vocal-pitch: harmonic-misread gates + outlier-rejected contour (v0.0.83)

**What:** Updated `[[vocal_alignment]]` with a v0.0.83 section and re-measured the rebuilt Open Road Song chart. The trust gate (`PYIN_PROB_THRESH` per segment + mode≈median) was necessary but NOT sufficient: a harmonic/bleed *split* reading passes it per-segment while the syllable as a whole is noise. Three-part fix in `autorb/transcribe/pitch_tracking.py`:
1. **Multi-segment spread rule** (`MAX_SYLLABLE_SPREAD_ST=6.0`) — a syllable whose segments span > 6 st is untrusted; a real vocal slide never jumps that far inside one syllable.
2. **Robust contour anchors** — `build_melodic_contour_from_syllables` rejects anchors that deviate > `CONTOUR_OUTLIER_ST` (7 st) from the local-median of their ±2 neighbors (`CONTOUR_ANCHOR_WINDOW`), *before* interpolating. A single contaminated anchor used to warp the whole contour (Open Road Song's "road"=72 = 3rd harmonic of A3=57 dragged the contour up and pulled untrusted neighbors like "pen"=64 with it).
3. **Trusted contour-check** in `resolve_syllable_pitches_with_fallback` — a trusted reading survives only if its first note is within 7 st of the robust contour, else it is reclassified as untrusted and resolved via BP/contour fallbacks.

Key measured results on the rebuilt chart (v0.0.83): consecutive vocal jumps ≥ 5 st **18 → 10**; vocal range **50..78 → 50..64** (72/76/78 were harmonics); first-phrase "hit eighty on the open road" `50→61→54→64→72` → `57→57→57→56`; ending "road/song" `66→78→76→52→61` → coherent `63→64→64` ascent. The low "As" dip (50 vs contour 56, dev 6.2 st) is a genuine melody element and is intentionally preserved by the 7-st threshold — do not lower the threshold expecting to catch it.

**Why:** User play-tested the PS4 chart and reported vocal pitches "jump" note-to-note. The previously-documented v0.0073 fix (per-word pyin trusted on confidence+mode-consensus) stopped most jumps (61→28) but the remaining 10-18 jumps were exactly the self-consistent harmonic misreads that no per-segment check can catch. Also documented a recurring debugging trap: `output/` frequently holds a different song's build (Brian Wilson), so `test_quality_validation.py` failures against `output/` are data-dependent, not code regressions — 4 such failures exist on the pre-fix baseline too.

---

## 2026-08-11 — Voiced-onset snapping + LRC-line sustain fix + quality-validation suite (v0.0.82)

**What:** Updated `[[vocal_alignment]]` with a new v0.0.82 section covering two `step4_sync.py` fixes and added `tests/test_quality_validation.py` (10 tests, currently 103 total passing):
1. **Voiced-onset snapping** — `_detect_vocal_onsets` now filters onsets to those with a pyin-confident (prob > 0.5) voiced frame within 0.25s (`VOICED_ONSET_PROB`/`VOICED_ONSET_WINDOW`). Root cause: `onset_detect(backtrack=True)` places an onset on the envelope floor before the peak; for the first word of a song that floor is pre-sound silence or an unvoiced consonant, so the note led its own pitch. Open Road Song's "Tonight" was snapping to 0.232s vs its true first voiced frame at 0.488s; it now charts at 0.534s (0.076s from the LRC).
2. **LRC-line sustain membership uses `raw_start`** — `_clip_and_extend_word_ends` extends each LRC line's last word toward the next line's timestamp, but onset snapping can pull the *next* phrase's first word before its LRC timestamp, mis-assigning it as the previous line's last word and silently disabling the sustain extension. Each refined word now records its pre-snap `raw_start` and line membership uses it.
Also documented the debugging trap: `output/` had been overwritten by a Brian Wilson run, so the Open Road Song chart was being driven by a 291s stem/cache — check stem/cache/tempo-map durations against the source audio before trusting quality-test failures against stale artifacts.

**Why:** The quality-validation suite exposed two real chart bugs (first word 0.38s early; line-final sustains chopped). The onset fix corrects what v0.0070's "charts at 0.232s ≈ the true attack" had wrongly enshrined; the raw_start fix makes the v0.0072+ sustain behavior actually engage.

---

## 2026-08-07 — Album art legibility fix + CP logo (v0.0075)

**What:** The default "Chris Prime Custom" album art was illegible on macOS ("scribbles") because it hardcoded the Linux-only font path `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`. On macOS that path doesn't exist, so `_font()` fell back to Pillow's built-in `load_default()` **with no size argument** → always returned the size-10 bitmap font. "CHRIS" rendered ~30×8px (~124 glyph px) instead of DejaVu's ~121×26px (~1858 glyph px) — unreadable when scaled on the PS4 song list. The devcontainer always had DejaVu installed, so it rendered fine; this was a latent mac-only portability bug, not a devcontainer regression (confirmed by a direct font-render test). Fix: DejaVu Sans Bold/Regular (permissive Bitstream Vera license) are now **bundled in the wheel** (`autorb/export/data/fonts/`, shipped via `[tool.setuptools.package-data]`). `_load_font()` prefers the bundled copy, then known OS paths (Homebrew/Library/macOS, `/usr/share/fonts/...`/Linux), then Pillow's scalable `load_default(size=)` (Pillow ≥ 10.1). Also added a circular "CP" monogram logo in the bottom-right corner (orange ring + white C/P strokes). New regression tests: `test_album_art_title_is_legible` (asserts thousands of white glyph pixels on 256px art) and `test_album_art_has_cp_logo` (asserts orange ring + white glyphs in bottom-right). Full suite: 42 passed.

**Why:** The user reported the macOS art was "scribbles" vs the devcontainer's clean art. Root cause was the hardcoded Linux font path; the fix makes the art portable to any OS and any Pillow version. The CP logo uses a previously unused corner.

---

## 2026-08-07 — Cross-platform ForgeTool build + bare-wheel pkg_resources fix (v0.0074)

**What:** (1) `tools/build_forgetool.sh` now auto-detects mono's .NET Framework reference-assembly dir via `find_framework_path()` — probing `brew --prefix mono` (Homebrew Intel + Apple Silicon, e.g. `/opt/homebrew/Cellar/mono/6.14.1/lib/mono/4.7.1-api`), the Linux `/usr/lib/mono/4.7.1-api` path, and the old `/Library/Frameworks/Mono.framework/...` path for `mscorlib.dll`, with a `find` fallback across the Homebrew Cellar / Framework roots — instead of hardcoding the Linux path, so the same script works on macOS and Linux. (2) The wheel now declares `setuptools>=68.0.0,<82.0.0` (setuptools 82 deletes `pkg_resources`) so `resampy 0.4.2`'s `import pkg_resources` no longer crashes bare-wheel installs. (3) `_find_forgetool()` now auto-discovers `tools/forgetool` by searching the CWD + its child dirs, all CWD ancestors, and `sys.prefix`/`sys.base_prefix`, so `--build-pkg` no longer requires running from the repository root. (4) The `tools/forgetool` wrapper sets `DYLD_FALLBACK_LIBRARY_PATH` to `$(brew --prefix)/lib` on macOS so ForgeTool's System.Drawing (album art) can find **libgdiplus** (and its pango/cairo deps) — Homebrew's mono bundles neither the library nor the search path; `tools/build_forgetool.sh` also checks for libgdiplus. Updated `[[ps4-environment]]` to reflect that the dev container CAN now build/run ForgeTool.

**Why:** The user hit two release-blocking failures on macOS. The build script passed `/p:FrameworkPathOverride=/usr/lib/mono/4.7.1-api`, which only exists on Linux — on macOS mono lives at `$(brew --prefix mono)/lib/mono/4.7.1-api` (Apple Silicon Homebrew: `/opt/homebrew/Cellar/mono/6.14.1/lib/mono/...`), causing `error CS0006: Metadata file '/usr/lib/mono/4.7.1-api/mscorlib.dll' could not be found`. And a fresh wheel install (which ships no setuptools) crashed at `autorb.pitch.note_creation` import with `ModuleNotFoundError: No module named 'pkg_resources'` because `resampy 0.4.2` imports it. The `<82` upper bound is mandatory (setuptools 82 removed `pkg_resources`; `requirements.txt` already had this pin). **The prerequisites are now pinned to tested versions so hardcoded script versions don't silently break in the future**: `ForgeTool.csproj` targets `.NET Framework v4.7.1`, so the docs/build script pin `.NET SDK 8` (`dotnet-sdk@8` / `--channel 8.0`) and **mono 6.x** (Homebrew 6.14.1; Debian 12 / Ubuntu 22.04+ apt 6.8+/6.12+), and the script prefers the `4.7.1-api` reference assemblies. `_find_forgetool()` was broadened because the user ran the CLI from `temp/` (parent of the clone) and the old two-candidate search (`cwd`, `cwd.parent`) missed `temp/RockBandAutoSongLevelCreator/tools/forgetool`. After that was fixed, the first macOS `--build-pkg` run surfaced a *third* gap: ForgeTool reads the CON's `_keep.png_xbox` with System.Drawing, whose native libgdiplus is bundled by Linux mono but **not** by Homebrew's mono. Installing `mono-libgdiplus` alone was still insufficient — mono 6.x doesn't search `/opt/homebrew/lib` for native deps on Apple Silicon — so the `tools/forgetool` wrapper now sets `DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib` on macOS. All fixes verified: clean from-scratch `tools/build_forgetool.sh` rebuild (0 errors) on the devcontainer + a simulated Apple-Silicon Homebrew `brew --prefix mono` layout resolving to `.../4.7.1-api`, a fresh-venv wheel install importing `resampy` + `pkg_resources`, and new tests proving `_find_forgetool` resolves from the clone's parent (child search) and from a deep subdir (ancestor walk).

---

## 2026-08-07 — Wiki restructured to llm-wiki conventions (v0.0073)

**What:** Added `[[index]]` (entry-point landing page) and `[[log]]` (this ledger), slimmed `README.md` to a minimal pointer, added `.obsidian/` vault config, and corrected stale `--skip-mogg` count-in wording in `[[vocal_alignment]]` and `[[architecture]]`.

**Why:** The KB previously had only a short `README.md` listing pages via markdown links. To follow the karpathy llm-wiki guide and make the KB work as an Obsidian vault (graph visualization, agent navigation), it needs an explicit entry point (`index.md`), a change ledger (`log.md`), `[[wikilinks]]`, and a vault config. Also, `--skip-mogg` no longer disables the count-in (v0.0073: it is derived unconditionally from the cached beat grid so a reused, already-count-in MOGG stays in sync), so the old "disables the count-in" statements were factually wrong and had to be updated.

**Pages now:** `index.md`, `log.md`, `architecture.md`, `rock_band_customs_domain.md`, `vocal_alignment.md`, `con_stfs_format.md`, `mogg_audio_format.md`, `forgetool_compat.md`, `ps4-environment.md`.

---

## Origin — KB creation

**What:** Created the initial 7 topic pages (`architecture`, `rock_band_customs_domain`, `vocal_alignment`, `con_stfs_format`, `mogg_audio_format`, `forgetool_compat`, `ps4-environment`) plus a short `README.md`.

**Why:** To capture the hard-won domain knowledge and architectural decisions accumulated across development cycles (STFS/MOGG formats, ForgeTool crash root-causes, vocal alignment fixes, PS4 test findings) so future agents can come up to speed without re-deriving them.

> Omissions and corrections welcome. Prefer appending dated entries over rewriting history so the reasoning chain stays intact.
