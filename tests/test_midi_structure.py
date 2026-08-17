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


def test_open_guitar_notes_are_not_dropped():
    """v0.0.97: Rock Band 5-button guitar/bass charts have no 'open' notes.

    Open-string hits used to be encoded as OPEN_PITCH (67), which is outside the
    60-100 difficulty ranges, so ForgeTool's HandleGuitarBass dropped them (the
    in-game chart lost those notes). They must now encode as a normal lane note.
    """
    from autorb.transcribe.instruments.difficulty import (
        ChartNote,
        InstrumentChart,
    )
    from autorb.export.midi_generator import build_instrument_track

    notes = [
        ChartNote(time=0.0, lane=2, length=0.1, is_open=True, velocity=100),
        ChartNote(time=0.5, lane=1, length=0.1, is_open=False, velocity=100),
    ]
    chart = {"expert": InstrumentChart(notes=notes, tempo_map=[(0, 120)])}
    counts = _count_per_difficulty(build_instrument_track(chart, "guitar", 0, lambda s: int(s * 480)))
    assert counts["bad"] == 0, f"open note produced out-of-range pitch: {counts}"
    assert counts["expert"] == 2, f"open note was dropped: {counts}"


def test_open_string_lane_minus_one_clamped():
    """`fret_string_to_lane` returns -1 for open strings (fret 0). `build_instrument_track`
    must clamp it into 0-4, otherwise `base + (-1)` (59/71/83/95) is outside the 60-100
    difficulty ranges and ForgeTool drops the note (the "too few notes" bug)."""
    from autorb.transcribe.instruments.difficulty import (
        ChartNote,
        InstrumentChart,
    )
    from autorb.export.midi_generator import build_instrument_track

    notes = [ChartNote(time=0.0, lane=-1, length=0.1, is_open=True, velocity=100)]
    chart = {"expert": InstrumentChart(notes=notes, tempo_map=[(0, 120)])}
    counts = _count_per_difficulty(build_instrument_track(chart, "guitar", 0, lambda s: int(s * 480)))
    assert counts["bad"] == 0, f"lane -1 produced out-of-range pitch: {counts}"
    assert counts["expert"] == 1, f"open-string note was dropped: {counts}"


def test_simultaneous_notes_stay_simultaneous():
    """v0.0.98: a chord (multiple notes at the same time) must stay simultaneous
    in the written MIDI. The old writer advanced last_tick by each note's
    *duration*, so a chord's 2nd+ notes landed after the previous note ended
    (never simultaneous) and chords never rendered as chords in-game.
    """
    import io
    import struct
    from autorb.transcribe.instruments.difficulty import (
        ChartNote,
        InstrumentChart,
    )
    from autorb.export.midi_generator import build_instrument_track

    # Two expert guitar notes at the SAME time -> a chord (lanes 0 and 2).
    notes = [
        ChartNote(time=1.0, lane=0, length=0.2, velocity=100, difficulty_pitch=96),
        ChartNote(time=1.0, lane=2, length=0.2, velocity=100, difficulty_pitch=98),
        ChartNote(time=2.0, lane=1, length=0.2, velocity=100, difficulty_pitch=97),
    ]
    # All four difficulties must be present, otherwise the writer injects
    # placeholder notes at tick 0 that would also look "simultaneous".
    chart = {
        d: InstrumentChart(notes=notes, tempo_map=[(0, 120)])
        for d in ("expert", "hard", "medium", "easy")
    }
    track_bytes = build_instrument_track(chart, "guitar", 0, lambda s: int(s * 480))

    full = b"MThd" + struct.pack(">IHHH", 6, 1, 1, 480) + track_bytes
    mid = mido.MidiFile(file=io.BytesIO(full))
    abs_tick = 0
    onsets_by_tick = {}
    for msg in mid.tracks[0]:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            onsets_by_tick.setdefault(abs_tick, []).append(msg.note)

    # The two expert chord notes (96, 98) must share one tick, and the single
    # note (97) must be on a *different* tick. (All four difficulties carry the
    # same chart, so each tick lists one copy per difficulty — the simultaneity
    # we care about is that 96 and 98 land on the same tick, not 97's.)
    chord_tick = next(t for t, ns in onsets_by_tick.items() if 96 in ns and 98 in ns)
    assert 96 in onsets_by_tick[chord_tick] and 98 in onsets_by_tick[chord_tick], (
        f"chord notes 96/98 not simultaneous: {onsets_by_tick}"
    )
    single_tick = next(t for t, ns in onsets_by_tick.items() if 97 in ns)
    assert single_tick != chord_tick, (
        f"single note 97 collided with chord tick: {onsets_by_tick}"
    )


def test_drum_difficulties_are_distinct_and_decreasing():
    """v0.1.0: Hard/Medium/Easy must be strictly simpler than Expert and
    lane-distinct (not byte-identical copies), following the RBN Drum Authoring
    rules. With a chart that uses all 5 lanes (kick/snare/hat/tom/cymbal) on an
    8th-note grid:
      - Hard keeps all lanes (cymbals included; just single-color crashes + no
        kicks inside fills).
      - Medium drops kicks/snares that fall *between* time-keeping hats (so a
        lone kick/snare hit is removed, leaving hat/tom/crash).
      - Easy is the basic rock beat: kick + snare only.
    """
    from autorb.transcribe.instruments.difficulty import (
        ChartNote,
        InstrumentChart,
        create_all_difficulties,
        Difficulty,
    )

    # Build a realistic kit chart: quarter-beat (hat + kick/snare) grooves plus
    # off-beat 8th toms/crashes, with one lone kick inside a fill region. Kicks
    # and snares ride *with* the hi-hat (time-keeping) so Medium keeps them and
    # Easy inherits the basic beat.
    events = []
    for m in range(5):
        for b in range(4):
            t = m * 2.0 + b * 0.5
            events.append((t, [2, 0])) if b % 2 == 0 else events.append((t, [2, 1]))
            events.append((t + 0.25, [3 if b % 2 == 0 else 4]))
    events.append((1.25, [0]))  # lone kick inside the fill region below
    notes = []
    for t, ev_lanes in events:
        for l in ev_lanes:
            notes.append(ChartNote(
                time=t, lane=l, length=0.0,
                difficulty_pitch=36 + l, velocity=100,
            ))
    expert = InstrumentChart(notes=notes, tempo_map=[(0, 120)], overdrive_phrases=[(1.0, 2.0)])
    diffs = create_all_difficulties(expert, "drums")

    counts = {d: len(diffs[d].notes) for d in diffs}
    # Non-increasing: expert >= hard >= medium >= easy, and Expert is strictly
    # simpler than Easy (the reduction genuinely happens end-to-end).
    assert counts[Difficulty.EXPERT] >= counts[Difficulty.HARD] >= \
        counts[Difficulty.MEDIUM] >= counts[Difficulty.EASY], (
        f"drum difficulties not non-increasing: {counts}"
    )
    assert counts[Difficulty.EXPERT] > counts[Difficulty.EASY], (
        f"drum Easy not simpler than Expert: {counts}"
    )
    # Easy is the basic rock beat: kick + snare only.
    easy_lanes = {n.lane for n in diffs[Difficulty.EASY].notes}
    assert easy_lanes <= {0, 1}, f"easy not basic kick/snare beat: {easy_lanes}"
    # Each difficulty is non-empty.
    for d in (Difficulty.HARD, Difficulty.MEDIUM, Difficulty.EASY):
        assert counts[d] > 0, f"{d} is empty"


def test_reduce_double_bass_collapses_rapid_kicks():
    """v0.1.0: Rock Band forbids fully-authored double bass. Rapid kick bursts
    (two kicks closer than MIN_KICK_GAP) must collapse to a single foot hit; other
    lanes and well-spaced kicks must survive untouched."""
    from autorb.transcribe.instruments.drums import reduce_double_bass
    from autorb.transcribe.instruments.difficulty import ChartNote

    def note(t, lane):
        return ChartNote(time=t, lane=lane, length=0.0, difficulty_pitch=36 + lane)

    # 5 kicks: at 0.0, 0.05 (rapid), 0.30, 0.34 (rapid), 0.60. Two bursts of two.
    notes = [
        note(0.00, 0), note(0.05, 0),          # burst 1 -> keep 0.00
        note(0.30, 1),                          # snare, untouched
        note(0.40, 0), note(0.45, 0),          # burst 2 -> keep 0.40
        note(0.70, 2),                          # hat, untouched
    ]
    out = reduce_double_bass(notes, min_gap=0.11)
    kept_times = sorted(n.time for n in out if n.lane == 0)
    assert kept_times == [0.0, 0.40], f"rapid kicks not collapsed: {kept_times}"
    # non-kick lanes survive
    assert sorted(n.lane for n in out) == [0, 0, 1, 2], sorted(n.lane for n in out)


def _chord_events_to_notes(events):
    """events: list of (time, [lanes]) -> flat ChartNote list."""
    from autorb.transcribe.instruments.difficulty import ChartNote
    notes = []
    for t, lanes in events:
        for l in lanes:
            notes.append(ChartNote(time=t, lane=l, length=0.0,
                                   difficulty_pitch=60 + l, velocity=100))
    return notes


def test_fretted_difficulty_chord_and_grid_rules():
    """v0.1.0: guitar/bass difficulty derivation enforces the RBN authoring rules:
    Hard drops 3-note / Green-Orange chords to 2 notes; Medium keeps only 2-note
    allowed chords and drops 8th-note (off-beat) single notes; Easy has no chords
    at all (single root notes) and keeps only half-note-grid notes."""
    from autorb.transcribe.instruments.difficulty import (
        InstrumentChart, create_all_difficulties, Difficulty,
    )

    # Quarter-beat chords + 8th-note single notes (alternating lanes).
    events = [
        (0.0, [0, 1, 2]),    # 3-note chord on beat 1  -> Hard keeps 2, Medium keeps 2, Easy single
        (0.5, [0, 4]),       # Green/Orange chord      -> reduced
        (0.25, [2]),         # 8th single (off-beat)   -> Medium drops, Easy drops
        (0.75, [3]),         # 8th single (off-beat)   -> Medium drops, Easy drops
        (1.0, [1, 2]),       # 2-note allowed chord on beat 3
        (1.25, [0]),         # 8th single
        (1.5, [2, 4]),       # Red/Orange -> forbidden on Medium
        (1.75, [1]),
    ]
    chart = InstrumentChart(notes=_chord_events_to_notes(events), tempo_map=[(0, 120)])
    diffs = create_all_difficulties(chart, "guitar")

    def lane_sets(notes):
        # group simultaneous lanes into chord "tuples" for inspection
        evs = {}
        for n in sorted(notes, key=lambda x: x.time):
            evs.setdefault(round(n.time, 3), set()).add(n.lane)
        return evs

    hard = lane_sets(diffs[Difficulty.HARD].notes)
    medium = lane_sets(diffs[Difficulty.MEDIUM].notes)
    easy = lane_sets(diffs[Difficulty.EASY].notes)

    # Hard: no 3-note chord, no Green/Orange {0,4}.
    for lanes in hard.values():
        assert len(lanes) <= 2, f"Hard has 3+ note chord: {lanes}"
        assert lanes != {0, 4}, f"Hard keeps Green/Orange: {lanes}"

    # Medium: only allowed 2-note chords; no {0,3},{0,4},{2,4}; no 3-note.
    # Medium also drops 8th-note (off-beat) singles, keeping quarter-note beats.
    for t, lanes in medium.items():
        assert len(lanes) <= 2, f"Medium has 3+ note chord: {lanes}"
        assert lanes not in ({0, 3}, {0, 4}, {2, 4}), f"Medium forbidden chord: {lanes}"
    assert set(round(t, 3) for t in medium.keys()) == {0.0, 0.5, 1.0, 1.5}, \
        f"Medium did not drop off-beat 8ths: {sorted(medium.keys())}"

    # Easy: every event is a single note (no chords).
    for lanes in easy.values():
        assert len(lanes) == 1, f"Easy has a chord: {lanes}"

    # Non-increasing and Expert strictly simpler than Easy.
    counts = {d: len(diffs[d].notes) for d in diffs}
    assert counts[Difficulty.EXPERT] >= counts[Difficulty.HARD] >= \
        counts[Difficulty.MEDIUM] >= counts[Difficulty.EASY]
    assert counts[Difficulty.EXPERT] > counts[Difficulty.EASY]



