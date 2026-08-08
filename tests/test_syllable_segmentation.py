#!/usr/bin/env python
"""
Tests for syllable segmentation module.
"""

import pytest
from autorb.transcribe.syllables import (
    parse_lrc_syllables,
    lrc_syllables_to_timed,
    pyphen_syllables,
    whisperx_chars_to_syllables,
    segment_word_to_syllables,
    segment_all_words_to_syllables,
    Syllable,
)


class TestParseLrcSyllables:
    def test_single_word_hyphenated(self):
        lrc_lines = [
            {"time": 12.34, "text": "[00:12.34]To-night"},
        ]
        result = parse_lrc_syllables(lrc_lines)
        assert len(result) == 1
        assert result[0] == (12.34, "To-night", ["To", "night"])

    def test_multi_word_line_not_parsed(self):
        lrc_lines = [
            {"time": 12.34, "text": "[00:12.34]To-night the world"},
        ]
        result = parse_lrc_syllables(lrc_lines)
        assert len(result) == 0  # Multi-word lines are not parsed as syllables

    def test_no_hyphen_not_parsed(self):
        lrc_lines = [
            {"time": 12.34, "text": "[00:12.34]Tonight"},
        ]
        result = parse_lrc_syllables(lrc_lines)
        assert len(result) == 0

    def test_multiple_syllable_lines(self):
        lrc_lines = [
            {"time": 12.34, "text": "[00:12.34]To-night"},
            {"time": 15.80, "text": "[00:15.80]beau-ti-ful"},
        ]
        result = parse_lrc_syllables(lrc_lines)
        assert len(result) == 2
        assert result[0] == (12.34, "To-night", ["To", "night"])
        assert result[1] == (15.80, "beau-ti-ful", ["beau", "ti", "ful"])


class TestLrcSyllablesToTimed:
    def test_equal_distribution(self):
        syllable_lines = [(12.34, "To-night", ["To", "night"])]
        result = lrc_syllables_to_timed(syllable_lines, next_line_time=15.80)
        assert len(result) == 2
        assert result[0].text == "To"
        assert result[0].start == 12.34
        assert result[0].end == pytest.approx(14.07, abs=0.01)
        assert result[1].text == "night"
        assert result[1].start == pytest.approx(14.07, abs=0.01)
        assert result[1].end == 15.80
        assert all(s.source == "lrc" for s in result)

    def test_three_syllables(self):
        syllable_lines = [(15.80, "beau-ti-ful", ["beau", "ti", "ful"])]
        result = lrc_syllables_to_timed(syllable_lines, next_line_time=18.0)
        assert len(result) == 3
        assert result[0].text == "beau"
        assert result[1].text == "ti"
        assert result[2].text == "ful"
        assert result[2].end == 18.0


class TestPyphenSyllables:
    def test_tonight_splits_to_two(self):
        result = pyphen_syllables("tonight", 0.0, 1.0)
        assert len(result) == 2
        assert result[0].text == "to"
        assert result[1].text == "night"
        assert result[0].source == "pyphen"
        assert result[0].start == 0.0
        assert result[1].end == 1.0

    def test_world_stays_one(self):
        result = pyphen_syllables("world", 0.0, 0.5)
        assert len(result) == 1
        assert result[0].text == "world"
        assert result[0].start == 0.0
        assert result[0].end == 0.5

    def test_beautiful_three_syllables(self):
        result = pyphen_syllables("beautiful", 0.0, 1.0)
        assert len(result) == 3
        assert result[0].text == "beau"
        assert result[1].text == "ti"
        assert result[2].text == "ful"
        assert result[0].start == 0.0
        assert result[2].end == 1.0

    def test_vowel_weighting(self):
        # "beautiful" splits as "beau", "ti", "ful"
        # "beau" has 3 vowels (e,a,u), "ti" has 1 (i), "ful" has 1 (u)
        # Total 5 vowels, so beau gets 3/5=0.6, ti gets 0.2, ful gets 0.2
        result = pyphen_syllables("beautiful", 0.0, 1.0)
        assert result[0].end == pytest.approx(0.6, abs=0.01)
        assert result[1].end == pytest.approx(0.8, abs=0.01)
        assert result[2].end == 1.0


class TestWhisperxCharsToSyllables:
    def test_groups_by_word(self):
        word_segments = [
            {"word": "Hello", "start": 0.5, "end": 1.0},
            {"word": "world", "start": 1.0, "end": 1.5},
        ]
        char_segments = [
            {"char": "H", "start": 0.50, "end": 0.55},
            {"char": "e", "start": 0.55, "end": 0.60},
            {"char": "l", "start": 0.60, "end": 0.65},
            {"char": "l", "start": 0.65, "end": 0.70},
            {"char": "o", "start": 0.70, "end": 0.80},
            {"char": "w", "start": 1.00, "end": 1.05},
            {"char": "o", "start": 1.05, "end": 1.10},
            {"char": "r", "start": 1.10, "end": 1.15},
            {"char": "l", "start": 1.15, "end": 1.20},
            {"char": "d", "start": 1.20, "end": 1.25},
        ]
        result = whisperx_chars_to_syllables(word_segments, char_segments)
        assert len(result) == 2
        assert result[0].text == "Hello"
        assert result[0].start == 0.50
        assert result[0].end == 0.80
        assert result[1].text == "world"
        assert result[1].start == 1.00
        assert result[1].end == 1.25
        assert all(s.source == "whisperx" for s in result)


class TestSegmentWordToSyllables:
    def test_whisperx_priority(self):
        word_segments = [
            {"word": "Hello", "start": 0.5, "end": 1.0},
            {"word": "world", "start": 1.0, "end": 1.5},
        ]
        char_segments = [
            {"char": "H", "start": 0.50, "end": 0.55},
            {"char": "e", "start": 0.55, "end": 0.60},
            {"char": "l", "start": 0.60, "end": 0.65},
            {"char": "l", "start": 0.65, "end": 0.70},
            {"char": "o", "start": 0.70, "end": 0.80},
            {"char": "w", "start": 1.00, "end": 1.05},
            {"char": "o", "start": 1.05, "end": 1.10},
            {"char": "r", "start": 1.10, "end": 1.15},
            {"char": "l", "start": 1.15, "end": 1.20},
            {"char": "d", "start": 1.20, "end": 1.25},
        ]
        result = segment_word_to_syllables(
            "Hello", 0.5, 1.0,
            whisperx_chars=char_segments,
            word_segments=word_segments,
        )
        assert len(result) == 1
        assert result[0].text == "Hello"
        assert result[0].source == "whisperx"

    def test_lrc_fallback(self):
        lrc_syllables = [
            Syllable(text="To", start=12.34, end=13.5, source="lrc"),
            Syllable(text="night", start=13.5, end=14.66, source="lrc"),
        ]
        result = segment_word_to_syllables(
            "tonight", 12.34, 14.66,
            lrc_syllables=lrc_syllables,
        )
        assert len(result) == 2
        assert result[0].text == "To"
        assert result[1].text == "night"
        assert all(s.source == "lrc" for s in result)

    def test_pyphen_fallback(self):
        result = segment_word_to_syllables("tonight", 0.0, 1.0)
        assert len(result) == 2
        assert result[0].text == "to"
        assert result[1].text == "night"
        assert all(s.source == "pyphen" for s in result)


class TestSegmentAllWordsToSyllables:
    def test_adds_syllables_to_words(self):
        synced_words = [
            {"word": "tonight", "start": 0.0, "end": 1.0},
            {"word": "world", "start": 1.5, "end": 2.0},  # Separate LRC line
        ]
        lrc_data = [
            {"time": 0.0, "text": "[00:00.00]To-night"},
            {"time": 1.5, "text": "[00:01.50]world"},  # No hyphen, won't be parsed as syllables
        ]
        result = segment_all_words_to_syllables(synced_words, lrc_data=lrc_data)
        assert len(result) == 2
        assert "syllables" in result[0]
        assert len(result[0]["syllables"]) == 2
        assert result[0]["syllables"][0]["text"] == "To"
        assert result[0]["syllables"][1]["text"] == "night"
        assert result[1]["syllables"][0]["text"] == "world"
        assert result[1]["syllables"][0]["source"] == "pyphen"  # no hyphen in LRC


if __name__ == "__main__":
    pytest.main([__file__, "-v"])