"""Tests for the guitar tab alignment / strum-backbone tools and helpers."""

import sys
from pathlib import Path
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from autorb.transcribe.instruments.guitar import (
    _strum_backbone,
    _grid_phase,
    _strum_chord_roots,
)
from autorb.transcribe.instruments.drums import limit_simultaneous_drums


def _synthetic_guitar(sr=44100, dur=5.0, strum_every=0.2):
    """Synthetic signal with distinct strum attacks every `strum_every` seconds.

    Each strum is a short noise burst (guitar-like wideband attack).
    """
    t = np.arange(int(sr * dur)) / sr
    x = 0.01 * np.random.randn(len(t))
    n = 0.0
    while (n + 0.05) < dur:
        i0 = int(n * sr)
        i1 = int((n + 0.05) * sr)
        x[i0:i1] += 0.5 * np.random.randn(i1 - i0)
        n += strum_every
    return x


def test_strum_backbone_counts_expected_strums():
    """10 strum attacks in 5s -> backbone should find ~10 (not 2x, not 0.5x)."""
    sr = 44100
    y = _synthetic_guitar(sr=sr, dur=5.0, strum_every=0.5)
    bb = _strum_backbone(y, sr)
    # Expect ~ ceil(5.0/0.5)=10 strums; allow a couple tolerance each way
    assert 7 <= len(bb) <= 12
    # strums should be ~0.5s apart
    diffs = np.diff(bb)
    assert np.all(diffs >= 0.04)


def test_strum_backbone_does_not_double_count():
    """A single short decaying strum burst must not yield multiple backbone times."""
    sr = 44100
    x = np.zeros(int(sr * 1.0))
    # realistic strum: short wideband attack (~40ms) with fast exponential decay
    i0 = int(0.3 * sr)
    n = int(0.04 * sr)
    x[i0:i0 + n] = 0.5 * np.random.randn(n) * np.exp(-np.arange(n) / (sr * 0.01))
    bb = _strum_backbone(x, sr)
    assert len(bb) <= 1


def test_grid_phase_aligns_strums_to_grid():
    """_grid_phase should recover a known 1/8-grid offset from strums."""
    import numpy as np
    # Build a fake tempo map: 120 BPM, beats at 0, 0.5, 1.0, ...
    beats = [i * 0.5 for i in range(40)]
    tempo_map = [(b, 120.0) for b in beats]
    # Strums on the 1/8 grid shifted by +0.0625 beats (a 16th late)
    phase_true = 0.0625
    strums = np.array([beats[i] + phase_true * 0.5 + j * 0.25
                       for i in range(2, 20) for j in range(0, 1)])
    ph = _grid_phase(strums, tempo_map, divisions=2)
    # recovered phase should put strums ON grid: ph + phase_true ~ 0.125 steps
    residual = (phase_true + ph) % 0.5
    assert min(residual, 0.5 - residual) < 0.06


def test_chord_roots_follow_pitch():
    """_strum_chord_roots must report a rising root for rising synthetic chords."""
    import numpy as np
    sr = 44100
    y = np.zeros(int(8.0 * sr))
    roots_hz = [110.0, 146.8, 196.0]  # A2, D3, G3
    t = 0.5
    times = []
    for hz in roots_hz:
        for k in range(3):  # 3 strums per chord
            i0 = int(t * sr)
            n = int(0.28 * sr)
            tt = np.arange(n) / sr
            tone = (np.sin(2 * np.pi * hz * tt) +
                    0.5 * np.sin(2 * np.pi * hz * 2 * tt))  # fundamental + octave
            y[i0:i0 + n] += 0.4 * tone * np.exp(-tt / 0.15)
            times.append(t)
            t += 0.35
    roots = _strum_chord_roots(y, sr, np.array(times))
    # MIDI of A2=45, D3=50, G3=55 (approx); 9 strums total, 3 per chord.
    assert np.median(roots[0:3]) > 43
    assert np.median(roots[3:6]) > np.median(roots[0:3]) + 3
    assert np.median(roots[6:9]) > np.median(roots[3:6]) + 3


def test_limit_simultaneous_drums_excludes_kick():
    """Three non-kick notes + a kick on one slot -> keeps kick + 2, drops 1."""
    from autorb.transcribe.instruments.difficulty import ChartNote
    notes = [
        ChartNote(time=1.0, lane=1, velocity=100, difficulty_pitch=38),  # snare
        ChartNote(time=1.0, lane=2, velocity=100, difficulty_pitch=42),  # hi-hat
        ChartNote(time=1.0, lane=4, velocity=100, difficulty_pitch=49),  # cymbal
        ChartNote(time=1.0, lane=0, velocity=100, difficulty_pitch=36),  # kick
    ]
    out = limit_simultaneous_drums(notes, max_simultaneous=2)
    lanes = sorted(n.lane for n in out)
    # kick (0) always kept; exactly 2 of the 3 non-kick kept
    assert 0 in lanes
    non_kick = [l for l in lanes if l != 0]
    assert len(non_kick) == 2


def test_limit_simultaneous_drums_keeps_snare_over_cymbal():
    """With 3 non-kick candidates, the cymbal (lowest priority after snare/hat) drops."""
    from autorb.transcribe.instruments.difficulty import ChartNote
    notes = [
        ChartNote(time=1.0, lane=4, velocity=100),  # cymbal
        ChartNote(time=1.0, lane=1, velocity=100),  # snare
        ChartNote(time=1.0, lane=2, velocity=100),  # hi-hat
    ]
    out = limit_simultaneous_drums(notes, max_simultaneous=2)
    lanes = sorted(n.lane for n in out)
    assert lanes == [1, 2]  # snare + hi-hat survive; cymbal dropped


def test_tab_parser_parses_standard_tab():
    from tools.guitar_tab_alignment.tab_parser import parse_tab
    tab = """\
e|-0-0-0-3-3-5-|
B|-1-1-1-1-1-3-|
G|-0-0-0-0-0-0-|
D|-2-2-2-2-2-2-|
A|-3-3-3-3-3-3-|
E|-------------|
"""
    cols = parse_tab(tab)
    assert len(cols) > 0
    # first column: D=2, A=3, E not played -> root = A3 freq (55Hz? no: A string open=45, +3 fret=48)
    c0 = cols[0]
    assert c0["root_midi"] == 48  # A3 (A string fret 3)
    assert set(c0["strings"].keys()) == {"e", "B", "G", "D", "A", "E"}