---
description: Mandatory development cycle rule requiring version bumps, changelog updates, README updates, and llm-wiki-kb maintenance.
mode: subagent
---

# Development Cycle Documentation & Versioning Rule

The canonical AutoRB project rules live in `/workspaces/RockBandAutoSongLevelCreator/AGENTS.md`. Read that file and follow it exactly. It covers:

1. Version bumps in `autorb/version.py` using proper semantic versioning (MAJOR.MINOR.PATCH integers; `+1` to PATCH per cycle, rolling `0.0.99` → `0.1.0` when PATCH would hit 100 — never `0.0.100`), plus matching `CHANGELOG.md`, `README.md`, and `llm-wiki-kb/` updates.
2. Git policy: staging (`git add`) and working-tree safety ops only (`git restore`, `git stash push`) — never commit, push, tag, or any other history/remote write. The full allowed/forbidden tables, the gh read-only policy, and the end-of-cycle workflow (validate → stage → suggest a commit message) are in AGENTS.md.
3. Scratch work must use a `.gitignored` workspace folder (`.tmp/`), never `/tmp`.
4. Run `pytest` and confirm it passes before presenting changes.
5. Release/tagging work: the Release Rules in AGENTS.md apply (pre-tag checklist; a release is only "good" with a green CI audit or a passing local `--strict` audit).
