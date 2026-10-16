#!/bin/bash
# setup_clone_hero_headless.sh — idempotent install of the headless Clone Hero
# playtesting harness used by the AutoRB devcontainer (see
# .ai_memory/plans/clone_hero_devcontainer_playtesting.md, Phase 1).
#
# Installs, in order, only what is missing:
#   1. X11/GL/audio/multiarch runtime deps (xvfb, mesa, pulseaudio, tesseract, gtk3)
#   2. box64 (arm64 only) — runs the x86_64 CH binary under emulation
#   3. Clone Hero itself (pinned tar, sha256-verified) at /opt/clonehero
#   4. the ALSA-seq shim (tools/clone_hero/alsa_seq_shim.c) for box64
#
# Safe to re-run: every step checks for an existing, valid install first.
# Requires root or passwordless sudo.

set -euo pipefail

# ---- pinned upstream release (bump deliberately + re-verify the sha256) ----
CH_VERSION="${CH_VERSION:-v1.1.0.6142-final}"
CH_URL="https://github.com/clonehero-game/releases/releases/download/${CH_VERSION}/Linux.x86_64-Standalone.tar"
CH_SHA256="572971d93092283c5d0d52006a26b52ab8e8fb128dcfb42a3496de26c8aa231d"
CH_DIR="${CH_DIR:-/opt/clonehero}"

# ---- locate repo + shim source relative to this script ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SHIM_SRC="${REPO_ROOT}/tools/clone_hero/alsa_seq_shim.c"
SHIM_OUT="${CH_DIR}/alsa_seq_shim.so"

ARCH="$(uname -m)"
NEED_BOX64=0
[ "${ARCH}" = "aarch64" ] || [ "${ARCH}" = "arm64" ] && NEED_BOX64=1

# ---- privilege helper ----
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

log() { echo "[setup_clone_hero] $*"; }

# ---------------------------------------------------------------------------
# 1. apt runtime deps
# ---------------------------------------------------------------------------
install_apt_deps() {
    log "Installing apt runtime dependencies (skip if already present)..."
    ${SUDO} apt-get update || true

    local base_pkgs=(
        xvfb mesa-utils libgl1-mesa-dri libgl1 libegl1 libgles2
        mesa-vulkan-drivers pulseaudio pulseaudio-utils
        libgtk-3-0 tesseract-ocr x11-apps dbus
        build-essential cmake gcc wget curl ca-certificates git
    )

    if [ "${NEED_BOX64}" -eq 1 ]; then
        # Enable multiarch so box64 can run the x86_64 CH binary + its libs.
        ${SUDO} dpkg --add-architecture amd64 || true
        ${SUDO} apt-get update || true
        local amd64_pkgs=(
            gcc-x86-64-linux-gnu
            libasound2t64:amd64 libasound2-plugins:amd64
            libgl1-mesa-dri:amd64 mesa-vulkan-drivers:amd64
            libgcc-s1:amd64 libstdc++6:amd64 libgtk-3-0t64:amd64 libgl1:amd64
        )
        ${SUDO} apt-get install -y --no-install-recommends "${base_pkgs[@]}" "${amd64_pkgs[@]}"
    else
        ${SUDO} apt-get install -y --no-install-recommends "${base_pkgs[@]}"
    fi
}

# ---------------------------------------------------------------------------
# 2. box64 (arm64 only)
# ---------------------------------------------------------------------------
install_box64() {
    if [ "${NEED_BOX64}" -ne 1 ]; then
        log "Native x86_64 host — box64 not required."
        return 0
    fi
    if command -v box64 >/dev/null 2>&1; then
        log "box64 already present ($(command -v box64)) — skipping."
        return 0
    fi
    log "Building box64 from source (this takes a few minutes)..."
    local tmp
    tmp="$(mktemp -d)"
    git clone --depth 1 https://github.com/ptitSeb/box64 "${tmp}/box64"
    cmake -S "${tmp}/box64" -B "${tmp}/box64/build" -DARM64=1 -DCMAKE_BUILD_TYPE=RelWithDebInfo
    cmake --build "${tmp}/box64/build" -j"$(nproc)"
    ${SUDO} cmake --install "${tmp}/box64/build"
    rm -rf "${tmp}"
    command -v box64 >/dev/null 2>&1 || { echo "box64 install failed"; exit 1; }
    log "box64 installed: $(box64 --version 2>&1 | head -n1 || true)"
}

# ---------------------------------------------------------------------------
# 3. Clone Hero binary
# ---------------------------------------------------------------------------
install_clonehero() {
    if [ -x "${CH_DIR}/clonehero" ]; then
        log "Clone Hero already present at ${CH_DIR}/clonehero — skipping download."
        return 0
    fi
    log "Downloading Clone Hero ${CH_VERSION} (pinned, sha256-verified)..."
    ${SUDO} mkdir -p "${CH_DIR}"
    local tar
    tar="$(mktemp)"
    wget -q -O "${tar}" "${CH_URL}"
    local actual
    actual="$(sha256sum "${tar}" | cut -d' ' -f1)"
    if [ "${actual}" != "${CH_SHA256}" ]; then
        echo "ERROR: Clone Hero sha256 mismatch (got ${actual}, want ${CH_SHA256})" >&2
        rm -f "${tar}"
        exit 1
    fi
    ${SUDO} tar -xf "${tar}" -C "${CH_DIR}" --strip-components=0
    ${SUDO} chmod +x "${CH_DIR}/clonehero"
    rm -f "${tar}"
    [ -x "${CH_DIR}/clonehero" ] || { echo "Clone Hero binary missing after extract"; exit 1; }
    log "Clone Hero installed at ${CH_DIR}/clonehero"
}

# ---------------------------------------------------------------------------
# 4. ALSA-seq shim (built for x86_64 so box64 can preload it)
# ---------------------------------------------------------------------------
build_shim() {
    if [ -s "${SHIM_OUT}" ] && [ "${SHIM_OUT}" -nt "${SHIM_SRC}" ]; then
        log "ALSA-seq shim already built and up to date — skipping."
        return 0
    fi
    log "Building ALSA-seq shim -> ${SHIM_OUT}"
    local cc="gcc"
    if [ "${NEED_BOX64}" -eq 1 ]; then
        cc="x86_64-linux-gnu-gcc"
    fi
    ${SUDO} "${cc}" -shared -fPIC -O2 -o "${SHIM_OUT}" "${SHIM_SRC}"
    log "Shim built."
}

# ---------------------------------------------------------------------------
main() {
    install_apt_deps
    install_box64
    install_clonehero
    build_shim
    log "Clone Hero headless harness ready at ${CH_DIR}."
    log "Launch with: tools/clone_hero_headless.sh --song /abs/path/to/song"
}

# Run only when executed (not sourced).
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
