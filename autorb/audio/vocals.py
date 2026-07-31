#!/usr/bin/env python

import click
from pathlib import Path
import re
import os
import torch
import json

import numpy as np

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NumpyEncoder, self).default(obj)

# Suppress TensorFlow C++ logging spam before importing basic_pitch
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
from basic_pitch.inference import predict
import whisperx

def process_vocals(vocal_stem_path, lrc_path, out_dir):
    """
    Parses the LRC file, force-aligns words via WhisperX, extracts vocal pitches,
    and caches the result to JSON.
    """
    vocal_stem_path = Path(vocal_stem_path)
    lrc_path = Path(lrc_path)
    out_dir = Path(out_dir)
    
    click.echo(f"Parsing LRC lyrics from {lrc_path.name}...")
    
    lyrics_data = []
    lrc_pattern = re.compile(r'\[(\d+):(\d+\.\d+)\](.*)')
    
    with open(lrc_path, 'r', encoding='utf-8') as f:
        for line in f:
            match = lrc_pattern.search(line)
            if match:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                text = match.group(3).strip()
                if text:
                    timestamp = (minutes * 60) + seconds
                    lyrics_data.append({"time": timestamp, "text": text})
                    
    click.echo(f"Successfully parsed {len(lyrics_data)} lyric lines.")
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    click.echo(f"Loading WhisperX alignment model on {device}...")
    audio = whisperx.load_audio(str(vocal_stem_path))
    audio_duration = len(audio) / 16000.0

    whisperx_transcript = []
    for i, line in enumerate(lyrics_data):
        start_time = line["time"]
        end_time = lyrics_data[i+1]["time"] if i + 1 < len(lyrics_data) else audio_duration
        whisperx_transcript.append({"text": line["text"], "start": start_time, "end": end_time})

    model_a, metadata = whisperx.load_align_model(language_code="en", device=device)
    
    click.echo("Running forced alignment to extract precise word and syllable timestamps...")
    alignment_result = whisperx.align(
        whisperx_transcript, model_a, metadata, audio, device, return_char_alignments=True
    )
    
    word_segments = alignment_result["word_segments"]
    click.echo(f"Successfully aligned {len(word_segments)} words to the audio.")

    click.echo("Extracting vocal pitches using Spotify's Basic Pitch...")
    _, _, note_events = predict(str(vocal_stem_path))
    click.echo(f"Extracted {len(note_events)} distinct vocal notes.")
    
    # Cache the extracted data
    cache_data = {
        "lyrics_data": lyrics_data,
        "word_segments": word_segments,
        "note_events": note_events
    }
    
    cache_path = out_dir / "vocals_cache.json"
    with open(cache_path, "w") as f:
        json.dump(cache_data, f, indent=4, cls=NumpyEncoder)
        
    click.echo(f"Vocals data cached to {cache_path}")
    
    return lyrics_data, word_segments, note_events

def load_vocals_cache(out_dir):
    """Loads previously cached vocal data from the output directory."""
    cache_path = Path(out_dir) / "vocals_cache.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"Vocals cache not found at {cache_path}")
        
    with open(cache_path, "r") as f:
        data = json.load(f)
        
    return data["lyrics_data"], data["word_segments"], data["note_events"]
