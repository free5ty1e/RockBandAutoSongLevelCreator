---
title: AutoRB Knowledge Base Log
date: 2026-08-07
---
# Log

Append-only ledger of changes to this knowledge base. Newest first. Each entry records: timestamp, what was added, and why (the reasoning that future agents should not have to re-derive).

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
