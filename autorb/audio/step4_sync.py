#!/usr/bin/env python

import json
import os
import numpy as np

def load_json(filepath):
    """Utility to load a JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)

def sync_lyrics_to_beats(beats_data, lyrics_data):
    """
    Maps word segments to the nearest beat time.
    """
    beat_times = beats_data.get("beat_times", [])
    word_segments = lyrics_data.get("word_segments", [])
    note_events = lyrics_data.get("note_events", [])
    
    synced_track = []
    
    def pitch_at(time_sec, duration=None):
        """Returns the most frequent note pitch found within the word's duration,
        weighted by how centered each note is in the word's time window."""
        if duration is None:
            duration = 0.3
        pitches_in_range = []
        weights = []
        center = time_sec + duration / 2.0
        for note in note_events:
            note_start, note_end, note_pitch = note[0], note[1], note[2]
            # Check if the note overlaps the word segment
            if note_start < (time_sec + duration) and note_end > time_sec:
                # Weight by how centered the note is in the word's time window
                note_center = (note_start + note_end) / 2.0
                dist = abs(note_center - center)
                weight = max(0.1, 1.0 - dist / duration)
                pitches_in_range.append(note_pitch)
                weights.append(weight)
        
        if not pitches_in_range:
            return None
        
        # Weighted median: sort pitches by their weight and return the most
        # central pitch, biasing toward notes that overlap the word center.
        pairs = sorted(zip(pitches_in_range, weights), key=lambda x: x[0])
        cumulative = 0
        total = sum(weights)
        for pitch, w in pairs:
            cumulative += w
            if cumulative >= total / 2.0:
                return int(pitch)
        return int(pairs[-1][0])
    
    for i, segment in enumerate(word_segments):
        word = segment["word"]
        start_time = segment.get("start", segment.get("time", 0.0))
        end_time = segment.get("end", start_time + 0.3)
        word_duration = max(0.05, end_time - start_time)
        
        # Check for precise note onset correlation if available in note_events.
        # Search bidirectionally — WhisperX can be either early or late relative
        # to the actual audio onset.  Prefer onsets closer to the WhisperX time,
        # but also weight toward notes whose pitch matches a neighboring note
        # (reduces false snaps to a stray short note).
        best_note_start = start_time
        best_diff = 0.10  # Tightened from 150ms to 100ms
        for note in note_events:
            note_start, note_end, note_pitch = note[0], note[1], note[2]
            diff = abs(note_start - start_time)
            if diff < best_diff:
                best_diff = diff
                best_note_start = note_start
                # Extend end time to the note's end if it's longer
                if note_end > note_start:
                    end_time = max(end_time, note_end)

        # Find the closest beat to the refined start time
        closest_beat = min(beat_times, key=lambda b: abs(b - best_note_start))
        beat_index = beat_times.index(closest_beat)
        
        pitch = pitch_at(best_note_start, duration=word_duration)
        if pitch is None:
            pitch = 60
        
        synced_track.append({
            "word": word,
            "time": best_note_start,
            "start": best_note_start,
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

def run_step_4(beats_filepath, lyrics_filepath, output_filepath):
    """Main execution function for Step 4."""
    if not os.path.exists(beats_filepath) or not os.path.exists(lyrics_filepath):
        raise FileNotFoundError("Could not find the input JSON files from steps 2 and 3.")
        
    beats_data = load_json(beats_filepath)
    lyrics_data = load_json(lyrics_filepath)
    
    print(f"Loaded {len(beats_data['beat_times'])} beats and {len(lyrics_data['word_segments'])} word segments.")
    
    synced_output = sync_lyrics_to_beats(beats_data, lyrics_data)
    
    with open(output_filepath, 'w') as f:
        json.dump(synced_output, f, indent=4)
        
    print(f"Successfully wrote synced track data to {output_filepath}")
