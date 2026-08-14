#!/usr/bin/env python

import json
import os
import re
import warnings
import numpy as np
from pathlib import Path

from autorb.transcribe.syllables import segment_all_words_to_syllables

def load_json(filepath):
    """Utility to load a JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)

# WhisperX word boundaries are systematically LATE relative to the true sung
# onset (median ~80ms, tail up to ~400ms). The vocal stem's Basic-Pitch note
# onsets mark where the sung pitch begins, so we snap each word's start to a
# real onset — but constrained so a word can never snap back into the previous
# word's sung region (Basic-Pitch often merges a fast following word, e.g.
# "Tonight I", into a single sustained note).
ONSET_SEARCH_BEFORE = 1.50  # max seconds before the WhisperX start to look.
                             # LRC timestamps are only a SUGGESTION and can be
                             # offset from the MP3 by >0.45s, and a badly late
                             # LRC line can drag a whisperx phrase late, so a
                             # wide window lets the true (audio-derived) attack
                             # win. Safe because the snap rule only ever picks
                             # the LATEST onset at-or-before the boundary and
                             # the previous-word floor blocks backtracking.
ONSET_SEARCH_AFTER = 0.05    # max seconds after it (WhisperX is rarely early)
ONSET_MAX_SHIFT = 0.30       # never snap more than this far (BP fallback only)
ONSET_SNAP_EARLY_MIN = 0.03  # only snap when WhisperX is at least this late
MIN_WORD_GAP = 0.02          # keep words from collapsing onto each other
MIN_WORD_SEP = 0.08          # minimum separation between consecutive charted
                             # starts (avoids zero-length notes when "I hit"
                             # shares one sung attack)
# A snap target must have AUDIBLE ENERGY (and ideally a voiced frame) shortly
# after it. Requiring only pyin voicing at a high confidence dropped most real
# attacks (e.g. "hit", "My", "pile" are plosives whose voiced vowel follows the
# onset late), leaving ~83% of words unsnapped and therefore charted late. We
# keep an onset if a voiced frame appears within the window OR the RMS energy
# rises above the (relative) noise floor — so unvoiced attacks are still kept
# while silence-floor backtracking and pure bleed are rejected.
VOICED_ONSET_PROB = 0.3       # pyin confidence threshold for "voiced"
VOICED_ONSET_WINDOW = 0.40    # max seconds after an onset to find voicing
ONSET_RMS_WINDOW = 0.30       # max seconds after an onset to find RMS energy
ONSET_RMS_FACTOR = 1.6        # onset is "real" if RMS peak > floor*this

# Vocal MIDI range. C3..C6 (48..84) covers the sung range for the vast
# majority of rock vocals; lower values come from sub-octave noise/guitar bleed.
VOCAL_MIDI_MIN, VOCAL_MIDI_MAX = 48, 84

# Pitch-detection constants. We run librosa pyin once per word over a window
# clipped to the next word's start (matching the charted note duration). A word
# is trusted when enough voiced, high-confidence frames agree between their
# median and rounded mode; this survives real slides/vibrato while rejecting
# split readings caused by harmonics, bleed, or noisy transitions.
PYIN_PROB_THRESH = 0.5
PYIN_MIN_FRAMES = 2
PYIN_MODE_AGREE_ST = 1.0   # median vs rounded mode must be within 1 semitone

# For words without a trusted pyin reading, we fall back to Basic-Pitch. BP is
# prone to octave/harmonic confusion, so we snap the chosen BP note to the octave
# copy that best follows the melodic contour derived from trusted pyin words.
CONTOUR_SNAP_ST = 3.0

# --- Audio-derived word END rules (the sung sustain must not bleed across a
# real phrase gap into the next word's energy). A word's charted end is the end
# of the contiguous active (voiced or RMS-energetic) run that begins at its
# start; once the voice stays below the energy/voicing floor for
# ``AUDIO_END_MAX_GAP`` seconds the word has ENDED, so a sustain can never ring
# into the next phrase ("here" into "I hear", "road" into "This", "listen"
# into "My", "it" into "out").
AUDIO_END_MAX_GAP = 0.20     # sustained inactive run that ends a word
AUDIO_END_VOICED_PROB = 0.25  # pyin confidence for a "voiced" frame

# --- Audio-derived word START fixes ---------------------------------------
# (1) GAP words: WhisperX occasionally glues the FIRST word of a phrase onto the
# PREVIOUS phrase's tail, charting it in vocal silence ("And"@20.9 sung at
# ~23.8, "'Cause"@32.7 sung at ~35.1). A start whose next word is
# ``GAP_WORD_MIN_NEXT``+ seconds away and whose region stays vocally SILENT for
# a grace window (allowing the previous word's sung tail to fade) is re-anchored
# to the first real vocal onset inside the gap.
GAP_WORD_MIN_NEXT = 1.00     # ... only when the next word is at least this far
GAP_WORD_GRACE = 0.20        # skip the previous word's decaying tail
GAP_WORD_SILENCE = 0.30      # ... then require this long of true vocal silence
GAP_WORD_BACKOFF = 0.12      # breathing room before the next word
# (2) LATE words: WhisperX can push the last word of a held phrase LATE ("alone"
# @63.96 sung at ~63.5, "out"@143.2 sung at ~142.15). A start sitting deep into
# an already-sung region is re-anchored to that region's true attack.
LATE_START_THRESH = 0.30     # a start this deep into a sung run is "late"
LATE_START_MOVE_MIN = 0.15   # only actually move when the correction is audible
LATE_START_RUN_GAP = 0.25    # voiced gaps under this stay inside one sung run
LATE_START_SEARCH = 2.00     # rule 1 only hunts onsets this close to the start
#                            # (a WhisperX gap across an instrumental break —
#                            # "forgotten"->"My"@169.2, "song"->"I"@121.2 — is a
#                            # real break, NOT a late word to pull back 3s+)
PITCH_UNIT_JUMP_ST = 3.5     # sustained pitch jump => new word/vowel boundary
PITCH_UNIT_PERSIST = 0.25    # the new pitch must hold this long to count
PITCH_UNIT_AGREE_ST = 1.5    # ... and stay within this of the post-jump pitch
PITCH_UNIT_WINDOW_GAP = 0.10  # start the "settled" window this long ahead of
#                             # each frame (skips an in-progress gradual descent
#                             # — the be/alone drop spans ~8 frames/0.19s)
ONSET_VOICED_AFTER = 0.15    # an onset is a real sung attack only when a
#                             # confident voiced frame follows within this long
#                             # (kills instrumental-bleed onsets in silences)


def _detect_vocal_onsets(vocals_stem):
    """Return the true vocal-attack onsets (source-time seconds) for a stem.

    Runs librosa onset detection on the vocal stem: the attack (consonant +
    first energy burst) is the ground truth for when the singer actually starts
    a syllable. Both WhisperX word starts and Basic-Pitch note onsets run late
    (Basic-Pitch misses the earliest part of the attack — e.g. the first word
    of a song charted ~350ms late). Returns None when the stem cannot be read.

    Onsets are kept only when AUDIBLE sound follows shortly after: a voiced
    (pyin-confident, pitch-bearing) frame within ``VOICED_ONSET_WINDOW``, OR an
    RMS peak above the (relative) noise floor within ``ONSET_RMS_WINDOW``. This
    rejects backtracking onto the envelope floor before any sound (song opening
    silence) and pure instrument bleed, while still keeping unvoiced attacks
    ("hit", "My", "pile") whose voiced vowel follows the onset late.
    """
    try:
        import librosa
    except Exception:
        return None
    try:
        y, sr = librosa.load(str(vocals_stem), sr=22050, mono=True)
    except Exception:
        return None
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr,
                                        backtrack=True, delta=0.05)
    onset_times = librosa.frames_to_time(frames, sr=sr).tolist()
    try:
        f0, _, probs = librosa.pyin(y, fmin=librosa.note_to_hz('C3'),
                                    fmax=librosa.note_to_hz('C6'), sr=sr,
                                    frame_length=2048, hop_length=512)
        f_times = librosa.times_like(f0, sr=sr, hop_length=512)
        voiced = np.isfinite(f0) & (probs > VOICED_ONSET_PROB)
        # Relative noise floor from a coarse RMS envelope (energy can be loud
        # or soft from song to song, so the threshold is relative, not absolute).
        hop_rms = int(0.025 * sr)
        rms = librosa.feature.rms(y=y, frame_length=hop_rms * 2,
                                  hop_length=hop_rms)[0]
        rms_t = librosa.frames_to_time(np.arange(len(rms)), sr=sr,
                                       hop_length=hop_rms)
        floor = np.percentile(rms, 25) * ONSET_RMS_FACTOR
        return [
            t for t in onset_times
            if np.any(voiced[(f_times >= t) & (f_times <= t + VOICED_ONSET_WINDOW)])
            or np.any(rms[(rms_t >= t) & (rms_t <= t + ONSET_RMS_WINDOW)] > floor)
        ]
    except Exception:
        return onset_times


def _refine_word_timing(segment, note_events, prev_sung_end, vocal_onsets=None):
    """Returns ``(start, end)`` for one word, snapped to the real sung onset.

    ``prev_sung_end`` is the FLOOR for candidate onsets: any onset before it
    belongs to a neighbour's sung region and is rejected. The caller passes the
    PREVIOUS word's true (snapped) onset plus a small separation — NOT the
    previous word's possibly over-extended end — so an over-sustained previous
    word (e.g. an LRC-timestamp hold) can never block this word from snapping
    to its own true attack.

    When ``vocal_onsets`` (the vocal stem's true attacks) is available, snap the
    start to the LATEST onset at-or-before the WhisperX boundary — the nearest
    real sung attack, correcting WhisperX's systematic lateness AND Basic-Pitch's
    own lag (which left the first word of a song ~350ms late). The window is wide
    (``ONSET_SEARCH_BEFORE``) because LRC/WhisperX timestamps are only
    suggestions and can be offset from the MP3. Without it, fall back to snapping
    to the nearest Basic-Pitch onset (legacy behaviour).
    """
    start_time = segment.get("start", segment.get("time", 0.0))
    end_time = segment.get("end", start_time + 0.3)

    best_start = start_time
    best_diff = ONSET_MAX_SHIFT

    if vocal_onsets:
        # Snap to the LATEST onset at-or-before the WhisperX start — the nearest
        # real sung attack on the early side. This corrects WhisperX/BP lateness
        # (true attack is right before the late boundary) WITHOUT over-reaching:
        # a wide ONSET_SEARCH_BEFORE absorbs large LRC/WhisperX offsets (the
        # timestamp is only a suggestion), but unrelated earlier attacks from the
        # previous phrase (e.g. 0.50 when the attack is 1.00) stay out of range
        # because we take the nearest, not the earliest, candidate.
        early_candidates = [
            o for o in vocal_onsets
            if start_time - ONSET_SEARCH_BEFORE <= o <= start_time + ONSET_SEARCH_AFTER
            and o >= prev_sung_end - MIN_WORD_GAP
        ]
        if early_candidates:
            nearest = max(early_candidates)
            if start_time - nearest >= ONSET_SNAP_EARLY_MIN:
                best_start = nearest
    else:
        # Legacy fallback: snap to the nearest Basic-Pitch onset within range.
        for note in note_events:
            note_start, note_end, _ = note[0], note[1], note[2]
            if note_start < start_time - ONSET_SEARCH_BEFORE:
                continue
            if note_start > start_time + ONSET_SEARCH_AFTER:
                break
            if note_start < prev_sung_end - MIN_WORD_GAP:
                continue
            diff = abs(note_start - start_time)
            if diff < best_diff:
                best_diff = diff
                best_start = note_start
                if note_end > note_start:
                    end_time = max(end_time, note_end)

    # Extend the end across notes that BEGIN inside this word's own span
    # (multi-syllable words produce several notes). Notes that start after the
    # word's WhisperX end belong to the next word and must not widen the pitch
    # window into the neighbour's sung region.
    for note in note_events:
        note_start, note_end, _ = note[0], note[1], note[2]
        if note_start < end_time and note_end > best_start:
            end_time = max(end_time, note_end)

    return best_start, end_time


def _compute_word_pyin_pitches(times, f0, voiced, probs, starts, ends,
                               prob_thresh=PYIN_PROB_THRESH,
                               min_frames=PYIN_MIN_FRAMES,
                               agree_st=PYIN_MODE_AGREE_ST):
    """Return per-word (median_midi, trusted_bool) from librosa pyin.

    The analysis window is clipped to the next word's charted start so the pitch
    window never leaks into a neighbour's sung region. A word is trusted when at
    least ``min_frames`` voiced, confident frames exist and the rounded mode is
    within ``agree_st`` semitones of the median. This rejects split readings
    (e.g. fundamental + strong harmonic both present) while keeping real
    vibrato, slides, and sustained vowels.
    """
    next_starts = starts[1:].tolist() + [ends[-1]]
    results = []
    for i in range(len(starts)):
        start = starts[i]
        end = min(ends[i], next_starts[i])
        if end - start < 0.05:
            end = start + 0.15
        i0 = int(np.searchsorted(times, start))
        i1 = int(np.searchsorted(times, end))
        mask = voiced[i0:i1] & (probs[i0:i1] > prob_thresh) & np.isfinite(f0[i0:i1])
        if np.count_nonzero(mask) < min_frames:
            results.append((None, False))
            continue
        midis = 69.0 + 12.0 * np.log2(f0[i0:i1][mask] / 440.0)
        med = float(np.median(midis))
        rounded = np.round(midis).astype(int)
        mode = float(np.bincount(rounded - rounded.min()).argmax() + rounded.min())
        if abs(med - mode) > agree_st:
            results.append((None, False))
            continue
        results.append((med, True))
    return results


def _build_melodic_contour(starts, pyin_results):
    """Return a callable melodic contour from trusted pyin words.

    Uses linear interpolation between trusted word starts, with constant
    extrapolation at both ends. If fewer than two trusted words exist, returns
    ``None`` (caller falls back to the default pitch contour).
    """
    from scipy.interpolate import interp1d
    trusted = [(i, med) for i, (med, ok) in enumerate(pyin_results) if ok]
    if len(trusted) < 2:
        return None
    x = np.array([starts[i] for i, _ in trusted], dtype=float)
    y = np.array([med for _, med in trusted], dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fn = interp1d(x, y, kind="linear", fill_value="extrapolate")
    x0, x1 = float(x[0]), float(x[-1])
    y0, y1 = float(y[0]), float(y[-1])

    def contour(t):
        if t < x0:
            return y0
        if t > x1:
            return y1
        return float(fn(t))
    return contour


def _best_overlap_pitch(start, end, note_events, min_overlap=0.02):
    """Return the Basic-Pitch note that overlaps the window most."""
    best_pitch = None
    best_overlap = min_overlap
    for note in note_events:
        note_start, note_end, note_pitch = note[0], note[1], note[2]
        overlap = min(note_end, end) - max(note_start, start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_pitch = note_pitch
    return best_pitch


def _octave_snap(bp_pitch, contour_pitch):
    """Pick the octave copy of ``bp_pitch`` nearest ``contour_pitch`` (in range).

    Returns ``None`` if no copy falls inside the allowed vocal MIDI range.
    """
    candidates = [bp_pitch + 12 * k for k in range(-2, 3)
                  if VOCAL_MIDI_MIN <= bp_pitch + 12 * k <= VOCAL_MIDI_MAX]
    if not candidates:
        return None
    return min(candidates, key=lambda x: abs(x - contour_pitch))


def _resolve_pitches(starts, ends, note_events, times, f0, voiced, probs):
    """Resolve a final integer MIDI pitch for every word.

    Priority:
      1. trusted librosa pyin reading (in-span, clipped to next word start);
      2. Basic-Pitch fallback, octave-snapped to the melodic contour built from
         trusted pyin words, but only if the snap stays close to the contour;
      3. the melodic contour value itself, clamped to the sane vocal range.
    """
    if f0 is None or voiced is None or probs is None or times is None:
        pyin_results = [(None, False)] * len(starts)
    else:
        pyin_results = _compute_word_pyin_pitches(times, f0, voiced, probs,
                                                 starts, ends)
    contour = _build_melodic_contour(starts, pyin_results)

    pitches = []
    for i in range(len(starts)):
        # 1) pyin is the most reliable source when it is confident and agrees.
        med, trusted = pyin_results[i]
        if trusted:
            pitches.append(int(round(med)))
            continue

        # 2) Build an expected pitch from the melodic contour and try to rescue
        # a Basic-Pitch note by snapping it to the nearest vocal octave. The BP
        # window spans the full multi-syllable `end` (as in the validated
        # prototype); the octave snap to the contour neutralizes any neighbour
        # contamination.
        contour_pitch = contour(starts[i]) if contour is not None else 60.0
        bp = _best_overlap_pitch(starts[i], ends[i], note_events)
        if bp is not None:
            snapped = _octave_snap(bp, contour_pitch)
            if snapped is not None and abs(snapped - contour_pitch) <= CONTOUR_SNAP_ST:
                pitches.append(int(snapped))
                continue

        # 3) No trustworthy local evidence: follow the contour.
        pitches.append(int(round(max(VOCAL_MIDI_MIN,
                                      min(VOCAL_MIDI_MAX, contour_pitch)))))
    return pitches


def _clip_and_extend_word_ends(refined, lyrics_data, audio_times=None,
                               audio_f0=None, audio_voiced=None, audio_probs=None,
                               audio_rms_t=None, audio_rms=None):
    """Post-process word ends so charted notes follow the AUDIO, not the LRC.

    The LRC/WhisperX timestamps are only suggestions; the true sung END of a
    word is the last audible (voiced or RMS-energetic) frame of its region.

    1. Set each word's end to its true sung end:
       - a voiced frame (prob > 0.25) and/or an RMS peak above the relative
         noise floor, within the word's own region [start, next_start).
       This is the fix for sustains that were wrong because they used LRC line
       timestamps: "forgottennnn" was CHOPPED short (under-sustain) while
       "bored"/"mirror"/"alone" were HELD ~1.8s too long (over-sustain).
    2. Clip every word's end to the *next* word's start (no overlaps). This is
       critical: un-clipped overlaps push every following note progressively
       later (the PS4 drift symptom).

    When no audio signals are available (e.g. pure unit tests / no stem), fall
    back to the WhisperX-provided end, only clipping overlaps.
    """
    # --- 1) Set each word's end from the audio tail ---
    if audio_times is not None:
        for i, w in enumerate(sorted(refined, key=lambda w: w.get("start", 0.0))):
            start = w.get("start", w.get("time", 0.0))
            next_start = (sorted(refined, key=lambda w: w.get("start", 0.0))[i + 1]
                          ["start"] if i + 1 < len(refined) else None)
            end = _audio_word_end(start, next_start, audio_times, audio_f0,
                                  audio_voiced, audio_probs,
                                  audio_rms_t, audio_rms)
            if end is not None:
                w["end"] = end
            elif next_start is not None:
                # No audio signal in this region (quiet pickup word, or the
                # START moved AFTER an earlier end pass — "And" pulled from
                # 20.9 to 23.8 leaves its stale 21.0 end behind). The word can
                # never validly extend past its neighbour, so default to just
                # before the next word instead of keeping a stale value.
                w["end"] = next_start - 0.02

    # --- 2) Clip to next word's start ---
    sorted_words = sorted(refined, key=lambda w: w.get("start", 0.0))
    for i in range(len(sorted_words) - 1):
        curr = sorted_words[i]
        nxt = sorted_words[i + 1]
        curr_end = curr.get("end", curr.get("start", 0.0))
        next_start = nxt.get("start", nxt.get("time", 0.0))
        if curr_end > next_start:
            curr["end"] = next_start
    # The last word must not end before its own start.
    last = sorted_words[-1]
    if last.get("end", 0.0) < last.get("start", 0.0):
        last["end"] = last.get("start", 0.0) + 0.2
    # Any word whose end still lands before its own start (a stale pre-move end
    # with no next word, e.g. the final word after a gap-word shift) becomes a
    # valid short note instead of a negative-length one.
    for w in sorted_words:
        if w.get("end", 0.0) < w.get("start", 0.0):
            w["end"] = w.get("start", 0.0) + 0.2


def _audio_word_end(start, next_start, times, f0, voiced, probs, rms_t, rms):
    """Return the true sung END of a word: the end of the contiguous active
    (voiced OR RMS-energetic) run that begins at the word's start.

    Walking forward from ``start``, the end is the last active frame BEFORE the
    first sustained inactive run (``AUDIO_END_MAX_GAP``). Once the voice drops
    below the energy/voicing floor for that long the word has ENDED — so a
    sustain can never bleed into the next phrase's energy ("here" ringing into
    "I hear", "road" into "This", "listen" into "My", "it" swallowing "out").
    The old rule (last active frame anywhere in the region) crossed those gaps
    and over-held every word that preceded a re-rise.

    Returns None when there is no signal to judge by (caller keeps the
    WhisperX/LRC end). The region is bounded by the next word's start so a
    sustain never leaks into the neighbour's sung region.
    """
    if times is None:
        return None
    end_bound = next_start if next_start is not None else times[-1] + 0.2
    if end_bound - start < 0.05:
        return None
    # VOICED is primary: the word's sung end is the last confident voiced frame
    # before a sustained voiced gap (``AUDIO_END_MAX_GAP``). Using voicing rather
    # than RMS keeps the low-level reverb bleed of the PREVIOUS word from
    # bridging a real phrase gap ("listen" ringing into "My" at 138.29, "it"
    # into "out" at 141.84, "road" into "This" at 186.39, "here" into "I hear").
    # Words with NO voiced content at all (breathy/unvoiced) fall back to RMS.
    if f0 is not None:
        vmask = np.isfinite(f0) & (probs is None or probs > AUDIO_END_VOICED_PROB)
        lo = int(np.searchsorted(times, start))
        hi = int(np.searchsorted(times, end_bound))
        if np.any(vmask[lo:hi]):
            grid = times
            in_run = vmask
        elif rms is not None and len(rms):
            floor = float(np.percentile(rms, 25)) * 1.5
            in_run = np.interp(times, rms_t, rms) > floor
            grid = times
        else:
            return None
    elif rms is not None and len(rms):
        floor = float(np.percentile(rms, 25)) * 1.5
        in_run = rms > floor
        grid = rms_t
    else:
        return None
    lo = int(np.searchsorted(grid, start))
    hi = int(np.searchsorted(grid, end_bound))
    last_active = None
    gap_start = None
    # The word's start is its onset (attack); the voiced vowel can take a
    # moment to develop, so an inactive LEAD-IN at the very start of the region
    # must not count as a gap. The timer only starts after the first active
    # frame ("it"@140.156 is onset-snapped, but pyin voicing starts 0.22s later).
    for i in range(lo, hi):
        if in_run[i]:
            last_active = float(grid[i])
            gap_start = None
        elif last_active is not None:
            if gap_start is None:
                gap_start = float(grid[i])
            elif grid[i] - gap_start > AUDIO_END_MAX_GAP:
                break
    if last_active is None:
        return None
    # never stretch into the next word (and never a zero/negative length)
    if next_start is not None and last_active >= next_start:
        last_active = next_start - 0.02
    if last_active < start + 0.05:
        return None
    return last_active


def _reanchor_gap_words(refined, grid, f0, probs, rms, rms_t, onsets):
    """Re-anchor a phrase-initial word that WhisperX glued onto the PREVIOUS
    phrase's tail, charting it in vocal silence ("And"@20.9 sung at ~23.8,
    "'Cause"@32.7 sung at ~35.1).

    A word whose next word is ``GAP_WORD_MIN_NEXT``+ seconds away AND whose
    region stays truly silent for the grace+sweep window sits in the gap BETWEEN
    phrases. The grace window skips the previous word's decaying sung tail (the
    "bored"/"mirror" over-sustains ARE still voiced up to 21.0/32.9, so a naive
    "no energy at the start" test never fires). Its real sung position is the
    first vocal-stem onset after that silence — the phrase's true attack — or,
    with no onset, just before the next word. Generalizable by construction: it
    never targets a song, only this (gap, far-next-word) pattern.
    """
    has_voice = grid is not None and f0 is not None
    has_rms = rms is not None and len(rms)
    if (not has_voice and not has_rms) or not onsets:
        return
    floor = float(np.percentile(rms, 25)) * 1.5 if has_rms else 0.0
    words = sorted(refined, key=lambda w: w.get("start", 0.0))
    for i, w in enumerate(words[:-1]):
        start = w.get("start", 0.0)
        nxt = words[i + 1].get("start", 0.0)
        if nxt - start < GAP_WORD_MIN_NEXT:
            continue
        g0 = start + GAP_WORD_GRACE
        g1 = g0 + GAP_WORD_SILENCE
        if has_voice:
            if np.any((grid >= g0) & (grid <= g1) & np.isfinite(f0)
                      & (probs > AUDIO_END_VOICED_PROB)):
                continue
        if has_rms:
            if np.any((rms_t >= g0) & (rms_t <= g1) & (rms > floor)):
                continue
        cand = [o for o in onsets if g0 < o <= nxt]
        new = min(cand) if cand else nxt - 0.28
        new = min(new, nxt - GAP_WORD_BACKOFF)
        new = max(new, start + 0.02)
        w["start"] = w["time"] = new


def _last_pitch_unit_boundary(run_start, wstart, grid, f0, probs):
    """Return the last sustained pitch jump inside ``(run_start, wstart)`` — the
    point where the singer changed pitch and HELD the new note (a new word or
    vowel). A frame counts when its pitch is ``PITCH_UNIT_JUMP_ST``+ semitones
    from the MEDIAN of the pitch it SETTLES into over the next
    ``PITCH_UNIT_PERSIST`` seconds (measured from ``PITCH_UNIT_WINDOW_GAP`` ahead
    so an in-progress gradual descent — the be/alone drop spans ~8 frames/0.19s —
    is skipped, not averaged into the settled window), and that settled window is
    STABLE (peak-to-peak under ~2st, rejecting vibrato/fast slides). Returns the
    LAST such frame; ``None`` when none exists.
    """
    lo = int(np.searchsorted(grid, run_start))
    hi = int(np.searchsorted(grid, wstart))
    if hi - lo < 8:
        return None
    mask = np.isfinite(f0[lo:hi]) & (probs[lo:hi] > AUDIO_END_VOICED_PROB)
    t = grid[lo:hi][mask]
    m = 69.0 + 12.0 * np.log2(f0[lo:hi][mask] / 440.0)
    if len(m) < 8:
        return None
    boundary = None
    for j in range(len(m)):
        rel = t[j:] - t[j]
        fut = (rel >= PITCH_UNIT_WINDOW_GAP) & (rel <= PITCH_UNIT_PERSIST + PITCH_UNIT_WINDOW_GAP)
        if fut.sum() < 4:
            continue
        fut_m = m[j:][fut]
        fut_med = float(np.median(fut_m))
        if abs(m[j] - fut_med) < PITCH_UNIT_JUMP_ST:
            continue
        if np.ptp(fut_m) > 2.0:
            continue
        boundary = float(t[j])
    return boundary


def _reanchor_late_words(refined, grid, f0, probs, onsets):
    """Re-anchor a word WhisperX placed LATE (its start deep inside an
    already-sung region) back to that region's true attack.

    Two independent, generalizable signals correct the lateness (whichever wins
    lands on a real sung boundary):
      1. GAP-ONSET: a start sitting ``LATE_START_THRESH``+ seconds after the
         PREVIOUS word's audio-derived end, with real onsets in between, moves
         to the EARLIEST such onset ("out" swallowed by "it": charted @143.2
         but sung @142.15).
      2. PITCH-BOUNDARY: a start sitting ``LATE_START_THRESH``+ seconds after
         the last sustained pitch jump inside the previous word's WhisperX span
         moves to that jump — WhisperX pushed the be/alone boundary late
         ("alone" charted @63.96 but its held note starts @63.5).
    """
    words = sorted(refined, key=lambda w: w.get("start", 0.0))
    for i in range(1, len(words)):
        w = words[i]
        prev = words[i - 1]
        start = w.get("start", 0.0)
        prev_end = prev.get("end", prev.get("start", 0.0))
        candidates = []
        # 1) earliest real onset after the previous word's true sung end. An
        #    onset only counts when a confident voiced frame follows it within
        #    ``ONSET_VOICED_AFTER`` — the 40.9/41.0/41.3 onsets before "I"@41.54
        #    are instrumental bleed in a true silence (no voiced pitch follows),
        #    while "out"'s 142.15 onset IS the sung attack.
        if onsets and start - prev_end >= LATE_START_THRESH:
            voiced_t = None
            if grid is not None and f0 is not None:
                voiced_t = grid[np.isfinite(f0) & (probs > AUDIO_END_VOICED_PROB)]
            search_lo = max(prev_end, start - LATE_START_SEARCH)
            for o in sorted(onsets):
                if search_lo < o <= start:
                    if voiced_t is not None and not np.any(
                            (voiced_t >= o) & (voiced_t <= o + ONSET_VOICED_AFTER)):
                        continue
                    candidates.append(o)
                    break
        # 2) last sustained pitch jump before the word's start (searching into
        #    the NEXT word's territory too — the be/alone drop's "settled" pitch
        #    only stabilises after be's WhisperX end, so the future window must
        #    be able to see alone's hold to confirm the drop)
        prev_raw_end = prev.get("raw_end")
        if grid is not None and f0 is not None:
            b = _last_pitch_unit_boundary(prev.get("start", 0.0),
                                          start,
                                          grid, f0, probs)
            if b is not None and 0.25 <= (start - b) <= 0.80 and b >= prev.get("end", 0) - 0.02:
                # Prefer a real vocal-stem attack near the pitch boundary when
                # one exists (the pitch boundary marks the note's start, but an
                # onset is more precise — "on"@46.63 sits 90ms before its 46.72
                # attack). Guarded: never past the next word or behind the
                # previous word, so a legato word with no attack ("I"@58.17,
                # whose next onset belongs to the next word) keeps its boundary.
                b_snap = b
                if onsets:
                    nxt_start = (words[i + 1].get("start", start + 1.0)
                                 if i + 1 < len(words) else start + 1.0)
                    for o in onsets:
                        if (b - 0.15 <= o <= b + 0.15
                                and prev.get("start", 0.0) <= o
                                and o <= nxt_start and o < start):
                            b_snap = o
                            break
                candidates.append(b_snap)
        if not candidates:
            continue
        new = min(candidates)
        new = max(new, prev.get("start", 0.0) + MIN_WORD_SEP)
        if start - new < LATE_START_MOVE_MIN:
            continue
        w["start"] = w["time"] = new


def _dedup_consecutive_words(word_segments, min_gap=0.35):
    """Drop WhisperX word duplications (same word emitted twice back-to-back).

    WhisperX occasionally emits the same word twice in a row — two segments with
    nearly identical text and timestamps for ONE sung word. A genuinely repeated
    lyric is sung with a real gap; a duplicate is two segments spaced under
    ``min_gap`` seconds apart. This runs BEFORE timing refinement so a duplicated
    word is never charted twice (which doubles the on-screen lyric, e.g.
    "crack crack a window").
    """
    norm = lambda w: re.sub(r"[^a-z0-9]", "", (w or "").lower())
    out = []
    for seg in sorted(word_segments, key=lambda s: s.get("start", s.get("time", 0.0))):
        s = seg.get("start", seg.get("time", 0.0))
        if out:
            prev = out[-1]
            ps = prev.get("start", prev.get("time", 0.0))
            if norm(seg.get("word")) == norm(prev.get("word")) and (s - ps) < min_gap:
                continue
        out.append(seg)
    return out


def _dedup_final_synced(synced_words, min_gap=0.15):
    """Drop final-chart near-simultaneous duplicate words (post onset-snap).

    Runs AFTER snapping, syllable segmentation, and pitch attachment (whole
    word dicts are dropped wholesale, so nothing dangles). A whisperx
    melisma-split of one sung word charted as the same lyric twice within
    ``min_gap`` seconds ("Well I'm-I'm lyin'") becomes two notes ~0.08s apart
    once both snap to the shared attack — that's an artifact, not a re-sung
    word, and it renders as a doubled lyric. Genuine repeats are re-articulated
    and land ≥ ~0.25s apart ("fun fun fun"), so they survive.
    """
    norm = lambda w: re.sub(r"[^a-z0-9]", "", (w or "").lower())
    out = []
    for w in synced_words:
        if out:
            prev = out[-1]
            if norm(w.get("word")) == norm(prev.get("word")) and \
               w.get("start", 0.0) - prev.get("start", 0.0) < min_gap:
                continue
        out.append(w)
    return out


def _clamp_syllable_regions(refined):
    """Clip every syllable to its word's [start, min(end, next_start - MIN_WORD_SEP)] region.

    Defends against cache v2 staleness overshoot and onset-snap interleaving:
    a syllable must never start before its word's true (onset-snapped) start nor
    spill past the next word's charted start, otherwise lyrics jumble
    ("eve Thatry thing" instead of "everything that").
    """
    for i, word in enumerate(refined):
        region_end = word.get("end", word.get("start", 0.0))
        if i + 1 < len(refined):
            nxt_start = refined[i + 1].get("start", word.get("start", 0.0) + 1.0)
            region_end = min(region_end, nxt_start - MIN_WORD_SEP)
        if region_end <= word.get("start", 0.0):
            region_end = word.get("start", 0.0) + 0.05
        for syl in word.get("syllables", []):
            if syl.get("start", 0) < word.get("start", 0):
                syl["start"] = word.get("start", 0)
            if syl.get("end", 0) > region_end:
                syl["end"] = region_end
            if syl.get("end", 0) < syl.get("start", 0):
                syl["end"] = syl.get("start", 0) + 0.05
    return refined


def sync_lyrics_to_beats(beats_data, lyrics_data, vocals_stem=None, lrc_path=None):
    """
    Maps word segments to the nearest beat time.

    ``vocals_stem`` (optional) is the path to the vocal stem WAV; when given,
    its true attack onsets (librosa) drive the per-word start snap so charted
    notes land on the real sung onset instead of WhisperX's late boundary.
    
    ``lrc_path`` (optional) is the path to the LRC file for syllable-level timing.
    """
    beat_times = beats_data.get("beat_times", [])
    word_segments = _dedup_consecutive_words(lyrics_data.get("word_segments", []))
    note_events = lyrics_data.get("note_events", [])
    alignment_result = lyrics_data.get("alignment_result", {})
    
    # NEW: Load per-syllable pitch data from cache (v2 format)
    syllable_pitches = lyrics_data.get("syllable_pitches", [])

    vocal_onsets = _detect_vocal_onsets(vocals_stem) if vocals_stem else None
    if vocal_onsets:
        print(f"Detected {len(vocal_onsets)} vocal-stem onsets for word-start snapping.")

    # Audio-derived timing signals (source of truth). LRC/WhisperX timestamps are
    # only SUGGESTIONS: the true sung onset is a vocal-stem attack and the true
    # sung END is the last voiced/RMS-energetic frame of the word's region.
    audio_times = audio_f0 = audio_voiced = audio_probs = None
    audio_rms_t = audio_rms = None
    if vocals_stem:
        try:
            import librosa
            y, sr = librosa.load(str(vocals_stem), sr=22050, mono=True)
            audio_f0, audio_voiced, audio_probs = librosa.pyin(
                y, fmin=librosa.note_to_hz("C3"), fmax=librosa.note_to_hz("C6"),
                sr=sr, frame_length=2048, hop_length=512)
            audio_times = librosa.times_like(audio_f0, sr=sr, hop_length=512)
            hop_rms = int(0.025 * sr)
            audio_rms = librosa.feature.rms(y=y, frame_length=hop_rms * 2,
                                            hop_length=hop_rms)[0]
            audio_rms_t = librosa.frames_to_time(np.arange(len(audio_rms)),
                                                 sr=sr, hop_length=hop_rms)
        except Exception:
            audio_times = audio_f0 = audio_voiced = audio_probs = None
            audio_rms_t = audio_rms = None

    # First pass: refine timings and collect word windows.
    refined = []
    # The snapping FLOOR for the next word is the PREVIOUS word's TRUE onset
    # plus a minimum separation — NOT its (possibly over-extended) end. This is
    # the fix for e.g. "salt" end 155.77 blocking "I search" from snapping to
    # its true attack (~155.6).
    prev_true_start = float("-inf")
    for segment in sorted(word_segments, key=lambda s: s.get("start", s.get("time", 0.0))):
        word = segment["word"]
        start_time, _ = _refine_word_timing(segment, note_events,
                                            prev_true_start, vocal_onsets)
        # Enforce a minimum separation so "I hit" (one shared sung attack) still
        # yields two non-zero-length notes instead of overlapping at one onset.
        start_time = max(start_time, prev_true_start + MIN_WORD_SEP)
        prev_true_start = start_time

        closest_beat = min(beat_times, key=lambda b: abs(b - start_time))
        beat_index = beat_times.index(closest_beat)

        refined.append({
            "word": word,
            "time": start_time,
            "start": start_time,
            "raw_start": segment.get("start", segment.get("time", 0.0)),
            "raw_end": segment.get("end", start_time + 0.3),
            "end": segment.get("end", start_time + 0.3),
            "beat_time": closest_beat,
            "beat_index": beat_index,
            "confidence_score": segment.get("score", 1.0)
        })

    # Post-process word starts AND ends using the AUDIO as the source of truth:
    # 1) Each word's end is set to the true sung end (last voiced/RMS frame in
    #    its region) so sustains follow the audio — neither chopped short by a
    #    late WhisperX boundary ("forgottennnn") nor held too long by a far-away
    #    LRC line timestamp ("bored", "mirror", "alone").
    # 2) No word's end may overlap the next word's start (overlaps accumulate
    #    into progressive lateness in-game).
    _clip_and_extend_word_ends(refined, lyrics_data,
                               audio_times, audio_f0, audio_voiced, audio_probs,
                               audio_rms_t, audio_rms)

    # Start-level corrections driven by the audio, applied AFTER the first end
    # pass so they can consult the previous word's true (gap-aware) sung end:
    #  - Gap words (first word of a phrase glued onto the previous phrase's
    #    tail, charted in vocal silence) move to their phrase's true attack.
    #  - Late words (WhisperX pushed the last word of a held phrase late) move
    #    back to the region's real pitch/onset boundary.
    # Then re-derive ends + re-clip with the corrected starts.
    if (audio_rms is not None and len(audio_rms)) or audio_f0 is not None:
        _reanchor_gap_words(refined, audio_times, audio_f0, audio_probs,
                            audio_rms, audio_rms_t, vocal_onsets or [])
    # Re-derive ends AFTER the gap-word moves so a moved word's neighbour gets a
    # fresh region bound (otherwise "And"@23.8 sees "bored"'s end clipped by the
    # OLD too-early next-start and pulls the bored-tail onset back onto itself).
    if audio_f0 is not None:
        _reanchor_late_words(refined, audio_times, audio_f0, audio_probs,
                             vocal_onsets or [])
    # Enforce that no word starts before the previous word's true end + sep,
    # preventing onset-snap from placing words inside the previous word's
    # sung region (which causes syllable interleaving and lyrical jumbling
    # such as "eve Thatry thing" instead of "everything that").
    for i in range(1, len(refined)):
        prev = refined[i - 1]
        w = refined[i]
        min_start = prev.get("end", prev.get("start", 0.0)) + MIN_WORD_SEP
        if w.get("start", 0.0) < min_start:
            w["start"] = w["time"] = min_start
# Second pass: syllable segmentation
    lrc_data = None
    if lrc_path and Path(lrc_path).exists():
        lrc_data = lyrics_data.get("lyrics_data", [])
    
    # Add syllable segmentation
    refined = segment_all_words_to_syllables(
        refined,
        lrc_data=lrc_data,
        whisperx_alignment=alignment_result,
    )

    # Third pass: attach per-syllable pitch data from cache
    if syllable_pitches:
        # The syllable_pitches from cache now have a "word_index" field
        # that tells us which word (by index in the original WhisperX word_segments)
        # each syllable belongs to. We use this to group syllables by their
        # parent word, which is far more reliable than timing-based matching.
        
        # First, group syllables by word_index to compute the shift per word
        syllables_by_word = [[] for _ in refined]
        for sp in syllable_pitches:
            wi = sp.get("word_index", -1)
            if 0 <= wi < len(refined):
                syllables_by_word[wi].append(sp)
        
        # Group syllables by word_index and compute shifts
        word_syllables = [[] for _ in refined]
        for wi, word_sps in enumerate(syllables_by_word):
            if not word_sps:
                continue
            
            # Find the earliest syllable start for this word (approximates cache word start)
            cache_word_start = min(sp["syllable_start"] for sp in word_sps)
            shift = refined[wi]["start"] - cache_word_start
            
            for sp in word_sps:
                # Shift syllable timing from original cache timing to
                # refined (onset-snapped) timing.
                shifted_segs = []
                for seg in sp["note_segments"]:
                    shifted_segs.append({
                        "start": seg["start"] + shift,
                        "end": seg["end"] + shift,
                        "midi_note": seg["midi_note"],
                        "confidence": seg["confidence"]
                    })
                word_syllables[wi].append({
                    "text": sp["syllable_text"],
                    "start": sp["syllable_start"] + shift,
                    "end": sp["syllable_end"] + shift,
                    "source": "cache",
                    "note_segments": shifted_segs,
                    "pitch_trusted": sp["is_trusted"]
                })
        
        # Attach to refined words
        for wi, word in enumerate(refined):
            if word_syllables[wi]:
                # Sort by start time within the word
                word_syllables[wi].sort(key=lambda s: s["start"])
                word["syllables"] = word_syllables[wi]
            else:
                # No cached syllables for this word - use pyphen fallback
                word["syllables"] = [{
                    "text": word["word"],
                    "start": word["start"],
                    "end": word["end"],
                    "source": "fallback",
                    "note_segments": [{
                        "start": word["start"],
                        "end": word["end"],
                        "midi_note": word.get("pitch", 60),
                        "confidence": 0.5
                    }],
                    "pitch_trusted": False
                }]
    else:
        # No v2 cache - fall back to old per-word pitch logic
        # (This path is for backward compatibility with old caches)
        starts = np.array([r["start"] for r in refined], dtype=float)
        ends = np.array([r["end"] for r in refined], dtype=float)

        f0 = voiced = probs = times = None
        if vocals_stem:
            try:
                import librosa
                y, sr = librosa.load(str(vocals_stem), sr=22050, mono=True)
                f0, voiced, probs = librosa.pyin(
                    y,
                    fmin=librosa.note_to_hz("C2"),
                    fmax=librosa.note_to_hz("C6"),
                    sr=sr,
                    frame_length=2048,
                )
                times = librosa.times_like(f0, sr=sr)
            except Exception:
                pass

        pitches = _resolve_pitches(starts, ends, note_events, times, f0, voiced, probs)
        for r, p in zip(refined, pitches):
            r["pitch"] = int(max(VOCAL_MIDI_MIN, min(VOCAL_MIDI_MAX, p)))
        
        # Run syllable segmentation for display purposes
        lrc_data = None
        if lrc_path and Path(lrc_path).exists():
            lrc_data = lyrics_data.get("lyrics_data", [])
        refined = segment_all_words_to_syllables(
            refined,
            lrc_data=lrc_data,
            whisperx_alignment=alignment_result,
            whisperx_word_segments=lyrics_data.get("word_segments", []),
        )
        for word in refined:
            for syl in word.get("syllables", []):
                syl["note_segments"] = [{
                    "start": syl["start"],
                    "end": syl["end"],
                    "midi_note": word.get("pitch", 60),
                    "confidence": 0.5
                }]
                syl["pitch_trusted"] = False

    refined = _clamp_syllable_regions(refined)
    return {
        "metadata": {
            "total_beats": len(beat_times),
            "total_words": len(refined)
        },
        "synced_lyrics": _dedup_final_synced(refined)
    }


def run_step_4(beats_filepath, lyrics_filepath, output_filepath, vocals_stem=None, lrc_path=None):
    """Main execution function for Step 4.

    ``vocals_stem`` optionally supplies the vocal stem WAV so each word's start
    snaps to the true sung attack rather than WhisperX's late boundary.
    ``lrc_path`` optionally supplies the original LRC file for syllable parsing.
    """
    if not os.path.exists(beats_filepath) or not os.path.exists(lyrics_filepath):
        raise FileNotFoundError("Could not find the input JSON files from steps 2 and 3.")

    beats_data = load_json(beats_filepath)
    lyrics_data = load_json(lyrics_filepath)

    print(f"Loaded {len(beats_data['beat_times'])} beats and {len(lyrics_data['word_segments'])} word segments.")

    synced_output = sync_lyrics_to_beats(beats_data, lyrics_data, vocals_stem=vocals_stem, lrc_path=lrc_path)

    with open(output_filepath, 'w') as f:
        json.dump(synced_output, f, indent=4)

    print(f"Successfully wrote synced track data to {output_filepath}")
