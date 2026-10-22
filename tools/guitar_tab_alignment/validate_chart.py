"""Validate a charted guitar track against a ground-truth strum guide.

Compares the algorithm's charted strum attacks (MIDI note_ons) against the
audio-derived strum guide (or a supplied tab-aligned guide) and reports:

* **strum recall**: fraction of guide strums matched by a charted attack
  (within a tolerance window). Low recall = the algorithm dropped strums.
* **false strums**: charted attacks with no guide strum nearby. High = the
  chart adds notes the audio doesn't have.
* **time sync error**: median offset between matched pairs.
* **pitch/lane fidelity**: for matched pairs, whether the chart's lane matches
  the guide's lane direction/pitch (if the guide has f0).

This is the objective scoreboard the closed loop optimizes against.
"""

from pathlib import Path
import numpy as np
import mido

#: How close a charted attack must be to a guide strum to count as a match (s).
MATCH_TOL = 0.10


def _midi_guitar_attacks(midi_path: Path, bpm: float = None):
    """Return charted guitar attack times in song-seconds.

    The chart MIDI carries a **dynamic** tempo map (one ``set_tempo`` per beat,
    ~555 events on Open Road Song), so ticks must be converted by *integrating*
    the tempo segments — a single-tempo conversion drifts progressively and
    turns correctly-matched strums into false/missing pairs.

    The returned times are in the MIDI timeline (which includes the Rock Band
    count-in on CON charts); callers subtract the count-in offset when
    comparing to song-time audio. Clone Hero ``notes.mid`` is count-in-free.
    """
    mf = mido.MidiFile(str(midi_path))
    tpb = mf.ticks_per_beat

    # Integrate tempo: collect (tick, tempo_us) events from the tempo track,
    # then map each attack tick through the segment it falls in.
    tempo_events = []  # (tick, tempo_us)
    abs_tick = 0
    for msg in mf.tracks[0]:
        abs_tick += msg.time
        if msg.type == "set_tempo":
            tempo_events.append((abs_tick, msg.tempo))
    if not tempo_events:
        tempo_events = [(0, 60_000_000.0 / (bpm or 120.0))]
    if tempo_events[0][0] > 0:
        tempo_events.insert(0, (0, tempo_events[0][1]))

    def ticks_to_seconds(tick: int) -> float:
        sec = 0.0
        for i in range(len(tempo_events) - 1):
            t0, tempo = tempo_events[i]
            t1 = tempo_events[i + 1][0]
            if tick <= t1:
                sec += (tick - t0) * (tempo / 1e6) / tpb
                return sec
            sec += (t1 - t0) * (tempo / 1e6) / tpb
        t0, tempo = tempo_events[-1]
        sec += (tick - t0) * (tempo / 1e6) / tpb
        return sec

    # Expert guitar pitches are packed at base 60 (lanes 60-64); Hard/Medium/Easy
    # live at 72/84/96 and are re-quantized onto coarser grids by the difficulty
    # reducer, which would add phantom attack slots. Validate Expert only.
    tick_attacks = set()
    for tr in mf.tracks:
        if "GUITAR" not in tr.name.upper():
            continue
        abs_tick = 0
        for msg in tr:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and 60 <= msg.note <= 64:
                tick_attacks.add(abs_tick)
    attacks = sorted(round(ticks_to_seconds(t), 4) for t in tick_attacks)
    return attacks


def _match(audio_guide, chart_attacks, count_in_offset, tol=MATCH_TOL):
    """Match charted attacks to guide strums. Returns (matched_chart, matched_guide, unmatched_chart)."""
    # shift chart attacks into song-time
    chart_song = [a - count_in_offset for a in chart_attacks]
    guide = sorted(g["time"] for g in audio_guide)
    chart_matched = []
    guide_matched = []
    gi = 0
    for c in chart_song:
        # find nearest guide strum not already used
        best = None
        for j in range(gi, len(guide)):
            d = abs(guide[j] - c)
            if d <= tol:
                best = j
                break
            if guide[j] > c + tol:
                break
        if best is not None:
            chart_matched.append(c)
            guide_matched.append(guide[best])
            gi = best + 1
        # else: unmatched chart attack (false strum)

    guide_all = set(g for g in guide)
    guide_unmatched = [g for g in guide if g not in set(guide_matched)]
    return chart_matched, guide_matched, len(chart_attacks) - len(chart_matched), guide_unmatched


def validate(audio_guide, chart_midi, count_in_offset, tol=MATCH_TOL):
    """Return a dict scorecard.

    Reports both:
    * **coverage recall/precision** (non-exclusive): does every audible strum
      have a charted attack within ``tol``? In dense 8th/16th runs, adjacent
      strums are ~60 ms apart while grid-snapping displaces attacks up to
      ~45 ms, so exclusive one-to-one matching undercounts there — a strum
      whose neighbor consumed the attack still means the chart has a gem in
      the right place.
    * **exclusive matched counts** (greedy one-to-one), for reference.
    """
    chart_attacks = _midi_guitar_attacks(chart_midi)
    chart_song = np.array([a - count_in_offset for a in chart_attacks])
    guide = np.array([g["time"] for g in audio_guide])

    # Coverage (non-exclusive) — the playtest-meaningful metric.
    if len(guide) and len(chart_song):
        nearest_to_strum = np.min(np.abs(chart_song[None, :] - guide[:, None]), axis=1)
        nearest_to_attack = np.min(np.abs(guide[None, :] - chart_song[:, None]), axis=1)
        cov_recall = float(np.mean(nearest_to_strum <= tol))
        cov_precision = float(np.mean(nearest_to_attack <= tol))
    else:
        cov_recall = cov_precision = 0.0

    matched_chart, matched_guide, n_false, guide_unmatched = _match(
        audio_guide, chart_attacks, count_in_offset, tol)

    n_guide = len(audio_guide)
    n_chart = len(chart_attacks)
    recall = len(matched_guide) / n_guide if n_guide else 0.0
    precision = len(matched_chart) / n_chart if n_chart else 0.0
    f1 = (2 * (cov_recall * cov_precision) / (cov_recall + cov_precision)
          if (cov_recall + cov_precision) else 0.0)
    if matched_chart:
        errs = [c - g for c, g in zip(matched_chart, matched_guide)]
        time_med = float(np.median(errs))
        time_abs = float(np.median(np.abs(errs)))
    else:
        time_med = time_abs = 0.0

    return {
        "n_guide_strums": n_guide,
        "n_charted_attacks": n_chart,
        "coverage_recall": cov_recall,
        "coverage_precision": cov_precision,
        "f1": f1,
        "exclusive_recall": recall,
        "exclusive_precision": precision,
        "false_attacks": n_false,
        "missing_strums": len(guide_unmatched),
        "median_time_error_s": time_med,
        "median_abs_time_error_s": time_abs,
    }


if __name__ == "__main__":
    import json, sys
    from audio_ground_truth import build_ground_truth
    audio_guide = build_ground_truth(Path(sys.argv[1]))
    chart_midi = Path(sys.argv[2])
    count_in = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    score = validate(audio_guide, chart_midi, count_in)
    print(json.dumps(score, indent=2))