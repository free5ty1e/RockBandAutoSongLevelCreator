"""Tests for the headless sync-validation artifacts (lyrics .srt + alignment report)."""

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from autorb.export.alignment_report import (
    build_lyrics_srt,
    build_alignment_report,
    _charted_vocal_times,
    _srt_time,
    _tick_to_sec,
)
from autorb.export.midi_generator import generate_vocal_midi


def _write_synced_json(path: Path, n: int = 10, gap: float = 0.8,
                       start: float = 1.0) -> None:
    items = []
    t = start
    for i in range(n):
        items.append({
            "start": t, "end": t + 0.5, "word": f"word{i}", "pitch": 60,
            "syllables": [{
                "text": f"word{i}", "start": t, "end": t + 0.5,
                "note_segments": [{"start": t, "end": t + 0.5, "midi_note": 60}],
                "pitch_trusted": True,
            }],
        })
        t += gap
    path.write_text(json.dumps({"synced_lyrics": items}), encoding="utf-8")


def _make_vocal_stem(path: Path, sr: int = 22050, secs: float = 9.0,
                     burst_gap: float = 0.8, first_burst: float = 1.0) -> None:
    """A vocal stem with short broadband noise bursts every ``burst_gap`` s.

    Noise bursts produce a strong, reliable librosa onset at each burst start
    (sine tones do not), so tests that count flagged words are deterministic.
    """
    rng = np.random.default_rng(0)
    n = int(sr * secs)
    t = np.arange(n) / sr
    data = np.zeros(n)
    start = first_burst
    while start < secs - 0.3:
        seg = (t >= start) & (t < start + 0.08)
        data[seg] += 0.4 * rng.standard_normal(int(seg.sum()))
        start += burst_gap
    sf.write(path, data, sr)


def _make_chart(synced: Path, tmp: Path) -> Path:
    beats, bpms = [], []
    t = 0.0
    for _ in range(40):
        beats.append(t)
        bpms.append(120.0)
        t += 0.5
    return generate_vocal_midi(
        synced, tmp, "notes",
        song_length_ms=10000, bpm=120.0,
        beat_times=beats, dynamic_bpms=bpms,
        count_in_ticks=0, count_in_ms=0,
    )


def test_srt_time_format():
    assert _srt_time(0) == "00:00:00,000"
    assert _srt_time(1.5) == "00:00:01,500"
    assert _srt_time(61.25) == "00:01:01,250"
    assert _srt_time(3661.0) == "01:01:01,000"


def test_build_lyrics_srt_entries(tmp_path: Path):
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced, n=4, gap=1.0)
    out = build_lyrics_srt(synced, tmp_path / "lyrics_preview.srt")
    text = out.read_text(encoding="utf-8")

    assert "word0" in text
    assert "00:00:01,000 --> 00:00:01,500" in text
    # 4 words -> blocks "1".."4"
    assert "3" in text and "4" in text


def test_srt_offset_shifts_all_timings(tmp_path: Path):
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced, n=2, gap=1.0)
    out = build_lyrics_srt(synced, tmp_path / "s.srt", offset_ms=1000)
    text = out.read_text(encoding="utf-8")
    assert "00:00:02,000 --> 00:00:02,500" in text


def test_charted_vocal_times_recovered_from_midi(tmp_path: Path):
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced, n=6)
    mid = _make_chart(synced, tmp_path)
    notes = _charted_vocal_times(mid)
    assert len(notes) == 6
    assert notes[0][1] == "word0"


def test_tick_to_sec_integrates_tempo_map(tmp_path: Path):
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced, n=4)
    mid = _make_chart(synced, tmp_path)
    t2s = _tick_to_sec(mid)
    # 1.0s @ 120 BPM @ 480 tpb = 960 ticks -> back to 1.0s.
    assert abs(t2s(960) - 1.0) < 0.001


def test_alignment_report_flags_aligned_and_missing_words(tmp_path: Path):
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced, n=8)
    mid = _make_chart(synced, tmp_path)
    stem = tmp_path / "vocals.wav"
    _make_vocal_stem(stem)

    report_path = build_alignment_report(
        synced, mid, stem, tmp_path / "alignment_report.json",
        spec_dir=tmp_path / "specs",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # The synthetic bursts are placed at exactly the word starts, so the bulk of
    # words should be 'ok' (delta ~0) and the report must summarize cleanly.
    assert report["summary"]["n_words"] == 8
    assert report["summary"]["n_ok"] >= 7
    assert report["summary"]["median_abs_delta_s"] is not None
    assert all("charted_sec" in w and "flag" in w for w in report["words"])

    # Spec PNGs may be emitted only for flagged words; with everything aligned
    # the folder may be empty, but the report itself must exist.
    assert report_path.exists()


def test_alignment_spec_pngs_render_for_flagged_words(tmp_path: Path):
    """Regression: rendering an annotated spectrogram must not crash.

    The original code passed an 88200-sample coordinate array to librosa's
    `specshow`, which expects one x-coordinate per mel frame (173) — that
    raised "Coordinate shape mismatch" and aborted the whole report step.

    Words are deliberately offset +0.4s from the vocal bursts, so EVERY word
    must be flagged 'early' (nearest onset = burst - 0.4s < -0.30s threshold)
    and every flagged word must render an `alignment_*.png`. A single missed
    word or a dropped spec means something is wrong — the assertions below are
    intentionally strict.
    """
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced, n=6, gap=0.8, start=1.4)
    mid = _make_chart(synced, tmp_path)
    stem = tmp_path / "vocals.wav"
    _make_vocal_stem(stem, burst_gap=0.8, first_burst=1.0)

    spec_dir = tmp_path / "specs"
    report_path = build_alignment_report(
        synced, mid, stem, tmp_path / "alignment_report.json",
        spec_dir=spec_dir,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # All 6 words are 0.4s early -> exactly 6 early flags, zero ok.
    assert report["summary"]["n_words"] == 6
    assert report["summary"]["n_early"] == 6, report["summary"]
    assert report["summary"]["n_ok"] == 0
    # One annotated PNG per flagged word.
    pngs = sorted(spec_dir.glob("alignment_*.png"))
    assert len(pngs) == 6
    for png in pngs:
        assert png.name.endswith("_early.png"), png.name
