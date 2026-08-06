"""Tests for the vocal sync refinements in step4_sync.py.

Covers the two behavioural changes introduced for the v0.0068 sync/pitch fix:
  1. ``_refine_word_timing`` snaps each word's start to the nearest real
     Basic-Pitch onset, but never back into the previous word's sung region and
     never more than ONSET_MAX_SHIFT seconds away.
  2. ``sync_lyrics_to_beats`` picks the pitch of the note with the largest
     overlap over the word window (max-overlap, not nearest), and the pyin
     octave guard only overrides when pyin is both confident (>= 0.8) and far
     from the Basic-Pitch reading (> PYIN_CORRECT_ST).
"""

from autorb.audio.step4_sync import (
    ONSET_MAX_SHIFT,
    PYIN_CORRECT_ST,
    VOCAL_MIDI_MAX,
    VOCAL_MIDI_MIN,
    _refine_word_timing,
    sync_lyrics_to_beats,
)

NOTES = [
    [1.00, 1.60, 60],  # sustained sung note
    [1.10, 1.35, 62],  # short harmonic riding on it
    [2.00, 2.80, 64],
]


def test_snap_start_to_nearest_onset():
    """A WhisperX start just after the real onset snaps back to it (the nearest
    onset within the search window wins)."""
    seg = {"start": 1.02, "end": 1.70, "word": "w"}
    start, end = _refine_word_timing(seg, NOTES, float("-inf"))
    assert start == 1.00, f"expected snap to onset 1.00, got {start}"
    assert end >= 1.60, "end should extend across the sustained note"


def test_no_snap_into_previous_word():
    """A candidate onset inside the previous word's sung region is rejected."""
    seg = {"start": 1.55, "end": 1.85, "word": "w"}  # WhisperX late
    prev_sung_end = 1.60  # previous word sung through the next onset
    start, _ = _refine_word_timing(seg, NOTES, prev_sung_end)
    assert start == 1.55, f"must not snap into prev word, got {start}"


def test_no_snap_beyond_max_shift():
    """Onsets farther than ONSET_MAX_SHIFT away are ignored; start is kept."""
    seg = {"start": 3.00, "end": 3.40, "word": "w"}
    start, _ = _refine_word_timing(seg, [[2.40, 3.00, 60]], float("-inf"))
    assert start == 3.00, f"onset 0.6s away must not fire, got {start}"
    assert ONSET_MAX_SHIFT < 0.6


def test_end_extends_over_internal_notes():
    """Multi-syllable words produce several notes inside the word's span; the
    end must cover them all, but notes after the word's WhisperX end are left
    to the next word."""
    seg = {"start": 2.05, "end": 2.35, "word": "w"}
    start, end = _refine_word_timing(seg, NOTES, float("-inf"))
    assert start == 2.00
    assert end == 2.80, f"expected end extended to 2.80, got {end}"


def test_pitch_is_max_overlap_note():
    """A short neighbour note near the window centre must lose to the longer
    sustained note underneath it."""
    beats = [1.0, 2.0, 3.0]
    lyrics = {"word_segments": [{"start": 1.05, "end": 1.65, "word": "w"}],
              "note_events": NOTES, "beat_times": beats}
    out = sync_lyrics_to_beats({"beat_times": beats}, lyrics)["synced_lyrics"][0]
    assert out["pitch"] == 60, f"max-overlap note is 60, got {out['pitch']}"


def test_pyin_guard_requires_high_confidence():
    """A mid-confidence pyin reading must NOT override Basic-Pitch."""
    beats = [1.0, 2.0, 3.0]
    lyrics = {"word_segments": [{"start": 1.05, "end": 1.65, "word": "w",
                                 "pyin_pitch": 50.0, "pyin_confidence": 0.6}],
              "note_events": [[1.00, 1.60, 60]], "beat_times": beats}
    out = sync_lyrics_to_beats({"beat_times": beats}, lyrics)["synced_lyrics"][0]
    assert out["pitch"] == 60, "pyin below 0.8 confidence must be ignored"


def test_pyin_guard_requires_large_disagreement():
    """A confident pyin reading close to Basic-Pitch is left alone."""
    beats = [1.0, 2.0, 3.0]
    lyrics = {"word_segments": [{"start": 1.05, "end": 1.65, "word": "w",
                                 "pyin_pitch": 61.0, "pyin_confidence": 0.9}],
              "note_events": [[1.00, 1.60, 60]], "beat_times": beats}
    out = sync_lyrics_to_beats({"beat_times": beats}, lyrics)["synced_lyrics"][0]
    assert out["pitch"] == 60, f"1 st disagreement must not override (got {out['pitch']})"


def test_pyin_guard_corrects_octave_error():
    """A confident, far-off pyin reading overrides a Basic-Pitch octave error."""
    beats = [1.0, 2.0, 3.0]
    lyrics = {"word_segments": [{"start": 1.05, "end": 1.65, "word": "w",
                                 "pyin_pitch": 72.0, "pyin_confidence": 0.95}],
              "note_events": [[1.00, 1.60, 60]], "beat_times": beats}
    out = sync_lyrics_to_beats({"beat_times": beats}, lyrics)["synced_lyrics"][0]
    assert out["pitch"] == 72, f"pyin octave fix must apply, got {out['pitch']}"
    assert 4.0 <= PYIN_CORRECT_ST < 12


def test_pitch_clamped_to_vocal_range():
    """Extreme notes are clamped to the C2..C6 vocal range."""
    beats = [1.0, 2.0, 3.0]
    for event_pitch, expected in ((100, VOCAL_MIDI_MAX), (30, VOCAL_MIDI_MIN)):
        lyrics = {"word_segments": [{"start": 1.05, "end": 1.65, "word": "w"}],
                  "note_events": [[1.00, 1.60, event_pitch]], "beat_times": beats}
        out = sync_lyrics_to_beats({"beat_times": beats}, lyrics)["synced_lyrics"][0]
        assert out["pitch"] == expected, (
            f"pitch {event_pitch} must clamp to {expected}, got {out['pitch']}"
        )
