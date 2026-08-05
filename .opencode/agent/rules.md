---
description: Mandatory development cycle rule requiring version bumps, changelog updates, README updates, and llm-wiki-kb maintenance.
mode: subagent
---

# Development Cycle Documentation & Versioning Rule

The canonical AutoRB project rules live in `/workspaces/RockBandAutoSongLevelCreator/AGENTS.md`. Read that file and follow it exactly. It covers:

1. Version bumps in `autorb/version.py` (+0.0001 per cycle), `CHANGELOG.md`, `README.md`, and `llm-wiki-kb/` updates.
2. Git policy: only `git add` (staging) is allowed — never commit, push, reset, or any other git write.
3. Scratch work must use a `.gitignored` workspace folder (`.tmp/`), never `/tmp`.
4. Run `pytest` and confirm it passes before presenting changes.
