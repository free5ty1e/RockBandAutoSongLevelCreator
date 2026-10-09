#!/bin/bash
# ch_capture.sh — capture a Clone Hero screenshot of a song at a specific
# instrument / difficulty / time, entirely headless (no GPU, no display needed).
#
# This is a thin, user-friendly wrapper around tools/clone_hero_headless.sh. It
# boots Clone Hero under box64 + Xvfb + PulseAudio, jumps straight into gameplay
# on the requested instrument/difficulty, waits until the requested point in the
# song, grabs one frame, and writes it to --out.
#
# Usage:
#   tools/ch_capture.sh --song /abs/path/to/song \
#       --instrument guitar --difficulty expert --at 45 --out shot.png
#
#   --song        Absolute path to the Clone Hero song folder (required).
#   --instrument  guitar | bass | drums | vocals | keys  (default: guitar)
#   --difficulty  expert | hard | medium | easy        (default: expert)
#   --at          Seconds into the song to capture (default: 30). Clone Hero
#                 needs ~15s to boot under box64, so very small values are
#                 clamped up to the boot grace period.
#   --out         Output PNG path (default: /tmp/ch_capture.png).
#   --wait        Override the total pre-capture delay in seconds (rarely needed).
#
# Example — see the guitar chart at 1:15 on Expert:
#   tools/ch_capture.sh --song "$PWD/output/clone_hero/Eve 6 - Open Road Song" \
#       --instrument guitar --difficulty expert --at 75 --out /tmp/guitar75.png
#
# Example — verify the drums chart loaded at all (capture early):
#   tools/ch_capture.sh --song "$PWD/output/clone_hero/Eve 6 - Open Road Song" \
#       --instrument drums --difficulty expert --at 20 --out /tmp/drums20.png

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SONG=""
INSTRUMENT="guitar"
DIFFICULTY="expert"
AT="30"
OUT="/tmp/ch_capture.png"
WAIT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --song) SONG="$2"; shift 2 ;;
        --instrument) INSTRUMENT="$2"; shift 2 ;;
        --difficulty) DIFFICULTY="$2"; shift 2 ;;
        --at) AT="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        --wait) WAIT="$2"; shift 2 ;;
        *) echo "ERROR: unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [ -z "${SONG}" ]; then
    echo "ERROR: --song <absolute path to song folder> is required" >&2
    exit 1
fi
if [ ! -d "${SONG}" ]; then
    echo "ERROR: song folder not found: ${SONG}" >&2
    exit 1
fi

# Capitalize the first letter for Clone Hero's -p flag (Guitar, Bass, Drums, …).
CAP="$(echo "${INSTRUMENT}" | sed 's/^./\U&/')"
DIFF_CAP="$(echo "${DIFFICULTY}" | sed 's/^./\U&/')"
PLAYER="${CAP},${DIFF_CAP}"

ARGS=(--song "${SONG}" --shot "${OUT}" -p "${PLAYER}")
if [ -n "${WAIT}" ]; then
    ARGS+=(--wait "${WAIT}")
else
    ARGS+=(--at "${AT}")
fi

echo "Capturing ${PLAYER} at ~${AT}s of: ${SONG}"
echo "  -> ${OUT}"
exec bash "${SCRIPT_DIR}/clone_hero_headless.sh" "${ARGS[@]}"
