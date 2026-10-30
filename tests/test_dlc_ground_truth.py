"""Tests for tools/dlc_ground_truth.py (v0.1.39).

The analyzer reads format-1 MIDI charts (official DLC + our own output).
The load-bearing detail: tempo events live in the CONDUCTOR track, not in
each PART track — the first version scanned tempo per-track and silently
computed every gem's seconds at a stale 120 BPM (the "chart truncated at
147s" false alarm on 2026-10-28). These tests pin the global-tempo-map
semantics with a synthetic format-1 file: a conductor track carrying a tempo
CHANGE mid-song, plus a PART GUITAR track whose gems must land at the true
times after the change.
"""

import struct
import sys
from pathlib import Path

import pytest

from mido import Message, MetaMessage, MidiFile, MidiTrack

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dlc_ground_truth import load_track_events  # noqa: E402


def _build_midi(path: Path) -> None:
    """Format-1: conductor track with a mid-song tempo change (120 -> 60 BPM),
    PART GUITAR with gems at t=1s (pre-change) and t=3s (post-change)."""
    mid = MidiFile(type=1)
    tpb = 480
    mid.ticks_per_beat = tpb

    # conductor: tempo 120 BPM (500000 us/beat) for 2 beats, then 60 BPM
    cond = MidiTrack()
    cond.append(MetaMessage("set_tempo", tempo=500000, time=0))
    cond.append(MetaMessage("set_tempo", tempo=1000000, time=2 * tpb))
    mid.tracks.append(cond)

    gtr = MidiTrack()
    gtr.append(MetaMessage("track_name", name="PART GUITAR", time=0))
    # gem at t=0.5s: delta 480 ticks at 500000us/beat (1 beat @120 BPM),
    # Expert lane 0 (pitch 96)
    gtr.append(Message("note_on", note=96, velocity=100, time=tpb))
    gtr.append(Message("note_off", note=96, velocity=0, time=60))
    # gem at t=2.0s: 0.625s + delta 900 = tick 1440; 960 ticks at 120 BPM
    # (1.0s) then 480 ticks at 60 BPM (1.0s) => 2.0s
    gtr.append(Message("note_on", note=97, velocity=100, time=900))
    gtr.append(Message("note_off", note=97, velocity=0, time=60))
    mid.tracks.append(gtr)
    mid.save(path)


def test_global_tempo_map_semantics(tmp_path):
    p = tmp_path / "official_like.mid"
    _build_midi(p)
    data = load_track_events(p)
    tr = data["tracks"]["PART GUITAR"]
    times = sorted(t for t, _ in tr["difficulties"]["expert"]["_gem_times"])
    assert len(times) == 2
    # t=0.5s (before the change) and t=2.0s (1.0s at 120 BPM to the change
    # tick 960, then tick 1440 is 480 ticks at 60 BPM = +1.0s)
    assert times[0] == pytest.approx(0.5, abs=0.02)
    assert times[1] == pytest.approx(2.0, abs=0.02)


def test_difficulty_and_lane_decode(tmp_path):
    p = tmp_path / "official_like.mid"
    _build_midi(p)
    data = load_track_events(p)
    d = data["tracks"]["PART GUITAR"]["difficulties"]["expert"]
    assert d["notes"] == 2
    assert d["lanes"] == {"G": 1, "R": 1}  # pitch 96 -> lane 0 (G), 97 -> lane 1 (R)


def test_bpm_range_reported(tmp_path):
    p = tmp_path / "official_like.mid"
    _build_midi(p)
    data = load_track_events(p)
    assert data["bpm_min"] == pytest.approx(60.0)
    assert data["bpm_max"] == pytest.approx(120.0)
