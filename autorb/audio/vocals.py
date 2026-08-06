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

from autorb.pitch.inference import predict
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

    click.echo("Cross-checking pitch with librosa pyin (octave/quantization guard)...")
    _annotate_pyin_pitches(vocal_stem_path, word_segments)
    
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

def _annotate_pyin_pitches(vocal_stem_path, word_segments):
    """Adds ``pyin_pitch``/``pyin_confidence`` to each word segment.

    Basic-Pitch (the primary vocal pitch source) occasionally produces octave
    or hallucinated notes on Demucs vocal stems. librosa's ``pyin`` computes a
    frame-level fundamental over the same stem and, for a monophonic vocal, its
    median is a reliable tiebreaker when the two strongly disagree. Words with
    little voiced content or low confidence keep ``pyin_pitch=None`` and the
    sync stage falls back to Basic-Pitch alone.
    """
    import librosa
    y, sr = librosa.load(str(vocal_stem_path), sr=22050, mono=True)
    f0, voiced, probs = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C6"),
        sr=sr,
        frame_length=2048,
    )
    times = librosa.times_like(f0, sr=sr)

    def hz_to_midi(f):
        return 69.0 + 12.0 * np.log2(f / 440.0)

    for seg in word_segments:
        start = seg.get("start", seg.get("time", 0.0))
        end = seg.get("end", start + 0.3)
        i0 = int(np.searchsorted(times, start))
        i1 = max(i0 + 1, int(np.searchsorted(times, end)))
        mask = voiced[i0:i1] & (probs[i0:i1] > 0.6)
        if not mask.any():
            seg["pyin_pitch"] = None
            seg["pyin_confidence"] = 0.0
            continue
        midis = hz_to_midi(f0[i0:i1][mask])
        seg["pyin_pitch"] = float(np.median(midis))
        seg["pyin_confidence"] = float(np.median(probs[i0:i1][mask]))

def load_vocals_cache(out_dir):
    """Loads previously cached vocal data from the output directory."""
    cache_path = Path(out_dir) / "vocals_cache.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"Vocals cache not found at {cache_path}")
        
    with open(cache_path, "r") as f:
        data = json.load(f)
        
    return data["lyrics_data"], data["word_segments"], data["note_events"]
