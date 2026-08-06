#!/usr/bin/env python

import json
import os
import numpy as np

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
VOCAL_MIDI_MIN, VOCAL_MIDI_MAX = 40, 84  # C2..C6 sane vocal range
PYIN_CORRECT_ST = 4.0  # override Basic-Pitch only when they disagree this much


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
                continue
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


def sync_lyrics_to_beats(beats_data, lyrics_data, vocals_stem=None):
    """
    Maps word segments to the nearest beat time.

    ``vocals_stem`` (optional) is the path to the vocal stem WAV; when given,
    its true attack onsets (librosa) drive the per-word start snap so charted
    notes land on the real sung onset instead of WhisperX's late boundary.
    """
    beat_times = beats_data.get("beat_times", [])
    word_segments = lyrics_data.get("word_segments", [])
    note_events = lyrics_data.get("note_events", [])
    
    vocal_onsets = _detect_vocal_onsets(vocals_stem) if vocals_stem else None
    if vocal_onsets:
        print(f"Detected {len(vocal_onsets)} vocal-stem onsets for word-start snapping.")
    
    synced_track = []
    
    def pitch_at(time_sec, duration):
        """Returns the pitch of the note that most dominates the word's window.

        Demucs vocal stems carry reverb/bleed, so Basic-Pitch often emits
        several simultaneous notes (one true vocal, the rest harmonics/echo).
        Weighting by overlap duration picks the sustained sung note instead of
        a spurious neighbour that merely sits near the window centre.
        """
        window_start = time_sec
        window_end = time_sec + max(0.05, duration)
        best_pitch = None
        best_overlap = 0.0
        for note in note_events:
            note_start, note_end, note_pitch = note[0], note[1], note[2]
            overlap = min(note_end, window_end) - max(note_start, window_start)
            if overlap <= 0.02:
                continue
            if overlap > best_overlap:
                best_overlap = overlap
                best_pitch = note_pitch
        return best_pitch
    
    # Process words in chronological order; the previous word's sung end keeps
    # each word's onset snap inside its own sung region.
    prev_sung_end = float("-inf")
    for segment in sorted(word_segments, key=lambda s: s.get("start", s.get("time", 0.0))):
        word = segment["word"]
        start_time, end_time = _refine_word_timing(segment, note_events, prev_sung_end, vocal_onsets)
        word_duration = max(0.05, end_time - start_time)
        prev_sung_end = max(prev_sung_end, end_time)

        # Find the closest beat to the refined start time
        closest_beat = min(beat_times, key=lambda b: abs(b - start_time))
        beat_index = beat_times.index(closest_beat)
        
        pitch = pitch_at(start_time, duration=word_duration)
        if pitch is None:
            pitch = 60
        pitch = int(max(VOCAL_MIDI_MIN, min(VOCAL_MIDI_MAX, pitch)))
        
        # Octave guard: when librosa pyin (cached per word) and Basic-Pitch
        # strongly disagree, a high-confidence median fundamental is the more
        # reliable vocal reading (Basic-Pitch is prone to octave/hallucinated
        # notes on stems). Only override when pyin is genuinely confident.
        pyin_pitch = segment.get("pyin_pitch")
        pyin_conf = segment.get("pyin_confidence", 0.0)
        if pyin_pitch is not None and pyin_conf >= 0.8:
            if abs(pyin_pitch - pitch) > PYIN_CORRECT_ST:
                pitch = int(max(VOCAL_MIDI_MIN, min(VOCAL_MIDI_MAX, round(pyin_pitch))))
        
        synced_track.append({
            "word": word,
            "time": start_time,
            "start": start_time,
            "end": end_time,
            "pitch": int(pitch),
            "beat_time": closest_beat,
            "beat_index": beat_index,
            "confidence_score": segment.get("score", 1.0)
        })
        
    return {
        "metadata": {
            "total_beats": len(beat_times),
            "total_words": len(synced_track)
        },
        "synced_lyrics": synced_track
    }

def run_step_4(beats_filepath, lyrics_filepath, output_filepath, vocals_stem=None):
    """Main execution function for Step 4.

    ``vocals_stem`` optionally supplies the vocal stem WAV so each word's start
    snaps to the true sung attack rather than WhisperX's late boundary.
    """
    if not os.path.exists(beats_filepath) or not os.path.exists(lyrics_filepath):
        raise FileNotFoundError("Could not find the input JSON files from steps 2 and 3.")
        
    beats_data = load_json(beats_filepath)
    lyrics_data = load_json(lyrics_filepath)
    
    print(f"Loaded {len(beats_data['beat_times'])} beats and {len(lyrics_data['word_segments'])} word segments.")
    
    synced_output = sync_lyrics_to_beats(beats_data, lyrics_data, vocals_stem=vocals_stem)
    
    with open(output_filepath, 'w') as f:
        json.dump(synced_output, f, indent=4)
        
    print(f"Successfully wrote synced track data to {output_filepath}")
