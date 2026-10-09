"""Bass single-note rule (RBN Guitar/Bass authoring).

Bass charts must be single notes: chords are super-rare on bass (2-note
double-stops only, deliberate) and 3-note bass chords are unheard of. The
Open Road Song Expert bass chart shipped 247 two-note + 46 three-note chords
before this rule; the transcriber and the difficulty reducer both now
enforce single-note bass at every difficulty.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autorb.transcribe.instruments.difficulty import (
    ChartNote, Difficulty, InstrumentChart, create_all_difficulties,
    _build_events, _single_note_slots,
)


def _bass_charts_with_chords():
    """Crafted Expert 'bass' with same-slot multi-lane notes and real chords."""
    notes = [
        # a 3-note "chord" at t=1.0
        ChartNote(time=1.0, lane=0, difficulty_pitch=60),
        ChartNote(time=1.0, lane=2, difficulty_pitch=62),
        ChartNote(time=1.0, lane=4, difficulty_pitch=64),
        # single note
        ChartNote(time=2.0, lane=3, difficulty_pitch=63),
        # 2-note same-slot
        ChartNote(time=3.0, lane=1, difficulty_pitch=61),
        ChartNote(time=3.0, lane=4, difficulty_pitch=64),
    ]
    notes[0].is_chord = True
    notes[0].chord_notes = notes[:3]
    return InstrumentChart(notes=notes, tempo_map=[(0, 120.0)])


def test_single_note_slots_keeps_lowest_lane():
    notes = [ChartNote(time=1.0, lane=2), ChartNote(time=1.0, lane=0),
             ChartNote(time=1.0, lane=4), ChartNote(time=2.0, lane=3)]
    out = _single_note_slots(notes)
    assert [(n.time, n.lane) for n in out] == [(1.0, 0), (2.0, 3)]
    assert all(not n.is_chord for n in out)


def test_bass_reduction_is_single_note_at_every_difficulty():
    chart = _bass_charts_with_chords()
    charts = create_all_difficulties(chart, "bass")
    # Expert is passed through as-is by create_all_difficulties (the
    # transcriber's step-6b enforces single-note Expert bass); the reducer
    # guards Hard/Medium/Easy regardless of what Expert contains.
    for diff in (Difficulty.HARD, Difficulty.MEDIUM, Difficulty.EASY):
        c = charts[diff]
        lanes_at_slot = {}
        for n in c.notes:
            lanes_at_slot.setdefault(round(n.time, 4), set()).add(n.lane)
        multi = {t: l for t, l in lanes_at_slot.items() if len(l) > 1}
        assert not multi, f"{diff.value}: multi-lane slots {multi}"
        assert all(not n.is_chord for n in c.notes), f"{diff.value}: chord flags set"


def test_guitar_chords_survive_guitar_reduction():
    """The single-note rule must NOT bleed into guitar."""
    notes = [
        ChartNote(time=1.0, lane=0, difficulty_pitch=60),
        ChartNote(time=1.0, lane=2, difficulty_pitch=62),
        ChartNote(time=2.0, lane=3, difficulty_pitch=63),
    ]
    notes[0].is_chord = True
    notes[0].chord_notes = notes[:2]
    chart = InstrumentChart(notes=notes, tempo_map=[(0, 120.0)])
    charts = create_all_difficulties(chart, "guitar")
    # Expert keeps its chord
    expert = charts[Difficulty.EXPERT]
    assert any(n.is_chord for n in expert.notes)
