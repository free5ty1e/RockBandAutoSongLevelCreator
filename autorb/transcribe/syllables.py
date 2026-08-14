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
_CMUDICT_PHONEMES = None


def _load_cmudict() -> tuple[dict, dict]:
    """Load CMUdict pronunciation dictionary for syllabification.
    
    Returns:
        (syllable_counts, phoneme_sequences) - both keyed by lowercase word
    """
    global _CMUDICT, _CMUDICT_PHONEMES
    if _CMUDICT is not None and _CMUDICT_PHONEMES is not None:
        return _CMUDICT, _CMUDICT_PHONEMES
    
    syllable_counts = {}
    phoneme_seqs = {}
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
                        if word not in syllable_counts:
                            syllable_counts[word] = syllable_count
                            # Store phonemes without stress markers for splitting
                            clean_phonemes = [p.rstrip('012') for p in phonemes]
                            phoneme_seqs[word] = clean_phonemes
    except Exception:
        # Network unavailable - CMUdict will be empty, fall back to pyphen only
        pass
    
    _CMUDICT = syllable_counts
    _CMUDICT_PHONEMES = phoneme_seqs
    return _CMUDICT, _CMUDICT_PHONEMES


def _get_cmudict_syllable_count(word: str) -> Optional[int]:
    """Get syllable count from CMUdict."""
    counts, _ = _load_cmudict()
    return counts.get(word.lower())


def _get_cmudict_phonemes(word: str) -> Optional[List[str]]:
    """Get phoneme sequence from CMUdict."""
    _, phonemes = _load_cmudict()
    return phonemes.get(word.lower())


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


def _norm_word(w: str) -> str:
    """Normalize a word for comparison (lowercase, strip punctuation)."""
    return re.sub(r"[^a-z0-9]", "", (w or "").lower())


def _flatten_raw_words(
    whisperx_alignment: Optional[dict],
    whisperx_word_segments: Optional[List[dict]],
) -> List[dict]:
    """Return the raw WhisperX word boundaries in order.

    Prefers ``whisperx_word_segments`` (the flattened list the pipeline already
    built) and falls back to flattening ``alignment_result["segments"][i][
    "words"]``.
    """
    if whisperx_word_segments:
        return whisperx_word_segments
    raw = []
    if whisperx_alignment and "segments" in whisperx_alignment:
        for seg in whisperx_alignment["segments"]:
            for w in seg.get("words", []):
                raw.append({
                    "word": w.get("word", ""),
                    "start": w.get("start", w.get("time", 0.0)),
                    "end": w.get("end", 0.0),
                })
    return raw


def _match_raw_word(raw_words: List[dict], word_text: str, anchor: float):
    """Find the raw WhisperX word matching ``word_text`` nearest ``anchor``.

    Repeated words appear many times in the raw list, so we pick the match whose
    raw start is closest to the (onset-snapped) charted anchor.
    """
    target = _norm_word(word_text)
    best = None
    for rw in raw_words:
        if _norm_word(rw.get("word")) == target:
            score = abs(rw.get("start", rw.get("time", 0.0)) - anchor)
            if best is None or score < best[0]:
                best = (score, rw)
    return best[1] if best else None


def _chars_in_range(chars: List[dict], raw_start: float, raw_end: float) -> List[dict]:
    """Chars whose midpoint falls inside the raw word's time range."""
    out = []
    for ch in chars:
        c_start = ch.get("start", 0.0)
        c_end = ch.get("end", c_start)
        c_mid = (c_start + c_end) / 2
        if raw_start - 0.05 <= c_mid <= raw_end + 0.05:
            out.append(ch)
    return out


def _syllable_times_from_chars(
    syllable_texts: List[str],
    chars: List[dict],
    raw_start: float,
    raw_end: float,
    word_start: float,
    word_end: float,
) -> Optional[List[Tuple[str, float, float]]]:
    """Timing for each syllable text, derived from WhisperX char alignments.

    Matches each syllable's text into the reconstructed char string, reads the
    char timestamps at the boundaries, then rescales the whole word onto the
    (possibly onset-snapped) charted ``[word_start, word_end]`` so relative
    syllable rhythm comes from the audio while the note still lands on the true
    sung onset. Returns None when the char data doesn't cover the word.
    """
    if not chars or not syllable_texts:
        return None
    ctext = "".join(ch.get("char", "") for ch in chars)
    if not ctext.strip():
        return None
    positions = []
    pos = 0
    for syl in syllable_texts:
        match = re.search(re.escape(_norm_word(syl)), _norm_word(ctext)[pos:])
        if not match:
            return None
        start_idx = pos + match.start()
        end_idx = pos + match.end()
        if end_idx <= start_idx or end_idx > len(chars):
            return None
        positions.append((start_idx, end_idx))
        pos = end_idx

    raw_dur = max(1e-6, (raw_end or word_end) - (raw_start or word_start))
    word_dur = max(1e-6, word_end - word_start)
    out = []
    for (si, ei), syl in zip(positions, syllable_texts):
        lo = (chars[si]["start"] + chars[si]["end"]) / 2
        hi = (chars[ei - 1]["start"] + chars[ei - 1]["end"]) / 2
        if ei < len(chars):
            next_mid = (chars[ei]["start"] + chars[ei]["end"]) / 2
            hi = (hi + next_mid) / 2
        frac_start = (lo - raw_start) / raw_dur
        frac_end = (hi - raw_start) / raw_dur
        t_start = word_start + min(1.0, max(0.0, frac_start)) * word_dur
        t_end = word_start + min(1.0, max(0.0, frac_end)) * word_dur
        if t_end < t_start:
            t_end = t_start
        out.append((syl, t_start, t_end))
    return out


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


# Manual syllable text overrides for words where CMUdict count != pyphen split
# These are words where English orthography doesn't match pyphen's rules
# Only used for the syllable TEXT (display), timing still uses vowel-weighting
_MANUAL_SYLLABLE_TEXT = {
    "forever": ["for", "ev", "er"],
    "eighty": ["eigh", "ty"],
    "nowhere": ["now", "here"],
    "everything": ["eve", "ry", "thing"],
    "broken": ["bro", "ken"],
    "listen": ["lis", "ten"],
    "together": ["to", "geth", "er"],
    "whatever": ["what", "ev", "er"],
    "ambitious": ["am", "bi", "tious"],
    "unconditional": ["un", "con", "di", "tion", "al"],
    "lonesome": ["lone", "some"],
    "ambition": ["am", "bi", "tion"],
    "condition": ["con", "di", "tion"],
    "tradition": ["tra", "di", "tion"],
    "position": ["po", "si", "tion"],
    "definition": ["def", "i", "ni", "tion"],
    "explanation": ["ex", "pla", "na", "tion"],
    "information": ["in", "for", "ma", "tion"],
    "education": ["ed", "u", "ca", "tion"],
    "celebration": ["cel", "e", "bra", "tion"],
    "imagination": ["im", "ag", "i", "na", "tion"],
    "organization": ["or", "gan", "i", "za", "tion"],
    "population": ["pop", "u", "la", "tion"],
    "generation": ["gen", "er", "a", "tion"],
    "operation": ["op", "er", "a", "tion"],
    "invitation": ["in", "vi", "ta", "tion"],
    "application": ["ap", "pli", "ca", "tion"],
    "destination": ["des", "ti", "na", "tion"],
    "investigation": ["in", "ves", "ti", "ga", "tion"],
    "reservation": ["res", "er", "va", "tion"],
    "conversation": ["con", "ver", "sa", "tion"],
    "observation": ["ob", "ser", "va", "tion"],
    "examination": ["ex", "am", "i", "na", "tion"],
    "imagination": ["im", "ag", "i", "na", "tion"],
    "configuration": ["con", "fig", "u", "ra", "tion"],
    "administration": ["ad", "min", "is", "tra", "tion"],
    "transformation": ["trans", "for", "ma", "tion"],
    "transportation": ["trans", "por", "ta", "tion"],
    "telecommunication": ["tel", "e", "com", "mu", "ni", "ca", "tion"],
}


def _split_by_phonemes(word: str, phonemes: List[str], target_count: int) -> List[str]:
    """
    Split word into syllables using CMUdict phoneme sequence.
    
    Maps phonemes to graphemes approximately. This is an approximation since
    English grapheme-to-phoneme mapping is many-to-many, but works well for
    common words.
    """
    # Simple heuristic: map phonemes to characters proportionally
    # Group phonemes by syllable (vowel phonemes)
    vowel_phonemes = {'AA', 'AE', 'AH', 'AO', 'AW', 'AY', 'EH', 'ER', 'EY', 
                      'IH', 'IY', 'OW', 'OY', 'UH', 'UW'}
    
    syllable_phonemes = []
    current = []
    for ph in phonemes:
        current.append(ph)
        if ph in vowel_phonemes:
            syllable_phonemes.append(current)
            current = []
    if current:
        if syllable_phonemes:
            syllable_phonemes[-1].extend(current)
        else:
            syllable_phonemes.append(current)
    
    if len(syllable_phonemes) == target_count:
        # Perfect match - distribute characters proportionally
        return _distribute_chars_by_phonemes(word, syllable_phonemes)
    
    # Close enough - use the phoneme-based count
    if abs(len(syllable_phonemes) - target_count) <= 1:
        return _distribute_chars_by_phonemes(word, syllable_phonemes)
    
    # Fallback to character distribution
    return _equal_char_split(word, target_count)


def _distribute_chars_by_phonemes(word: str, syllable_phonemes: List[List[str]]) -> List[str]:
    """Distribute word characters across syllables based on phoneme count."""
    total_phonemes = sum(len(s) for s in syllable_phonemes)
    syllables = []
    char_idx = 0
    for i, syl_ph in enumerate(syllable_phonemes):
        weight = len(syl_ph) / total_phonemes
        end_idx = int(char_idx + len(word) * weight)
        if i == len(syllable_phonemes) - 1:
            end_idx = len(word)
        syllables.append(word[char_idx:end_idx])
        char_idx = end_idx
    return syllables


def _redistribute_syllables_vowel_based(word: str, target_count: int) -> List[str]:
    """Fallback: redistribute using vowel nuclei + maximum onset principle."""
    vowels = set('aeiouAEIOUyY')
    word_lower = word.lower()
    
    # Find vowel nuclei
    nuclei = []
    i = 0
    while i < len(word):
        if word_lower[i] in vowels:
            j = i
            while j < len(word) and word_lower[j] in vowels:
                j += 1
            nuclei.append((i, j))
            i = j
        else:
            i += 1
    
    if not nuclei:
        return [word]
    
    if len(nuclei) == target_count:
        syllables = []
        for idx, (n_start, n_end) in enumerate(nuclei):
            onset_start = nuclei[idx-1][1] if idx > 0 else 0
            syllable = word[onset_start:n_end]
            syllables.append(syllable)
        return syllables
    
    return _equal_char_split(word, target_count)


def _equal_char_split(word: str, target_count: int) -> List[str]:
    """Last resort: equal character split."""
    syllables = []
    for i in range(target_count):
        start = int(i * len(word) / target_count)
        end = int((i + 1) * len(word) / target_count) if i < target_count - 1 else len(word)
        syllables.append(word[start:end])
    return syllables


_MANUAL_SYLLABLE_TEXT = {
    "forever": ["for", "ev", "er"],
    "eighty": ["eigh", "ty"],
    "nowhere": ["now", "here"],
    "everything": ["eve", "ry", "thing"],
    "broken": ["bro", "ken"],
    "listen": ["lis", "ten"],
    "together": ["to", "geth", "er"],
    "whatever": ["what", "ev", "er"],
    "ambitious": ["am", "bi", "tious"],
    "unconditional": ["un", "con", "di", "tion", "al"],
    "lonesome": ["lone", "some"],
    "ambition": ["am", "bi", "tion"],
    "condition": ["con", "di", "tion"],
    "tradition": ["tra", "di", "tion"],
    "position": ["po", "si", "tion"],
    "definition": ["def", "i", "ni", "tion"],
    "explanation": ["ex", "pla", "na", "tion"],
    "information": ["in", "for", "ma", "tion"],
    "education": ["ed", "u", "ca", "tion"],
    "celebration": ["cel", "e", "bra", "tion"],
    "imagination": ["im", "ag", "i", "na", "tion"],
    "organization": ["or", "gan", "i", "za", "tion"],
    "population": ["pop", "u", "la", "tion"],
    "generation": ["gen", "er", "a", "tion"],
    "operation": ["op", "er", "a", "tion"],
    "invitation": ["in", "vi", "ta", "tion"],
    "application": ["ap", "pli", "ca", "tion"],
    "destination": ["des", "ti", "na", "tion"],
    "investigation": ["in", "ves", "ti", "ga", "tion"],
    "reservation": ["res", "er", "va", "tion"],
    "conversation": ["con", "ver", "sa", "tion"],
    "observation": ["ob", "ser", "va", "tion"],
    "examination": ["ex", "am", "i", "na", "tion"],
    "imagination": ["im", "ag", "i", "na", "tion"],
    "configuration": ["con", "fig", "u", "ra", "tion"],
    "administration": ["ad", "min", "is", "tra", "tion"],
    "transformation": ["trans", "for", "ma", "tion"],
    "transportation": ["trans", "por", "ta", "tion"],
    "telecommunication": ["tel", "e", "com", "mu", "ni", "ca", "tion"],
}


def _get_manual_syllable_text(word: str) -> Optional[List[str]]:
    """Return manual syllable text for known problem words."""
    return _MANUAL_SYLLABLE_TEXT.get(word.lower())


def _redistribute_syllables(word: str, target_count: int) -> List[str]:
    """
    Split word into target_count syllables using CMUdict phonemes when available,
    otherwise fall back to vowel-based heuristic.
    """
    # Check manual overrides first
    manual = _get_manual_syllable_text(word)
    if manual and len(manual) == target_count:
        return manual
    
    # Try to use CMUdict phonemes for accurate syllabification
    phonemes = _get_cmudict_phonemes(word)
    if phonemes:
        return _split_by_phonemes(word, phonemes, target_count)
    
    # Fallback: vowel-based heuristic
    return _redistribute_syllables_vowel_based(word, target_count)


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
    2. WhisperX character alignments grouped into the dictionary syllables
       (audio-derived syllable start/end instead of vowel-weighted proportion)
    3. Dictionary syllables via pyphen (always used as fallback)
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

    # 2. WhisperX character alignments: derive syllable start/end from the audio.
    #    The dictionary syllable TEXT still comes from pyphen/CMUdict/manual
    #    overrides; only the TIMING is audio-derived.
    if whisperx_chars and word_segments:
        # Find the raw WhisperX word for this (possibly onset-snapped) word and
        # derive syllable timing from its character alignments.
        raw = _match_raw_word(word_segments, word_text, word_start)
        if raw is not None:
            raw_start = raw.get("start", raw.get("time", 0.0))
            raw_end = raw.get("end", word_end)
            chars = _chars_in_range(whisperx_chars, raw_start, raw_end)
            texts = [s.text for s in split_base_syllable_into_dictionary(word_text, word_start, word_end)]
            timed = _syllable_times_from_chars(texts, chars, raw_start, raw_end,
                                               word_start, word_end)
            if timed:
                return [Syllable(text=t, start=s, end=e, source="whisperx")
                        for t, s, e in timed]

    # 3. Fallback: use pyphen directly on the word text
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

    # Raw WhisperX word boundaries, used to map chars to the right word.
    raw_words = _flatten_raw_words(whisperx_alignment, whisperx_word_segments)
    if not raw_words:
        whisperx_chars = []

    # Segment each word
    for word in synced_words:
        syllables = segment_word_to_syllables(
            word_text=word["word"],
            word_start=word["start"],
            word_end=word["end"],
            lrc_syllables=lrc_syllables if lrc_syllables else None,
            whisperx_chars=whisperx_chars if whisperx_chars else None,
            word_segments=raw_words if whisperx_chars else None,
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