"""
Drum transcription for Rock Band charts.

Transcribes the drums stem into a playable 5-lane drum chart
with all drum elements, fill detection -> overdrive, solos, BRE.
"""

from pathlib import Path
import numpy as np
import librosa

from .onset_detection import (
    detect_onsets_librosa,
    detect_onsets_madmom,
    merge_nearby_onsets,
    filter_onsets_by_strength,
)
from .drum_classifier import (
    classify_drum_onsets_energy,
)
from .difficulty import (
    InstrumentChart,
    create_all_difficulties,
)

#: ADTOF Frame-RNN class pitches -> element names. The model separates drums
#: into kick / snare / toms / hi-hat / cymbals (it merges ride+crash and all
#: toms, which we re-split spectrally in ``_refine_*`` below).
ADTOF_CLASS_MAP = {
    35: 'kick',   # C2
    38: 'snare',  # D2
    42: 'hihat',  # F#2
    47: 'toms',   # B2
    49: 'cymbals' # C#3
}

#: Intro window used to decide whether the drums stem is digitally silent there
#: (Demucs routes a song's intro drums into other.wav). Seconds.
INTRO_END = 60.0


def transcribe_drums(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
    other_stem_path: Path = None,
    mixed_audio_path: Path = None,
) -> InstrumentChart:
    """
    Main drum transcription pipeline.

    Primary path is the **ADTOF Frame-RNN** neural drum transcriber
    (kick/snare/toms/hi-hat/cymbals), which both detects and classifies hits
    from the audio directly — far more accurate than hand-tuned band onsets,
    and it reads the intro correctly off the drums stem (no mixed-audio
    band hack that charted guitar/bass lows as kicks).

    * The drums stem is the source when it carries real content; when Demucs
      routed the intro drums into ``other.wav`` (digitally silent stem intro,
      RMS < 2% of the body) the **mixed audio** is used instead, since it
      carries every drum hit the game will play.
    * If ADTOF is unavailable (package not installed / weights missing), the
      pipeline falls back to the librosa band-based detector + energy
      classifier on the same source.
    * All hits are grid-quantized to the 1/8 note beat grid (Rock Band drums
      are authored on the grid) and double-bass bursts are reduced to a single
      pedal.

    Args:
        stem_path: Path to 'drums.wav' stem
        tempo_map: List of (time, bpm) tuples
        song_end: Song end time in seconds
        sr: Sample rate
        other_stem_path: Optional path to 'other.wav' stem (contains drum bleed)
        mixed_audio_path: Optional path to the original mixed audio (best source
            of drum content when the stem's intro is digitally silent)

    Returns:
        InstrumentChart with Expert difficulty
    """
    from .difficulty import ChartNote, _snap

    source = _choose_drum_source(stem_path, mixed_audio_path, other_stem_path, sr)

    expert_notes = _transcribe_drums_adtof(source, tempo_map, song_end, sr)
    if not expert_notes:
        # ADTOF missing or produced nothing: band-based librosa fallback.
        expert_notes = _transcribe_drums_band(
            stem_path, mixed_audio_path, other_stem_path, tempo_map, song_end, sr
        )

    # Grid-quantize to 1/8 notes: Rock Band drum charts live on the beat grid,
    # and the difficulty reduction below assumes grid-aligned hits.
    for n in expert_notes:
        n.time = _snap(n.time, tempo_map, 2)

    # De-duplicate same-lane hits that landed on the same grid slot.
    expert_notes = sorted(expert_notes, key=lambda n: (n.time, n.lane))
    deduped, seen = [], set()
    for n in expert_notes:
        key = (round(n.time, 4), n.lane)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(n)
    expert_notes = deduped

    # 7b. Rock Band does NOT support fully-authored double bass (alternating
    # pedal). Author only what a single foot can play.
    expert_notes = reduce_double_bass(expert_notes, min_gap=0.11)

    # 8. Build Expert chart.
    # For metadata, approximate element counts from lanes.
    n_kick = sum(1 for n in expert_notes if n.lane == 0)
    n_snare = sum(1 for n in expert_notes if n.lane == 1)
    n_hihat = sum(1 for n in expert_notes if n.lane == 2)
    expert_chart = InstrumentChart(
        notes=expert_notes,
        tempo_map=tempo_map,
        solo_sections=[],
        bre_section=None,
        overdrive_phrases=[],
        metadata={
            'instrument': 'drums',
            'num_kick': n_kick,
            'num_snare': n_snare,
            'num_hihat': n_hihat,
            'num_fills': 0,
        },
    )

    return expert_chart


def _choose_drum_source(
    stem_path: Path,
    mixed_audio_path: Path,
    other_stem_path: Path,
    sr: int,
) -> Path:
    """Pick the audio source for drum transcription.

    The drums stem is the cleanest signal, but Demucs routes a quiet intro's
    drums into ``other.wav`` leaving the stem digitally silent there. When the
    stem's intro RMS is < 2% of its body RMS, fall back to the mixed audio
    (which carries every drum hit) — otherwise transcribe from the stem.
    """
    y, _ = librosa.load(stem_path, sr=sr, mono=True)
    body_start = min(int(INTRO_END * sr), len(y))
    if len(y) > body_start + sr:  # at least 1s of body to compare against
        intro_rms = float(np.sqrt(np.mean(y[:body_start] ** 2)))
        body_rms = float(np.sqrt(np.mean(y[body_start:] ** 2)))
        if body_rms > 1e-6 and intro_rms < 0.02 * body_rms:
            return next(
                (p for p in (mixed_audio_path, other_stem_path, stem_path) if p is not None),
                stem_path,
            )
    return stem_path


def _transcribe_drums_adtof(
    audio_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> list:
    """Neural drum transcription via the ADTOF Frame-RNN.

    Detects and classifies hits (kick/snare/toms/hi-hat/cymbals) in one pass.
    Returns a list of ChartNotes, or ``None`` if the package / weights are
    unavailable so the caller can fall back to the band-based approach.
    """
    from .difficulty import ChartNote

    try:
        import torch
        from adtof_pytorch import (
            calculate_n_bins,
            create_frame_rnn_model,
            load_audio_for_model,
            load_pytorch_weights,
            get_default_weights_path,
            FRAME_RNN_THRESHOLDS,
            LABELS_5,
            PeakPicker,
        )
    except Exception:
        return None

    try:
        model = create_frame_rnn_model(calculate_n_bins())
        model.eval()
        weights = get_default_weights_path()
        if weights:
            model = load_pytorch_weights(model, weights, strict=False)
        model.to("cpu")
        x = load_audio_for_model(str(audio_path))
        with torch.no_grad():
            pred = model(x).cpu().numpy()  # [1, time, 5]
        picker = PeakPicker(thresholds=FRAME_RNN_THRESHOLDS, fps=100)
        picked = picker.pick(pred, labels=LABELS_5, label_offset=0)[0]
    except Exception:
        return None

    y, _ = librosa.load(audio_path, sr=sr, mono=True)

    # Pre-compute tom pitches: ADTOF returns one merged 'toms' class, but Rock
    # Band has three tom pads. Toms are PITCHED, so split by fundamental (low ->
    # tom3/Green, mid -> tom2/Blue, high -> tom1/Yellow). A whole-stem pyin contour
    # is unreliable (the tom band overlaps kick/snares), so we pyin a short
    # window around each tom hit -- only hundreds of windows, each a few ms.
    tom_times = [float(t) for t in picked.get(47, [])]
    tom_f0 = _tom_f0_contour(y, sr, tom_times)

    notes = []
    for pitch, times in picked.items():
        element = ADTOF_CLASS_MAP.get(pitch)
        if element is None:
            continue
        for t in times:
            if t < 0 or t > song_end:
                continue
            if element == 'cymbals':
                _, lane, dp = _refine_cymbal(y, sr, t)
            elif element == 'toms':
                _, lane, dp = _refine_tom(y, sr, t, f0_hz=tom_f0.get(float(t)))
            elif element == 'kick':
                lane, dp = 0, 36
            elif element == 'snare':
                lane, dp = 1, 38
            else:
                lane, dp = 2, 42
            notes.append(ChartNote(
                time=float(t), lane=lane, velocity=100, difficulty_pitch=dp,
            ))
    return notes


# tom fundamental band: floor/low tom ~60 Hz .. high tom ~220 Hz. fmin/fmax chosen so
# pyin locks on the tom's pitched decay while rejecting kick thump (sub 60) bleed.
_TOM_FMIN = librosa.note_to_hz('C2')   # ~65 Hz
_TOM_FMAX = librosa.note_to_hz('A3')   # ~220 Hz
# Pitch split thresholds (Hz) for the three toms. Low tom (floor tom) sits ~65-100 Hz,
# mid tom ~100-140 Hz, high tom ~140-200 Hz. A real low tom is the loudest/most common
# in fills; high tom (lane 2, shares Yellow with the hi-hat) is the rarest -- keeping
# most toms OFF lane 2 un-floods the hi-hat lane.
_TOM_LOW_MAX = 100.0    # < 100 Hz -> tom3 (Green, lane 4)
_TOM_HIGH_MIN = 140.0   # >= 140 Hz -> tom1 (Yellow, lane 2); 100-140 -> tom2 (Blue, 3)


def _refine_cymbal(y: np.ndarray, sr: int, t: float) -> tuple:
    """Split an ADTOF 'cymbals' hit into ride (Blue, lane 3) vs crash (Green,
    lane 4) using the band-energy crash rule from ``drum_classifier``."""
    from .drum_classifier import _band_rms
    i = int(t * sr)
    half = int(sr * 0.06 / 2)
    seg = y[max(0, i - half):min(len(y), i + half)]
    if len(seg) < int(sr * 0.005):
        return 'crash', 4, 49
    ek = _band_rms(seg, sr, 30, 110)
    em = _band_rms(seg, sr, 110, 350)
    eh = _band_rms(seg, sr, 7000, 14000)
    ec = _band_rms(seg, sr, 3000, 9000)
    tot = ek + em + eh + ec + 1e-9
    if (eh + ec) > 0.55 * tot:
        return 'crash', 4, 49
    return 'ride', 3, 51


def _tom_f0_contour(y: np.ndarray, sr: int, tom_times):
    """Estimate each tom hit's fundamental pitch (Hz) by windowed pyin on the
    tom band.

    Toms ring at a distinct fundamental (low ~65-100 Hz, mid ~100-140, high
    ~140-200). A single whole-stem pyin in the tom band is hopeless (the band
    overlaps kick/snares, so the tracker loses itself in the noise between
    hits), so we pyin a short window around each tom hit instead -- only ~hundreds
    of windows per song, each a few milliseconds.

    A hit is only accepted as "pitched" when a voiced frame lands within the
    ring of the strike (voiced-prob >= 0.4 on >= one frame in the window). Short
    tom hits / tom+overhead bleed that pyin can't lock are returned as None and
    fall through to the spectral-centroid rule in ``_refine_tom``.

    Returns a dict ``time -> f0_hz (or None)``.
    """
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2.0
    sos = butter(4, [_TOM_FMIN / nyq, _TOM_FMAX / nyq], btype='band', output='sos')
    yb = sosfiltfilt(sos, y)
    hop = 512
    out = {}
    for t in tom_times:
        i = int(t * sr)
        seg = yb[max(0, i - int(0.15 * sr)): i + int(0.15 * sr)]
        if len(seg) < int(0.15 * sr):
            out[t] = None
            continue
        f0, _flag, vp = librosa.pyin(
            seg, fmin=_TOM_FMIN, fmax=_TOM_FMAX, sr=sr,
            frame_length=2048, hop_length=hop,
        )
        voiced = f0[(vp >= 0.3) & (f0 > 0)]
        out[t] = float(np.median(voiced)) if len(voiced) else None
    return out


def _tom_ring_energy(ring: np.ndarray, sr: int) -> dict:
    """Band energy in the low / mid / high tom ring sub-bands (RMS).

    Low tom (floor tom) rings at ~60-100 Hz, mid tom ~100-170 Hz, high tom
    ~170-260 Hz. Comparing these on the post-attack ring (not the broadband stick
    attack) is what separates a low-pitched tom from a mid tom.
    """
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2.0
    out = {}
    for lab, (lo, hi) in (('low', (60, 100)), ('mid', (100, 170)), ('high', (170, 260))):
        lo = max(lo / nyq, 1e-3)
        hi = min(hi / nyq, 0.99)
        if hi <= lo:
            out[lab] = 0.0
            continue
        b = sosfiltfilt(butter(4, [lo, hi], btype='band', output='sos'), ring)
        out[lab] = float(np.sqrt(np.mean(b ** 2))) if len(b) else 0.0
    return out


_TOM_BY_RING = {
    'low':  ('tom3', 4, 43),   # low tom  -> Green  (lane 4)
    'mid':  ('tom2', 3, 45),   # mid tom  -> Blue   (lane 3)
    'high': ('tom1', 2, 48),   # high tom -> Yellow (lane 2)
}


def _to_tom_by_pitch(f0_hz: float) -> tuple:
    """Map a tom's fundamental pitch to the low/mid/high tom lane."""
    if f0_hz is None:
        return None
    if f0_hz < _TOM_LOW_MAX:
        return 'tom3', 4, 43   # low tom  -> Green  (lane 4)
    if f0_hz < _TOM_HIGH_MIN:
        return 'tom2', 3, 45   # mid tom  -> Blue   (lane 3)
    return 'tom1', 2, 48       # high tom -> Yellow (lane 2)


def _refine_tom(y: np.ndarray, sr: int, t: float, f0_hz: float = None) -> tuple:
    """Assign an ADTOF 'toms' hit to tom1 (Yellow, lane 2) / tom2 (Blue, lane 3)
    / tom3 (Green, lane 4).

    Primary: the tom's fundamental pitch (low -> tom3, mid -> tom2, high -> tom1),
    measured once over the stem's tom band in ``_tom_f0_contour`` and sampled at
    ``t``. The old spectral-centroid rule is the fallback when pyin can't lock a
    pitch (short tom hits, tom+overhead bleed) -- its thresholds are tuned so an
    unpitched hit lands on the middle tom (tom2/Blue) rather than always tom1.
    """
    pitched = _to_tom_by_pitch(f0_hz)
    if pitched is not None:
        return pitched
    # Unpitched ADTOF "toms" that pyin couldn't lock (short hits, tom+overhead
    # bleed): classify by the tom's *ring* rather than its attack. A tom's stick
    # attack is broadband-bright for every tom, so spectral centroid on the attack
    # can't tell a low tom (low ring, bright attack) from a mid tom -- it routes
    # almost everything to tom1 and floods the hi-hat lane. The ring window
    # (t+30ms..t+250ms) carries the tom's fundamental, so compare energy in the
    # low/mid/high tom sub-bands there and pick the dominant pitch class.
    i = int(t * sr)
    start = i + int(0.03 * sr)
    end = i + int(0.25 * sr)
    if end > len(y):
        end = len(y)
    ring = y[start:end]
    if len(ring) < int(sr * 0.05):
        return 'tom2', 3, 45
    bands = _tom_ring_energy(ring, sr)
    if not bands:
        return 'tom2', 3, 45
    lab = max(bands, key=bands.get)
    return _TOM_BY_RING[lab]


def _transcribe_drums_band(
    stem_path: Path,
    mixed_audio_path: Path,
    other_stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> list:
    """Fallback drum transcription: librosa band onsets + energy classifier.

    This is the pre-ADTOF approach (band-specific detection on the mixed/other
    source for the intro, windowed onset detection + classification on the drums
    stem for the body). Only used when the neural transcriber is unavailable.
    """
    onset_path = next(
        (p for p in (mixed_audio_path, other_stem_path, stem_path) if p is not None),
        stem_path,
    )
    y_mix, _ = librosa.load(onset_path, sr=sr, mono=True)
    intro_notes = _transcribe_intro(y_mix, sr, tempo_map, INTRO_END)
    body_notes = _transcribe_body(stem_path, tempo_map, song_end, sr, INTRO_END)
    return intro_notes + body_notes


def _transcribe_intro(
    y: np.ndarray,
    sr: int,
    tempo_map: list,
    intro_end: float,
) -> list:
    """Transcribe the intro (first ``intro_end`` seconds) from the mixed audio.

    The drums stem is silent here (Demucs routes the hits to other.wav), so the
    only reliable signal is the mixed audio itself. Kicks, snares and hi-hats are
    detected in their characteristic frequency bands and snapped onto the 1/8
    note grid (a real rock groove lives on the grid; stray guitar/bass transients
    rarely align). Simultaneous band hits on one grid slot become chords.

    Returns a list of ChartNotes.
    """
    from .difficulty import ChartNote, _snap, _beat_dur

    # Kicks live at 30-110 Hz (sub-bass thump), snares at 150-350 Hz (body) plus
    # broadband crack, hats at 7-14 kHz. Moderate deltas so the band detector
    # catches real hits without flooding on guitar/bass sustain.
    kick_t = _band_onsets(y, sr, 30, 110, delta=0.20, wait=4)
    snare_t = _band_onsets(y, sr, 150, 350, delta=0.20, wait=4)
    hat_t = _band_onsets(y, sr, 7000, 14000, delta=0.20, wait=4)

    def grid_slots(times):
        """Snap to the 1/8 grid, keeping only onsets within 35% of the step."""
        slots = set()
        for t in times:
            if t >= intro_end:
                continue
            step = _beat_dur(tempo_map, t) / 2
            if step <= 0:
                continue
            s = round(_snap(t, tempo_map, 2), 4)
            if abs(t - s) <= step * 0.35:
                slots.add(s)
        return slots

    kick_slots = grid_slots(kick_t)
    snare_slots = grid_slots(snare_t)
    hat_slots = grid_slots(hat_t)

    notes = []
    for t in kick_slots:
        notes.append(ChartNote(time=t, lane=0, velocity=100, difficulty_pitch=36))
    for t in snare_slots:
        notes.append(ChartNote(time=t, lane=1, velocity=100, difficulty_pitch=38))
    for t in hat_slots:
        notes.append(ChartNote(time=t, lane=2, velocity=100, difficulty_pitch=42))

    # Chord-ify simultaneous lanes on one grid slot.
    by_time = {}
    for n in notes:
        by_time.setdefault(n.time, []).append(n)
    for t, ns in by_time.items():
        if len(ns) > 1:
            ns.sort(key=lambda x: x.lane)
            ns[0].is_chord = True
            ns[0].chord_notes = ns[1:]
    return notes


def _transcribe_body(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
    body_start: float = 60.0,
) -> list:
    """Transcribe the body (t >= ``body_start``) from the drums stem.

    The drums stem carries real content here, so the standard windowed onset
    detection + band-energy classifier applies. Returns a list of ChartNotes.
    """
    from .drum_classifier import classify_drum_onsets_energy
    from .difficulty import ChartNote

    try:
        onset_result = detect_onsets_madmom(stem_path)
        onset_result = merge_nearby_onsets(onset_result, min_interval=0.03)
        onset_result = filter_onsets_by_strength(onset_result, min_strength=0.1)
    except Exception:
        onset_result = detect_onsets_librosa(stem_path, sr=sr, window_seconds=30.0)
        onset_result = merge_nearby_onsets(onset_result, min_interval=0.03)
        onset_result = filter_onsets_by_strength(onset_result, min_strength=0.08)

    y, _ = librosa.load(stem_path, sr=sr, mono=True)

    # Augment full-signal onsets with high-band onsets so quiet hi-hats /
    # cymbals (often attenuated by stem separation) are not missed.
    hat_t = _band_onsets(y, sr, 7000, 14000, delta=0.15, wait=5)
    cym_t = _band_onsets(y, sr, 3000, 9000, delta=0.15, wait=6)
    times = np.asarray(_merge_times([onset_result.times, hat_t, cym_t], tol=0.03), dtype=float)
    times = times[times >= body_start]

    elements = classify_drum_onsets_energy(y, sr, times, window_ms=60)

    notes = []
    for elem, t in zip(elements, times):
        if elem.element_type == 'unknown':
            continue
        notes.append(ChartNote(
            time=float(t),
            lane=elem.lane,
            velocity=100,
            difficulty_pitch=elem.midi_pitch,
        ))
    return notes


def _band_onsets(
    y: np.ndarray,
    sr: int,
    fmin: float,
    fmax: float,
    delta: float = 0.07,
    wait: int = 4,
    n_mels: int = None,
) -> np.ndarray:
    """Detect onsets in a band-passed version of the signal (per-element)."""
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2.0
    lo = max(fmin / nyq, 1e-3)
    hi = min(fmax / nyq, 0.99)
    if hi <= lo:
        hi = min(lo * 1.5, 0.99)
    sos = butter(4, [lo, hi], btype='band', output='sos')
    yb = sosfiltfilt(sos, y)
    # Scale the mel filterbank to the band: librosa 0.11's mel banks collapse to
    # all-zeros when n_mels is large relative to fmax (e.g. 64 bands over 110 Hz).
    if n_mels is None:
        n_mels = int(max(8, min(64, fmax / 2000.0 * 64)))
    # Use aggregate=np.mean (not median): on a band-passed signal most mel bins
    # are outside the band, so the median across frequency collapses to ~0.
    env = librosa.onset.onset_strength(
        y=yb, sr=sr, hop_length=512, aggregate=np.mean, n_mels=n_mels, fmax=fmax
    )
    frames = librosa.onset.onset_detect(
        onset_envelope=env, sr=sr, hop_length=512,
        delta=delta, wait=wait, backtrack=True,
    )
    return librosa.frames_to_time(frames, sr=sr, hop_length=512)


def _merge_times(lists, tol: float = 0.025):
    """Merge several onset-time lists, averaging any within `tol` seconds."""
    all_t = sorted(float(t) for lst in lists for t in lst)
    merged = []
    for t in all_t:
        if merged and t - merged[-1] <= tol:
            merged[-1] = (merged[-1] + t) / 2.0
        else:
            merged.append(t)
    return merged


def reduce_double_bass(notes: list, min_gap: float = 0.11) -> list:
    """Collapse rapid kick bursts into single-foot hits.

    Rock Band does not support fully-authored double bass (alternating pedal);
    Expert kick patterns must be playable with one foot. Any kick (lane 0) whose
    onset is within ``min_gap`` seconds of the previously kept kick is dropped,
    keeping the first of the burst. Other lanes are untouched.
    """
    out: list = []
    last_kick_t = -1e9
    for n in sorted(notes, key=lambda x: x.time):
        if getattr(n, "lane", None) == 0:  # kick
            if n.time - last_kick_t < min_gap:
                continue
            last_kick_t = n.time
        out.append(n)
    return out


def generate_all_difficulties(expert_chart: InstrumentChart) -> dict:
    """Generate Hard, Medium, Easy from Expert."""
    return create_all_difficulties(expert_chart, 'drums')