#!/usr/bin/env python3
"""Analyze an official Rock Band DLC chart (notes.mid extracted from a CON).

This is the ground-truth side of the charting-accuracy loop (the accuracy
plan §9: tab + official chart + audio = three-way truth). Quantifies what
"DLC quality" means per instrument: note counts per difficulty, HOPO
placement (incl. forced markers), sustain lengths, chord rates, drum lanes,
vocal phrasing — the numbers our auto charts must approach.

Usage:
    python tools/dlc_ground_truth.py analyze <notes.mid> [--json out.json]
    python tools/dlc_ground_truth.py diff <official.mid> <ours.mid> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from mido import MidiFile

#: difficulty base pitches (the packed-MIDI convention, RBMidConverter.cs)
DIFF_BASES = {"easy": 60, "medium": 72, "hard": 84, "expert": 96}
LANE_NAMES = {0: "G", 1: "R", 2: "Y", 3: "B", 4: "O"}

INSTRUMENT_TRACKS = ["PART GUITAR", "PART BASS", "PART DRUMS", "PART KEYS"]


def _decode_pitch(p: int):
    """packed pitch -> (difficulty, lane, marker_kind) or None."""
    for diff, base in DIFF_BASES.items():
        if base <= p <= base + 4:
            return diff, p - base, "gem"
        if p == base + 5:
            return diff, 5, "hopo_on"
        if p == base + 6:
            return diff, 6, "strum"
    return None


def analyze_track(track, tpb: int, ticks_to_sec=None) -> dict:
    """Analyze one PART track: per-difficulty gems, HOPO markers, sustains.

    ``ticks_to_sec`` converts absolute ticks to seconds via the GLOBAL tempo
    map (format-1 conductor-track semantics)."""
    out = {"_ticks_to_sec": ticks_to_sec}
    open_notes = defaultdict(dict)  # pitch -> {start_tick: start_tick}
    events = []  # (kind, diff, lane, start_tick, end_tick)
    markers = Counter()
    tick = 0
    for msg in track:
        tick += msg.time  # NOTE: msg.time is a DELTA — accumulate to absolute
        if msg.type not in ("note_on", "note_off"):
            continue
        vel = 0 if msg.type == "note_off" else msg.velocity
        pitch = msg.note
        dec = _decode_pitch(pitch)
        if dec is None:
            continue
        diff, lane, kind = dec
        if kind == "hopo_on":
            markers[f"{diff}:hopo_on"] += 1
            continue
        if kind == "strum":
            markers[f"{diff}:strum"] += 1
            continue
        key = (diff, lane)
        if vel > 0:
            open_notes[key][tick] = tick
        else:  # note_off
            starts = [t for t in open_notes.get(key, {}) if t <= tick]
            if starts:
                st = max(starts)
                del open_notes[key][st]
                events.append(("gem", diff, lane, st, tick))
    for (diff, lane), starts in list(open_notes.items()):
        for st in starts.values():
            events.append(("gem", diff, lane, st, st))  # unterminated = tick-off
    per_diff = defaultdict(lambda: {"notes": 0, "chords": 0, "sustains": [],
                                    "lanes": Counter(), "total_len": 0,
                                    "_gem_times": []})
    by_start = defaultdict(list)
    t2s = ticks_to_sec or (lambda t: t)
    for kind, diff, lane, st, en in events:
        per_diff[diff]["notes"] += 1
        per_diff[diff]["lanes"][lane] += 1
        per_diff[diff]["_gem_times"].append((t2s(st), lane))
        length_ticks = max(0, en - st)
        per_diff[diff]["total_len"] += length_ticks
        if length_ticks > 0:
            per_diff[diff]["sustains"].append(length_ticks)
        by_start[(diff, st)].append(lane)
    for (diff, st), lanes in by_start.items():
        if len(lanes) > 1:
            per_diff[diff]["chords"] += 1
    for diff, d in per_diff.items():
        n = d["notes"]
        d["chord_rate"] = round(d["chords"] / n, 3) if n else 0.0
        sust = sorted(d["sustains"])
        if sust:
            d["sustain_ticks"] = {
                "median": sust[len(sust) // 2], "max": sust[-1],
                "count": len(sust)}
        else:
            d["sustain_ticks"] = {"median": 0, "max": 0, "count": 0}
        d["lanes"] = {LANE_NAMES.get(k, k): v for k, v in d["lanes"].most_common()}
        del d["sustains"]
        # _gem_times STAYS (consumed by align_expert; stripped from JSON output)
    out["difficulties"] = dict(per_diff)
    out["markers"] = dict(markers)
    out["total_notes"] = sum(d["notes"] for d in per_diff.values())
    return out


def analyze_vocals(track) -> dict:
    """Vocal track: phrases (105/106), notes, pitch range."""
    phrases = 0
    notes = []
    open_note = None
    lyrics = []
    for msg in track:
        if msg.type == "note_on" and msg.velocity > 0 and 36 <= msg.note <= 84:
            open_note = (msg.note, len(lyrics))
        elif msg.type == "note_off" and open_note and msg.note == open_note[0]:
            notes.append(msg.note)
            open_note = None
        elif msg.type == "note_on" and msg.velocity > 0 and msg.note == 105:
            phrases += 1
        elif msg.type == "lyrics" and msg.text.strip():
            lyrics.append(msg.text)
    return {
        "phrases": phrases,
        "notes": len(notes),
        "pitch_min": min(notes) if notes else None,
        "pitch_max": max(notes) if notes else None,
        "lyric_syllables": len(lyrics),
    }


def load_track_events(path: Path) -> dict:
    mid = MidiFile(str(path))
    tpb = mid.ticks_per_beat
    tempo_us = 500000
    # Format-1 MIDI: tempo events live in the CONDUCTOR track (usually track 0),
    # not in each PART track. Collect a GLOBAL tick->tempo map first, then
    # convert each track's gem ticks with it. (The per-track scan wrongly
    # assumed 120 BPM throughout and made every downstream time look early —
    # the "chart truncated at 147s" false alarm on 2026-10-28.)
    global_tempo = []  # [(tick, us)] sorted
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                global_tempo.append((tick, msg.tempo))
    global_tempo.sort()
    import bisect

    def ticks_to_sec(tick: int) -> float:
        # integrate the global tempo map up to `tick`
        sec = 0.0
        prev_t, prev_us = 0, global_tempo[0][1] if global_tempo else 500000
        for t, us in global_tempo:
            if t >= tick:
                break
            sec += (min(t, tick) - prev_t) * prev_us / tpb / 1e6
            prev_t, prev_us = t, us
        sec += (tick - prev_t) * prev_us / tpb / 1e6
        return sec

    tempos = [(t, round(60_000_000 / u, 2)) for t, u in global_tempo]
    result = {"ticks_per_beat": tpb, "tracks": {},
              "_ticks_to_sec": ticks_to_sec}
    for track in mid.tracks:
        name = ""
        for msg in track:
            if msg.type == "track_name":
                name = msg.name.strip()
                break
        if name.startswith("PART ") and name in INSTRUMENT_TRACKS:
            result["tracks"][name] = analyze_track(track, tpb,
                                                   ticks_to_sec=ticks_to_sec)
        elif name in ("PART VOCALS", "HARM1"):
            result["tracks"][name] = analyze_vocals(track)
    result["tempo_changes"] = tempos[:10]
    if tempos:
        bps = [b for _, b in tempos]
        result["bpm_min"] = min(bps)
        result["bpm_max"] = max(bps)
    return result


def diff_official_vs_ours(off: dict, ours: dict) -> dict:
    """Per instrument/difficulty: our note count vs official's."""
    out = {}
    for inst in set(off["tracks"]) | set(ours["tracks"]):
        o = off["tracks"].get(inst, {})
        m = ours["tracks"].get(inst, {})
        row = {}
        for diff in ("expert", "hard", "medium", "easy"):
            od = o.get("difficulties", {}).get(diff)
            md = m.get("difficulties", {}).get(diff)
            row[diff] = {
                "official": od["notes"] if od else 0,
                "ours": md["notes"] if md else 0,
                "ratio": round(md["notes"] / od["notes"], 2)
                if od and od["notes"] and md else None,
            }
        out[inst] = row
    return out


def align_expert(off: dict, ours: dict, tol_s: float = 0.15) -> dict:
    """Note-level alignment of the EXPERT charts (the accuracy loop's core
    metric): recall = official notes we also chart (within tol_s), precision
    = our notes that match an official note, lane agreement on matches."""
    out = {}
    for inst in ("PART GUITAR", "PART BASS", "PART DRUMS"):
        off_tr = off["tracks"].get(inst, {}).get("difficulties", {}).get("expert")
        our_tr = ours["tracks"].get(inst, {}).get("difficulties", {}).get("expert")
        if not off_tr or not our_tr:
            continue
        off_times = off_tr.get("_gem_times") or []
        our_times = our_tr.get("_gem_times") or []
        if not off_times or not our_times:
            out[inst] = {"error": "no gem times captured"}
            continue
        # greedy two-pointer matching on sorted times
        off_times = sorted(off_times)
        our_times = sorted(our_times)
        matched = 0
        j = 0
        lane_matches = 0
        for t, lane in off_times:
            # advance j to first candidate within window
            while j < len(our_times) and our_times[j][0] < t - tol_s:
                j += 1
            if j < len(our_times) and our_times[j][0] <= t + tol_s:
                matched += 1
                if our_times[j][1] == lane:
                    lane_matches += 1
                j += 1
        recall = matched / len(off_times)
        precision = matched / len(our_times)
        out[inst] = {
            "official": len(off_times), "ours": len(our_times),
            "matched": matched, "recall": round(recall, 3),
            "precision": round(precision, 3),
            "f1": round(2 * precision * recall / (precision + recall), 3)
            if precision + recall else 0.0,
            "lane_agreement": round(lane_matches / matched, 3) if matched else 0.0,
            "tolerance_s": tol_s,
        }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["analyze", "diff", "align"])
    ap.add_argument("midi", type=Path)
    ap.add_argument("midi2", type=Path, nargs="?")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()

    data = load_track_events(a.midi)
    if a.mode == "analyze":
        report = data
        print(f"ticks/beat={data['ticks_per_beat']} "
              f"bpm={data.get('bpm_min')}-{data.get('bpm_max')}")
        for name, tr in data["tracks"].items():
            print(f"\n== {name}")
            if "difficulties" in tr:
                for diff, d in sorted(tr["difficulties"].items(),
                                      key=lambda kv: -kv[1]["notes"]):
                    print(f"   {diff:>6}: {d['notes']:5d} notes "
                          f"chords={d['chords']} ({d['chord_rate']:.0%}) "
                          f"lanes={d['lanes']} sustain={d['sustain_ticks']}")
                if tr.get("markers"):
                    print(f"   markers: {tr['markers']}")
            else:
                print(f"   {tr}")
    else:
        if not a.midi2:
            ap.error("diff/align need a second MIDI")
        ours = load_track_events(a.midi2)
        if a.mode == "diff":
            report = diff_official_vs_ours(data, ours)
            print(f"{'instrument':<14}{'difficulty':<10}{'official':>9}{'ours':>8}  ratio")
            for inst, row in report.items():
                for diff, d in row.items():
                    r = f"{d['ratio']:.2f}" if d["ratio"] else "-"
                    print(f"{inst:<14}{diff:<10}{d['official']:>9}{d['ours']:>8}  {r}")
        else:
            report = align_expert(data, ours)
            print(f"{'instrument':<14}{'recall':>7}{'prec':>7}{'f1':>7}{'lanes':>7}   (official vs ours, expert)")
            for inst, r in report.items():
                if "error" in r:
                    print(f"{inst:<14}  ERROR: {r['error']}")
                    continue
                print(f"{inst:<14}{r['recall']:>7.3f}{r['precision']:>7.3f}"
                      f"{r['f1']:>7.3f}{r['lane_agreement']:>7.3f}"
                      f"   {r['official']} vs {r['ours']} matched {r['matched']}")
    if a.json:
        # strip the bulky per-gem times before writing
        import copy
        slim = copy.deepcopy(report)
        tracks = slim.get("tracks", {}) if isinstance(slim, dict) else {}
        for tr in tracks.values():
            for d in (tr.get("difficulties") or {}).values():
                d.pop("_gem_times", None)
        a.json.write_text(json.dumps(slim, indent=1, default=str))
        print(f"\nreport: {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
