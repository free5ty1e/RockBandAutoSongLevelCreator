#!/usr/bin/env bash
# Fetch the FREE-licensed benchmark song for the release-audit functional
# conversion (stage 5b). Safe to re-run (idempotent, --clobber).
#
# Benchmark: "Tisk Tisk Sadness" by Trans Atlantic Rage
#   Source: Free Music Archive (mirrored on the Internet Archive)
#   Item:   https://archive.org/details/Introverted_Circumstances-7242
#   License: Creative Commons BY-NC-ND 3.0
#           http://creativecommons.org/licenses/by-nc-nd/3.0/
#   Why this song: full-band punk rock (drums/bass/distorted guitar/vocals)
#   with a DIFFERENT profile from Open Road Song (heavier vocals, sparser
#   onsets), exercising different charting paths. 52s = fast CI conversion.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
URL="https://archive.org/download/Introverted_Circumstances-7242/Trans_Atlantic_Rage_-_04_-_Tisk_Tisk_Sadness.mp3"
DEST="$DIR/benchmark_tisk_tisk.mp3"
echo "Fetching benchmark song -> $DEST"
curl -fsSL "$URL" -o "$DEST"
echo "Done: $(du -h "$DEST" | cut -f1) — $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$DEST" 2>/dev/null || echo 'unknown')s"
