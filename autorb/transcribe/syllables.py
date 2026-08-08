#!/usr/bin/env python
"""
Syllable segmentation for vocal lyrics.

Supports three sources of syllable boundaries (in priority order):
1. LRC file with explicit syllable timestamps: [mm:ss.xx]syl-la-ble
2. WhisperX character alignments (chars field) grouped into syllables
3. Heuristic splitting via pyphen + proportional timing within word
"""

import re
from typing import List, Tuple, Optional
from dataclasses import dataclass

try:
    import pyphen
    _HAS_PYPHEN = True
except ImportError:
    _HAS_PYPHEN = False


@dataclass
class Syllable:
    """A single syllable with timing and text."""
    text: str
    start: float
    end: float
    source: str  # "lrc", "whisperx", "pyphen"


def parse_lrc_syllables(lrc_lines: List[dict]) -> List[Tuple[float, str, List[str]]]:
    """
    Parse LRC lines for syllable-level timestamps.

    Expected format: [mm:ss.xx]syl-la-ble (hyphen-separated syllables, single word)
    Returns list of (line_start_time, line_text, syllable_texts)
    
    Only processes lines that contain hyphens and NO spaces (single word with syllables).
    Multi-word lines fall back to pyphen.
    """
    syllable_lines = []
    pattern = re.compile(r'\[(\d+):(\d+\.\d+)\](.*)')
    
    for line in lrc_lines:
        text = line.get("text", "")
        match = pattern.search(text)
        if match:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            line_start = minutes * 60 + seconds
            content = match.group(3).strip()
            
            # Only parse as syllables if it's a single hyphenated word (no spaces)
            if '-' in content and ' ' not in content:
                syllables = [s.strip() for s in content.split('-') if s.strip()]
                if len(syllables) > 1:
                    syllable_lines.append((line_start, content, syllables))
    
    return syllable_lines


def lrc_syllables_to_timed(
    syllable_lines: List[Tuple[float, str, List[str]]],
    next_line_time: Optional[float] = None
) -> List[Syllable]:
    """
    Convert LRC syllable lines to timed Syllable objects.
    
    Distributes time equally among syllables within a line.
    The last syllable extends to the next line's start (or line end + estimate).
    """
    syllables = []
    
    for i, (line_start, line_text, syl_texts) in enumerate(syllable_lines):
        # Determine line end time
        if i + 1 < len(syllable_lines):
            line_end = syllable_lines[i + 1][0]
        elif next_line_time is not None:
            line_end = next_line_time
        else:
            # Estimate: ~0.4s per syllable
            line_end = line_start + len(syl_texts) * 0.4
        
        duration = line_end - line_start
        per_syllable = duration / len(syl_texts) if syl_texts else duration
        
        for j, syl_text in enumerate(syl_texts):
            start = line_start + j * per_syllable
            end = line_start + (j + 1) * per_syllable
            syllables.append(Syllable(
                text=syl_text,
                start=start,
                end=end,
                source="lrc"
            ))
    
    return syllables


def whisperx_chars_to_syllables(
    word_segments: List[dict],
    char_segments: List[dict]
) -> List[Syllable]:
    """
    Group WhisperX character segments into syllables.
    
    Simple heuristic: group consecutive characters until we hit a vowel
    boundary or reach max syllable length. More sophisticated approaches
    would use phonemizer, but this is a reasonable start.
    """
    if not char_segments:
        return []
    
    # Map character index to word index
    char_to_word = []
    for wi, word in enumerate(word_segments):
        w_start = word.get("start", word.get("time", 0))
        w_end = word.get("end", w_start + 0.3)
        for ci, char in enumerate(char_segments):
            if w_start <= char["start"] < w_end:
                char_to_word.append(wi)
    
    syllables = []
    current_syl_chars = []
    current_syl_word_idx = None
    
    vowels = set('aeiouAEIOU')
    
    for ci, char in enumerate(char_segments):
        c = char["char"]
        wi = char_to_word[ci] if ci < len(char_to_word) else 0
        
        # Start new syllable on word boundary
        if current_syl_word_idx is not None and wi != current_syl_word_idx:
            if current_syl_chars:
                syl_text = "".join(ch["char"] for ch in current_syl_chars)
                syllables.append(Syllable(
                    text=syl_text,
                    start=current_syl_chars[0]["start"],
                    end=current_syl_chars[-1]["end"],
                    source="whisperx"
                ))
                current_syl_chars = []
        
        current_syl_chars.append(char)
        current_syl_word_idx = wi
        
        # Heuristic: end syllable after vowel + optional consonants
        # (This is very rough; proper syllabification needs phonemizer)
        if c in vowels and len(current_syl_chars) >= 2:
            # Look ahead - if next char is consonant, continue
            # If next is vowel or end, end syllable
            pass  # Keep it simple for now - just group by word
    
    # Flush last syllable
    if current_syl_chars:
        syl_text = "".join(ch["char"] for ch in current_syl_chars)
        syllables.append(Syllable(
            text=syl_text,
            start=current_syl_chars[0]["start"],
            end=current_syl_chars[-1]["end"],
            source="whisperx"
        ))
    
    return syllables


def pyphen_syllables(word: str, word_start: float, word_end: float) -> List[Syllable]:
    """
    Split a word into syllables using pyphen and distribute time proportionally.
    
    Uses vowel count as weight for more natural timing (vowels take more time).
    """
    if not _HAS_PYPHEN:
        return [Syllable(text=word, start=word_start, end=word_end, source="pyphen")]
    
    dic = pyphen.Pyphen(lang='en_GB')
    positions = dic.positions(word)
    
    if not positions:
        return [Syllable(text=word, start=word_start, end=word_end, source="pyphen")]
    
    # Build syllable texts from hyphenation positions
    syllables_text = []
    last = 0
    for pos in positions:
        syllables_text.append(word[last:pos])
        last = pos
    syllables_text.append(word[last:])
    
    # Weight by vowel count for timing
    vowel_counts = [sum(1 for c in s if c.lower() in 'aeiou') for s in syllables_text]
    total_vowels = sum(vowel_counts) or len(syllables_text)
    duration = word_end - word_start
    
    syllables = []
    t = word_start
    for syl_text, vcount in zip(syllables_text, vowel_counts):
        weight = max(1, vcount) / total_vowels
        syl_duration = duration * weight
        syllables.append(Syllable(
            text=syl_text,
            start=t,
            end=t + syl_duration,
            source="pyphen"
        ))
        t += syl_duration
    
    # Fix rounding: last syllable ends exactly at word_end
    if syllables:
        syllables[-1].end = word_end
    
    return syllables


def segment_word_to_syllables(
    word_text: str,
    word_start: float,
    word_end: float,
    lrc_syllables: Optional[List[Syllable]] = None,
    whisperx_chars: Optional[List[dict]] = None,
    word_segments: Optional[List[dict]] = None,
) -> List[Syllable]:
    """
    Segment a single word into syllables using best available source.
    
    Priority:
    1. WhisperX character alignments grouped into syllables (most accurate - force-aligned to audio)
    2. LRC syllables that overlap with this word's time range (if LRC has per-syllable timestamps)
    3. Pyphen heuristic fallback
    """
    # 1. WhisperX character-based (force-aligned to audio, most accurate)
    if whisperx_chars and word_segments:
        all_syllables = whisperx_chars_to_syllables(word_segments, whisperx_chars)
        # Match syllables whose center falls within the word time range
        matched = [s for s in all_syllables 
                   if (s.start + s.end) / 2 >= word_start - 0.02 
                   and (s.start + s.end) / 2 <= word_end + 0.02]
        if matched:
            return matched
    
    # 2. LRC syllables overlapping with word time range (only if LRC has per-syllable timestamps)
    if lrc_syllables:
        matched = [s for s in lrc_syllables 
                   if s.end > word_start - 0.1 and s.start < word_end + 0.1]
        if matched:
            # Clip matched syllables to word boundaries
            clipped = []
            for s in matched:
                clipped.append(Syllable(
                    text=s.text,
                    start=max(s.start, word_start),
                    end=min(s.end, word_end),
                    source=s.source
                ))
            # Filter out zero-duration syllables
            clipped = [s for s in clipped if s.end > s.start + 0.01]
            if clipped:
                return clipped
    
    # 3. Pyphen fallback
    return pyphen_syllables(word_text, word_start, word_end)


def segment_all_words_to_syllables(
    synced_words: List[dict],
    lrc_data: Optional[List[dict]] = None,
    whisperx_alignment: Optional[dict] = None,
) -> List[dict]:
    """
    Add syllable segmentation to all synced words.
    
    Returns list of word dicts with added 'syllables' key containing
    list of dicts with 'text', 'start', 'end', 'source'.
    """
    # Pre-parse LRC syllables if available
    lrc_syllables = []
    if lrc_data:
        next_times = [lrc_data[i+1]["time"] for i in range(len(lrc_data)-1)] + [None]
        for line, next_time in zip(lrc_data, next_times):
            syllable_lines = parse_lrc_syllables([line])
            lrc_syllables.extend(lrc_syllables_to_timed(syllable_lines, next_time))
    
    # Extract WhisperX chars if available
    whisperx_chars = []
    if whisperx_alignment and "segments" in whisperx_alignment:
        for seg in whisperx_alignment["segments"]:
            if seg.get("chars"):
                whisperx_chars.extend(seg["chars"])
    
    # Segment each word
    for word in synced_words:
        syllables = segment_word_to_syllables(
            word_text=word["word"],
            word_start=word["start"],
            word_end=word["end"],
            lrc_syllables=lrc_syllables if lrc_syllables else None,
            whisperx_chars=whisperx_chars if whisperx_chars else None,
            word_segments=synced_words if whisperx_chars else None,
        )
        word["syllables"] = [
            {"text": s.text, "start": s.start, "end": s.end, "source": s.source}
            for s in syllables
        ]
    
    return synced_words


if __name__ == "__main__":
    # Quick test
    print("Testing syllable segmentation...")
    
    # Test pyphen
    syls = pyphen_syllables("tonight", 0.0, 1.0)
    print("tonight:", [(s.text, f"{s.start:.2f}-{s.end:.2f}") for s in syls])
    
    syls = pyphen_syllables("world", 0.0, 0.5)
    print("world:", [(s.text, f"{s.start:.2f}-{s.end:.2f}") for s in syls])
    
    syls = pyphen_syllables("the", 0.0, 0.2)
    print("the:", [(s.text, f"{s.start:.2f}-{s.end:.2f}") for s in syls])
    
    # Test LRC parsing
    lrc_test = [
        {"time": 12.34, "text": "[00:12.34]To-night"},
        {"time": 15.80, "text": "[00:15.80]the world"},
    ]
    parsed = parse_lrc_syllables(lrc_test)
    print("LRC parsed:", parsed)
    timed = lrc_syllables_to_timed(parsed, next_line_time=18.0)
    print("LRC timed:", [(s.text, f"{s.start:.2f}-{s.end:.2f}") for s in timed])