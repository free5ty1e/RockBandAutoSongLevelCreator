#!/usr/bin/env python

import json
import os
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
ONSET_SEARCH_BEFORE = 0.45   # max seconds before the WhisperX start to look
ONSET_SEARCH_AFTER = 0.05    # max seconds after it (WhisperX is rarely early)
ONSET_MAX_SHIFT = 0.30       # never snap more than this far (BP fallback only)
ONSET_SNAP_EARLY_MIN = 0.03  # only snap when WhisperX is at least this late
MIN_WORD_GAP = 0.02          # keep words from collapsing onto each other

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


def _detect_vocal_onsets(vocals_stem):
    """Return the true vocal-attack onsets (source-time seconds) for a stem.

    Runs librosa onset detection on the vocal stem: the attack (consonant +
    first energy burst) is the ground truth for when the singer actually starts
    a syllable. Both WhisperX word starts and Basic-Pitch note onsets run late
    (Basic-Pitch misses the earliest part of the attack — e.g. the first word
    of a song charted ~350ms late). Returns None when the stem cannot be read.
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
    return librosa.frames_to_time(frames, sr=sr).tolist()


def _refine_word_timing(segment, note_events, prev_sung_end, vocal_onsets=None):
    """Returns ``(start, end)`` for one word, snapped to the real sung onset.

    ``prev_sung_end`` is the charted end of the previous word; candidate onsets
    before it are rejected so the word cannot snap into a neighbour's note.

    When ``vocal_onsets`` (the vocal stem's true attacks) is available, snap the
    start to the EARLIEST onset in the search window — that is the actual sung
    attack, correcting WhisperX's systematic lateness AND Basic-Pitch's own lag
    (which left the first word of a song ~350ms late). Without it, fall back to
    snapping to the nearest Basic-Pitch onset (legacy behaviour).
    """
    start_time = segment.get("start", segment.get("time", 0.0))
    end_time = segment.get("end", start_time + 0.3)

    best_start = start_time
    best_diff = ONSET_MAX_SHIFT

    if vocal_onsets:
        early_candidates = [
            o for o in vocal_onsets
            if start_time - ONSET_SEARCH_BEFORE <= o <= start_time + ONSET_SEARCH_AFTER
            and o >= prev_sung_end - MIN_WORD_GAP
        ]
        if early_candidates:
            earliest = min(early_candidates)
            if start_time - earliest >= ONSET_SNAP_EARLY_MIN:
                best_start = earliest
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


def sync_lyrics_to_beats(beats_data, lyrics_data, vocals_stem=None, lrc_path=None):
    """
    Maps word segments to the nearest beat time.

    ``vocals_stem`` (optional) is the path to the vocal stem WAV; when given,
    its true attack onsets (librosa) drive the per-word start snap so charted
    notes land on the real sung onset instead of WhisperX's late boundary.
    
    ``lrc_path`` (optional) is the path to the LRC file for syllable-level timing.
    """
    beat_times = beats_data.get("beat_times", [])
    word_segments = lyrics_data.get("word_segments", [])
    note_events = lyrics_data.get("note_events", [])
    alignment_result = lyrics_data.get("alignment_result", {})
    
    # NEW: Load per-syllable pitch data from cache (v2 format)
    syllable_pitches = lyrics_data.get("syllable_pitches", [])

    vocal_onsets = _detect_vocal_onsets(vocals_stem) if vocals_stem else None
    if vocal_onsets:
        print(f"Detected {len(vocal_onsets)} vocal-stem onsets for word-start snapping.")

    # First pass: refine timings and collect word windows.
    refined = []
    prev_sung_end = float("-inf")
    for segment in sorted(word_segments, key=lambda s: s.get("start", s.get("time", 0.0))):
        word = segment["word"]
        start_time, end_time = _refine_word_timing(segment, note_events,
                                                   prev_sung_end, vocal_onsets)
        prev_sung_end = max(prev_sung_end, end_time)

        closest_beat = min(beat_times, key=lambda b: abs(b - start_time))
        beat_index = beat_times.index(closest_beat)

        refined.append({
            "word": word,
            "time": start_time,
            "start": start_time,
            "end": end_time,
            "beat_time": closest_beat,
            "beat_index": beat_index,
            "confidence_score": segment.get("score", 1.0)
        })

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
        # The syllable_pitches from cache are in the SAME ORDER as WhisperX
        # word_segments (284 entries each). The refined words are also sorted
        # from the same WhisperX word_segments. Match by INDEX, not time,
        # because refined words have extended end times that overlap with
        # subsequent syllables.
        #
        # Both lists should have the same length (one per WhisperX word).
        # If lengths differ, fall back to time-based matching.
        if len(syllable_pitches) == len(refined):
            for wi, (word, sp) in enumerate(zip(refined, syllable_pitches)):
                # Shift syllable timing from original WhisperX timing to
                # refined (onset-snapped) timing.
                shift = word["start"] - sp["syllable_start"]
                shifted_segs = []
                for seg in sp["note_segments"]:
                    shifted_segs.append({
                        "start": seg["start"] + shift,
                        "end": seg["end"] + shift,
                        "midi_note": seg["midi_note"],
                        "confidence": seg["confidence"]
                    })
                word["syllables"] = [{
                    "text": sp["syllable_text"],
                    "start": word["start"],
                    "end": word["end"],
                    "source": "cache",
                    "note_segments": shifted_segs,
                    "pitch_trusted": sp["is_trusted"]
                }]
        else:
            # Fallback: time-based matching (old behavior)
            word_syllables = [[] for _ in refined]
            for sp in syllable_pitches:
                syl_start = sp["syllable_start"]
                for wi, word in enumerate(refined):
                    if word["start"] - 0.1 <= syl_start <= word["end"] + 0.1:
                        word_syllables[wi].append({
                            "text": sp["syllable_text"],
                            "start": sp["syllable_start"],
                            "end": sp["syllable_end"],
                            "source": "cache",
                            "note_segments": sp["note_segments"],
                            "pitch_trusted": sp["is_trusted"]
                        })
                        break
            
            for wi, word in enumerate(refined):
                if word_syllables[wi]:
                    word_syllables[wi].sort(key=lambda s: s["start"])
                    word["syllables"] = word_syllables[wi]
                else:
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

    return {
        "metadata": {
            "total_beats": len(beat_times),
            "total_words": len(refined)
        },
        "synced_lyrics": refined
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
