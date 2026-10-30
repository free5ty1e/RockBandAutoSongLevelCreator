# AutoRB Project Rules

These rules are MANDATORY for every session and agent working in this repo, in EVERY harness. **This file is the canonical rules file.** Pi (and opencode) auto-load it into the agent's context; the Claude CLI harness loads `CLAUDE.md`, which mirrors these rules — the two files must be kept in sync (key contracts are pinned in both by `tests/test_audit_release.py::TestReleaseDocsConsistency`). The opencode `rules` subagent (`.opencode/agent/rules.md`) follows this same file.

## Development Cycle Documentation & Versioning

During every development cycle where code, pipelines, packaging logic, or configuration scripts are modified, you MUST proactively and thoroughly:

1. Bump the pipeline version in `autorb/version.py` using **proper semantic versioning** (`MAJOR.MINOR.PATCH`, each a plain integer — the version is a release identifier, NOT a float). Per cycle, increment `PATCH` by 1 (e.g. `0.0.98` → `0.0.99`). **When `PATCH` would reach `100`, roll over to the next `MINOR` instead** (e.g. `0.0.99` → `0.1.0`, never `0.0.100` — a `0.0.100` string does not sort correctly against `0.0.99`). Only bump `MAJOR`/`MINOR` deliberately (a milestone or a breaking change); routine fixes stay on `PATCH`. The version in `autorb/version.py`, the `## [x.y.z]` header in `CHANGELOG.md`, and any in-doc version references must all match.
2. Document all changes in `CHANGELOG.md` under the new version.
3. Update `README.md` to reflect new features, test commands, or pipeline changes.
4. Update `llm-wiki-kb/` to keep architectural records and domain knowledge completely up-to-date.

Never skip version bumps, changelog entries, or documentation updates when completing tasks.

## Mandatory End-of-Cycle Workflow

After every development cycle, BEFORE writing your final response message to
the user, you MUST complete all three steps in order:

1. **Validate**: run the relevant unit tests AND integration tests for your
   changes (e.g. `python -m pytest tests/ -q --deselect
   tests/test_quality_validation.py::TestSyncedTrackQuality` plus an
   end-to-end pipeline run when chart/export code changed). Fix failures
   before responding.
2. **Stage**: `git add` ONLY your specific intended changes (fine-grained,
   never `git add -A` for unrelated files). The git restrictions below still
   apply — NEVER commit, push, branch, merge, or tag.
3. **Suggest a commit message** for the staged changes in your response for
   the user to review.

The Claude CLI harness enforces this via a Stop hook
(`.claude/hooks/dev-cycle-verification.sh`) — do not disable it there. In
other harnesses (Pi, opencode) it is enforced by discipline; the workflow is
equally mandatory everywhere.

## Testing

Before presenting changes, run the test suite and confirm it passes — the
full local command is:

```
python -m pytest tests/ -q --deselect tests/test_quality_validation.py::TestSyncedTrackQuality
```

When chart/export/packaging code changed, also run an end-to-end pipeline
conversion (e.g. with `--skip-separation` on cached stems) and verify the
artifacts before presenting.

## Scratch / Temp Files

Do not work in `/tmp`. Instead, use a `.gitignored` folder inside the workspace that the user can observe (`.tmp/` already exists and is gitignored). If an appropriate temp folder does not exist, create it and `.gitignore` it.

## Release Rules (read before any release/tagging work)

Releases are validated by two automated gates — respect both:

1. **The CI pipeline builds it** (`.github/workflows/ci-cd.yml`): test →
   build (wheel-content check) → release → **audit**. The `audit` job runs
   `tools/audit_release.py --strict` on every `v*` tag and uploads
   `AUDIT_REPORT.txt`. A red audit job means the release is NOT valid,
   even if a GitHub Release was published.
2. **The audit tool is the source of truth for "is this release good"**:
   `python tools/audit_release.py --tag vX.Y.Z --strict`. It checks CI
   state, release assets, wheel contents (source parity: every repo module
   must ship in the wheel), data assets, release-notes contract, a
   fresh-venv install+import smoke of the downloaded wheel, and tag
   hygiene. Full stage table + rationale: `llm-wiki-kb/release_process.md`.

**When a release build fails or a release is reported broken:**
- Get the failing run first: `gh run list --limit 5`, then
  `gh run view <id> --log-failed`. Diagnose from the actual error — do not
  guess from the working tree (the v0.1.30-alpha01 failure was a
  dependency's build-time `pkg_resources` use that the devcontainer masked).
- After diagnosing, run the audit against the tag to enumerate every
  missing piece (it reports CI state → assets → contents → notes → smoke
  in order).

**Pre-tag checklist — complete EVERY item before suggesting the user tag:**
1. `autorb/version.py` = the version being released.
2. `CHANGELOG.md` has a `## [X.Y.Z] — date` entry for it (the notes
   generator hard-fails without it; the release body embeds it verbatim).
3. NEW PACKAGE this release? It must be added to
   `[tool.setuptools].packages` AND the CI wheel-content check AND
   `tools/audit_release.py`'s `EXPECTED_IMPORTS`. **The devcontainer's
   editable install masks a missing entry indefinitely** — this is how
   v0.1.30 nearly shipped wheels with NO instrument charting package.
4. NEW DATA FILE? Same: `[tool.setuptools.package-data]` + CI check +
   `REQUIRED_WHEEL_DATA`.
5. NEW DEPENDENCY? It must (a) actually be imported by the code,
   (b) install cleanly on a FRESH environment — never anything whose
   build needs `pkg_resources` (the crepe failure class), (c) if optional,
   keep it out of core deps with a guarded import (adtof, spleeter).
6. Console scripts (`[project.scripts]`) must have ALL their deps in CORE
   dependencies — a plain `pip install autorb` has to run them.
7. Full suite green locally, then cheap wheel smoke:
   `python -m pip wheel --no-deps -w /tmp/wheelcheck .` and verify the
   new modules/files are IN the wheel zip.

Tag rule: `v` + exact `autorb/version.py` version, optional suffix that
must NOT start with a digit (`v0.1.31-alpha01` ✓). Never tag yourself —
git tag is in the FORBIDDEN list; the user tags.

**Never claim a release is good without either (a) a green CI audit job
on that tag, or (b) a passing local `audit_release.py --strict` run
against it.** "Good" includes the FUNCTIONAL CONVERSION (stage 5b): the
wheel-installed CLI must convert the committed FREE benchmark song
(`tools/test_data/benchmark_tisk_tisk.mp3`, CC BY-NC-ND — provenance in
`tools/test_data/BENCHMARK_SONG.md`) and produce substantial artifacts
(CON, MOGG, Clone Hero folder, instrument tracks with ≥10 notes each),
plus any songs the developer drops into git-ignored
`tools/test_data/local/` (e.g. Open Road Song — copyrighted, NEVER
committed; the ignore is enforced by test). An install/import pass alone
is NOT sufficient — runtime-only failures (lazy imports, mid-pipeline
data files, optional-dep fallbacks) only surface when a real song is
converted. If a new runtime input is added (model, font, data file),
make sure the conversion test exercises it. NEVER commit copyrighted
audio (or any copyrighted material) to the repo — test fixtures come
from free-licensed sources only.

# DANGER MODE GUARDRAILS — Do Not Remove

You are running with **automatic permission approval**. Every tool call
you make is executed WITHOUT confirmation. This is a safety-critical mode.

## MANDATORY RESTRICTIONS — Git write operations

Only the following **Staging & Read** operations are allowed:

### ALLOWED Git Operations
| Command | Purpose |
|---------|---------|
| `git add <file>` | Stage a file (fine-grained) |
| `git add -p` | Stage interactively by hunk |
| `git status` | View working tree state |
| `git diff` | View unstaged changes |
| `git diff --cached` | View staged changes |
| `git log` | View commit history |
| `git show` | View a commit |
| `git blame` | Annotate a file |
| `git checkout <ref>` | Switch branches (no history/remote writes) |
| `git restore <file>` | Discard unstaged local changes |
| `git stash push` | Save WIP temporarily |
| `git stash list` | View stashes |
| `git stash show` | View stash contents |

### FORBIDDEN Git Operations
| Operation | Reason |
|-----------|--------|
| `git commit` | Would record changes permanently |
| `git push` / `git push --force` | Would publish to remote |
| `git branch` / `git checkout -b` | Would create branches |
| `git merge` / `git rebase` | Would alter history |
| `git tag` | Would tag releases |
| `git fetch` / `git pull` | Would contact remote |
| `git reset --hard` / `git reset --mixed` | Destructive history reset |
| `git revert` / `git cherry-pick` | Would create new commits |
| `git rm` / `git mv` | Would remove/rename tracked files |

The user performs all commits, pushes, tags, merges, and other history
operations themselves. If the user's workflow expects a commit, ask the
user to run it (or provide the exact command for them to run).

## MANDATORY RESTRICTIONS — gh (GitHub CLI)

Only read operations and updating PR descriptions via `gh pr edit` are permitted.
Release auditing requires exactly these READ operations — they are allowed
and expected during release work: `gh run list`, `gh run view`,
`gh release view`, `gh release download` (used by
`tools/audit_release.py`). All still read-only.

### FORBIDDEN gh Operations
| Operation | Reason |
|-----------|--------|
| `gh pr create` / `gh pr merge` / `gh pr close` | Would create or modify pull requests |
| `gh issue create` / `gh issue close` | Would modify issues |
| `gh release create` / `gh release delete` / `gh release edit` | Would create or modify releases |
| `gh repo fork` / `gh repo create` / `gh repo delete` | Would create or delete repositories |

## File System Cautions

- You can read, write, and edit files normally.
- **Do not delete files** without the user explicitly asking.

## Enforcement

- If you are asked to do a forbidden git or gh operation, refuse.
- If in doubt, err on the side of refusing.

# --- DANGER GUARDRAILS END ---
