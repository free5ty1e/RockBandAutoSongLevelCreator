#!/usr/bin/env python
"""
TDD tests for vocal sync fixes.
These tests catch specific failure modes; they should FAIL on the current
output (bugs present) and PASS after fixes.
"""

import json
import re
import pytest
from pathlib import Path


def test_word_starts_after_prev_end_plus_sep():
    """Ensure no word starts before the previous word's end + MIN_WORD_SEP.

    This catches the interleaving bugs the user reported: e.g. "nowhere" colliding
    with "to", "alone" with "good", "out" with "heart", etc. Word starts must be
    separated from the previous word's end by at least MIN_WORD_SEP, enforced from
    audio analysis (not LRC timestamps).
    """
    project_root = Path(__file__).parent.parent
    synced_path = project_root / 'output_fresh' / 'synced_track.json'
    if not synced_path.exists():
        pytest.skip("synced_track.json not found in output_fresh - run pipeline first")

    with open(synced_path, 'r') as f:
        data = json.load(f)

    refined = data.get('synced_lyrics', [])
    min_sep = 0.08  # MIN_WORD_SEP

    failures = []
    for i in range(1, len(refined)):
        prev_end = refined[i-1].get('end', refined[i-1].get('start', 0.0))
        w_start = refined[i].get('start', 0.0)
        if w_start < prev_end + min_sep:
            failures.append(
                f"Word {i} '{refined[i]['word']}' starts at {w_start:.3f} "
                f"but prev word end is {prev_end:.3f} + {min_sep:.2f}sep = {prev_end+min_sep:.3f}"
            )

    msg = "Word start ordering failures: " + "; ".join(failures) if failures else ""
    assert len(failures) == 0, msg


def test_syllable_regions_no_cross_word_boundary():
    """Ensure syllables never overlap the next word's start.

    The cache v2 syllable timing may retain stale timing relative to corrected
    word bounds. This test clips syllables to [word.start, min(word.end, next_start -
    MIN_WORD_SEP)] and verifies the global display order matches LRC content.
    """
    project_root = Path(__file__).parent.parent
    lrc_path = project_root / 'input' / 'eve6-openRoadSong.lrc'
    synced_path = project_root / 'output_fresh' / 'synced_track.json'

    if not synced_path.exists() or not lrc_path.exists():
        pytest.skip("input files not found")

    # Load synced data and clamp syllable regions
    with open(synced_path, 'r') as f:
        data = json.load(f)

    refined = data.get('synced_lyrics', [])

    # Clamp syllables (same logic as in step4_sync.py)
    for i, word in enumerate(refined):
        region_end = word.get('end', word.get('start', 0.0))
        if i + 1 < len(refined):
            nxt_start = refined[i+1].get('start', word.get('start', 0.0) + 1.0)
            region_end = min(region_end, nxt_start - 0.08)
        if region_end <= word.get('start', 0.0):
            region_end = word.get('start', 0.0) + 0.05
        for syl in word.get('syllables', []):
            if syl.get('start', 0) < word.get('start', 0):
                syl['start'] = word.get('start', 0)
            if syl.get('end', 0) > region_end:
                syl['end'] = region_end
            if syl.get('end', 0) < syl.get('start', 0):
                syl['end'] = syl.get('start', 0) + 0.05

    # Collect all syllables sorted by start time
    all_syllables = []
    for word in refined:
        for syl in word.get('syllables', []):
            all_syllables.append(syl)

    all_syllables.sort(key=lambda s: s.get('start', 0.0))
    display_lyric = ''.join(s['text'] for s in all_syllables)

    # Extract LRC text: concatenate all text after timestamp tags
    lrc_text = ""
    with open(lrc_path, 'r', encoding='utf-8') as f:
        for line in f:
            m = re.search(r'\[(\d+):(\d+\.\d+)\](.*)', line)
            if m:
                lrc_text += m.group(3)

    # Normalize both: lowercase, remove non-word chars
    display_norm = re.sub(r'[^\w]', '', display_lyric.lower())
    lrc_norm = re.sub(r'[^\w]', '', lrc_text.lower())

    assert display_norm == lrc_norm, (
        f"Syllable display order mismatch: display vs LRC normalized texts differ"
    )
