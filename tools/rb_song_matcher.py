#!/usr/bin/env python3
"""Find official-Rock-Band songs with matching YouTube + synced-LRC material.

The official-DLC ground-truth loop needs song sets where ALL of these line up:
  1. an official RB CON chart exists (the user fetches it from their archive),
  2. a YouTube upload of the SAME master (duration match — RB DLC uses the
     album master + a short lead-in, so the album length is the proxy),
  3. a synchronized .lrc of the same length (lrclib.net),
  4. (bonus, this repo only) a full-band Guitar Pro tab in the local
     git-ignored `tabs/` collection.

For every candidate this tool gathers: YouTube durations (yt-dlp, median of
the top uploads = the canonical studio length), lrclib synced-lyrics
availability + duration, MusicBrainz recording lengths (album-master
cross-check), and the local tab situation. It ranks candidates by how well
the three durations agree.

Sources & keys: yt-dlp (no key), lrclib.net (no key; set a User-Agent),
MusicBrainz (no key; 1 req/s max — we sleep). None of the fetched material is
committed: this tool only writes a JSON REPORT of durations/URLs.

Usage:
  # the RB3 on-disc list (authoritative, full-band charts incl. keys):
  python tools/rb_song_matcher.py --from-dta .tmp/rb3_songs.dta [--limit 40]

  # an explicit candidate list (JSON: [{"artist": ..., "title": ...}, ...]):
  python tools/rb_song_matcher.py --list candidates.json

  # one song:
  python tools/rb_song_matcher.py --artist "Eve 6" --title "Inside Out"

  [--out report.json] [--tabs-root tabs] [--no-youtube/--no-musicbrainz]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "AutoRB-Research/1.0 (ground-truth matching; contact: dev@autorb.local)"


def http_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


# --------------------------------------------------------------- candidates

def parse_rb3_dta(path: Path) -> list[dict]:
    """Extract (song_id, title, artist) from an rb3_songs.dta-style file."""
    src = path.read_text(errors="replace")
    out = []
    # blocks: (songid\n   (name\n      "Title")\n   (artist\n      "Artist") ...
    for m in re.finditer(
            r"^\(([a-z0-9_-]+)\s*\n\s*\(name\s*\n?\s*\"([^\"]+)\"\)\s*\n\s*\(artist\s*\n?\s*\"([^\"]+)\"\)",
            src, re.M):
        out.append({"song_id": m.group(1), "title": m.group(2), "artist": m.group(3)})
    return out


def load_candidates(args) -> list[dict]:
    if args.artist and args.title:
        return [{"song_id": None, "artist": args.artist, "title": args.title}]
    if args.list:
        data = json.loads(Path(args.list).read_text())
        return data if isinstance(data, list) else data.get("candidates", [])
    if args.from_dta:
        return parse_rb3_dta(Path(args.from_dta))
    raise SystemExit("one of --from-dta / --list / --artist+--title is required")


# ----------------------------------------------------------------- sources

def youtube_durations(artist: str, title: str, n: int = 6) -> dict:
    """Search YouTube via yt-dlp; return {urls_by_duration, median}."""
    q = urllib.parse.quote(f"{artist} {title} audio")
    try:
        proc = subprocess.run(
            ["yt-dlp", "--no-warnings", "--flat-playlist", "--no-download",
             "--print", "%(duration)s|%(webpage_url)s|%(title)s",
             f"ytsearch{n}:{q}"],
            capture_output=True, text=True, timeout=90)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"median": None, "hits": [], "error": "yt-dlp failed/missing"}
    hits = []
    for line in proc.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        hits.append({"duration": int(parts[0]), "url": parts[1], "title": parts[2]})
    if not hits:
        # YouTube throttles rapid flat searches — retry once after a pause
        time.sleep(4)
        try:
            proc = subprocess.run(
                ["yt-dlp", "--no-warnings", "--flat-playlist", "--no-download",
                 "--print", "%(duration)s|%(webpage_url)s|%(title)s",
                 f"ytsearch{n}:{q}"],
                capture_output=True, text=True, timeout=90)
            for line in proc.stdout.splitlines():
                parts = line.split("|", 2)
                if len(parts) == 3 and parts[0].isdigit():
                    hits.append({"duration": int(parts[0]), "url": parts[1],
                                 "title": parts[2]})
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    if not hits:
        return {"median": None, "hits": [], "error": (proc.stderr or "no results")[:120]}
    med = statistics.median(h["duration"] for h in hits)
    # keep the uploads closest to the median (the canonical studio version)
    hits.sort(key=lambda h: abs(h["duration"] - med))
    return {"median": int(med), "hits": hits[:3]}


def lrclib_lookup(artist: str, title: str) -> dict:
    q = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
    data = http_json(f"https://lrclib.net/api/search?{q}")
    if not data:
        return {"synced": False}
    best = None
    for item in data:
        if item.get("syncedLyrics"):
            best = item
            break
    if not best:
        return {"synced": False, "plain_only": len(data) > 0}
    return {
        "synced": True,
        "duration": best.get("duration"),
        "lrclib_id": best.get("id"),
        "url": f"https://lrclib.net/api/get?id={best.get('id')}",
    }


def musicbrainz_lengths(artist: str, title: str) -> dict:
    q = urllib.parse.quote(f'recording:"{title}" AND artist:"{artist}"')
    data = http_json(f"https://musicbrainz.org/ws/2/recording/?query={q}&fmt=json&limit=5")
    time.sleep(1.1)  # MB rate limit: 1 req/s
    if not data or not data.get("recordings"):
        return {"median": None, "n": 0}
    lens = []
    for r in data["recordings"]:
        if r.get("length"):
            lens.append(r["length"] // 1000)
    if not lens:
        return {"median": None, "n": 0}
    med = statistics.median(lens)
    lens.sort(key=lambda L: abs(L - med))
    return {"median": int(med), "n": len(lens)}


# ------------------------------------------------------------------- tabs

def find_tab(artist: str, title: str, tabs_root: Path) -> dict:
    """Filename-only match in the GP collection (fast); parse matched files
    lazily via the audit tool when possible."""
    if not tabs_root or not tabs_root.exists():
        return {"tab": None}
    def norm(s):
        return re.sub(r"[^a-z0-9]+", "", s.lower())
    na, nt = norm(artist), norm(title)
    hits = []
    for p in tabs_root.rglob("*"):
        if p.suffix.lower() not in (".gp3", ".gp4", ".gp5") or not p.is_file():
            continue
        f = norm(p.stem)
        if nt in f and na in f:
            hits.append(p)
    if not hits:
        return {"tab": None}
    return {"tab": str(min(hits, key=lambda p: len(p.name)))}


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-dta", type=Path)
    ap.add_argument("--list", type=Path)
    ap.add_argument("--artist")
    ap.add_argument("--title")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--tabs-root", type=Path, default=Path("tabs"))
    ap.add_argument("--tolerance", type=int, default=4,
                    help="seconds of YT-vs-LRC length agreement to rank as exact")
    ap.add_argument("--no-youtube", action="store_true")
    ap.add_argument("--no-musicbrainz", action="store_true")
    a = ap.parse_args()

    candidates = load_candidates(a)
    print(f"{len(candidates)} candidate(s); researching up to {a.limit}\n", file=sys.stderr)
    results = []
    for i, c in enumerate(candidates[: a.limit]):
        artist, title = c.get("artist", ""), c.get("title", "")
        if not artist or not title:
            continue
        time.sleep(1.5)  # throttle: YouTube rate-limits rapid flat searches
        row = {"artist": artist, "title": title, "song_id": c.get("song_id")}
        yt = {"median": None, "hits": []} if a.no_youtube else youtube_durations(artist, title)
        lrc = lrclib_lookup(artist, title)
        mb = {"median": None} if a.no_musicbrainz else musicbrainz_lengths(artist, title)
        row["youtube"] = yt
        row["lrc"] = lrc
        row["musicbrainz"] = mb
        row["tab"] = find_tab(artist, title, a.tabs_root)
        # agreement: the three durations pairwise
        durs = [d.get("median") for d in (yt, mb) if d.get("median")]
        if lrc.get("duration"):
            durs.append(lrc["duration"])
        row["durations"] = durs
        row["agreement"] = (max(durs) - min(durs)) if len(durs) >= 2 else None
        row["match_quality"] = (
            "exact" if row["agreement"] is not None and row["agreement"] <= a.tolerance
            else "close" if row["agreement"] is not None and row["agreement"] <= 10
            else "mismatch" if row["agreement"] is not None
            else "insufficient-data")
        results.append(row)
        flag = row["match_quality"]
        tabf = " +tab" if row["tab"].get("tab") else ""
        print(f"[{i + 1}/{min(len(candidates), a.limit)}] {artist} - {title}: "
              f"{flag} (yt={yt.get('median')} mb={mb.get('median')} "
              f"lrc={lrc.get('duration')}){tabf}", file=sys.stderr)

    order = {"exact": 0, "close": 1, "mismatch": 2, "insufficient-data": 3}
    results.sort(key=lambda r: (order[r["match_quality"]],
                                r["agreement"] if r["agreement"] is not None else 9e9,
                                0 if r["tab"].get("tab") else 1))
    if a.out:
        a.out.write_text(json.dumps({"tolerance_s": a.tolerance,
                                     "results": results}, indent=1))
        print(f"\nreport: {a.out}", file=sys.stderr)

    print(f"\n{'quality':<10} {'durations (yt/mb/lrc)':<28} {'tab':<4} artist - title")
    for r in results:
        d = r["durations"]
        dstr = f"{d[0] if d else '-'}/{r['musicbrainz'].get('median') or '-'}/{r['lrc'].get('duration') or '-'}"
        print(f"{r['match_quality']:<10} {dstr:<28} {'Y' if r['tab'].get('tab') else '-':<4} "
              f"{r['artist']} - {r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
