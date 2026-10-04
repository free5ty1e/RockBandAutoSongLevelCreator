# Project Instructions


## Mandatory End-of-Cycle Workflow (hook-enforced)

After every development cycle, BEFORE writing your final response message to
the user, you MUST complete all three steps in order:

1. **Validate**: run the relevant unit tests AND integration tests for your
   changes (e.g. `python -m pytest tests/ -q --deselect
   tests/test_quality_validation.py::TestSyncedTrackQuality` plus an
   end-to-end pipeline run when chart/export code changed). Fix failures
   before responding.
2. **Stage**: `git add` ONLY your specific intended changes (fine-grained,
   never `git add -A` for unrelated files). The existing git restrictions
   still apply — NEVER commit, push, branch, merge, or tag.
3. **Suggest a commit message** for the staged changes in your response for
   the user to review.

The `.claude/hooks/dev-cycle-verification.sh` Stop hook checks steps 1-2 and
reminds you if you forgot. Do not disable it.


# DANGER MODE GUARDRAILS — Do Not Remove

You are running with **automatic permission approval**. Every tool call you
make is executed WITHOUT confirmation. This is a safety-critical mode.

## MANDATORY RESTRICTIONS — Git write operations

Only the following **Staging & Read** operations are allowed:

### ALLOWED Git Operations
| Command | Purpose |
|---------|---------|
| `git add <file>` | Stage a file (fine-grained) |
| `git add -p` | Stage interactively by hunk |
| `git add -A` | Stage all changes |
| `git status` | View working tree state |
| `git diff` | View unstaged changes |
| `git diff --cached` | View staged changes |
| `git log` | View commit history |
| `git show` | View a commit |
| `git blame` | Annotate a file |
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

### File System Cautions
- You can read, write, and edit files normally.
- **Do not delete files** without the user explicitly asking.

### Enforcement
- If you are asked to do a forbidden git operation, refuse.
- If in doubt, err on the side of refusing.

## MANDATORY RESTRICTIONS — gh (GitHub CLI)

Only read operations and updating PR descriptions via `gh edit` are permitted.

### FORBIDDEN gh Operations
| Operation | Reason |
|-----------|--------|
| `gh pr create` / `gh pr merge` / `gh pr close` | Would create or modify pull requests |
| `gh issue create` / `gh issue close` | Would modify issues |
| `gh release create` | Would create releases |
| `gh repo fork` / `gh repo create` / `gh repo delete` | Would create or delete repositories |

# --- DANGER GUARDRAILS END ---
