"""Parse standard ASCII guitar tablature into a structured, time-less guide.

Converts classic 6-line ASCII tabs:

    e|-0-0-0-0-3-3-3-3-5-5-5-5-3-3-3-3-|
    B|-1-1-1-1-1-1-1-1-3-3-3-3-1-1-1-1-|
    G|-0-0-0-0-0-0-0-0-0-0-0-0-0-0-0-0-|
    D|-2-2-2-2-2-2-2-2-2-2-2-2-2-2-2-2-|
    A|-3-3-3-3-3-3-3-3-3-3-3-3-3-3-3-3-|
    E|----------------------------------|

into a per-column chord guide: each column is one strum (the set of frets held
across the played strings), with the implied pitch (MIDI) computed from each
string's open tuning + fret. The tab does not encode rhythm/timing; the
alignment step assigns beat positions to each column.

Output columns:
    {"index": int,
     "strings": {string_name: fret_or_None},   # e.g. {"e":0,"B":1,...}
     "midi_pitches": [midi...],                # pitches of played strings
     "root_midi": float,                       # lowest/root pitch
    }
"""

from pathlib import Path
import re

#: Low->high string name order in a standard 6-string tab.
STRINGS_LOW_TO_HIGH = ["E", "A", "D", "G", "B", "e"]
#: Open-string MIDI pitches (low E2=40 ... high e4=76) for standard tuning.
OPEN_MIDI = {"E": 40, "A": 45, "D": 50, "G": 55, "B": 59, "e": 64}
#: XX or x = muted string (play but no pitch). '-' = not played.
_FRET_PATTERN = re.compile(r"(\d+|[xX])")


def _line_to_string(line: str) -> str:
    """Return the string name a tab line starts with (e.g. 'e', 'B', 'D')."""
    m = re.match(r"\s*([eEaAdDgGbB])[-|% ]", line)
    return m.group(1) if m else None


def parse_tab(text: str) -> list:
    """Parse ASCII tab text into a list of strum columns.

    Returns a list of {"index", "strings", "midi_pitches", "root_midi"}.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    string_columns = {}   # string_name -> list of frets (one per column)
    for line in lines:
        sname = _line_to_string(line)
        if sname is None:
            continue
        # Take the body between the first '|' (or the whole line if no bar).
        if "|" in line:
            body = line.split("|")[1]
        else:
            # strip the leading string label then the rest is the tab body
            body = line[len(sname):]
        toks = _FRET_PATTERN.findall(body)
        string_columns[sname] = toks

    # Determine the column count as the MAX across the real strings (a fully
    # un-played low-E line has 0 fret tokens but still spans the same columns).
    # Ignore strings with 0 tokens (un-played lines) when computing width.
    played = {k: v for k, v in string_columns.items() if v}
    lengths = [len(v) for v in played.values()] if played else []
    n = max(lengths) if lengths else 0
    if n == 0:
        return []

    if not string_columns:
        return []

    columns = []
    # Build each column: for each string in low->high order
    for c in range(n):
        strings = {}
        midis = []
        for sname in STRINGS_LOW_TO_HIGH:  # low->high
            if sname not in string_columns:
                continue
            tok = string_columns[sname][c] if c < len(string_columns[sname]) else None
            if tok is None:
                strings[sname] = None
                continue
            if tok.lower() == "x":
                strings[sname] = -1  # muted
                continue
            fret = int(tok)
            strings[sname] = fret
            if fret >= 0:
                midis.append(OPEN_MIDI[sname] + fret)
        root = min(midis) if midis else None
        columns.append({
            "index": c,
            "strings": strings,
            "midi_pitches": sorted(midis),
            "root_midi": root,
        })
    return columns


if __name__ == "__main__":
    import sys, json
    text = Path(sys.argv[1]).read_text()
    cols = parse_tab(text)
    print(json.dumps(cols, indent=2))
    print(f"... {len(cols)} columns (strums)")