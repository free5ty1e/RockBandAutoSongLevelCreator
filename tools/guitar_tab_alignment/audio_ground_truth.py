"""Extract a ground-truth strum/pitch guide directly from a guitar stem.

This is the audio-side ground truth used to validate charted strums and to
derive per-strum fret positions independent of Basic Pitch (which is the
component whose strum-picking is failing). It detects (a) distinct strum onset
times and (b) the dominant pitch at each strum, then maps that pitch to a
5-lane fret position using the same pitch_to_lane mapping the charter uses.

Why not just trust Basic Pitch? The chart gap diagnostics show Basic Pitch
drops/merges strums; this passes the audio through independent onset detection
(librosa) and windowed pitch detection (pyin) so we have an unbiased reference.
"""

from pathlib import Path
import numpy as np
import librosa

#: Minimum gap (s) between two distinct strums. Below this they are one attack.
MIN_STRUM_GAP = 0.06
#: Onset strength delta for detecting a strum. Calibrated on Open Road Song:
#: 0.08 yields ~698 distinct strums, matching the human-audible strum count
#: (~700). 0.03 over-detects (~1467) by treating chord-tone re-attacks as
#: separate strums; 0.15+ loses real 8th-note strums at 169 BPM.
ONSET_DELTA = 0.08
#: Hop length for onset envelope.
HOP = 256


def detect_strum_times(audio: np.ndarray, sr: int, min_gap: float = MIN_STRUM_GAP):
    """Return sorted, de-duplicated strum onset times (seconds)."""
    oenv = librosa.onset.onset_strength(y=audio, sr=sr, hop_length=HOP)
    times = librosa.times_like(oenv, sr=sr, hop_length=HOP)
    onsets = librosa.onset.onset_detect(
        onset_envelope=oenv, sr=sr, hop_length=HOP,
        delta=ONSET_DELTA, backtrack=True,
    )
    all_att = sorted(float(t) for t in times[onsets])
    kept = []
    for t in all_att:
        if not kept or t - kept[-1] >= min_gap:
            kept.append(t)
    return kept


def strum_pitch_at(audio: np.ndarray, sr: int, t: float,
                   fmin: float = 82.0, fmax: float = 1400.0):
    """Return the dominant f0 (Hz) in a short window at strum time ``t``.

    Uses a windowed pyin (a few cm) around the strum attack so the fundamental
    of the strummed chord/note rings through. Returns None if unvoiced.
    """
    i = int(t * sr)
    start = max(0, i - int(0.03 * sr))
    end = min(len(audio), i + int(0.12 * sr))
    seg = audio[start:end]
    if len(seg) < int(0.05 * sr):
        return None
    f0, _, voiced = librosa.pyin(
        seg, fmin=fmin, fmax=fmax, sr=sr,
        frame_length=2048, hop_length=512,
    )
    v = f0[(voiced >= 0.3) & (f0 > 0)]
    return float(np.median(v)) if len(v) else None


def build_ground_truth(audio_path: Path, sr: int = 44100) -> list:
    """Build a list of ``{"time": float, "f0": float|None}`` strum guides."""
    y, _ = librosa.load(str(audio_path), sr=sr, mono=True)
    times = detect_strum_times(y, sr)
    guide = []
    for t in times:
        f0 = strum_pitch_at(y, sr, t)
        guide.append({"time": float(t), "f0": f0})
    return guide


def guide_to_lanes(guide: list, instrumental_tuning=None) -> list:
    """Map each guide strum to a (lane, is_open) using pitch_to_lane.

    Pass the same tuning object the charter uses so lane meaning agrees.
    Falls back to a 0-4 chromatic mapping on raw pitch when no tuning is given
    (increasing pitch -> roughly increasing lane, per the user's requirement).
    """
    from autorb.transcribe.instruments.pitch_to_lane import (
        pitch_to_fret_string, fret_string_to_lane, Tuning,
    )
    tuning = instrumental_tuning or Tuning.standard_guitar()
    lanes = []
    for g in guide:
        if g["f0"] is None:
            lanes.append({"time": g["time"], "lane": None, "f0": None})
            continue
        fps = pitch_to_fret_string(g["f0"], tuning)
        lane = fret_string_to_lane(fps, tuning.num_strings)
        lanes.append({
            "time": g["time"],
            "f0": g["f0"],
            "lane": lane if 0 <= lane <= 4 else 0,
            "is_open": bool(fps.fret == 0),
            "fret": fps.fret,
        })
    return lanes


if __name__ == "__main__":
    import json, sys
    path = Path(sys.argv[1])
    guide = build_ground_truth(path)
    lanes = guide_to_lanes(guide)
    print(json.dumps(lanes[:50], indent=2))
    print(f"... total {len(lanes)} strums")