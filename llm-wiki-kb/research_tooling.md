# Research Tooling — official-DLC ground truth, tabs, web sources

The charting-accuracy work (`.ai_memory/plans/tab_backed_charting_and_accuracy.md`)
runs a closed loop against **official Rock Band charts**. This page documents
the tooling that loop is built with — what each piece is for, where it lives,
and exactly how to use it. Everything here is devcontainer/research tooling:
none of it is imported by the `autorb` package or shipped in the wheel.

## The ground-truth loop (why these tools exist)

For a song where we have (1) the official RB CON chart, (2) an mp3 of the same
master, (3) a synced LRC, and ideally (4) a Guitar Pro tab, we can measure our
auto chart against Harmonix's per instrument/difficulty — note-level
recall/precision/lane-agreement (`tools/dlc_ground_truth.py align`) — then fix
the pipeline and re-measure. First measured data point (Eve 6 - Inside Out,
v0.1.39): drums F1 0.839, guitar recall 0.538, lane agreement ≈ random. The
tooling below is how more song sets get sourced.

## 1. `devscripts/con_extract/` — extract files from an official RB CON

A ~60-line mono/C# tool using **GameArchives** (`STFSPackage.OpenFile`) — the
exact library the vendored ForgeTool uses. ForgeTool's own `con2gp4` crashes
on RB2-era dta ("Element at index 1 is not a string"), so raw extraction is
the reliable path into official charts.

```
cd devscripts/con_extract
mcs con_extract.cs -r:../../tools/libforge/Dependencies/GameArchives/Library/bin/Release/GameArchives.dll -out:con-extract.exe
cp ../../tools/libforge/Dependencies/GameArchives/Library/bin/Release/GameArchives.dll .
mono con-extract.exe "input/rockbanddlc/Song.con" out_dir/
```

The devcontainer's post-install builds it automatically. Output for an RB2-era
DLC CON: `songs/<id>/<id>.mid` (THE official chart), `songs.dta`, `<id>.mogg`
(official stem mix), voc/pan/usr/vnn. RB3-era CONs use `notes.mid`.

## 2. `tools/dlc_ground_truth.py` — analyze/diff/align chart MIDIs

Works on ANY format-1 chart MIDI (official DLC or our own output):

```
# what does an official chart contain?
python tools/dlc_ground_truth.py analyze <official.mid> --json out.json

# counts per instrument/difficulty, ours vs official:
python tools/dlc_ground_truth.py diff <official.mid> <ours.mid>

# note-level accuracy (the headline metric): recall/precision/F1/lane
# agreement on the EXPERT charts within ±150 ms:
python tools/dlc_ground_truth.py align <official.mid> <ours.mid>
```

**Load-bearing detail (regression-tested):** format-1 MIDI carries tempo
events in the CONDUCTOR track — the tool builds one GLOBAL tick→seconds map
from all tracks. A per-track tempo scan silently computes every gem's time at
a stale 120 BPM (this caused the v0.1.39 "chart truncated at 147 s" false
alarm). Diffs are count-based and unaffected, but never hand-roll time math
on these files without the global map.

## 3. `tools/rb_song_matcher.py` — find new song sets (YouTube + LRC + tab)

Finds songs where official RB DLC, a matching-length YouTube upload, and a
synced LRC all exist:

```
# curated candidate list (artist/title JSON) — the usual way:
python tools/rb_song_matcher.py --list candidates.json --out report.json

# or all 83 RB3 on-disc songs straight from their dta:
python tools/rb_song_matcher.py --from-dta .tmp/rb3_songs.dta --limit 40
```

Per candidate it gathers: **YouTube** durations via yt-dlp (`ytsearch`, median
of top uploads = the canonical studio length; retries once — YouTube
throttles rapid searches), **lrclib.net** synced-lyrics availability +
duration (`https://lrclib.net/api/search?track_name=&artist_name=` — plain
params, no key, set a User-Agent), **MusicBrainz** recording lengths (1
req/s), and the local **`tabs/`** Guitar Pro collection (filename match).
Results rank by duration agreement (`exact` ≤ 4 s). RB DLC uses the album
master plus a short lead-in, so album/YT length ≈ chart length is the proxy;
the CON's mogg gives the exact in-game length once the user drops the file.

Where to get RB song catalogs: `hmxmilohax/rock-band-3-deluxe` on GitHub —
`_ark/songs/songs_dx.dta` (DX additions), `_ark/dx/song_updates/rb3_songs.dta`
(the 83 RB3 on-disc songs with full name/artist/tracks metadata), and
`official_additional_metadata.dta` (annotated game_origin ids for RB1/track
packs). `songs_yarg.dta` there lists 2559 legacy Harmonix song ids.

## 4. `tools/guitar_tab_alignment/audit_gp_collection.py` — the tabs/ inventory

Parses the local Guitar Pro collection (git-ignored `tabs/`, ~96 k files from
the user's Ultimate Guitar archive — gp3/gp4/gp5) and reports per-song track
families: guitar/bass/drums(keys)/full-band, note counts, tempo, lyrics.

```
python tools/guitar_tab_alignment/audit_gp_collection.py --sample 600          # stats
python tools/guitar_tab_alignment/audit_gp_collection.py --file "tabs/E/Eve 6 - Inside Out.gp3"
python tools/guitar_tab_alignment/audit_gp_collection.py --search "eve 6"
```

Collection findings (v0.1.38 sample): 53.4 % full band, 63 % bass, 62 %
drums, 15 % keys. Parsed with `guitarpro` (pip: pyguitarpro) — **GPL,
devcontainer-only** (in `requirements-research.txt`, never in
requirements.txt/pyproject, never shipped).

## 5. `requirements-research.txt` — the research dependency set

`yt-dlp` (Unlicense) + `pyguitarpro` (GPL-3.0). Installed by the devcontainer
post-install (survives rebuilds), kept OUT of the shipped dependency set:
the pipeline never imports either. The pipeline's own GP reading (Phase 2)
will be a vendored minimal reader.

## 6. Pi harness web tools (`devscripts/pi_extensions/web-tools.ts`)

Installs `web_search` (Bing RSS — DuckDuckGo blocks datacenter IPs) and
`web_fetch` (URL → readable text) as first-class Pi tools. Canonical copy in
the repo; installed to `~/.pi/agent/extensions/` (which the Pi persistence
script keeps in the workspace, so it survives rebuilds).

## Copyright rules for all of this

Official CONs, mp3s, and tabs are copyrighted: they live ONLY in git-ignored
folders (`input/rockbanddlc/`, `tabs/`, `tools/test_data/local/`); nothing
fetched is committed; the repo stores only what we LEARN (measurements,
guidelines, code). The tab-search web UI carries the server-enforced
copyright-disclaimer gate (v0.1.37).
