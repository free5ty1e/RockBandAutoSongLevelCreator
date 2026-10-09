"""Align a tab's pitch/strum contour to the audio ground-truth strums.

The tab encodes the **relative** pitch contour (each strum's root pitch) and
how many strums per beat, but NOT absolute timing. The audio ground truth gives
absolute strum times with per-strum f0. We align the two with **Dynamic Time
Warping (DTW)** on the pitch contour: find the mapping that makes the tab's
pitch sequence track the audio's pitch sequence with minimal pitch error and
monotone timing. The result is a timestamped tab guide.

DTW is used because Basic Pitch / the transcriber misassigned pitches — we do
NOT want to lock onto its (possibly wrong) fret positions; we only use it to
line up the tab's chord/strum rhythm with the audio's real strum attack times.
"""

import numpy as np
from pathlib import Path


def _pitch_cost(tab_midi, audio_f0):
    """Cost of matching a tab column (root midi) to an audio strum (f0 hz).

    Returns inf when either side is missing; otherwise a pitch distance in
    semitones (converted: midi is already linear; f0 hz -> midi).
    """
    if tab_midi is None or audio_f0 is None or audio_f0 <= 0:
        return 1e9
    audio_midi = 69 + 12 * np.log2(audio_f0 / 440.0)
    return abs(tab_midi - audio_midi)


def dtw_align(tab_roots: list, audio_f0s: list) -> list:
    """Return the list of ``(tab_idx, audio_idx)`` DIAGONAL matches.

    Standard DTW with a skip penalty for unmatched tab columns and audio
    strums; only diagonal moves (tab col i matched to audio strum j) are
    returned as genuine correspondences. Audio strums with no pitch (f0 None)
    cost nothing to skip, so they don't force wrong alignments.

    Returns a list of (i, j) in order.
    """
    n, m = len(tab_roots), len(audio_f0s)
    if n == 0 or m == 0:
        return []
    INF = 1e18
    cost = np.full((n + 1, m + 1), INF)
    cost[0, 0] = 0.0
    for i in range(1, n + 1):
        cost[i, 0] = i * 3.0
    for j in range(1, m + 1):
        cost[0, j] = j * 3.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            p = _pitch_cost(tab_roots[i - 1], audio_f0s[j - 1])
            cost[i, j] = p + min(
                cost[i - 1, j] + 0.5,     # skip a tab column
                cost[i, j - 1] + 0.5,     # skip an audio strum
                cost[i - 1, j - 1],       # match
            )
    # Backtrack, remembering only diagonal (match) moves.
    path = []
    i, j = n, m
    while i > 0 and j > 0:
        diag = cost[i - 1, j - 1]
        up = cost[i - 1, j]
        left = cost[i, j - 1]
        if diag <= up and diag <= left:
            path.append((i - 1, j - 1))
            i -= 1; j -= 1
        elif up <= left:
            i -= 1
        else:
            j -= 1
    path.reverse()
    return path


def align(tab_columns: list, audio_guide: list) -> list:
    """Return tab columns with assigned audio times.

    Each output: {"column": tab_column, "time": audio_strum_time or None,
                  "matched_f0": f0 or None}
    """
    tab_roots = [c["root_midi"] for c in tab_columns]
    audio_f0s = [g["f0"] for g in audio_guide]
    audio_times = [g["time"] for g in audio_guide]

    path = dtw_align(tab_roots, audio_f0s)
    # path is list of (tab_idx, audio_idx) matched pairs (some may be None if skipped)

    # Build time assignment: each tab column that was matched gets the audio time
    assigned = []
    matched_tab = {}
    for tab_i, aud_j in path:
        matched_tab[tab_i] = (audio_times[aud_j], audio_f0s[aud_j])

    for ti, col in enumerate(tab_columns):
        if ti in matched_tab:
            t, f0 = matched_tab[ti]
            assigned.append({"column": col, "time": t, "matched_f0": f0})
        else:
            # Unmatched (audio had no strum for it). Leave a gap marker.
            assigned.append({"column": col, "time": None, "matched_f0": None})
    return assigned


if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    from tab_parser import parse_tab
    from audio_ground_truth import build_ground_truth

    tab_cols = parse_tab(Path(sys.argv[1]).read_text())
    guide = build_ground_truth(sys.argv[2]) if len(sys.argv) > 2 else []
    out = align(tab_cols, guide)
    print(json.dumps(out, indent=2))
    print(f"... {len(out)} columns aligned, {sum(1 for o in out if o['time'] is not None)} matched")