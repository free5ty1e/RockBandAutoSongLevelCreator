#!/bin/bash
# clone_hero_headless.sh — bootstrap a headless X11 + PulseAudio environment and
# launch Clone Hero (Linux) under box64 (arm64) or natively (x86_64), with the
# ALSA-seq shim preloaded so RtMidi's MIDI init can't crash Unity.
#
# Usage:
#   tools/clone_hero_headless.sh --song /abs/path/to/song [--player Guitar,Expert] [CH_ARGS...]
#   tools/clone_hero_headless.sh --song /abs/path/to/song --shot out.png   # capture one frame, exit
#
# The --song path MUST be absolute (Clone Hero resolves relative paths from its
# own binary dir under box64 and NREs). See
# .ai_memory/plans/clone_hero_devcontainer_playtesting.md (Phase 0 findings).

set -euo pipefail

CH_DIR="${CH_DIR:-/opt/clonehero}"
ARCH="$(uname -m)"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
export DISPLAY=":${DISPLAY_NUM}"

log() { echo "[clone_hero] $*"; }

# ---- choose the launcher ----
if [ "${ARCH}" = "aarch64" ] || [ "${ARCH}" = "arm64" ]; then
    LAUNCHER=(box64 "${CH_DIR}/clonehero")
    export BOX64_LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu
    export BOX64_GL_LIBRARY=/usr/lib/x86_64-linux-gnu/libGL.so.1
    export BOX64_NOBANNER=1
    export BOX64_LD_PRELOAD="${CH_DIR}/alsa_seq_shim.so"
else
    LAUNCHER=("${CH_DIR}/clonehero")
fi

# Software GL (no GPU in container)
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe

# ---- virtual audio: PulseAudio null sink whose clock runs in real time ----
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/ch_pulse}"
export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"
export PULSE_SINK="ch_sink"
mkdir -p "${XDG_RUNTIME_DIR}"

start_pulse() {
    if pulseaudio --check 2>/dev/null; then
        log "PulseAudio already running."
        return 0
    fi
    log "Starting PulseAudio null sink..."
    pulseaudio -D --exit-idle-time=-1 \
        --load="module-null-sink sink_name=ch_sink sink_properties=device.description=CloneHeroHeadless"
    # give it a moment to create the socket
    for _ in $(seq 1 20); do
        [ -S "${XDG_RUNTIME_DIR}/pulse/native" ] && break
        sleep 0.2
    done
}

# ---- virtual X display ----
start_xvfb() {
    if [ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; then
        log "Xvfb :${DISPLAY_NUM} already running."
        return 0
    fi
    log "Starting Xvfb :${DISPLAY_NUM}..."
    Xvfb ":${DISPLAY_NUM}" -screen 0 1920x1080x24 -ac >/tmp/xvfb.log 2>&1 &
    for _ in $(seq 1 20); do
        [ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ] && break
        sleep 0.2
    done
}

start_xvfb
start_pulse

# ---- parse our own flags ----
SONG=""
SHOT=""
WAIT=20
AT=""
EXTRA=()
while [ $# -gt 0 ]; do
    case "$1" in
        --song) SONG="$2"; shift 2 ;;
        --shot) SHOT="$2"; shift 2 ;;
        --wait) WAIT="$2"; shift 2 ;;
        --at) AT="$2"; shift 2 ;;
        *) EXTRA+=("$1"); shift ;;
    esac
done

# --at <seconds> = target time in the SONG to capture. Under box64 Clone Hero
# spends ~BOOT_GRACE seconds booting before the song actually starts playing, so
# a wall-clock sleep of exactly AT would capture (AT - BOOT_GRACE) seconds into
# the song. Add the boot grace to the wait so the captured frame lands at ~AT.
if [ -n "${AT}" ]; then
    BOOT_GRACE=15
    WAIT=$((AT + BOOT_GRACE))
fi

if [ -z "${SONG}" ]; then
    echo "ERROR: --song <absolute path> is required" >&2
    exit 1
fi
if [ ! -d "${SONG}" ]; then
    echo "ERROR: song folder not found: ${SONG}" >&2
    exit 1
fi

# ---- frame capture mode: launch, wait, grab, kill ----
if [ -n "${SHOT}" ]; then
    log "Launching CH (capture mode) on ${SONG}..."
    "${LAUNCHER[@]}" --song "${SONG}" "${EXTRA[@]}" >/tmp/clonehero.log 2>&1 &
    CH_PID=$!
    log "Waiting ${WAIT}s for the song to load..."
    sleep "${WAIT}"
    log "Capturing frame -> ${SHOT}"
    ffmpeg -y -hide_banner -loglevel error -f x11grab -video_size 1920x1080 \
        -i "${DISPLAY}" -frames:v 1 "${SHOT}"
    log "Killing CH (pid ${CH_PID})..."
    kill "${CH_PID}" 2>/dev/null || true
    wait "${CH_PID}" 2>/dev/null || true
    log "Done. Screenshot at ${SHOT}."
    exit 0
fi

# ---- foreground launch ----
log "Launching Clone Hero on ${SONG}..."
exec "${LAUNCHER[@]}" --song "${SONG}" "${EXTRA[@]}"
