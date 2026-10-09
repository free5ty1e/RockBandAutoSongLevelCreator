#!/usr/bin/env python3
"""Fetch official/community guitar tabs for a song from the web.

Bakes in the tab-retrieval procedure used for the validation loop:
searches the web for ASCII guitar tabs of a song (Ultimate Guitar, TabCrawler,
GuitareTab, Songsterr and mirrors), extracts the 6-string ASCII tab blocks
(`e|-...E|` line groups) plus fret/chord consensus, and saves a structured
YAML guide under ``tools/guitar_tab_alignment/tabs/`` for the chart validator.

Usage:
    python tools/guitar_tab_alignment/fetch_tabs.py \
        --artist "Eve 6" --title "Open Road Song" \
        [--out tabs/eve6_open_road_song.yaml]

The script is offline-friendly: if a cached guide already exists it is
reused (re-running a pipeline validation shouldn't re-scrape the web). When
no web access is available it reports that clearly and exits non-zero
WITHOUT writing a fabricated guide.
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

#: Sites known to host plain-text ASCII tabs (search-result snippet fetches
#: land on these; direct page fetches often 404 for tab sites that gate
#: content behind JS). Each entry: (label, url template with {slug}).
SOURCES = [
    ("tabcrawler", "http://www.tabcrawler.com/tabs.php?tabs={slug}"),
    ("guitaretab", "https://www.guitaretab.com/{slug}.htm"),
]

#: A tab block = 6 lines starting with a string label (e/A/D/G/B/e).
TAB_LINE = re.compile(r"^\s*([eEaAdDgGbB])\s*[|]-")
STRING_ORDER = ["E", "A", "D", "G", "B", "e"]
OPEN_MIDI = {"E": 40, "A": 45, "D": 50, "G": 55, "B": 59, "e": 64}


def slug_for(artist: str, title: str) -> str:
    """Build the common tab-site slug for artist/song."""
    def clean(s: str) -> str:
        s = s.lower().replace("&", "and")
        s = re.sub(r"[^a-z0-9]+", "_", s)
        return s.strip("_")
    return f"{clean(artist)}/{clean(artist)}_{clean(title)}"


def extract_ascii_blocks(text: str) -> list:
    """Pull all 6-line ASCII tab blocks out of free text.

    Returns a list of blocks, each a dict {string: [fret tokens]}.
    """
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if TAB_LINE.match(lines[i]):
            block_lines = lines[i:i + 6]
            if len(block_lines) == 6 and all(TAB_LINE.match(l) for l in block_lines):
                block = {}
                for l in block_lines:
                    m = TAB_LINE.match(l)
                    sname = m.group(1)
                    body = l.split("|", 1)[1] if "|" in l else l[len(sname):]
                    toks = re.findall(r"(\d+|[xX])", body)
                    block[sname] = toks
                if any(v for v in block.values()):
                    blocks.append(block)
                i += 6
                continue
        i += 1
    return blocks


def fetch_url(url: str, timeout: int = 15):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (autorb tab fetcher)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def consensus_chords(blocks: list) -> list:
    """Derive the chord consensus (fret shapes) from tab blocks.

    Groups blocks by their low-E/A/D fret shape (the power-chord root
    fingerprint) and reports each distinct shape with its implied root MIDI.
    """
    shapes = {}
    for b in blocks:
        root = None
        # lowest fretted string defines the power-chord root
        for s in ("E", "A", "D"):
            toks = b.get(s, [])
            frets = [int(t) for t in toks if t.isdigit()]
            if frets:
                root = OPEN_MIDI[s] + min(frets)
                break
        if root is None:
            continue
        key = (tuple(b.get("E", [])), tuple(b.get("A", [])), tuple(b.get("D", [])))
        shapes.setdefault(key, {"root_midi": root, "count": 0})
        shapes[key]["count"] += 1
    out = []
    for key, info in sorted(shapes.items(), key=lambda kv: -kv[1]["count"]):
        out.append({
            "E": list(key[0]), "A": list(key[1]), "D": list(key[2]),
            "root_midi": info["root_midi"], "occurrences": info["count"],
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--text", default=None,
                    help="Optional path to already-retrieved tab text "
                         "(search-result dump) to parse instead of fetching")
    args = ap.parse_args()

    def slug_part(s: str) -> str:
        s = s.lower().replace(" ", "_").replace("&", "and")
        return re.sub(r"[^a-z0-9_]+", "", s)

    out = Path(args.out) if args.out else (
        Path(__file__).parent / "tabs" /
        f"{slug_part(args.artist)}_{slug_part(args.title)}.yaml"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    if out.exists():
        print(f"[fetch_tabs] cached guide exists: {out} (reusing; delete to re-fetch)")
        return 0

    if args.text:
        text = Path(args.text).read_text()
        blocks = extract_ascii_blocks(text)
        print(f"[fetch_tabs] parsed {len(blocks)} tab block(s) from {args.text}")
    else:
        slug = slug_for(args.artist, args.title)
        blocks = []
        for label, url in SOURCES:
            try:
                text = fetch_url(url.format(slug=slug))
                found = extract_ascii_blocks(text)
                print(f"[fetch_tabs] {label}: {len(found)} tab block(s)")
                blocks.extend(found)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                print(f"[fetch_tabs] {label}: fetch failed ({e})")
        if not blocks:
            print("[fetch_tabs] ERROR: could not retrieve any tab content. "
                  "No guide written (we never fabricate tabs). "
                  "Manually save an ASCII tab to a file and re-run with --text.")
            return 2

    chords = consensus_chords(blocks)
    guide = {
        "song": args.title,
        "artist": args.artist,
        "tuning": "standard",
        "fetched_blocks": len(blocks),
        "chord_shapes": chords,
        "note": "Auto-derived from web tab content; verify voicings by ear.",
    }
    # Minimal YAML emission (avoid a PyYAML dependency for the tool).
    lines = [f"# Auto-fetched tab guide — {args.artist} — {args.title}"]
    for k, v in guide.items():
        lines.append(f"{k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}")
    out.write_text("\n".join(lines) + "\n")
    print(f"[fetch_tabs] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
