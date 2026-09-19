#!/usr/bin/env python3
"""Formal guitar-chart-vs-tab validation: outputs an ERROR RATING (0-100).

This is the validation stage of the pipeline: after a fresh guitar chart is
produced, compare it against the official guitar tabs (the tab guides in
``tools/guitar_tab_alignment/tabs/``) on two axes the user defined:

1. RHYTHM error — how closely charted strum timing matches the tab's rhythm
   (the user's canonical case: the Open Road Song intro is a repeating
   "3 eighth notes + 2 quarter notes" cell). Measured by extracting the
   chart's inter-onset interval pattern in each phrase and scoring it
   against the tab cell pattern.

2. PITCH-CHANGE error — when the guitar's chord root moves up/down, the
   chart's lane must move up/down to match (monotonic lane movement). We
   align the chart's per-strum lane sequence to the audio's chord-root
   contour and count direction violations.

Output: a JSON report with per-section metrics and a single composite
``error_rating`` (0 = perfect chart, 100 = maximally wrong), plus a
human-readable summary. Exit code 0 if under threshold, 1 otherwise, so the
pipeline can gate on it.

Usage (after a pipeline run with --build-clone-hero):
    python tools/guitar_tab_alignment/validate_guitar_vs_tab.py \
        --chart-dir output_6s_v117 \
        --tab-guide tools/guitar_tab_alignment/tabs/eve6_open_road_song.yaml \
        [--threshold 25]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audio_ground_truth import build_ground_truth          # noqa: E402
from validate_chart import _midi_guitar_attacks            # noqa: E402


def load_tab_guide(path: Path) -> dict:
    """Load a tab guide YAML (real parser — the guides use nested blocks)."""
    import yaml
    return yaml.safe_load(Path(path).read_text()) or {}


def chart_lanes_by_attack(midi_path: Path):
    """Return (attack_times, lanes) — one lane per Expert attack.

    For chord attacks (2+ notes at one tick) the lane is the *lowest*
    fret-position lane (the root), matching how a power chord is played.
    """
    import mido
    mf = mido.MidiFile(str(midi_path))
    tpb = mf.ticks_per_beat
    tempo_events = []
    abs_tick = 0
    for msg in mf.tracks[0]:
        abs_tick += msg.time
        if msg.type == "set_tempo":
            tempo_events.append((abs_tick, msg.tempo))
    if not tempo_events:
        tempo_events = [(0, 500000)]
    if tempo_events[0][0] > 0:
        tempo_events.insert(0, (0, tempo_events[0][1]))

    def t2s(tick):
        sec = 0.0
        for i in range(len(tempo_events) - 1):
            t0, tempo = tempo_events[i]
            t1 = tempo_events[i + 1][0]
            if tick <= t1:
                return sec + (tick - t0) * (tempo / 1e6) / tpb
            sec += (t1 - t0) * (tempo / 1e6) / tpb
        t0, tempo = tempo_events[-1]
        return sec + (tick - t0) * (tempo / 1e6) / tpb

    attacks = {}
    for tr in mf.tracks:
        if "GUITAR" not in tr.name.upper():
            continue
        abs_tick = 0
        for msg in tr:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and 60 <= msg.note <= 64:
                t = abs_tick
                lane = msg.note - 60
                if t in attacks:
                    attacks[t] = min(attacks[t], lane)  # root = lowest lane
                else:
                    attacks[t] = lane
    times = sorted(attacks)
    return [t2s(t) for t in times], [attacks[t] for t in times]


def rhythm_error(attacks, tempo_map, cell_pattern_beats):
    """Score the chart's rhythm against the tab's rhythmic cell.

    Two components:
    1. **Grid adherence** (primary): charted attacks must sit on the
       ``divisions``-per-beat grid at the guitar's phase — the tab's rhythm
       figures are grid rhythms, and misplaced gems are what a player reads as
       "wrong rhythm". Scored as the fraction of attacks off-grid (within a
       1/16 tolerance), weighted by their distance.
    2. **Cell match** (secondary): sliding-window L1 between the chart's
       interval pattern and the tab cell (normalized), reported separately so
       the dominant rhythmic figure can be compared without conflating it
       with grid placement.

    Returns (grid_error in [0,1], cell_error or None).
    """
    if not attacks:
        return 1.0, None
    beats = np.array([t for t, _ in tempo_map])

    def beat_pos(t):
        i = int(np.searchsorted(beats, t)) - 1
        i = max(0, min(i, len(beats) - 2))
        return i + (t - beats[i]) / (beats[i + 1] - beats[i])

    # --- Grid adherence at 1/8 divisions, best phase (as the transcriber does)
    best_phase, best_err = 0.0, np.inf
    for k in range(8):
        ph = k * 0.125
        err = 0.0
        for a in attacks:
            pos = beat_pos(a) + ph
            r = (pos * 2) % 1.0
            err += min(r, 1 - r)
        err /= len(attacks)
        if err < best_err:
            best_err, best_phase = err, ph
    # grid_error: fraction of a grid step the average attack is displaced.
    # 0.5 = attacks sit exactly between grid lines (maximally off-grid).
    grid_error = min(1.0, best_err / 0.25)

    cell_err = None
    if cell_pattern_beats:
        bp = np.array([beat_pos(a) for a in attacks])
        # The tab cell [e,e,e,q,q] lists note DURATIONS. The observable interval
        # between attack k and k+1 IS the duration of note k (consecutive
        # attacks), so the interval pattern is the cell minus its LAST entry
        # — NOT np.diff of the cell (which would subtract adjacent durations).
        cell = np.array(cell_pattern_beats, dtype=float)[:-1]
        n = len(cell) + 1
        errs = []
        for s in range(0, len(bp) - n + 1):
            intervals = np.diff(bp[s:s + n])
            scale = intervals.sum() / max(cell.sum(), 1e-9)
            errs.append(float(np.abs(intervals - cell * scale).sum() / max(scale, 1e-9)))
        # The tab figure must be RENDERED correctly wherever it occurs; the
        # chart is not penalized for also containing other rhythms the audio
        # objectively has (e.g. continuous 8th runs). Use the best window plus
        # the fraction of near-matching windows so a missing figure still scores.
        if errs:
            errs = np.array(errs)
            best = float(errs.min())
            near = float(np.mean(errs <= 0.35))
            # error = how well the figure is rendered where it appears
            # (best window) blended with how consistently it appears.
            cell_err = 0.5 * best + 0.5 * (1.0 - near)
        else:
            cell_err = None
    return grid_error, cell_err
    for s in range(0, len(bp) - n + 1):
        window = bp[s:s + n]
        intervals = np.diff(window)
        # normalize the tab cell to the same total duration as the window
        scale = intervals.sum() / max(cell.sum(), 1e-9)
        errs.append(float(np.abs(intervals - cell * scale).sum() / max(scale, 1e-9)))
    med = float(np.median(errs))
    return med, None


def pitch_direction_error(attacks, lanes, audio_guide, stem_path=None, sr=44100):
    """Direction fidelity: chord-root up/down vs lane up/down.

    The pitch ground truth per strum is the low-band chord root (same
    detector the transcriber uses — robust on distorted power chords, unlike
    pyin f0 which only fires on a fraction of strums). For consecutive
    charted strums whose roots moved by >= 1 semitone, the charted lane must
    move in the same direction (user requirement: "pitch changes must be
    generally represented as increasing or decreasing finger positions").
    """
    if stem_path is None or len(attacks) < 3:
        return 0.0, 0
    import librosa as _lr
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from autorb.transcribe.instruments.guitar import (
        _strum_chord_roots, _strum_backbone,
    )
    y, _ = _lr.load(str(stem_path), sr=sr, mono=True)
    # Charted attacks snapped onto their own strum grid — root measured at
    # each charted attack time. The transcriber median/mode-filters raw roots
    # (single-window FFT roots jitter on distorted chords), so the ground
    # truth here must apply the same filter — otherwise the metric scores
    # detector noise, not chart error. Sub-semitone steps are also collapsed
    # to the transcriber's chord-LEVEL (a chart expresses chord changes, not
    # detector bin jitter).
    roots = _strum_chord_roots(y, sr, np.array(attacks))
    # Cluster into the same 1-semitone levels the transcriber uses.
    valid = roots[roots > 0]
    if len(valid):
        lvl = np.sort(valid)
        levels = []
        for r in lvl:
            if not levels or r - levels[-1] > 1.0:
                levels.append(float(r))
        levels = np.array(levels)
        roots = np.where(roots > 0, levels[np.argmin(np.abs(levels[None, :] - roots[:, None]), axis=1)], roots)
    viol = 0
    total = 0
    prev = None
    for lane, root in zip(lanes, roots):
        if root <= 0:
            continue
        if prev is not None and abs(root - prev[1]) >= 1.0:
            total += 1
            d_root = np.sign(root - prev[1])
            d_lane = np.sign(lane - prev[0])
            if d_lane != d_root:
                viol += 1
        prev = (lane, root)
    return (viol / total if total else 0.0), total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart-dir", required=True,
                    help="Pipeline output dir (needs clone_hero/<song>/notes.mid and stems/guitar.wav)")
    ap.add_argument("--tab-guide", required=True)
    ap.add_argument("--threshold", type=float, default=25.0)
    ap.add_argument("--section-end", type=float, default=None,
                    help="Only validate the first N seconds (e.g. the intro)")
    args = ap.parse_args()

    chart_dir = Path(args.chart_dir)
    guide = load_tab_guide(Path(args.tab_guide))

    # Locate the Clone Hero notes.mid (count-in-free) and the guitar stem.
    ch_midi = None
    for p in chart_dir.glob("clone_hero/*/notes.mid"):
        ch_midi = p
        break
    stem = chart_dir / "stems" / "guitar.wav"
    if ch_midi is None or not stem.exists():
        print(json.dumps({"error": f"missing clone_hero notes.mid or guitar.wav under {chart_dir}"}))
        return 2

    # tempo map (from the pipeline's cached tempo_map.json)
    tm = json.loads((chart_dir / "tempo_map.json").read_text())
    tempo_map = list(zip(tm["beat_times"], tm["bpms"]))

    attacks = _midi_guitar_attacks(ch_midi)
    lane_times, lanes = chart_lanes_by_attack(ch_midi)
    if args.section_end:
        attacks = [a for a in attacks if a <= args.section_end]
        keep = [i for i, t in enumerate(lane_times) if t <= args.section_end]
        lane_times = [lane_times[i] for i in keep]
        lanes = [lanes[i] for i in keep]

    audio_guide = build_ground_truth(str(stem))
    if args.section_end:
        audio_guide = [g for g in audio_guide if g["time"] <= args.section_end]

    # Rhythm error vs the tab cell.
    cell = guide.get("validation", {}).get("cell_pattern_beats") or guide.get("cell_pattern_beats")
    if isinstance(cell, str):
        cell = json.loads(cell)
    if cell:
        r_err, cell_err = rhythm_error(attacks, tempo_map, cell)
    else:
        r_err, cell_err = rhythm_error(attacks, tempo_map, None)

    # Pitch direction error (low-band root as ground truth).
    p_err, n_pitch = pitch_direction_error(lane_times, lanes, audio_guide,
                                            stem_path=stem)

    # Strum coverage (recall/precision vs the audio backbone).
    gt = np.array([g["time"] for g in audio_guide])
    at = np.array(attacks)
    if len(gt) and len(at):
        cov_r = float(np.mean(np.min(np.abs(at[None, :] - gt[:, None]), axis=1) <= 0.10))
        cov_p = float(np.mean(np.min(np.abs(gt[None, :] - at[:, None]), axis=1) <= 0.10))
    else:
        cov_r = cov_p = 0.0

    # Composite error rating: 0 = perfect, 100 = worst.
    # 40 points grid adherence (rhythm placement), 20 points cell match,
    # 20 points pitch-direction, 20 points strum coverage.
    r_term = min(1.0, r_err / 1.0) if r_err is not None else 0.0
    c_term = min(1.0, (cell_err or 0.0) / 1.0) if cell_err is not None else 0.0
    p_term = p_err if n_pitch else 0.0
    cov_term = ((1 - cov_r) + (1 - cov_p) / 2)
    error_rating = round(40 * r_term + 20 * c_term + 20 * p_term + 20 * min(1.0, cov_term), 2)

    report = {
        "song": guide.get("song", Path(args.tab_guide).stem),
        "n_chart_attacks": len(attacks),
        "n_guide_strums": len(audio_guide),
        "grid_error": None if r_err is None else round(r_err, 3),
        "rhythm_cell_error": None if cell_err is None else round(cell_err, 3),
        "rhythm_cell": cell,
        "pitch_direction_error": round(p_err, 3),
        "pitch_direction_samples": n_pitch,
        "coverage_recall": round(cov_r, 3),
        "coverage_precision": round(cov_p, 3),
        "error_rating": error_rating,
        "threshold": args.threshold,
        "pass": bool(error_rating <= args.threshold),
    }
    (chart_dir / "guitar_validation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())