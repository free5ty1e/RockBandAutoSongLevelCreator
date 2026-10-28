"""Tests for the GP-collection audit tool (v0.1.38).

The audit tool parses Guitar Pro files with `guitarpro` (pip: pyguitarpro) —
a DEVCONTAINER-ONLY research dependency, deliberately NOT in
requirements.txt (the pipeline itself never imports it; pyguitarpro is
GPL-licensed and AutoRB keeps it out of the shipped dependency set). Tests
skip where it is absent (the adtof/spleeter optional pattern).

The fixtures are SYNTHETIC Song objects injected via monkeypatched
`gp.parse` — no copyrighted tab ever enters the repo or a test artifact,
and the tests exercise exactly what the audit tool OWNS: the track -> family
classification and the full-band/keys/lyrics detection. (The pyguitarpro GP5
writer does not round-trip ad-hoc MidiChannel edits faithfully, so we do not
go through a file; real-file parsing was verified live on the collection.)
"""

import sys
from pathlib import Path

import pytest

guitarpro = pytest.importorskip("guitarpro", reason="pyguitarpro not installed (devcontainer research dep)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "guitar_tab_alignment"))
import audit_gp_collection  # noqa: E402
from audit_gp_collection import parse_one  # noqa: E402

from guitarpro.models import (  # noqa: E402
    GuitarString, Lyrics, Measure, MeasureHeader, MidiChannel, Track, TimeSignature, Voice,
)


def _synth_song(tracks: list[tuple[str, int, bool]], *, with_lyrics: bool = False) -> guitarpro.Song:
    """Build a minimal synthetic Song with the requested tracks.

    tracks: (name, midi instrument, is_percussion)
    """
    song = guitarpro.Song(title="Synthetic Fixture", artist="AutoRB Tests")
    if with_lyrics:
        song.lyrics = Lyrics(lines=[guitarpro.models.LyricLine(startingMeasure=1, lyrics="la la la")])
    song.measureHeaders.clear()  # the attrs default factory pre-populates one
    song.measureHeaders.append(MeasureHeader(number=1, timeSignature=TimeSignature()))
    for name, inst, perc in tracks:
        t = Track(song=song, isPercussionTrack=perc, name=name,
                  channel=MidiChannel(channel=9 if perc else 0, instrument=inst))
        t.strings = [GuitarString(number=i + 1, value=v)
                     for i, v in enumerate([0] * (6 if perc else 4))]
        m = Measure(track=t, header=song.measureHeaders[0], voices=[Voice(measure=None, beats=[])])
        t.measures.append(m)
        song.tracks.append(t)
    return song


def _record(monkeypatch, tracks, with_lyrics=False):
    song = _synth_song(tracks, with_lyrics=with_lyrics)
    monkeypatch.setattr(audit_gp_collection.gp, "parse", lambda p: song)
    return parse_one(Path("does-not-need-to-exist.gp5"))


def test_full_band_detection(monkeypatch):
    r = _record(monkeypatch, [("Gtr", 29, False), ("Bass", 33, False), ("Drums", 0, True)])
    assert r["full_band"] is True
    assert r["full_band_keys"] is False
    assert r["families"] == ["bass", "drums", "guitar"]
    assert r["title"] == "Synthetic Fixture"
    assert r["measures"] == 1
    assert r["has_lyrics"] is False


def test_guitar_only_is_not_full_band(monkeypatch):
    r = _record(monkeypatch, [("Solo gtr", 27, False)])
    assert r["has_guitar"] is True
    assert r["full_band"] is False


def test_keys_detection(monkeypatch):
    r = _record(monkeypatch, [("Piano", 0, False), ("Gtr", 29, False),
                              ("Bass", 33, False), ("Drums", 0, True)])
    assert r["full_band_keys"] is True
    assert "keys" in r["families"]


def test_strings_horns_family(monkeypatch):
    r = _record(monkeypatch, [("Sax", 65, False), ("Gtr", 29, False),
                              ("Bass", 33, False), ("Drums", 0, True)])
    # a sax track is strings_horns, not keys — still full band but not +keys
    assert r["full_band"] is True
    assert r["full_band_keys"] is False
    assert "strings_horns" in r["families"]


def test_lyrics_flag(monkeypatch):
    r = _record(monkeypatch, [("Gtr", 29, False)], with_lyrics=True)
    assert r["has_lyrics"] is True


def test_note_counting(monkeypatch):
    """Note counts come from beats, so a synthetic empty measure parses to 0."""
    r = _record(monkeypatch, [("Gtr", 29, False)])
    assert all(tr["notes"] == 0 for tr in r["tracks"])
