"""Regression tests for pitch -> 5-lane mapping robustness.

Covers the v0.0.95 fix where ``pitch_to_fret_string`` returned ``None`` for
out-of-range pitches and ``build_lane_map`` then crashed on ``fret_pos.fret``.
"""

import numpy as np
import pytest

from autorb.transcribe.instruments.pitch_to_lane import (
    Tuning,
    pitch_to_fret_string,
    build_lane_map,
)


def _guitar_tuning():
    return Tuning.standard_guitar()


@pytest.mark.parametrize("hz", [20.0, 30.0, 5000.0, 8000.0, 0.0, -5.0, None])
def test_pitch_to_fret_string_never_none(hz):
    """Extreme / degenerate pitches must still yield a FretPosition, not None."""
    pos = pitch_to_fret_string(hz, _guitar_tuning())
    assert pos is not None
    assert 0 <= pos.fret <= 22
    assert pos.string >= 0


def test_pitch_to_fret_string_in_range_returns_valid_fret():
    # A4 = 440 Hz sits comfortably within standard guitar range.
    pos = pitch_to_fret_string(440.0, _guitar_tuning())
    assert pos is not None
    assert 0 <= pos.fret <= 22


def test_build_lane_map_handles_out_of_range_pitches():
    """build_lane_map must not raise on pitches outside the fret range."""
    tuning = _guitar_tuning()
    onsets = [
        (0.0, 440.0),    # in range
        (0.5, 20.0),     # far too low
        (1.0, 6000.0),   # far too high
        (1.5, 0.0),      # degenerate
    ]
    notes = build_lane_map(onsets, tuning, 'expert')
    assert len(notes) == 4
    for n in notes:
        assert n['lane'] is not None
        assert 0 <= n['fret'] <= 22


def test_build_lane_map_open_string_lane_is_minus_one():
    # An open-string pitch (low E2 = 82.41 Hz) should map to the open lane (-1).
    tuning = _guitar_tuning()
    notes = build_lane_map([(0.0, 82.41)], tuning, 'expert')
    assert notes[0]['is_open'] is True
    assert notes[0]['lane'] == -1
