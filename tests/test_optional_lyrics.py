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
