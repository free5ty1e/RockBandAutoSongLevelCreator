#!/bin/bash
set -e

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y patchelf

echo "Installing Python dependencies..."
# requirements.txt lists crepe + madmom, but both fail to BUILD on Python 3.11
# (setuptools>=81 dropped pkg_resources; madmom 0.16.1 also uses removed numpy
# Py2 aliases). They are optional backends: the pipeline falls back to librosa
# onsets and basic-pitch/pyin pitch when they are absent. Install the bulk first
# (tolerant of those two failing), then install crepe explicitly with the
# setuptools workaround so the devcontainer actually gets the better pitch backend.
pip install -r requirements.txt || echo "WARN: requirements.txt had build failures (continuing; crepe/madmom installed below if possible)"

echo "Installing crepe (pitch detection for guitar/bass/keys) — needs setuptools<81 to build on Py3.11..."
pip install "setuptools<81" && pip install --no-build-isolation crepe && pip install --upgrade setuptools \
    || echo "WARN: crepe install failed — pipeline will fall back to librosa pyin / basic-pitch"

echo "Patching ctranslate2 to fix execstack crash..."
CT2_LIB=$(find ~/.local/lib /usr/local/lib /opt /usr/lib -type f -name "libctranslate2-*.so*" 2>/dev/null | head -n 1)

if [ -n "$CT2_LIB" ]; then
    patchelf --clear-execstack "$CT2_LIB"
    echo "Successfully patched: $CT2_LIB"
else
    echo "Warning: libctranslate2-*.so* not found. Did the pip install fail?"
fi

echo "Installing .NET SDK for ForgeTool build..."
curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0 --install-dir /tmp/dotnet
export PATH=/tmp/dotnet:$PATH

echo "Building ForgeTool..."
bash tools/build_forgetool.sh

echo "Installing Clone Hero headless playtest harness (box64 + Clone Hero + ALSA-seq shim)..."
bash tools/setup_clone_hero_headless.sh || echo "WARN: Clone Hero harness setup failed (network/restriction) — run tools/setup_clone_hero_headless.sh manually."
