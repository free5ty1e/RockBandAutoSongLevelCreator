"""Regression tests for the position-aware strip merge in autorb.audio.stems.

The old sequential merge assumed every strip begins exactly `overlap` after
the accumulated output; the flush-to-tail final strip (start = n - strip_len)
violates that and corrupted the outro of Open Road Song (input vs
sum-of-stems correlation 0.998 -> ~0 from ~175 s). These tests pin the
position-aware merge (`_merge_strips_by_position`) with synthetic signals of
known truth.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autorb.audio.stems import _init_fades, _merge_strips_by_position


@pytest.fixture()
def tmpdir(tmp_path):
    return tmp_path


def _build_raw_strips(tmpdir, starts, strip_len, sr, n):
    """Write RAW (unwindowed) strips whose content encodes absolute time."""
    files = []
    for i, s in enumerate(starts):
        seg = ((np.arange(strip_len, dtype=np.float32) + s) / sr)[:, None]
        p = tmpdir / f"strip_{i}.wav"
        sf.write(str(p), seg.astype(np.float32), sr, subtype="FLOAT")
        files.append(str(p))
    return files


def test_merge_exact_with_irregular_final_strip(tmpdir):
    """The flush-to-tail geometry that corrupted the outro must merge exactly.

    Geometry mirrors the real 198 s Eve 6 case scaled down: regular gaps of
    20 s, final strip flush to the tail (gap 10 s, larger-than-nominal
    overlap).
    """
    sr = 8000
    n = int(100 * sr)
    strip_len = int(30 * sr)
    step = int(20 * sr)
    overlap = int(6 * sr)
    starts = list(range(0, n - strip_len + 1, step))
    if not starts or starts[-1] + strip_len < n:
        starts.append(max(0, n - strip_len))
    assert starts[-1] < starts[-2] + step, "test requires an irregular final strip"

    _init_fades(overlap)
    files = _build_raw_strips(tmpdir, starts, strip_len, sr, n)
    out = tmpdir / "merged.wav"
    _merge_strips_by_position(files, starts, out, sr=sr, ch=1, n=n)

    merged, _ = sf.read(str(out))
    expected = np.arange(len(merged), dtype=np.float32) / sr
    err = np.abs(merged - expected)
    assert err.max() < 1e-3, f"max err {err.max()}"


def test_merge_exact_on_grid(tmpdir):
    """Regular on-grid strips (exact nominal overlaps) must also merge exactly."""
    sr = 8000
    n = int(80 * sr)
    strip_len = int(20 * sr)
    step = int(14 * sr)
    overlap = int(6 * sr)
    starts = list(range(0, n - strip_len + 1, step))
    if not starts or starts[-1] + strip_len < n:
        starts.append(max(0, n - strip_len))

    _init_fades(overlap)
    files = _build_raw_strips(tmpdir, starts, strip_len, sr, n)
    out = tmpdir / "merged.wav"
    _merge_strips_by_position(files, starts, out, sr=sr, ch=1, n=n)

    merged, _ = sf.read(str(out))
    expected = np.arange(len(merged), dtype=np.float32) / sr
    err = np.abs(merged - expected)
    assert err.max() < 1e-3, f"max err {err.max()}"


def test_merge_stereo_preserves_channels(tmpdir):
    """Stereo strips must stay stereo (and mono must not broadcast to 2-D explode)."""
    sr = 8000
    strip_len = int(20 * sr)
    overlap = int(6 * sr)
    starts = [0, int(14 * sr)]
    n = int(30 * sr)  # fully covered: last strip ends at 34 s > 30 s
    _init_fades(overlap)
    files = []
    for i, s in enumerate(starts):
        t = (np.arange(strip_len, dtype=np.float32) + s) / sr
        seg = np.stack([t, -t], axis=1)  # left = +time, right = -time
        p = tmpdir / f"st_{i}.wav"
        sf.write(str(p), seg.astype(np.float32), sr, subtype="FLOAT")
        files.append(str(p))
    out = tmpdir / "merged.wav"
    _merge_strips_by_position(files, starts, out, sr=sr, ch=2, n=n)
    merged, _ = sf.read(str(out))
    assert merged.ndim == 2 and merged.shape[1] == 2
    k = np.arange(len(merged), dtype=np.float32) / sr
    assert np.abs(merged[:, 0] - k).max() < 1e-3
    assert np.abs(merged[:, 1] + k).max() < 1e-3


def test_merge_single_strip_passthrough(tmpdir):
    """A single strip must pass through unchanged (no fade applied)."""
    sr = 8000
    n = int(10 * sr)
    overlap = int(6 * sr)
    _init_fades(overlap)
    seg = (np.arange(n, dtype=np.float32) / sr)[:, None]
    p = tmpdir / "solo.wav"
    sf.write(str(p), seg, sr, subtype="FLOAT")
    out = tmpdir / "merged.wav"
    _merge_strips_by_position([str(p)], [0], out, sr=sr, ch=1, n=n)
    merged, _ = sf.read(str(out))
    assert np.abs(merged - seg[:, 0]).max() < 1e-6


def test_detect_solo_regions_register_energy():
    """Solo detection: high-register dominance marks the solo, not rhythm.

    Builds a synthetic stem: steady low power-chord chug throughout, plus a
    lead melody in the 600-1600 Hz band during 20-40 s only. The detector
    must return a region covering the lead section and nothing else.
    """
    import numpy as np
    from autorb.transcribe.instruments.guitar import (
        _strum_backbone, _detect_solo_regions,
    )
    sr = 22050
    t = np.arange(int(60 * sr)) / sr
    y = np.zeros_like(t)
    # rhythm: 110 Hz chug on every 0.25 s
    for k in range(0, 60 * 4):
        i0 = int(k * 0.25 * sr)
        i1 = i0 + int(0.1 * sr)
        tt = t[i0:i1]
        y[i0:i1] += 0.4 * np.sin(2 * np.pi * 110 * tt)
    # lead: 880 Hz melody during 20-40 s (amplitude such that the lead
    # register dominates the chug, as in real solos — measured ratio during
    # the Open Road Song solo is ~2.4-2.8 vs ~0.3-0.7 in rhythm sections)
    for k in range(80, 160):
        i0 = int(k * 0.25 * sr)
        i1 = i0 + int(0.1 * sr)
        tt = t[i0:i1]
        y[i0:i1] += 1.2 * np.sin(2 * np.pi * 880 * tt)
    strums = np.array([k * 0.25 for k in range(0, 60 * 4)])
    regions = _detect_solo_regions(y, sr, strums)
    assert regions, "expected a solo region around 20-40 s"
    # region must cover the lead section
    assert any(a <= 25 <= b for a, b in regions), regions
    # and must not extend over the pure-rhythm intro
    assert all(a > 10 for a, b in regions), regions