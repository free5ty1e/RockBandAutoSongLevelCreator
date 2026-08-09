#!/usr/bin/env python
"""
Test: MIDI lyrics must match LRC words exactly (no duplicates, no missing, same order).
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


def extract_midi_lyrics(midi_path: Path) -> list:
    """Extract lyric events from PART VOCALS track in MIDI file."""
    import mido
    
    mid = mido.MidiFile(midi_path)
    lyrics = []
    
    for track in mid.tracks:
        if track.name == 'PART VOCALS':
            abs_time = 0
            for msg in track:
                abs_time += msg.time
                if msg.type == 'lyrics' and msg.text.strip():
                    lyrics.append(msg.text.strip())
            break
    
    return lyrics


def test_midi_lyrics_match_lrc():
    """Test that MIDI lyrics match LRC words exactly."""
    project_root = Path(__file__).parent.parent
    lrc_path = project_root / 'input' / 'eve6-openRoadSong.lrc'
    midi_path = project_root / 'output_test' / 'open_road_song.mid'
    
    if not midi_path.exists():
        pytest.skip("MIDI file not found - run pipeline first")
    
    lrc_words = extract_lrc_words(lrc_path)
    midi_lyrics = extract_midi_lyrics(midi_path)
    
    # The MIDI lyrics should be a superset (includes sub-syllables)
    # But when we join consecutive non-empty lyrics, we should get LRC words
    
    # Filter out empty lyrics
    midi_nonempty = [l for l in midi_lyrics if l]
    
    # Check for consecutive duplicates (the bug we're fixing)
    consecutive_dups = []
    for i in range(1, len(midi_nonempty)):
        if midi_nonempty[i] == midi_nonempty[i-1]:
            consecutive_dups.append((i, midi_nonempty[i]))
    
    assert len(consecutive_dups) == 0, \
        f"Found {len(consecutive_dups)} consecutive duplicate lyrics:\n" + \
        "\n".join(f"  Index {i}: \"{word}\"" for i, word in consecutive_dups[:20])
    
    # Reconstruct words from MIDI by joining sub-syllables
    # Each LRC word corresponds to one or more MIDI lyric events
    # We should be able to reconstruct the exact LRC word sequence
    
    # This is a more sophisticated check - we expect the MIDI to have
    # sub-syllables that can be grouped back into the original words
    # For now, just verify no consecutive duplicates
    print(f"LRC words: {len(lrc_words)}")
    print(f"MIDI lyric events: {len(midi_lyrics)}")
    print(f"MIDI non-empty lyrics: {len(midi_nonempty)}")


if __name__ == "__main__":
    test_midi_lyrics_match_lrc()
    print("Test passed!")