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
# Narrower window (20ms) to separate rapid strums that are distinct, not chord tones.
# 30ms was still merging some fast 8th-note strums at high tempo.
CHORD_WINDOW = 0.020

# Grid resolution the Expert chart is quantized to (divisions per beat).
# 4 = 1/16 note: fine enough for eighth/sixteenth strum runs.
SNAP_DIVISIONS = 4

# Basic Pitch confidence thresholds. For a dedicated *guitar* stem (htdemucs_6s or master
# stems), lower thresholds recover rapid 8th-note rhythm-guitar parts that were
# silently dropped. For the shared "other" stem (keys bleed risk), higher thresholds
# are used via the fallback when no dedicated guitar stem exists.
ONSET_THRESHOLD = 0.35  # was 0.40; lower to catch quiet off-beat 8th strums
FRAME_THRESHOLD = 0.25  # was 0.30; tighter frame gate keeps harmonic bleed low

# Deduplication tolerance for (time, lane) - notes within this many seconds
# are considered duplicates. Guitar chords can have slight timing variations
# between strings due to pick attack physics.
DEDUP_TIME_TOL = 0.010  # 10ms

#: Minimum gap between two DISTINCT strums in the audio strum backbone (s).
#: The backbone is derived from librosa onset detection, de-duplicated at this
#: gap. Below this, re-attacks of one chord are treated as one strum.
MIN_STRUM_GAP = 0.06
#: Onset-strength delta for the strum backbone (calibrated on Open Road Song:
#: 0.08 yields ~698 strums, matching the human-audible count; see
#: tools/guitar_tab_alignment/audio_ground_truth.py).
STRUM_BACKBONE_DELTA = 0.08
#: Hop for the strum backbone onset envelope.
_STRUM_HOP = 256


def _strum_backbone(y: np.ndarray, sr: int) -> np.ndarray:
    """Detect the array of distinct strum onset times in the guitar stem.

    Drives guitar strum timing. This is independent of Basic Pitch's note
    onsets (which over-detect by splitting chord tones into separate onsets)
    and reliably matches the human-audible strum rhythm (~698 strums on Open
    Road Song vs Basic Pitch's ~1814 onsets and a 695-900 strum chart).
    """
    import librosa
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=_STRUM_HOP)
    times = librosa.times_like(oenv, sr=sr, hop_length=_STRUM_HOP)
    onsets = librosa.onset.onset_detect(
        onset_envelope=oenv, sr=sr, hop_length=_STRUM_HOP,
        delta=STRUM_BACKBONE_DELTA, backtrack=True,
    )
    all_att = sorted(float(t) for t in times[onsets])
    kept = []
    for t in all_att:
        if not kept or t - kept[-1] >= MIN_STRUM_GAP:
            kept.append(t)
    return np.array(kept)


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


#: Low-band (root-fundamental) window for per-strum chord-root detection.
#: Power-chord roots live at 82-220 Hz (E2..A3); distorted chords confuse
#: chroma, so the root is read from the low-band spectral peak with a
#: median filter over the strum neighborhood (see _strum_chord_roots).
_ROOT_FMIN = 80.0
_ROOT_FMAX = 230.0


def _strum_chord_roots(y: np.ndarray, sr: int, strum_times: np.ndarray,
                       n_fft: int = 8192) -> np.ndarray:
    """Per-strum chord-root MIDI pitch, median-filtered for stability.

    For each strum, window the first ~300 ms (attack + early ring), FFT with
    zero-padding, and take the strongest peak in the root band
    (``_ROOT_FMIN``..``_ROOT_FMAX``). A single window is still jittery on
    distorted power chords (adjacent-bin competition), so the raw sequence is
    median-filtered over a 5-strum window: a real chord change persists across
    several strums, while single-window outliers do not.

    Returns an array of MIDI pitches (float), same length as ``strum_times``.
    """
    roots = np.zeros(len(strum_times), dtype=float)
    win = int(0.30 * sr)
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    band = (freqs >= _ROOT_FMIN) & (freqs <= _ROOT_FMAX)
    for i, t in enumerate(strum_times):
        i0 = int(t * sr)
        seg = y[i0:i0 + win]
        if len(seg) < 1024:
            roots[i] = 0.0
            continue
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=n_fft))
        if not spec[band].any():
            roots[i] = 0.0
            continue
        f_peak = float(freqs[band][np.argmax(spec[band])])
        roots[i] = 69.0 + 12.0 * np.log2(f_peak / 440.0)
    # Median filter over 5 strums (odd window; chord changes persist, jitter
    # does not). Zero (undetectable) entries do not participate.
    from scipy.signal import medfilt
    from collections import Counter as _Counter
    out = roots.copy()
    if len(roots) >= 5:
        # Replace zeros with the nearest nonzero so the filter isn't dragged
        # to 0 by undetectable strums.
        nz = roots[roots > 0]
        fill = float(np.median(nz)) if len(nz) else 0.0
        filled = np.where(roots > 0, roots, fill)
        # MODE over a sliding 5-strum window (rounded to semitones): two nearby
        # FFT peaks trading dominance across windows (bin competition on
        # distorted chords) produces an alternating 113/129 Hz pattern that a
        # MEDIAN preserves (the alternation is symmetric) but the MODE
        # correctly resolves to the level that dominates the chord run.
        rounded = np.round(filled)
        for i in range(len(rounded)):
            lo = max(0, i - 2)
            hi = min(len(rounded), i + 3)
            win = rounded[lo:hi]
            out[i] = float(_Counter(win.tolist()).most_common(1)[0][0])
    return out


def _grid_phase(strum_times: np.ndarray, tempo_map: list,
                divisions: int = 2) -> float:
    """Estimate the grid phase (in beats) that best aligns the strums.

    The drum-derived tempo map's beat phase does not necessarily match the
    guitar's strum placement (the guitar may enter offbeat); snapping strums
    onto the raw grid then produces systematically misplaced gems ("phantom
    strums"). This finds the phase offset (in fractions of one grid step)
    minimizing the strums' mean distance to the grid.

    Returns the phase in BEATS (add to strum positions before snapping).
    """
    if len(strum_times) < 4 or not tempo_map:
        return 0.0
    beats = np.array([float(t) for t, _ in tempo_map])
    step = 1.0 / divisions
    best_phase, best_err = 0.0, np.inf
    # Scan at 32nd-note resolution within one grid step (the guitar's
    # downbeat placement can be anywhere within the step; a coarse scan
    # quantizes the phase to the scan grid and leaves residual error).
    for k in range(divisions * 8):  # 32nd-resolution phase scan
        ph = k * step / 8.0
        err = 0.0
        for t in strum_times:
            bi = int(np.searchsorted(beats, t)) - 1
            bi = max(0, min(bi, len(beats) - 2))
            b0, b1 = beats[bi], beats[bi + 1]
            pos = bi + (t - b0) / (b1 - b0) + ph
            r = (pos * divisions) % 1.0
            err += min(r / divisions, (1 - r) / divisions)
        err /= len(strum_times)
        if err < best_err:
            best_err, best_phase = err, ph
    return best_phase


def _snap_to_grid_phased(t: float, tempo_map: list, divisions: int,
                         phase_beats: float) -> float:
    """Snap ``t`` onto the ``divisions``-per-beat grid with a phase offset.

    Works before the first beat too: grid positions <= 0 extrapolate from
    the first beat interval, so intro strums that precede beat 0 snap to the
    grid point they are actually nearest (the old version pushed everything
    forward into the grid and collapsed pre-beat strums).
    """
    if not tempo_map:
        return t
    beats = np.array([float(t2) for t2, _ in tempo_map])
    bi = int(np.searchsorted(beats, t)) - 1
    bi = max(0, min(bi, len(beats) - 2))
    b0, b1 = beats[bi], beats[bi + 1]
    pos = bi + (t - b0) / (b1 - b0) + phase_beats
    step = 1.0 / divisions
    snapped_pos = round(pos / step) * step
    # back-convert grid position to seconds (extrapolate before beat 0)
    i = int(np.floor(snapped_pos))
    frac = snapped_pos - i
    if i < 0:
        # extrapolate backwards using the first beat interval
        b0, b1 = beats[0], beats[1]
        return b0 + frac * (b1 - b0) + i * (b1 - b0)
    i = min(i, len(beats) - 2)
    b0, b1 = beats[i], beats[i + 1]
    return b0 + frac * (b1 - b0)


def _detect_solo_regions(y: np.ndarray, sr: int,
                         strums: np.ndarray,
                         min_duration: float = 4.0,
                         window: float = 3.0) -> list:
    """Detect lead-guitar solo regions from the stem's register energy.

    During a lead solo the RHYTHM guitar usually keeps playing underneath
    (verified on Open Road Song at ~97 s: the low-band chord roots stay
    steady, std ~1.6 semitones, while the solo soars above), so a root-
    contour detector cannot see it. The reliable signature is REGISTER
    ENERGY: solo sections show the high band (lead register, ~600-1600 Hz)
    dominating the low chord band (80-230 Hz) — measured ratio ~2.4-2.8
    during the Open Road Song solo vs ~0.3-0.7 during rhythm chugging.

    A window is marked solo when the high/low RMS ratio >= 1.5 for a
    sustained run (>= min_duration). Windows step at window/2.

    Returns [(start_s, end_s), ...].
    """
    if len(strums) < 8:
        return []
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2.0
    sos_lo = butter(4, [80.0 / nyq, 230.0 / nyq], btype='band', output='sos')
    sos_hi = butter(4, [600.0 / nyq, 1600.0 / nyq], btype='band', output='sos')
    y_lo = sosfiltfilt(sos_lo, y)
    y_hi = sosfiltfilt(sos_hi, y)

    solo_mask = np.zeros(len(strums), dtype=bool)
    step = window / 2.0
    t = 0.0
    last = float(strums[-1]) if len(strums) else 0.0
    while t < last:
        i0, i1 = int(t * sr), int((t + window) * sr)
        lo = float(np.sqrt(np.mean(y_lo[i0:i1] ** 2))) if i1 <= len(y_lo) else 0.0
        hi = float(np.sqrt(np.mean(y_hi[i0:i1] ** 2))) if i1 <= len(y_hi) else 0.0
        if lo > 1e-6 and hi / lo >= 1.5:
            sel = (strums >= t) & (strums < t + window)
            solo_mask |= sel
        t += step
    idx = np.where(solo_mask)[0]
    if len(idx) == 0:
        return []
    # Expand marked strums into contiguous regions (gaps > 1.5 s split).
    regions = []
    start = strums[idx[0]]
    prev_end = strums[idx[0]]
    for a, b in zip(idx[:-1], idx[1:]):
        if strums[b] - strums[b - 1] > 1.5:
            regions.append((float(start), float(prev_end)))
            start = strums[b]
        prev_end = strums[b]
    regions.append((float(start), float(prev_end)))
    merged = []
    for r in regions:
        if merged and r[0] - merged[-1][1] < 1.0:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(list(r))
    return [(float(a), float(b)) for a, b in merged if b - a >= min_duration]


def _note_pitch_at(y: np.ndarray, sr: int, t: float,
                    fmin: float = 200.0, fmax: float = 1600.0):
    """Dominant pitch (Hz) of a lead note at time ``t`` (pyin over 150 ms).

    Lead/solo guitar is typically single-line above the chord band, where pyin
    is reliable (it fails on polyphonic distorted chords — which is why the
    rhythm path reads roots from the low-band FFT instead).
    """
    import librosa as _lr
    i = int(t * sr)
    seg = y[max(0, i): i + int(0.15 * sr)]
    if len(seg) < int(0.10 * sr):
        return None
    f0, _, v = _lr.pyin(seg, fmin=fmin, fmax=fmax, sr=sr,
                        frame_length=1024, hop_length=256)
    voiced = f0[(v >= 0.4) & (f0 > 0)]
    return float(np.median(voiced)) if len(voiced) else None


def _transcribe_guitar_rhythm(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
    solo_charting: bool = False,
) -> InstrumentChart:
    """Rhythm-guitar Expert chart driven by the audio strum backbone.

    Design (validated against the Open Road Song tab — palm-muted power chords
    on straight 8ths; and the user's ear: the intro is a regular, repeating
    strum cell):

    1. **Strums from the audio** (``_strum_backbone``): one charted attack per
       audible strum. No Basic-Pitch onset is trusted for timing (it splits
       chord tones into spurious onsets).
    2. **Grid-aligned with local phase** (``_grid_phase``): every strum snaps
       onto the 1/8 tempo grid at the phase the guitar actually plays, so the
       charted rhythm is a clean 8th-note pulse like the tab.
    3. **Lane from the chord root** (``_strum_chord_roots``): each strum's
       low-band root maps to a fret position; lane rises/falls with pitch, so
       chord changes (A5->B5) move the chart up/down like the tab.
    4. **Power chords**: root lane + fifth lane (2-note chord), matching the
       tab's 5th shapes. Sustain runs until the next strum (capped at 2 s).

    With ``solo_charting=True``, detected lead-solo regions
    (``_detect_solo_regions``) are charted as SINGLE notes whose lane follows
    the lead pitch contour (``_note_pitch_at`` pyin) instead of the rhythm
    power chords underneath.
    """
    import librosa as _lr
    from .difficulty import ChartNote, _snap

    y, _ = _lr.load(stem_path, sr=sr, mono=True)
    strums = _strum_backbone(y, sr)
    strums = np.array([s for s in strums if 0 <= s <= song_end])
    if len(strums) == 0:
        return InstrumentChart(
            notes=[], tempo_map=tempo_map,
            metadata={"instrument": "guitar", "num_onsets": 0},
        )

    # 2. grid phase + snap
    phase = _grid_phase(strums, tempo_map, divisions=2)
    snapped = [_snap_to_grid_phased(float(s), tempo_map, 2, phase)
               for s in strums]
    # de-duplicate strums that snapped onto the same grid slot: keep the
    # earliest raw strum per slot (two chord-tone onsets inside one strum
    # sometimes survive the 60 ms backbone dedup; the chart must have ONE
    # gem per grid slot). Threshold = 60% of one eighth note at the local
    # tempo (snapped slots are exactly an eighth apart when distinct).
    _eighth = 60.0 / (float(np.median([b for _, b in tempo_map])) or 120.0) / 2.0 \
        if tempo_map else 0.25
    dedup = []
    for s in snapped:
        if not dedup or s - dedup[-1] >= 0.6 * _eighth:
            dedup.append(s)
    snapped = dedup
    strums = np.array(snapped)

    # 3. chord roots per strum (median-filtered)
    roots = _strum_chord_roots(y, sr, strums)

    # Map roots to lanes MONOTONICALLY in pitch. The old
    # pitch_to_fret_string->fret_string_to_lane chain maps via fret%5, which is
    # cyclic (midi 43->lane 2, 45->open(-1), 47->lane 1, 50->lane 4, 52->lane
    # 1) — a rising chord root can move the lane DOWN, which reads as "the
    # chart doesn't follow the pitch". A rhythm chart needs the gem to track
    # the root's pitch movement (user requirement; also how official charts
    # feel).
    #
    # Rank-based mapping: rock rhythm parts use a SMALL set of chord roots
    # (e.g. A/B/D/E). Clustering roots into distinct levels (1-semitone
    # tolerance) and spreading the levels evenly across lanes 0-4 makes every
    # root change visible as a lane change, while preserving order (a higher
    # root always maps to a higher-or-equal lane, never lower).
    _valid_roots = np.array([r for r in roots if r > 0])
    if len(_valid_roots) == 0:
        return InstrumentChart(
            notes=[], tempo_map=tempo_map,
            metadata={"instrument": "guitar", "num_onsets": 0},
        )
    # Cluster distinct root levels (1-semitone bins over the observed range).
    _lvl = np.sort(_valid_roots)
    _levels = []
    for r in _lvl:
        if not _levels or r - _levels[-1] > 1.0:
            _levels.append(float(r))
    # Cap at 5 levels (5 lanes); if more, merge by k-means-free even binning.
    if len(_levels) > 5:
        # keep the 5 most-population-dense levels? Simpler: evenly spaced
        # quantiles of the observed roots.
        _levels = [float(v) for v in np.quantile(_valid_roots, [0.1, 0.3, 0.5, 0.7, 0.9])]
        _levels = sorted(set(_levels))
    _levels = np.array(_levels)

    def _root_to_lane(root_midi: float) -> int:
        """Monotonic rank map: root level index spread over lanes 0-4."""
        # nearest level
        li = int(np.argmin(np.abs(_levels - root_midi)))
        frac = li / max(len(_levels) - 1, 1)
        return int(np.clip(round(frac * 4.0), 0, 4))

    # --- Solo detection (lead vs. rhythm). Always computed (the regions are
    # also chart solo_sections metadata); with solo_charting=True the strums
    # INSIDE a solo region are charted as single lead notes following the
    # pyin pitch contour instead of the rhythm power chord.
    solo_regions = _detect_solo_regions(y, sr, strums)

    def _in_solo(t: float) -> bool:
        return any(a <= t <= b for a, b in solo_regions)

    expert_notes = []
    for s, root in zip(strums, roots):
        if root <= 0:
            continue
        if solo_charting and _in_solo(s):
            # Lead note: lane follows the soloist's melodic pitch (pyin in the
            # lead register). Falls back to the root lane when pyin fails.
            hz = _note_pitch_at(y, sr, s)
            lane = None
            if hz:
                lead_midi = 69.0 + 12.0 * np.log2(hz / 440.0)
                # rank the lead pitch against the song's chord levels for
                # consistency, then clamp: leads sit above the chords, so a
                # lead at/below the highest chord level maps to the top lane.
                if lead_midi > _levels[-1]:
                    frac = min(1.0, (lead_midi - _levels[0]) /
                               max(_levels[-1] - _levels[0], 1.0))
                    lane = int(np.clip(round(frac * 4.0), 0, 4))
                else:
                    lane = 4  # lead inside/below the chord band: top lane
            if lane is None:
                lane = _root_to_lane(root)
            expert_notes.append({
                "time": float(s), "lanes": [lane], "root": float(root),
            })
            continue
        lane = _root_to_lane(root)
        # power chord: root lane + the fifth above (clamped to the highway)
        lane5 = min(4, lane + 2)
        if lane5 == lane:
            lanes = [lane]
        else:
            lanes = sorted([lane, lane5])
        expert_notes.append({
            "time": float(s), "lanes": lanes, "root": float(root),
        })

    # 4. build ChartNotes: sustain to next strum (cap 2 s), power chords as
    # 2-lane chords with is_chord linkage.
    notes = []
    for k, rec in enumerate(expert_notes):
        t = rec["time"]
        lanes = rec["lanes"]
        nxt = expert_notes[k + 1]["time"] if k + 1 < len(expert_notes) else song_end
        length = float(np.clip(nxt - t - 0.02, 0.08, 2.0))
        chord = len(lanes) > 1
        members = []
        for lane in lanes:
            n = ChartNote(
                time=t, lane=lane, length=length,
                is_open=False, is_hopo=False, velocity=100,
                difficulty_pitch=60 + lane,
            )
            n.is_chord = chord
            members.append(n)
            notes.append(n)
        if chord:
            members[0].chord_notes = list(members)
    notes.sort(key=lambda n: (n.time, n.lane))

    # Solo sections: prefer the audio-detected lead regions (they are ground
    # truth when solo_charting replaced the rhythm), else the old density
    # heuristic.
    solos = solo_regions if solo_regions else _detect_solo_sections(notes, tempo_map)
    bre = _detect_bre_section(notes, song_end)
    return InstrumentChart(
        notes=notes,
        tempo_map=tempo_map,
        solo_sections=solos,
        bre_section=bre,
        overdrive_phrases=[],
        metadata={
            "instrument": "guitar",
            "num_onsets": len(notes),
            "grid_phase_beats": float(phase),
            "algorithm": "strum_backbone_rhythm",
            "solo_regions": [(round(a, 2), round(b, 2)) for a, b in solo_regions],
            "solo_charting": bool(solo_charting),
        },
    )


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
    # For the shared "other" stem, raise guitar FMIN to ~150 Hz to reject
    # bass-fundamental bleed (E1=41Hz through ~D3=147Hz) while keeping
    # guitar power chords (D3=147Hz and up). Low open strings E2/A2
    # (82/110Hz) are sacrificed but rarely used in rock rhythm parts.
    if instrument == "bass":
        FMIN, FMAX = 38.0, 420.0
    else:  # guitar
        FMIN, FMAX = 150.0, 1400.0

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

    # 2b. (GUITAR) Snap Basic Pitch note onsets onto the audio strum backbone.
    # Basic Pitch over-detects rhythm-guitar onsets (it splits each strum's chord
    # tones into separate onsets -- ~1814 onsets on Open Road Song vs ~698 real
    # strums), and the old post-processing collapsed the dense 8th-note intro
    # into held notes. Instead, detect the real strum attack times from the
    # audio (librosa onset strength, de-duplicated at 60 ms) and assign each
    # Basic Pitch note to the NEAREST strum backbone time. This makes the chart
    # rhythm match the audio strums 1:1 while still using Basic Pitch's pitches
    # for lane assignment. Repeated strums of one chord then group per-strum.
    if instrument == "guitar":
        import librosa as _lr_bk
        _stem_y, _ = _lr_bk.load(stem_path, sr=sr, mono=True)
        _backbone = _strum_backbone(_stem_y, sr)
        _tol_snap = 0.15  # max distance a BP note may snap onto a strum (captures ~96% of strums)
        if len(_backbone):
            # Pass 1: snap each BP note onto its nearest backbone strum (within tol).
            _snapped = []
            for _r in raw:
                _d = np.abs(_backbone - _r["start"])
                _j = int(np.argmin(_d))
                if _d[_j] <= _tol_snap:
                    _r2 = dict(_r)
                    _r2["start"] = float(_backbone[_j])
                    _snapped.append(_r2)
            raw = _snapped

            # Pass 2 (GAP-FILL): some strums have NO Basic Pitch note nearby
            # (a repeated chord strum Basic Pitch missed). For each backbone
            # strum with no charted note, inherit the chord lane-set from a
            # nearby matched strum (within 0.6 s) so the rhythm stays dense and
            # captures every audible strum, matching repeated-chord riffs.
            _matched = {}
            for _r in raw:
                _matched.setdefault(_r["start"], set()).add(_r["lane"])
            _tol_fill = 0.6
            _added = 0
            for _b in _backbone:
                if _b in _matched:
                    continue
                # find nearest matched strum (any time) within tol_fill
                _best_j = None; _best_d = _tol_fill
                for _r in raw:
                    _d = abs(_r["start"] - _b)
                    if _d < _best_d:
                        _best_d = _d; _best_j = _r
                if _best_j is not None:
                    # replicate the neighbor's lanes at this strum (short note)
                    for _lane in sorted({r["lane"] for r in raw if r["start"] == _best_j["start"]}):
                        raw.append({
                            "start": float(_b),
                            "lane": _lane,
                            "is_open": _best_j["is_open"],
                            "length": _best_j["length"],
                            "pitch": _best_j["pitch"],
                            "band_rms": _best_j.get("band_rms"),
                        })
                        _added += 1
            if _added:
                raw.sort(key=lambda r: r["start"])
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
    # Strategy: Two-tier merge
    # 1. Per-gap merge (existing): fuse consecutive chord groups within _frag_gap
    #    if lane-set-stable AND envelope-continuous AND fragments sustained.
    # 2. Windowed-LANE merge (bridge fix): For sustained regions where per-gap
    #    merge didn't collapse enough, apply a sliding window and collapse if
    #    the SAME LANE SET appears consistently AND envelope stays up.
    #    IMPORTANT: Only collapse if the notes are actually SUSTAINED (long length),
    #    not short strum fragments. This preserves rhythm strum riffs.
    if instrument == "guitar":
        _rms = _lr.feature.rms(y=_y, hop_length=_hop)[0]
        _ct = _lr.frames_to_time(np.arange(_chroma.shape[1]), sr=sr, hop_length=_hop)
        _bpm = float(np.median([bpm for _t, bpm in tempo_map])) if tempo_map else 120.0
        # _frag_gap: how far apart two chord fragments can be and still
        # merge into one sustained chord. Must be SHORTER than the song's
        # active strum interval so rhythm-guitar 8th-note parts aren't
        # collapsed into single holds. 2 eighth-notes is a safe upper bound:
        # at 120 BPM that's 0.5 s, at 200 BPM it's 0.3 s.
        _n_eighths = 2
        _frag_gap = min(_n_eighths * (60.0 / max(_bpm, 40.0) / 2), 1.0)
        _ENV_FLOOR = 0.15

        def _lane_set(group):
            """Return frozenset of lanes for a group."""
            return frozenset(r["lane"] for r in group)

        def _stable(t0, t1):
            # Use lane sets instead of chroma for stability
            # Find the group at t0 and t1
            for _g in groups:
                if abs(_g[0]["start"] - t0) < 0.01:
                    lanes_t0 = _lane_set(_g)
                    break
            else:
                lanes_t0 = frozenset()
            for _g in groups:
                if abs(_g[0]["start"] - t1) < 0.01:
                    lanes_t1 = _lane_set(_g)
                    break
            else:
                lanes_t1 = frozenset()
            return lanes_t0 == lanes_t1 and len(lanes_t0) >= 2

        def _held(t0, t1):
            j0 = int(np.clip(np.searchsorted(_ct, t0), 0, len(_ct) - 1))
            j1 = int(np.clip(np.searchsorted(_ct, t1), 0, len(_ct) - 1))
            if j1 < j0:
                j0, j1 = j1, j0
            seg = _rms[j0:j1 + 1]
            if len(seg) < 2:
                return False
            mx = float(seg.max())
            if mx == 0:
                return False
            # Use median instead of min to tolerate brief palm-mute dips / silences
            # A genuinely held chord sustains above floor for most of the region
            # We require >50% of the region to be above floor (not 100%)
            frac_above = float(np.mean(seg >= _ENV_FLOOR * mx))
            return frac_above >= 0.50

        # Tier 1: Per-gap merge (conservative, preserves strum riffs)
        # ONLY merge fragments that are genuinely sustained (length > 2.0s).
        # Short strum fragments (< 2s) are NEVER merged - they stay as separate strums.
        _merged = []
        for _g in groups:
            if _merged:
                _pg = _merged[-1]
                _gap = _g[0]["start"] - _pg[0]["start"]
                # Only merge if BOTH fragments are genuinely sustained chords (> 2s each)
                _pg_sustained = all(r["length"] > 2.0 for r in _pg)
                _g_sustained = all(r["length"] > 2.0 for r in _g)
                if (0.0 < _gap < _frag_gap
                        and _stable(_pg[-1]["start"], _g[0]["start"])
                        and _held(_pg[-1]["start"], _g[0]["start"])
                        and _pg_sustained and _g_sustained):
                    # DO NOT extend lengths here - keep original lengths to not fool Tier 2
                    continue  # absorb _g as a fragment of the held chord
            _merged.append(_g)
        groups = _merged

        # Tier 2: Windowed-LANE merge for SUSTAINED sections only (bridge fix)
        # Only collapse if fragments share the same LANE SET AND are VERY LONG (> 3s each).
        # This is extremely conservative - only for bridge sections with held power chords.
        _window_sec = 6.0  # larger window for bridge detection
        _min_fragments = 5  # minimum fragments in window (more conservative)
        _min_set_coverage = 0.85  # 85% of fragments must share the same lane set

        _i = 0
        while _i < len(groups):
            _g = groups[_i]
            _t_start = _g[0]["start"]
            _t_end = _t_start + _window_sec

            # Collect all fragments in this window
            _window_groups = [_g]
            _j = _i + 1
            while _j < len(groups) and groups[_j][0]["start"] < _t_end:
                _window_groups.append(groups[_j])
                _j += 1

            if len(_window_groups) >= _min_fragments:
                # Check lane SET agreement.
                from collections import Counter
                _lane_sets = [_lane_set(g) for g in _window_groups]
                _set_counts = Counter(_lane_sets)
                _majority_set, _majority_count = _set_counts.most_common(1)[0]
                _set_coverage = _majority_count / len(_window_groups)

                # Also verify the region is sustained (envelope doesn't drop to silence)
                _t_window_end = groups[_j - 1][0]["start"] if _j - 1 < len(groups) else _t_end
                _sustained = _held(_t_start, _t_window_end)

                # Only merge if ALL fragments are VERY LONG (> 3.0s each) - genuinely held chords
                _all_sustained = all(r["length"] > 3.0 for g in _window_groups for r in g)

                # Accept if: very high set coverage, sustained envelope, ALL notes > 3s,
                # and minimum 2 lanes for power chord
                if (_set_coverage >= _min_set_coverage
                        and _sustained
                        and _all_sustained
                        and len(_majority_set) >= 2):
                    # Collapse entire window to ONE sustained chord
                    _window_end = max(r["start"] + r["length"] for g in _window_groups for r in g)
                    _all_notes = [r for g in _window_groups for r in g]
                    _merged_group = _all_notes
                    _merged_group[0]["length"] = _window_end - _merged_group[0]["start"]
                    groups[_i:_j] = [_merged_group]
                    _i += 1
                    continue
            _i += 1


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
    solo_charting: bool = False,
) -> InstrumentChart:
    """Guitar Expert chart.

    Rhythm guitar (the common case this pipeline serves — strummed power
    chords) uses the audio-strum-backbone algorithm
    (``_transcribe_guitar_rhythm``): timing from real strums, lanes from
    chord roots, grid-quantized like the tab. Basic Pitch's note onsets are
    NOT trusted for rhythm-guitar timing (they split chord tones into
    spurious onsets and missed/phantom strums were the standing complaint).

    ``solo_charting=True`` (the CLI's experimental --guitar-solo-charting)
    charts detected lead-solo regions as single lead notes (pyin pitch
    contour) instead of the rhythm power chords there. Solo regions are
    ALWAYS detected and reported in the chart metadata either way.
    """
    return _transcribe_guitar_rhythm(stem_path, tempo_map, song_end, sr,
                                     solo_charting=solo_charting)


def transcribe_bass(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> InstrumentChart:
    return _transcribe_fretted(stem_path, tempo_map, song_end, sr, "bass")


def generate_all_difficulties(expert_chart: InstrumentChart) -> dict:
    return create_all_difficulties(expert_chart, "guitar")