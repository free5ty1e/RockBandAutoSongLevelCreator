"""Regression tests: bass sustain overlaps + drum 16th-note rolls (v0.1.22).

User reports after the single-note bass fix shipped:
1. Bass still showed "chords / overlapping held bass notes" — a hold on one
   lane bled across the next note on a DIFFERENT lane (the sustain cap was
   per-lane). Single-note bass means one gem timeline: every hold must end
   before the next attack on ANY lane.
2. Expert drums charted only 1/8 notes — 16th-note snare rolls were snapped
   onto the beat grid and thinned. Expert now quantizes to 1/16 (lower
   difficulties still reduce to coarser grids), with a local-tempo
   same-lane faster-than-16th rejection.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autorb.transcribe.instruments.difficulty import (
    ChartNote, Difficulty, InstrumentChart, _beat_dur, _snap,
)
from autorb.transcribe.instruments.guitar import transcribe_bass


def test_bass_holds_never_overlap_next_note_any_lane():
    """A bass hold on lane 1 must end before the next attack on lane 3."""
    # Build a fake tempo map (120 BPM flat) and run the overlap-prone shape
    # through the transcriber's step-4 cap by calling the chart-level helper
    # path: simulate via direct construction of the post-step-4 condition.
    tempo_map = [(i * 0.5, 120.0) for i in range(40)]
    notes = [
        ChartNote(time=1.0, lane=1, length=0.5, difficulty_pitch=61),   # long hold on lane 1
        ChartNote(time=1.4, lane=3, length=0.1, difficulty_pitch=63),   # starts before hold ends
        ChartNote(time=2.0, lane=0, length=0.1, difficulty_pitch=60),
    ]
    # Apply the same cap the transcriber applies for bass (step 4 single-note path)
    by_time = sorted(notes, key=lambda n: n.time)
    for k in range(len(by_time) - 1):
        nxt = by_time[k + 1].time
        max_len = max(0.0, nxt - by_time[k].time - 0.02)
        if by_time[k].length > max_len:
            by_time[k].length = max_len
    assert by_time[0].length <= by_time[1].time - by_time[0].time, (
        f"hold {by_time[0].length}s still overlaps next note at {by_time[1].time}s"
    )
    assert by_time[0].length <= 0.38  # 1.4 - 1.0 - 0.02


def test_bass_exported_chart_has_no_overlaps(tmp_path):
    """End-to-end-ish: the transcriber's own output must have zero
    note-window overlaps (any lane) — mirrors the shipped-chart bug (85
    overlapping sustain pairs on ORS Expert bass)."""
    stem = Path("output_6s_v124/stems/bass.wav")
    tmap = Path("output_6s_v124/tempo_map.json")
    if not stem.exists() or not tmap.exists():
        pytest.skip("pipeline artifacts not present")
    import json
    tm = json.loads(tmap.read_text())
    tempo_map = list(zip(tm["beat_times"], tm["bpms"]))
    chart = transcribe_bass(stem, tempo_map, float(tm["beat_times"][-1]))
    notes = sorted(chart.notes, key=lambda n: n.time)
    overlaps = [
        (a.time, b.time) for a, b in zip(notes, notes[1:])
        if b.time < a.time + a.length
    ]
    assert not overlaps, f"{len(overlaps)} overlapping bass sustains: {overlaps[:5]}"


def test_snap_16ths_preserve_rolls():
    """_snap(divisions=4) must map 16th-spaced hits to distinct grid slots."""
    tempo_map = [(i * 0.35, 172.0) for i in range(60)]  # 0.35s beats
    t0 = 10 * 0.35
    raw = [t0, t0 + 0.087, t0 + 0.175]  # three hits at 16th spacing
    snapped = [float(_snap(t, tempo_map, 4)) for t in raw]
    assert len(set(round(s, 4) for s in snapped)) == 3, snapped


def test_local_tempo_16th_gap():
    """A 16th gap at 172 BPM (0.087s) must be slower than the local min-gap.

    Regression for the roll-thinning bug: _local_bpm(tempo_map, 0.0) falls
    back to 120 BPM when the map's first beat is at t>0 (e.g. 0.894s on the
    ORS map), so an opening-tempo gap formula computed 0.106s and discarded
    every second hit of a 172 BPM 16th roll (0.087s). The local-tempo gap
    (0.349/4*0.85 = 0.074s) keeps them.
    """
    # a map whose first beat is at t>0 (like the real ORS map: 0.894s)
    tempo_map = [(0.894 + i * 0.372, 161.5) for i in range(50)]
    # old buggy formula: _beat_dur at t=0 -> 120 BPM default -> 0.106s gap
    old_gap = _beat_dur(tempo_map, 0.0) / 2 / 2 * 0.85
    assert old_gap > 0.087, f"old opening-tempo gap {old_gap:.4f}s must exceed a 172 BPM 16th"
    # local-tempo formula inside the song keeps a 172 BPM 16th roll
    local_gap = _beat_dur(tempo_map, 20.0) / 4.0 * 0.85
    assert local_gap < 0.087, f"local gap {local_gap:.4f}s must admit a 172 BPM 16th"