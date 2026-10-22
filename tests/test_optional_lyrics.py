"""Optional-LRC plumbing tests (v0.1.23): the web UI's "optional lyrics".

Two code paths through process_vocals:
  * LRC supplied: force-align its text (unchanged behavior)
  * NO LRC: WhisperX *transcribes* the vocal stem, and those segments
    become the lyric lines (each = one {time, text} entry)

The web UI promised "optional LRC"; before v0.1.23 the CLI hard-required
--lyrics and process_vocals opened the LRC unconditionally.

All heavy models are mocked (whisperx load/align/transcribe, Basic-Pitch
predict, syllable segmentation) — these tests exercise plumbing only.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import autorb.audio.vocals as vocals


def _mock_heavy_models(monkeypatch, transcript_segments=None):
    """Mock whisperx + Basic-Pitch + syllables; capture align transcripts."""
    captured = {}

    def fake_load_audio(_p):
        return np.zeros(16000 * 100, dtype=np.float32)

    def fake_align(transcript, model, metadata, audio, device,
                   return_char_alignments=True):
        captured["align_transcript"] = transcript
        return {"word_segments": [], "segments": [],
                "char_segments": []}

    def fake_load_align_model(language_code, device):
        return object(), {}

    monkeypatch.setattr(vocals.whisperx, "load_audio", fake_load_audio)
    monkeypatch.setattr(vocals.whisperx, "align", fake_align)
    monkeypatch.setattr(vocals.whisperx, "load_align_model",
                        fake_load_align_model)
    monkeypatch.setattr(vocals, "predict", lambda _p: (None, None, []))

    if transcript_segments is not None:
        class _FakeTranscribeModel:
            def transcribe(self, audio, batch_size=16, language=None):
                return {"segments": list(transcript_segments)}

        monkeypatch.setattr(vocals.whisperx, "load_model",
                            lambda name, device, compute_type: _FakeTranscribeModel())
    else:
        # only reached when the no-LRC path is taken — fail loudly otherwise
        monkeypatch.setattr(vocals.whisperx, "load_model",
                            lambda *a, **k: pytest.fail(
                                "load_model called on the LRC path"))

    import autorb.transcribe.syllables as syllables_mod
    import autorb.transcribe.pitch_tracking as pt
    monkeypatch.setattr(syllables_mod, "segment_all_words_to_syllables",
                        lambda *a, **k: [])
    monkeypatch.setattr(pt, "compute_vocal_pitch_per_syllable", lambda *a, **k: [])
    monkeypatch.setattr(pt, "build_melodic_contour_from_syllables",
                        lambda *a, **k: None)
    monkeypatch.setattr(pt, "resolve_syllable_pitches_with_fallback",
                        lambda *a, **k: [])
    return captured


class TestOptionalLrc:
    def test_with_lrc_aligns_lrc_text(self, tmp_path, monkeypatch):
        """LRC supplied: transcribed words never load the big model;
        align gets coarse chunks built from the LRC lines."""
        captured = _mock_heavy_models(monkeypatch)
        lrc = tmp_path / "song.lrc"
        lrc.write_text("[00:01.00]hello world\n[00:05.00]second line\n",
                       encoding="utf-8")
        out_dir = tmp_path / "out"; out_dir.mkdir()
        stem = tmp_path / "vocals.wav"; stem.write_bytes(b"RIFF")

        lyrics_data, word_segments, notes = vocals.process_vocals(
            stem, lrc, out_dir)

        assert len(lyrics_data) == 2
        assert lyrics_data[0] == {"time": 1.0, "text": "hello world"}
        # coarse chunking for alignment (not per-line slicing)
        assert "align_transcript" in captured
        starts = [s["start"] for s in captured["align_transcript"]]
        assert len(starts) <= 3 and starts[0] == 0.0

    def test_without_lrc_transcribes_vocal_stem(self, tmp_path, monkeypatch):
        """NO LRC: whisperx transcribes; segments become lyric lines."""
        captured = _mock_heavy_models(monkeypatch, transcript_segments=[
            {"start": 2.0, "end": 6.0, "text": " On the road again"},
            {"start": 10.0, "end": 14.0, "text": " Second phrase here"},
        ])
        out_dir = tmp_path / "out"; out_dir.mkdir()
        stem = tmp_path / "vocals.wav"; stem.write_bytes(b"RIFF")

        lyrics_data, word_segments, notes = vocals.process_vocals(
            stem, None, out_dir)

        assert len(lyrics_data) == 2
        assert lyrics_data[0] == {"time": 2.0, "text": "On the road again"}
        assert lyrics_data[1] == {"time": 10.0, "text": "Second phrase here"}
        # the transcription ALSO feeds the aligner as coarse chunks
        assert captured["align_transcript"], \
            "transcribed segments must still be aligned for word timing"


class TestCliOptionalLyrics:
    def test_cli_lyrics_not_required(self):
        """--lyrics is no longer in the CLI's missing-arguments check."""
        import ast
        tree = ast.parse(Path("autorb/cli.py").read_text())
        missing_checks = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "echo"
            and n.args and isinstance(n.args[0], ast.JoinedStr)
            and "missing required argument" in
                (n.args[0].values[0].value if n.args[0].values else "")
        ]
        src = Path("autorb/cli.py").read_text()
        assert '"--lyrics", lyrics' not in src
        assert '("--year", year), ("--genre", genre)' not in src

    def test_cli_metadata_never_writes_none(self):
        """Year/genre None must be coalesced before reaching songs.dta —
        generate_songs_dta's .get(key, default) only defaults ABSENT keys,
        so an explicit None would write 'year_released None'."""
        src = Path("autorb/cli.py").read_text()
        assert 'year if year is not None else 1998' in src
        assert 'genre if genre not in (None, "") else "Rock"' in src


class TestEmptyVocalsRobustness:
    """v0.1.32: a song whose vocal stem yields NO detectable speech
    (instrumentals; or buried/screamed punk vocals that WhisperX's VAD
    rejects — the free benchmark song) must chart as a song with an EMPTY
    vocal track, not crash step 4 with IndexError (caught by the release
    audit's functional conversion on the alpha04 wheel)."""

    def _empty_cache(self, tmp):
        import numpy as np
        (tmp / "tempo_map.json").write_text(json.dumps(
            {"beat_times": list(np.arange(0, 50, 0.35)),
             "bpms": [170.0] * 143}))
        (tmp / "vocals_cache.json").write_text(json.dumps(
            {"version": 2, "lyrics_data": [], "word_segments": [],
             "note_events": [], "alignment_result": {},
             "syllable_pitches": []}))

    def test_step4_survives_empty_words(self, tmp_path):
        from autorb.audio.step4_sync import run_step_4
        self._empty_cache(tmp_path)
        run_step_4(str(tmp_path/"tempo_map.json"),
                   str(tmp_path/"vocals_cache.json"),
                   str(tmp_path/"synced_track.json"),
                   vocals_stem=None, lrc_path=None)
        out = json.loads((tmp_path/"synced_track.json").read_text())
        words = out.get("words", out.get("word_segments", []))
        assert words == []

    def test_zero_word_pyin_pitches_survives(self):
        """The _compute_word_pyin_pitches zero-word guard: `ends[-1]` on an
        empty word list crashed (IndexError) — the benchmark conversion's
        second crash, found after the first (_clip_and_extend) fix."""
        from autorb.audio.step4_sync import _compute_word_pyin_pitches
        import numpy as np
        times = np.arange(0.0, 50.0, 0.01)
        f0 = np.full(len(times), np.nan)
        voiced = np.zeros(len(times), dtype=bool)
        probs = np.zeros(len(times))
        out = _compute_word_pyin_pitches(times, f0, voiced, probs,
                                         starts=[], ends=[])
        assert out == []

    def test_vocal_midi_survives_empty_words(self, tmp_path):
        import numpy as np
        from autorb.audio.step4_sync import run_step_4
        from autorb.export.midi_generator import generate_vocal_midi
        self._empty_cache(tmp_path)
        run_step_4(str(tmp_path/"tempo_map.json"),
                   str(tmp_path/"vocals_cache.json"),
                   str(tmp_path/"synced_track.json"),
                   vocals_stem=None, lrc_path=None)
        mid = generate_vocal_midi(tmp_path/"synced_track.json", tmp_path,
                                  "empty_test", song_length_ms=50000,
                                  bpm=170.0,
                                  beat_times=list(np.arange(0, 50, 0.35)),
                                  dynamic_bpms=[170.0]*143,
                                  count_in_ticks=0, count_in_ms=0)
        assert Path(mid).exists()
