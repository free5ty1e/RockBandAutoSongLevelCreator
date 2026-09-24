#!/usr/bin/env python
"""
Quality validation tests for AutoRB pipeline.

These tests detect musical/alignment issues that make charts feel wrong in-game:
- Duplicate consecutive words
- Syllable split duplication (word appears as whole + split syllables)
- Sustain notes cut short (last word of LRC line doesn't extend to next line)
- Pitch instability in monotonous sections
- Pitch ordering correctness (higher sung pitch = higher MIDI note)
"""

import pytest
import json
from pathlib import Path


class TestSyncedTrackQuality:
    """Tests that validate the synced_track.json output quality."""

    @pytest.fixture
    def synced_track(self):
        """Load synced_track.json from output directory."""
        path = Path("output/synced_track.json")
        if not path.exists():
            pytest.skip("output/synced_track.json not found - run pipeline first")
        with open(path) as f:
            return json.load(f)

    @pytest.fixture
    def lrc_lines(self):
        """Parse LRC file to get line-level timestamps."""
        path = Path("input/eve6-openRoadSong.lrc")
        if not path.exists():
            pytest.skip("LRC file not found")
        import re
        lines = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                match = re.match(r'\[(\d+):(\d+\.\d+)\](.*)', line)
                if match:
                    minutes = int(match.group(1))
                    seconds = float(match.group(2))
                    text = match.group(3).strip()
                    timestamp = minutes * 60 + seconds
                    words = text.split() if text else []
                    lines.append({
                        'timestamp': timestamp,
                        'text': text,
                        'words': words
                    })
        return lines

    def test_no_duplicate_consecutive_words(self, synced_track):
        """
        No word should appear consecutively in the synced track
        unless it actually appears twice in a row in the LRC.
        """
        synced_lyrics = synced_track.get('synced_lyrics', [])
        duplicates = []
        prev_word = None
        for i, entry in enumerate(synced_lyrics):
            word = entry.get('word', '').lower().strip('.,?!\'"')
            if word and word == prev_word:
                duplicates.append((i, word))
            prev_word = word

        assert not duplicates, f"Found duplicate consecutive words: {duplicates}"

    def test_each_lrc_word_appears_once_in_synced(self, synced_track, lrc_lines):
        """
        Each word from the LRC should appear exactly once in the synced track.
        No word should appear as both a whole word AND split into syllables.
        """
        synced_lyrics = synced_track.get('synced_lyrics', [])
        
        # Build set of normalized LRC words (excluding timestamp-only lines)
        lrc_words = []
        for line in lrc_lines:
            for word in line['words']:
                normalized = word.lower().strip('.,?!\'"')
                if normalized:
                    lrc_words.append(normalized)
        
        # Build set of normalized synced words
        synced_words = []
        for entry in synced_lyrics:
            word = entry.get('word', '').lower().strip('.,?!\'"')
            if word:
                synced_words.append(word)
        
        # Check for words that appear more times in synced than in LRC
        from collections import Counter
        lrc_counts = Counter(lrc_words)
        synced_counts = Counter(synced_words)
        
        overrepresented = []
        for word, count in synced_counts.items():
            lrc_count = lrc_counts.get(word, 0)
            if count > lrc_count:
                overrepresented.append((word, count, lrc_count))
        
        assert not overrepresented, \
            f"Words appearing more in synced than LRC: {overrepresented}"

    def test_syllable_split_matches_word(self, synced_track):
        """
        When a word is split into syllables, the concatenated syllables
        should equal the original word (no missing/extra letters).
        """
        synced_lyrics = synced_track.get('synced_lyrics', [])
        
        mismatches = []
        for entry in synced_lyrics:
            word = entry.get('word', '').lower().strip('.,?!\'"')
            syllables = entry.get('syllables', [])
            if not syllables:
                continue
            reconstructed = ''.join(s.get('text', '').lower() for s in syllables)
            # Remove non-alphabetic for comparison
            word_clean = ''.join(c for c in word if c.isalpha())
            recon_clean = ''.join(c for c in reconstructed if c.isalpha())
            if word_clean != recon_clean:
                mismatches.append({
                    'word': word,
                    'syllables': [s.get('text', '') for s in syllables],
                    'reconstructed': reconstructed
                })
        
        assert not mismatches, f"Syllable reconstruction mismatches: {mismatches}"

    @pytest.mark.xfail(strict=True, reason=(
        "v0.1.9 deliberately clips word ends to the last voiced/RMS frame of each "
        "word's own region (_audio_word_end, README 'Audio-derived note ends'), not "
        "to the next LRC line timestamp -- so a line's last word legitimately ends "
        "before the next line begins (gaps up to ~5.9s for 'forgotten'). This test "
        "asserts the pre-v0.1.9 line-sustain behavior. strict=True: flip when the "
        "roadmap phrase-aware sustain is implemented."
    ))
    def test_sustain_last_word_of_lrc_line(self, synced_track, lrc_lines):
        """
        The last word of each LRC line should extend to (or near) the next LRC line's timestamp.
        This ensures sustained notes at end of phrases aren't cut short.
        """
        synced_lyrics = synced_track.get('synced_lyrics', [])
        
        # Map LRC line index to its last word's end time in synced track
        # We need to match LRC lines to synced entries
        lrc_word_idx = 0
        issues = []
        
        for line_idx, line in enumerate(lrc_lines):
            if not line['words']:
                continue
            last_word_text = line['words'][-1].lower().strip('.,?!\'"')
            next_line_time = lrc_lines[line_idx + 1]['timestamp'] if line_idx + 1 < len(lrc_lines) else None
            
            # Find this word in synced_lyrics
            found = False
            for i in range(lrc_word_idx, len(synced_lyrics)):
                synced_word = synced_lyrics[i].get('word', '').lower().strip('.,?!\'"')
                if synced_word == last_word_text:
                    lrc_word_idx = i + 1
                    found = True
                    end_time = synced_lyrics[i].get('end', 0)
                    
                    if next_line_time:
                        gap = next_line_time - end_time
                        # Allow up to 0.5s gap (breath), but not more
                        if gap > 0.5:
                            issues.append({
                                'line': line_idx,
                                'word': last_word_text,
                                'end_time': end_time,
                                'next_line_time': next_line_time,
                                'gap': gap
                            })
                    break
            
            if not found:
                issues.append({
                    'line': line_idx,
                    'word': last_word_text,
                    'error': 'Word not found in synced track'
                })
        
        assert not issues, f"Sustain cutoff issues: {issues}"

    def test_no_overlapping_word_ends(self, synced_track):
        """
        No word's end time should exceed the next word's start time.
        Overlaps cause notes to push each other late (cumulative drift).
        """
        synced_lyrics = synced_track.get('synced_lyrics', [])
        
        overlaps = []
        for i in range(len(synced_lyrics) - 1):
            curr_end = synced_lyrics[i].get('end', 0)
            next_start = synced_lyrics[i + 1].get('start', 0)
            if curr_end > next_start:
                overlaps.append({
                    'index': i,
                    'word': synced_lyrics[i].get('word'),
                    'end': curr_end,
                    'next_word': synced_lyrics[i + 1].get('word'),
                    'next_start': next_start,
                    'overlap': curr_end - next_start
                })
        
        assert not overlaps, f"Word end overlaps next word start: {overlaps[:10]}"


class TestMidiPitchQuality:
    """Tests that validate the MIDI chart pitch quality."""

    @pytest.fixture
    def midi_file(self):
        """Load the generated MIDI file."""
        path = Path("output/open_road_song.mid")
        if not path.exists():
            pytest.skip("MIDI file not found - run pipeline first")
        import mido
        return mido.MidiFile(str(path))

    @pytest.fixture
    def vocal_track(self, midi_file):
        """Extract PART VOCALS track."""
        for track in midi_file.tracks:
            if track.name == 'PART VOCALS':
                return track
        pytest.fail("PART VOCALS track not found")

    def test_pitch_stability_in_monotonous_sections(self, vocal_track):
        """
        In sections where the singer holds a steady pitch, MIDI notes should not jump.
        Detect runs of notes where pitch variation exceeds threshold for 'monotonous' sections.
        """
        import mido
        
        # Extract note_on events with pitch, EXCLUDING phrase markers (note 105)
        notes = []
        tick = 0
        for msg in vocal_track:
            tick += msg.time
            if msg.type == 'note_on' and msg.velocity > 0 and msg.note != 105:
                notes.append({'tick': tick, 'pitch': msg.note})
        
        # Find runs of notes with similar timing (same phrase) and check pitch stability
        # Group notes that are close in time (within ~200ms = ~1000 ticks at 480 PPQ)
        unstable_runs = []
        i = 0
        while i < len(notes):
            run = [notes[i]]
            j = i + 1
            while j < len(notes) and notes[j]['tick'] - notes[j-1]['tick'] < 1000:
                run.append(notes[j])
                j += 1
            
            if len(run) >= 4:  # At least 4 notes in quick succession
                pitches = [n['pitch'] for n in run]
                pitch_range = max(pitches) - min(pitches)
                # If pitch range > 5 semitones in a fast run, it's likely unstable
                if pitch_range > 5:
                    unstable_runs.append({
                        'start_tick': run[0]['tick'],
                        'end_tick': run[-1]['tick'],
                        'pitches': pitches,
                        'range': pitch_range,
                        'note_count': len(run)
                    })
            
            i = j if j > i + 1 else i + 1
        
        # Allow some unstable runs (vibrato, actual melody), but not excessive
        assert len(unstable_runs) < 10, \
            f"Too many unstable pitch runs ({len(unstable_runs)}): {unstable_runs[:5]}"

    def test_pitch_ordering_correctness(self, vocal_track):
        """
        Higher sung pitch should map to higher MIDI note number.
        Compare adjacent syllables in the same phrase - if syllable A is audibly
        higher than B, its MIDI note should be higher.
        
        We approximate by checking that large pitch jumps in MIDI correspond to
        actual melodic intervals, not random noise.
        """
        import mido
        
        notes = []
        tick = 0
        for msg in vocal_track:
            tick += msg.time
            if msg.type == 'note_on' and msg.velocity > 0 and msg.note != 105:
                notes.append({'tick': tick, 'pitch': msg.note})
        
        # Check for inversions: adjacent notes where pitch jumps up then immediately down
        # by more than an octave (indicates octave error)
        inversions = []
        for i in range(1, len(notes) - 1):
            prev = notes[i-1]['pitch']
            curr = notes[i]['pitch']
            next_p = notes[i+1]['pitch']
            
            # Up then down by >12 semitones = likely octave flip
            if curr - prev > 6 and prev - next_p > 12:
                inversions.append({
                    'index': i,
                    'prev': prev,
                    'curr': curr,
                    'next': next_p
                })
            # Down then up by >12 semitones
            if prev - curr > 6 and next_p - prev > 12:
                inversions.append({
                    'index': i,
                    'prev': prev,
                    'curr': curr,
                    'next': next_p
                })
        
        assert len(inversions) < 5, \
            f"Too many pitch inversions (likely octave errors): {inversions[:10]}"

    def test_vocal_range_reasonable(self, vocal_track):
        """
        All vocal notes should be within reasonable vocal range (MIDI 40-85).
        Notes outside this range indicate pitch detection errors.
        """
        import mido
        
        out_of_range = []
        tick = 0
        for msg in vocal_track:
            tick += msg.time
            if msg.type == 'note_on' and msg.velocity > 0 and msg.note != 105:
                if msg.note < 40 or msg.note > 85:
                    out_of_range.append({'tick': tick, 'pitch': msg.note})
        
        assert not out_of_range, f"Notes outside vocal range (40-85): {out_of_range[:10]}"


class TestLyricTimingAccuracy:
    """Tests that validate lyric timing accuracy against LRC."""

    @pytest.fixture
    def synced_track(self):
        path = Path("output/synced_track.json")
        if not path.exists():
            pytest.skip("output/synced_track.json not found")
        with open(path) as f:
            return json.load(f)

    @pytest.mark.xfail(strict=True, reason=(
        "v0.1.9 deliberately snaps the first word's start to the vocal-stem audio "
        "onset (README: 'LRC timestamps are suggestions only -- WhisperX decides'), "
        "not to the LRC timestamp. 'Tonight' snaps to an onset at 0.255s vs the LRC "
        "0.610s. This test asserts the pre-v0.1.9 LRC-proximity assumption. strict=True: "
        "flip once onset-snapping regresses toward LRC-gating."
    ))
    def test_first_word_timing_close_to_lrc(self, synced_track):
        """First word should start close to first LRC timestamp (within 200ms)."""
        synced_lyrics = synced_track.get('synced_lyrics', [])
        if not synced_lyrics:
            pytest.skip("No synced lyrics")
        
        first_word_start = synced_lyrics[0].get('start', 0)
        # First LRC timestamp is 00:00.61 = 0.61s
        lrc_first = 0.61
        diff = abs(first_word_start - lrc_first)
        assert diff < 0.2, f"First word timing off by {diff:.3f}s (LRC: {lrc_first}, synced: {first_word_start})"

    def test_word_order_matches_lrc(self, synced_track):
        """Synced words should appear in same order as LRC (no reordering)."""
        synced_lyrics = synced_track.get('synced_lyrics', [])
        
        # Check that start times are strictly increasing (monotonic)
        non_monotonic = []
        prev_start = -1
        for i, entry in enumerate(synced_lyrics):
            start = entry.get('start', 0)
            if start < prev_start:
                non_monotonic.append({
                    'index': i,
                    'word': entry.get('word'),
                    'start': start,
                    'prev_start': prev_start
                })
            prev_start = start
        
        assert not non_monotonic, f"Non-monotonic word start times: {non_monotonic[:5]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])