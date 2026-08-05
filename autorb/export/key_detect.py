#!/usr/bin/env python

import logging

logger = logging.getLogger(__name__)

# Krumhansl-Schmuckler key profiles: relative weights for the 12 pitch classes
# starting from the tonic (index 0 = tonic). Major and minor are the two tonalities
# Rock Band supports via (song_tonality 0) / (song_tonality 1).
KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

# C3 authoring convention: tonic note is a chromatic pitch class where 0 = C.
# (The authoring guide's "0=C, 1=D..." wording is a simplification; real RB3DX
# DTA files use values 0-11, e.g. vocal_tonic_note 11 for B, 9 for A.)
PITCH_CLASS_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def detect_vocal_key(note_events, fallback_tonic=4, fallback_tonality=0):
    """Estimate the song key from a list of vocal note events.

    Each event is a sequence whose first three elements are
    ``[start_seconds, end_seconds, midi_pitch]`` (Basic-Pitch output).

    Returns ``(tonic_pitch_class, tonality)`` where ``tonic_pitch_class`` is
    0-11 (0 = C) and ``tonality`` is 0 for major or 1 for minor, matching the
    ``(vocal_tonic_note ...)`` / ``(song_tonality ...)`` DTA fields.
    """
    if not note_events:
        logger.warning("No vocal note events; defaulting to tonic %s, tonality %s",
                       fallback_tonic, fallback_tonality)
        return fallback_tonic, fallback_tonality

    weights = [0.0] * 12
    total = 0.0
    for event in note_events:
        try:
            start, end, pitch = float(event[0]), float(event[1]), int(event[2])
        except (TypeError, ValueError, IndexError):
            continue
        if pitch < 0:
            continue
        duration = max(0.0, end - start)
        if duration <= 0:
            duration = 1.0
        weights[pitch % 12] += duration
        total += duration

    if total <= 0:
        logger.warning("No valid vocal note events; defaulting to tonic %s, tonality %s",
                       fallback_tonic, fallback_tonality)
        return fallback_tonic, fallback_tonality

    # Normalize the observed pitch-class distribution.
    obs = [w / total for w in weights]

    best_score = float("-inf")
    best = (fallback_tonic, fallback_tonality)
    for tonic in range(12):
        for tonality, profile in ((0, KS_MAJOR), (1, KS_MINOR)):
            # rotated[pc] = profile[(pc - tonic) % 12]: weight of a pitch class
            # is the profile degree of its distance above the tonic.
            rotated = profile[-tonic:] + profile[:-tonic]
            score = _cosine(obs, rotated)
            if score > best_score:
                best_score = score
                best = (tonic, tonality)

    logger.info("Detected vocal key: %s %s (vocal_tonic_note %d, song_tonality %d)",
                PITCH_CLASS_NAMES[best[0]], "major" if best[1] == 0 else "minor",
                best[0], best[1])
    return best


def _cosine(a, b):
    """Cosine similarity between two equal-length lists."""
    num = sum(x * y for x, y in zip(a, b))
    den_a = sum(x * x for x in a) ** 0.5
    den_b = sum(y * y for y in b) ** 0.5
    if den_a == 0 or den_b == 0:
        return 0.0
    return num / (den_a * den_b)
