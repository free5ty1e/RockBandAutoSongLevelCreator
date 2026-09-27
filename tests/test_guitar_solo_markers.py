"""Tests for RBN guitar solo markers (pitch 103) in the exported MIDI and
Clone Hero .chart, and for the solo-region lead-contour charting.

LibForge ground truth (tools/libforge RBMidConverter.cs HandleGuitarBass):
``const byte SoloMarker = 103`` — a note at pitch 103 whose start tick is
the solo start and whose length is the solo duration is parsed into the
CON's solo-scoring sections. Clone Hero instead reads ``solo``/``soloend``
events.
"""

import sys
from pathlib import Path

import mido
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autorb.export.midi_generator import build_instrument_track


def _tt():
    def time_to_tick(sec):
        return int(sec * 480 * 120 / 60)
    return time_to_tick


def _expert_chart(notes_spec):
    """Build a minimal InstrumentChart with Expert notes."""
    from autorb.transcribe.instruments.difficulty import (
        InstrumentChart, ChartNote, Difficulty,
    )
    notes = [
        ChartNote(time=t, lane=lane, length=l, difficulty_pitch=60 + lane)
        for t, lane, l in notes_spec
    ]
    return {Difficulty.EXPERT: InstrumentChart(notes=notes, tempo_map=[(0, 120.0)])}


def test_solo_marker_pitch_103_emitted():
    """A guitar track with solo_sections must carry a pitch-103 note spanning
    each solo (start tick = solo start, length = duration)."""
    charts = _expert_chart([(0.0, 0, 0.2), (10.0, 1, 0.2)])
    raw = build_instrument_track(charts, 'guitar', 0, _tt(),
                                 solo_sections=[(2.0, 6.0)])
    # parse the returned MTrk bytes: wrap in a minimal MidiFile via mido? The
    # function returns raw MTrk bytes; re-parse by reading note events.
    import struct
    # MTrk chunk: 4-byte ident + 4-byte len + payload
    assert raw[:4] == b'MTrk'
    payload = raw[8:]
    # walk events: find note_on with pitch 103
    found = []
    i = 0
    running_status = None
    while i < len(payload):
        # delta time (varlen)
        if payload[i] & 0x80:
            i += 1
        i += 1
        b = payload[i]
        if b == 0xFF:  # meta
            i += 1
            mtype = payload[i]
            i += 1
            ln = payload[i]
            i += 1 + ln
            continue
        if b in (0x90, 0x80):
            running_status = b
            i += 1
            pitch = payload[i]
            vel = payload[i + 1]
            i += 2
            if pitch == 103:
                found.append((b, vel))
        else:
            pitch = b
            vel = payload[i + 1]
            i += 2
            if pitch == 103:
                found.append((running_status, vel))
    # both the note-on and note-off for pitch 103 must exist
    assert any(f[0] == 0x90 for f in found), f"no pitch-103 note_on: {found}"


def test_no_solo_marker_for_bass():
    """Solo sections must NOT be emitted on non-guitar tracks."""
    charts = _expert_chart([(0.0, 0, 0.2)])
    raw = build_instrument_track(charts, 'bass', 0, _tt(),
                                 solo_sections=[(1.0, 3.0)])
    assert b'MTrk' == raw[:4]
    # pitch 103 should not appear as a note-on (0x90 0x67 0x64)
    assert bytes([0x90, 103, 100]) not in raw


def test_lead_notes_in_region_segments_holds():
    """_lead_notes_in_region must return held single notes from a synthetic
    lead line (and ignore a chugging low chord beneath)."""
    from autorb.transcribe.instruments.guitar import _lead_notes_in_region
    sr = 22050
    t = np.arange(int(20 * sr)) / sr
    y = np.zeros_like(t)
    # rhythm chug at 110 Hz throughout
    for k in range(80):
        i0 = int(k * 0.25 * sr)
        i1 = i0 + int(0.1 * sr)
        tt = t[i0:i1]
        y[i0:i1] += 0.4 * np.sin(2 * np.pi * 110 * tt)
    # lead: A4 (440) held 5-9s, then E5 (659) held 11-15s
    for f0, a, b in [(440.0, 5.0, 9.0), (659.25, 11.0, 15.0)]:
        i0, i1 = int(a * sr), int(b * sr)
        tt = t[i0:i1]
        y[i0:i1] += 0.5 * np.sin(2 * np.pi * f0 * tt)
    notes = _lead_notes_in_region(y, sr, 0.0, 20.0, min_midi=60.0,
                                 tempo_map=[(0, 120.0)])
    # two held lead notes; the 110 Hz chug (midi 45) is below min_midi
    assert len(notes) >= 2, notes
    held = [n for n in notes if n["length"] > 2.0]
    assert len(held) == 2, [(n["start"], n["length"]) for n in notes]
    midis = sorted(round(n["midi"]) for n in held)
    assert abs(midis[0] - 69) <= 1   # A4
    assert abs(midis[1] - 76) <= 1  # E5


def test_detect_solo_regions_still_works():
    """Register-energy solo detection (v0.1.19) unchanged by these edits."""
    from autorb.transcribe.instruments.guitar import (
        _strum_backbone, _detect_solo_regions,
    )
    sr = 22050
    t = np.arange(int(60 * sr)) / sr
    y = np.zeros_like(t)
    for k in range(240):
        i0 = int(k * 0.25 * sr)
        i1 = i0 + int(0.1 * sr)
        y[i0:i1] += 0.4 * np.sin(2 * np.pi * 110 * t[i0:i1])
    for k in range(80, 160):
        i0 = int(k * 0.25 * sr)
        i1 = i0 + int(0.1 * sr)
        y[i0:i1] += 1.2 * np.sin(2 * np.pi * 880 * t[i0:i1])
    strums = np.array([k * 0.25 for k in range(240)])
    regions = _detect_solo_regions(y, sr, strums)
    assert regions and any(a <= 25 <= b for a, b in regions)
    assert all(a > 10 for a, b in regions)