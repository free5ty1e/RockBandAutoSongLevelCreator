#!/usr/bin/env python3
"""Audit a Guitar Pro tab collection (the Ultimate Guitar dump in `tabs/`).

Answers, for the charting-accuracy Tier-0/1 work:
  1. What instruments do the tabs actually carry? (guitar-only vs full band)
  2. Which songs have ALL instruments we care about (guitar + bass + drums
     [+ keys]) — candidate test songs where one tab backs every part?
  3. Per-song details (tracks, note counts, tempo, tuning) for specific
     songs (--file / --search).

The tool parses with `guitarpro` (pip package `pyguitarpro`, pure Python,
devcontainer-research-only — deliberately NOT in requirements.txt; the
pipeline's own GP parsing, when it lands, will be a vendored minimal reader).

Parsing ~96k files takes ~52 min — two modes:
  --sample N      uniform random sample for collection-wide statistics
  --inventory     full walk (run in the background; writes --out incrementally)

Output: JSON report (machine-readable) + printed summary. NO tab content is
ever written to the report — only file names, track names, instrument MIDI
numbers, note counts, and metadata. The tabs are copyrighted arrangements:
they stay in the git-ignored `tabs/` folder; only what we LEARN is committed.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import guitarpro as gp

#: MIDI program numbers -> coarse family (GM standard)
INSTRUMENT_FAMILIES = {
    "keys": list(range(0, 8)) + [9] + list(range(96, 104)),  # piano/organs/synth pads
    "guitar": list(range(24, 32)),                            # nylon/steel/electric/overdriven/distortion
    "bass": list(range(32, 40)),                              # acoustic/electric basses + fretless
    "strings_horns": list(range(40, 80)),                     # everything orchestral/band
    "sfx_other": list(range(80, 96)) + list(range(104, 128)),
}
FAMILY_LOOKUP = {}
for fam, nums in INSTRUMENT_FAMILIES.items():
    for n in nums:
        FAMILY_LOOKUP[n] = fam


def file_family(track) -> str:
    """Coarse instrument family of a GP track ('drums' for percussion)."""
    if track.isPercussionTrack:
        return "drums"
    return FAMILY_LOOKUP.get(track.channel.instrument, "sfx_other")


def parse_one(path: Path) -> dict:
    """Parse one GP file into an audit record (no note content)."""
    song = gp.parse(str(path))
    tracks = []
    for t in song.tracks:
        notes = sum(len(b.notes) for m in t.measures for v in m.voices for b in v.beats)
        tracks.append({
            "name": t.name,
            "instrument": t.channel.instrument if not t.isPercussionTrack else "percussion",
            "family": file_family(t),
            "notes": notes,
            "strings": len(t.strings),
        })
    fams = sorted({tr["family"] for tr in tracks})
    _lyr = getattr(song, "lyrics", None)
    has_lyrics = bool(_lyr and any(
        getattr(line, "lyrics", "") for line in (_lyr.lines or [])))  # NB: Lyrics()
    # pre-populates five EMPTY lines — count only non-empty lyric text
    return {
        "file": str(path),
        "name": path.name,
        "title": song.title or "",
        "artist": song.artist or "",
        "tempo": song.tempo,
        "measures": len(song.measureHeaders),
        "tracks": tracks,
        "families": fams,
        "has_guitar": "guitar" in fams,
        "has_bass": "bass" in fams,
        "has_drums": "drums" in fams,
        "has_keys": "keys" in fams,
        "full_band": all(f in fams for f in ("guitar", "bass", "drums")),
        "full_band_keys": all(f in fams for f in ("guitar", "bass", "drums", "keys")),
        "has_lyrics": has_lyrics,
        "version": (getattr(song, "version", "") or "").strip(),
    }


def _iter_gp_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".gp3", ".gp4", ".gp5"):
            yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="tabs", help="collection root")
    ap.add_argument("--sample", type=int, default=None,
                    help="uniform random sample size (collection statistics)")
    ap.add_argument("--inventory", action="store_true",
                    help="parse the ENTIRE collection (slow — background it)")
    ap.add_argument("--file", action="append", default=None,
                    help="parse specific file(s) and print their track layout")
    ap.add_argument("--search", default=None,
                    help="case-insensitive filename substring; parse every match")
    ap.add_argument("--out", default=None, help="write the JSON report here")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    root = Path(args.root)
    records: list[dict] = []
    failures: list[str] = []

    if args.file or args.search:
        targets = [Path(f) for f in (args.file or [])]
        if args.search:
            needle = args.search.lower()
            targets += [p for p in _iter_gp_files(root) if needle in str(p).lower()]
        for p in targets:
            if not p.exists():
                print(f"missing: {p}", file=sys.stderr)
                continue
            try:
                r = parse_one(p)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{p}: {e}")
                continue
            records.append(r)
            print(f"\n=== {p.name}")
            print(f"  title={r['title']!r} artist={r['artist']!r} tempo={r['tempo']} measures={r['measures']}")
            for tr in r["tracks"]:
                print(f"    [{tr['family']:>12}] {tr['name']!r:<28} inst={tr['instrument']} notes={tr['notes']}")
            print(f"    families={r['families']} full_band={r['full_band']} full_band_keys={r['full_band_keys']}")
    else:
        files = list(_iter_gp_files(root))
        if args.sample:
            random.seed(args.seed)
            files = random.sample(files, min(args.sample, len(files)))
        t0 = time.time()
        for i, p in enumerate(files):
            try:
                records.append(parse_one(p))
            except Exception as e:  # noqa: BLE001
                failures.append(f"{p}: {type(e).__name__}: {e}")
            if args.inventory and (i + 1) % 2000 == 0:
                print(f"  {i + 1}/{len(files)} ({time.time() - t0:.0f}s)", flush=True)

    if records:
        print(f"\n=== SUMMARY ({len(records)} file(s)"
              + (f", {len(failures)} parse failures" if failures else "") + ")")
        n = len(records)
        for key in ("has_guitar", "has_bass", "has_drums", "has_keys",
                    "full_band", "full_band_keys", "has_lyrics"):
            cnt = sum(1 for r in records if r[key])
            print(f"  {key:>16}: {cnt:5d} ({cnt / n * 100:.1f}%)")
        # track-count distribution
        from collections import Counter
        tc = Counter(len(r["tracks"]) for r in records)
        print("  tracks/song     :", dict(sorted(tc.items())))
        fam_counts = Counter(f for r in records for f in r["families"])
        print("  family coverage :", dict(fam_counts.most_common()))
        fb = [r for r in records if r["full_band"]]
        if fb and len(records) > 5:
            print(f"  full-band examples: {[Path(r['file']).name for r in fb[:5]]}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(
            {"records": records, "failures": failures}, indent=1))
        print(f"\nreport written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
