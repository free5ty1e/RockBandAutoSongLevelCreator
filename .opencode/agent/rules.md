---
description: Mandatory development cycle rule requiring version bumps, changelog updates, README updates, and llm-wiki-kb maintenance.
mode: subagent
---

# Development Cycle Documentation & Versioning Rule

The canonical AutoRB project rules live in `/workspaces/RockBandAutoSongLevelCreator/AGENTS.md`. Read that file and follow it exactly. It covers:

1. Version bumps in `autorb/version.py` using proper semantic versioning (MAJOR.MINOR.PATCH integers; `+1` to PATCH per cycle, rolling `0.0.99` → `0.1.0` when PATCH would hit 100 — never `0.0.100`), plus matching `CHANGELOG.md`, `README.md`, and `llm-wiki-kb/` updates.
2. Git policy: only `git add` (staging) is allowed — never commit, push, reset, or any other git write.
3. Scratch work must use a `.gitignored` workspace folder (`.tmp/`), never `/tmp`.
4. Run `pytest` and confirm it passes before presenting changes.
