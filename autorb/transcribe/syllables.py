#!/usr/bin/env python
"""
Syllable segmentation for vocal lyrics.

Supports four sources of syllable boundaries (in priority order):
1. LRC file with explicit syllable timestamps: [mm:ss.xx]syl-la-ble
2. WhisperX character alignments (chars field) grouped into syllables
3. CMUdict pronunciation dictionary (phoneme-based syllabification)
4. Heuristic splitting via pyphen + proportional timing within word
"""

import re
from typing import List, Tuple, Optional
from dataclasses import dataclass

try:
    import pyphen
    _HAS_PYPHEN = True
except ImportError:
    _HAS_PYPHEN = False

# CMUdict pronunciation cache (lazy-loaded)
_CMUDICT = None


def _load_cmudict() -> dict:
    """Load CMUdict pronunciation dictionary for syllabification."""
    global _CMUDICT
    if _CMUDICT is not None:
        return _CMUDICT
    
    cmudict = {}
    try:
        # CMUdict format: WORD PHONEME1 PHONEME2 ... (single space separated)
        # Vowels have stress markers (0,1,2) - syllable count = number of vowels
        import urllib.request
        url = "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict"
        with urllib.request.urlopen(url, timeout=10) as response:
            for line in response:
                line = line.decode('utf-8').strip()
                if line.startswith(';;;') or not line:
                    continue
                parts = line.split(' ', 1)  # Single space split
                if len(parts) == 2:
                    word = parts[0].lower()
                    # Remove variant suffixes like (1), (2)
                    word = re.sub(r'\(\d+\)$', '', word)
                    phonemes = parts[1].split()
                    # Count syllables = phonemes with stress digits (0,1,2)
                    syllable_count = sum(1 for p in phonemes if p[-1].isdigit())
                    if syllable_count > 0:
                        if word not in cmudict:
                            cmudict[word] = syllable_count
    except Exception:
        # Network unavailable - CMUdict will be empty, fall back to pyphen only
        pass
    
    _CMUDICT = cmudict
    return _CMUDICT


def _get_cmudict_syllable_count(word: str) -> Optional[int]:
    """Get syllable count from CMUdict."""
    cmudict = _load_cmudict()
    return cmudict.get(word.lower())


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
    Group WhisperX character segments into syllables (one per word for now).
    
    Maps each character to its word based on timing, then groups chars by word.
    """
    if not char_segments or not word_segments:
        return []
    
    # Map each character to its word index based on timing
    char_to_word = [-1] * len(char_segments)
    for ci, char in enumerate(char_segments):
        c_start = char.get("start", 0)
        c_end = char.get("end", c_start)
        c_mid = (c_start + c_end) / 2
        
        # Find the word this character belongs to
        for wi, word in enumerate(word_segments):
            w_start = word.get("start", word.get("time", 0))
            w_end = word.get("end", w_start + 0.3)
            if w_start <= c_mid < w_end:
                char_to_word[ci] = wi
                break
    
    # Group consecutive characters by word
    syllables = []
    current_chars = []
    current_wi = None
    
    for ci, char in enumerate(char_segments):
        wi = char_to_word[ci]
        
        # Skip characters that couldn't be mapped
        if wi == -1:
            continue
        
        # Start new syllable on word boundary
        if current_wi is not None and wi != current_wi:
            if current_chars:
                syl_text = "".join(ch["char"] for ch in current_chars)
                syllables.append(Syllable(
                    text=syl_text,
                    start=current_chars[0]["start"],
                    end=current_chars[-1]["end"],
                    source="whisperx"
                ))
                current_chars = []
        
        current_chars.append(char)
        current_wi = wi
    
    # Flush last syllable
    if current_chars:
        syl_text = "".join(ch["char"] for ch in current_chars)
        syllables.append(Syllable(
            text=syl_text,
            start=current_chars[0]["start"],
            end=current_chars[-1]["end"],
            source="whisperx"
        ))
    
    return syllables


def pyphen_syllables(word: str, word_start: float, word_end: float) -> List[Syllable]:
    """
    Split a word into syllables using pyphen + CMUdict, distribute time proportionally.
    
    Uses CMUdict for target syllable count, pyphen for actual split.
    Falls back to vowel-weighted pyphen split if CMUdict unavailable.
    """
    if not _HAS_PYPHEN:
        return [Syllable(text=word, start=word_start, end=word_end, source="pyphen")]
    
    dic = pyphen.Pyphen(lang='en_GB')
    positions = dic.positions(word)
    
    # Build syllable texts from hyphenation positions (or whole word if no split)
    if not positions:
        syllables_text = [word]
    else:
        syllables_text = []
        last = 0
        for pos in positions:
            syllables_text.append(word[last:pos])
            last = pos
        syllables_text.append(word[last:])
    
    # Target syllable count from CMUdict (if available), else use pyphen's count
    target_count = _get_cmudict_syllable_count(word) or len(syllables_text)
    
    # If pyphen gives wrong count, redistribute to match CMUdict
    if len(syllables_text) != target_count and target_count > 1:
        # Redistribute by vowel groups to match target count
        # Each vowel group = one syllable nucleus
        syllables_text = _redistribute_syllables(word, target_count)
    
    # Weight by vowel count for timing (include 'y' as vowel)
    vowel_counts = [sum(1 for c in s if c.lower() in 'aeiouy') for s in syllables_text]
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


def _redistribute_syllables(word: str, target_count: int) -> List[str]:
    """
    Split word into target_count syllables based on vowel nuclei and 
    the maximum onset principle (consonants before vowel go to that syllable).
    """
    vowels = set('aeiouAEIOU')
    word_lower = word.lower()
    
    # Find vowel nuclei (contiguous vowels = one nucleus)
    nuclei = []
    i = 0
    while i < len(word):
        if word_lower[i] in vowels:
            # Found vowel start - include all contiguous vowels
            j = i
            while j < len(word) and word_lower[j] in vowels:
                j += 1
            nuclei.append((i, j))
            i = j
        else:
            i += 1
    
    if not nuclei:
        return [word]  # No vowels
    
    # If we have exactly target_count nuclei, apply maximum onset principle
    if len(nuclei) == target_count:
        syllables = []
        for idx, (n_start, n_end) in enumerate(nuclei):
            # Onset: consonants before this nucleus up to previous nucleus end
            onset_start = nuclei[idx-1][1] if idx > 0 else 0
            # Nucleus + coda (consonants after nucleus up to next nucleus start)
            syllable = word[onset_start:n_end]
            syllables.append(syllable)
        return syllables
    
    # More nuclei than target: need to merge some nuclei
    # Fewer nuclei than target: need to split (rare, fallback to equal)
    # For simplicity, distribute characters equally
    chars_per_syl = len(word) / target_count
    syllables = []
    for i in range(target_count):
        start = int(i * chars_per_syl)
        end = int((i + 1) * chars_per_syl) if i < target_count - 1 else len(word)
        syllables.append(word[start:end])
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
    Segment a single word into syllables.
    
    Priority:
    1. LRC syllables whose START falls within this word's time range (only if LRC has per-syllable timestamps for single words)
    2. Dictionary syllables via pyphen (always used)
    """
    # 1. Try LRC syllables - only use if their start falls within this word's time range
    # AND the LRC line was a single hyphenated word (parsed by parse_lrc_syllables)
    if lrc_syllables:
        # Match syllables whose START is within this word's time range
        # Use midpoint for more robust matching
        matched = [s for s in lrc_syllables 
                   if s.start >= word_start - 0.02 and s.start <= word_end + 0.02]
        if matched:
            # Split each LRC syllable into dictionary syllables
            dictionary_syllables = []
            for base in matched:
                sub_syllables = split_base_syllable_into_dictionary(
                    base.text, base.start, base.end
                )
                for sub in sub_syllables:
                    sub.source = base.source
                dictionary_syllables.extend(sub_syllables)
            return dictionary_syllables
    
    # 2. Fallback: use pyphen directly on the word text
    return split_base_syllable_into_dictionary(word_text, word_start, word_end)


def split_base_syllable_into_dictionary(text: str, start: float, end: float) -> List[Syllable]:
    """
    Split a base syllable into dictionary syllables using pyphen + CMUdict.
    
    Distributes timing proportionally based on vowel count (vowel-weighted).
    Uses CMUdict for target syllable count, pyphen for actual split.
    """
    return pyphen_syllables(text, start, end)


def segment_all_words_to_syllables(
    synced_words: List[dict],
    lrc_data: Optional[List[dict]] = None,
    whisperx_alignment: Optional[dict] = None,
    whisperx_word_segments: Optional[List[dict]] = None,
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
            word_segments=whisperx_word_segments if whisperx_chars else None,
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