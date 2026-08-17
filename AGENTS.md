# AutoRB Project Rules

These rules are MANDATORY for every session and agent working in this repo. This file is auto-loaded into the primary agent's context by opencode; the `rules` subagent (`.opencode/agent/rules.md`) follows the same rules.

## Development Cycle Documentation & Versioning

During every development cycle where code, pipelines, packaging logic, or configuration scripts are modified, you MUST proactively and thoroughly:

1. Bump the pipeline version in `autorb/version.py` using **proper semantic versioning** (`MAJOR.MINOR.PATCH`, each a plain integer — the version is a release identifier, NOT a float). Per cycle, increment `PATCH` by 1 (e.g. `0.0.98` → `0.0.99`). **When `PATCH` would reach `100`, roll over to the next `MINOR` instead** (e.g. `0.0.99` → `0.1.0`, never `0.0.100` — a `0.0.100` string does not sort correctly against `0.0.99`). Only bump `MAJOR`/`MINOR` deliberately (a milestone or a breaking change); routine fixes stay on `PATCH`. The version in `autorb/version.py`, the `## [x.y.z]` header in `CHANGELOG.md`, and any in-doc version references must all match.
2. Document all changes in `CHANGELOG.md` under the new version.
3. Update `README.md` to reflect new features, test commands, or pipeline changes.
4. Update `llm-wiki-kb/` to keep architectural records and domain knowledge completely up-to-date.

Never skip version bumps, changelog entries, or documentation updates when completing tasks.

## Git Operations

Never perform any git write operations, except for `git add`. Stage your specific changes each development cycle and present them to the user for review; the user performs all commits.

- Allowed: `git add` (staging), plus read-only inspection (`git status`, `git diff`, `git log`, etc.).
- NEVER allowed: `git commit`, `git push`, `git reset`, `git checkout`, `git merge`, `git stash`, `git restore`, or any other git write. If the user's workflow expects a commit, ask the user to run it (or provide the exact command for them to run).

## Scratch / Temp Files

Do not work in `/tmp`. Instead, use a `.gitignored` folder inside the workspace that the user can observe (`.tmp/` already exists and is gitignored). If an appropriate temp folder does not exist, create it and `.gitignore` it.

## Testing

Before presenting changes, run the test suite (`pytest`) and confirm it passes.
