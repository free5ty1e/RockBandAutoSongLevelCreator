"""Map AutoRB CLI log lines to a UI stage + progress percent.

The CLI prints human markers (click.echo) as it walks its stages; this module
turns those into (stage_name, progress_0_to_1) for the web UI's progress bar,
plus the intra-stage strip counter from the Demucs separation messages
("separating strip 7/19 ..."), which is the longest stage by far.

Pure functions only — no I/O — so the whole thing is unit-testable.
"""

from __future__ import annotations

import re

# (marker substring, cumulative progress when this point is REACHED).
# Weights are rough wall-clock shares of a typical CPU run (separation
# dominates). A single log line can match several markers (e.g.
# "[1/5] Skipping Demucs separation" matches both "[1/5]" and the skip
# marker) — the highest-progress match wins, so the furthest-along reading
# is always taken.
_STAGE_MARKERS: list[tuple[str, float]] = [
    ("Starting AutoRB Pipeline", 0.00),
    ("[1/5]", 0.02),
    ("Separating stems", 0.02),
    ("Loading Demucs model", 0.02),
    ("Skipping Demucs separation", 0.30),
    ("[2/5]", 0.30),
    ("[3/5]", 0.34),
    ("[4/5]", 0.42),
    ("[4b/5]", 0.46),
    ("[5/5]", 0.48),
    ("Generating vocal MIDI chart", 0.60),
    ("Generating songs.dta metadata", 0.66),
    ("Packaging into CON container", 0.68),
    ("CON file successfully packaged", 0.70),
    ("[6/5]", 0.70),
    ("Clone Hero song exported", 0.82),
    ("[7/5]", 0.82),
    ("Validating guitar chart against tab guide", 0.84),
    ("Guitar error rating", 0.88),
    ("PS4 PKG installer successfully built", 0.90),
    ("Pipeline complete", 1.00),
]

# Intra-stage strip progress: "  separating strip 7/19 (htdemucs_ft)..."
_STRIP_RE = re.compile(r"separating strip (\d+)/(\d+)")

# Separation spans [0.02, 0.30): strip k/m maps linearly inside that band.
_STRIP_BAND = (0.02, 0.30)


def parse_stage(line: str) -> tuple[str | None, float | None]:
    """Return (marker, progress) for the best-matching stage marker, else (None, None).

    ``progress`` is the cumulative progress when this point is reached. When a
    line matches several markers, the one furthest along wins.
    """
    best_marker, best_prog = None, None
    for marker, prog in _STAGE_MARKERS:
        if marker in line and (best_prog is None or prog > best_prog):
            best_marker, best_prog = marker, prog
    return best_marker, best_prog


def parse_strip(line: str) -> float | None:
    """Return fine-grained separation progress for a strip message, else None."""
    m = _STRIP_RE.search(line)
    if not m:
        return None
    k, total = int(m.group(1)), int(m.group(2))
    if total <= 0:
        return None
    k = min(max(k, 0), total)
    lo, hi = _STRIP_BAND
    return lo + (hi - lo) * (k / total)


def next_progress(line: str, current: float) -> float | None:
    """Fold one log line into a new progress value, or None if it carries none.

    Progress never regresses: stage markers and the strip counter only move
    forward. Strip lines are ignored once a later stage has started (after an
    OOM retry the strip counter restarts at 1/m; the max() keeps the bar put).
    """
    strip = parse_strip(line)
    if strip is not None and current < _STRIP_BAND[1]:
        return max(current, strip)

    _marker, prog = parse_stage(line)
    if prog is not None and prog > current:
        return prog

    return None


def stage_label(progress: float) -> str:
    """Human-readable stage name for a progress value (for the status line)."""
    if progress >= 1.0:
        return "Done"
    labels = [
        (0.02, "Starting"),
        (0.30, "Separating stems"),
        (0.34, "Detecting tempo"),
        (0.42, "Aligning vocals"),
        (0.46, "Transcribing instruments"),
        (0.60, "Building MOGG + charts"),
        (0.70, "Packaging CON"),
        (0.82, "Exporting Clone Hero"),
        (0.84, "Validating guitar chart"),
        (0.90, "Building PS4 PKG"),
    ]
    for threshold, name in labels:
        if progress < threshold:
            return name
    return "Finishing up"
