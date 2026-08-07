"""Tests for the vocal sync and pitch refinements in step4_sync.py.

Covers:
  1. ``_refine_word_timing`` snaps each word's start to the earliest real
     vocal-stem onset, never back into the previous word's sung region and
     never more than ONSET_MAX_SHIFT away.
  2. Per-word pitch selection uses librosa pyin as the primary source (window
     clipped to the next word's start, mode/median agreement gate), falls back
     to a Basic-Pitch note octave-snapped to the melodic contour, and finally
     to the contour itself.
"""

import numpy as np
import pytest

from autorb.audio.step4_sync import (
    ONSET_MAX_SHIFT,
    ONSET_SNAP_EARLY_MIN,
    VOCAL_MIDI_MAX,
    VOCAL_MIDI_MIN,
    _build_melodic_contour,
    _compute_word_pyin_pitches,
    _octave_snap,
    _refine_word_timing,
    _resolve_pitches,
    sync_lyrics_to_beats,
)

NOTES = [
    [1.00, 1.60, 60],  # sustained sung note
    [1.10, 1.35, 62],  # short harmonic riding on it
    [2.00, 2.80, 64],
]


def _frames(freqs, sr=22050, step=0.01, prob=0.8):
    """Build synthetic pyin arrays covering the given (start,end,freq_midi) runs.

    Returns (times, f0, voiced, probs) with one frame every ``step`` seconds,
    NaN f0 for unvoiced gaps.
    """
    runs = sorted(freqs, key=lambda r: r[0])
    end_max = max(r[1] for r in runs) + 0.1
    n = int(end_max / step) + 1
    times = np.arange(n) * step
    f0 = np.full(n, np.nan)
    voiced = np.zeros(n, dtype=bool)
    probs = np.zeros(n)
    for start, end, midi in runs:
        i0 = int(start / step)
        i1 = int(end / step)
        hz = 440.0 * 2 ** ((midi - 69.0) / 12.0)
        f0[i0:i1] = hz
        voiced[i0:i1] = True
        probs[i0:i1] = prob
    return times, f0, voiced, probs


# ---------------------------------------------------------------------------
# Timing / onset snap (unchanged behaviour)
# ---------------------------------------------------------------------------

def test_snap_start_to_nearest_onset():
    """A WhisperX start just after the real onset snaps back to it."""
    seg = {"start": 1.02, "end": 1.70, "word": "w"}
    start, end = _refine_word_timing(seg, NOTES, float("-inf"))
    assert start == 1.00, f"expected snap to onset 1.00, got {start}"
    assert end >= 1.60, "end should extend across the sustained note"


def test_vocal_onsets_snap_to_earliest_attack():
    """With real vocal-stem onsets, snap to the EARLIEST attack in the window."""
    seg = {"start": 1.08, "end": 1.70, "word": "w"}  # WhisperX ~100ms late
    onsets = [0.50, 1.00, 1.30]                       # true attack = 1.00
    start, end = _refine_word_timing(seg, [[1.03, 1.60, 60]], float("-inf"), onsets)
    assert start == 1.00, f"expected snap to true attack 1.00, got {start}"
    assert end >= 1.60, "end should still extend across the sustained note"


def test_vocal_onsets_first_word_very_late():
    """The v0.0070 regression: a first word 350ms late snaps to the true attack."""
    seg = {"start": 1.60, "end": 1.90, "word": "w"}
    onsets = [0.40, 0.90, 1.35]  # true attack at 1.35
    start, _ = _refine_word_timing(seg, [[1.50, 1.90, 60]], float("-inf"), onsets)
    assert start == 1.35, f"expected snap to earliest attack 1.35, got {start}"


def test_vocal_onsets_not_snapped_when_accurate():
    """An on-time WhisperX start is left alone."""
    seg = {"start": 1.02, "end": 1.60, "word": "w"}
    onsets = [0.50, 1.00]
    start, _ = _refine_word_timing(seg, NOTES, float("-inf"), onsets)
    assert start == 1.02, f"accurate start must not move, got {start}"
    assert ONSET_SNAP_EARLY_MIN < 0.10


def test_vocal_onsets_respect_prev_word():
    """An onset inside the previous word's sung region is rejected."""
    seg = {"start": 1.60, "end": 1.90, "word": "w"}  # WhisperX late
    prev_sung_end = 1.50
    onsets = [1.10, 1.35, 1.55]  # 1.10/1.35 belong to prev word
    start, _ = _refine_word_timing(seg, NOTES, prev_sung_end, onsets)
    assert start == 1.55, f"must snap only to onset after prev word, got {start}"


def test_vocal_onsets_empty_falls_back_to_bp():
    seg = {"start": 1.02, "end": 1.70, "word": "w"}
    start, _ = _refine_word_timing(seg, NOTES, float("-inf"), [])
    assert start == 1.00, f"fallback snap to BP onset 1.00, got {start}"


def test_no_snap_into_previous_word():
    seg = {"start": 1.55, "end": 1.85, "word": "w"}
    prev_sung_end = 1.60
    start, _ = _refine_word_timing(seg, NOTES, prev_sung_end)
    assert start == 1.55, f"must not snap into prev word, got {start}"


def test_no_snap_beyond_max_shift():
    seg = {"start": 3.00, "end": 3.40, "word": "w"}
    start, _ = _refine_word_timing(seg, [[2.40, 3.00, 60]], float("-inf"))
    assert start == 3.00, f"onset 0.6s away must not fire, got {start}"
    assert ONSET_MAX_SHIFT < 0.6


def test_end_extends_over_internal_notes():
    seg = {"start": 2.05, "end": 2.35, "word": "w"}
    start, end = _refine_word_timing(seg, NOTES, float("-inf"))
    assert start == 2.00
    assert end == 2.80, f"expected end extended to 2.80, got {end}"


# ---------------------------------------------------------------------------
# Per-word pyin pitch selection
# ---------------------------------------------------------------------------

def test_word_pyin_trusts_agreeing_reading():
    """Frames all at one pitch: median == rounded mode -> trusted."""
    times, f0, voiced, probs = _frames([(0.20, 0.50, 69.0)])
    res = _compute_word_pyin_pitches(times, f0, voiced, probs,
                                     np.array([0.2]), np.array([0.5]))
    med, ok = res[0]
    assert ok is True
    assert med == pytest.approx(69.0, abs=0.5)


def test_word_pyin_rejects_split_reading():
    """Half the frames at one octave, half at the other -> not trusted."""
    times, f0, voiced, probs = _frames([
        (0.10, 0.25, 57.0),  # low
        (0.25, 0.40, 69.0),  # high
    ])
    res = _compute_word_pyin_pitches(times, f0, voiced, probs,
                                     np.array([0.1]), np.array([0.4]))
    med, ok = res[0]
    assert ok is False, f"split reading must be rejected, got {med}"


def test_word_pyin_window_clipped_to_next_word():
    """The first word's window must not include the second word's pitch frames."""
    times, f0, voiced, probs = _frames([
        (0.10, 0.30, 57.0),  # word 1
        (0.35, 0.60, 69.0),  # word 2 (starts just after 0.30)
    ])
    starts = np.array([0.1, 0.35])
    ends = np.array([0.30, 0.60])  # word1 end would reach 0.60 if unclipped
    res = _compute_word_pyin_pitches(times, f0, voiced, probs, starts, ends)
    med1, ok1 = res[0]
    med2, ok2 = res[1]
    assert ok1 and med1 == pytest.approx(57.0, abs=0.5), (
        f"word1 must read 57, got {med1} (window leaked into word2)"
    )
    assert ok2 and med2 == pytest.approx(69.0, abs=0.5)


def test_melodic_contour_interpolates():
    """Contour linearly interpolates between trusted word pitches."""
    starts = np.array([0.0, 1.0, 2.0], dtype=float)
    pyin_results = [(60.0, True), (None, False), (67.0, True)]
    contour = _build_melodic_contour(starts, pyin_results)
    assert contour is not None
    assert contour(0.0) == pytest.approx(60.0)
    assert contour(2.0) == pytest.approx(67.0)
    assert contour(1.0) == pytest.approx(63.5, abs=0.01)
    # constant extrapolation
    assert contour(-1.0) == pytest.approx(60.0)
    assert contour(3.0) == pytest.approx(67.0)


def test_octave_snap_chooses_near_contour():
    assert _octave_snap(60, 72) == 72
    assert _octave_snap(60, 55) == 60
    assert _octave_snap(60, 69) in (60, 72)


def test_resolve_pitches_prioritizes_pyin_over_bad_bp():
    """pyin wins even when BP has the wrong octave."""
    times, f0, voiced, probs = _frames([
        (0.10, 0.50, 69.0),  # word1 truly 69
        (0.60, 0.90, 57.0),  # word2 truly 57
    ])
    starts = np.array([0.1, 0.6])
    ends = np.array([0.5, 0.9])
    note_events = [[0.10, 0.50, 57], [0.60, 0.90, 69]]  # BP octaves reversed
    out = _resolve_pitches(starts, ends, note_events, times, f0, voiced, probs)
    assert out == [69, 57], f"pyin must override bad BP, got {out}"


def test_resolve_pitches_bp_follows_contour():
    """Untrusted words use a BP note snapped near the melodic contour."""
    times, f0, voiced, probs = _frames([
        (0.00, 0.30, 60.0),  # word0 trusted (contour anchor)
        (0.60, 0.90, 66.0),  # word2 trusted (contour anchor)
    ])
    starts = np.array([0.0, 0.3, 0.6])
    ends = np.array([0.30, 0.60, 0.90])
    # word1 (start 0.3) has NO voiced frames -> untrusted.
    # BP reports it one octave up (72); contour at 0.3 is 63, so the nearest
    # in-range octave copy of 72 is 60, which is within CONTOUR_SNAP_ST (3) of
    # the contour -> the snapped BP note wins over the raw contour.
    note_events = [[0.30, 0.55, 72]]
    out = _resolve_pitches(starts, ends, note_events, times, f0, voiced, probs)
    assert out[0] == 60
    assert out[2] == 66
    assert out[1] == 60, f"snapped BP note should win, got {out[1]}"


def test_resolve_pitches_contour_extrapolates_ends():
    """Leading/trailing untrusted words use constant contour extrapolation."""
    times, f0, voiced, probs = _frames([(0.50, 0.70, 60.0)])
    starts = np.array([0.1, 0.5, 0.9])
    ends = np.array([0.30, 0.70, 1.00])
    note_events = []
    out = _resolve_pitches(starts, ends, note_events, times, f0, voiced, probs)
    # only middle word is trusted; single anchor -> no contour -> default 60
    assert out[1] == 60
    assert out[0] == 60 and out[2] == 60


# ---------------------------------------------------------------------------
# sync_lyrics_to_beats integration (no vocals stem -> BP max-overlap fallback)
# ---------------------------------------------------------------------------

def test_pitch_is_max_overlap_note():
    """Without a vocal stem, BP max-overlap note is used."""
    beats = [1.0, 2.0, 3.0]
    lyrics = {"word_segments": [{"start": 1.05, "end": 1.65, "word": "w"}],
              "note_events": NOTES, "beat_times": beats}
    out = sync_lyrics_to_beats({"beat_times": beats}, lyrics)["synced_lyrics"][0]
    assert out["pitch"] == 60, f"max-overlap note is 60, got {out['pitch']}"


def test_pitch_clamped_to_vocal_range():
    """Every resolved pitch stays within the C3..C6 vocal range."""
    beats = [1.0, 2.0, 3.0]
    for event_pitch in (100, 30, 200, 0):
        lyrics = {"word_segments": [{"start": 1.05, "end": 1.65, "word": "w"}],
                  "note_events": [[1.00, 1.60, event_pitch]], "beat_times": beats}
        out = sync_lyrics_to_beats({"beat_times": beats}, lyrics)["synced_lyrics"][0]
        assert VOCAL_MIDI_MIN <= out["pitch"] <= VOCAL_MIDI_MAX, (
            f"pitch from BP note {event_pitch} escaped range: {out['pitch']}"
        )


def test_pitch_resolution_uses_vocal_stem(tmp_path):
    """End-to-end: a sine-wave vocal stem drives pyin; BP octave errors are
    overridden by the trusted pyin reading."""
    import librosa
    import wave
    import struct

    # Build a 1s, 22050 Hz WAV with two sine segments (440Hz then 220Hz).
    sr = 22050
    n = sr
    samples = np.zeros(n, dtype=np.int16)
    for start, end, hz in ((0.0, 0.5, 440.0), (0.55, 1.0, 220.0)):
        i0, i1 = int(start * sr), int(end * sr)
        t = np.arange(i1 - i0) / sr
        samples[i0:i1] = (0.5 * np.sin(2 * np.pi * hz * t) * 32767).astype(np.int16)

    wav = tmp_path / "vocals.wav"
    with wave.open(str(wav), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.tobytes())

    beats = [0.0, 0.5, 1.0, 1.5]
    lyrics = {
        "word_segments": [
            {"start": 0.05, "end": 0.50, "word": "a"},
            {"start": 0.55, "end": 1.00, "word": "b"},
        ],
        # BP reports both an octave too high (should be overridden by pyin)
        "note_events": [[0.05, 0.50, 81], [0.55, 1.00, 69]],
        "beat_times": beats,
    }
    out = sync_lyrics_to_beats({"beat_times": beats}, lyrics,
                               vocals_stem=str(wav))["synced_lyrics"]
    # 440Hz -> MIDI 69; 220Hz -> MIDI 57
    assert out[0]["pitch"] == 69, f"expected pyin 69, got {out[0]['pitch']}"
    assert out[1]["pitch"] == 57, f"expected pyin 57, got {out[1]['pitch']}"
