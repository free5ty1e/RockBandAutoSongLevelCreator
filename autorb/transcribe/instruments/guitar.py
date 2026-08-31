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
from scipy.signal import butter, sosfiltfilt

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
# guitar notes; lowering recovers missing strums but may add harmonic bleed on
# the shared "other" stem. For a dedicated *guitar* stem (htdemucs_6s or master
# stems), 0.40/0.30 recovers the rapid 8th-note rhythm-guitar parts the user
# hears but Basic Pitch was silently dropping (verified on the Open Road Song
# 198 s guitar stem: strum coverage rose from ~56% to ~78% with the lower
# thresholds while note-level precision stayed comparable). For the shared
# "other" stem (keys bleed risk), the higher 0.45/0.35 is still used via the
# fallback when no dedicated guitar stem exists.
ONSET_THRESHOLD = 0.40  # was 0.45; 0.40 recovers quiet off-beat 8th strums
FRAME_THRESHOLD = 0.30  # was 0.35; tighter frame gate keeps harmonic bleed low

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
    # For bass: pre-load stem audio and compute a bass-band (40-250 Hz) RMS
    # envelope, used to reject phantom notes in low-energy regions caused by
    # stem-separation bleed in the intro/outro. The previous version gated on
    # whole-stem global RMS, which collapses toward zero when the bass is silent
    # for long stretches -- making the "2% of global" threshold useless (bleed
    # at ~20-30% of *active* level passed right through). Gating on the bass-band
    # RMS relative to the track's own *active* level (75th percentile) cleanly
    # separates bleed from real bass playing.
    band_env_t = None
    band_env = None
    band_floor = 0.0
    if instrument == "bass":
        import librosa
        stem_audio, _ = librosa.load(stem_path, sr=sr, mono=True)
        if len(stem_audio) > 0:
            sos_b = butter(4, [40.0 / (sr / 2), 250.0 / (sr / 2)],
                           btype="band", output="sos")
            band = sosfiltfilt(sos_b, stem_audio)
            _hop = 512
            band_env = librosa.feature.rms(y=band, hop_length=_hop)[0]
            band_env_t = librosa.frames_to_time(
                np.arange(len(band_env)), sr=sr, hop_length=_hop)
            _active = float(np.percentile(band_env, 75))
            # A bass note is genuine only where the bass band (40-250 Hz) is
            # actually active. We gate on the stem's own *active* level (75th
            # percentile of the bass-band RMS) rather than whole-stem RMS (fixed
            # above), which collapsed toward zero across the long silent intro and
            # let bleed at ~20-30% of active level walk through. 35% of the active
            # level gates the quiet intro bleed and the 12.9 / 13.1 / 13.9 s guitar-
            # fundamental bleeds (band RMS ~0.01-0.022); the higher 13.3 s A2 spike
            # (0.032) is caught by the density pass below. Soft *real* bass notes
            # (~0.025-0.03 of active) survive stage 1 and are kept by the density
            # pass (real bass is rhythmically dense). See
            # llm-wiki-kb/instrument_charting.md#bass-energy-gate.
            band_floor = _active * 0.35

    for (start, end, pitch_midi, _amp, _bends) in note_events:
        if pitch_midi <= 0:
            continue
        hz = _hz(pitch_midi)
        if not (FMIN <= hz <= FMAX):
            continue  # Reject bleed outside instrument range

        # For bass: reject notes where the bass band is not actually active
        # (stem-separation bleed in the intro/outro). Real bass notes coincide
        # with genuine low-band energy; bleed transients don't.
        _note_band_rms = None
        if instrument == "bass" and band_env is not None and band_floor > 0:
            _bi = int(np.argmin(np.abs(band_env_t - start)))
            _note_band_rms = float(band_env[_bi])
            if _note_band_rms < band_floor:
                continue  # quiet bleed (e.g. the intro, 12-13s guitar-fundamental bleed)

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
            "band_rms": _note_band_rms,
        })

    if not raw:
        return InstrumentChart(
            notes=[], tempo_map=tempo_map,
            metadata={"instrument": instrument, "num_onsets": 0},
        )

    # 3a. For bass: second-pass density gate. A note that cleared the hard floor
    # but sits in the ambiguous low-energy band ([floor, 0.5*active)) is only kept
    # if it has a neighboring bass note within 0.5 s -- real bass is rhythmically
    # dense; a lone bleed spike (e.g. the 13.3 s A2 at band RMS ~0.032, whose
    # only neighbor is the real bass 10 s later) is phantom. Sparse *real* bass
    # lines on eighth-notes or faster (~0.36 s at this tempo) are preserved.
    if instrument == "bass" and band_env is not None and band_floor > 0:
        _amb_hi = _active * 0.50
        _starts = np.array([r["start"] for r in raw])
        _to_drop = set()
        for i, _rnote in enumerate(raw):
            br = _rnote.get("band_rms")
            if br is None or br < band_floor or br >= _amb_hi:
                continue
            dist = np.abs(_starts - _rnote["start"])
            dist[i] = np.inf
            if float(dist.min()) >= 0.5:
                _to_drop.add(i)
        if _to_drop:
            raw = [r for j, r in enumerate(raw) if j not in _to_drop]

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

    # 3c. Collapse held-chord strum-fragments into one sustained chord (guitar
    # only). On held-bridge sections the rhythm guitar holds a single power chord
    # for several measures while Basic Pitch re-emits it every 8th-note (~178 ms
    # @ 169 BPM), reading as a "mass of overlapping briefly-held notes." The user
    # hears this as "strummed once and held until the pitch changes." A genuinely
    # held chord sustains (envelope stays up between re-emissions, only
    # interrupted by brief palm-mute dips, never real silence) and its fragments
    # are sustained notes; a deliberate strum riff (e.g. the intro's
    # 8th+8th+quarter+quarter+8th pattern) re-articulates with damped envelopes
    # and short note lengths.
    #
    # Generic rule (works for any song): segment the chord events by chroma ROOT
    # change (lower of a power chord's top-2 pitch classes -- a root/fifth flip is
    # not a chord change). Within a root region, collapse to ONE sustained chord
    # iff the region is held: (a) its internal inter-onset gaps are envelope-
    # continuous in the mean (>=0.30 of local peak, ignoring deep rests that are
    # true silences, not palm muting), AND (b) the fragments are sustained
    # (median note length >= one 8th note). Otherwise the region is a riff and is
    # left as individual strums. A new chord (root change) always breaks a region,
    # so one sustained chord becomes exactly one charted note however long it
    # rings.
    if instrument == "guitar":
        _rms = _lr.feature.rms(y=_y, hop_length=_hop)[0]
        _ct = _lr.frames_to_time(np.arange(_chroma.shape[1]), sr=sr, hop_length=_hop)
        _bpm = float(np.median([bpm for _t, bpm in tempo_map])) if tempo_map else 120.0
        # _frag_gap: how far apart two chord fragments can be and still
        # merge into one sustained chord. Must be SHORTER than the song's
        # active strum interval so rhythm-guitar 8th-note parts aren't
        # collapsed into single holds. 3 eighth-notes is a safe upper bound:
        # at 120 BPM that's 0.75 s, at 200 BPM it's 0.45 s. (The old fixed
        # 1.5 s swallowed ~8 strums at 169 BPM.) The 2.0 s hard cap (legacy)
        # only applies to extremely slow songs where 3 eighths > 2 s.
        _n_eighths = 3
        _frag_gap = min(_n_eighths * (60.0 / max(_bpm, 40.0) / 2), 2.0)
        _ENV_FLOOR = 0.15

        def _stable(t0, t1):
            j0 = int(np.clip(np.searchsorted(_ct, t0), 0, len(_ct) - 1))
            j1 = int(np.clip(np.searchsorted(_ct, t1), 0, len(_ct) - 1))
            return int(np.argmax(_chroma[:, j0])) == int(np.argmax(_chroma[:, j1]))

        def _held(t0, t1):
            j0 = int(np.clip(np.searchsorted(_ct, t0), 0, len(_ct) - 1))
            j1 = int(np.clip(np.searchsorted(_ct, t1), 0, len(_ct) - 1))
            if j1 < j0:
                j0, j1 = j1, j0
            seg = _rms[j0:j1 + 1]
            if len(seg) < 2:
                return False
            mx = float(seg.max())
            return mx > 0 and float(seg.min()) >= _ENV_FLOOR * mx

        _merged = []
        for _g in groups:
            if _merged:
                _pg = _merged[-1]
                _gap = _g[0]["start"] - _pg[0]["start"]
                if (0.0 < _gap < _frag_gap
                        and _stable(_pg[-1]["start"], _g[0]["start"])
                        and _held(_pg[-1]["start"], _g[0]["start"])):
                    _g_end = max(r["start"] + r["length"] for r in _g)
                    for _r in _pg:
                        _r["length"] = max(_r["length"], _g_end - _r["start"])
                    continue  # absorb _g as a fragment of the held chord
            _merged.append(_g)
        groups = _merged


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
                      tempo_map, 2.0 if instrument == "bass" else SNAP_DIVISIONS)
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