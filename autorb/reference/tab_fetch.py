"""Tier-1 web tab discovery + Tier-0 user-supplied tab staging.

What this stage does (v0.1.37 — discovery/report slice; sync + tab-as-chart
come in later phases per the accuracy plan):

* **Tier 1 (opt-in, `--fetch-tabs`)**: searches Songsterr's public JSON API
  (``https://www.songsterr.com/api/songs?pattern=<artist title>`` — the one
  tab-site API that is reachable from datacenter IPs; Ultimate Guitar gates
  everything behind a JS challenge, tabcrawler/guitaretab are dead), scores
  candidates by artist/title match, and *attempts* a GuitarPro download via
  the known URL patterns. Songsterr currently gates GPX downloads behind its
  JS player (verified 2026-10-24: every known ``a/ra/player/...`` pattern
  404s), so the honest outcome is a structured REPORT — matched song,
  songId, tracks with tuning/difficulty, and the URLs to try — with the GPX
  fetch succeeding only if/when the site allows it. The pipeline NEVER
  fails because of this stage: a fetch error is a warning in the report.
* **Tier 0**: `--guitar-tab <file>` (repeatable) registers user-supplied
  GuitarPro/MIDI/ASCII tabs by copying them into the job's
  ``reference_tabs/`` folder so every reference artifact for a job lives in
  one place. (Full GP parsing → chart translation is the Phase-2/4 work.)

Output: ``<output_dir>/reference_tabs/report.json`` — the contract the
sync + tab-as-chart phases will consume.

We never fabricate: if nothing is found, the report says so.
"""

from __future__ import annotations

import json
import re
import shutil
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

#: Songsterr's public search API — verified reachable from datacenter IPs
#: (2026-10-24). Returns a JSON array; entries carry songId, artist, title,
#: hasChords/hasPlayer and a tracks[] with instrument, difficulty (1-5),
#: tuning (MIDI pitch per string) and a per-track hash.
SONGSTERR_SEARCH_URL = "https://www.songsterr.com/api/songs?pattern={query}&withTabs=true"

#: Known GuitarPro download URL patterns (songsterr player backend). All were
#: 404 (ERR_NOT_FOUND) as of 2026-10-24 — the GPX fetch is gated behind the
#: JS player. We still try them: a) the gating may change, b) a user-supplied
#: mirror path via --tab-url uses the same attempt machinery.
GPX_URL_PATTERNS = [
    "https://www.songsterr.com/a/ra/player/song/{song_id}/{track_hash}.gpx",
    "https://www.songsterr.com/a/ra/player/songid/{song_id}/tab/{track_hash}",
    "https://www.songsterr.com/a/ra/player/song/{song_id}/{track_hash}",
]

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_TIMEOUT = 15
_SSL_CTX = ssl.create_default_context()


def _norm(s: str) -> str:
    """Normalize for match scoring: lowercase, strip punctuation/spaces."""
    s = s.lower()
    s = re.sub(r"\(.*?\)", "", s)  # drop parenthetical qualifiers (e.g. "- Radio Edit")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


@dataclass
class TabCandidate:
    """One search hit, scored against the requested artist/title."""
    song_id: int
    artist: str
    title: str
    score: float
    guitar_tracks: list = field(default_factory=list)
    has_chords: bool = False
    source: str = "songsterr"

    def to_dict(self) -> dict:
        return asdict(self)


def _http_get(url: str, timeout: int = _TIMEOUT) -> Optional[bytes]:
    """GET with a desktop UA; returns bytes or None on any failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                                   "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return r.read()
    except Exception:  # noqa: BLE001 - any network error is a miss, never a crash
        return None


def search_songsterr(artist: str, title: str,
                     http_get=None) -> list[TabCandidate]:
    """Search Songsterr and return scored candidates (best first).

    ``http_get`` is injectable for tests (offline). Scoring: exact normalized
    artist+title = 1.0; each of artist/title exact on its own adds 0.45;
    substring containment adds up to 0.3 by containment fraction. Candidates
    scoring 0 are dropped (search noise).
    """
    fetch = http_get or _http_get
    query = urllib.parse.quote(f"{artist} {title}")
    raw = fetch(SONGSTERR_SEARCH_URL.format(query=query))
    if raw is None:
        return []
    try:
        entries = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return []
    if not isinstance(entries, list):
        return []

    na, nt = _norm(artist), _norm(title)
    out: list[TabCandidate] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        e_artist = str(e.get("artist") or "")
        e_title = str(e.get("title") or "")
        score = 0.0
        if e_artist and e_title:
            ea, et = _norm(e_artist), _norm(e_title)
            if not ea or not et:
                continue
            if ea == na and et == nt:
                score = 1.0
            else:
                if ea == na:
                    score += 0.45
                elif na and (na in ea or ea in na):
                    score += 0.3 * min(len(na), len(ea)) / max(len(na), len(ea))
                if et == nt:
                    score += 0.45
                elif nt and (nt in et or et in nt):
                    score += 0.3 * min(len(nt), len(et)) / max(len(nt), len(et))
        if score <= 0:
            continue
        tracks = []
        for t in e.get("tracks") or []:
            if not isinstance(t, dict):
                continue
            if "guitar" in str(t.get("instrument") or "").lower() or \
               "bass" in str(t.get("instrument") or "").lower():
                tracks.append({
                    "instrument": t.get("instrument"),
                    "difficulty": t.get("difficulty"),
                    "tuning": t.get("tuning"),
                    "hash": t.get("hash"),
                })
        out.append(TabCandidate(
            song_id=int(e.get("songId") or 0),
            artist=e_artist, title=e_title, score=round(score, 3),
            guitar_tracks=tracks,
            has_chords=bool(e.get("hasChords")),
        ))
    out.sort(key=lambda c: (-c.score, -len(c.guitar_tracks)))
    return out


def attempt_gpx_download(song_id: int, track_hash: str, dest: Path,
                          http_get=None) -> Optional[Path]:
    """Try every known GPX URL pattern; save the first plausible file.

    A "plausible" download is non-empty and does not start with '{' (the
    player API answers misses with a JSON error body — that is not a tab).
    Returns the saved path or None.
    """
    fetch = http_get or _http_get
    dest.parent.mkdir(parents=True, exist_ok=True)
    for pattern in GPX_URL_PATTERNS:
        url = pattern.format(song_id=song_id, track_hash=track_hash)
        data = fetch(url)
        if data and not data.lstrip()[:1] == b"{" and len(data) > 32:
            # GPX is a zip container -> starts with 'PK'
            if data[:2] != b"PK":
                continue
            dest.write_bytes(data)
            return dest
    return None


def build_report(artist: str, title: str, candidates: list[TabCandidate],
                 downloads: dict, user_supplied: list,
                 status: str, notes: list) -> dict:
    """The report.json contract consumed by the (future) sync/chart phases."""
    best = candidates[0] if candidates else None
    return {
        "schema": "autorb-reference-tabs/1",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "artist": artist,
        "title": title,
        "status": status,  # "found" | "found_no_download" | "not_found" | "offline"
        "best_match": best.to_dict() if best else None,
        "candidates": [c.to_dict() for c in candidates[:10]],
        "downloads": downloads,          # {track_hash: {"path":..., "url":...}}
        "user_supplied": user_supplied,   # [{"name":..., "path":...}] (Tier 0)
        "notes": notes,
        "next_step": ("Run the tab-sync phase once implemented (see the "
                      "accuracy plan); until then supply tab files with "
                      "--guitar-tab for Tier-0 use."),
    }


def run_tab_fetch_stage(artist: str, title: str, output_dir: Path,
                        user_tabs: Optional[list[Path]] = None,
                        http_get=None) -> dict:
    """Stage entry point: discover, attempt downloads, stage Tier-0 files,
    write ``<output_dir>/reference_tabs/report.json``.

    Non-fatal by design: network failures produce a status='offline' report.
    """
    ref_dir = Path(output_dir) / "reference_tabs"
    ref_dir.mkdir(parents=True, exist_ok=True)

    notes: list[str] = []
    user_supplied: list[dict] = []
    for tab in (user_tabs or []):
        tab = Path(tab)
        if not tab.exists():
            notes.append(f"user-supplied tab missing: {tab}")
            continue
        dest = ref_dir / tab.name
        shutil.copy2(tab, dest)
        user_supplied.append({"name": tab.name, "path": str(dest)})
        notes.append(f"staged user-supplied tab: {tab.name}")

    if not artist or not title:
        report = build_report(artist or "", title or "", [], {}, user_supplied,
                              status="no_metadata",
                              notes=notes + ["fetch skipped: artist/title unknown"])
        _write_report(ref_dir, report)
        return report

    candidates = search_songsterr(artist, title, http_get=http_get)
    if not candidates:
        status = "offline" if (http_get or _http_get)(SONGSTERR_SEARCH_URL.format(
            query=urllib.parse.quote(f"{artist} {title}"))) is None else "not_found"
        report = build_report(artist, title, [], {}, user_supplied,
                              status=status, notes=notes + [
                                  "No Songsterr match; provide a tab with "
                                  "--guitar-tab (Tier 0) or refine artist/title."])
        _write_report(ref_dir, report)
        return report

    downloads: dict = {}
    best = candidates[0]
    for tr in best.guitar_tracks[:4]:  # try the top candidate's guitar tracks
        h = tr.get("hash")
        if not h:
            continue
        dest = ref_dir / f"{best.song_id}_{h}.gpx"
        got = attempt_gpx_download(best.song_id, h, dest, http_get=http_get)
        if got:
            downloads[h] = {"path": str(got), "instrument": tr.get("instrument")}
        else:
            notes.append(f"GPX download gated for track {h} "
                         f"({tr.get('instrument')}) — Songsterr serves GPX "
                         "through its JS player; open the song on songsterr "
                         f"and save the tab manually, or supply --guitar-tab.")
    status = "found" if downloads else "found_no_download"
    report = build_report(artist, title, candidates, downloads,
                          user_supplied, status=status, notes=notes)
    _write_report(ref_dir, report)
    return report


def _write_report(ref_dir: Path, report: dict) -> None:
    (ref_dir / "report.json").write_text(json.dumps(report, indent=2))
    if not sys.warnoptions and report["status"] not in ("found",):
        # keep the pipeline log honest without failing the run
        print(f"[tab-fetch] status={report['status']} "
              f"({len(report['candidates'])} candidate(s))", file=sys.stderr)
