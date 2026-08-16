"""Regression test for MIDI track-count / BEAT-track integrity.

v0.0.95: ``generate_vocal_midi`` wrote 8 MTrk chunks (tempo + 4 instrument
tracks + vocals + EVENTS + BEAT) but the MThd header declared ``ntrks=7``.
Strict parsers (ForgeTool's MidiCS) read only 7 tracks and silently drop the
final BEAT track, so PS4 PKG conversion crashed with
"Sequence contains no elements" (it does ``tracks.Where(t => t.Name == "BEAT").First()``).
"""

import mido
import pytest

from autorb.export.midi_generator import generate_vocal_midi


def test_generated_midi_has_beat_track(tmp_path):
    # No synced json -> empty vocals; no instrument charts -> placeholders.
    # Fast path, no CREPE/WhisperX needed.
    out = tmp_path / "mid"
    out.mkdir()
    midi_path = generate_vocal_midi(
        tmp_path / "does_not_exist.json",  # not read -> empty items
        out,
        "test_song",
        beat_times=None,
        dynamic_bpms=None,
    )

    mid = mido.MidiFile(str(midi_path))
    names = [t.name for t in mid.tracks]
    assert "BEAT" in names, f"BEAT track missing; tracks={names}"
    # The header track count must equal the number of chunks actually written,
    # otherwise a strict parser drops the last (BEAT) track.
    assert mid.tracks, "no tracks parsed"
    # mido reads exactly the declared ntrks; if BEAT is present we're consistent.
    assert names.count("BEAT") == 1


def test_generated_midi_track_count_matches_header(tmp_path):
    out = tmp_path / "mid"
    out.mkdir()
    midi_path = generate_vocal_midi(
        tmp_path / "nope.json",
        out,
        "test_song",
        beat_times=None,
        dynamic_bpms=None,
    )
    # Raw header ntrks must equal the count mido recovers (no dropped track).
    with open(midi_path, "rb") as f:
        data = f.read()
    assert data[:4] == b"MThd"
    ntrks = int.from_bytes(data[10:12], "big")
    mid = mido.MidiFile(str(midi_path))
    assert ntrks == len(mid.tracks), (
        f"header ntrks={ntrks} but parsed {len(mid.tracks)} tracks "
        f"(BEAT likely dropped)"
    )


def _charts_with_lanes(lanes_per_diff):
    """Build minimal per-difficulty InstrumentCharts for an encoding test."""
    from autorb.transcribe.instruments.difficulty import (
        ChartNote,
        InstrumentChart,
    )

    charts = {}
    for diff, lanes in lanes_per_diff.items():
        notes = [
            ChartNote(
                time=0.5 * i,
                lane=l,
                length=0.1,
                difficulty_pitch=36 + l,
                velocity=100,
            )
            for i, l in enumerate(lanes)
        ]
        charts[diff] = InstrumentChart(notes=notes, tempo_map=[(0, 120)])
    return charts


def _count_per_difficulty(track_bytes):
    import io
    import struct

    full = b"MThd" + struct.pack(">IHHH", 6, 1, 1, 480) + track_bytes
    mid = mido.MidiFile(file=io.BytesIO(full))
    counts = {"easy": 0, "medium": 0, "hard": 0, "expert": 0, "bad": 0}
    for msg in mid.tracks[0]:
        if msg.type == "note_on" and msg.velocity > 0:
            k = msg.note
            if 60 <= k <= 64:
                counts["easy"] += 1
            elif 72 <= k <= 76:
                counts["medium"] += 1
            elif 84 <= k <= 88:
                counts["hard"] += 1
            elif 96 <= k <= 100:
                counts["expert"] += 1
            else:
                counts["bad"] += 1
    return counts


def test_instrument_tracks_use_difficulty_offset_pitches():
    """v0.0.96: drums/keys must be lane-encoded (base+lane), not raw pitches.

    ForgeTool's HandleDrumTrk/HandleGuitarBass only accept difficulty-offset
    pitches (Easy 60-64 / Medium 72-76 / Hard 84-88 / Expert 96-100). Raw 35-59
    drum sound pitches or true key pitches left every difficulty gem-track null
    and crashed PKG conversion with a NullReferenceException.
    """
    from autorb.export.midi_generator import build_instrument_track

    charts = _charts_with_lanes(
        {
            "expert": [0, 1, 2, 3, 4],
            "hard": [0, 1, 2, 3],
            "medium": [0, 1, 2],
            "easy": [0, 1],
        }
    )
    t2t = lambda sec: int(sec * 480)

    for inst in ("drums", "keys", "guitar", "bass"):
        counts = _count_per_difficulty(
            build_instrument_track(charts, inst, 0, t2t)
        )
        assert counts["bad"] == 0, f"{inst}: out-of-range pitch {counts}"
        for diff in ("easy", "medium", "hard", "expert"):
            assert counts[diff] > 0, f"{inst}: empty {diff} difficulty"

