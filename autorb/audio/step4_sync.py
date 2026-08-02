#!/usr/bin/env python

import json
import os

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
    
    def pitch_at(time_sec):
        """Returns the Basic-Pitch note (midi pitch, end time) active at time_sec."""
        best = None
        for note in note_events:
            note_start, note_end, note_pitch = note[0], note[1], note[2]
            if note_start <= time_sec <= note_end:
                return note_pitch
            if best is None or abs(note_start - time_sec) < best[0]:
                best = (abs(note_start - time_sec), note_pitch, note_end)
        return best[1] if best else None
    
    for i, segment in enumerate(word_segments):
        word = segment["word"]
        start_time = segment["start"]
        end_time = segment.get("end", start_time + 0.5)
        
        # Find the closest beat to the start time of the word
        closest_beat = min(beat_times, key=lambda b: abs(b - start_time))
        beat_index = beat_times.index(closest_beat)
        
        pitch = pitch_at(start_time)
        if pitch is None:
            pitch = 60
        
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
