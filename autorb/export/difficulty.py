#!/usr/bin/env python
"""Automatic per-instrument difficulty (rank) calculation for songs.dta.

Rock Band stores each instrument's difficulty as a ``(rank ...)`` value in
``songs.dta`` (roughly 0-350 in practice; official DLC peaks around 311).
AutoRB historically hardcoded ``150`` for every instrument, which made every
song render as "1 of 6" difficulty in-game.

This module derives the rank from the chart's actual note density (notes per
second), calibrated per instrument against the reference "311 - Down" DLC
(5411 drum / 3382 guitar / 1775 bass / 599 vocal note-ons over 179s mapping
to ranks 311 / 250 / 225 / 144, verified against ``pretty_midi``).  Note
counts include every difficulty level and drum-chord lanes, so the factors
are tuned to that aggregate density.  ``band`` is the mean of the four,
matching the reference (311's band 233 = mean(311, 250, 225, 144)).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_RANK_FACTORS = {
    "drum": 10.0,
    "guitar": 13.0,
    "bass": 22.0,
    "vocals": 43.0,
}

_RANK_CAPS = {
    "drum": 350,
    "guitar": 300,
    "bass": 280,
    "vocals": 220,
}

TRACK_TO_INSTRUMENT = {
    "PART DRUMS": "drum",
    "PART GUITAR": "guitar",
    "PART BASS": "bass",
    "PART VOCALS": "vocals",
}


def _read_varlen(data: bytes, pos: int):
    value = 0
    while True:
        b = data[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            break
    return value, pos


def _track_name_and_notes(track: bytes):
    """Returns (track_name, note_count) for one MTrk chunk."""
    name = ""
    notes = 0
    pos = 0
    running = 0

    while pos < len(track):
        _, pos = _read_varlen(track, pos)
        if pos >= len(track):
            break
        event = track[pos]

        if event == 0xFF:
            pos += 1
            if pos >= len(track):
                break
            meta_type = track[pos]
            pos += 1
            if pos >= len(track):
                break
            length, pos = _read_varlen(track, pos)
            if meta_type == 0x03:
                name = track[pos:pos + length].decode("latin1", errors="replace")
            pos += length
            running = 0
        elif event == 0xF0 or event == 0xF7:
            length, pos = _read_varlen(track, pos)
            pos += length
            running = 0
        elif event >= 0x80:
            running = event
            if event & 0xF0 in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                if event & 0xF0 == 0x90 and pos + 2 < len(track):
                    if track[pos + 2] > 0:
                        notes += 1
                pos += 3
            else:
                pos += 1
        else:
            if running & 0xF0 in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                if running & 0xF0 == 0x90 and pos + 1 < len(track):
                    if track[pos + 1] > 0:
                        notes += 1
                pos += 2
            else:
                pos += 1

    return name, notes


def count_notes_per_track(midi_path: str | Path) -> dict:
    """Returns {track_name: note_count} parsed from a Rock Band MIDI chart."""
    data = Path(midi_path).read_bytes()
    if data[:4] != b"MThd":
        raise ValueError(f"Not a MIDI file: {midi_path}")

    track_count = int.from_bytes(data[10:12], "big")
    pos = 14  # MThd + header length + format + track count + division
    counts = {}
    for _ in range(track_count):
        if data[pos:pos + 4] != b"MTrk":
            break
        length = int.from_bytes(data[pos + 4:pos + 8], "big")
        track = data[pos + 8:pos + 8 + length]
        name, notes = _track_name_and_notes(track)
        counts.setdefault(name, 0)
        counts[name] += notes
        pos += 8 + length
    return counts


def _rank_from_density(density: float, instrument: str) -> int:
    factor = _RANK_FACTORS[instrument]
    cap = _RANK_CAPS[instrument]
    rank = max(1, min(cap, round(density * factor)))
    return rank


def compute_ranks(midi_path: str | Path, song_length_ms: int) -> dict:
    """Computes per-instrument (rank ...) values from chart note density.

    ``song_length_ms`` drives the density denominator; ``keys`` and the
    ``real_*`` pro guitar/bass/keys slots stay 0 (no chart data yet).
    """
    counts = count_notes_per_track(midi_path)
    duration_s = max(1.0, song_length_ms / 1000.0)

    ranks = {}
    for instrument, factor in _RANK_FACTORS.items():
        note_count = counts.get(next((k for k, v in TRACK_TO_INSTRUMENT.items() if v == instrument), ""), 0)
        ranks[instrument] = _rank_from_density(note_count / duration_s, instrument)

    ranks["band"] = max(1, round(
        (ranks["drum"] + ranks["guitar"] + ranks["bass"] + ranks["vocals"]) / 4
    ))

    return {
        "drum": ranks["drum"],
        "guitar": ranks["guitar"],
        "bass": ranks["bass"],
        "vocals": ranks["vocals"],
        "keys": 0,
        "real_guitar": 0,
        "real_bass": 0,
        "real_keys": 0,
        "band": ranks["band"],
    }
