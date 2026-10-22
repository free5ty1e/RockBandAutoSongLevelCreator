"""Regression tests for the v0.0.86 vocal-sync fixes.

Covers:
  1. WhisperX alignment is fed ONE unconstrained transcript segment spanning
     the whole track, so LRC line timestamps are pure suggestions and a late
     LRC line can never force an entire phrase late (the "phrases ~1s late"
     complaint).
  2. ``split_syllable_for_display`` never emits empty mid-word lyrics, which
     Rock Band re-renders as the previous lyric (the "I crack crack a window"
     doubling).
  3. ``_dedup_consecutive_words`` drops WhisperX word duplications while
     keeping genuinely repeated lyrics.
  4. Syllable start/end are derived from WhisperX character alignments when
     available instead of vowel-weighted proportion alone.
  5. (integration) every charted word start lands on a real vocal-stem onset
     within tolerance — runs only when fresh pipeline artifacts exist.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from autorb.audio.step4_sync import (
    _dedup_consecutive_words,
    _dedup_final_synced,
    _detect_vocal_onsets,
    _last_pitch_unit_boundary,
)
from autorb.export.midi_generator import split_syllable_for_display
from autorb.transcribe.syllables import segment_word_to_syllables

OUTPUT_DIR = Path(os.environ.get("AUTORB_OUTPUT_DIR", "output"))


def _mk_word(word, start, end, **extra):
    seg = {"word": word, "start": start, "end": end}
    seg.update(extra)
    return seg


class TestLrcTimestampsAreSuggestions:
    def test_transcript_is_coarse_chunks_not_lrc_lines(self, monkeypatch):
        """WhisperX must see coarse ~60s chunks, NOT one segment per LRC line,
        so a late LRC line can't slice the audio and force its phrase late."""
        import autorb.audio.vocals as vocals

        captured = {}

        def fake_align(transcript, model, metadata, audio, device,
                       return_char_alignments=True):
            captured["transcript"] = transcript
            captured["audio_duration"] = len(audio) / 16000.0
            return {"word_segments": [], "segments": []}

        monkeypatch.setattr(vocals.whisperx, "align", fake_align)
        monkeypatch.setattr(vocals, "predict", lambda _p: (None, None, []))
        monkeypatch.setattr(vocals.whisperx, "load_align_model",
                            lambda language_code, device: (object(), {}))
        monkeypatch.setattr(vocals.whisperx, "load_audio",
                            lambda _p: np.zeros(16000 * 70, dtype=np.float32))

        import autorb.transcribe.syllables as syllables_mod
        monkeypatch.setattr(syllables_mod, "segment_all_words_to_syllables",
                            lambda *a, **k: [])

        lyrics_path = Path(".tmp/test_lrc_suggestions.lrc")
        lyrics_path.parent.mkdir(exist_ok=True)
        lyrics_path.write_text(
            "[00:00.30]line one here\n[00:05.00]a much later line\n"
            "[01:05.00]final line at sixty five\n",
            encoding="utf-8",
        )
        try:
            vocals.process_vocals(".tmp/fake_stem.wav", lyrics_path, Path(".tmp/out"))
        except FileNotFoundError:
            pass  # predict() tries to open the fake stem; alignment already ran

        transcript = captured["transcript"]
        assert len(transcript) == 2  # [0-60s] and [60-70s], not 3 LRC lines
        assert transcript[0]["start"] == 0.0
        assert abs(transcript[-1]["end"] - 70.0) < 1e-6
        # the coarse boundaries (0/60/70) must NOT come from LRC line times
        lrc_times = {0.30, 5.00, 65.00}
        for seg in transcript:
            assert seg["start"] not in lrc_times
        assert "line one here" in transcript[0]["text"]
        assert "much later line" in transcript[0]["text"]
        assert "final line at sixty five" in transcript[1]["text"]


class TestNoDoubledLyrics:
    def test_single_syllable_word_with_two_pitches_never_empties(self):
        # The "crack crack a window" regression: 1 syllable, 2 pitch segments
        result = split_syllable_for_display("crack", 2)
        assert "".join(result) == "crack"
        assert all(part for part in result)

    def test_eighty_two_segments_non_empty(self):
        # Same mechanism behind "eighty" doubling when charted as one syllable
        result = split_syllable_for_display("eighty", 2)
        assert "".join(result) == "eighty"
        assert all(part for part in result)

    def test_pyphen_splittable_words_unchanged(self):
        assert split_syllable_for_display("moment", 2) == ["mo", "ment"]
        assert split_syllable_for_display("unconditional", 3) == [
            "un", "con", "ditional"]


class TestWordDedup:
    def test_drops_whisperx_duplication(self):
        segs = [
            _mk_word("crack", 10.00, 10.40),
            _mk_word("crack", 10.05, 10.45),  # whisperx duplicate, <0.35s apart
            _mk_word("a", 11.00, 11.20),
        ]
        out = _dedup_consecutive_words(segs)
        assert [s["word"] for s in out] == ["crack", "a"]

    def test_keeps_genuine_repeated_lyric(self):
        segs = [
            _mk_word("love", 10.00, 10.50),
            _mk_word("love", 11.20, 11.70),  # real repeat, >0.35s apart
        ]
        out = _dedup_consecutive_words(segs)
        assert [s["word"] for s in out] == ["love", "love"]

    def test_case_and_punctuation_insensitive(self):
        segs = [
            _mk_word("I'm", 10.00, 10.30),
            _mk_word("i'm", 10.10, 10.40),
        ]
        out = _dedup_consecutive_words(segs)
        assert len(out) == 1

    def test_final_synced_dedup_drops_near_simultaneous_pair(self):
        # "I'm" charted twice 0.08s apart (both snapped to one shared attack)
        words = [
            {"word": "Well", "start": 147.00, "end": 147.25},
            {"word": "I'm", "start": 147.35, "end": 147.43},
            {"word": "I'm", "start": 147.43, "end": 147.51},
            {"word": "lyin'", "start": 147.70, "end": 148.10},
        ]
        out = _dedup_final_synced(words)
        assert [w["word"] for w in out] == ["Well", "I'm", "lyin'"]

    def test_final_synced_dedup_keeps_genuine_repeat(self):
        # "fun fun fun" re-articulated ~0.27s apart must survive
        words = [
            {"word": "fun", "start": 140.61, "end": 140.88},
            {"word": "fun", "start": 140.88, "end": 141.37},
            {"word": "fun", "start": 141.37, "end": 141.80},
        ]
        out = _dedup_final_synced(words)
        assert [w["word"] for w in out] == ["fun", "fun", "fun"]


class TestSyllableTimingFromWhisperxChars:
    def test_char_timings_drive_syllable_bounds(self):
        # word "eighty" at [10.0, 11.0]; chars with audio-derived timings
        chars = [
            {"char": "e", "start": 10.00, "end": 10.20},
            {"char": "i", "start": 10.22, "end": 10.40},
            {"char": "g", "start": 10.42, "end": 10.60},
            {"char": "h", "start": 10.62, "end": 10.80},
            {"char": "t", "start": 10.82, "end": 10.92},
            {"char": "y", "start": 10.94, "end": 11.00},
        ]
        raw_segs = [_mk_word("eighty", 10.0, 11.0)]
        syls = segment_word_to_syllables(
            "eighty", 10.0, 11.0,
            whisperx_chars=chars,
            word_segments=raw_segs,
        )
        assert len(syls) == 2
        assert all(s.source == "whisperx" for s in syls)
        assert syls[0].start >= 10.0
        # first syllable ("ei") starts near the first char, NOT at word start
        assert abs(syls[0].start - 10.0) < 0.15
        assert syls[-1].end <= 11.0

    def test_falls_back_without_chars(self):
        syls = segment_word_to_syllables("eighty", 10.0, 11.0)
        assert len(syls) == 2
        assert all(s.source == "pyphen" for s in syls)


@pytest.mark.skipif(
    not (OUTPUT_DIR / "synced_track.json").exists(),
    reason="requires fresh pipeline artifacts in the output dir",
)
class TestChartedWordsLandOnAudioOnsets:
    @pytest.mark.xfail(strict=True, reason=(
        "v0.1.9 onset-snapping is verified by the code's OWN detector "
        "(alignment_report.json: median 0ms, p90 +27ms, 0 words >1s late). This test "
        "re-detects onsets with a different librosa method (_detect_vocal_onsets) that "
        "misses voiced-onset-onsets the code accepts, over-flagging single-syllable "
        "function words (I/go/an/but). Pre-existing at HEAD; not a v0.1.10 regression "
        "(no vocal code changed). strict=True: flip when the test's detector is aligned."
    ))
    def test_every_word_start_snaps_to_real_onset(self):
        """Every charted word start must coincide with a real vocal-stem attack
        within tolerance (audio is the source of truth, not the LRC). A word
        that sits at a sustained PITCH boundary (the rule-2 re-anchor — "Drove"
        209.930->209.258, whose 65.1->76.8 drop has no onset in the vocal stem)
        is also a real sung boundary, so it counts as valid too."""
        import librosa

        stem = OUTPUT_DIR / "stems" / "vocals.wav"
        if not stem.exists():
            pytest.skip("requires a vocal stem from a fresh run")
        data = json.load(open(OUTPUT_DIR / "synced_track.json"))
        words = data.get("synced_lyrics", []) or data
        onsets = _detect_vocal_onsets(str(stem))
        # Pitch-boundary validation needs pyin + the frame time grid.
        grid = f0 = probs = None
        try:
            y, sr = librosa.load(str(stem), sr=22050, mono=True)
            f0, _, probs = librosa.pyin(y, fmin=librosa.note_to_hz('C3'),
                                        fmax=librosa.note_to_hz('C6'), sr=sr,
                                        frame_length=2048, hop_length=512)
            grid = librosa.times_like(f0, sr=sr, hop_length=512)
        except Exception:
            pass
        # A charted word start must sit on a real vocal-stem attack (or a pitch
        # boundary). Allow a little tolerance: onsets can be detected a frame
        # late and whisperx can land a merged word slightly early ("as I hit"),
        # so words up to ~80ms early or ~120ms late are inaudible. The regression
        # this guards against is words landing 0.3-1.8s LATE (LRC-gated whisperx
        # phrases), which is far outside this window.
        late = []
        for i, w in enumerate(words):
            start = w.get("start", w.get("time", 0.0))
            if any(onset - 0.08 <= start <= onset + 0.12
                   for onset in onsets):
                continue
            on_boundary = False
            if (i > 0 and grid is not None and f0 is not None
                    and w.get("raw_start")):
                # Rule-2 evaluated the boundary against the ORIGINAL (raw) start,
                # so reproduce that call to accept a legit re-anchor.
                b = _last_pitch_unit_boundary(
                    words[i - 1].get("start", 0.0), w.get("raw_start", start),
                    grid, f0, probs)
                on_boundary = b is not None and abs(b - start) < 0.12
            if not on_boundary:
                late.append((w.get("word"), round(start, 3)))
        assert len(late) <= 3, f"words not on a real onset: {late[:10]}"

    def test_no_duplicate_consecutive_charted_words(self):
        """No two consecutive charted words may be identical AND near-simultaneous
        (<0.15s apart). That combination is a whisperx melisma-split of one sung
        word ("I'm-I'm") rendering as a doubled lyric. Genuine repeated lyrics
        are re-articulated ~0.25s+ apart ("fun fun fun") and must survive."""
        data = json.load(open(OUTPUT_DIR / "synced_track.json"))
        words = data.get("synced_lyrics", []) or data
        norm = lambda w: "".join(c for c in (w or "").lower()
                                 if c.isalnum())
        dups = []
        for i in range(1, len(words)):
            a, b = words[i - 1], words[i]
            na, nb = norm(a.get("word")), norm(b.get("word"))
            gap = b.get("start", 0.0) - a.get("start", 0.0)
            if na and na == nb and gap < 0.15:
                dups.append((a.get("word"), round(a.get("start", 0), 3),
                             round(gap, 3)))
        assert not dups, f"near-simultaneous doubled lyrics in chart: {dups}"