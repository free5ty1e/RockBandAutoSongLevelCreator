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

# whisperx.align pushes each segment's whole audio window through the wav2vec2
# alignment model in ONE forward pass (and builds a CTC trellis from the full
# text), so a segment that spans too much audio exhausts CPU memory (~291s of
# audio OOMs on a 7GB box while ~198s survives). Chunks of ~60s keep each
# forward pass small while leaving whisperx free to align every word inside.
ALIGN_CHUNK_SECONDS = 60.0


def _build_alignment_transcript(lyrics_data, audio_duration):
    """Build the coarse whisperx transcript segments (LRC times = suggestions).

    Groups lyric lines into ~60s chunks by their (suggested) LRC timestamps.
    WhisperX freely aligns each chunk's text within its audio window, so a
    badly late LRC line can no longer drag its whole phrase late — only a line
    within ~a second of a chunk boundary could land in the neighbouring chunk,
    which the downstream onset snapping absorbs.
    """
    segments = []
    line_idx = 0
    chunk_start = 0.0
    while chunk_start < audio_duration and line_idx < len(lyrics_data):
        chunk_end = min(chunk_start + ALIGN_CHUNK_SECONDS, audio_duration)
        chunk_lines = []
        while line_idx < len(lyrics_data):
            line_time = lyrics_data[line_idx]["time"]
            if line_time >= chunk_end:
                break
            chunk_lines.append(lyrics_data[line_idx])
            line_idx += 1
        if chunk_lines:
            segments.append({
                "text": " ".join(line["text"] for line in chunk_lines),
                "start": chunk_start,
                "end": chunk_end,
            })
        chunk_start = chunk_end
    return segments


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

    # The MP3 and the .lrc come from different sources, so LRC timestamps are
    # suggestions only — they carry a global offset and occasionally a badly
    # late line. Feeding whisperx one segment *per LRC line* is dangerous:
    # whisperx.align() slices the audio at each segment["start"] (a hard
    # boundary), so a late LRC line drags its entire phrase late and out of
    # the onset-snap recovery window downstream. Instead we hand whisperx a
    # handful of COARSE segments (one per ~60s of audio, grouped by LRC line
    # time) spanning the whole track; whisperx then freely aligns every word
    # to the actual vocal audio within each chunk, and the LRC timestamps are
    # used later only as phrase hints. (A single segment spanning the whole
    # track is ideal but pushes the whole song through the wav2vec2 align
    # model in one forward pass, which exhausts CPU memory on longer songs —
    # e.g. 291s dies silently while 198s survives.)
    whisperx_transcript = _build_alignment_transcript(lyrics_data, audio_duration)

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

    # NEW: Run per-syllable pitch tracking (dense pyin + change-point segmentation)
    click.echo("Running per-syllable pitch tracking...")
    from autorb.transcribe.syllables import segment_all_words_to_syllables
    from autorb.transcribe.pitch_tracking import (
        compute_vocal_pitch_per_syllable,
        build_melodic_contour_from_syllables,
        resolve_syllable_pitches_with_fallback,
    )
    
    # First, get syllable segmentation for all words
    synced_words = []
    for seg in word_segments:
        synced_words.append({
            "word": seg["word"],
            "start": seg.get("start", seg.get("time", 0.0)),
            "end": seg.get("end", seg.get("start", 0.0) + 0.3),
        })
    
    # Add syllable segmentation (pass original word_segments for WhisperX char mapping)
    synced_words = segment_all_words_to_syllables(
        synced_words,
        lrc_data=lyrics_data,
        whisperx_alignment=alignment_result,
        whisperx_word_segments=word_segments,  # Pass original for char->word mapping
    )
    
    # Collect all syllables across all words, WITH word index
    all_syllables = []
    for wi, word in enumerate(synced_words):
        for syl in word.get("syllables", []):
            syl_with_index = syl.copy()
            syl_with_index["word_index"] = wi
            all_syllables.append(syl_with_index)
    
    click.echo(f"Segmented into {len(all_syllables)} syllables.")
    
    # Compute pitch for each syllable
    syllable_pitches = compute_vocal_pitch_per_syllable(all_syllables, str(vocal_stem_path))
    
    # Build melodic contour from trusted syllables
    melodic_contour = build_melodic_contour_from_syllables(syllable_pitches)
    
    # Resolve untrusted syllables with Basic-Pitch fallback
    syllable_pitches = resolve_syllable_pitches_with_fallback(
        syllable_pitches, note_events, melodic_contour
    )
    
    # Convert to serializable format
    syllable_pitch_data = []
    for syl in syllable_pitches:
        segs = []
        for seg in syl.note_segments:
            segs.append({
                "start": seg.start,
                "end": seg.end,
                "midi_note": seg.midi_note,
                "confidence": seg.confidence,
            })
        syllable_pitch_data.append({
            "syllable_text": syl.syllable_text,
            "syllable_start": syl.syllable_start,
            "syllable_end": syl.syllable_end,
            "note_segments": segs,
            "is_trusted": syl.is_trusted,
            "word_index": syl.word_index,  # NEW: preserve word-syllable relationship
        })
    
    # Cache the extracted data (v2 format with per-syllable pitch)
    cache_data = {
        "version": 2,
        "lyrics_data": lyrics_data,
        "word_segments": word_segments,
        "note_events": note_events,
        "alignment_result": alignment_result,
        "syllable_pitches": syllable_pitch_data,  # NEW v2 format
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
        
    # Support both v1 and v2 cache formats
    if data.get("version") == 2:
        return data["lyrics_data"], data["word_segments"], data["note_events"], data.get("syllable_pitches", [])
    else:
        return data["lyrics_data"], data["word_segments"], data["note_events"], []
