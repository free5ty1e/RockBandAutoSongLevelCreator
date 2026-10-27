"""Reference-material sources and staging for charting (Tier 0/1).

The charting-accuracy plan (`.ai_memory/plans/tab_backed_charting_and_accuracy.md`)
adds a deterministic post-separation stage that gathers *reference material*
for a song — user-supplied tabs (Tier 0) and web-discovered tabs (Tier 1) —
and stages it under `<output>/reference_tabs/` for the (future) tab-sync and
tab-as-chart modes. This package holds the fetch/stage logic; it never
triggers implicitly: web fetching is strictly opt-in (`--fetch-tabs` on the
CLI, the acknowledged disclaimer checkbox in the web UI).

Copyright stance (AGENTS.md / CLAUDE.md release rules): tabs are user-made
arrangements. We never COMMIT fetched tab content to the repo; fetched
material lives only inside the (git-ignored) job output dir, and the web UI
requires an explicit disclaimer acknowledgement before fetching.
"""

from .tab_fetch import (
    TabCandidate,
    attempt_gpx_download,
    build_report,
    run_tab_fetch_stage,
    search_songsterr,
)

__all__ = [
    "TabCandidate",
    "attempt_gpx_download",
    "build_report",
    "run_tab_fetch_stage",
    "search_songsterr",
]
