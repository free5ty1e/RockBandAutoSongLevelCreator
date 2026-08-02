#!/usr/bin/env python
"""Automatic per-instrument difficulty (rank) calculation for songs.dta.

Rock Band stores each instrument's difficulty as a ``(rank ...)`` value in
``songs.dta``.  The game maps a rank to the displayed difficulty dots via
per-instrument thresholds (rock-band-customs authoring-dtas table, min rank
per level): drums 133/169/208/294/349, guitar 145/194/247/301/354, bass
166/220/259/298/349, vocals 139/180/220/259/298, band 159/219/274/328/383
for levels 2-6 (level 1 = rank 1).  A linear formula (AutoRB's old
``rank = density * factor``) produced values like vocals 62 which all fall
inside the level-1 band, so every song still displayed "1 of 6".

This module instead maps chart note density (notes/sec, counting every
difficulty lane and drum-chord hit) to a difficulty level, calibrated so the
reference "311 - Down" DLC reproduces its actual levels (drum 311->5,
guitar 250->4, bass 225->3, vocals 144->2; counts verified with
``pretty_midi``: 5411/3382/1775/599 note-ons over 179s), then emits the
midpoint rank of that level's band.  ``band`` uses the hardest charted
instrument so a song with any real charting never shows "1 of 6".
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# (min_notes_per_sec, level) sorted highest-threshold-first.  The 311 anchor
# points are: drum 30.2 nps -> level 5, guitar 18.9 -> 4, bass 9.9 -> 3,
# vocals 3.35 -> 2.
_DENSITY_BANDS = {
    "drum": [(35, 6), (20, 5), (12, 4), (6, 3), (3, 2)],
    "guitar": [(30, 6), (20, 5), (13, 4), (8, 3), (4, 2)],
    "bass": [(30, 6), (20, 5), (13, 4), (6, 3), (3, 2)],
    "vocals": [(13, 6), (9, 5), (6, 4), (4, 3), (1.2, 2)],
}

# Midpoint rank of each difficulty level's band (index 0 = level 1).
_RANK_BAND_MID = {
    "drum": [1, 150, 188, 250, 321, 374],
    "guitar": [1, 169, 220, 273, 327, 377],
    "bass": [1, 192, 239, 278, 323, 374],
    "vocals": [1, 159, 199, 239, 278, 335],
    "band": [1, 188, 246, 300, 355, 400],
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


def _level_from_density(density: float, instrument: str) -> int:
    for threshold, level in _DENSITY_BANDS[instrument]:
        if density >= threshold:
            return level
    return 1


def compute_ranks(midi_path: str | Path, song_length_ms: int) -> dict:
    """Computes per-instrument (rank ...) values from chart note density.

    ``song_length_ms`` drives the density denominator; ``keys`` and the
    ``real_*`` pro guitar/bass/keys slots stay 0 (no chart data yet).
    """
    counts = count_notes_per_track(midi_path)
    duration_s = max(1.0, song_length_ms / 1000.0)

    levels = {}
    ranks = {}
    for instrument in _DENSITY_BANDS:
        track_name = next((k for k, v in TRACK_TO_INSTRUMENT.items() if v == instrument), "")
        note_count = counts.get(track_name, 0)
        density = note_count / duration_s
        level = _level_from_density(density, instrument)
        levels[instrument] = level
        ranks[instrument] = _RANK_BAND_MID[instrument][level - 1]

    band_level = max(levels.values())
    ranks["band"] = _RANK_BAND_MID["band"][band_level - 1]

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
