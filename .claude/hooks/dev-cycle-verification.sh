#!/usr/bin/env bash
# Stop-hook: dev-cycle verification (AutoRB project rule).
#
# When Claude finishes a development cycle, verify the handoff contract:
#   1. changes validated (tests ran this session — pytest cache touched recently)
#   2. intended changes are STAGED (git index non-empty when the worktree had edits)
#   3. a commit message was suggested (can't be checked mechanically; the
#      systemMessage reminds Claude to include one)
#
# If any check fails, emits a systemMessage telling Claude what's missing so it
# completes the cycle before the user reads a "done" that isn't done.
# Never blocks on repos with no modifications (e.g. pure Q&A turns).

cd "$(dirname "$0")/../.." || exit 0

msgs=()

# Only relevant when source/docs were modified or are staged.
unstaged=$(git status --porcelain 2>/dev/null | grep -vE '^\?\?|^A |^M ' | head -1)
staged=$(git diff --cached --name-only 2>/dev/null | head -1)
worktree_changed=$(git status --porcelain 2>/dev/null | grep -E '^ ?M|^ ?D|^ ?\?\? ' | grep -vE '^\?\? (output|\.tmp|\.claude_persist|\.opencode|\.vscode|\.claude_zen|\.claude_config)' | head -1)

# 1. Tests ran recently? (.pytest_cache last-write within 30 min on this repo)
if [ -n "$worktree_changed" ]; then
  if [ -d .pytest_cache ]; then
    newest=$(find .pytest_cache -newermt '-45 minutes' -print -quit 2>/dev/null)
    [ -z "$newest" ] && msgs+=("Tests have NOT been run in the last 45 minutes — run the relevant pytest suites (and integration checks where applicable) before handing off.")
  else
    msgs+=("No .pytest_cache found — run the test suite before handing off changes.")
  fi
fi

# 2. Changes staged? Only when tracked files are modified beyond the index.
if [ -n "$worktree_changed" ] && [ -z "$staged" ]; then
  msgs+=("Modified files are NOT staged. Stage your specific intended changes with 'git add <files>' (never commit).")
fi

if [ ${#msgs[@]} -gt 0 ]; then
  text="Dev-cycle verification failed:"
  for m in "${msgs[@]}"; do text="$text • $m"; done
  text="$text • Remember to suggest a commit message for the staged changes for user review."
  python3 - "$text" <<'PYEOF'
import json, sys
print(json.dumps({"systemMessage": sys.argv[1]}))
PYEOF
else
  echo '{"systemMessage": "Dev-cycle verification passed: tests run, changes staged, ready for commit-message review."}'
fi
exit 0
