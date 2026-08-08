#!/usr/bin/env python
"""
Validation test: LRC lyrics must match reconstructed syllables exactly.

This test ensures that:
1. The number of words in LRC matches the output
2. Each word's syllables can be joined back to form the original word
3. No words are lost, duplicated, or corrupted
"""

import pytest
import re
from pathlib import Path


def extract_lrc_words(lrc_path: Path) -> list:
    """Extract words from LRC file in order."""
    words = []
    pattern = re.compile(r'\[(\d+):(\d+\.\d+)\](.*)')
    with open(lrc_path, 'r', encoding='utf-8') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                text = match.group(3).strip()
                if text:
                    words.extend(text.split())
    return words


def reconstruct_words_from_synced(synced_data: dict) -> list:
    """Reconstruct words by joining syllable texts."""
    reconstructed = []
    for word in synced_data.get('synced_lyrics', []):
        syls = word.get('syllables', [])
        if syls:
            reconstructed_word = ''.join(s['text'] for s in syls)
            reconstructed.append(reconstructed_word)
        else:
            reconstructed.append(word.get('word', word.get('lyric', '')))
    return reconstructed


def test_lrc_vs_synced_lyrics_parity():
    """Test that synced track lyrics match LRC exactly."""
    # Paths
    project_root = Path(__file__).parent.parent
    lrc_path = project_root / 'input' / 'eve6-openRoadSong.lrc'
    synced_path = project_root / 'output_test' / 'synced_track.json'
    
    if not synced_path.exists():
        pytest.skip("synced_track.json not found - run pipeline first")
    
    # Load data
    lrc_words = extract_lrc_words(lrc_path)
    with open(synced_path, 'r') as f:
        synced_data = json.load(f)
    reconstructed = reconstruct_words_from_synced(synced_data)
    
    # Check counts match
    assert len(lrc_words) == len(reconstructed), \
        f"Word count mismatch: LRC has {len(lrc_words)}, synced has {len(reconstructed)}"
    
    # Check each word matches (allowing punctuation normalization)
    mismatches = []
    for i, (lrc, rec) in enumerate(zip(lrc_words, reconstructed)):
        # Normalize: remove punctuation for comparison
        lrc_norm = re.sub(r'[^\w]', '', lrc.lower())
        rec_norm = re.sub(r'[^\w]', '', rec.lower())
        if lrc_norm != rec_norm:
            mismatches.append((i, lrc, rec))
    
    assert len(mismatches) == 0, \
        f"Found {len(mismatches)} word mismatches:\n" + \
        "\n".join(f"  Index {i}: LRC='{lrc}' vs RECONSTRUCTED='{rec}'" for i, lrc, rec in mismatches[:20])


def test_no_duplicate_words_in_sequence():
    """Test that synced words don't have unexpected duplicates."""
    project_root = Path(__file__).parent.parent
    synced_path = project_root / 'output_test' / 'synced_track.json'
    
    if not synced_path.exists():
        pytest.skip("synced_track.json not found")
    
    with open(synced_path, 'r') as f:
        synced_data = json.load(f)
    
    synced_words = [w['word'] for w in synced_data['synced_lyrics']]
    
    # Check against LRC - they should have the same sequence
    lrc_words = extract_lrc_words(project_root / 'input' / 'eve6-openRoadSong.lrc')
    
    assert synced_words == lrc_words, \
        "Synced word sequence does not match LRC sequence"


import json
if __name__ == "__main__":
    test_lrc_vs_synced_lyrics_parity()
    test_no_duplicate_words_in_sequence()
    print("All validation tests passed!")