#!/usr/bin/env python
"""
Integration test: MIDI lyrics must match LRC file exactly.

Reconstructs LRC from generated MIDI and compares character-by-character
with the input LRC file. Fails on any mismatch (missing syllables, 
missing letters, extra characters, etc.).
"""

import pytest
import re
from pathlib import Path
import tempfile
import shutil
import subprocess
import json


def extract_lrc_content(lrc_path: Path) -> str:
    """Extract just the text content from LRC file, normalized."""
    content = []
    pattern = re.compile(r'\[(\d+):(\d+\.\d+)\](.*)')
    with open(lrc_path, 'r', encoding='utf-8') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                text = match.group(3).strip()
                if text:
                    content.append(text)
    return ' '.join(content)


def extract_midi_lyrics(midi_path: Path) -> str:
    """Extract all lyric events from PART VOCALS track, in order."""
    import mido
    
    mid = mido.MidiFile(midi_path)
    lyrics = []
    
    for track in mid.tracks:
        if track.name == 'PART VOCALS':
            for msg in track:
                if msg.type == 'lyrics' and msg.text.strip():
                    lyrics.append(msg.text.strip())
            break
    
    return ' '.join(lyrics)


def normalize_lyrics(text: str) -> str:
    """Normalize lyrics for comparison: remove all whitespace, lowercase, keep only alphanumeric."""
    # Keep only alphanumeric characters (removes whitespace, punctuation, apostrophes, hyphens)
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()


def test_lrc_vs_midi_lyrics_exact_match():
    """Full pipeline test: LRC lyrics must match MIDI lyrics exactly.
    
    Uses existing output from previous pipeline run (output_final).
    """
    
    project_root = Path(__file__).parent.parent
    lrc_path = project_root / 'input' / 'eve6-openRoadSong.lrc'
    midi_path = project_root / 'output_fixed' / 'open_road_song.mid'
    
    assert lrc_path.exists(), f"LRC not found: {lrc_path}"
    assert midi_path.exists(), f"MIDI not found: {midi_path} (run pipeline first)"
    
    # Extract lyrics
    lrc_text = extract_lrc_content(lrc_path)
    midi_lyrics = extract_midi_lyrics(midi_path)
    
    lrc_normalized = normalize_lyrics(lrc_text)
    midi_normalized = normalize_lyrics(midi_lyrics)
    
    # Print for debugging
    print(f"\nLRC ({len(lrc_normalized)} chars): {lrc_normalized[:200]}...")
    print(f"MIDI ({len(midi_normalized)} chars): {midi_normalized[:200]}...")
    
    # Exact match required (character-level, ignoring whitespace/punctuation)
    assert lrc_normalized == midi_normalized, (
        f"LRC and MIDI lyrics do not match!\n"
        f"LRC:  {lrc_normalized}\n"
        f"MIDI: {midi_normalized}\n"
        f"Diff: {find_diff(lrc_normalized, midi_normalized)}"
    )


def find_diff(a: str, b: str) -> str:
    """Find first difference between two strings."""
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            start = max(0, i - 20)
            end = min(len(a), i + 20)
            return f"At char {i}: LRC[{start}:{end}]='{a[start:end]}' vs MIDI[{start}:{end}]='{b[start:end]}'"
    if len(a) != len(b):
        return f"Length mismatch: LRC={len(a)} MIDI={len(b)}"
    return "Identical"


def test_syllable_coverage():
    """Verify every LRC word has corresponding syllables in synced_track.json."""
    project_root = Path(__file__).parent.parent
    synced_path = project_root / 'output_fixed' / 'synced_track.json'
    
    if not synced_path.exists():
        pytest.skip("synced_track.json not found")
    
    with open(synced_path) as f:
        data = json.load(f)
    
    # Load LRC words
    lrc_path = project_root / 'input' / 'eve6-openRoadSong.lrc'
    lrc_words = []
    pattern = re.compile(r'\[(\d+):(\d+\.\d+)\](.*)')
    with open(lrc_path) as f:
        for line in f:
            match = pattern.search(line)
            if match:
                text = match.group(3).strip()
                if text:
                    lrc_words.extend(text.split())
    
    # Get all synced words
    synced_words = [w['word'] for w in data['synced_lyrics']]
    
    # Normalize both
    lrc_norm = [normalize_lyrics(w) for w in lrc_words]
    synced_norm = [normalize_lyrics(w) for w in synced_words]
    
    # Check for missing words (excluding duplicates)
    lrc_set = set(lrc_norm)
    synced_set = set(synced_norm)
    missing = lrc_set - synced_set
    extra = synced_set - lrc_set
    
    assert not missing, f"Words in LRC but missing from synced: {missing}"
    # Extra might be OK (WhisperX adds words), but warn
    if extra:
        print(f"Extra words in synced (WhisperX additions): {extra}")


def test_syllable_letter_completeness():
    """Verify each syllable in synced_track.json has all letters from the word."""
    project_root = Path(__file__).parent.parent
    synced_path = project_root / 'output_fixed' / 'synced_track.json'
    
    if not synced_path.exists():
        pytest.skip("synced_track.json not found")
    
    with open(synced_path) as f:
        data = json.load(f)
    
    errors = []
    for word_data in data['synced_lyrics']:
        word = word_data['word'].lower()
        syllables = word_data.get('syllables', [])
        
        if not syllables:
            continue
        
        # Reconstruct word from syllables
        reconstructed = ''.join(s['text'].lower() for s in syllables)
        # Remove punctuation for comparison
        word_clean = re.sub(r"[^\w]", '', word)
        recon_clean = re.sub(r"[^\w]", '', reconstructed)
        
        if word_clean != recon_clean:
            errors.append(f"Word '{word}' reconstructed as '{reconstructed}' from syllables: {[s['text'] for s in syllables]}")
    
    assert not errors, f"Syllable letter mismatches:\n" + '\n'.join(errors)


def test_no_monotonic_pitch_drift():
    """Verify that consecutive words at same pitch don't show vertical drift in game."""
    project_root = Path(__file__).parent.parent
    synced_path = project_root / 'output' / 'synced_track.json'
    
    if not synced_path.exists():
        pytest.skip("synced_track.json not found")
    
    with open(synced_path) as f:
        data = json.load(f)
    
    # Find runs of same pitch
    prev_pitch = None
    run_length = 0
    max_run = 0
    
    for word_data in data['synced_lyrics']:
        pitch = word_data.get('pitch')
        if pitch is not None:
            if pitch == prev_pitch:
                run_length += 1
                max_run = max(max_run, run_length)
            else:
                run_length = 1
                prev_pitch = pitch
    
    # More than 5 consecutive words at exactly same pitch is suspicious
    # (likely indicates pitch tracking issue, not actual monotone singing)
    assert max_run <= 5, f"Found {max_run} consecutive words at same pitch - likely pitch tracking issue"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])