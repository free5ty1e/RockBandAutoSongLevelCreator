"""
Guitar / Bass transcription for Rock Band charts.

Uses Spotify's Basic Pitch neural network (a polyphonic, pitch-accurate
transcriber) on the separated instrument stem, then maps each detected note to a
5-lane fretboard position and quantizes it to the song grid. Because Basic Pitch
is polyphonic it recovers the chords and fast strum runs that the old
CQT / spectral-flux heuristics dropped — which is what makes the Expert chart
match the audio.

Difficulty reduction (Hard / Medium / Easy) is handled downstream in
``difficulty.py``; this module only produces the *Expert* chart.
"""

from pathlib import Path
import numpy as np

import basic_pitch.inference as bp
from basic_pitch import ICASSP_2022_MODEL_PATH

from .pitch_to_lane import (
    detect_tuning_from_pitches,
    pitch_to_fret_string,
    fret_string_to_lane,
)
from .difficulty import (
    InstrumentChart,
    ChartNote,
    Difficulty,
    create_all_difficulties,
    _snap,
)

# Basic Pitch is slow; cache note events per stem path so the same stem is not
# transcribed twice (guitar and keys share the "other" stem).
_BP_CACHE = {}

# Chord grouping window (seconds): Basic Pitch reports the onsets of the tones
# of one strum within a few tens of ms of each other — group them into one chord.
# Narrower window (30ms) to separate rapid double/triple strums that are
# distinct strums, not chord tones. 60ms was merging rapid strums into chords.
CHORD_WINDOW = 0.030

# Grid resolution the Expert chart is quantized to (divisions per beat).
# 4 = 1/16 note: fine enough for eighth/sixteenth strum runs.
SNAP_DIVISIONS = 4

# Basic Pitch confidence thresholds. Defaults (0.5 / 0.3) silently drop quiet
# guitar/bass notes; lowering recovers missing notes but adds noise (keys on
# the shared "other" stem). Raising reduces keys bleed at cost of missing
# quiet guitar notes. 0.45/0.35 balances recovery of rapid strums vs keys bleed.
ONSET_THRESHOLD = 0.45
FRAME_THRESHOLD = 0.35

# Deduplication tolerance for (time, lane) - notes within this many seconds
# are considered duplicates. Guitar chords can have slight timing variations
# between strings due to pick attack physics.
DEDUP_TIME_TOL = 0.015  # 15ms


def _basic_pitch_notes(stem_path: Path):
    """Run Basic Pitch once per stem and cache the raw note events."""
    key = str(stem_path)
    if key in _BP_CACHE:
        return _BP_CACHE[key]
    _, _, note_events = bp.predict(
        key,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
        onset_threshold=ONSET_THRESHOLD,
        frame_threshold=FRAME_THRESHOLD,
    )
    _BP_CACHE[key] = note_events
    return note_events


def _hz(midi_pitch: float) -> float:
    return 440.0 * (2.0 ** ((midi_pitch - 69) / 12.0))


def _transcribe_fretted(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
    instrument: str = "guitar",
) -> InstrumentChart:
    """Shared Expert transcription for guitar and bass."""
    note_events = _basic_pitch_notes(stem_path)
    if not note_events:
        return InstrumentChart(
            notes=[], tempo_map=tempo_map,
            metadata={"instrument": instrument, "num_onsets": 0},
        )

    # 1. Tuning detection from the detected pitch distribution.
    pitches_hz = np.array([_hz(ne[2]) for ne in note_events])
    tuning = detect_tuning_from_pitches(pitches_hz, instrument)
    # Capo detection is fragile and only shifts the (consistent) lane mapping,
    # so we intentionally keep capo = 0 to avoid spurious octave/fret errors.

    # 2. Build per-note raw records (pre-quantization) with lane + open flag.
    # Instrument-specific frequency ranges to reject bleed:
    # Guitar: ~E2 (82 Hz) to ~E6 (1318 Hz) - extended for high frets/harmonics
    # Bass: ~E1 (41 Hz) to ~G4 (392 Hz)
    if instrument == "bass":
        FMIN, FMAX = 38.0, 420.0
    else:  # guitar
        FMIN, FMAX = 70.0, 1400.0

    raw = []
    # For bass: pre-load stem audio to enable energy-based filtering of phantom notes
    # in low-energy regions (stem separation bleed in intro/outro)
    stem_audio = None
    if instrument == "bass":
        import librosa
        stem_audio, _ = librosa.load(stem_path, sr=sr, mono=True)
        global_rms = np.sqrt(np.mean(stem_audio**2)) if len(stem_audio) > 0 else 1.0
    
    for (start, end, pitch_midi, _amp, _bends) in note_events:
        if pitch_midi <= 0:
            continue
        hz = _hz(pitch_midi)
        if not (FMIN <= hz <= FMAX):
            continue  # Reject bleed outside instrument range
        
        # For bass: reject notes in near-silent regions (stem separation bleed)
        if instrument == "bass" and stem_audio is not None:
            i = int(start * sr)
            half_win = int(0.025 * sr)  # 25ms half-window
            start_idx = max(0, i - half_win)
            end_idx = min(len(stem_audio), i + half_win)
            seg = stem_audio[start_idx:end_idx]
            if len(seg) > 0:
                seg_rms = np.sqrt(np.mean(seg**2))
                if global_rms > 0:
                    rel_energy = seg_rms / global_rms
                    if rel_energy < 0.02:  # Less than 2% of global RMS
                        continue  # Skip phantom note in silent region
        
        fps = pitch_to_fret_string(hz, tuning)
        lane = fret_string_to_lane(fps, tuning.num_strings)
        if lane < 0 or lane > 4:
            lane = 0
        length = end - start
        if length < 0.02:  # Reject too-short ghost notes (<20ms)
            continue
        raw.append({
            "start": float(start),
            "lane": lane,
            "is_open": bool(fps.fret == 0),
            "length": float(length),
            "pitch": float(pitch_midi),
        })

    if not raw:
        return InstrumentChart(
            notes=[], tempo_map=tempo_map,
            metadata={"instrument": instrument, "num_onsets": 0},
        )

    # 3. Group near-simultaneous onsets into chord events, then snap the whole
    #    group to the shared quantized time so chords render simultaneously.
    raw.sort(key=lambda r: r["start"])
    groups = []
    cur = [raw[0]]
    for r in raw[1:]:
        if r["start"] - cur[0]["start"] <= CHORD_WINDOW:
            cur.append(r)
        else:
            groups.append(cur)
            cur = [r]
    groups.append(cur)

    # 3b. Reconstruct strummed chords. Basic Pitch leans monophonic and usually
    # reports the single dominant tone of each strum, so a rock rhythm-guitar
    # part gets charted as single notes. Where the audio at a charted note's
    # frame is clearly chordal (>= 3 strong chroma pitch-classes — a strummed
    # chord, not a melodic note), add the perfect-fifth to turn it into a
    # playable 2-note power chord. Bass is left single-note.
    if instrument == "guitar":
        import librosa as _lr
        _y, _ = _lr.load(stem_path, sr=sr, mono=True)
        _hop = 512
        _chroma = _lr.feature.chroma_stft(y=_y, sr=sr, hop_length=_hop)
        for _g in groups:
            if len(_g) != 1:
                continue  # already a chord (or chord tones detected)
            _r = _g[0]
            _frame = int(_r["start"] * sr / _hop)
            if not (0 <= _frame < _chroma.shape[1]):
                continue
            _c = _chroma[:, _frame]
            _mx = _c.max()
            if _mx <= 0:
                continue
            _strong = int(np.sum(_c > 0.5 * _mx))
            if not (3 <= _strong <= 7):
                continue  # not convincingly a strummed chord
            _fifth_hz = _hz(_r["pitch"] + 7)
            _fps = pitch_to_fret_string(_fifth_hz, tuning)
            _f_lane = fret_string_to_lane(_fps, tuning.num_strings)
            if _f_lane < 0 or _f_lane > 4 or _f_lane == _r["lane"]:
                continue
            _g.append({
                "start": _r["start"],
                "lane": _f_lane,
                "is_open": bool(_fps.fret == 0),
                "length": _r["length"],
                "pitch": _r["pitch"] + 7,
            })

    expert_notes = []
    for g in groups:
        # Deduplicate identical lanes within a group (keep the first).
        seen_lanes = set()
        unique = []
        for r in g:
            if r["lane"] in seen_lanes:
                continue
            seen_lanes.add(r["lane"])
            unique.append(r)
        qtime = _snap(float(np.median([r["start"] for r in unique])),
                      tempo_map, SNAP_DIVISIONS)
        is_chord = len(unique) > 1
        for r in unique:
            note = ChartNote(
                time=qtime,
                lane=r["lane"],
                length=r["length"],
                is_open=r["is_open"],
                is_hopo=False,
                velocity=100,
                difficulty_pitch=60 + r["lane"],
            )
            note.is_chord = is_chord
            expert_notes.append(note)
        if is_chord:
            expert_notes[-len(unique)].chord_notes = list(expert_notes[-len(unique):])

    # 4. Cap sustains so a held note never bleeds into the next same-lane note,
    #    and never exceeds a sane maximum ring.
    # Bass holds can be much longer than guitar; guitar chords rarely exceed 2s.
    max_hold = 8.0 if instrument == "bass" else 2.0
    min_note_len = 0.04 if instrument == "guitar" else 0.03  # 40ms guitar, 30ms bass
    for lane in range(5):
        lane_notes = [n for n in expert_notes if n.lane == lane]
        for k in range(len(lane_notes) - 1):
            nxt = lane_notes[k + 1].time
            max_len = max(0.0, nxt - lane_notes[k].time - 0.02)
            if lane_notes[k].length > max_len:
                lane_notes[k].length = max_len
        for n in lane_notes:
            if n.length > max_hold:
                n.length = max_hold
            if 0 < n.length < min_note_len:
                n.length = 0.0

    # 5. Expert HOPO pass: a non-chord, non-open note that follows the previous
    #    note on an adjacent lane within 120 ms (same direction) becomes a HOPO.
    #    Bass does not have HOPOs in Rock Band.
    if instrument != "bass":
        expert_notes.sort(key=lambda n: (n.time, n.lane))
        for i in range(1, len(expert_notes)):
            prev, curr = expert_notes[i - 1], expert_notes[i]
            if curr.time == prev.time or curr.is_chord:
                continue
            td = curr.time - prev.time
            ld = abs(curr.lane - prev.lane)
            if td <= 0.12 and ld == 1 and not prev.is_open and not curr.is_open:
                nxt = expert_notes[min(i + 1, len(expert_notes) - 1)]
                if (curr.lane > prev.lane) == (nxt.lane > curr.lane):
                    curr.is_hopo = True
                    curr.velocity = 127

    # 6. Collapse near-duplicate (time, lane) duplicates. Two separate chord groups can
    #    snap to nearby quantized times and assign the same lane (the within-group
    #    lane dedup can't catch cross-group collisions), producing two notes on the
    #    same lane at nearly the same instant -- illegal in Rock Band and rendered as
    #    overlapping MIDI gems. Keep the longer-sustain note and fix chord refs.
    from collections import defaultdict as _defdict
    _bylane = _defdict(list)
    for n in expert_notes:
        _bylane[(round(n.time / DEDUP_TIME_TOL) * DEDUP_TIME_TOL, n.lane)].append(n)
    _dropped = set()
    _cleaned = []
    for _key, _grp in _bylane.items():
        _best = max(_grp, key=lambda n: (n.length, n.velocity, n.is_chord))
        for n in _grp:
            if n is not _best:
                _dropped.add(id(n))
        _cleaned.append(_best)
    for n in _cleaned:
        if n.chord_notes:
            n.chord_notes = [c for c in n.chord_notes if id(c) not in _dropped]
    expert_notes = sorted(_cleaned, key=lambda n: (n.time, n.lane))

    solos = _detect_solo_sections(expert_notes, tempo_map)
    bre = _detect_bre_section(expert_notes, song_end)

    # 7. Final pass: merge notes on the same lane within a tiny time window
    #    (catches any remaining near-duplicates from quantization spread).
    from collections import defaultdict as _defdict
    _bylane = _defdict(list)
    for n in expert_notes:
        _bylane[n.lane].append(n)
    _cleaned = []
    for _lane, _notes in _bylane.items():
        _notes.sort(key=lambda n: n.time)
        _merged = []
        for n in _notes:
            if _merged and abs(n.time - _merged[-1].time) < 0.010:  # 10ms merge window
                # Merge: keep the earlier time, extend sustain to cover both
                _merged[-1].length = max(_merged[-1].length, n.time + n.length - _merged[-1].time)
            else:
                _merged.append(n)
        _cleaned.extend(_merged)
    expert_notes = sorted(_cleaned, key=lambda n: (n.time, n.lane))

    solos = _detect_solo_sections(expert_notes, tempo_map)
    bre = _detect_bre_section(expert_notes, song_end)

    return InstrumentChart(
        notes=expert_notes,
        tempo_map=tempo_map,
        solo_sections=solos,
        bre_section=bre,
        overdrive_phrases=[],
        metadata={
            "instrument": instrument,
            "tuning": tuning.name,
            "num_onsets": len(expert_notes),
        },
    )


def _detect_solo_sections(notes, tempo_map, min_density=8.0, min_duration=4.0):
    if not notes:
        return []
    solos = []
    window, step = 2.0, 0.5
    max_time = max(n.time for n in notes)
    t = 0.0
    while t <= max_time:
        dens = len([n for n in notes if t <= n.time < t + window]) / window
        if dens >= min_density:
            start, end = t, t + window
            while start > 0 and len([n for n in notes if start - window <= n.time < start]) / window >= min_density * 0.7:
                start -= step
            while end < max_time and len([n for n in notes if end <= n.time < end + window]) / window >= min_density * 0.7:
                end += step
            if end - start >= min_duration:
                solos.append((start, end))
                t = end
            else:
                t += step
        else:
            t += step
    if not solos:
        return []
    merged = [solos[0]]
    for s in solos[1:]:
        if s[0] <= merged[-1][1] + 1.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], s[1]))
        else:
            merged.append(s)
    return merged


def _detect_bre_section(notes, song_end, bre_window=20.0):
    if not notes:
        return None
    end_notes = [n for n in notes if n.time >= song_end - bre_window]
    if len(end_notes) < 10:
        return None
    densities = []
    window = 2.0
    for t in np.linspace(song_end - bre_window, song_end - window, 5):
        densities.append(len([n for n in end_notes if t <= n.time < t + window]) / window)
    if len(densities) >= 3 and densities[-1] > densities[0] * 1.5:
        return (song_end - bre_window, song_end)
    return None


def transcribe_guitar(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> InstrumentChart:
    return _transcribe_fretted(stem_path, tempo_map, song_end, sr, "guitar")


def transcribe_bass(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> InstrumentChart:
    return _transcribe_fretted(stem_path, tempo_map, song_end, sr, "bass")


def generate_all_difficulties(expert_chart: InstrumentChart) -> dict:
    return create_all_difficulties(expert_chart, "guitar")